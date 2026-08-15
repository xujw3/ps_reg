# -*- coding: utf-8 -*-
"""run_registration 重试补号逻辑测试。

目标成功数语义：count = 目标成功账号数；失败自动换新邮箱重试，
直到达标或达到尝试上限（count × registration_retry_multiplier，默认 3）。
"""
import tempfile
import unittest
from unittest import mock

from backend.registration import engine as gr


def _patch_success_chain(tmp_dir, email="ok@dgu.edu.kg"):
    """mock 成功链所需函数；返回 (patchers, mocks)。"""
    patchers = [
        mock.patch.object(gr, "DATA_DIR", tmp_dir),
        mock.patch.object(gr, "registration_log"),
        mock.patch.object(gr, "new_registration_batch_id", return_value="batch-test"),
        mock.patch.object(gr, "reset_network_route_logs"),
        mock.patch.object(gr, "_cleanup_stale_profiles"),
        mock.patch.object(gr._conn, "run_connectivity_checks", return_value=[]),
        mock.patch.object(gr._conn, "has_blocking_ps_failure", return_value=False),
        mock.patch.object(gr, "start_browser"),
        mock.patch.object(gr, "stop_browser"),
        mock.patch.object(gr, "restart_browser"),
        mock.patch.object(gr, "maybe_stop_browser"),
        mock.patch.object(gr, "cleanup_runtime_memory"),
        mock.patch.object(gr, "parse_account_interval", return_value=0.0),
        mock.patch.object(gr, "persist_registration_result", return_value=1),
        mock.patch.object(gr, "capture_failure_screenshot", return_value=""),
        mock.patch.object(gr, "current_exception_traceback", return_value=""),
        mock.patch.object(gr, "account_file_for_email", return_value="ok-account.txt"),
        mock.patch.object(gr, "save_proxy_list_file", return_value="ok-proxy.txt"),
        mock.patch.object(gr, "save_account_record"),
        mock.patch.object(gr._psf, "open_ps_signup_page"),
        mock.patch.object(gr, "get_email_and_token", return_value=(email, "dev-token")),
        mock.patch.object(gr._psf, "fill_ps_signup_form"),
        mock.patch.object(gr._psf, "submit_ps_signup_and_wait_token", return_value="access-token"),
        mock.patch.object(gr, "get_oai_code", return_value="verify-code"),
        mock.patch.object(gr._ps_api, "ps_verify_email_api"),
        mock.patch.object(gr._ps_api, "ps_complete_typeform"),
        mock.patch.object(gr._ps_api, "ps_fetch_me", return_value={"data": {"subaccounts": []}}),
        mock.patch.object(
            gr._ps_api, "ps_pick_subaccount", return_value={"AccountID": "acc-1"}
        ),
        mock.patch.object(gr._ps_api, "ps_download_proxy_list", return_value=["1.2.3.4:80"]),
        mock.patch.object(gr._ps_resin, "resin_enabled", return_value=False),
    ]
    mocks = {}
    for p in patchers:
        m = p.start()
        mocks[p.attribute] = m
    return patchers, mocks


class RunRegistrationRetryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patchers = []
        self._patchers, self._mocks = _patch_success_chain(self._tmp.name)
        self.addCleanup(lambda: [p.stop() for p in self._patchers])

    def test_failure_then_success_retries_same_target(self):
        """目标 1：第一次失败、第二次成功 → 共尝试 2 次，最终成功 1。"""
        gr.config["register_workers"] = 1
        gr.config["registration_retry_multiplier"] = 3
        self._mocks["get_email_and_token"].side_effect = [
            RuntimeError("CloudMail 添加邮箱失败: 不存在的邮箱域名"),
            ("ok@dgu.edu.kg", "dev-token"),
        ]
        gr.run_registration(1)
        self.assertEqual(self._mocks["get_email_and_token"].call_count, 2)
        persist_kwargs = [
            c.kwargs for c in self._mocks["persist_registration_result"].call_args_list
        ]
        statuses = [k.get("status") for k in persist_kwargs]
        self.assertEqual(statuses, ["failure", "success"])

    def test_stops_after_attempt_budget(self):
        """目标 1、倍率 3：全部失败 → 恰好尝试 3 次后停止，无成功。"""
        gr.config["register_workers"] = 1
        gr.config["registration_retry_multiplier"] = 3
        self._mocks["get_email_and_token"].side_effect = RuntimeError("邮箱服务不可用")
        gr.run_registration(1)
        self.assertEqual(self._mocks["get_email_and_token"].call_count, 3)
        statuses = [
            c.kwargs.get("status")
            for c in self._mocks["persist_registration_result"].call_args_list
        ]
        self.assertEqual(statuses, ["failure", "failure", "failure"])

    def test_stops_when_success_target_reached(self):
        """目标 2：两次都成功 → 恰好 2 次后停止，不多试。"""
        gr.config["register_workers"] = 1
        gr.config["registration_retry_multiplier"] = 3
        gr.run_registration(2)
        self.assertEqual(self._mocks["get_email_and_token"].call_count, 2)
        statuses = [
            c.kwargs.get("status")
            for c in self._mocks["persist_registration_result"].call_args_list
        ]
        self.assertEqual(statuses, ["success", "success"])

    def test_budget_scales_with_multiplier(self):
        """目标 2、倍率 2：全部失败 → 尝试 4 次后停止。"""
        gr.config["register_workers"] = 1
        gr.config["registration_retry_multiplier"] = 2
        self._mocks["get_email_and_token"].side_effect = RuntimeError("邮箱服务不可用")
        gr.run_registration(2)
        self.assertEqual(self._mocks["get_email_and_token"].call_count, 4)


if __name__ == "__main__":
    unittest.main()
