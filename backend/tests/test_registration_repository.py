import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.registration.store import RegistrationRepository


OLD_SCHEMA = """
CREATE TABLE registration_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT UNIQUE,
    batch_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'gui',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0,
    email TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'failure',
    success INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL DEFAULT '',
    worker_id INTEGER NOT NULL DEFAULT 0,
    cpa_enabled INTEGER NOT NULL DEFAULT 0,
    cpa_status TEXT NOT NULL DEFAULT 'disabled',
    auth_info TEXT NOT NULL DEFAULT '',
    auth_path TEXT NOT NULL DEFAULT '',
    failure_type TEXT NOT NULL DEFAULT '',
    failure_reason TEXT NOT NULL DEFAULT '',
    account_file TEXT NOT NULL DEFAULT '',
    sso_saved INTEGER NOT NULL DEFAULT 0,
    nsfw_status TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);
PRAGMA user_version = 1;
"""


class RegistrationRepositoryMigrationTests(unittest.TestCase):
    def test_old_database_migrates_and_filters_disable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(OLD_SCHEMA)
                conn.execute(
                    """
                    INSERT INTO registration_results
                    (started_at, finished_at, email, status, success, provider)
                    VALUES ('2026-08-01 00:00:00', '2026-08-01 00:00:01',
                            'old@example.com', 'success', 1, 'cloudflare')
                    """
                )
                conn.commit()

            store = RegistrationRepository(path)
            with closing(sqlite3.connect(path)) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(registration_results)")}
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, 8)
            self.assertIn("bot_risk", columns)
            self.assertIn("bfs", columns)
            with closing(sqlite3.connect(path)) as outbox_conn:
                outbox_tables = {
                    row[0]
                    for row in outbox_conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            self.assertIn("grokiq_outbox", outbox_tables)
            self.assertTrue(
                {
                    "email_account_id",
                    "email_disable_status",
                    "email_disabled_at",
                    "email_disable_error",
                    "cpa_auth_path",
                    "grok2api_auth_path",
                    "screenshot_path",
                    "cpa_remote_status",
                    "cpa_remote_imported_at",
                    "cpa_remote_error",
                    "grok2api_remote_status",
                    "grok2api_remote_imported_at",
                    "grok2api_remote_error",
                }.issubset(columns)
            )
            self.assertEqual(store.list_results()[0]["email_disable_status"], "not_applicable")

            store.add_result(
                {
                    "email": "disabled@outlook.com",
                    "status": "success",
                    "provider": "outlookemail",
                    "cpa_enabled": True,
                    "cpa_status": "success",
                    "email_account_id": "367",
                    "email_disable_status": "success",
                    "email_disabled_at": "2026-08-01 01:02:03",
                    "screenshot_path": "/tmp/failure.png",
                }
            )
            store.add_result(
                {
                    "email": "failed@outlook.com",
                    "status": "success",
                    "provider": "outlookemail",
                    "cpa_enabled": True,
                    "cpa_status": "success",
                    "email_disable_status": "failed",
                    "email_disable_error": "fixture error",
                }
            )

            filtered = store.list_results(email_disable_status="failed")
            self.assertEqual([row["email"] for row in filtered], ["failed@outlook.com"])
            self.assertEqual(store.count_results(), 3)
            self.assertEqual(len(store.list_results(limit=1, offset=1)), 1)
            self.assertEqual(
                store.count_results(email_disable_status="failed"), 1
            )
            stats = store.stats()
            self.assertEqual(stats["email_disabled"], 1)
            self.assertEqual(stats["email_disable_failed"], 1)
            disabled = next(row for row in store.list_results() if row["email"] == "disabled@outlook.com")
            self.assertEqual(disabled["screenshot_path"], "/tmp/failure.png")

    def test_pagination_filters_and_large_id_batches_share_consistent_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            for index in range(5):
                store.add_result(
                    {
                        "email": f"user-{index}@example.com",
                        "status": "success" if index < 4 else "failure",
                        "provider": "fixture",
                        "finished_at": f"2026-08-04 00:00:0{index}",
                    }
                )

            self.assertEqual(store.count_results(status="success", keyword="user-"), 4)
            page = store.list_results(
                status="success",
                keyword="user-",
                limit=2,
                offset=2,
            )
            self.assertEqual(
                [row["email"] for row in page],
                ["user-1@example.com", "user-0@example.com"],
            )
            records = store.get_results_by_ids(range(1, 1006))
            self.assertEqual([row["id"] for row in records], [1, 2, 3, 4, 5])
            self.assertEqual(len(store.delete_results(range(1, 1006))), 5)
            self.assertEqual(store.count_results(), 0)

    def test_bot_risk_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            store.add_result(
                {
                    "email": "risk@example.com",
                    "status": "success",
                    "bot_risk": True,
                    "bfs": 1,
                }
            )
            store.add_result(
                {
                    "email": "safe@example.com",
                    "status": "success",
                    "bot_risk": False,
                    "bfs": 0,
                }
            )
            store.add_result(
                {
                    "email": "unknown@example.com",
                    "status": "success",
                    "bot_risk": False,
                }
            )
            store.add_result(
                {
                    "email": "source-only-risk@example.com",
                    "status": "success",
                    "bot_risk": False,
                    "bfs": 4,
                }
            )
            store.add_result(
                {
                    "email": "legacy-clean@example.com",
                    "status": "success",
                    "bot_risk": False,
                    "extra_json": json.dumps({"sso_check_status": "clean"}),
                }
            )
            risk_rows = store.list_results(bot_risk="1")
            self.assertEqual(
                [row["email"] for row in risk_rows],
                ["source-only-risk@example.com", "risk@example.com"],
            )
            self.assertEqual(store.count_results(bot_risk="risk"), 2)
            safe_rows = store.list_results(bot_risk="0")
            self.assertEqual(
                [row["email"] for row in safe_rows],
                ["legacy-clean@example.com", "safe@example.com"],
            )
            self.assertEqual(store.count_results(bot_risk="normal"), 2)
            unknown_rows = store.list_results(bot_risk="unknown")
            self.assertEqual([row["email"] for row in unknown_rows], ["unknown@example.com"])

    def test_list_result_ids_matches_filters_and_list_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            first = store.add_result(
                {"email": "first@example.com", "status": "success", "provider": "fixture"}
            )
            second = store.add_result(
                {"email": "second@example.com", "status": "failure", "provider": "fixture"}
            )
            third = store.add_result(
                {"email": "third@example.com", "status": "success", "provider": "other"}
            )

            expected = [row["id"] for row in store.list_results(status="success", keyword="fixture")]
            self.assertEqual(store.list_result_ids(status="success", keyword="fixture"), expected)
            self.assertEqual(expected, [first])
            self.assertNotIn(second, expected)
            self.assertNotIn(third, expected)

    def test_registration_risk_email_is_treated_as_consumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            store.add_result(
                {
                    "email": "risk@outlook.com",
                    "status": "failure",
                    "failure_type": "registration_risk",
                    "failure_reason": "注册风控拒绝",
                }
            )
            store.add_result(
                {
                    "email": "sso@outlook.com",
                    "status": "failure",
                    "failure_type": "sso_timeout",
                    "failure_reason": "未获取到 sso cookie",
                }
            )
            store.add_result(
                {
                    "email": "timeout@outlook.com",
                    "status": "failure",
                    "failure_type": "code_timeout",
                    "failure_reason": "未收到验证码",
                }
            )

            self.assertTrue(store.has_registered_or_consumed("risk@outlook.com"))
            self.assertTrue(store.has_registered_or_consumed("sso@outlook.com"))
            self.assertFalse(store.has_registered_or_consumed("timeout@outlook.com"))

    def test_ps_fields_roundtrip_through_repository(self):
        """access_token/account_id/expire_at/proxy_file/resin_status 完整落库读回。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = RegistrationRepository(Path(tmp) / "results.sqlite3")
            row_id = store.add_result(
                {
                    "email": "ps@example.com",
                    "status": "success",
                    "provider": "cloudflare",
                    "access_token": "ps-token-1234567890abcdef",
                    "account_id": "acc-42",
                    "expire_at": "2026-08-22T12:00:00",
                    "proxy_file": "data/proxy_lists/ps@example.com.http.txt",
                    "resin_status": "success",
                }
            )
            rows = store.get_results_by_ids([row_id])
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["access_token"], "ps-token-1234567890abcdef")
            self.assertEqual(row["account_id"], "acc-42")
            self.assertEqual(row["expire_at"], "2026-08-22T12:00:00")
            self.assertEqual(row["proxy_file"], "data/proxy_lists/ps@example.com.http.txt")
            self.assertEqual(row["resin_status"], "success")

    def test_old_database_migrates_ps_columns_with_defaults(self):
        """旧库迁移后新增 5 个 PS 列且默认值正确。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.executescript(OLD_SCHEMA)
                conn.execute(
                    """
                    INSERT INTO registration_results
                    (started_at, finished_at, email, status, success, provider)
                    VALUES ('2026-08-01 00:00:00', '2026-08-01 00:00:01',
                            'legacy@example.com', 'success', 1, 'cloudflare')
                    """
                )
                conn.commit()

            store = RegistrationRepository(path)
            with closing(sqlite3.connect(path)) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(registration_results)")}
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, 8)
            for col in ("access_token", "account_id", "expire_at", "proxy_file", "resin_status"):
                self.assertIn(col, columns)
            rows = store.get_results_by_ids(store.list_result_ids())
            self.assertEqual(rows[0]["access_token"], "")
            self.assertEqual(rows[0]["account_id"], "")
            self.assertEqual(rows[0]["expire_at"], "")
            self.assertEqual(rows[0]["proxy_file"], "")
            self.assertEqual(rows[0]["resin_status"], "skipped")


if __name__ == "__main__":
    unittest.main()
