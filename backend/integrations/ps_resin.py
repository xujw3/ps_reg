# -*- coding: utf-8 -*-
"""Resin 订阅入池客户端。

把 ProxyScrape 代理列表推送到自建 Resin 服务（/api/v1/subscriptions）。
HTTP 调用经 ``configure(**kwargs)`` 注入（engine 提供 http_post/http_get/http_delete），
配置读取延迟引用 ``backend.registration.engine.config``。
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

_deps: Dict[str, Any] = {}


def configure(**kwargs) -> None:
    _deps.update(kwargs)


def _gr():
    from backend.registration import engine as gr

    return gr


def resin_enabled() -> bool:
    """resin_base_url 与 resin_auth_token 均非空。"""
    cfg = _gr().config
    return bool(
        str(cfg.get("resin_base_url") or "").strip()
        and str(cfg.get("resin_auth_token") or "").strip()
    )


def _resin_subscription_name(email: str) -> str:
    """订阅名：用邮箱前缀。"""
    s = str(email or "").strip()
    if "@" in s:
        s = s.split("@", 1)[0]
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("._-")
    return s or f"ps_{int(time.time())}"


def _proxies_to_resin_content(proxies: list, scheme: str = "http") -> str:
    """把 user:pass@ip:port / ip:port 转成 http://user:pass@ip:port 多行文本。"""
    scheme = str(scheme or "http").strip() or "http"
    lines = []
    for raw in proxies or []:
        s = str(raw or "").strip()
        if not s:
            continue
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
            lines.append(s)
            continue
        lines.append(f"{scheme}://{s}")
    return "\n".join(lines)


def _resin_base_and_path() -> tuple[str, str]:
    base = str(_gr().config.get("resin_base_url") or "").strip().rstrip("/")
    path = str(
        _gr().config.get("resin_subscriptions_path") or "/api/v1/subscriptions"
    ).strip()
    if not path.startswith("/"):
        path = "/" + path
    if not base:
        raise Exception("resin_base_url 未配置")
    return base, path


def _resin_auth_headers(base: str) -> dict:
    token = str(_gr().config.get("resin_auth_token") or "").strip()
    if not token:
        raise Exception("resin_auth_token 未配置")
    headers = {
        "Accept": "application/json, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Origin": base,
        "Referer": f"{base}/ui/subscriptions",
        "User-Agent": str(_gr().config.get("user_agent") or ""),
        "authorization": f"Bearer {token}",
        "content-type": "application/json; charset=utf-8",
    }
    cookie = str(_gr().config.get("resin_cookie") or "").strip()
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _resin_request(method: str, url: str, **kwargs):
    """Resin API 请求：强制直连，可关 TLS 校验。"""
    timeout = float(_gr().config.get("resin_timeout") or 30)
    verify_tls = bool(_gr().config.get("resin_verify_tls", False))
    kwargs.setdefault("timeout", timeout)
    kwargs.setdefault("proxies", {})
    kwargs.setdefault("verify", verify_tls)
    method = method.upper()
    try:
        if method == "GET":
            return _deps["http_get"](url, **kwargs)
        if method == "POST":
            return _deps["http_post"](url, **kwargs)
        if method == "DELETE":
            return _deps["http_delete"](url, **kwargs)
        raise Exception(f"不支持的 resin 请求方法: {method}")
    except TypeError:
        kwargs.pop("verify", None)
        if method == "GET":
            return _deps["http_get"](url, **kwargs)
        if method == "POST":
            return _deps["http_post"](url, **kwargs)
        if method == "DELETE":
            return _deps["http_delete"](url, **kwargs)
        raise Exception(f"不支持的 resin 请求方法: {method}")


def resin_list_subscriptions(
    *,
    limit: int = 100,
    keyword: str = "",
    log_callback=None,
) -> List[dict]:
    """分页拉取 Resin 全部订阅，返回 items 列表。"""
    base, path = _resin_base_and_path()
    headers = _resin_auth_headers(base)
    offset = 0
    page_limit = max(1, min(int(limit or 100), 200))
    items: List[dict] = []
    while True:
        qs = [
            f"limit={page_limit}",
            f"offset={offset}",
            "sort_by=created_at",
            "sort_order=desc",
        ]
        if keyword:
            qs.append(f"keyword={quote(str(keyword))}")
        url = f"{base}{path}?{'&'.join(qs)}"
        resp = _resin_request("GET", url, headers=headers)
        body_text = ""
        try:
            body_text = resp.text or ""
        except Exception:
            body_text = ""
        try:
            body = resp.json()
        except Exception:
            body = {}
        if getattr(resp, "status_code", 500) >= 400:
            raise Exception(f"resin 列表失败 HTTP {resp.status_code}: {body_text[:300]}")
        page_items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(page_items, list):
            page_items = body if isinstance(body, list) else []
        items.extend([x for x in page_items if isinstance(x, dict)])
        total = int(body.get("total") or 0) if isinstance(body, dict) else len(items)
        offset += len(page_items)
        if not page_items or offset >= total or len(page_items) < page_limit:
            break
    if log_callback:
        log_callback(f"[*] resin 订阅数: {len(items)}")
    return items


def resin_delete_subscription(subscription_id: str, *, log_callback=None) -> dict:
    """DELETE /api/v1/subscriptions/{id}，从 Resin 移除订阅及其节点。"""
    sub_id = str(subscription_id or "").strip()
    if not sub_id:
        raise Exception("subscription_id 为空")
    base, path = _resin_base_and_path()
    headers = _resin_auth_headers(base)
    url = f"{base}{path}/{sub_id}"
    if log_callback:
        log_callback(f"[*] resin 删除订阅: {sub_id}")
    resp = _resin_request("DELETE", url, headers=headers)
    code = getattr(resp, "status_code", 500)
    if code in (200, 204, 404):
        if log_callback:
            log_callback(f"[+] resin 已删除订阅: {sub_id} status={code}")
        return {"ok": True, "status_code": code, "id": sub_id}
    body_text = ""
    try:
        body_text = resp.text or ""
    except Exception:
        body_text = ""
    raise Exception(f"resin 删除失败 HTTP {code}: {body_text[:300]}")


def resin_find_subscription_by_name(
    name: str, subscriptions: Optional[List[dict]] = None
) -> Optional[dict]:
    """按订阅名精确匹配（大小写不敏感）。"""
    target = str(name or "").strip().lower()
    if not target:
        return None
    subs = subscriptions if subscriptions is not None else resin_list_subscriptions()
    for sub in subs:
        if str(sub.get("name") or "").strip().lower() == target:
            return sub
    return None


def resin_push_subscription(
    email: str,
    proxies: list,
    *,
    name: str = "",
    log_callback=None,
) -> dict:
    """把代理列表推送到 Resin /api/v1/subscriptions。"""
    if not resin_enabled():
        raise Exception("resin 未配置（resin_base_url / resin_auth_token 缺失）")

    base, path = _resin_base_and_path()
    content = _proxies_to_resin_content(
        proxies,
        scheme=str(_gr().config.get("resin_proxy_scheme") or "http"),
    )
    if not content.strip():
        raise Exception("代理列表为空，无法 resin 入池")

    sub_name = str(name or _resin_subscription_name(email)).strip()
    url = f"{base}{path}"
    payload = {
        "name": sub_name,
        "source_type": str(_gr().config.get("resin_source_type") or "local"),
        "update_interval": str(_gr().config.get("resin_update_interval") or "12h"),
        "ephemeral_node_evict_delay": str(
            _gr().config.get("resin_ephemeral_node_evict_delay") or "72h"
        ),
        "enabled": bool(_gr().config.get("resin_enabled_flag", True)),
        "ephemeral": bool(_gr().config.get("resin_ephemeral", False)),
        "incremental_alive_nodes": bool(
            _gr().config.get("resin_incremental_alive_nodes", False)
        ),
        "content": content,
    }
    headers = _resin_auth_headers(base)
    if log_callback:
        log_callback(
            f"[*] resin 入池: {url} name={sub_name} proxies={len(content.splitlines())}"
        )

    resp = _resin_request("POST", url, headers=headers, json=payload)
    body_text = ""
    try:
        body_text = resp.text or ""
    except Exception:
        body_text = ""
    try:
        body = resp.json()
    except Exception:
        body = {"raw": body_text[:500]}

    if getattr(resp, "status_code", 500) >= 400:
        raise Exception(f"resin 入池失败 HTTP {resp.status_code}: {body_text[:300] or body}")
    if log_callback:
        log_callback(f"[+] resin 入池成功: name={sub_name} status={resp.status_code}")
    return {
        "ok": True,
        "status_code": resp.status_code,
        "name": sub_name,
        "id": str((body or {}).get("id") or "") if isinstance(body, dict) else "",
        "proxy_count": len(content.splitlines()),
        "response": body,
        "url": url,
    }
