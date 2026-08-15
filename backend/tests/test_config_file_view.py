import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.registration import engine as gr
from backend.web.application import _apply_config_updates, _config_file_snapshot


class ConfigFileSnapshotTests(unittest.TestCase):
    def test_reads_actual_path_and_pretty_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"proxy": "http://proxy", "secret": "value"}), encoding="utf-8")
            with patch("backend.registration.engine.CONFIG_FILE", str(path)):
                snapshot = _config_file_snapshot()
            self.assertEqual(snapshot["path"], str(path.resolve()))
            self.assertTrue(snapshot["exists"])
            self.assertEqual(json.loads(snapshot["content"])["secret"], "value")
            self.assertGreater(snapshot["size"], 0)
            self.assertFalse(snapshot["parse_error"])
            self.assertIn("proxy", snapshot["sensitive_keys"])

    def test_reports_invalid_json_without_hiding_file_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"broken":', encoding="utf-8")
            with patch("backend.registration.engine.CONFIG_FILE", str(path)):
                snapshot = _config_file_snapshot()
            self.assertTrue(snapshot["parse_error"])
            self.assertIn('{"broken":', snapshot["content"])


class ProxyConfigUpdateTests(unittest.TestCase):
    def setUp(self):
        self.original_config = dict(gr.config)

    def tearDown(self):
        gr.config.clear()
        gr.config.update(self.original_config)

    def test_encoded_authenticated_http_proxy_is_saved_unchanged(self):
        proxy = "http://user%40mail:p%40ss@proxy.example.com:8080"
        with patch.object(gr, "load_config"), patch.object(gr, "save_config") as save:
            result = _apply_config_updates({"proxy": f"  {proxy}  "})

        self.assertEqual(gr.config["proxy"], proxy)
        self.assertEqual(result["config"]["proxy"], proxy)
        save.assert_called_once_with()

    def test_invalid_http_proxy_is_rejected_before_saving(self):
        with patch.object(gr, "load_config"), patch.object(gr, "save_config") as save:
            with self.assertRaises(HTTPException) as raised:
                _apply_config_updates(
                    {"proxy": "http://user:bad%ZZ@proxy.example.com:8080"}
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("网络代理格式错误", str(raised.exception.detail))
        save.assert_not_called()

    def test_ps_dashboard_base_is_public_and_saved(self):
        with patch.object(gr, "load_config"), patch.object(gr, "save_config") as save:
            result = _apply_config_updates({"ps_dashboard_base": "https://dashboard.proxyscrape.com/v2"})
        self.assertEqual(gr.config["ps_dashboard_base"], "https://dashboard.proxyscrape.com/v2")
        self.assertEqual(result["config"]["ps_dashboard_base"], "https://dashboard.proxyscrape.com/v2")
        save.assert_called_once_with()

    def test_removed_legacy_keys_are_ignored(self):
        """cpa_auto_add 等已移除键提交时不写入 config。"""
        gr.config["cpa_auto_add"] = True
        with patch.object(gr, "load_config"), patch.object(gr, "save_config") as save:
            result = _apply_config_updates(
                {"cpa_auto_add": True, "legacy_unknown_key": "http://x"}
            )
        self.assertNotIn("legacy_unknown_key", gr.config)
        self.assertNotIn("legacy_unknown_key", result["config"])
        self.assertEqual(save.call_count, 1)


if __name__ == "__main__":
    unittest.main()
