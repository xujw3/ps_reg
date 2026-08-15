# -*- coding: utf-8 -*-
"""号池快照测试：本地账号 × Resin 远端订阅对齐。

验证 build_pool_snapshot 的远端订阅读取、订阅名匹配、
状态分类（有效/即将到期/过期/未知）、孤儿订阅与失败降级。
"""
import datetime
import unittest
from unittest import mock

from backend.integrations import ps_resin as _resin
from backend.registration import engine as gr
from backend.registration.pool_snapshot import build_pool_snapshot

VALID_DAYS = 7


def _future(days=3):
    return (datetime.datetime.now().astimezone()
            + datetime.timedelta(days=days)).isoformat()


def _past(days=1):
    return (datetime.datetime.now().astimezone()
            - datetime.timedelta(days=days)).isoformat()


def _row(rid, email, expire_at, resin_status="success"):
    return {
        "id": rid,
        "email": email,
        "password": "pw",
        "created_at": _past(),
        "expire_at": expire_at,
        "status": "success",
        "resin_status": resin_status,
        "proxy_file": "",
    }


def _set_rows(store, rows):
    store.list_results.return_value = rows


class PoolSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._store = mock.Mock()
        self._store_patcher = mock.patch.object(
            gr, "get_registration_repository", return_value=self._store
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)

    def test_aligns_accounts_with_remote_subscriptions_by_name(self):
        gr.config["account_valid_days"] = VALID_DAYS
        _set_rows(self._store, [
            _row(1, "active@dgu.edu.kg", _future()),
            _row(2, "expired@dgu.edu.kg", _past(), resin_status="failed"),
        ])
        subs = [
            {"id": "sub-active", "name": "active", "enabled": True,
             "node_count": 5, "healthy_node_count": 4},
            {"id": "sub-expired", "name": "expired", "enabled": True,
             "node_count": 3, "healthy_node_count": 0},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs):
            snap = build_pool_snapshot()
        self.assertEqual(snap["resin_error"], "")
        self.assertEqual(snap["stats"]["total"], 2)
        self.assertEqual(snap["stats"]["active"], 1)
        self.assertEqual(snap["stats"]["expired"], 1)
        self.assertEqual(snap["stats"]["in_resin"], 2)
        self.assertEqual(snap["stats"]["expired_still_in_resin"], 1)
        self.assertEqual(snap["stats"]["node_count_sum"], 8)
        self.assertEqual(snap["stats"]["healthy_node_count_sum"], 4)
        by_email = {it["email"]: it for it in snap["items"]}
        self.assertTrue(by_email["active@dgu.edu.kg"]["in_resin"])
        self.assertEqual(by_email["active@dgu.edu.kg"]["resin_id"], "sub-active")
        self.assertEqual(by_email["active@dgu.edu.kg"]["node_count"], 5)
        self.assertEqual(by_email["expired@dgu.edu.kg"]["resin_status"], "failed")
        self.assertLess(by_email["expired@dgu.edu.kg"]["remaining_sec"], 0)

    def test_not_in_resin_when_subscription_missing(self):
        _set_rows(self._store, [_row(1, "nobody@dgu.edu.kg", _future())])
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=[]):
            snap = build_pool_snapshot()
        self.assertEqual(snap["stats"]["in_resin"], 0)
        self.assertEqual(snap["stats"]["not_in_resin"], 1)
        self.assertFalse(snap["items"][0]["in_resin"])
        self.assertEqual(snap["items"][0]["resin_id"], "")

    def test_orphans_are_remote_subscriptions_without_local_account(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        subs = [
            {"id": "sub-1", "name": "active", "node_count": 4,
             "healthy_node_count": 4},
            {"id": "sub-2", "name": "stale_node", "node_count": 1,
             "healthy_node_count": 0},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs):
            snap = build_pool_snapshot()
        self.assertEqual(snap["stats"]["resin_orphan"], 1)
        self.assertEqual(snap["resin_orphans"][0]["id"], "sub-2")
        self.assertEqual(snap["resin_orphans"][0]["name"], "stale_node")

    def test_resin_fetch_failure_sets_error_but_keeps_local_data(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  side_effect=RuntimeError("resin 500")):
            snap = build_pool_snapshot()
        self.assertIn("resin 500", snap["resin_error"])
        self.assertEqual(snap["stats"]["total"], 1)
        self.assertEqual(snap["stats"]["in_resin"], 0)
        self.assertEqual(snap["resin_orphans"], [])

    def test_expiring_soon_classification_with_threshold(self):
        gr.config["resin_expiring_soon_hours"] = 24
        _set_rows(self._store, [
            _row(1, "soon@dgu.edu.kg", _future(days=0.5)),
            _row(2, "later@dgu.edu.kg", _future(days=3)),
            _row(3, "noexpire@dgu.edu.kg", ""),
        ])
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=[]):
            snap = build_pool_snapshot()
        stats = snap["stats"]
        self.assertEqual(stats["expiring_soon"], 1)
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["unknown_expire"], 1)
        by_email = {it["email"]: it for it in snap["items"]}
        self.assertEqual(by_email["soon@dgu.edu.kg"]["status"], "expiring_soon")
        self.assertGreater(by_email["soon@dgu.edu.kg"]["remaining_sec"], 0)
        self.assertEqual(by_email["noexpire@dgu.edu.kg"]["status"], "unknown")
        self.assertIsNone(by_email["noexpire@dgu.edu.kg"]["remaining_sec"])

    def test_skips_resin_fetch_when_not_enabled(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        with mock.patch.object(_resin, "resin_enabled", return_value=False), \
                mock.patch.object(_resin, "resin_list_subscriptions") \
                as list_mock:
            snap = build_pool_snapshot(fetch_resin=True)
        list_mock.assert_not_called()
        self.assertEqual(snap["resin_error"], "")
        self.assertEqual(snap["stats"]["resin_total"], 0)


if __name__ == "__main__":
    unittest.main()
