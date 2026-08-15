# -*- coding: utf-8 -*-
"""Resin 订阅入池测试。"""
import unittest
from unittest import mock

from backend.integrations import ps_resin
from backend.registration import engine as gr


def fake_response(status_code=200, body=None, text=""):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.text = text
    if body is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = body
    return resp


class ResinTests(unittest.TestCase):
    def setUp(self):
        self.http_post = mock.Mock(return_value=fake_response(200, {"id": "sub-1"}))
        self.http_get = mock.Mock(
            return_value=fake_response(
                200,
                {"items": [{"id": "1", "name": "userA"}, {"id": "2", "name": "userB"}], "total": 2},
            )
        )
        self.http_delete = mock.Mock(return_value=fake_response(204))
        ps_resin.configure(
            http_post=self.http_post,
            http_get=self.http_get,
            http_delete=self.http_delete,
        )
        self.original_config = dict(gr.config)

    def tearDown(self):
        gr.config.clear()
        gr.config.update(self.original_config)
        ps_resin.configure(http_post=None, http_get=None, http_delete=None)

    def test_resin_enabled_requires_base_and_token(self):
        gr.config.pop("resin_base_url", None)
        gr.config.pop("resin_auth_token", None)
        self.assertFalse(ps_resin.resin_enabled())
        gr.config["resin_base_url"] = "http://resin.local"
        gr.config["resin_auth_token"] = "tok"
        self.assertTrue(ps_resin.resin_enabled())

    def test_push_subscription_posts_name_and_content(self):
        gr.config["resin_base_url"] = "http://resin.local"
        gr.config["resin_auth_token"] = "secret-token"
        gr.config["resin_subscriptions_path"] = "/api/v1/subscriptions"
        result = ps_resin.resin_push_subscription(
            "userA@example.com",
            ["u1:p1@1.2.3.4:8080", "u2:p2@5.6.7.8:9090"],
            log_callback=lambda m: None,
        )
        self.http_post.assert_called_once()
        args, kwargs = self.http_post.call_args
        self.assertEqual(args[0], "http://resin.local/api/v1/subscriptions")
        self.assertEqual(kwargs["headers"]["authorization"], "Bearer secret-token")
        self.assertEqual(kwargs["json"]["name"], "userA")
        self.assertIn(
            "http://u1:p1@1.2.3.4:8080\nhttp://u2:p2@5.6.7.8:9090",
            kwargs["json"]["content"],
        )
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["id"], "sub-1")

    def test_push_subscription_raises_when_unconfigured(self):
        gr.config.pop("resin_base_url", None)
        with self.assertRaises(Exception) as raised:
            ps_resin.resin_push_subscription("userA@example.com", ["1.2.3.4:8080"])
        self.assertIn("resin_base_url", str(raised.exception))
        self.http_post.assert_not_called()

    def test_list_subscriptions_parses_items(self):
        gr.config["resin_base_url"] = "http://resin.local"
        gr.config["resin_auth_token"] = "secret-token"
        items = ps_resin.resin_list_subscriptions(limit=100)
        self.assertEqual([x["name"] for x in items], ["userA", "userB"])
        self.assertIn("limit=100", self.http_get.call_args.args[0])

    def test_delete_subscription_sends_delete(self):
        gr.config["resin_base_url"] = "http://resin.local"
        gr.config["resin_auth_token"] = "secret-token"
        result = ps_resin.resin_delete_subscription("sub-9", log_callback=lambda m: None)
        self.http_delete.assert_called_once()
        args, kwargs = self.http_delete.call_args
        self.assertEqual(args[0], "http://resin.local/api/v1/subscriptions/sub-9")
        self.assertEqual(kwargs["headers"]["authorization"], "Bearer secret-token")
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["id"], "sub-9")

    def test_find_subscription_by_name_is_case_insensitive(self):
        subs = [{"id": "1", "name": "UserA"}, {"id": "2", "name": "userb"}]
        self.assertEqual(ps_resin.resin_find_subscription_by_name("usera", subs)["id"], "1")
        self.assertEqual(ps_resin.resin_find_subscription_by_name("USERB", subs)["id"], "2")
        self.assertIsNone(ps_resin.resin_find_subscription_by_name("nope", subs))

    def test_find_subscription_by_name_lists_when_not_given(self):
        gr.config["resin_base_url"] = "http://resin.local"
        gr.config["resin_auth_token"] = "secret-token"
        found = ps_resin.resin_find_subscription_by_name("userb")
        self.assertEqual(found["id"], "2")


if __name__ == "__main__":
    unittest.main()
