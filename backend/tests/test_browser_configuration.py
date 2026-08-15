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


if __name__ == "__main__":
    unittest.main()
