import unittest
from unittest import mock

from backend.automation import session as browser_session


class CamoufoxProcessMatchTests(unittest.TestCase):
    def tearDown(self):
        browser_session.allow_browser_launches()

    def test_matches_camoufox_executables_and_managed_profiles(self):
        self.assertTrue(browser_session._is_camoufox_process("/cache/camoufox/camoufox-bin", ""))
        self.assertTrue(
            browser_session._is_camoufox_process(
                "/usr/lib/firefox/firefox",
                "firefox -profile /tmp/ps-register-camoufox/123-profile",
            )
        )

    def test_does_not_match_regular_firefox(self):
        self.assertFalse(
            browser_session._is_camoufox_process(
                "/usr/lib/firefox/firefox",
                "firefox https://example.com",
            )
        )

    def test_emergency_block_prevents_browser_restart(self):
        browser_session.block_browser_launches()
        with self.assertRaisesRegex(RuntimeError, "紧急终止"):
            browser_session.start_browser()

    def test_kill_all_targets_camoufox_tree_only(self):
        processes = {
            101: (1, "/cache/camoufox/camoufox", "camoufox"),
            102: (101, "/usr/lib/helper", "content process"),
            201: (1, "/usr/lib/firefox/firefox", "firefox https://example.com"),
        }
        killed = []
        with (
            mock.patch.object(browser_session, "_linux_processes", return_value=processes),
            mock.patch.object(browser_session, "_cleanup_all_managed_profiles", return_value=2),
            mock.patch.object(browser_session.os, "kill", side_effect=lambda pid, sig: killed.append((pid, sig))),
            mock.patch.object(browser_session.time, "sleep"),
        ):
            result = browser_session.kill_all_camoufox_processes()

        self.assertEqual(result, {"killed": 2, "profiles_cleaned": 2})
        self.assertEqual({pid for pid, _ in killed}, {101, 102})
        self.assertNotIn(201, {pid for pid, _ in killed})


if __name__ == "__main__":
    unittest.main()
