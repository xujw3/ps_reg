# -*- coding: utf-8 -*-
"""YYDS 临时邮箱域名选择测试。

未配置固定域名时，从公开域名列表（vip.215.im/v1/domains）随机选一个
已验证域名（优先 isVerified+isMxValid）；固定域名优先。
"""
import unittest
from unittest import mock

from backend.mailbox import yyds_mail


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _domain(domain, verified=True, mx=True, public=True):
    return {
        "id": f"id-{domain}",
        "domain": domain,
        "isVerified": verified,
        "isMxValid": mx,
        "isPublic": public,
    }


def _ok_response(items):
    return _Resp({"success": True, "data": items})


class PickDomainTests(unittest.TestCase):
    def test_picks_verified_and_mx_valid_domain(self):
        http_get = mock.Mock(return_value=_ok_response([
            _domain("a.hzeg.eu.org"),
            _domain("b.hzeg.eu.org"),
        ]))
        picked = yyds_mail.pick_domain(http_get, api_key="k")
        self.assertIn(picked, {"a.hzeg.eu.org", "b.hzeg.eu.org"})
        # 走公开域名列表接口，无鉴权头
        call = http_get.call_args
        self.assertEqual(call.args[0], yyds_mail.PUBLIC_DOMAINS_URL)
        self.assertNotIn("headers", call.kwargs or {})

    def test_falls_back_to_verified_when_mx_invalid(self):
        http_get = mock.Mock(return_value=_ok_response([
            _domain("no-mx.hzeg.eu.org", mx=False),
            _domain("ok.hzeg.eu.org", mx=True),
        ]))
        picked = yyds_mail.pick_domain(http_get)
        self.assertEqual(picked, "ok.hzeg.eu.org")

    def test_skips_unverified_domains(self):
        http_get = mock.Mock(return_value=_ok_response([
            _domain("unverified.hzeg.eu.org", verified=False),
            _domain("good.hzeg.eu.org"),
        ]))
        picked = yyds_mail.pick_domain(http_get)
        self.assertEqual(picked, "good.hzeg.eu.org")

    def test_raises_when_no_verified_domains(self):
        http_get = mock.Mock(return_value=_ok_response([
            _domain("only-unverified.hzeg.eu.org", verified=False),
        ]))
        with self.assertRaises(Exception) as ctx:
            yyds_mail.pick_domain(http_get)
        self.assertIn("无已验证域名", str(ctx.exception))

    def test_raises_when_empty_list(self):
        http_get = mock.Mock(return_value=_ok_response([]))
        with self.assertRaises(Exception) as ctx:
            yyds_mail.pick_domain(http_get)
        self.assertIn("没有返回任何可用域名", str(ctx.exception))

    def test_random_pick_spans_multiple_domains(self):
        """随机性：多次抽取应覆盖列表中的多个域名。"""
        http_get = mock.Mock(return_value=_ok_response([
            _domain(f"d{i}.hzeg.eu.org") for i in range(6)
        ]))
        picked = {yyds_mail.pick_domain(http_get) for _ in range(40)}
        # 40 次抽样覆盖 6 个域名，几乎必然 >1
        self.assertGreater(len(picked), 1)


class CreateMailboxDomainTests(unittest.TestCase):
    def _make_http(self, domains=None):
        domains = domains or [_domain("free.hzeg.eu.org")]

        def http_get(url, **kwargs):
            if url == yyds_mail.PUBLIC_DOMAINS_URL:
                return _ok_response(domains)
            return _ok_response({"success": True, "data": []})

        return mock.Mock(side_effect=http_get)

    def test_uses_fixed_domain_without_public_fetch(self):
        http_get = mock.Mock(return_value=_ok_response({"success": True, "data": []}))
        http_post = mock.Mock(return_value=_Resp({
            "success": True,
            "data": {"address": "abc123@fixed.hzeg.eu.org", "token": "t"},
        }))
        address, token = yyds_mail.create_mailbox(
            http_get, http_post, api_key="k", default_domain="fixed.hzeg.eu.org"
        )
        self.assertEqual(address, "abc123@fixed.hzeg.eu.org")
        self.assertEqual(token, "t")
        payload = http_post.call_args.kwargs["json"]
        self.assertEqual(payload["domain"], "fixed.hzeg.eu.org")
        # 固定域名时不应拉公开列表
        for call in http_get.call_args_list:
            self.assertNotEqual(call.args[0], yyds_mail.PUBLIC_DOMAINS_URL)

    def test_random_domain_when_not_configured(self):
        domains = [_domain(f"free{i}.hzeg.eu.org") for i in range(4)]
        http_get = self._make_http(domains)
        http_post = mock.Mock(return_value=_Resp({
            "success": True,
            "data": {"address": "abc123@free1.hzeg.eu.org", "token": "t"},
        }))
        address, token = yyds_mail.create_mailbox(http_get, http_post, api_key="k")
        self.assertEqual(token, "t")
        payload = http_post.call_args.kwargs["json"]
        self.assertIn(payload["domain"], {d["domain"] for d in domains})
        # 确实拉取了公开域名列表
        urls = [call.args[0] for call in http_get.call_args_list]
        self.assertIn(yyds_mail.PUBLIC_DOMAINS_URL, urls)


if __name__ == "__main__":
    unittest.main()
