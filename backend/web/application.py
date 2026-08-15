# -*- coding: utf-8 -*-
"""管理控制台应用。

本模块负责 HTTP 路由、管理员会话、配置读写和静态资源分发；注册执行由
``backend.registration`` 与 ``backend.web.jobs`` 提供。
"""
from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import secrets
import time
import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .jobs import job_coordinator
from backend.integrations.proxy import validate_http_proxy_url
from backend.shared.paths import DATA_ROOT, PROJECT_ROOT, STATIC_ROOT

APP_DIR = PROJECT_ROOT
DATA_DIR = DATA_ROOT
STATIC_DIR = STATIC_ROOT
WEB_SESSION_COOKIE = "ps_register_session"
WEB_SESSION_TTL = 60 * 60 * 24 * 7
WEB_AUTH_FILE = DATA_DIR / "web_auth.json"
LEGACY_WEB_AUTH_FILE = APP_DIR / "web_auth.json"
MAX_BATCH_ACCOUNT_IDS = 10000

_resin_monitor = None

CONFIG_PUBLIC_KEYS = (
    "email_provider",
    "duckmail_api_key",
    "duckmail_api_base",
    "defaultDomains",
    "cloudmail_url",
    "cloudmail_admin_email",
    "cloudmail_password",
    "cloudflare_api_base",
    "cloudflare_api_key",
    "cloudflare_auth_mode",
    "cloudflare_custom_auth",
    "cloudflare_path_domains",
    "cloudflare_path_accounts",
    "cloudflare_path_token",
    "cloudflare_path_messages",
    "proxy",
    "debug_mode",
    "browser_headless",
    "browser_locale",
    "close_browser_on_stop",
    "log_level",
    "register_count",
    "register_workers",
    "registration_retry_multiplier",
    "user_agent",
    "mailnest_api_key",
    "mailnest_project_code",
    "yyds_api_key",
    "yyds_jwt",
    "yyds_default_domain",
    "ps_dashboard_base",
    "ps_api_base",
    "ps_signup_url",
    "ps_turnstile_sitekey",
    "ps_password_length",
    "ps_skip_typeform",
    "ps_typeform_form_id",
    "ps_typeform_response_stub",
    "ps_typeform_response_id",
    "ps_proxy_protocol",
    "ps_proxy_format",
    "ps_proxy_list_dir",
    "account_valid_days",
    "resin_base_url",
    "resin_auth_token",
    "resin_cookie",
    "resin_subscriptions_path",
    "resin_timeout",
    "resin_push_retries",
    "resin_verify_tls",
    "resin_proxy_scheme",
    "resin_source_type",
    "resin_update_interval",
    "resin_ephemeral_node_evict_delay",
    "resin_enabled_flag",
    "resin_ephemeral",
    "resin_monitor_enabled",
    "resin_target_count",
    "resin_monitor_interval",
    "resin_delete_expired",
    "resin_incremental_alive_nodes",
    "account_interval",
)

SENSITIVE_HINT_KEYS = {
    "duckmail_api_key",
    "cloudmail_password",
    "cloudflare_api_key",
    "cloudflare_custom_auth",
    "mailnest_api_key",
    "yyds_api_key",
    "yyds_jwt",
    "resin_auth_token",
    "proxy",
}


class AccountIdsBody(BaseModel):
    ids: List[int] = Field(default_factory=list)


class DeleteAccountsBody(AccountIdsBody):
    delete_files: bool = True


class ConfigUpdateBody(BaseModel):
    config: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class StartJobBody(BaseModel):
    count: Optional[int] = None
    workers: Optional[int] = None
    config: Optional[Dict[str, Any]] = None


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""
    confirm_password: str = ""


def _batch_account_ids(ids: List[int]) -> List[int]:
    normalized: List[int] = []
    seen = set()
    for account_id in ids or []:
        if account_id <= 0:
            raise HTTPException(status_code=400, detail="账号 ID 必须是正整数")
        if account_id in seen:
            continue
        seen.add(account_id)
        normalized.append(account_id)
        if len(normalized) > MAX_BATCH_ACCOUNT_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"单次最多操作 {MAX_BATCH_ACCOUNT_IDS} 个账号",
            )
    if not normalized:
        raise HTTPException(status_code=400, detail="请选择要操作的账号")
    return normalized


def _gr():
    from backend.registration import engine as gr

    return gr


def _load_auth_record() -> Dict[str, str] | None:
    for path in (WEB_AUTH_FILE, LEGACY_WEB_AUTH_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("username") and data.get("password_hash"):
            return {str(key): str(value) for key, value in data.items()}
    return None


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000).hex()


def _create_auth_record(username: str, password: str) -> Dict[str, str]:
    salt = secrets.token_bytes(16)
    return {
        "username": username,
        "password_salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "password_hash": _hash_password(password, salt),
        "session_secret": secrets.token_urlsafe(32),
    }


def _save_auth_record(record: Dict[str, str]) -> None:
    WEB_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = WEB_AUTH_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=True, indent=2), encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    os.replace(temporary, WEB_AUTH_FILE)


def _auth_record() -> Dict[str, str] | None:
    return _load_auth_record()


def _web_auth_enabled() -> bool:
    return _auth_record() is not None


def _sign_session(username: str, expires_at: int, secret: str) -> str:
    payload = f"{username}\n{expires_at}".encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _valid_session(value: str) -> bool:
    record = _auth_record()
    username = str((record or {}).get("username") or "")
    secret = str((record or {}).get("session_secret") or "")
    if not username or not secret or not value or "." not in value:
        return False
    encoded, signature = value.split(".", 1)
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        padding = "=" * (-len(encoded) % 4)
        raw_username, raw_expires = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8").split("\n", 1)
        return hmac.compare_digest(raw_username, username) and int(raw_expires) > int(time.time())
    except (ValueError, UnicodeError, base64.binascii.Error):
        return False


def _auth_required_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    return path not in {
        "/api/health",
        "/api/auth/login",
        "/api/auth/setup",
        "/api/auth/me",
        "/api/auth/logout",
    }


def _public_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    gr = _gr()
    for key in CONFIG_PUBLIC_KEYS:
        if key in raw:
            out[key] = raw.get(key)
        elif key in gr.DEFAULT_CONFIG:
            out[key] = gr.DEFAULT_CONFIG.get(key)
    out["_sensitive_keys"] = sorted(SENSITIVE_HINT_KEYS)
    return out


def _config_file_snapshot() -> Dict[str, Any]:
    """读取磁盘上的实际 config.json，并返回适合管理端展示的元数据。"""
    gr = _gr()
    path = Path(gr.CONFIG_FILE).expanduser()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    result: Dict[str, Any] = {
        "path": str(resolved),
        "exists": resolved.is_file(),
        "size": 0,
        "modified_at": "",
        "content": "{}",
        "parse_error": "",
        "sensitive_keys": sorted(SENSITIVE_HINT_KEYS),
    }
    if not resolved.is_file():
        gr.load_config()
        result["content"] = json.dumps(gr.config, ensure_ascii=False, indent=2)
        return result
    try:
        stat = resolved.stat()
        result["size"] = int(stat.st_size)
        result["modified_at"] = datetime.datetime.fromtimestamp(
            stat.st_mtime, tz=datetime.timezone.utc
        ).isoformat().replace("+00:00", "Z")
        if stat.st_size > 2 * 1024 * 1024:
            raise ValueError("config.json 超过 2 MiB")
        raw_text = resolved.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
        result["content"] = json.dumps(parsed, ensure_ascii=False, indent=2)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        result["parse_error"] = str(exc)
        try:
            result["content"] = resolved.read_text(encoding="utf-8")[: 2 * 1024 * 1024]
        except (OSError, UnicodeError):
            result["content"] = ""
    return result


def _apply_config_updates(updates: Dict[str, Any]) -> Dict[str, Any]:
    gr = _gr()
    gr.load_config()
    proxy_update: Optional[str] = None
    if "proxy" in updates:
        proxy_update = str(updates.get("proxy") or "").strip()
        if proxy_update.lower().startswith(("http:", "https:")):
            try:
                proxy_update = validate_http_proxy_url(proxy_update)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"网络代理格式错误: {exc}") from exc
    changed: List[str] = []
    for key in CONFIG_PUBLIC_KEYS:
        if key not in updates:
            continue
        value = updates[key]
        if key in (
            "debug_mode",
            "browser_headless",
            "close_browser_on_stop",
            "ps_skip_typeform",
            "ps_typeform_response_stub",
            "resin_verify_tls",
            "resin_enabled_flag",
            "resin_ephemeral",
            "resin_incremental_alive_nodes",
            "resin_monitor_enabled",
            "resin_delete_expired",
        ):
            value = bool(value)
        elif key in (
            "register_count",
            "register_workers",
            "registration_retry_multiplier",
            "ps_password_length",
            "account_valid_days",
            "resin_timeout",
            "resin_push_retries",
            "resin_target_count",
            "resin_monitor_interval",
        ):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if key == "register_count":
                value = max(1, min(value, 1000))
            elif key == "register_workers":
                value = max(1, min(value, 8))
            elif key == "registration_retry_multiplier":
                value = max(1, min(value, 20))
            elif key == "ps_password_length":
                value = max(10, min(value, 32))
            elif key == "account_valid_days":
                value = max(1, min(value, 365))
            elif key == "resin_timeout":
                value = max(5, min(value, 300))
            elif key == "resin_push_retries":
                value = max(0, min(value, 10))
            elif key == "resin_target_count":
                value = max(0, min(value, 100000))
            elif key == "resin_monitor_interval":
                value = max(30, min(value, 86400))
        elif key == "log_level":
            value = str(value or "info").strip().lower() or "info"
        elif key == "browser_locale":
            value = str(value or "en-US").strip()
            if value not in {"en-US", "zh-CN"}:
                value = "en-US"
        elif key == "email_provider":
            value = str(value or "cloudflare").strip().lower() or "cloudflare"
            if value not in {"cloudflare", "duckmail", "yyds", "mailnest", "cloudmail"}:
                value = "cloudflare"
        elif key == "cloudflare_auth_mode":
            value = str(value or "none").strip().lower()
            if value not in {"none", "bearer", "x-api-key", "x-admin-auth", "query-key"}:
                value = "none"
        elif key in (
            "proxy",
            "duckmail_api_base",
            "cloudflare_api_base",
        ):
            value = proxy_update if key == "proxy" else str(value or "").strip()
        else:
            if isinstance(value, (dict, list)):
                continue
            value = value if isinstance(value, (int, float, bool)) else str(
                value if value is not None else ""
            )
        gr.config[key] = value
        changed.append(key)
    gr.save_config()
    return {"changed": changed, "config": _public_config(gr.config)}


def _serialize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(record or {})
    item["success"] = bool(item.get("success"))
    item["cpa_enabled"] = bool(item.get("cpa_enabled"))
    bfs_text = "" if item.get("bfs") is None else str(item.get("bfs")).strip()
    item["bfs"] = bfs_text
    item["bot_risk"] = bool(item.get("bot_risk")) or bool(bfs_text and bfs_text != "0")
    item["screenshot_url"] = (
        f"/api/accounts/{item.get('id')}/failure-screenshot"
        if str(item.get("screenshot_path") or "").strip()
        else ""
    )
    extra = item.get("extra_json") or "{}"
    if isinstance(extra, str):
        try:
            item["extra"] = json.loads(extra) if extra.strip() else {}
        except Exception:
            item["extra"] = {"raw": extra}
    else:
        item["extra"] = extra
    extra_data = item["extra"] if isinstance(item["extra"], dict) else {}
    item["exception_traceback"] = str(extra_data.get("exception_traceback") or "")
    item["exception_type"] = str(extra_data.get("exception_type") or "")
    item["has_exception_traceback"] = bool(item["exception_traceback"])
    # Resin 状态列可能带完整错误文本（入池失败时记 "failed: <长错误>"），
    # 表格只需要短状态，完整错误单独给 resin_error 字段（详情面板展示）。
    raw_resin = str(item.get("resin_status") or "").strip()
    if raw_resin.startswith("failed:"):
        item["resin_status"] = "failed"
        item["resin_error"] = raw_resin[len("failed:"):].strip()
    elif len(raw_resin) > 40:
        item["resin_status"] = raw_resin[:40]
        item["resin_error"] = raw_resin
    else:
        item["resin_status"] = raw_resin
        item["resin_error"] = ""
    return item


def _path_within(path: Path, roots: List[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def _stream_file(path: Path, chunk_size: int = 65536) -> Iterator[bytes]:
    """按固定块读取文件，让响应在首块就绪后立即进入浏览器下载队列。"""
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def _failure_screenshot_file(record: Dict[str, Any]) -> tuple[Path, str]:
    raw_path = str(record.get("screenshot_path") or "").strip()
    if not raw_path:
        raise FileNotFoundError("该记录没有失败截图")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = APP_DIR / path
    screenshot_roots = [
        DATA_DIR / "screenshots" / "registration-failures",
    ]
    if not _path_within(path, screenshot_roots) or not path.is_file():
        raise FileNotFoundError("失败截图文件不存在")
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_types.get(path.suffix.lower())
    if not media_type:
        raise ValueError("失败截图格式不受支持")
    return path.resolve(), media_type


def _find_account_proxy_file(record: Dict[str, Any]) -> Path:
    """定位账号的代理列表文件；校验在 data/proxy_lists/ 内防穿越。"""
    raw_path = str(record.get("proxy_file") or "").strip()
    if not raw_path:
        raise FileNotFoundError("该记录没有代理列表")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = APP_DIR / path
    proxy_roots = [DATA_DIR / "proxy_lists"]
    if not _path_within(path, proxy_roots) or not path.is_file():
        raise FileNotFoundError("代理列表文件不存在")
    return path.resolve()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ProxyScrape Register Web",
        description="Lightweight console for register / list / manage accounts",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_web_login(request: Request, call_next):
        if _auth_required_path(request.url.path):
            if not _web_auth_enabled():
                return JSONResponse(
                    status_code=401,
                    content={
                        "ok": False,
                        "error": "请先创建管理员账号",
                        "auth_required": True,
                        "setup_required": True,
                    },
                )
            if not _valid_session(request.cookies.get(WEB_SESSION_COOKIE, "")):
                return JSONResponse(
                    status_code=401,
                    content={"ok": False, "error": "请先登录", "auth_required": True},
                )
        return await call_next(request)

    @app.on_event("startup")
    def _startup() -> None:
        gr = _gr()
        gr.load_config()
        gr._wire_runtime_modules()
        try:
            gr.get_registration_repository()
        except Exception as exc:
            print(f"[web] 初始化 SQLite 失败: {exc}", flush=True)
        global _resin_monitor
        try:
            from backend.registration.resin_monitor import ResinMonitor

            _resin_monitor = ResinMonitor(
                coordinator=job_coordinator,
                log=lambda m: print(m, flush=True),
            )
            if bool(gr.config.get("resin_monitor_enabled", False)):
                _resin_monitor.start()
            else:
                print("[web] Resin 监控未启用（resin_monitor_enabled=false）", flush=True)
        except Exception as exc:
            print(f"[web] 初始化 Resin 监控失败: {exc}", flush=True)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        global _resin_monitor
        if _resin_monitor is not None:
            try:
                _resin_monitor.stop()
            except Exception:
                pass
            _resin_monitor = None

    @app.get("/api/health")
    def api_health() -> Dict[str, Any]:
        return {"ok": True, "service": "ps-register-web", "version": "1.0.0"}

    @app.get("/api/auth/me")
    def api_auth_me(request: Request) -> Dict[str, Any]:
        record = _auth_record() or {}
        username = str(record.get("username") or "")
        enabled = _web_auth_enabled()
        authenticated = bool(enabled and _valid_session(request.cookies.get(WEB_SESSION_COOKIE, "")))
        return {
            "ok": True,
            "enabled": enabled,
            "setup_required": not enabled,
            "authenticated": authenticated,
            "username": username if authenticated and enabled else "",
        }

    @app.post("/api/auth/setup")
    def api_auth_setup(body: LoginBody) -> JSONResponse:
        if _auth_record() is not None:
            raise HTTPException(status_code=409, detail="管理员账号已创建")
        username = str(body.username or "").strip()
        password = str(body.password or "")
        confirm = str(body.confirm_password or "")
        if len(username) < 3:
            raise HTTPException(status_code=400, detail="账号至少需要 3 个字符")
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="密码至少需要 8 个字符")
        if password != confirm:
            raise HTTPException(status_code=400, detail="两次输入的密码不一致")
        record = _create_auth_record(username, password)
        try:
            _save_auth_record(record)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"保存管理员账号失败: {exc}") from exc
        response = JSONResponse(
            {"ok": True, "enabled": True, "authenticated": True, "username": username}
        )
        expires_at = int(time.time()) + WEB_SESSION_TTL
        response.set_cookie(
            WEB_SESSION_COOKIE,
            _sign_session(username, expires_at, record["session_secret"]),
            max_age=WEB_SESSION_TTL,
            expires=WEB_SESSION_TTL,
            httponly=True,
            secure=str(os.environ.get("PS_WEB_COOKIE_SECURE", "1")).strip().lower()
            not in {"0", "false", "no", "off"},
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/auth/login")
    def api_auth_login(body: LoginBody) -> JSONResponse:
        record = _auth_record()
        if record is None:
            raise HTTPException(status_code=409, detail="请先创建管理员账号")
        username = record["username"]
        supplied_password = str(body.password or "")
        supplied_user = str(body.username or "")
        try:
            salt = base64.urlsafe_b64decode(record["password_salt"])
        except (ValueError, base64.binascii.Error) as exc:
            raise HTTPException(status_code=500, detail="管理员账号数据损坏") from exc
        valid_password = hmac.compare_digest(
            _hash_password(supplied_password, salt), record["password_hash"]
        )
        if not (hmac.compare_digest(supplied_user, username) and valid_password):
            raise HTTPException(status_code=401, detail="账号或密码错误")
        expires_at = int(time.time()) + WEB_SESSION_TTL
        response = JSONResponse(
            {"ok": True, "enabled": True, "authenticated": True, "username": username}
        )
        response.set_cookie(
            WEB_SESSION_COOKIE,
            _sign_session(username, expires_at, record["session_secret"]),
            max_age=WEB_SESSION_TTL,
            expires=WEB_SESSION_TTL,
            httponly=True,
            secure=str(os.environ.get("PS_WEB_COOKIE_SECURE", "1")).strip().lower()
            not in {"0", "false", "no", "off"},
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/auth/logout")
    def api_auth_logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(WEB_SESSION_COOKIE, path="/")
        return response

    @app.get("/api/stats")
    def api_stats() -> Dict[str, Any]:
        gr = _gr()
        gr.load_config()
        store = gr.get_registration_repository()
        return {"ok": True, "stats": store.stats(), "job": job_coordinator.status()}

    @app.get("/api/accounts")
    def api_accounts(
        status: str = Query(""),
        email_disable_status: str = Query(""),
        include_failed: bool = Query(False),
        q: str = Query(""),
        keyword: str = Query(""),
        batch_id: str = Query(""),
        bot_risk: str = Query(""),
        limit: int = Query(20, ge=1, le=10000),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        gr = _gr()
        store = gr.get_registration_repository()
        status_norm = str(status or "").strip().lower()
        keyword_norm = str(q or keyword or "").strip()
        batch_norm = str(batch_id or "").strip()
        bot_risk_norm = str(bot_risk or "").strip().lower()
        # 默认不显示失败记录；显式 status 筛选或 include_failed=1 时显示
        exclude_failed = status_norm == "" and not include_failed
        rows = store.list_results(
            status=status_norm,
            email_disable_status=str(email_disable_status or "").strip().lower(),
            keyword=keyword_norm,
            batch_id=batch_norm,
            bot_risk=bot_risk_norm,
            exclude_failed=exclude_failed,
            limit=limit,
            offset=offset,
        )
        total = store.count_results(
            status=status_norm,
            email_disable_status=str(email_disable_status or "").strip().lower(),
            keyword=keyword_norm,
            batch_id=batch_norm,
            bot_risk=bot_risk_norm,
            exclude_failed=exclude_failed,
        )
        return {
            "ok": True,
            "total": total,
            "count": len(rows),
            "has_more": offset + len(rows) < total,
            "offset": offset,
            "limit": limit,
            "items": [_serialize_record(row) for row in rows],
        }

    @app.get("/api/accounts/select-ids")
    def api_account_select_ids(
        status: str = Query(""),
        email_disable_status: str = Query(""),
        include_failed: bool = Query(False),
        q: str = Query(""),
        keyword: str = Query(""),
        batch_id: str = Query(""),
        bot_risk: str = Query(""),
    ) -> Dict[str, Any]:
        store = _gr().get_registration_repository()
        status_norm = str(status or "").strip().lower()
        exclude_failed = status_norm == "" and not include_failed
        ids = store.list_result_ids(
            status=status_norm,
            email_disable_status=str(email_disable_status or "").strip().lower(),
            keyword=str(q or keyword or "").strip(),
            batch_id=str(batch_id or "").strip(),
            bot_risk=str(bot_risk or "").strip().lower(),
            exclude_failed=exclude_failed,
        )
        return {"ok": True, "ids": ids, "total": len(ids)}

    @app.get("/api/accounts/{account_id}")
    def api_account_detail(account_id: int) -> Dict[str, Any]:
        gr = _gr()
        store = gr.get_registration_repository()
        rows = store.get_results_by_ids([account_id])
        if not rows:
            raise HTTPException(status_code=404, detail="记录不存在")
        return {"ok": True, "item": _serialize_record(rows[0])}

    @app.get("/api/accounts/{account_id}/failure-screenshot")
    def api_account_failure_screenshot(account_id: int) -> FileResponse:
        gr = _gr()
        rows = gr.get_registration_repository().get_results_by_ids([account_id])
        if not rows:
            raise HTTPException(status_code=404, detail="记录不存在")
        try:
            path, media_type = _failure_screenshot_file(rows[0])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(path, media_type=media_type, content_disposition_type="inline")

    @app.get("/api/accounts/{account_id}/proxy-list")
    def api_account_proxy_list(account_id: int) -> FileResponse:
        """返回账号的 ProxyScrape 代理列表文件。"""
        gr = _gr()
        rows = gr.get_registration_repository().get_results_by_ids([account_id])
        if not rows:
            raise HTTPException(status_code=404, detail="记录不存在")
        try:
            path = _find_account_proxy_file(rows[0])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            path,
            media_type="text/plain",
            filename=path.name,
            content_disposition_type="attachment",
        )

    @app.post("/api/accounts/delete")
    def api_accounts_delete(body: DeleteAccountsBody) -> Dict[str, Any]:
        gr = _gr()
        ids = _batch_account_ids(body.ids)

        from backend.registration.artifacts import (
            cleanup_side_files_for_emails,
            collect_related_file_paths,
            delete_related_files,
        )

        store = gr.get_registration_repository()
        records = store.get_results_by_ids(ids)
        if not records:
            raise HTTPException(status_code=404, detail="没有匹配的记录")

        file_paths: List[str] = []
        seen = set()
        if body.delete_files:
            for record in records:
                for path in collect_related_file_paths(
                    record,
                    accounts_dir=gr.ACCOUNTS_DIR,
                    app_dir=gr.DATA_DIR,
                ):
                    if path in seen:
                        continue
                    seen.add(path)
                    file_paths.append(path)

        deleted_records = store.delete_results([row.get("id") for row in records])
        deleted_files: List[str] = []
        file_errors: List[str] = []
        side_lines = 0
        if body.delete_files:
            deleted_files, file_errors = delete_related_files(file_paths)
            side_cleanup = cleanup_side_files_for_emails(
                gr.ACCOUNTS_DIR,
                [str(item.get("email") or "") for item in deleted_records],
            )
            side_lines = sum(side_cleanup.values())

        return {
            "ok": True,
            "deleted": len(deleted_records),
            "deleted_files": len(deleted_files),
            "side_lines": side_lines,
            "file_errors": file_errors[:20],
        }

    @app.get("/api/config")
    def api_config_get() -> Dict[str, Any]:
        gr = _gr()
        gr.load_config()
        return {"ok": True, "config": _public_config(gr.config)}

    @app.get("/api/config/file")
    def api_config_file_get() -> Dict[str, Any]:
        return {"ok": True, "file": _config_file_snapshot()}

    @app.put("/api/config")
    @app.post("/api/config")
    async def api_config_put(request: Request) -> Dict[str, Any]:
        if job_coordinator.status().get("running"):
            raise HTTPException(status_code=409, detail="注册任务运行中，暂不可修改配置")
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="无效的配置 JSON")
        updates = payload.get("config") if isinstance(payload.get("config"), dict) else payload
        result = _apply_config_updates(updates)
        return {"ok": True, **result}

    @app.get("/api/job")
    def api_job_status() -> Dict[str, Any]:
        return {"ok": True, "job": job_coordinator.status()}

    @app.get("/api/resin-monitor")
    def api_resin_monitor_status() -> Dict[str, Any]:
        global _resin_monitor
        if _resin_monitor is None:
            return {
                "ok": True,
                "monitor": {
                    "enabled": bool(_gr().config.get("resin_monitor_enabled", False)),
                    "running": False,
                    "summary": "监控未初始化",
                    "logs": [],
                },
            }
        return {"ok": True, "monitor": _resin_monitor.status()}

    @app.post("/api/resin-monitor/check")
    def api_resin_monitor_check() -> Dict[str, Any]:
        global _resin_monitor
        if _resin_monitor is None:
            raise HTTPException(status_code=409, detail="Resin 监控未初始化（Web 服务启动后可用）")
        gr = _gr()
        gr.load_config()
        result = _resin_monitor.check_once()
        return {"ok": True, "result": result, "monitor": _resin_monitor.status()}

    @app.get("/api/job/logs")
    def api_job_logs(
        after_id: int = Query(0, ge=0),
        limit: int = Query(500, ge=1, le=2000),
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "logs": job_coordinator.get_logs(after_id=after_id, limit=limit),
            "job": job_coordinator.status(),
        }

    @app.post("/api/job/start")
    def api_job_start(body: StartJobBody) -> Dict[str, Any]:
        gr = _gr()
        gr.load_config()
        if body.config:
            _apply_config_updates(body.config)
            gr.load_config()

        count = body.count if body.count is not None else gr.config.get("register_count", 1)
        workers = body.workers if body.workers is not None else gr.config.get("register_workers", 1)
        try:
            count_i = int(count)
            workers_i = int(workers)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="count / workers 必须是整数")

        try:
            status = job_coordinator.start(count=count_i, workers=workers_i)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"启动失败: {exc}",
            ) from exc
        return {"ok": True, "job": status}

    @app.post("/api/job/stop")
    def api_job_stop() -> Dict[str, Any]:
        try:
            status = job_coordinator.stop()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"停止失败: {exc}") from exc
        return {"ok": True, "job": status}

    @app.post("/api/browser/kill-all")
    def api_browser_kill_all() -> Dict[str, Any]:
        gr = _gr()
        gr._bs.block_browser_launches()
        if job_coordinator.status().get("running"):
            try:
                job_coordinator.request_stop()
            except Exception:
                pass
        try:
            result = gr._bs.kill_all_camoufox_processes(log_callback=job_coordinator._append_log)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"终止浏览器失败: {exc}") from exc
        return {"ok": True, **result, "job": job_coordinator.status()}

    @app.api_route("/api/connectivity", methods=["GET", "POST"])
    def api_connectivity() -> Dict[str, Any]:
        gr = _gr()
        gr.load_config()
        gr._wire_runtime_modules()
        try:
            checks = gr._conn.run_connectivity_checks(gr.config, gr.http_get, gr.http_post)
            items = [
                {"name": name, "ok": bool(ok), "detail": str(detail)}
                for name, ok, detail in checks
            ]
            blocked = bool(gr._conn.has_blocking_ps_failure(checks))
            return {"ok": True, "items": items, "blocked": blocked}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"连通性检查失败: {exc}") from exc

    # ---- static SPA ----
    if (STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=503,
                detail="Web UI 未构建。请在 front/ 执行 npm install && npm run build。",
            )
        return FileResponse(index)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=503, detail="Web UI 未构建")

    return app


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    import uvicorn

    print("[web] ProxyScrape Register Web UI -> http://{host}:{port}", flush=True)
    print(f"[web] API docs -> http://{host}:{port}/api/docs", flush=True)
    uvicorn.run(
        "backend.web.application:create_app",
        factory=True,
        host=host,
        port=int(port),
        log_level="warning",
        access_log=False,
        workers=1,
    )


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="ProxyScrape Register Web Console (FastAPI)")
    parser.add_argument("--host", default=os.environ.get("PS_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PS_WEB_PORT", "8787")))
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
