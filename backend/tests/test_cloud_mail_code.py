# -*- coding: utf-8 -*-
"""CloudMail 取码：验证码必须按邮件原文返回，不做大小写转换。

背景（故障复现）：ProxyScrape 验证码邮件同一封里两个分支大小写不同 ——

    text/plain : YOUR CODE: F8C9B6A11F      （模板 upper 显示）
    text/html  : <span>f8c9b6a11f</span>    （模板原值）

CloudMail 的 /api/public/emailList 同时返回 content(HTML) 与 text(纯文本)。
若把纯文本排在前面，取到的是大写那份；提交给 /v4/account/verify-email 会被判
"Incorrect verification code."（HTTP 400）。所以组装时 HTML 剥标签文本优先，
纯文本兜底，且整个链路不做 upper()/lower() 归一化。
"""

import unittest
from unittest import mock

from backend.mailbox import cloud_mail as cm

HTML_TAIL = (
    '<h1 class="h1" style="color:#FFFFFF">Your code: '
    '<span style="color:#A1D0FF">f8c9b6a11f</span></h1>'
    '<p>Enter this code to verify your email address.</p>'
)

PLAIN_TEXT = (
    "VERIFY YOUR EMAIL\n\n\u00a0\n\n\nYOUR CODE: F8C9B6A11F\n\n\u00a0\n\n"
    "Enter this code to verify your email address."
)

ADDRESS = "b7m05gn3ni@xujwx.com"


def _wait(messages):
    with mock.patch.object(cm, "get_shared_token", return_value="public-token"), \
         mock.patch.object(cm, "public_email_list", return_value=messages), \
         mock.patch.object(cm, "cleanup_address", return_value=None):
        return cm.wait_for_code(
            None,
            None,
            "https://mail.example.test",
            "admin@example.test",
            "pw",
            ADDRESS,
            timeout=5,
            poll_interval=0,
            raise_if_cancelled=lambda cb: None,
            sleep_with_cancel=lambda s, cb: None,
        )


class CloudMailCodeCaseTests(unittest.TestCase):
    def test_html_original_case_wins_over_upper_plain_text(self):
        messages = [
            {
                "emailId": 42,
                "toEmail": ADDRESS,
                "subject": "ProxyScrape - Email Verification",
                "content": f"<html><body>{HTML_TAIL}</body></html>",
                "text": PLAIN_TEXT,
            }
        ]
        self.assertEqual(_wait(messages), "f8c9b6a11f")

    def test_plain_text_used_when_html_missing_and_case_kept(self):
        # 只有纯文本时按原文返回（大写就大写，不强行 lower）。
        messages = [
            {
                "emailId": 43,
                "toEmail": ADDRESS,
                "subject": "ProxyScrape - Email Verification",
                "text": PLAIN_TEXT,
            }
        ]
        self.assertEqual(_wait(messages), "F8C9B6A11F")

    def test_legacy_xai_template_untouched(self):
        messages = [
            {
                "emailId": 44,
                "toEmail": ADDRESS,
                "subject": "Your X verification code",
                "text": "Your verification code is I6R-B2W - do not share it.",
            }
        ]
        self.assertEqual(_wait(messages), "I6R-B2W")


if __name__ == "__main__":
    unittest.main()