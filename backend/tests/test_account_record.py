import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.registration import engine as gr


class SaveAccountRecordTests(unittest.TestCase):
    """data/accounts/accounts.txt 统一汇总文件（proxyscrape_reg 同款格式）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.accounts_dir = Path(self.tmp.name) / "accounts"

    def test_appends_ps_format_line_to_accounts_txt(self):
        with patch.object(gr, "ACCOUNTS_DIR", str(self.accounts_dir)):
            gr.save_account_record(
                email="a@example.com",
                password="pw1234567890",
                created_at="2026-08-15T10:00:00",
                expire_at="2026-08-22T10:00:00",
            )
        lines = (self.accounts_dir / "accounts.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines, ["a@example.com----pw1234567890----2026-08-15T10:00:00----2026-08-22T10:00:00"])

    def test_append_multiple_lines_preserves_order(self):
        with patch.object(gr, "ACCOUNTS_DIR", str(self.accounts_dir)):
            for i in range(3):
                gr.save_account_record(
                    email=f"u{i}@example.com",
                    password="pw",
                    created_at=f"2026-08-15T10:0{i}:00",
                    expire_at=f"2026-08-22T10:0{i}:00",
                )
        lines = (self.accounts_dir / "accounts.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("u0@example.com----pw----"))
        self.assertTrue(lines[2].startswith("u2@example.com----pw----"))

    def test_missing_dates_filled_from_now_plus_valid_days(self):
        import datetime as real_dt

        original = dict(gr.config)
        gr.config.update({"account_valid_days": 7})
        try:
            with patch.object(gr, "ACCOUNTS_DIR", str(self.accounts_dir)):
                before = real_dt.datetime.now()
                gr.save_account_record(email="b@example.com", password="pw")
                after = real_dt.datetime.now()
        finally:
            gr.config.clear()
            gr.config.update(original)
        line = (self.accounts_dir / "accounts.txt").read_text(encoding="utf-8").splitlines()[0]
        parts = line.split("----")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "b@example.com")
        self.assertEqual(parts[1], "pw")
        created_dt = real_dt.datetime.fromisoformat(parts[2])
        expire_dt = real_dt.datetime.fromisoformat(parts[3])
        before_s = before.replace(microsecond=0)
        after_s = after.replace(microsecond=0)
        self.assertGreaterEqual(created_dt, before_s)
        self.assertLessEqual(created_dt, after_s)
        self.assertEqual((expire_dt - created_dt).days, 7)


if __name__ == "__main__":
    unittest.main()
