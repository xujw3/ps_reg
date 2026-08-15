#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""账号注册编排引擎。

组合邮箱渠道、浏览器流程、授权交换、结果持久化与任务取消机制，提供 Web 后台
调用的批量注册入口。
"""

import threading
import datetime
import time
import os
import gc
import secrets
import struct
import random
import re
import string
import json
import base64
import traceback
from pathlib import Path
from urllib.parse import urlsplit

from playwright._impl._errors import TargetClosedError as PageDisconnectedError
from curl_cffi import requests

from backend.mailbox import cloudflare_worker as cloudflare_provider
from backend.mailbox import cloud_mail as cloudmail_provider
from backend.mailbox import duck_mail as duckmail_provider
from backend.mailbox import mail_nest as mailnest_provider
from backend.mailbox import yyds_mail as yyds_provider
from backend.mailbox.utilities import extract_verification_code as _extract_code
from backend.mailbox.utilities import generate_username as _generate_username
from backend.mailbox.utilities import pick_list_payload as _pick_list

from backend.automation import session as _bs
from backend.registration import signup_flow as _rf
from backend.registration import ps_signup_flow as _psf
from backend.integrations import network_checks as _conn
from backend.integrations import ps_api as _ps_api
from backend.integrations import ps_resin as _ps_resin
from backend.registration.store import RegistrationRepository
from backend.integrations.proxy import redact_proxy_text, redact_proxy_url, resolve_proxy_url
from backend.shared.paths import DATA_ROOT, PROJECT_ROOT
from backend.automation.session import (
    browser,
    page,
    active_browser as _active_browser,
    active_page as _active_page,
    set_browser_session as _set_browser_session,
    start_browser,
    stop_browser,
    restart_browser,
    cleanup_runtime_memory,
    refresh_active_page,
    create_browser_options,
    get_start_fail_streak,
    cleanup_stale_profiles as _cleanup_stale_profiles,
)
from backend.registration.signup_flow import (
    detect_email_domain_rejection,
    raise_if_email_domain_rejected,
    getTurnstileToken,
)



APP_DIR = str(PROJECT_ROOT)
DATA_DIR = str(DATA_ROOT)
CONFIG_FILE = os.path.abspath(
    os.path.expanduser(os.environ.get("PS_CONFIG_FILE", os.path.join(APP_DIR, "config.json")))
)
# 所有注册运行数据统一放入 data/，避免与前后端代码混放。
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
RESULTS_DB_FILE = os.path.join(ACCOUNTS_DIR, "registration_results.sqlite3")
MEMORY_CLEANUP_INTERVAL = 5
TRACEBACK_MAX_CHARS = 60_000
TRACEBACK_LOG_MAX_CHARS = 16_000

_repository = None
_repository_lock = threading.Lock()
_network_route_log_lock = threading.Lock()
_network_route_log_keys = set()


def current_exception_traceback(max_chars=TRACEBACK_MAX_CHARS):
    """返回当前异常的标准堆栈；没有活动异常时返回空字符串。"""
    text = traceback.format_exc().strip()
    if not text or text == "NoneType: None":
        return ""

    limit = max(1_000, int(max_chars or TRACEBACK_MAX_CHARS))
    if len(text) > limit:
        tail_size = min(4_000, limit // 4)
        text = (
            text[: limit - tail_size]
            + "\n... 异常堆栈过长，已截断 ...\n"
            + text[-tail_size:]
        )
    return text


def ensure_accounts_dir():
    """确保 data/accounts/ 存在，返回目录绝对路径。"""
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    return ACCOUNTS_DIR


def account_file_for_email(email):
    """单个账号的独立输出路径：data/accounts/{email}.txt"""
    ensure_accounts_dir()
    safe_email = str(email or "").strip().replace("/", "_").replace("\\", "_")
    return os.path.join(ACCOUNTS_DIR, f"{safe_email}.txt")


def accounts_side_file(name):
    """data/accounts/ 下的附属文件路径（mail_credentials 等）。"""
    ensure_accounts_dir()
    return os.path.join(ACCOUNTS_DIR, name)


_accounts_txt_lock = threading.Lock()


def save_account_record(*, email, password="", created_at="", expire_at="") -> str:
    """把账号追加写入 data/accounts/accounts.txt（统一汇总文件）。

    行格式与 proxyscrape_reg 一致：email----password----created_at----expire_at。
    多线程安全：跨 worker 并发注册共用同一汇总文件。
    """
    email = str(email or "").strip()
    if not email:
        raise ValueError("save_account_record 需要 email")
    if not created_at:
        created_at = datetime.datetime.now().isoformat(timespec="seconds")
    if not expire_at:
        try:
            days = max(1, int(config.get("account_valid_days") or 7))
        except (TypeError, ValueError):
            days = 7
        try:
            created_dt = datetime.datetime.fromisoformat(created_at)
        except ValueError:
            created_dt = datetime.datetime.now()
        expire_at = (created_dt + datetime.timedelta(days=days)).isoformat(timespec="seconds")
    line = f"{email}----{password}----{created_at}----{expire_at}\n"
    target = accounts_side_file("accounts.txt")
    with _accounts_txt_lock:
        with open(target, "a", encoding="utf-8") as f:
            f.write(line)
    return target


def get_registration_repository():
    """懒加载 SQLite；首次启动时把旧账号 TXT 补录为成功结果。"""
    global _repository
    if _repository is not None:
        return _repository
    with _repository_lock:
        if _repository is None:
            store = RegistrationRepository(RESULTS_DB_FILE)
            store.import_existing_accounts(ACCOUNTS_DIR)
            _repository = store
    return _repository


def email_registered_successfully(email):
    """数据库或旧账号文件中已有成功/已消耗记录时返回 True。

    除正式 success 外，已保存 SSO、已判定 already_registered / registration_risk /
    sso_timeout，或已尝试停用的 Outlook 邮箱也应跳过，避免邮箱池重复取用造成死循环。
    """
    normalized = str(email or "").strip()
    if not normalized:
        return False
    try:
        repo = get_registration_repository()
        if repo.has_success(normalized):
            return True
        if hasattr(repo, "has_registered_or_consumed") and repo.has_registered_or_consumed(normalized):
            return True
    except Exception:
        pass
    return os.path.isfile(account_file_for_email(normalized))


def _environment_int(name, default):
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return int(default)


def _environment_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_CONFIG = {
    "email_provider": "cloudflare",
    "duckmail_api_key": "",
    "duckmail_api_base": "https://api.duckmail.sbs",
    "defaultDomains": "",
    "cloudmail_url": "",
    "cloudmail_admin_email": "",
    "cloudmail_password": "",
    "cloudflare_api_base": "",
    "cloudflare_api_key": "",
    "cloudflare_auth_mode": "none",
    "cloudflare_custom_auth": "",
    "cloudflare_path_domains": "/api/domains",
    "cloudflare_path_accounts": "/admin/new_address",
    "cloudflare_path_token": "/api/token",
    "cloudflare_path_messages": "/api/mails",
    "proxy": "http://127.0.0.1:7890",
    "debug_mode": False,
    "browser_headless": False,
    "browser_locale": "en-US",
    "close_browser_on_stop": False,
    "log_level": "info",
    "register_count": 1,
    "register_workers": 1,
    "registration_retry_multiplier": 3,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "mailnest_api_key": "",
    "mailnest_project_code": "x-ai001",
    # YYDS：留空自动选已验证域名；填写则固定该域名
    "yyds_default_domain": "",
    # ProxyScrape 注册：dashboard 与 API 地址
    "ps_dashboard_base": "https://dashboard.proxyscrape.com/v2",
    "ps_api_base": "",
    "ps_signup_url": "",
    "ps_turnstile_sitekey": "0x4AAAAAAAFWUVCKyusT9T8r",
    "ps_password_length": 14,
    "ps_skip_typeform": True,
    "ps_typeform_form_id": "vnCgUn0n",
    "ps_typeform_response_stub": True,
    "ps_typeform_response_id": "",
    "ps_proxy_protocol": "http",
    "ps_proxy_format": "userpass",
    # 代理列表输出目录（相对项目根）
    "ps_proxy_list_dir": "data/proxy_lists",
    # 账号有效天数（决定 expire_at 写入）
    "account_valid_days": 7,
    # Resin 入池（可选）
    "resin_base_url": "",
    "resin_auth_token": "",
    "resin_cookie": "",
    "resin_subscriptions_path": "/api/v1/subscriptions",
    "resin_timeout": 30,
    "resin_push_retries": 2,
    "resin_expiring_soon_hours": 24,
    "resin_delete_proxy_files": True,
    "resin_remove_expired_records": False,
    "resin_verify_tls": False,
    "resin_proxy_scheme": "http",
    "resin_source_type": "local",
    "resin_update_interval": "12h",
    "resin_ephemeral_node_evict_delay": "72h",
    "resin_enabled_flag": True,
    "resin_ephemeral": False,
    "resin_monitor_enabled": False,
    "resin_target_count": 0,
    "resin_monitor_interval": 600,
    "resin_topup_lead_hours": 12,
    "resin_delete_expired": True,
    "resin_incremental_alive_nodes": False,
    # 账号间注册间隔（秒），0=不等待。填一个整数=N秒固定等待，填区间"60-120"=随机等待
    "account_interval": "60-120",
}

config = DEFAULT_CONFIG.copy()
_cf_domain_index = 0


class RegistrationCancelled(Exception):
    pass


class AccountRetryNeeded(Exception):
    pass


class EmailDomainRejected(Exception):
    """xAI 拒绝当前邮箱域名（如公共临时域被拉黑）。"""

    def __init__(self, email="", message=""):
        self.email = email or ""
        self.message = message or "邮箱域名已被拒绝"
        domain = ""
        if "@" in self.email:
            domain = self.email.split("@", 1)[1]
        detail = self.message
        if domain and domain not in detail:
            detail = f"{detail}（域名: {domain}）"
        if self.email and self.email not in detail:
            detail = f"{detail} | 邮箱: {self.email}"
        super().__init__(detail)


FAIL_DOMAIN = "domain_rejected"
FAIL_ALREADY_REGISTERED = "already_registered"
FAIL_CODE = "code_timeout"
FAIL_BROWSER = "browser"
FAIL_PS_FORM = "ps_form"
FAIL_PS_REGISTER = "ps_register"
FAIL_PS_VERIFY = "ps_verify"
FAIL_PS_PROXY = "ps_proxy"
FAIL_OTHER = "other"

FAIL_LABELS = {
    FAIL_DOMAIN: "域名拒绝",
    FAIL_ALREADY_REGISTERED: "账号已注册",
    FAIL_CODE: "验证码超时",
    FAIL_BROWSER: "浏览器断开",
    FAIL_PS_FORM: "表单/Turnstile",
    FAIL_PS_REGISTER: "注册API",
    FAIL_PS_VERIFY: "验证邮箱",
    FAIL_PS_PROXY: "代理列表",
    FAIL_OTHER: "其它",
}


def classify_failure(exc) -> str:
    if isinstance(exc, EmailDomainRejected):
        return FAIL_DOMAIN
    if isinstance(exc, _rf.AccountAlreadyRegistered):
        return FAIL_ALREADY_REGISTERED
    msg = str(exc or "")
    low = msg.lower()
    if "未收到验证码" in msg or "验证码阶段失败" in msg or "验证码" in msg and "失败" in msg:
        return FAIL_CODE
    if (
        "浏览器" in msg
        or "page disconnected" in low
        or "与页面的连接已断开" in msg
        or "PageDisconnected" in msg
        or "disconnected" in low
    ):
        return FAIL_BROWSER
    if "表单" in msg or "turnstile" in low or "提交注册" in msg:
        return FAIL_PS_FORM
    if "注册接口" in msg or "注册API" in msg or "register" in low and "失败" in msg:
        return FAIL_PS_REGISTER
    if "验证邮箱" in msg or "verify-email" in low or "typeform" in low:
        return FAIL_PS_VERIFY
    if "代理列表" in msg or "proxy-list" in low:
        return FAIL_PS_PROXY
    return FAIL_OTHER


def empty_fail_stats():
    return {k: 0 for k in FAIL_LABELS}


def format_fail_stats(stats: dict) -> str:
    parts = [f"{FAIL_LABELS.get(k, k)}={stats.get(k, 0)}" for k in FAIL_LABELS if stats.get(k, 0)]
    if not parts:
        return "无分类失败"
    return " | ".join(parts)


def new_registration_batch_id(source="web"):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{source}-{stamp}-{secrets.token_hex(3)}"


def current_attempt_email(email="", exc=None):
    return str(
        getattr(exc, "email", "")
        or email
        or _rf.last_acquired_email()
        or ""
    ).strip()


def current_attempt_password(profile=None):
    current = dict(profile or {})
    if current.get("password"):
        return str(current.get("password") or "")
    return str(_rf.last_profile().get("password") or "")


def capture_failure_screenshot(
    *,
    batch_id="",
    worker_id=0,
    email="",
    failure_type="",
    log_callback=None,
):
    """保存当前活动页面；页面不存在或已经断开时返回空路径。"""
    current_page = _active_page()
    if current_page is None:
        return ""

    def _safe_part(value, fallback):
        normalized = re.sub(r"[^A-Za-z0-9._@-]+", "_", str(value or "").strip())
        return normalized.strip("._-")[:80] or fallback

    folder = os.path.join(DATA_DIR, "screenshots", "registration-failures")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = "-".join(
        (
            _safe_part(batch_id, "batch"),
            f"w{max(int(worker_id or 0), 0) + 1}",
            _safe_part(email, "unknown"),
            _safe_part(failure_type, "failure"),
            stamp,
            secrets.token_hex(2),
        )
    ) + ".png"
    path = os.path.abspath(os.path.join(folder, filename))
    try:
        os.makedirs(folder, exist_ok=True)
        current_page.screenshot(path=path, full_page=True)
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            return ""
        if log_callback:
            log_callback(f"[截图] 浏览器失败现场已保存: {path}")
        return path
    except Exception as exc:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
        if log_callback:
            log_callback(f"[Debug] 浏览器失败截图保存失败: {exc}")
        return ""


def default_email_disable_detail(provider="", ps_detail=None) -> dict:
    # Outlook 渠道已移除；email_disable 状态对现有渠道不适用，保留列兼容。
    return {
        "status": "not_applicable",
        "account_id": "",
        "disabled_at": "",
        "error": "",
    }


def persist_registration_result(
    *,
    batch_id,
    source,
    started_at,
    email="",
    password="",
    status="failure",
    provider="",
    worker_id=0,
    ps_detail=None,
    email_disable_detail=None,
    failure_type="",
    failure_reason="",
    screenshot_path="",
    account_file="",
    extra=None,
    log_callback=None,
):
    """统一保存 Web 注册结果；写库异常不打断注册流程。"""
    finished_epoch = time.time()
    try:
        started_epoch = float(started_at or finished_epoch)
    except (TypeError, ValueError):
        started_epoch = finished_epoch
    started_text = datetime.datetime.fromtimestamp(started_epoch).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    finished_text = datetime.datetime.fromtimestamp(finished_epoch).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    detail = dict(ps_detail or {})
    provider_name = provider or str(config.get("email_provider", "") or "")
    ps_status = str(detail.get("status") or "not_attempted")
    auth_info = detail.get("auth_info", "")
    if isinstance(auth_info, (list, tuple, set)):
        auth_info = "\n".join(str(item) for item in auth_info if str(item).strip())
    extra_data = dict(extra or {})
    if detail.get("error"):
        extra_data["ps_error"] = str(detail.get("error"))
    disable_detail = default_email_disable_detail(provider_name, detail)
    disable_detail.update(dict(email_disable_detail or {}))
    try:
        repository = get_registration_repository()
        registration_id = repository.add_result(
            {
                "batch_id": batch_id,
                "source": source,
                "started_at": started_text,
                "finished_at": finished_text,
                "duration_seconds": max(finished_epoch - started_epoch, 0),
                "email": email,
                "password": password,
                "status": status,
                "success": status == "success",
                "provider": provider_name,
                "worker_id": worker_id,
                "cpa_enabled": 1,
                "cpa_status": ps_status,
                "auth_info": auth_info,
                "auth_path": "",
                "cpa_auth_path": "",
                "cpa_remote_status": "not_configured",
                "cpa_remote_imported_at": "",
                "cpa_remote_error": "",
                "sub2api_remote_status": "disabled",
                "sub2api_remote_imported_at": "",
                "sub2api_remote_error": "",
                "email_account_id": disable_detail.get("account_id", ""),
                "email_disable_status": disable_detail.get("status", "not_attempted"),
                "email_disabled_at": disable_detail.get("disabled_at", ""),
                "email_disable_error": disable_detail.get("error", ""),
                "failure_type": failure_type,
                "failure_reason": str(failure_reason or ""),
                "screenshot_path": screenshot_path,
                "account_file": account_file,
                "sso_saved": 0,
                "nsfw_status": "",
                "bot_risk": 0,
                "bfs": "",
                # ProxyScrape 账号字段（Task 10 落库）
                "access_token": str(detail.get("access_token") or ""),
                "account_id": str(detail.get("account_id") or ""),
                "expire_at": str(detail.get("expire_at") or ""),
                "proxy_file": str(detail.get("proxy_file") or ""),
                "resin_status": str(detail.get("resin_status") or "skipped"),
                "extra": extra_data,
            }
        )
        return registration_id
    except Exception as exc:
        if log_callback:
            log_callback(f"[!] SQLite 保存注册结果失败: {exc}")
        return None


def ps_detail_succeeded(ps_detail=None) -> bool:
    """access_token + account_id 非空且 error 空。"""
    detail = dict(ps_detail or {})
    return bool(
        str(detail.get("access_token") or "").strip()
        and str(detail.get("account_id") or "").strip()
        and not str(detail.get("error") or "").strip()
    )


def ps_failure_reason_detail(ps_detail=None) -> str:
    detail = dict(ps_detail or {})
    return str(
        detail.get("error")
        or detail.get("message")
        or ps_api.ps_failure_reason(detail)
        or ""
    ).strip()


def save_proxy_list_file(email: str, proxies, log_callback=None) -> str:
    """把代理行写入 data/proxy_lists/{email}.http.txt（原子写）。"""
    proxy_dir = str(config.get("ps_proxy_list_dir") or "data/proxy_lists").strip()
    root = Path(proxy_dir).expanduser()
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._@-]+", "_", str(email or "unknown").strip()) or "unknown"
    target = root / f"{safe}.http.txt"
    text = "\n".join(str(line).strip() for line in (proxies or []) if str(line).strip())
    if not text:
        raise Exception(f"代理列表为空，无法写入文件: {target}")
    tmp = target.with_suffix(".http.txt.tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, target)
    if log_callback:
        log_callback(f"[*] 代理列表已保存: {target} ({len(text.splitlines())} 行)")
    return str(target)


def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            config = {**DEFAULT_CONFIG, **loaded}
        except Exception:
            config = DEFAULT_CONFIG.copy()
    return config


def parse_account_interval() -> float:
    """解析 account_interval 配置，返回等待秒数。

    "0" / "" → 0（不等待）
    "30" → 30.0（固定 30 秒）
    "60-120" → 60~120 之间的随机值
    """
    raw = str(config.get("account_interval", "0") or "0").strip()
    if not raw or raw == "0":
        return 0.0
    if "-" in raw:
        parts = raw.split("-", 1)
        try:
            lo = max(int(parts[0].strip()), 0)
            hi = max(int(parts[1].strip()), lo)
            return float(random.randint(lo, hi))
        except (ValueError, IndexError):
            return 0.0
    try:
        return float(int(raw))
    except ValueError:
        return 0.0


def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"保存配置失败: {e}")


load_config()

# turnstilePatch 是 Chrome 扩展，Camoufox 基于 Firefox 不兼容，已移除。
# Turnstile 交互由 signup_flow.getTurnstileToken 统一处理。
EXTENSION_PATH = ""


DUCKMAIL_API_BASE_DEFAULT = duckmail_provider.API_BASE_DEFAULT


def get_proxies():
    proxy = resolve_proxy_url(config.get("proxy", ""))
    if proxy:
        return {"http": proxy, "https": proxy}
    return {}


def reset_network_route_logs():
    with _network_route_log_lock:
        _network_route_log_keys.clear()


def _log_actual_http_route(method, url, *, proxies=None, proxy=""):
    """记录实际请求的接口和路由；相同方法/接口/路由只记录一次。"""
    parsed = urlsplit(str(url or ""))
    display_url = (
        f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"
        if parsed.netloc
        else str(url or "")
    )
    proxy_value = str(proxy or "").strip()
    if not proxy_value and isinstance(proxies, dict):
        proxy_value = str(
            proxies.get(parsed.scheme)
            or proxies.get("all")
            or proxies.get("https")
            or proxies.get("http")
            or ""
        ).strip()
    route = f"代理 {redact_proxy_url(proxy_value)}" if proxy_value else "直连（不使用代理）"
    key = (str(method or "GET").upper(), display_url, route)
    with _network_route_log_lock:
        if key in _network_route_log_keys:
            return
        _network_route_log_keys.add(key)
    registration_log(f"[*] [网络] {key[0]} {display_url} -> {route}")


def get_duckmail_api_base():
    return duckmail_provider.normalize_base(str(config.get("duckmail_api_base", "") or ""))


def get_duckmail_api_key():
    return config.get("duckmail_api_key", "")



def get_cloudflare_api_base():
    return str(config.get("cloudflare_api_base", "") or "").rstrip("/")


def get_cloudflare_api_key():
    return config.get("cloudflare_api_key", "")


def get_cloudflare_auth_mode():
    return str(config.get("cloudflare_auth_mode", "none") or "none").lower()


def get_cloudflare_custom_auth():
    """全局访问密码（cloudflare_temp_email 的 PASSWORDS）。"""
    return str(config.get("cloudflare_custom_auth", "") or "").strip()


def cloudflare_apply_custom_auth(headers):
    return cloudflare_provider.apply_custom_auth(headers, get_cloudflare_custom_auth())


def get_cloudflare_path(key, default_path):
    return cloudflare_provider.path_from_config(config, key, default_path)


def cloudflare_build_headers(content_type=False):
    return cloudflare_provider.build_headers(
        get_cloudflare_api_key(),
        get_cloudflare_auth_mode(),
        get_cloudflare_custom_auth(),
        content_type=content_type,
    )


def cloudflare_apply_auth_params(params=None):
    return cloudflare_provider.apply_auth_params(
        params, get_cloudflare_api_key(), get_cloudflare_auth_mode()
    )


def cloudflare_next_default_domain():
    global _cf_domain_index
    domains = [x.strip() for x in str(config.get("defaultDomains", "") or "").split(",") if x.strip()]
    domain, _cf_domain_index = cloudflare_provider.next_default_domain(domains, _cf_domain_index)
    return domain


def cloudflare_is_admin_create_path(path):
    return cloudflare_provider.is_admin_create_path(path)


def _pick_list_payload(data):
    return _pick_list(data)


def cloudflare_create_temp_address(api_base):
    return cloudflare_provider.create_temp_address(
        http_post,
        api_base,
        accounts_path=get_cloudflare_path("cloudflare_path_accounts", "/admin/new_address"),
        domain=cloudflare_next_default_domain(),
        api_key=get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
        name=generate_username(10),
    )


MAILNEST_API_BASE = mailnest_provider.API_BASE
MAILNEST_DEFAULT_PROJECT_CODE = mailnest_provider.DEFAULT_PROJECT_CODE


def get_mailnest_api_key():
    key = str(config.get("mailnest_api_key", "") or "").strip()
    if not key:
        raise Exception(f"请在配置文件中配置 mailnest_api_key | 注册网址：{MAILNEST_API_BASE}")
    return key


def get_mailnest_project_code():
    code = str(config.get("mailnest_project_code", "") or "").strip()
    return code or MAILNEST_DEFAULT_PROJECT_CODE


def mailnest_buy_email():
    return mailnest_provider.buy_email(http_post, get_mailnest_api_key(), get_mailnest_project_code())


def mailnest_receive_email(email):
    return mailnest_provider.receive_email(http_post, get_mailnest_api_key(), email)


def mailnest_get_code(email, timeout=180, poll_interval=3, log_callback=None, cancel_callback=None):
    return mailnest_provider.wait_for_code(
        http_post,
        get_mailnest_api_key(),
        email,
        timeout=timeout,
        poll_interval=poll_interval,
        raise_if_cancelled=raise_if_cancelled,
        sleep_with_cancel=sleep_with_cancel,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )


def get_user_agent():
    return config.get(
        "user_agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    )


def _build_request_kwargs(**kwargs):
    request_kwargs = dict(kwargs)
    proxies = request_kwargs.pop("proxies", None)
    # 通用 HTTP 默认直连。只有 ProxyScrape 调用方可以显式传入 get_proxies()。
    request_kwargs["proxies"] = proxies or {}
    request_kwargs.setdefault("timeout", 15)
    return request_kwargs


def _http_request(method, url, **kwargs):
    kwargs.pop("_allow_direct_fallback", None)
    with direct_http_session() as session:
        return session.request(method, url, **_build_request_kwargs(**kwargs))


def http_get(url, **kwargs):
    return _http_request("GET", url, **kwargs)


def http_post(url, **kwargs):
    return _http_request("POST", url, **kwargs)


def http_delete(url, **kwargs):
    return _http_request("DELETE", url, **kwargs)


def direct_http_session():
    """创建不读取项目代理或环境代理的 HTTP 会话。"""
    session = requests.Session(trust_env=False)
    raw_request = session.request

    def logged_request(method, url, *args, **kwargs):
        _log_actual_http_route(
            method,
            url,
            proxies=kwargs.get("proxies"),
            proxy=kwargs.get("proxy", ""),
        )
        return raw_request(method, url, *args, **kwargs)

    session.request = logged_request
    return session


def raise_if_cancelled(cancel_callback=None):
    if cancel_callback and cancel_callback():
        raise RegistrationCancelled("用户停止注册")


def sleep_with_cancel(seconds, cancel_callback=None):
    deadline = time.time() + max(seconds, 0)
    while True:
        raise_if_cancelled(cancel_callback)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def get_domains(api_key=None):
    return duckmail_provider.get_domains(
        http_get,
        get_duckmail_api_base(),
        api_key=api_key or get_duckmail_api_key(),
    )


def create_account(address, password, api_key=None, expires_in=0):
    return duckmail_provider.create_account(
        http_post,
        get_duckmail_api_base(),
        address,
        password,
        api_key=api_key or get_duckmail_api_key(),
        expires_in=expires_in,
    )


def get_token(address, password):
    return duckmail_provider.get_token(
        http_post,
        get_duckmail_api_base(),
        address,
        password,
    )


def get_messages(token):
    return duckmail_provider.get_messages(
        http_get,
        get_duckmail_api_base(),
        token,
    )


def get_message_detail(token, message_id):
    return duckmail_provider.get_message_detail(
        http_get,
        get_duckmail_api_base(),
        token,
        message_id,
    )



def cloudflare_get_domains(api_base, api_key=None):
    return cloudflare_provider.get_domains(
        http_get,
        api_base,
        domains_path=get_cloudflare_path("cloudflare_path_domains", "/domains"),
        api_key=api_key or get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
    )


def cloudflare_create_account(api_base, address, password, api_key=None, expires_in=0):
    return cloudflare_provider.create_account(
        http_post,
        api_base,
        address,
        password,
        accounts_path=get_cloudflare_path("cloudflare_path_accounts", "/accounts"),
        api_key=api_key or get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
        expires_in=expires_in,
    )


def cloudflare_get_token(api_base, address, password, api_key=None):
    return cloudflare_provider.get_token(
        http_post,
        api_base,
        address,
        password,
        token_path=get_cloudflare_path("cloudflare_path_token", "/token"),
        api_key=api_key or get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
    )


def cloudflare_get_messages(api_base, token):
    return cloudflare_provider.get_messages(
        http_get,
        api_base,
        token,
        messages_path=get_cloudflare_path("cloudflare_path_messages", "/messages"),
        api_key=get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
    )


def cloudflare_get_message_detail(api_base, token, message_id):
    return cloudflare_provider.get_message_detail(
        http_get,
        api_base,
        token,
        message_id,
        messages_path=get_cloudflare_path("cloudflare_path_messages", "/messages"),
        api_key=get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
    )


YYDS_API_BASE = yyds_provider.API_BASE


def get_yyds_api_key():
    return config.get("yyds_api_key", "")


def get_yyds_jwt():
    return config.get("yyds_jwt", "")


def get_yyds_default_domain():
    return str(config.get("yyds_default_domain", "") or "").strip()


def yyds_get_domains(api_key=None, jwt=None):
    return yyds_provider.get_domains(http_get, api_key=api_key or get_yyds_api_key(), jwt=jwt or get_yyds_jwt())


def yyds_create_account(local_part=None, domain=None, api_key=None, jwt=None):
    return yyds_provider.create_account(
        http_post,
        local_part=local_part or "",
        domain=domain or "",
        api_key=api_key or get_yyds_api_key(),
        jwt=jwt or get_yyds_jwt(),
    )


def yyds_get_token(address, api_key=None, jwt=None):
    return yyds_provider.get_token(http_post, address, api_key=api_key or get_yyds_api_key(), jwt=jwt or get_yyds_jwt())


def yyds_get_messages(address, token=None, api_key=None, jwt=None):
    return yyds_provider.get_messages(
        http_get,
        address,
        token=token or "",
        api_key=api_key or get_yyds_api_key(),
        jwt=jwt or get_yyds_jwt(),
    )


def yyds_get_message_detail(message_id, token=None, api_key=None, jwt=None):
    return yyds_provider.get_message_detail(
        http_get,
        message_id,
        token=token or "",
        api_key=api_key or get_yyds_api_key(),
        jwt=jwt or get_yyds_jwt(),
    )


def yyds_generate_username(length=10):
    return yyds_provider.generate_username(length)


def yyds_pick_domain(api_key=None, jwt=None):
    return yyds_provider.pick_domain(http_get, api_key=api_key or get_yyds_api_key(), jwt=jwt or get_yyds_jwt())


def yyds_get_email_and_token(api_key=None, jwt=None):
    key = api_key or get_yyds_api_key()
    token = jwt or get_yyds_jwt()
    if not token and not key:
        raise Exception("YYDS API Key 或 JWT 未配置")
    domain = get_yyds_default_domain() or yyds_pick_domain(api_key=key, jwt=token)
    username = yyds_generate_username(10)
    result = yyds_create_account(
        local_part=username, domain=domain, api_key=key, jwt=token
    )
    address = result.get("address") or f"{username}@{domain}"
    temp_token = result.get("token")
    if not temp_token:
        temp_token = yyds_get_token(address, api_key=key, jwt=token)
    if not temp_token:
        raise Exception("获取 YYDS token 失败")
    print(f"[*] 已创建 YYDS 邮箱: {address}")
    return address, temp_token


def yyds_get_oai_code(token, address, timeout=180, poll_interval=3, log_callback=None, jwt=None, cancel_callback=None):
    return yyds_provider.wait_for_code(
        http_get,
        token,
        address,
        timeout=timeout,
        poll_interval=poll_interval,
        jwt=jwt or get_yyds_jwt(),
        raise_if_cancelled=raise_if_cancelled,
        sleep_with_cancel=sleep_with_cancel,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )



def generate_username(length=10):
    return _generate_username(length)


def pick_domain(api_key=None):
    return duckmail_provider.pick_domain(get_domains(api_key=api_key))


def get_cloudmail_url():
    return str(os.environ.get("CLOUDMAIL_URL") or config.get("cloudmail_url", "") or "").strip().rstrip("/")


def get_cloudmail_admin_email():
    return str(os.environ.get("CLOUDMAIL_ADMIN_EMAIL") or config.get("cloudmail_admin_email", "") or "").strip()


def get_cloudmail_password():
    return str(os.environ.get("CLOUDMAIL_PASSWORD") or config.get("cloudmail_password", "") or "")


def cloudmail_get_email_and_token():
    raw_domains = str(config.get("defaultDomains", "") or "")
    domains = [item.strip() for item in re.split(r"[,，\s]+", raw_domains) if item.strip()]
    return cloudmail_provider.create_mailbox(
        http_post,
        get_cloudmail_url(),
        get_cloudmail_admin_email(),
        get_cloudmail_password(),
        domains,
        username=generate_username(10),
    )


def cloudmail_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
    resend_callback=None,
):
    del dev_token
    return cloudmail_provider.wait_for_code(
        http_post,
        http_delete,
        get_cloudmail_url(),
        get_cloudmail_admin_email(),
        get_cloudmail_password(),
        email,
        timeout=timeout,
        poll_interval=poll_interval,
        raise_if_cancelled=raise_if_cancelled,
        sleep_with_cancel=sleep_with_cancel,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
        resend_callback=resend_callback,
    )


def get_email_provider():
    return config.get("email_provider", "cloudflare")


def get_email_and_token(api_key=None):
    provider = get_email_provider()
    if provider == "yyds":
        return yyds_get_email_and_token(api_key=api_key, jwt=get_yyds_jwt())
    if provider == "cloudmail":
        return cloudmail_get_email_and_token()
    if provider == "cloudflare":
        api_base = get_cloudflare_api_base()
        if not api_base:
            raise Exception("Cloudflare API Base 未配置")
        try:
            # cloudflare_temp_email 专用模式
            return cloudflare_create_temp_address(api_base)
        except Exception as primary_exc:
            create_path = get_cloudflare_path("cloudflare_path_accounts", "/admin/new_address")
            try:
                return cloudflare_provider.create_mailbox_fallback(
                    http_get,
                    http_post,
                    api_base,
                    domains_path=get_cloudflare_path("cloudflare_path_domains", "/domains"),
                    accounts_path=get_cloudflare_path("cloudflare_path_accounts", "/accounts"),
                    token_path=get_cloudflare_path("cloudflare_path_token", "/token"),
                    api_key=api_key or get_cloudflare_api_key(),
                    auth_mode=get_cloudflare_auth_mode(),
                    custom_auth=get_cloudflare_custom_auth(),
                )
            except Exception as fallback_exc:
                raise Exception(
                    "Cloudflare 创建邮箱失败；"
                    f"主接口 {create_path}: "
                    f"{primary_exc.__class__.__name__}: {primary_exc}；"
                    f"兼容回退: "
                    f"{fallback_exc.__class__.__name__}: {fallback_exc}"
                ) from fallback_exc
    if provider == "mailnest":
        return mailnest_buy_email(), "_"
    return duckmail_provider.create_mailbox(
        http_get,
        http_post,
        get_duckmail_api_base(),
        api_key=api_key or get_duckmail_api_key(),
        expires_in=0,
    )


def get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
    resend_callback=None,
    min_received_at=None,
):
    provider = get_email_provider()
    if provider == "yyds":
        return yyds_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            jwt=get_yyds_jwt(),
            cancel_callback=cancel_callback,
        )
    if provider == "cloudmail":
        return cloudmail_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
            resend_callback=resend_callback,
        )
    if provider == "cloudflare":
        return cloudflare_get_oai_code(
            dev_token,
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
            resend_callback=resend_callback,
        )
    if provider == "mailnest":
        return mailnest_get_code(
            email,
            timeout=timeout,
            poll_interval=poll_interval,
            log_callback=log_callback,
            cancel_callback=cancel_callback,
        )
    return duckmail_get_oai_code(
        dev_token,
        email,
        timeout=timeout,
        poll_interval=poll_interval,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )



def extract_verification_code(text, subject=""):
    return _extract_code(text, subject)


def duckmail_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
):
    return duckmail_provider.wait_for_code(
        http_get,
        get_duckmail_api_base(),
        dev_token,
        email,
        timeout=timeout,
        poll_interval=poll_interval,
        extract_code=extract_verification_code,
        raise_if_cancelled=raise_if_cancelled,
        sleep_with_cancel=sleep_with_cancel,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
    )


def cloudflare_get_oai_code(
    dev_token,
    email,
    timeout=180,
    poll_interval=3,
    log_callback=None,
    cancel_callback=None,
    resend_callback=None,
):
    return cloudflare_provider.wait_for_code(
        http_get,
        get_cloudflare_api_base(),
        dev_token,
        email,
        messages_path=get_cloudflare_path("cloudflare_path_messages", "/messages"),
        api_key=get_cloudflare_api_key(),
        auth_mode=get_cloudflare_auth_mode(),
        custom_auth=get_cloudflare_custom_auth(),
        timeout=timeout,
        poll_interval=poll_interval,
        raise_if_cancelled=raise_if_cancelled,
        sleep_with_cancel=sleep_with_cancel,
        log_callback=log_callback,
        cancel_callback=cancel_callback,
        resend_callback=resend_callback,
    )


def generate_random_birthdate():
    import datetime as dt

    today = dt.date.today()
    age = random.randint(20, 40)
    birth_year = today.year - age
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    return f"{birth_year}-{birth_month:02d}-{birth_day:02d}T16:00:00.000Z"


def response_preview(res, limit=200):
    """安全预览 HTTP 响应体；gRPC/二进制内容不直接当文本打印。"""
    try:
        headers = {str(k).lower(): str(v).lower() for k, v in dict(getattr(res, "headers", {}) or {}).items()}
        content_type = headers.get("content-type", "")
        raw = getattr(res, "content", None)
        if raw is None:
            try:
                raw = (res.text or "").encode("utf-8", errors="replace")
            except Exception:
                raw = b""
        if not isinstance(raw, (bytes, bytearray)):
            raw = str(raw).encode("utf-8", errors="replace")
        raw = bytes(raw)

        # gRPC / protobuf 常见 content-type 或正文以不可打印字节为主
        is_binaryish = (
            "grpc" in content_type
            or "protobuf" in content_type
            or "octet-stream" in content_type
            or (raw[:1] in (b"\x00", b"\x01") and b"grpc-status" in raw)
        )
        if is_binaryish or (raw and sum(1 for b in raw[:64] if b < 9 or (13 < b < 32)) > 8):
            # 尽量抽出可读的 trailer 片段（如 grpc-status:0）
            readable = re.findall(rb"[ -~]{3,}", raw)
            text = " ".join(part.decode("ascii", errors="ignore") for part in readable)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                text = f"<binary {len(raw)} bytes>"
            return text[:limit]

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]
    except Exception:
        return ""


def is_cloudflare_block_response(res):
    try:
        headers = {str(k).lower(): str(v).lower() for k, v in dict(res.headers).items()}
        text = str(res.text or "").lower()
        server = headers.get("server", "")
        content_type = headers.get("content-type", "")
        return (
            res.status_code in (403, 429, 503)
            and (
                "cloudflare" in server
                or "cloudflare" in text
                or "cf-error" in text
                or "__cf_chl" in text
                or "text/html" in content_type
            )
        )
    except Exception:
        return False


def is_debug_mode():
    return bool(config.get("debug_mode", False))


def is_browser_headless():
    force_headed = str(os.environ.get("PS_FORCE_HEADED", "") or "").strip().lower()
    if force_headed in {"1", "true", "yes", "on"}:
        return False
    return bool(config.get("browser_headless", False))


def get_browser_locale() -> str:
    value = str(config.get("browser_locale", "en-US") or "en-US").strip()
    return value if value in {"en-US", "zh-CN"} else "en-US"


def should_close_browser_after_run(user_stopped: bool) -> bool:
    """正常结束时非调试模式关闭；手动停止时严格以勾选项为准。"""
    if user_stopped:
        return bool(config.get("close_browser_on_stop", False))
    return not is_debug_mode()


def maybe_stop_browser(user_stopped: bool = False, log_callback=None):
    if should_close_browser_after_run(user_stopped):
        # 手动勾选关闭时应优先于调试模式，因此这里显式 force。
        stop_browser(force=True)
        if log_callback:
            reason = "用户停止" if user_stopped else "任务结束"
            log_callback(f"[*] {reason}：已执行浏览器关闭")
        return
    if log_callback:
        if user_stopped:
            log_callback("[*] 用户停止：按当前勾选设置保留浏览器")
        else:
            log_callback("[*] 调试模式：正常结束后保留浏览器")


def get_log_level() -> str:
    level = str(config.get("log_level", "info") or "info").strip().lower()
    return level if level in ("info", "debug") else "info"


def should_emit_log(message: str) -> bool:
    """info 级别过滤 [Debug] 行；debug 全开。"""
    if get_log_level() == "debug":
        return True
    text = str(message or "")
    if text.lstrip().startswith("[Debug]") or " [Debug] " in text:
        return False
    return True


def _wire_runtime_modules():
    """向浏览器运行时和页面流程注入本次任务依赖。"""
    _bs.configure(
        get_proxies=get_proxies,
        is_debug=is_debug_mode,
        is_headless=is_browser_headless,
        get_locale=get_browser_locale,
        extension_path=EXTENSION_PATH,
    )
    _rf.configure(
        get_email_and_token=get_email_and_token,
        get_oai_code=get_oai_code,
        raise_if_cancelled=raise_if_cancelled,
        sleep_with_cancel=sleep_with_cancel,
        RegistrationCancelled=RegistrationCancelled,
        EmailDomainRejected=EmailDomainRejected,
        AccountRetryNeeded=AccountRetryNeeded,
        email_unavailable=email_registered_successfully,
    )
    _ps_api.configure(http_post=http_post, http_get=http_get, http_delete=http_delete)
    _ps_resin.configure(http_post=http_post, http_get=http_get, http_delete=http_delete)

# 页面步骤由 registration.signup_flow / ps_signup_flow 实现。

class RegistrationStopController:
    def __init__(self):
        self.stop_requested = False

    def should_stop(self):
        return self.stop_requested

    def stop(self):
        self.stop_requested = True


def registration_log(message):
    if not should_emit_log(message):
        return
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)


def run_registration(count):
    controller = RegistrationStopController()
    reset_network_route_logs()

    success_count = 0
    fail_count = 0
    fail_stats = empty_fail_stats()
    batch_id = new_registration_batch_id("web")
    retry_count_for_slot = 0
    max_slot_retry = 3
    workers = max(1, min(int(config.get("register_workers", 1) or 1), 8, int(count or 1)))
    retry_multiplier = max(1, int(config.get("registration_retry_multiplier", 3) or 3))
    max_attempts_total = max(int(count or 1) * retry_multiplier, int(count or 1) + 2)
    registration_log(f"[*] Web 任务启动，目标成功数: {count} | 并发: {workers} | 失败自动重试，总尝试上限: {max_attempts_total}")
    _interval_raw = str(config.get("account_interval", "0") or "0").strip()
    if _interval_raw and _interval_raw != "0":
        registration_log(f"[*] 账号间注册间隔: {_interval_raw}s")
    _ps_base = str(config.get("ps_dashboard_base") or "https://dashboard.proxyscrape.com/v2").rstrip("/")
    registration_log(f"[*] ProxyScrape: {_ps_base} | Resin 入池: {'开' if _ps_resin.resin_enabled() else '关'}")
    traceback_log_lock = threading.Lock()
    logged_traceback_signatures = set()
    try:
        _cleanup_stale_profiles(log_callback=registration_log)
    except Exception:
        pass
    try:
        startup_checks = _conn.run_connectivity_checks(config, http_get, http_post)
        for name, ok, detail in startup_checks:
            registration_log(f"[检查] [{'OK' if ok else 'FAIL'}] {name}: {detail}")
        if _conn.has_blocking_ps_failure(startup_checks):
            registration_log("[!] ProxyScrape 注册页被 Cloudflare 拦截，已停止建号；请更换当前 proxy 后重试")
            return
    except Exception as exc:
        registration_log(f"[!] 启动连通性检查异常，继续注册: {exc}")

    def _record_failure(exc):
        nonlocal fail_count
        kind = classify_failure(exc)
        fail_count += 1
        fail_stats[kind] = fail_stats.get(kind, 0) + 1
        return kind

    def _persist_result(*, started_at, worker_id=0, **kwargs):
        trace_text = ""
        if str(kwargs.get("status") or "").strip().lower() == "failure":
            trace_text = current_exception_traceback()
            if trace_text:
                extra = dict(kwargs.get("extra") or {})
                extra["exception_traceback"] = trace_text
                extra["exception_type"] = trace_text.rstrip().splitlines()[-1]
                kwargs["extra"] = extra
                signature = hash(trace_text)
                with traceback_log_lock:
                    should_log_traceback = signature not in logged_traceback_signatures
                    if should_log_traceback:
                        logged_traceback_signatures.add(signature)
                if should_log_traceback:
                    registration_log(
                        "[异常堆栈]\n"
                        + current_exception_traceback(TRACEBACK_LOG_MAX_CHARS)
                    )
        if (
            str(kwargs.get("status") or "").strip().lower() == "failure"
            and str(kwargs.get("failure_type") or "") not in (FAIL_DOMAIN, FAIL_ALREADY_REGISTERED)
            and not kwargs.get("screenshot_path")
        ):
            kwargs["screenshot_path"] = capture_failure_screenshot(
                batch_id=batch_id,
                worker_id=worker_id,
                email=str(kwargs.get("email") or ""),
                failure_type=str(kwargs.get("failure_type") or FAIL_OTHER),
                log_callback=registration_log,
            )
        return persist_registration_result(
            batch_id=batch_id,
            source="web",
            started_at=started_at,
            provider=str(config.get("email_provider", "") or ""),
            worker_id=int(worker_id) + 1,
            log_callback=registration_log,
            **kwargs,
        )

    def _slot_log(message, prefix=""):
        registration_log(f"{prefix}{message}")

    def _run_slot(*, started_at, worker_id=0, prefix="", seq=0):
        """单个账号的 ProxyScrape 注册流程；返回 (成功?, 失败分类)。"""
        email = ""
        password = ""
        email_file = ""
        ps_detail = {}
        try:
            _psf.open_ps_signup_page(
                log_callback=lambda m: _slot_log(m, prefix),
                cancel_callback=controller.should_stop,
            )
            email, dev_token = get_email_and_token()
            password = _ps_api.generate_password()
            registration_log(f"{prefix}[*] 邮箱: {email} | 密码长度: {len(password)}")
            try:
                with open(
                    accounts_side_file("mail_credentials.txt"),
                    "a",
                    encoding="utf-8",
                ) as f:
                    f.write(f"{email}\t{dev_token}\n")
            except Exception:
                pass
            _psf.fill_ps_signup_form(
                email,
                password,
                log_callback=lambda m: _slot_log(m, prefix),
                cancel_callback=controller.should_stop,
            )
            registration_log(f"{prefix}[*] 等待 Turnstile 并提交注册")
            access_token = _psf.submit_ps_signup_and_wait_token(
                timeout=60,
                log_callback=lambda m: _slot_log(m, prefix),
                cancel_callback=controller.should_stop,
            )
            registration_log(f"{prefix}[*] 验证邮箱")
            code = get_oai_code(
                dev_token,
                email,
                log_callback=lambda m: _slot_log(m, prefix),
                cancel_callback=controller.should_stop,
            )
            _ps_api.ps_verify_email_api(access_token, code, log_callback=lambda m: _slot_log(m, prefix))
            _ps_api.ps_complete_typeform(access_token, log_callback=lambda m: _slot_log(m, prefix))
            me = _ps_api.ps_fetch_me(access_token)
            sub = _ps_api.ps_pick_subaccount(me)
            if not sub:
                raise Exception("me 响应中未找到可用子账号")
            account_id = str(sub.get("AccountID") or sub.get("id") or "").strip()
            if not account_id:
                raise Exception("子账号缺少 AccountID")
            registration_log(f"{prefix}[*] 下载代理列表 (account={account_id})")
            proxies = _ps_api.ps_download_proxy_list(
                access_token,
                account_id,
                log_callback=lambda m: _slot_log(m, prefix),
            )
            proxy_file = save_proxy_list_file(email, proxies, log_callback=lambda m: _slot_log(m, prefix))
            valid_days = max(1, int(config.get("account_valid_days") or 7))
            expire_at = (datetime.datetime.now() + datetime.timedelta(days=valid_days)).isoformat()
            resin_status = "skipped"
            if _ps_resin.resin_enabled():
                # 入池失败自动重试（resin_push_retries 次，间隔递增 5s/10s/15s）
                resin_push_retries = max(0, int(config.get("resin_push_retries", 2) or 0))
                resin_exc = None
                for push_attempt in range(resin_push_retries + 1):
                    try:
                        _ps_resin.resin_push_subscription(
                            email,
                            proxies,
                            log_callback=lambda m: _slot_log(m, prefix),
                        )
                        resin_status = "success"
                        resin_exc = None
                        break
                    except Exception as exc:
                        resin_exc = exc
                        if push_attempt < resin_push_retries:
                            registration_log(
                                f"{prefix}[!] Resin 入池失败，"
                                f"{push_attempt + 1}/{resin_push_retries} 次重试: {exc}"
                            )
                            sleep_with_cancel(5 * (push_attempt + 1), controller.should_stop)
                if resin_exc is not None:
                    resin_status = f"failed: {resin_exc}"
                    hint = ""
                    msg = str(resin_exc)
                    if "timed out" in msg or "timeout" in msg or "Connection" in msg:
                        hint = (
                            " 提示: 1) Resin 与 ps-register 同机时请把 resin_base_url 改为 "
                            "http://host.docker.internal:2260(hairpin NAT); 2) 若 reg 通过 "
                            "节点隧道上网且 Resin 在节点服务器上，发往节点自身公网 IP 的流量 "
                            "会被节点透明代理劫持——在 reg 宿主机执行 "
                            "'ssh -N -L 2260:127.0.0.1:2260 root@<节点IP>' 建隧道，"
                            "resin_base_url 改 http://host.docker.internal:2260; "
                            "3) 其他机器请检查安全组/防火墙放行 2260。"
                        )
                    registration_log(f"{prefix}[!] Resin 入池失败（不影响账号保存）: {resin_exc}{hint}")
            ps_detail = {
                "status": "success",
                "access_token": access_token,
                "account_id": account_id,
                "expire_at": expire_at,
                "proxy_file": proxy_file,
                "resin_status": resin_status,
            }
            try:
                email_file = account_file_for_email(email)
                with open(email_file, "w", encoding="utf-8") as f:
                    f.write(f"{email}----{password}----{access_token}\n")
            except Exception as file_exc:
                registration_log(f"{prefix}[!] 保存账号文件失败，当前账号不计为成功: {file_exc}")
                raise RuntimeError(f"保存账号文件失败: {file_exc}") from file_exc
            try:
                save_account_record(
                    email=email,
                    password=password,
                    created_at=datetime.datetime.now().isoformat(timespec="seconds"),
                    expire_at=expire_at,
                )
            except Exception as summary_exc:
                registration_log(f"{prefix}[!] 写入 accounts.txt 汇总失败（不影响账号保存）: {summary_exc}")
            email_disable_detail = default_email_disable_detail("", ps_detail)
            _persist_result(
                started_at=started_at,
                worker_id=worker_id,
                email=email,
                password=password,
                status="success",
                ps_detail=ps_detail,
                email_disable_detail=email_disable_detail,
                account_file=email_file,
                extra={"任务序号": seq, "并发数": workers},
            )
            registration_log(f"{prefix}[+] 注册成功: {email}")
            return True, None
        except RegistrationCancelled:
            cancelled_email = current_attempt_email(email)
            if cancelled_email:
                _persist_result(
                    started_at=started_at,
                    worker_id=worker_id,
                    email=cancelled_email,
                    password=password,
                    status="cancelled",
                    ps_detail=ps_detail,
                    failure_reason="用户停止注册",
                    account_file=email_file,
                )
            raise
        except EmailDomainRejected as exc:
            kind = classify_failure(exc)
            ps_detail.update(status="failure", error=str(exc))
            email_disable_detail = default_email_disable_detail("", ps_detail)
            _persist_result(
                started_at=started_at,
                worker_id=worker_id,
                email=current_attempt_email(email, exc),
                password=password,
                status="failure",
                ps_detail=ps_detail,
                email_disable_detail=email_disable_detail,
                failure_type=kind,
                failure_reason=str(exc),
            )
            registration_log(f"{prefix}[-] 域名拒绝: {exc}")
            return False, kind
        except Exception as exc:
            kind = classify_failure(exc)
            ps_detail.update(status="failure", error=str(exc))
            fail_email = current_attempt_email(email, exc)
            email_disable_detail = default_email_disable_detail("", ps_detail)
            _persist_result(
                started_at=started_at,
                worker_id=worker_id,
                email=fail_email,
                password=password,
                status="failure",
                ps_detail=ps_detail,
                email_disable_detail=email_disable_detail,
                failure_type=kind,
                failure_reason=str(exc),
                account_file=email_file,
                extra={"任务序号": seq, "并发数": workers},
            )
            registration_log(f"{prefix}[-] 失败 [{FAIL_LABELS.get(kind, kind)}]: {exc}")
            return False, kind

    if workers > 1:
        stats_lock = threading.Lock()
        accounts_lock = threading.Lock()
        base, rem = divmod(count, workers)
        chunks = [base + (1 if i < rem else 0) for i in range(workers)]
        threads = []
        shared = {"success": 0, "fail": 0, "fail_stats": empty_fail_stats()}

        def worker(n, wid):
            local_success = 0
            local_fail = 0
            local_fail_stats = empty_fail_stats()
            try:
                boot_started_at = time.time()
                try:
                    start_browser(log_callback=lambda m: registration_log(f"[W{wid+1}] {m}"))
                except Exception as boot_exc:
                    local_fail = n
                    local_fail_stats[FAIL_BROWSER] = local_fail_stats.get(FAIL_BROWSER, 0) + n
                    registration_log(f"[W{wid+1}] [-] 浏览器启动失败，{n} 个任务均记为失败: {boot_exc}")
                    for _ in range(max(int(n or 0), 0)):
                        _persist_result(
                            started_at=boot_started_at,
                            worker_id=wid,
                            status="failure",
                            failure_type=FAIL_BROWSER,
                            failure_reason=str(boot_exc),
                            ps_detail={"status": "failure", "error": str(boot_exc)},
                        )
                    return
                local_max_attempts = max(int(n or 1) * retry_multiplier, int(n or 1) + 2)
                attempts = 0
                while local_success < n and attempts < local_max_attempts and not controller.should_stop():
                    attempt_started_at = time.time()
                    prefix = f"[W{wid+1}] "
                    ok, kind = _run_slot(
                        started_at=attempt_started_at,
                        worker_id=wid,
                        prefix=prefix,
                        seq=local_success + 1,
                    )
                    if ok:
                        local_success += 1
                        attempts += 1
                    elif kind == FAIL_BROWSER and not controller.should_stop():
                        # 浏览器级失败：重启浏览器重试同一账号，不消耗新账号尝试预算
                        retry = 0
                        while retry < max_slot_retry and not controller.should_stop():
                            retry += 1
                            registration_log(f"{prefix}[!] 浏览器异常，重启后重试第 {retry}/{max_slot_retry} 次")
                            try:
                                restart_browser(log_callback=lambda m: registration_log(f"{prefix}{m}"))
                            except Exception:
                                pass
                            ok2, kind2 = _run_slot(
                                started_at=time.time(),
                                worker_id=wid,
                                prefix=prefix,
                                seq=local_success + 1,
                            )
                            if ok2:
                                local_success += 1
                                attempts += 1
                                break
                            if kind2 != FAIL_BROWSER:
                                local_fail += 1
                                local_fail_stats[kind2] = local_fail_stats.get(kind2, 0) + 1
                                attempts += 1
                                break
                        else:
                            local_fail += 1
                            local_fail_stats[FAIL_BROWSER] = local_fail_stats.get(FAIL_BROWSER, 0) + 1
                            attempts += 1
                    else:
                        # 非浏览器失败：记录后自动换新邮箱重试（不直接放弃）
                        local_fail += 1
                        local_fail_stats[kind] = local_fail_stats.get(kind, 0) + 1
                        attempts += 1
                    if (
                        local_success < n
                        and attempts < local_max_attempts
                        and not controller.should_stop()
                    ):
                        try:
                            stop_browser()
                            time.sleep(0.3)
                        except Exception:
                            pass
            finally:
                try:
                    maybe_stop_browser(
                        user_stopped=bool(controller.should_stop()),
                        log_callback=lambda m: registration_log(f"[W{wid+1}] {m}"),
                    )
                except Exception:
                    pass
                with stats_lock:
                    shared["success"] += local_success
                    shared["fail"] += local_fail
                    for k, v in local_fail_stats.items():
                        shared["fail_stats"][k] = shared["fail_stats"].get(k, 0) + v

        for wid, n in enumerate(chunks):
            if n <= 0:
                continue
            t = threading.Thread(target=worker, args=(n, wid), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        success_count = shared["success"]
        fail_count = shared["fail"]
        fail_stats = shared["fail_stats"]
        registration_log(
            f"[*] 任务结束。成功 {success_count} | 失败 {fail_count}"
            + (f" | {format_fail_stats(fail_stats)}" if fail_count else "")
        )
        return

    try:
        boot_started_at = time.time()
        try:
            start_browser(log_callback=registration_log)
        except Exception as boot_exc:
            fail_count += count
            fail_stats[FAIL_BROWSER] = fail_stats.get(FAIL_BROWSER, 0) + count
            registration_log(f"[-] 浏览器启动失败，{count} 个任务均记为失败: {boot_exc}")
            for _ in range(max(int(count or 0), 0)):
                _persist_result(
                    started_at=boot_started_at,
                    status="failure",
                    failure_type=FAIL_BROWSER,
                    failure_reason=str(boot_exc),
                    ps_detail={"status": "failure", "error": str(boot_exc)},
                )
            return
        registration_log("[*] 浏览器已启动")
        attempts = 0
        while success_count < count and attempts < max_attempts_total:
            if controller.should_stop():
                break
            attempts += 1
            registration_log(
                f"--- 尝试第 {attempts}/{max_attempts_total} 个新邮箱（目标 {count}，已成功 {success_count}）---"
            )
            attempt_started_at = time.time()
            ok, kind = _run_slot(started_at=attempt_started_at, worker_id=0, prefix="", seq=success_count + 1)
            if ok:
                success_count += 1
                retry_count_for_slot = 0
            elif kind == FAIL_BROWSER and not controller.should_stop():
                retry_count_for_slot += 1
                if retry_count_for_slot <= max_slot_retry:
                    registration_log(f"[!] 浏览器异常，重启后重试第 {retry_count_for_slot}/{max_slot_retry} 次")
                    try:
                        restart_browser(log_callback=registration_log)
                    except Exception:
                        pass
                    continue
                _record_failure(Exception("浏览器异常重试超限"))
                retry_count_for_slot = 0
            else:
                # 非浏览器失败：记录后自动换新邮箱重试（不直接放弃）
                _record_failure(
                    Exception(f"{FAIL_LABELS.get(kind, kind)}") if kind else RuntimeError("注册失败")
                )
                retry_count_for_slot = 0
            registration_log(
                f"[*] 当前统计: 成功 {success_count} | 失败 {fail_count} | 尝试 {attempts}/{max_attempts_total}"
            )
            if (
                ok
                and success_count > 0
                and success_count % MEMORY_CLEANUP_INTERVAL == 0
                and success_count < count
            ):
                cleanup_runtime_memory(
                    log_callback=registration_log,
                    reason=f"已成功 {success_count} 个账号，执行定期清理",
                )
            if controller.should_stop():
                break
            if success_count >= count or attempts >= max_attempts_total:
                continue
            wait_sec = parse_account_interval()
            if wait_sec > 0:
                registration_log(f"[*] 下一个账号前等待 {wait_sec:.0f} 秒...")
                sleep_with_cancel(wait_sec, controller.should_stop)
            try:
                stop_browser()
                time.sleep(0.5)
            except RegistrationCancelled:
                break
            except Exception as close_exc:
                if controller.should_stop():
                    break
                registration_log(f"[Debug] 轮次关闭浏览器失败: {close_exc}")
    except RegistrationCancelled:
        registration_log("[!] 注册被停止")
    except Exception as exc:
        registration_log(f"[!] 任务异常: {exc}")
    finally:
        try:
            user_stopped = bool(controller.should_stop())
            if user_stopped:
                maybe_stop_browser(user_stopped=True, log_callback=registration_log)
            else:
                cleanup_runtime_memory(log_callback=registration_log, reason="任务结束")
        except BaseException:
            pass
        try:
            registration_log(
                f"[*] 任务结束。成功 {success_count} | 失败 {fail_count}"
                + (f" | {format_fail_stats(fail_stats)}" if fail_count else "")
            )
        except BaseException:
            pass
