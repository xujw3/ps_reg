# -*- coding: utf-8 -*-
"""ProxyScrape REST API 封装。

注册/验证/typeform/me/代理列表等 HTTP 接口，HTTP 调用经
``configure(**kwargs)`` 注入（engine 提供 http_post/http_get），
配置读取延迟引用 ``backend.registration.engine.config`` 避免循环导入。
"""
from __future__ import annotations

import random
import re
import secrets
import string
import time
from typing import Any, Dict, List, Optional

PS_TURNSTILE_SITEKEY = "0x4AAAAAAAFWUVCKyusT9T8r"

_deps: Dict[str, Any] = {}


def configure(**kwargs) -> None:
    _deps.update(kwargs)


def _gr():
    from backend.registration import engine as gr

    return gr


def _ps_dashboard_base() -> str:
    return str(_gr().config.get("ps_dashboard_base") or "https://dashboard.proxyscrape.com/v2").rstrip("/")


def _ps_api_base() -> str:
    base = str(_gr().config.get("ps_api_base") or "").strip().rstrip("/")
    if base:
        return base
    return _ps_dashboard_base()


def _ps_endpoint(path: str) -> str:
    """构建端点 URL；默认与前端一致走 dashboard 同源 /v2/v4/...。"""
    path = "/" + str(path or "").lstrip("/")
    return f"{_ps_api_base()}{path}"


def _ps_auth_headers(access_token: str = "") -> dict:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://dashboard.proxyscrape.com",
        "Referer": f"{_ps_dashboard_base()}/sign-up",
        "User-Agent": str(_gr().config.get("user_agent") or ""),
        "Accept": "application/json, text/plain, */*",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


def generate_password(length: Optional[int] = None) -> str:
    """生成满足 ProxyScrape 规则的密码：≥8、大写、数字、特殊字符，长度 clamp [10,32]。"""
    n = int(length if length is not None else _gr().config.get("ps_password_length") or 14)
    n = max(10, min(n, 32))
    upper = random.choice(string.ascii_uppercase)
    lower = random.choice(string.ascii_lowercase)
    digit = random.choice(string.digits)
    special = random.choice("!@#$%^&*")
    pool = string.ascii_letters + string.digits + "!@#$%^&*"
    chars = list(upper + lower + digit + special)
    chars += [secrets.choice(pool) for _ in range(n - 4)]
    random.shuffle(chars)
    return "".join(chars)


def _http_post(url: str, **kwargs):
    return _deps["http_post"](url, **kwargs)


def _http_get(url: str, **kwargs):
    return _deps["http_get"](url, **kwargs)


def _parse_body(resp, fallback: str = "") -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"raw": str(body)[:300]}
    except Exception:
        return {"raw": (resp.text or fallback)[:500]}


def _raise_on_error(resp, body: dict, action: str) -> None:
    if resp.status_code >= 400 or body.get("success") is False:
        msg = body.get("message") or body.get("error") or (resp.text or "")[:300]
        raise Exception(f"{action} HTTP {resp.status_code}: {msg}")


def ps_register_api(email: str, password: str, turnstile_token: str, log_callback=None) -> dict:
    """POST /v4/account/auth/register"""
    url = _ps_endpoint("/v4/account/auth/register")
    data = {"email": email, "password": password, "cf_turnstile_token": turnstile_token}
    if log_callback:
        log_callback(f"[*] 注册 API: {url}")
    resp = _http_post(url, data=data, headers=_ps_auth_headers(), timeout=30)
    body = _parse_body(resp)
    _raise_on_error(resp, body, "注册失败")
    return body


def ps_verify_email_api(access_token: str, verification_code: str, log_callback=None) -> dict:
    """POST /v4/account/verify-email"""
    url = _ps_endpoint("/v4/account/verify-email")
    data = {"verificationCode": verification_code}
    if log_callback:
        log_callback(f"[*] 验证邮箱 API: {url}")
    resp = _http_post(url, data=data, headers=_ps_auth_headers(access_token), timeout=30)
    body = _parse_body(resp)
    _raise_on_error(resp, body, "邮箱验证失败")
    return body


def ps_resend_verification_code(access_token: str, log_callback=None) -> dict:
    """POST /v4/account/reset-verification-code"""
    url = _ps_endpoint("/v4/account/reset-verification-code")
    if log_callback:
        log_callback(f"[*] 重发验证码: {url}")
    resp = _http_post(url, data={}, headers=_ps_auth_headers(access_token), timeout=30)
    return _parse_body(resp, "{}")


def ps_complete_typeform(access_token: str, log_callback=None) -> dict:
    """完成注册后的 typeform 问卷步骤（默认 stub response_id）。"""
    if _gr().config.get("ps_skip_typeform"):
        if log_callback:
            log_callback("[*] 跳过 typeform")
        return {"success": True, "skipped": True}
    url = _ps_endpoint("/v4/account/typeform")
    form_id = str(_gr().config.get("ps_typeform_form_id") or "vnCgUn0n")
    if _gr().config.get("ps_typeform_response_stub", True):
        response_id = f"auto-{int(time.time())}-{secrets.token_hex(4)}"
    else:
        response_id = str(_gr().config.get("ps_typeform_response_id") or f"manual-{int(time.time())}")
    payload = {"form_id": form_id, "response_id": response_id}
    headers = _ps_auth_headers(access_token)
    headers["Content-Type"] = "application/json"
    if log_callback:
        log_callback(f"[*] 提交 typeform: form_id={form_id}")
    resp = _http_post(url, json=payload, headers=headers, timeout=30)
    body = _parse_body(resp)
    if resp.status_code >= 400 and log_callback:
        log_callback(f"[!] typeform 返回 {resp.status_code}: {str(body)[:160]}")
    return body


def ps_fetch_me(access_token: str) -> dict:
    """/v4/account/auth/me 仅支持 POST。"""
    url = _ps_endpoint("/v4/account/auth/me")
    resp = _http_post(url, data={}, headers=_ps_auth_headers(access_token), timeout=20)
    return _parse_body(resp, "{}")


def ps_pick_subaccount(me_body: dict, preferred_type: str = "datacenter_shared") -> dict:
    subs = []
    if isinstance(me_body, dict):
        subs = me_body.get("associatedSubaccounts") or []
        if not subs:
            data = me_body.get("data") or {}
            if isinstance(data, dict):
                subs = data.get("subaccounts") or []
    if not isinstance(subs, list):
        return {}
    for s in subs:
        if str(s.get("AccountType") or "") == preferred_type:
            return s
    return subs[0] if subs else {}


def ps_fetch_proxy_credentials(
    access_token: str,
    account_id: str,
    *,
    protocol: str = "http",
    proxy_type: str = "datacenter_shared",
    log_callback=None,
) -> dict:
    """从 services/overview 读取 proxy_username / proxy_password。"""
    account_id = str(account_id or "").strip()
    if not account_id:
        raise Exception("缺少 AccountID，无法读取代理账密")
    url = _ps_endpoint(f"/v4/account/{account_id}/services/overview")
    headers = _ps_auth_headers(access_token)
    headers["Accept"] = "application/json, text/plain, */*"
    if log_callback:
        log_callback(f"[*] 读取代理账密: {url}")
    resp = _http_get(url, headers=headers, timeout=30)
    body = _parse_body(resp)
    if resp.status_code >= 400:
        raise Exception(f"读取代理账密失败 HTTP {resp.status_code}: {(resp.text or '')[:200]}")
    data = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data, dict):
        data = {}
    services = data.get("services") if isinstance(data.get("services"), dict) else {}
    svc = services.get(proxy_type) if isinstance(services, dict) else {}
    if not isinstance(svc, dict):
        # 兜底：直接取对应 service 的 overview
        try:
            url2 = _ps_endpoint(f"/v4/account/{account_id}/{proxy_type}/overview")
            resp2 = _http_get(url2, headers=headers, timeout=30)
            body2 = _parse_body(resp2)
            data2 = body2.get("data") if isinstance(body2, dict) else {}
            services2 = data2.get("services") if isinstance(data2, dict) else {}
            svc = (services2 or {}).get(proxy_type) or {}
            data = data2 if isinstance(data2, dict) else data
        except Exception:
            svc = {}
    username = str((svc or {}).get("proxy_username") or "").strip()
    password = str((svc or {}).get("proxy_password") or "").strip()
    enabled = bool(data.get("proxy_credentials_enabled")) if isinstance(data, dict) else False
    if not username or not password:
        raise Exception(
            f"未获取到代理账密: enabled={enabled}, username={username!r}, password={'***' if password else ''}"
        )
    if log_callback:
        log_callback(f"[*] 代理账密: {username} / {'*' * min(8, len(password))}")
    return {
        "proxy_username": username,
        "proxy_password": password,
        "proxy_credentials_enabled": enabled,
        "raw_service": svc or {},
        "overview_status": body.get("status") if isinstance(body, dict) else None,
    }


def _format_proxy_line(raw: str, username: str = "", password: str = "", fmt: str = "userpass") -> str:
    """把原始代理行格式化成目标样式。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    # 已是 user:pass@ip:port
    if "@" in s and ":" in s.split("@", 1)[0]:
        return s
    s = re.sub(r"^[a-zA-Z0-9+.-]+://", "", s)
    parts = s.split(":")
    hostport = s
    if len(parts) == 4 and not username:
        return f"{parts[0]}:{parts[1]}@{parts[2]}:{parts[3]}"
    if len(parts) >= 2:
        hostport = f"{parts[-2]}:{parts[-1]}"
    fmt = str(fmt or "userpass").strip().lower()
    if fmt in ("ipport", "ip:port", "hostport"):
        return hostport
    if username and password:
        return f"{username}:{password}@{hostport}"
    return hostport


def ps_download_proxy_list(
    access_token: str,
    account_id: str,
    *,
    protocol: str = "http",
    proxy_type: str = "datacenter_shared",
    fmt: str = "userpass",
    log_callback=None,
) -> List[str]:
    """下载代理列表并拼上代理账密，返回格式化后的代理行。"""
    protocol = str(protocol or _gr().config.get("ps_proxy_protocol") or "http").strip().lower()
    proxy_format = str(fmt or _gr().config.get("ps_proxy_format") or "userpass").strip().lower()
    account_id = str(account_id or "").strip()
    if not account_id:
        raise Exception("缺少 AccountID，无法下载代理列表")

    creds = {"proxy_username": "", "proxy_password": ""}
    if proxy_format not in ("ipport", "ip:port", "hostport"):
        try:
            creds = ps_fetch_proxy_credentials(
                access_token,
                account_id,
                protocol=protocol,
                proxy_type=proxy_type,
                log_callback=log_callback,
            )
        except Exception as ce:
            if log_callback:
                log_callback(f"[!] 读取代理账密失败，将仅保存 ip:port: {ce}")

    url = _ps_endpoint(f"/v4/account/{account_id}/{proxy_type}/proxy-list")
    headers = _ps_auth_headers(access_token)
    headers["Accept"] = "*/*"
    params = {"type": "getproxies", "protocol": protocol}
    if log_callback:
        log_callback(f"[*] 下载代理列表: {url}?type=getproxies&protocol={protocol}")
    resp = _http_get(url, headers=headers, params=params, timeout=45)
    text = resp.text or ""
    if resp.status_code >= 400 or "No protocol provided" in text or "Invalid protocol" in text:
        raise Exception(f"代理列表下载失败 HTTP {resp.status_code}: {text[:200]}")
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("{")]
    if not raw_lines:
        try:
            data = resp.json()
            if isinstance(data, list):
                raw_lines = [str(x) for x in data]
        except Exception:
            pass
    if not raw_lines:
        raise Exception(f"代理列表为空: content-type={resp.headers.get('content-type')} body={text[:160]}")

    username = str(creds.get("proxy_username") or "")
    password = str(creds.get("proxy_password") or "")
    lines = [
        _format_proxy_line(x, username=username, password=password, fmt=proxy_format)
        for x in raw_lines
    ]
    lines = [x for x in lines if x]
    if log_callback:
        sample = lines[0] if lines else ""
        if username and password and f"{username}:{password}@" in sample:
            sample = sample.replace(f"{username}:{password}@", f"{username}:****@")
        log_callback(f"[*] 代理格式: {proxy_format} | 示例: {sample}")
    return lines


def ps_failure_reason(result) -> str:
    """从响应 dict 提取可读失败文案。"""
    if not isinstance(result, dict):
        return ""
    return str(result.get("message") or result.get("error") or "").strip()
