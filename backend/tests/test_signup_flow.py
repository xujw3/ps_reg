import unittest
from unittest import mock

from backend.registration import engine
from backend.registration import signup_flow


class SignupFlowTests(unittest.TestCase):
    class NativeInput:
        def __init__(self, current_value=""):
            self.current_value = current_value
            self.states = mock.Mock(is_alive=True, is_displayed=True, is_enabled=True)

        def click(self, **kwargs):
            return None

        def input(self, value, **kwargs):
            return None

        def property(self, name):
            return self.current_value

    def test_native_input_does_not_treat_empty_value_as_success(self):
        element = self.NativeInput(current_value="")
        self.assertFalse(signup_flow._native_type_element(element, "Neo"))

    def test_native_input_accepts_confirmed_value(self):
        element = self.NativeInput(current_value="Neo")
        self.assertTrue(signup_flow._native_type_element(element, "Neo"))

    def test_duplicate_account_has_own_failure_type(self):
        exc = signup_flow.AccountAlreadyRegistered("fixture")
        self.assertEqual(engine.classify_failure(exc), engine.FAIL_ALREADY_REGISTERED)

    def test_turnstile_failure_classified_as_browser(self):
        """Turnstile 相关失败按浏览器类处理（重启浏览器重试，不消耗新账号预算）。"""
        self.assertEqual(
            engine.classify_failure(Exception("Turnstile 获取 token 失败")),
            engine.FAIL_BROWSER,
        )
        self.assertEqual(
            engine.classify_failure(Exception("Turnstile 连续点击失败（浏览器交互异常）")),
            engine.FAIL_BROWSER,
        )

    def test_turnstile_click_failures_fail_fast(self):
        """连续 3 轮点击失败 → 立即抛异常，不空转 20 轮等待。"""
        fake_page = mock.Mock()
        fake_page.run_js.return_value = ""
        with mock.patch.object(signup_flow, "active_page", return_value=fake_page), \
                mock.patch.object(signup_flow, "page", fake_page), \
                mock.patch.object(
                    signup_flow, "_try_click_turnstile_frame", return_value=False
                ) as click_mock, \
                mock.patch.object(signup_flow, "sleep_with_cancel"), \
                mock.patch.object(signup_flow, "raise_if_cancelled"):
            with self.assertRaises(Exception) as ctx:
                signup_flow.getTurnstileToken()
        self.assertIn("连续点击失败", str(ctx.exception))
        # 只尝试了 3 次点击（而非 20 轮空转）
        self.assertEqual(click_mock.call_count, 3)

    def test_turnstile_recovers_after_one_failed_click(self):
        """第 1 轮点击失败、第 2 轮成功 → 正常继续，不被快速失败误杀。"""
        fake_page = mock.Mock()
        fake_page.run_js.return_value = ""

        def fake_click(log_callback=None):
            fake_click.calls += 1
            return fake_click.calls >= 2

        fake_click.calls = 0
        with mock.patch.object(signup_flow, "active_page", return_value=fake_page), \
                mock.patch.object(signup_flow, "page", fake_page), \
                mock.patch.object(
                    signup_flow, "_try_click_turnstile_frame", side_effect=fake_click
                ), \
                mock.patch.object(signup_flow, "sleep_with_cancel"), \
                mock.patch.object(signup_flow, "raise_if_cancelled"):
            # 20 轮内 token 始终为空 → 最终正常超时报错，而不是快速失败
            with self.assertRaises(Exception) as ctx:
                signup_flow.getTurnstileToken()
        self.assertNotIn("连续点击失败", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
