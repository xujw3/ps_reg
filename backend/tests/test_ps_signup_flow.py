# -*- coding: utf-8 -*-
"""ProxyScrape 注册页浏览器流程测试。"""
import unittest
from unittest import mock

from backend.registration import ps_signup_flow
from backend.registration import engine as gr


def _make_page(run_js_side_effect=None, url="https://dashboard.proxyscrape.com/v2/sign-up"):
    page = mock.Mock()
    page.url = url
    page.run_js = mock.Mock(side_effect=run_js_side_effect)
    page.get = mock.Mock()
    page.ele = mock.Mock(return_value=None)
    page.eles = mock.Mock(return_value=[])
    return page


class PSSignupFlowTests(unittest.TestCase):
    def setUp(self):
        self.original_config = dict(gr.config)
        self.calls = []

    def tearDown(self):
        gr.config.clear()
        gr.config.update(self.original_config)

    def test_open_ps_signup_page_clears_auth_then_goto_signup(self):
        """先到 dashboard 同源清登录态，再打开 /sign-up，直到表单就绪。"""
        state = {"step": 0}

        def run_js(script, *args):
            if "localStorage.removeItem" in script or "localStorage.clear" in script:
                return True
            if "hasEmail" in script:
                state["step"] += 1
                if state["step"] < 2:
                    return '{"url":"https://dashboard.proxyscrape.com/v2/login","hasEmail":false,"hasPwd":false,"tokenLen":42,"onSignup":false,"onLogin":true,"onDashboard":false}'
                return '{"url":"https://dashboard.proxyscrape.com/v2/sign-up","hasEmail":true,"hasPwd":true,"tokenLen":0,"onSignup":true,"onLogin":false,"onDashboard":false}'
            return "{}"

        page = _make_page(run_js)
        with mock.patch.object(ps_signup_flow, "page", page), mock.patch.object(
            ps_signup_flow, "active_page", return_value=page
        ):
            ps_signup_flow.open_ps_signup_page(log_callback=lambda m: self.calls.append(m))

        got_urls = [c.args[0] for c in page.get.call_args_list]
        self.assertTrue(any("/sign-up" in u for u in got_urls))
        self.assertGreater(len(got_urls), 1)
        self.assertTrue(any("登录态" in m or "清理" in m or "重开" in m for m in self.calls))

    def test_fill_ps_signup_form_writes_email_password_and_terms(self):
        """MUI 受控输入 + terms checkbox 勾选 + 表单快照校验。"""
        state = {"status_calls": 0}

        def run_js(script, *args):
            if "var selectors" in script and "arguments[1]" in script:
                return '{"ok":true,"value":"' + str(args[1] if args else "") + '"}'
            if "var boxes" in script and "checked" in script and "ariaChecked" in script:
                state["status_calls"] += 1
                return '{"total":1,"checked":1,"ariaChecked":true,"submitDisabled":false}'
            if "var out = {ok:false" in script:
                return '{"ok":false}'
            if "var email = (document.querySelector" in script:
                return (
                    '{"email":"user@example.com","passwordLen":14,"confirmLen":14,'
                    '"pwdCount":2,"termsChecked":true,"submitDisabled":false,"submitText":"Continue"}'
                )
            return "{}"

        page = _make_page(run_js)
        with mock.patch.object(ps_signup_flow, "page", page), mock.patch.object(
            ps_signup_flow, "active_page", return_value=page
        ):
            ps_signup_flow.fill_ps_signup_form(
                "user@example.com",
                "Abcdef1!xyz",
                log_callback=lambda m: self.calls.append(m),
            )
        self.assertTrue(any("已填写 email" in m for m in self.calls))
        self.assertTrue(any("服务条款" in m for m in self.calls))

    def test_fill_ps_signup_form_raises_when_terms_missing(self):
        """terms 无法勾选时报错，避免提交被禁用按钮卡住。"""
        def run_js(script, *args):
            if "var selectors" in script:
                return '{"ok":true}'
            if "var boxes" in script and "checked" in script and "ariaChecked" in script:
                return '{"total":1,"checked":0,"ariaChecked":false,"submitDisabled":true}'
            if "var out = {ok:false" in script:
                return '{"ok":false}'
            return "{}"

        page = _make_page(run_js)
        with mock.patch.object(ps_signup_flow, "page", page), mock.patch.object(
            ps_signup_flow, "active_page", return_value=page
        ):
            with self.assertRaises(Exception) as raised:
                ps_signup_flow.fill_ps_signup_form(
                    "user@example.com", "Abcdef1!xyz", log_callback=lambda m: None
                )
        self.assertIn("服务条款", str(raised.exception))

    def test_submit_signup_waits_turnstile_then_returns_token(self):
        """等 Turnstile 通过 → 点一次 Continue → 轮询 accessToken 返回。"""
        state = {"token_given": False}

        def run_js(script, *args):
            if "localStorage.getItem('accessToken')" in script or "accessToken" in script:
                if state["token_given"]:
                    return "ps-token-1234567890abcdef"
                return ""
            if "forceUnlock" in script:
                return "clicked"
            if "cf-turnstile-response" in script:
                return '{"disabled":false,"terms":true,"tsLen":100,"apiLen":100,"hasSubmit":true}'
            if "var boxes" in script and "checked" in script:
                return '{"total":1,"checked":1,"ariaChecked":true,"submitDisabled":false}'
            if "var nodes" in script and "Mui-error" in script:
                return ""
            return "{}"

        page = _make_page(run_js)

        def fake_turnstile(log_callback=None, cancel_callback=None, force_reset=False):
            state["token_given"] = True
            return "ps-token-1234567890abcdef"

        with mock.patch.object(ps_signup_flow, "page", page), mock.patch.object(
            ps_signup_flow, "active_page", return_value=page
        ), mock.patch.object(
            ps_signup_flow.signup_flow, "getTurnstileToken", side_effect=fake_turnstile
        ):
            token = ps_signup_flow.submit_ps_signup_and_wait_token(
                timeout=15, log_callback=lambda m: self.calls.append(m)
            )
        self.assertEqual(token, "ps-token-1234567890abcdef")

    def test_submit_signup_raises_on_timeout(self):
        """一直拿不到 token 时抛异常。"""
        def run_js(script, *args):
            if "accessToken" in script:
                return ""
            if "forceUnlock" in script:
                return "clicked"
            if "cf-turnstile-response" in script:
                return '{"disabled":false,"terms":true,"tsLen":100,"apiLen":100,"hasSubmit":true}'
            if "var boxes" in script and "checked" in script:
                return '{"total":1,"checked":1,"ariaChecked":true,"submitDisabled":false}'
            if "var nodes" in script and "Mui-error" in script:
                return ""
            return "{}"

        page = _make_page(run_js, url="https://dashboard.proxyscrape.com/v2/sign-up")

        with mock.patch.object(ps_signup_flow, "page", page), mock.patch.object(
            ps_signup_flow, "active_page", return_value=page
        ), mock.patch.object(
            ps_signup_flow.signup_flow, "getTurnstileToken", return_value="tok-1234567890abcdef"
        ), mock.patch.object(ps_signup_flow, "sleep_with_cancel", return_value=None):
            with self.assertRaises(Exception) as raised:
                ps_signup_flow.submit_ps_signup_and_wait_token(timeout=1)
        self.assertTrue(
            "Turnstile" in str(raised.exception) or "accessToken" in str(raised.exception),
            str(raised.exception),
        )

    def test_read_token_from_page_storage(self):
        page = _make_page(lambda script, *args: "ps-token-abcdef123456")
        with mock.patch.object(ps_signup_flow, "page", page):
            token = ps_signup_flow.read_ps_access_token_from_page(page)
        self.assertEqual(token, "ps-token-abcdef123456")


if __name__ == "__main__":
    unittest.main()
