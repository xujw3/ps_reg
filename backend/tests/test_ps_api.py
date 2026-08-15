# -*- coding: utf-8 -*-
"""ProxyScrape REST API 封装测试。"""
import unittest
from unittest import mock

from backend.integrations import ps_api
from backend.registration import engine as gr


def fake_response(status_code=200, body=None, text="", headers=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {"content-type": "application/json"}
    if body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = body
    return resp


class PSApiTests(unittest.TestCase):
    def setUp(self):
        self.http_post = mock.Mock(return_value=fake_response(200, {"success": True}))
        self.http_get = mock.Mock(return_value=fake_response(200, text="1.2.3.4:8080\n5.6.7.8:9090\n"))
        ps_api.configure(http_post=self.http_post, http_get=self.http_get)
        self.original_config = dict(gr.config)

    def tearDown(self):
        gr.config.clear()
        gr.config.update(self.original_config)
        ps_api.configure(http_post=None, http_get=None)

    def test_register_api_posts_email_password_and_turnstile(self):
        ps_api.ps_register_api(
            "user@example.com", "Passw0rd!", "turnstile-token", log_callback=lambda m: None
        )
        self.http_post.assert_called_once()
        args, kwargs = self.http_post.call_args
        self.assertIn("/v4/account/auth/register", args[0])
        self.assertEqual(kwargs["data"]["email"], "user@example.com")
        self.assertEqual(kwargs["data"]["password"], "Passw0rd!")
        self.assertEqual(kwargs["data"]["cf_turnstile_token"], "turnstile-token")
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(kwargs["timeout"], 30)

    def test_verify_email_api_uses_bearer_and_verification_code(self):
        ps_api.ps_verify_email_api("access-token", "123456", log_callback=lambda m: None)
        args, kwargs = self.http_post.call_args
        self.assertIn("/v4/account/verify-email", args[0])
        self.assertEqual(kwargs["data"]["verificationCode"], "123456")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer access-token")

    def test_fetch_me_returns_parsed_body(self):
        me_body = {
            "success": True,
            "data": {
                "user": {"email": "user@example.com"},
                "associatedSubaccounts": [
                    {"AccountID": "acc-1", "AccountType": "datacenter_shared"}
                ],
            },
        }
        self.http_post.return_value = fake_response(200, me_body)
        result = ps_api.ps_fetch_me("access-token")
        self.assertEqual(result["data"]["user"]["email"], "user@example.com")

    def test_pick_subaccount_prefers_datacenter_shared(self):
        me_body = {
            "associatedSubaccounts": [
                {"AccountID": "acc-res", "AccountType": "residential"},
                {"AccountID": "acc-dc", "AccountType": "datacenter_shared"},
            ]
        }
        picked = ps_api.ps_pick_subaccount(me_body)
        self.assertEqual(picked["AccountID"], "acc-dc")

    def test_generate_password_meets_rules(self):
        for length in (None, 10, 14, 40):
            pwd = ps_api.generate_password(length=length)
            n = 14 if length is None else max(10, min(length, 32))
            self.assertEqual(len(pwd), n)
            self.assertRegex(pwd, r"[A-Z]")
            self.assertRegex(pwd, r"[a-z]")
            self.assertRegex(pwd, r"[0-9]")
            self.assertRegex(pwd, r"[!@#$%^&*]")

    def test_complete_typeform_skips_when_configured(self):
        gr.config["ps_skip_typeform"] = True
        result = ps_api.ps_complete_typeform("access-token", log_callback=lambda m: None)
        self.http_post.assert_not_called()
        self.assertEqual(result, {"success": True, "skipped": True})

    def test_complete_typeform_posts_form_and_response_id(self):
        gr.config["ps_skip_typeform"] = False
        self.http_post.return_value = fake_response(200, {"success": True})
        result = ps_api.ps_complete_typeform("access-token", log_callback=lambda m: None)
        self.http_post.assert_called_once()
        args, kwargs = self.http_post.call_args
        self.assertIn("/v4/account/typeform", args[0])
        self.assertEqual(kwargs["json"]["form_id"], "vnCgUn0n")
        self.assertTrue(str(kwargs["json"]["response_id"]).startswith("auto-"))
        self.assertEqual(result, {"success": True})

    def test_download_proxy_list_formats_userpass_lines(self):
        gr.config["ps_proxy_protocol"] = "http"
        gr.config["ps_proxy_format"] = "userpass"
        creds = fake_response(200, {"data": {"services": {"datacenter_shared": {"proxy_username": "u1", "proxy_password": "p1"}}}})
        self.http_get.side_effect = [creds, fake_response(200, text="1.2.3.4:8080\n5.6.7.8:9090\n")]
        lines = ps_api.ps_download_proxy_list("access-token", "acc-1", log_callback=lambda m: None)
        self.assertEqual(lines, ["u1:p1@1.2.3.4:8080", "u1:p1@5.6.7.8:9090"])
        # 第一次 GET 取账密，第二次 GET 取代理列表
        urls = [call.args[0] for call in self.http_get.call_args_list]
        self.assertIn("/v4/account/acc-1/datacenter_shared/proxy-list", urls[1])
        self.assertEqual(urls[1].split("?")[0].split("/")[-2], "datacenter_shared")

    def test_register_api_raises_on_error_response(self):
        self.http_post.return_value = fake_response(400, {"success": False, "message": "banned"})
        with self.assertRaises(Exception) as raised:
            ps_api.ps_register_api("user@example.com", "Passw0rd!", "tok")
        self.assertIn("banned", str(raised.exception))

    def test_failure_reason_extracts_message_or_error(self):
        self.assertEqual(ps_api.ps_failure_reason({"success": False, "message": "m1"}), "m1")
        self.assertEqual(ps_api.ps_failure_reason({"success": False, "error": "e1"}), "e1")
        self.assertEqual(ps_api.ps_failure_reason({"success": False}), "")


if __name__ == "__main__":
    unittest.main()
