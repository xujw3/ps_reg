"""验证码提取正则的回归测试。

背景（故障复现）：ProxyScrape 把验证码邮件模板从

    Here is your email verification code: 774dc99b9f

换成了

    VERIFY YOUR EMAIL
    YOUR CODE: F2FC0BA7DF
    Enter this code to verify your email address.

模板里不再有 "verification code" 字样，token 也从 3-3 短横线（x.ai: I6R-B2W）
变成 10 位 hex，于是旧正则全部落空，注册流程卡在 180s code_timeout。
HTML 版本还把小写 token 包在 <span> 里（`Your code: <span>f2fc0ba7df</span>`），
冒号与 token 之间夹标签，必须先剥 HTML 才能匹配。

注意：纯文本与 HTML 的码大小写本来就不同（模板上/下文各写各的），
提取只做原文透传 —— 不做 lower()/upper() 之类归一化，邮件给什么就返回什么。
"""

import base64
import quopri
import unittest

from backend.mailbox.utilities import extract_verification_code, strip_html

# 纯文本分支（YOUR CODE: xxx）
PROXYSCRAPE_CODE_TEXT = "F2FC0BA7DF"
# HTML 分支（<span>xxx</span>），大小写与上面不同，必须原样返回
PROXYSCRAPE_CODE_HTML = "f2fc0ba7df"
XAI_CODE = "I6R-B2W"

# 线上抓到的真实 HTML 片段（只截取 h1 附近）。
PROXYSCRAPE_HTML = (
    '<h1 class="h1" style="margin:0;font-family:\'Poppins\', Arial;font-size:36px;'
    'line-height:44px;font-weight:700;color:#FFFFFF">Your code: '
    '<span style="color:#A1D0FF">f2fc0ba7df</span></h1>'
    '<div style="height:16px;line-height:16px;font-size:0">&#160;</div>'
    '<p style="color:#CDD0DD">Enter this code to verify your email address.</p>'
)

PROXYSCRAPE_TEXT = (
    "VERIFY YOUR EMAIL\n\n\u00a0\n\n\nYOUR CODE: F2FC0BA7DF\n\n\u00a0\n\n"
    "Enter this code to verify your email address.\n\n\u00a0\n\n"
    "Kind regards, The ProxyScrape team."
)


class YourCodeTemplateTests(unittest.TestCase):
    def test_plain_text_your_code(self):
        self.assertEqual(extract_verification_code(PROXYSCRAPE_TEXT), PROXYSCRAPE_CODE_TEXT)

    def test_stripped_html_your_code(self):
        # 剥标签后得到 "Your code: f2fc0ba7df"，统一归一化为大写（与纯文本一致）。
        self.assertEqual(extract_verification_code(strip_html(PROXYSCRAPE_HTML)), PROXYSCRAPE_CODE_HTML)

    def test_raw_html_retry_without_pre_strip(self):
        # 调用方直接喂 HTML 原文也能出码。
        self.assertEqual(extract_verification_code(PROXYSCRAPE_HTML), PROXYSCRAPE_CODE_HTML)

    def test_full_mail_body_with_css_noise(self):
        # HTML 里带的 CSS 类名 / 颜色值不应抢在真码之前被命中。
        noisy = (
            '<html><head><style>.contentwrapper123456{width:100%}'
            ".btn-glow{box-shadow:0 0 0 1px rgba(43,137,203,.45)}</style></head>"
            "<body>" + PROXYSCRAPE_HTML + "</body></html>"
        )
        self.assertEqual(extract_verification_code(strip_html(noisy)), PROXYSCRAPE_CODE_HTML)


class FalsePositiveTests(unittest.TestCase):
    def test_hex_color_without_code_context(self):
        self.assertIsNone(extract_verification_code("background-color:#262B41 panel"))

    def test_css_class_token(self):
        self.assertIsNone(extract_verification_code(".contentwrapper123456{width:100%} No code here"))

    def test_short_promo_code(self):
        # 6 位 promo code 太短，不是模板里的 8-16 位验证码；纯字母词也不该命中。
        self.assertIsNone(extract_verification_code("promo code: SAVE20 only"))
        self.assertIsNone(extract_verification_code("code: PROXYSCRAPE"))


class OtherProviderTemplateTests(unittest.TestCase):
    def test_xai_dashed_code_still_works(self):
        self.assertEqual(
            extract_verification_code(f"Your verification code is {XAI_CODE} - do not share it."),
            XAI_CODE,
        )

    def test_numeric_code_with_context(self):
        self.assertEqual(extract_verification_code("verification code: 482913"), "482913")

    def test_quoted_printable_new_template(self):
        body = quopri.encodestring(PROXYSCRAPE_TEXT.encode("utf-8")).decode("ascii")
        raw = (
            "From: ProxyScrape <no-reply@proxyscrape.com>\r\n"
            "Subject: ProxyScrape - Email Verification\r\n"
            "Content-Type: text/plain; charset=UTF-8\r\n"
            "Content-Transfer-Encoding: quoted-printable\r\n"
            "\r\n" + body
        )
        self.assertIn(PROXYSCRAPE_CODE_TEXT, raw)
        message_body = raw.split("\r\n\r\n", 1)[1]
        decoded = quopri.decodestring(message_body.encode("ascii")).decode("utf-8")
        self.assertEqual(extract_verification_code(decoded), PROXYSCRAPE_CODE_TEXT)

    def test_base64_html_new_template(self):
        body = base64.b64encode(
            f"<html><body>{PROXYSCRAPE_HTML}</body></html>".encode("utf-8")
        ).decode("ascii")
        decoded = base64.b64decode(body).decode("utf-8")
        self.assertEqual(extract_verification_code(strip_html(decoded)), PROXYSCRAPE_CODE_HTML)


if __name__ == "__main__":
    unittest.main()