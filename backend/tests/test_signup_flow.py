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

    def test_wall_clock_guard_fails_fast_on_total_timeout(self):
        """外层墙钟守卫：整体超过 55s 立即失败，不空转 20 轮。"""
        fake_page = mock.Mock()
        fake_page.run_js.return_value = ""
        with mock.patch.object(signup_flow, "active_page", return_value=fake_page), \
                mock.patch.object(signup_flow, "page", fake_page), \
                mock.patch.object(signup_flow, "_try_click_turnstile_frame",
                                  return_value=True), \
                mock.patch.object(signup_flow, "sleep_with_cancel"), \
                mock.patch.object(signup_flow, "raise_if_cancelled"), \
                mock.patch.object(
                    signup_flow.time, "time",
                    side_effect=[1000.0, 9999.0],
                ):
            with self.assertRaises(Exception) as ctx:
                signup_flow.getTurnstileToken()
        self.assertIn("外层守卫", str(ctx.exception))

    def test_wall_clock_guard_allows_normal_polling(self):
        """墙钟未到期时正常轮询；token 出现即返回，不被守卫误杀。"""
        fake_page = mock.Mock()
        fake_page.run_js.side_effect = ["", "", "x" * 88]
        with mock.patch.object(signup_flow, "active_page", return_value=fake_page), \
                mock.patch.object(signup_flow, "page", fake_page), \
                mock.patch.object(signup_flow, "_try_click_turnstile_frame",
                                  return_value=True), \
                mock.patch.object(signup_flow, "sleep_with_cancel"), \
                mock.patch.object(signup_flow, "raise_if_cancelled"), \
                mock.patch.object(
                    signup_flow.time, "time",
                    side_effect=[1000.0, 1000.1, 1000.2, 1000.3],
                ):
            token = signup_flow.getTurnstileToken()
        self.assertEqual(len(token), 88)

    def test_turnstile_timeout_classified_as_form(self):
        """外层守卫抛错含 turnstile 关键词 → FAIL_PS_FORM（换新邮箱重试）。"""
        self.assertEqual(
            engine.classify_failure(Exception("Turnstile 获取 token 超时（外层守卫）")),
            engine.FAIL_PS_FORM,
        )


if __name__ == "__main__":
    unittest.main()
