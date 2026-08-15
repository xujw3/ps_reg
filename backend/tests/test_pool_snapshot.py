# -*- coding: utf-8 -*-
"""号池快照测试：本地账号 × Resin 远端订阅对齐。

验证 build_pool_snapshot 的远端订阅读取、订阅名匹配、
状态分类（有效/即将到期/过期/未知）、孤儿订阅与失败降级。
"""
import datetime
import os
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


class CleanupExpiredPoolTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from backend.registration import pool_snapshot as ps

        self._ps = ps
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store = mock.Mock()
        self._store_patcher = mock.patch.object(
            gr, "get_registration_repository", return_value=self._store
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)
        gr.config["ps_proxy_list_dir"] = self._tmp.name
        gr.config["resin_delete_proxy_files"] = True
        gr.config["resin_remove_expired_records"] = False

    def _expired_row(self, rid, email):
        return _row(rid, email, _past())

    def test_dry_run_counts_without_deleting(self):
        _set_rows(self._store, [
            self._expired_row(1, "expired@dgu.edu.kg"),
            _row(2, "active@dgu.edu.kg", _future()),
        ])
        subs = [
            {"id": "sub-1", "name": "expired", "node_count": 3,
             "healthy_node_count": 2},
            {"id": "sub-2", "name": "stale", "node_count": 1,
             "healthy_node_count": 0},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription") \
                as del_mock:
            result = self._ps.cleanup_expired_pool(
                dry_run=True, also_delete_orphans=True
            )
        self.assertTrue(result["dry_run"])
        del_mock.assert_not_called()
        self._store.delete_results.assert_not_called()
        self.assertEqual(result["deleted_count"], 1)
        self.assertEqual(result["orphan_deleted_count"], 1)
        self.assertEqual(result["skipped_count"], 0)

    def test_cleanup_deletes_subscription_and_proxy_file(self):
        proxy_file = os.path.join(self._tmp.name, "expired.http.txt")
        with open(proxy_file, "w", encoding="utf-8") as f:
            f.write("1.2.3.4:80\n")
        rows = [self._expired_row(1, "expired@dgu.edu.kg")]
        rows[0]["proxy_file"] = proxy_file
        _set_rows(self._store, rows)
        subs = [{"id": "sub-1", "name": "expired", "node_count": 3,
                 "healthy_node_count": 2}]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription") \
                as del_mock:
            result = self._ps.cleanup_expired_pool(dry_run=False)
        self.assertEqual(result["deleted_count"], 1)
        del_mock.assert_called_once_with("sub-1")
        self.assertFalse(os.path.exists(proxy_file))
        # remove_records=False → 本地记录保留
        self._store.delete_results.assert_not_called()

    def test_cleanup_removes_records_when_enabled(self):
        _set_rows(self._store, [self._expired_row(1, "expired@dgu.edu.kg")])
        subs = [{"id": "sub-1", "name": "expired", "node_count": 3,
                 "healthy_node_count": 2}]
        gr.config["resin_remove_expired_records"] = True
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription"):
            result = self._ps.cleanup_expired_pool(dry_run=False)
        self.assertEqual(result["deleted_count"], 1)
        self._store.delete_results.assert_called_once_with([1])

    def test_cleanup_skips_expired_not_in_resin(self):
        _set_rows(self._store, [self._expired_row(1, "expired@dgu.edu.kg")])
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=[]), \
                mock.patch.object(_resin, "resin_delete_subscription") \
                as del_mock:
            result = self._ps.cleanup_expired_pool(dry_run=False)
        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["skipped_count"], 1)
        del_mock.assert_not_called()

    def test_cleanup_counts_errors(self):
        _set_rows(self._store, [self._expired_row(1, "expired@dgu.edu.kg")])
        subs = [{"id": "sub-1", "name": "expired", "node_count": 3,
                 "healthy_node_count": 2}]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription",
                                  side_effect=RuntimeError("resin 500")):
            result = self._ps.cleanup_expired_pool(dry_run=False)
        self.assertEqual(result["deleted_count"], 0)
        self.assertEqual(result["error_count"], 1)
        self.assertIn("resin 500", result["errors"][0]["error"])

    def test_cleanup_deletes_orphans(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        subs = [
            {"id": "sub-1", "name": "active", "node_count": 4,
             "healthy_node_count": 4},
            {"id": "sub-2", "name": "stale", "node_count": 1,
             "healthy_node_count": 0},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription") \
                as del_mock:
            result = self._ps.cleanup_expired_pool(
                dry_run=False, also_delete_orphans=True
            )
        self.assertEqual(result["orphan_deleted_count"], 1)
        self.assertEqual(del_mock.call_count, 1)
        del_mock.assert_called_once_with("sub-2")

    def test_cleanup_raises_when_resin_unreachable(self):
        _set_rows(self._store, [self._expired_row(1, "expired@dgu.edu.kg")])
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  side_effect=RuntimeError("timeout")):
            with self.assertRaises(Exception) as ctx:
                self._ps.cleanup_expired_pool(dry_run=False)
        self.assertIn("timeout", str(ctx.exception))


class OrphanProtectTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        from backend.registration import pool_snapshot as ps

        self._ps = ps
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._store = mock.Mock()
        self._store_patcher = mock.patch.object(
            gr, "get_registration_repository", return_value=self._store
        )
        self._store_patcher.start()
        self.addCleanup(self._store_patcher.stop)
        self._file_patcher = mock.patch.object(
            ps, "_protected_file", return_value=os.path.join(
                self._tmp.name, "resin_orphan_protected.json"
            )
        )
        self._file_patcher.start()
        self.addCleanup(self._file_patcher.stop)

    def test_set_and_clear_protection(self):
        self.assertFalse(self._ps.is_orphan_protected("sub-9"))
        self.assertTrue(self._ps.set_orphan_protected("sub-9", "stale", True))
        self.assertTrue(self._ps.is_orphan_protected("sub-9"))
        self.assertFalse(self._ps.set_orphan_protected("sub-9", "stale", False))
        self.assertFalse(self._ps.is_orphan_protected("sub-9"))

    def test_snapshot_orphan_carries_protected_and_expire_at(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        self._ps.set_orphan_protected("sub-2", "stale", True)
        subs = [
            {"id": "sub-1", "name": "active", "created_at": _past(),
             "node_count": 4, "healthy_node_count": 4},
            {"id": "sub-2", "name": "stale", "created_at": _past(),
             "node_count": 1, "healthy_node_count": 0},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs):
            snap = build_pool_snapshot()
        orphans = {o["id"]: o for o in snap["resin_orphans"]}
        # sub-1 名 "active" 匹配本地账号 → 不是孤儿
        self.assertNotIn("sub-1", orphans)
        self.assertTrue(orphans["sub-2"]["protected"])
        self.assertTrue(orphans["sub-2"]["expire_at"])
        self.assertIn("T", orphans["sub-2"]["expire_at"])

    def test_cleanup_skips_protected_orphans(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        self._ps.set_orphan_protected("sub-2", "stale", True)
        subs = [
            {"id": "sub-1", "name": "active", "node_count": 4,
             "healthy_node_count": 4},
            {"id": "sub-2", "name": "stale", "node_count": 1,
             "healthy_node_count": 0},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription") \
                as del_mock:
            result = self._ps.cleanup_expired_pool(
                dry_run=False, also_delete_orphans=True
            )
        self.assertEqual(result["orphan_deleted_count"], 0)
        del_mock.assert_not_called()

    def test_cleanup_deletes_unprotected_orphans_only(self):
        _set_rows(self._store, [_row(1, "active@dgu.edu.kg", _future())])
        self._ps.set_orphan_protected("sub-2", "stale", True)
        subs = [
            {"id": "sub-1", "name": "active", "node_count": 4,
             "healthy_node_count": 4},
            {"id": "sub-2", "name": "stale", "node_count": 1,
             "healthy_node_count": 0},
            {"id": "sub-3", "name": "extra", "node_count": 2,
             "healthy_node_count": 1},
        ]
        with mock.patch.object(_resin, "resin_enabled", return_value=True), \
                mock.patch.object(_resin, "resin_list_subscriptions",
                                  return_value=subs), \
                mock.patch.object(_resin, "resin_delete_subscription") \
                as del_mock:
            result = self._ps.cleanup_expired_pool(
                dry_run=False, also_delete_orphans=True
            )
        self.assertEqual(result["orphan_deleted_count"], 1)
        del_mock.assert_called_once_with("sub-3")


if __name__ == "__main__":
    unittest.main()
