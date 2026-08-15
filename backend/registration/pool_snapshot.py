# -*- coding: utf-8 -*-
"""号池快照：本地账号记录 × Resin 远端订阅对齐。

读取远端 Resin 订阅列表（resin_list_subscriptions），按订阅名（邮箱前缀）
与本地成功账号比对，输出每个账号的入池状态 / 节点健康数、池统计与孤儿订阅。
供 Web UI「Resin 监控」页展示远端真实状态（参考号池监控 pool_webui）。
"""
from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from backend.integrations import ps_resin as _resin


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _parse_dt(value: Any) -> Optional[datetime.datetime]:
    """解析时间字符串；失败返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def _gr():
    from backend.registration import engine as gr

    return gr


def _sub_int(sub: Optional[dict], key: str, default: int = 0) -> int:
    return int(sub.get(key) or 0) if sub else default


def _sub_str(sub: Optional[dict], key: str, default: str = "") -> str:
    return str(sub.get(key) or "") if sub else default


def build_pool_snapshot(
    *, fetch_resin: bool = True, limit: int = 10000
) -> Dict[str, Any]:
    """号池快照：本地成功账号 + Resin 远端订阅对齐状态。"""
    gr = _gr()
    store = gr.get_registration_repository()
    now = _now()
    try:
        soon_hours = float(gr.config.get("resin_expiring_soon_hours") or 24)
    except (TypeError, ValueError):
        soon_hours = 24.0
    soon_delta = datetime.timedelta(hours=max(0.0, soon_hours))

    rows = []
    if store is not None:
        rows = store.list_results(status="success", limit=limit)

    resin_error = ""
    resin_subs: List[dict] = []
    if fetch_resin and _resin.resin_enabled():
        try:
            resin_subs = _resin.resin_list_subscriptions()
        except Exception as exc:
            resin_error = str(exc)

    by_name: Dict[str, dict] = {}
    for sub in resin_subs:
        name = str(sub.get("name") or "").strip().lower()
        if name and name not in by_name:
            by_name[name] = sub

    stats = {
        "total": 0,
        "active": 0,
        "expiring_soon": 0,
        "expired": 0,
        "unknown_expire": 0,
        "in_resin": 0,
        "not_in_resin": 0,
        "expired_still_in_resin": 0,
        "resin_total": len(resin_subs),
        "resin_orphan": 0,
        "proxy_file_exists": 0,
        "node_count_sum": 0,
        "healthy_node_count_sum": 0,
    }

    matched_names: set = set()
    items: List[dict] = []
    for row in rows:
        email = str(row.get("email") or "")
        resin_name = _resin._resin_subscription_name(email)
        expire_dt = _parse_dt(row.get("expire_at"))
        status = "unknown"
        remaining_sec = None
        if expire_dt is None:
            status = "unknown"
            stats["unknown_expire"] += 1
        elif expire_dt <= now:
            status = "expired"
            stats["expired"] += 1
            remaining_sec = int((expire_dt - now).total_seconds())
        elif expire_dt <= now + soon_delta:
            status = "expiring_soon"
            stats["expiring_soon"] += 1
            remaining_sec = int((expire_dt - now).total_seconds())
        else:
            status = "active"
            stats["active"] += 1
            remaining_sec = int((expire_dt - now).total_seconds())

        sub = by_name.get(resin_name.lower())
        in_resin = sub is not None
        if in_resin:
            matched_names.add(resin_name.lower())
            stats["in_resin"] += 1
            if status == "expired":
                stats["expired_still_in_resin"] += 1
            stats["node_count_sum"] += int(sub.get("node_count") or 0)
            stats["healthy_node_count_sum"] += int(sub.get("healthy_node_count") or 0)
        else:
            stats["not_in_resin"] += 1

        proxy_path = str(row.get("proxy_file") or "").strip()
        proxy_exists = bool(proxy_path) and os.path.isfile(proxy_path)
        if proxy_exists:
            stats["proxy_file_exists"] += 1

        stats["total"] += 1
        items.append(
            {
                "id": row.get("id"),
                "email": email,
                "created_at": str(row.get("created_at") or ""),
                "expire_at": str(row.get("expire_at") or ""),
                "status": status,
                "remaining_sec": remaining_sec,
                "resin_name": resin_name,
                "resin_status": str(row.get("resin_status") or ""),
                "in_resin": in_resin,
                "resin_id": _sub_str(sub, "id"),
                "resin_enabled": bool(sub.get("enabled")) if sub else False,
                "node_count": _sub_int(sub, "node_count"),
                "healthy_node_count": _sub_int(sub, "healthy_node_count"),
                "resin_created_at": _sub_str(sub, "created_at"),
                "resin_last_updated": _sub_str(sub, "last_updated"),
                "proxy_file_exists": proxy_exists,
            }
        )

    orphans: List[dict] = []
    for sub in resin_subs:
        name = str(sub.get("name") or "").strip()
        if name.lower() in matched_names:
            continue
        orphans.append(
            {
                "id": _sub_str(sub, "id"),
                "name": name,
                "enabled": bool(sub.get("enabled")),
                "source_type": _sub_str(sub, "source_type"),
                "node_count": _sub_int(sub, "node_count"),
                "healthy_node_count": _sub_int(sub, "healthy_node_count"),
                "created_at": _sub_str(sub, "created_at"),
                "last_updated": _sub_str(sub, "last_updated"),
            }
        )
    stats["resin_orphan"] = len(orphans)

    items.sort(
        key=lambda x: (
            {"expired": 0, "expiring_soon": 1, "active": 2, "unknown": 3}.get(
                x["status"], 9
            ),
            x.get("expire_at") or "",
            x.get("email") or "",
        )
    )
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "resin_base_url": str(gr.config.get("resin_base_url") or ""),
        "resin_error": resin_error,
        "stats": stats,
        "items": items,
        "resin_orphans": orphans,
        "valid_days": int(gr.config.get("account_valid_days") or 7),
        "expiring_soon_hours": soon_hours,
    }
