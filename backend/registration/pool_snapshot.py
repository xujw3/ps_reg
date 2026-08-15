# -*- coding: utf-8 -*-
"""号池快照：本地账号记录 × Resin 远端订阅对齐。

读取远端 Resin 订阅列表（resin_list_subscriptions），按订阅名（邮箱前缀）
与本地成功账号比对，输出每个账号的入池状态 / 节点健康数、池统计与孤儿订阅。
供 Web UI「Resin 监控」页展示远端真实状态（参考号池监控 pool_webui）。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import threading
from pathlib import Path
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


# ── 孤儿订阅保护名单（勾选后不参与批量/自动清理） ──

_protect_lock = threading.Lock()


def _protected_file() -> str:
    from backend.shared.paths import DATA_ROOT

    return os.path.join(str(DATA_ROOT), "resin_orphan_protected.json")


def _load_protected() -> Dict[str, dict]:
    try:
        with open(_protected_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_protected(data: Dict[str, dict]) -> None:
    target = Path(_protected_file())
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def is_orphan_protected(sub_id: str) -> bool:
    with _protect_lock:
        return bool(_load_protected().get(str(sub_id)))


def set_orphan_protected(sub_id: str, name: str, protected: bool) -> bool:
    """勾选/取消孤儿订阅保护；返回最终保护状态。"""
    with _protect_lock:
        data = _load_protected()
        key = str(sub_id)
        if protected:
            data[key] = {
                "name": str(name or ""),
                "protected_at": datetime.datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
            }
        else:
            data.pop(key, None)
        _save_protected(data)
        return key in data


def _sub_int(sub: Optional[dict], key: str, default: int = 0) -> int:
    return int(sub.get(key) or 0) if sub else default


def _sub_str(sub: Optional[dict], key: str, default: str = "") -> str:
    return str(sub.get(key) or "") if sub else default


def _short_resin_status(value: Any) -> str:
    """本地入池记录状态列：完整错误文本（failed: <长错误>）压成短状态。"""
    raw = str(value or "").strip()
    if raw.startswith("failed:"):
        return "failed"
    if len(raw) > 20:
        return raw[:20]
    return raw


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
                "resin_status": _short_resin_status(row.get("resin_status")),
                "in_resin": in_resin,
                "resin_id": _sub_str(sub, "id"),
                "resin_enabled": bool(sub.get("enabled")) if sub else False,
                "node_count": _sub_int(sub, "node_count"),
                "healthy_node_count": _sub_int(sub, "healthy_node_count"),
                "resin_created_at": _sub_str(sub, "created_at"),
                "resin_last_updated": _sub_str(sub, "last_updated"),
                "proxy_file": proxy_path,
                "proxy_file_exists": proxy_exists,
            }
        )

    orphans: List[dict] = []
    protected_map = _load_protected()
    valid_days = int(gr.config.get("account_valid_days") or 7)
    for sub in resin_subs:
        name = str(sub.get("name") or "").strip()
        if name.lower() in matched_names:
            continue
        created_dt = _parse_dt(sub.get("created_at"))
        expire_at = ""
        if created_dt is not None:
            expire_at = (created_dt + datetime.timedelta(days=valid_days)).isoformat(
                timespec="seconds"
            )
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
                "expire_at": expire_at,
                "protected": str(sub.get("id") or "") in protected_map,
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


def _proxy_list_path_for_email(email: str) -> Optional[str]:
    """按 save_proxy_list_file 的命名规则推导代理文件路径。"""
    from backend.shared.paths import PROJECT_ROOT

    gr = _gr()
    proxy_dir = str(gr.config.get("ps_proxy_list_dir") or "data/proxy_lists").strip()
    root = Path(proxy_dir).expanduser()
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    safe = re.sub(r"[^A-Za-z0-9._@-]+", "_", str(email or "unknown").strip()) or "unknown"
    return str(root / f"{safe}.http.txt")


def delete_proxy_list_file(email: str) -> bool:
    """删除邮箱对应的本地代理文件；文件不存在返回 False。"""
    path = _proxy_list_path_for_email(email)
    if not path or not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _delete_local_proxy_file(row: dict) -> bool:
    """按 store 行记录的路径删除代理文件（行里没有则按命名规则）。"""
    recorded = str(row.get("proxy_file") or "").strip()
    if recorded and os.path.isfile(recorded):
        try:
            os.remove(recorded)
            return True
        except OSError:
            return False
    return delete_proxy_list_file(str(row.get("email") or ""))


def cleanup_expired_pool(
    *,
    dry_run: bool = False,
    also_delete_orphans: bool = False,
    log_callback=None,
) -> dict:
    """批量清理：过期且在池的账号删 Resin 订阅，可选删代理文件/本地记录；
    可选同时删除 Resin 孤儿订阅。dry_run 只统计不执行。"""
    log = log_callback or (lambda m: None)
    gr = _gr()
    store = gr.get_registration_repository()
    delete_proxy_files = bool(gr.config.get("resin_delete_proxy_files", True))
    remove_records = bool(gr.config.get("resin_remove_expired_records", False))

    snap = build_pool_snapshot(fetch_resin=True)
    if snap.get("resin_error"):
        raise Exception(f"无法连接 Resin: {snap['resin_error']}")

    deleted: List[dict] = []
    errors: List[dict] = []
    skipped: List[dict] = []

    row_by_id = {}
    if store is not None and not dry_run:
        for row in store.list_results(status="success", limit=10000):
            row_by_id[int(row.get("id") or 0)] = row

    for item in snap["items"]:
        if item["status"] != "expired":
            continue
        if not item.get("in_resin") or not item.get("resin_id"):
            skipped.append(
                {
                    "email": item["email"],
                    "reason": "not_in_resin",
                    "resin_name": item.get("resin_name"),
                }
            )
            continue
        entry = {
            "email": item["email"],
            "resin_name": item["resin_name"],
            "resin_id": item["resin_id"],
            "expire_at": item.get("expire_at"),
            "node_count": item.get("node_count"),
        }
        if dry_run:
            entry["dry_run"] = True
            deleted.append(entry)
            continue
        try:
            _resin.resin_delete_subscription(item["resin_id"])
            if delete_proxy_files:
                row = row_by_id.get(int(item.get("id") or 0)) or {}
                _delete_local_proxy_file(row)
            if remove_records and store is not None:
                store.delete_results([int(item.get("id") or 0)])
            entry["ok"] = True
            deleted.append(entry)
            log(f"[Resin监控] 已清理过期 {item['email']}（订阅 {item['resin_id']}）")
        except Exception as exc:
            errors.append({**entry, "error": str(exc)})
            log(f"[Resin监控] 清理失败 {item['email']}: {exc}")

    orphan_deleted: List[dict] = []
    if also_delete_orphans:
        protected_map = _load_protected()
        for orphan in snap.get("resin_orphans") or []:
            oid = orphan.get("id")
            if not oid:
                continue
            if oid in protected_map:
                log(f"[Resin监控] 跳过受保护孤儿订阅 {orphan.get('name')}")
                continue
            if dry_run:
                orphan_deleted.append({**orphan, "dry_run": True})
                continue
            try:
                _resin.resin_delete_subscription(oid)
                orphan_deleted.append({**orphan, "ok": True})
                log(f"[Resin监控] 已删除孤儿订阅 {orphan.get('name')}")
            except Exception as exc:
                errors.append(
                    {
                        "email": "",
                        "resin_name": orphan.get("name"),
                        "resin_id": oid,
                        "error": str(exc),
                    }
                )

    result = {
        "ok": True,
        "dry_run": bool(dry_run),
        "generated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "deleted_count": len(deleted),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "orphan_deleted_count": len(orphan_deleted),
        "deleted": deleted,
        "errors": errors,
        "skipped": skipped,
        "orphan_deleted": orphan_deleted,
        "stats_before": snap["stats"],
    }
    log(
        f"[+] 过期清理完成: deleted={len(deleted)} errors={len(errors)} "
        f"skipped={len(skipped)} orphans={len(orphan_deleted)}"
    )
    return result
