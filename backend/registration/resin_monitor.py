# -*- coding: utf-8 -*-
"""Resin 监控：自动删除到期账号与订阅、自动补号到目标数量。

后台线程按 resin_monitor_interval 轮询：
1. 到期扫描：status=success 且 resin_status=success 且 expire_at 已过期的账号
   → 按订阅名（邮箱前缀）从 Resin 删除订阅 → 删除本地记录
2. 补号：有效账号数（success 且未到期）< resin_target_count
   → 通过 job_coordinator.start(缺口) 触发注册；已有任务在跑时跳过本轮
   （job_coordinator 为单任务模型，天然互斥）
"""
from __future__ import annotations

import collections
import datetime
import threading
from typing import Any, Callable, Deque, Dict, List, Optional

from backend.integrations import ps_resin as _resin


def parse_expire_at(value: Any) -> Optional[datetime.datetime]:
    """解析 expire_at 字符串；失败返回 None。"""
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


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def _gr():
    from backend.registration import engine as gr

    return gr


class ResinMonitor:
    """Resin 账号池维护线程。"""

    def __init__(
        self,
        *,
        coordinator: Any = None,
        log: Optional[Callable[[str], None]] = None,
    ):
        self._coordinator = coordinator
        self._external_log = log or (lambda m: None)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._logs: Deque[Dict[str, str]] = collections.deque(maxlen=50)
        self._last_summary = "未运行"
        self._last_checked_at = ""
        self._last_error = ""
        self._total_expired = 0
        self._total_topup = 0
        self._last_expired = 0
        self._last_topup = 0

    def _log(self, message: str) -> None:
        """写内部 ring 日志 + 外部回调。"""
        try:
            with self._lock:
                self._logs.append(
                    {
                        "time": datetime.datetime.now().astimezone().strftime("%H:%M:%S"),
                        "message": str(message or ""),
                    }
                )
        except Exception:
            pass
        try:
            self._external_log(str(message or ""))
        except Exception:
            pass

    def logs(self, limit: int = 50) -> List[Dict[str, str]]:
        with self._lock:
            return list(self._logs)[-max(1, min(int(limit or 50), 200)):]

    # ---------- 状态查询 ----------

    def store(self):
        return _gr().get_registration_repository()

    def collect_expired_accounts(self) -> List[Dict[str, Any]]:
        """返回已到期且已入池（resin_status=success）的账号记录。"""
        store = self.store()
        if store is None:
            return []
        now = _now()
        expired = []
        for row in store.list_results(status="success", limit=10000):
            if str(row.get("resin_status") or "") != "success":
                continue
            expire_at = parse_expire_at(row.get("expire_at"))
            if expire_at is not None and expire_at < now:
                expired.append(row)
        return expired

    def _topup_lead_delta(self) -> datetime.timedelta:
        """补号提前量：到期前 N 小时内的账号即视为待补缺口。"""
        try:
            hours = float(_gr().config.get("resin_topup_lead_hours") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        return datetime.timedelta(hours=max(0.0, hours))

    def count_active(self) -> int:
        """有效账号数：status=success 且剩余有效期大于补号提前量。

        剩余时间不足提前量（含已到期）的账号不计入有效，
        从而在完全失效前就触发补号，避免空窗。
        """
        store = self.store()
        if store is None:
            return 0
        now = _now()
        threshold = now + self._topup_lead_delta()
        active = 0
        for row in store.list_results(status="success", limit=10000):
            expire_at = parse_expire_at(row.get("expire_at"))
            if expire_at is None or expire_at >= threshold:
                active += 1
        return active

    # ---------- 到期删除 ----------

    def delete_expired(self) -> int:
        """删除到期账号：先删 Resin 订阅，再删本地记录。返回删除数。"""
        removed = 0
        for row in self.collect_expired_accounts():
            email = str(row.get("email") or "")
            rid = row.get("id")
            try:
                name = _resin._resin_subscription_name(email)
                subs = _resin.resin_list_subscriptions()
                sub = _resin.resin_find_subscription_by_name(name, subs)
                if sub:
                    sid = str(sub.get("id") or "")
                    if sid:
                        _resin.resin_delete_subscription(sid)
                        self._log(f"[Resin监控] 已删除 Resin 订阅 {name} (id={sid})")
                self.store().delete_results([rid])
                self._log(f"[Resin监控] 已删除到期账号 {email}")
                removed += 1
            except Exception as exc:
                self._log(f"[Resin监控] 删除到期账号 {email} 失败（下轮重试）: {exc}")
        return removed

    # ---------- 自动补号 ----------

    def topup_if_needed(self) -> int:
        """有效账号数 < 目标数时通过 job_coordinator 补号；返回触发数量。"""
        gr = _gr()
        target = int(gr.config.get("resin_target_count") or 0)
        if target <= 0:
            return 0
        active = self.count_active()
        gap = max(target - active, 0)
        if gap <= 0:
            return 0
        coordinator = self._coordinator
        if coordinator is None:
            self._log("[Resin监控] 未注入任务协调器，跳过补号")
            return 0
        try:
            if coordinator.status().get("running"):
                self._log(f"[Resin监控] 已有注册任务在运行，跳过补号（有效 {active}/{target}）")
                return 0
        except Exception as exc:
            self._log(f"[Resin监控] 查询任务状态失败: {exc}")
            return 0
        self._log(f"[Resin监控] 有效账号 {active}/{target}，自动补号 {gap} 个")
        try:
            coordinator.start(count=gap, workers=1)
            return gap
        except Exception as exc:
            self._log(f"[Resin监控] 触发补号失败: {exc}")
            return 0

    # ---------- 主循环 ----------

    def check_once(self) -> Dict[str, str]:
        """手动/轮询触发一次检查；线程安全（可与监控线程并发调用）。"""
        with self._lock:
            result: Dict[str, str] = {"expired": "0", "topup": "0"}
            gr = _gr()
            if not _resin.resin_enabled():
                self._last_checked_at = _now().strftime("%Y-%m-%d %H:%M:%S")
                self._last_summary = "Resin 未配置（resin_base_url / resin_auth_token 缺失），跳过"
                return result
            if bool(gr.config.get("resin_monitor_enabled", False)) is False:
                self._last_checked_at = _now().strftime("%Y-%m-%d %H:%M:%S")
                self._last_summary = "监控未启用（resin_monitor_enabled=false）"
                return result
            try:
                if bool(gr.config.get("resin_delete_expired", True)):
                    expired = self.delete_expired()
                    result["expired"] = str(expired)
                    self._last_expired = expired
                    self._total_expired += expired
            except Exception as exc:
                self._last_error = str(exc)
                self._log(f"[Resin监控] 到期清理异常: {exc}")
            try:
                topup = self.topup_if_needed()
                result["topup"] = str(topup)
                self._last_topup = topup
                self._total_topup += topup
            except Exception as exc:
                self._last_error = str(exc)
                self._log(f"[Resin监控] 补号异常: {exc}")
            self._last_checked_at = _now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_summary = (
                f"到期删除 {result.get('expired', '0')} | 补号 {result.get('topup', '0')}"
            )
            return result

    def run_loop(self) -> None:
        while True:
            try:
                interval = int(_gr().config.get("resin_monitor_interval") or 600)
            except (TypeError, ValueError):
                interval = 600
            if self._stop.wait(max(interval, 10)):
                break
            try:
                self.check_once()
            except Exception as exc:
                self._log(f"[Resin监控] 轮询异常: {exc}")

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self.run_loop,
                name="resin-monitor",
                daemon=True,
            )
            self._thread.start()
            self._log("[Resin监控] 已启动（自动清理到期账号/订阅 + 补号）")

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        self._log("[Resin监控] 已停止")

    def status(self) -> Dict[str, Any]:
        """Web API 用：监控运行状态与统计。"""
        gr = _gr()
        running = bool(self._thread and self._thread.is_alive())
        target = int(gr.config.get("resin_target_count") or 0)
        active = self.count_active() if running or target > 0 else 0
        return {
            "enabled": bool(gr.config.get("resin_monitor_enabled", False)),
            "resin_configured": bool(_resin.resin_enabled()),
            "running": running,
            "interval": int(gr.config.get("resin_monitor_interval") or 600),
            "target_count": target,
            "delete_expired": bool(gr.config.get("resin_delete_expired", True)),
            "active": active,
            "gap": max(target - active, 0) if target > 0 else 0,
            "summary": self._last_summary,
            "last_checked_at": self._last_checked_at,
            "last_error": self._last_error,
            "last_expired": self._last_expired,
            "last_topup": self._last_topup,
            "total_expired": self._total_expired,
            "total_topup": self._total_topup,
            "logs": self.logs(50),
        }
