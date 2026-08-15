# -*- coding: utf-8 -*-
"""账号列表 Resin 状态列序列化测试。

表格列只显示短状态，完整错误文本单独放 resin_error（详情面板展示），
避免入池失败的长错误（如 curl 超时详情）把账号列表列宽撑爆。
"""
import unittest

from backend.web import application


class ResinStatusSerializeTests(unittest.TestCase):
    def test_failed_long_error_becomes_short_status_plus_full_error(self):
        item = application._serialize_record(
            {
                "id": 1,
                "resin_status": (
                    "failed: Failed to perform, curl: (28) Operation timed out "
                    "after 30002 milliseconds with 0 bytes received. See "
                    "https://curl.se/libcurl/c/libcurl-errors.html first for "
                    "more details."
                ),
            }
        )
        self.assertEqual(item["resin_status"], "failed")
        self.assertIn("curl: (28)", item["resin_error"])
        self.assertIn("30002 milliseconds", item["resin_error"])

    def test_short_status_untouched(self):
        item = application._serialize_record({"id": 2, "resin_status": "success"})
        self.assertEqual(item["resin_status"], "success")
        self.assertEqual(item["resin_error"], "")

    def test_long_non_failed_status_truncated(self):
        raw = "x" * 60
        item = application._serialize_record({"id": 3, "resin_status": raw})
        self.assertEqual(len(item["resin_status"]), 40)
        self.assertEqual(item["resin_error"], raw)

    def test_missing_resin_status_defaults_empty(self):
        item = application._serialize_record({"id": 4})
        self.assertEqual(item["resin_status"], "")
        self.assertEqual(item["resin_error"], "")


if __name__ == "__main__":
    unittest.main()
