# -*- coding: utf-8 -*-
"""Resin 监控逻辑测试：到期删除订阅/账号、自动补号。"""
import datetime
import unittest
from unittest import mock

from backend.integrations import ps_resin as _resin
from backend.registration import engine as gr
from backend.registration.resin_monitor import ResinMonitor, parse_expire_at


def _row(rid, email, expire_at, resin_status="success", status="success"):
    return {
        "id": rid,
        "email": email,
        "expire_at": expire_at,
        "resin_status": resin_status,
        "status": status,
    }


def _future(days=3):
    return (datetime.datetime.now().astimezone() + datetime.timedelta(days=days)).isoformat()


def _past(days=1):
    return (datetime.datetime.now().astimezone() - datetime.timedelta(days=days)).isoformat()


class ParseExpireAtTests(unittest.TestCase):
    def test_parses_iso_with_and_without_tz(self):
        self.assertIsNotNone(parse_expire_at("2026-08-20T10:00:00+08:00"))
        self.assertIsNotNone(parse_expire_at("2026-08-20T10:00:00"))
        self.assertIsNone(parse_expire_at(""))
        self.assertIsNone(parse_expire_at("not-a-date"))
        self.assertIsNone(parse_expire_at(None))


class ResinMonitorTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.monitor = ResinMonitor(coordinator=mock.Mock(), log=self.logs.append)
        self._store = mock.Mock()
        self._store_patcher = mock.patch.object(
            gr, "get_registration_repository", return_value=self._store
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)

    def test_collect_expired_only_resin_success_and_expired(self):
        self._store.list_results.return_value = [
            _row(1, "expired@dgu.edu.kg", _past()),
            _row(2, "active@dgu.edu.kg", _future()),
            _row(3, "no-resin@dgu.edu.kg", _past(), resin_status="skipped"),
            _row(4, "no-expire@dgu.edu.kg", ""),
        ]
        expired = self.monitor.collect_expired_accounts()
        self.assertEqual([r["id"] for r in expired], [1])
        self._store.list_results.assert_called_once_with(status="success", limit=10000)

    def test_count_active_counts_not_expired(self):
        self._store.list_results.return_value = [
            _row(1, "expired@dgu.edu.kg", _past()),
            _row(2, "active@dgu.edu.kg", _future()),
            _row(3, "no-expire@dgu.edu.kg", ""),
        ]
        self.assertEqual(self.monitor.count_active(), 2)

    def test_count_active_counts_lead_window_as_inactive(self):
        """到期前 12 小时内（含已到期）的账号不计入有效 → 提前补号。"""
        gr.config["resin_topup_lead_hours"] = 12
        self._store.list_results.return_value = [
            _row(1, "lead@dgu.edu.kg", _future(days=0.4)),  # 剩余 ~9.6h
            _row(2, "ok@dgu.edu.kg", _future(days=2)),
        ]
        self.assertEqual(self.monitor.count_active(), 1)

    def test_topup_lead_zero_preserves_old_behavior(self):
        """提前量为 0 时：完全到期才算无效（旧行为）。"""
        gr.config["resin_topup_lead_hours"] = 0
        self._store.list_results.return_value = [
            _row(1, "lead@dgu.edu.kg", _future(days=0.4)),
            _row(2, "expired@dgu.edu.kg", _past()),
        ]
        self.assertEqual(self.monitor.count_active(), 1)

    def test_topup_gap_includes_lead_window_accounts(self):
        """目标 3：2 个远期 + 1 个 12h 内到期 → 缺口 2（含提前量）。"""
        gr.config["resin_topup_lead_hours"] = 12
        gr.config["resin_target_count"] = 3
        self._store.list_results.return_value = [
            _row(1, "lead@dgu.edu.kg", _future(days=0.4)),
            _row(2, "ok1@dgu.edu.kg", _future(days=2)),
            _row(3, "ok2@dgu.edu.kg", _future(days=3)),
        ]
        self.monitor._coordinator.status.return_value = {"running": False}
        gap = self.monitor.topup_if_needed()
        self.assertEqual(gap, 1)
        self.monitor._coordinator.start.assert_called_once_with(count=1, workers=1)

    def test_delete_expired_removes_subscription_and_record(self):
        self._store.list_results.return_value = [
            _row(1, "expired@dgu.edu.kg", _past()),
        ]
        with mock.patch.object(
            _resin, "resin_list_subscriptions",
            return_value=[{"id": "sub-1", "name": "expired"}],
        ) as list_mock, mock.patch.object(
            _resin, "resin_delete_subscription", return_value={"ok": True}
        ) as delete_mock:
            removed = self.monitor.delete_expired()
            delete_mock.assert_called_once_with("sub-1")
        self.assertEqual(removed, 1)
        list_mock.assert_called_once()
        self._store.delete_results.assert_called_once_with([1])
        self.assertTrue(any("已删除到期账号 expired@dgu.edu.kg" in m for m in self.logs))

    def test_delete_expired_keeps_record_when_subscription_delete_fails(self):
        self._store.list_results.return_value = [
            _row(1, "expired@dgu.edu.kg", _past()),
        ]
        with mock.patch.object(
            _resin, "resin_list_subscriptions",
            return_value=[{"id": "sub-1", "name": "expired"}],
        ), mock.patch.object(
            _resin, "resin_delete_subscription", side_effect=RuntimeError("resin 500")
        ):
            removed = self.monitor.delete_expired()
        self.assertEqual(removed, 0)
        self._store.delete_results.assert_not_called()
        self.assertTrue(any("删除到期账号 expired@dgu.edu.kg 失败" in m for m in self.logs))

    def test_topup_skips_when_target_met_or_zero(self):
        gr.config["resin_target_count"] = 0
        self.assertEqual(self.monitor.topup_if_needed(), 0)
        self._store.list_results.return_value = [_row(1, "a@dgu.edu.kg", _future())]
        gr.config["resin_target_count"] = 2
        self.monitor._coordinator.status.return_value = {"running": True}
        self.assertEqual(self.monitor.topup_if_needed(), 0)
        self.monitor._coordinator.start.assert_not_called()

    def test_topup_starts_job_with_gap(self):
        self._store.list_results.return_value = [_row(1, "a@dgu.edu.kg", _future())]
        gr.config["resin_target_count"] = 5
        self.monitor._coordinator.status.return_value = {"running": False}
        gap = self.monitor.topup_if_needed()
        self.assertEqual(gap, 4)
        self.monitor._coordinator.start.assert_called_once_with(count=4, workers=1)

    def test_check_once_skips_when_resin_disabled(self):
        gr.config["resin_monitor_enabled"] = True
        with mock.patch.object(_resin, "resin_enabled", return_value=False):
            result = self.monitor.check_once()
        self.assertEqual(result, {"expired": "0", "topup": "0"})
        self._store.list_results.assert_not_called()

    def test_check_once_skips_when_monitor_disabled(self):
        gr.config["resin_monitor_enabled"] = False
        with mock.patch.object(_resin, "resin_enabled", return_value=True):
            result = self.monitor.check_once()
        self.assertEqual(result, {"expired": "0", "topup": "0"})
        self._store.list_results.assert_not_called()
        self.assertEqual(self.monitor._last_summary, "监控未启用（resin_monitor_enabled=false）")
        self.assertTrue(self.monitor._last_checked_at)

    def test_check_once_records_expired_and_topup_stats(self):
        gr.config["resin_monitor_enabled"] = True
        gr.config["resin_target_count"] = 3
        self._store.list_results.side_effect = [
            # delete_expired 的 collect
            [_row(1, "expired@dgu.edu.kg", _past())],
            # count_active（delete 后）+ topup 的 count_active
            [_row(2, "active@dgu.edu.kg", _future())],
            [_row(2, "active@dgu.edu.kg", _future())],
        ]
        self.monitor._coordinator.status.return_value = {"running": False}
        with mock.patch.object(
            _resin, "resin_list_subscriptions", return_value=[]
        ), mock.patch.object(
            _resin, "resin_enabled", return_value=True
        ):
            result = self.monitor.check_once()
        self.assertEqual(result["expired"], "1")
        self.assertEqual(result["topup"], "2")
        self.assertEqual(self.monitor._total_expired, 1)
        self.assertEqual(self.monitor._total_topup, 2)
        self.assertEqual(self.monitor._last_expired, 1)
        self.assertEqual(self.monitor._last_topup, 2)
        self.assertTrue(self.monitor._last_checked_at)
        self.assertEqual(self.monitor._last_summary, "到期删除 1 | 补号 2")

    def test_status_reports_running_stats_and_logs(self):
        gr.config["resin_monitor_enabled"] = True
        gr.config["resin_target_count"] = 5
        self._store.list_results.return_value = [_row(1, "a@dgu.edu.kg", _future())]
        with mock.patch.object(_resin, "resin_enabled", return_value=True):
            status = self.monitor.status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["resin_configured"])
        self.assertFalse(status["running"])
        self.assertEqual(status["target_count"], 5)
        self.assertEqual(status["active"], 1)
        self.assertEqual(status["gap"], 4)
        self.assertEqual(status["summary"], "未运行")
        self.assertIsInstance(status["logs"], list)
        self.monitor._log("测试日志")
        self.assertTrue(any("测试日志" in entry["message"] for entry in self.monitor.logs()))
        self.assertTrue(all(entry.get("time") for entry in self.monitor.logs()))


if __name__ == "__main__":
    unittest.main()
