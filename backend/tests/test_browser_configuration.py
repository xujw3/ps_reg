import os
import tempfile
import unittest
from unittest import mock

from backend.automation import session as browser_session
from backend.registration import engine as gr


class BrowserHeadlessConfigTests(unittest.TestCase):
    def tearDown(self):
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "en-US",
        )

    def test_browser_options_follow_headless_setting(self):
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: True,
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertIs(options["headless"], True)

        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: False,
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertIs(options["headless"], False)

    def test_container_force_headed_overrides_config(self):
        with mock.patch.dict(gr.os.environ, {"PS_FORCE_HEADED": "1"}, clear=False):
            with mock.patch.dict(gr.config, {"browser_headless": True}, clear=False):
                self.assertFalse(gr.is_browser_headless())

    def test_browser_options_force_configured_locale(self):
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "zh-CN",
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertEqual(options["locale"], "zh-CN")

    def test_invalid_browser_locale_falls_back_to_english(self):
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "fr-FR",
        )
        options = browser_session.create_browser_options(unique_profile=False)
        self.assertEqual(options["locale"], "en-US")


class CamoufoxAddonCompatTests(unittest.TestCase):
    """回归：camoufox 0.5.9 把 get_addon_path 改成 (addon_name, executable_path)。

    旧代码只传 addon_name，0.5.9+ 直接 TypeError: missing 1 required positional
    argument: 'executable_path'，create_browser_options 整体抛错，CI 里
    test_browser_configuration / test_proxy_routing 全红。新代码两种签名都得吃下。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.exe_path = os.path.join(self._tmp.name, "camoufox.exe")
        self.addon_root = os.path.join(self._tmp.name, "addons")

    def tearDown(self):
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: False,
            get_locale=lambda: "en-US",
        )

    def _options(self, fake_get_addon_path, detected_exe=None):
        browser_session.configure(
            get_proxies=lambda: {},
            is_debug=lambda: False,
            is_headless=lambda: True,
            get_locale=lambda: "en-US",
        )
        exe = self.exe_path if detected_exe is None else detected_exe
        with mock.patch.object(
            browser_session, "_detect_camoufox_exe", return_value=exe
        ), mock.patch("camoufox.addons.get_addon_path", fake_get_addon_path):
            return browser_session.create_browser_options(unique_profile=False)

    def _healthy_addon(self, addon_name):
        path = os.path.join(self.addon_root, addon_name)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "manifest.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        return path

    def test_new_signature_receives_executable_path(self):
        from camoufox.addons import DefaultAddons

        calls = []

        def get_addon_path(addon_name, executable_path):  # 0.5.9 签名
            calls.append((addon_name, executable_path))
            return self._healthy_addon(addon_name)

        options = self._options(get_addon_path)

        # 健康 addon 目录不应被排除
        self.assertNotIn("exclude_addons", options)
        self.assertTrue(calls)
        self.assertEqual(calls[0][0], DefaultAddons.UBO.name)
        self.assertEqual(calls[0][1], self.exe_path)

    def test_legacy_signature_still_supported(self):
        calls = []

        def get_addon_path(addon_name):  # 0.5.4 签名：传两个参数会 TypeError
            calls.append(addon_name)
            return self._healthy_addon(addon_name)

        options = self._options(get_addon_path, detected_exe="")

        self.assertNotIn("exclude_addons", options)
        self.assertTrue(calls)

    def test_corrupted_addon_dir_is_excluded(self):
        from camoufox.addons import DefaultAddons

        def get_addon_path(addon_name, executable_path):
            # 目录存在但缺 manifest.json → 半下载状态，必须 exclude 而不是启动崩
            path = os.path.join(self.addon_root, "corrupt-" + addon_name)
            os.makedirs(path, exist_ok=True)
            return path

        options = self._options(get_addon_path)

        self.assertEqual(options.get("exclude_addons"), [DefaultAddons.UBO])


if __name__ == "__main__":
    unittest.main()
