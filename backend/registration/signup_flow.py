# -*- coding: utf-8 -*-
"""注册页面步骤。

封装 Turnstile 挑战处理、邮箱域名拦截检测等浏览器交互通用工具。
"""
from __future__ import annotations

import os
import random
import re
import secrets
import string
import threading
import time
from typing import Any, Dict

from playwright._impl._errors import TargetClosedError as PageDisconnectedError

from backend.automation.session import (
    active_browser,
    active_page,
    browser,
    page,
    refresh_active_page,
    restart_browser,
    set_browser_session,
    start_browser,
    stop_browser,
)


class AccountAlreadyRegistered(Exception):
    """资料提交后站点明确提示邮箱或账号已经存在。"""


_ALREADY_REGISTERED_PATTERNS = (
    re.compile(r"existing account found", re.I),
    re.compile(r"email.{0,80}already.{0,40}(?:registered|exists|in use|used|taken)", re.I),
    re.compile(r"account.{0,80}already.{0,40}(?:registered|exists)", re.I),
    re.compile(r"already.{0,40}registered.{0,80}email", re.I),
    re.compile(r"user.{0,60}already.{0,40}exists", re.I),
    re.compile(r"email.{0,40}(?:is|address is).{0,20}(?:unavailable|not available)", re.I),
    re.compile(r"邮箱.{0,40}(?:已|已经).{0,40}(?:注册|存在|使用|占用)"),
    re.compile(r"账号.{0,40}(?:已|已经).{0,40}(?:注册|存在)"),
    re.compile(r"找到现有(?:账号|账户)"),
    re.compile(r"(?:账号|账户).{0,20}(?:已|已经).{0,40}(?:注册|存在)"),
    re.compile(r"已存在与此邮箱地址关联的(?:账号|账户)"),
)

_deps: Dict[str, Any] = {}
_runtime = threading.local()


def configure(**kwargs):
    _deps.update(kwargs)


def last_acquired_email() -> str:
    return str(getattr(_runtime, "last_email", "") or "")


def last_profile() -> Dict[str, str]:
    return dict(getattr(_runtime, "last_profile", {}) or {})


def _AccountRetryNeeded(msg=""):
    cls = _deps.get("AccountRetryNeeded", Exception)
    return cls(msg)


def raise_if_cancelled(cancel_callback=None):
    fn = _deps.get("raise_if_cancelled")
    if fn:
        return fn(cancel_callback)


def sleep_with_cancel(seconds, cancel_callback=None):
    fn = _deps.get("sleep_with_cancel")
    if fn:
        return fn(seconds, cancel_callback)
    time.sleep(max(seconds, 0))


def _native_attr(element, name: str) -> str:
    try:
        value = element.attr(name)
    except Exception:
        value = ""
    return str(value or "").strip()


def _native_is_usable(element) -> bool:
    try:
        states = element.states
        if getattr(states, "is_alive", True) is False:
            return False
        if getattr(states, "is_displayed", True) is False:
            return False
        if getattr(states, "is_enabled", True) is False:
            return False
    except Exception:
        return False
    return True


def _native_label(element) -> str:
    parts = []
    try:
        parts.append(str(element.text or ""))
    except Exception:
        pass
    for name in ("aria-label", "title", "value", "placeholder", "name", "id", "data-testid", "autocomplete"):
        value = _native_attr(element, name)
        if value:
            parts.append(value)
    return " ".join(parts).replace("\u00a0", " ").strip()


def _native_elements(tag: str):
    try:
        return list(page.eles(f"tag:{tag}") or [])
    except Exception:
        return []


def _native_click_action(keywords, deny_keywords=()) -> str:
    """按可见文本用 CDP 原生事件点击；返回按钮文字。"""
    keys = [str(x).replace(" ", "").lower() for x in keywords]
    denied = [str(x).replace(" ", "").lower() for x in deny_keywords]
    candidates = []
    for tag in ("button", "a", "input"):
        for element in _native_elements(tag):
            if not _native_is_usable(element):
                continue
            if tag == "input" and _native_attr(element, "type").lower() not in (
                "submit",
                "button",
            ):
                continue
            if _native_attr(element, "aria-disabled").lower() == "true":
                continue
            label = _native_label(element)
            compact = re.sub(r"\s+", "", label).lower()
            if not compact or any(item in compact for item in denied):
                continue
            score = max((len(item) for item in keys if item and item in compact), default=0)
            if score:
                candidates.append((score, element, label))
    for _, element, label in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            element.click(timeout=3)
            return label
        except Exception:
            # 原生点击失败（可能被 Cookie 横幅等覆盖），尝试 JS 直接点击
            try:
                element.click(by_js=True)
                return label
            except Exception:
                continue
    return ""


def _native_type_element(element, value: str, per_char: bool = True) -> bool:
    """使用 Playwright 真实键盘事件输入，避免 JS setter 产生 isTrusted=false 事件。"""
    if not element or not _native_is_usable(element):
        return False
    text = str(value or "")
    try:
        element.click(timeout=3)
        if per_char:
            for index, char in enumerate(text):
                element.input(char, clear=index == 0, by_js=False)
                if index + 1 < len(text):
                    time.sleep(random.uniform(0.02, 0.06))
        else:
            element.input(text, clear=True, by_js=False)
        try:
            current = str(element.property("value") or "")
        except Exception:
            current = None
        # property 无法读取时交给页面推进检查；明确读到空值表示输入没有生效。
        return current is None or current.strip() == text.strip()
    except Exception:
        return False


def _native_input_candidates(kind: str):
    scored = []
    for tag in ("input", "textarea"):
        for element in _native_elements(tag):
            if not _native_is_usable(element):
                continue
            typ = _native_attr(element, "type").lower()
            if typ in ("hidden", "submit", "button", "checkbox", "radio", "file", "search"):
                continue
            meta = _native_label(element).lower()
            name = _native_attr(element, "name").lower()
            testid = _native_attr(element, "data-testid").lower()
            autocomplete = _native_attr(element, "autocomplete").lower()
            inputmode = _native_attr(element, "inputmode").lower()
            maxlength = _native_attr(element, "maxlength")
            try:
                max_len = int(maxlength or 0)
            except ValueError:
                max_len = 0
            score = 0
            if kind == "email":
                score = (100 if typ == "email" else 0) + (90 if name == "email" else 0)
                score += 80 if "email" in autocomplete else 0
                score += 70 if "email" in testid else 0
                score += 40 if any(x in meta for x in ("email", "mail", "邮箱")) else 0
            elif kind == "code":
                score = (100 if testid == "code" or name == "code" else 0)
                score += 90 if autocomplete == "one-time-code" else 0
                score += 70 if inputmode in ("numeric", "decimal") else 0
                score += 50 if max_len > 1 else 0
            elif kind == "code_box":
                score = 100 if max_len == 1 else 0
                score += 80 if autocomplete == "one-time-code" else 0
            elif kind == "given":
                score = 100 if testid in ("givenname", "firstname") or name in ("givenname", "firstname") else 0
                score += 90 if autocomplete == "given-name" else 0
                score += 40 if any(x in meta for x in ("given", "first name", "firstname", "名")) else 0
            elif kind == "family":
                score = 100 if testid in ("familyname", "lastname", "surname") or name in ("familyname", "lastname", "surname") else 0
                score += 90 if autocomplete == "family-name" else 0
                score += 40 if any(x in meta for x in ("family", "last name", "lastname", "surname", "姓")) else 0
            elif kind == "password":
                score = 110 if typ == "password" else 0
                score += 90 if name == "password" or "password" in autocomplete else 0
                score += 60 if "password" in meta or "密码" in meta else 0
            if score:
                scored.append((score, element))
    return [element for _, element in sorted(scored, key=lambda item: item[0], reverse=True)]


def _native_fill_email(email: str) -> bool:
    candidates = _native_input_candidates("email")
    return bool(candidates and _native_type_element(candidates[0], email))


def _native_fill_code(code: str) -> str:
    aggregate = _native_input_candidates("code")
    if aggregate and _native_type_element(aggregate[0], code):
        return "filled-aggregate"
    boxes = _native_input_candidates("code_box")
    if len(boxes) < len(code):
        return "not-ready"
    if all(_native_type_element(box, char, per_char=False) for box, char in zip(boxes, code)):
        return "filled-boxes"
    return "boxes-failed"


def _native_fill_profile(given_name: str, family_name: str, password: str) -> bool:
    given = _native_input_candidates("given")
    family = _native_input_candidates("family")
    secret = _native_input_candidates("password")
    if not given or not family or not secret:
        return False
    return all(
        (
            _native_type_element(given[0], given_name),
            _native_type_element(family[0], family_name),
            _native_type_element(secret[0], password),
        )
    )


def _dismiss_cookie_consent(log_callback=None):
    """尝试关闭 OneTrust / 通用 Cookie 同意横幅，避免遮挡按钮。"""
    try:
        dismissed = page.run_js(r"""
// OneTrust: 点击 "Accept All" / "全部接受" 按钮
const oneTrustBtn = document.querySelector('#onetrust-accept-btn-handler, #accept-recommended-btn-handler');
if (oneTrustBtn) { oneTrustBtn.click(); return 'OneTrust'; }
// 通用：查找带 "Accept" / "接受" / "同意" / "Agree" 文本的按钮
const btns = Array.from(document.querySelectorAll('button, a, [role="button"]'));
for (const b of btns) {
    const t = (b.innerText || b.textContent || '').trim().toLowerCase();
    if (t === 'accept all' || t === 'accept' || t === 'agree' || t === '同意' || t === '全部接受' || t === '接受') {
        b.click(); return 'generic:' + t;
    }
}
return '';
        """)
        if dismissed and log_callback:
            log_callback(f"[*] 已关闭 Cookie 横幅: {dismissed}")
    except Exception:
        pass


def detect_email_domain_rejection(email=""):
    """检测 xAI 是否拒绝当前邮箱域名。

    返回拒绝文案字符串；未检测到则返回空字符串。
    """
    if not page:
        return ""
    try:
        result = page.run_js(
            r"""
function collectText() {
    const chunks = [];
    const selectors = [
        '[role="alert"]',
        '[data-testid*="error" i]',
        '[class*="error" i]',
        '[class*="Error"]',
        '[class*="danger" i]',
        '[class*="invalid" i]',
        'p', 'span', 'div', 'li', 'label',
    ];
    for (const sel of selectors) {
        for (const node of Array.from(document.querySelectorAll(sel)).slice(0, 80)) {
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            const text = (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
            if (text && text.length >= 8 && text.length <= 400) chunks.push(text);
        }
    }
    const body = (document.body && (document.body.innerText || document.body.textContent) || '')
        .replace(/\s+/g, ' ').trim();
    if (body) chunks.push(body.slice(0, 1200));
    return Array.from(new Set(chunks));
}
const texts = collectText();
const patterns = [
    /邮箱域名[^。\n]{0,80}被拒绝/,
    /域名[^。\n]{0,40}已被拒绝/,
    /已被拒绝[^。\n]{0,40}邮箱/,
    /email domain[^.\n]{0,80}rejected/i,
    /domain[^.\n]{0,40}(has been |is )?rejected/i,
    /please use (a )?different email/i,
    /use another email address/i,
    /请使用其他邮箱/,
    /support@x\.ai/,
];
for (const text of texts) {
    for (const re of patterns) {
        if (re.test(text)) {
            const m = text.match(/.{0,40}(拒绝|rejected|different email|其他邮箱).{0,80}/i);
            return (m && m[0]) || text.slice(0, 180);
        }
    }
}
return '';
            """
        )
        if isinstance(result, str) and result.strip():
            return result.strip()
    except Exception:
        pass
    return ""


def raise_if_email_domain_rejected(email=""):
    message = detect_email_domain_rejection(email)
    if message:
        raise _deps['EmailDomainRejected'](email=email, message=message)


def _fill_cf_turnstile_token(token) -> Any:
    """把 Turnstile token 写回页面隐藏域。"""
    return page.run_js(
        """
const token = String(arguments[0] || '').trim();
const cfInput = document.querySelector('input[name="cf-turnstile-response"]');
if (!cfInput || !token) return false;
const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
if (nativeSetter) nativeSetter.call(cfInput, token);
else cfInput.value = token;
cfInput.dispatchEvent(new Event('input', { bubbles: true }));
cfInput.dispatchEvent(new Event('change', { bubbles: true }));
return String(cfInput.value || '').trim().length;
        """,
        token,
    )


def _try_sync_turnstile(
    log_callback=None,
    cancel_callback=None,
    reason="自动复用 Turnstile",
) -> bool:
    """主动获取 Turnstile token 并回填；成功返回 True。

    优化：先快速读取已有 token，只有 token 为空时才进入完整获取流程。
    避免每次调用都进入 30 秒循环，导致 widget 被 reset 打断。
    """
    if log_callback:
        log_callback(f"[*] {reason}...")

    # 先快速读取已有 token（不 reset，不阻塞）
    try:
        existing = page.run_js(
            """
try {
  const byInput = String((document.querySelector('input[name="cf-turnstile-response"]') || {}).value || '').trim();
  if (byInput) return byInput;
  if (window.turnstile && typeof turnstile.getResponse === 'function') {
    return String(turnstile.getResponse() || '').trim();
  }
  return '';
} catch(e) { return ''; }
            """
        )
        existing = str(existing or "").strip()
        if len(existing) >= 80:
            synced = _fill_cf_turnstile_token(existing)
            if log_callback:
                log_callback(f"[*] Turnstile token 已就绪，回填长度={synced}")
            return bool(synced and int(synced or 0) >= 80)
    except Exception:
        pass

    # token 为空，进入完整获取流程（被动等待优先，不 reset）
    try:
        token = getTurnstileToken(log_callback=log_callback, cancel_callback=cancel_callback)
        if not token:
            return False
        synced = _fill_cf_turnstile_token(token)
        if log_callback:
            log_callback(f"[*] Turnstile 二次复用完成，回填长度={synced}")
        return bool(synced and int(synced or 0) >= 80)
    except Exception as cf_exc:
        if log_callback:
            log_callback(f"[Debug] Turnstile 二次复用失败: {cf_exc}")
        return False


def getTurnstileToken(log_callback=None, cancel_callback=None, force_reset=False):
    """获取 Turnstile token（直接点击 + 轮询等待）。

    Turnstile iframe 内无 checkbox DOM 元素（canvas/overlay 渲染），
    managed 模式不会自动通过，所以：
    1. 直接通过 raw_page.frames 定位 frame 并坐标点击
    2. 轮询等待 token 出现
    3. 未通过则间隔重试点击
    """
    if active_page() is None:
        raise Exception("页面未就绪，无法执行 Turnstile")

    click_attempted = False
    last_click_round = -100
    consecutive_click_failures = 0
    TOTAL_ROUNDS = 20
    POLL_INTERVAL = 2.0

    for _ in range(0, TOTAL_ROUNDS):
        raise_if_cancelled(cancel_callback)
        token = ""
        try:
            token = page.run_js(
                """
try {
  const byInput = String((document.querySelector('input[name="cf-turnstile-response"]') || {}).value || '').trim();
  if (byInput) return byInput;
  if (window.turnstile && typeof turnstile.getResponse === 'function') {
    return String(turnstile.getResponse() || '').trim();
  }
  return '';
} catch(e) { return ''; }
                """,
                timeout=6000,
            )
            token = str(token or "").strip()
        except Exception:
            # run_js 偶发失败（页面忙/跳转中）：本轮跳过，下一轮重试
            token = ""
        if len(token) >= 80:
            if log_callback:
                log_callback(f"[*] Turnstile 已通过，token长度={len(token)}")
            return token

        # 直接点击（首次或间隔重试）
        if not click_attempted or (_ - last_click_round >= 4):
            if not click_attempted:
                if log_callback:
                    log_callback("[*] 尝试点击 Turnstile...")
            else:
                if log_callback:
                    log_callback("[*] 再次尝试点击 Turnstile...")
            clicked = _try_click_turnstile_frame(log_callback=log_callback)
            if clicked:
                consecutive_click_failures = 0
            else:
                consecutive_click_failures += 1
                if consecutive_click_failures >= 3:
                    # 连续 3 轮点击全部失败：浏览器/Turnstile 交互已损坏，
                    # 立即失败交给上层重启浏览器，不再空转 20 轮
                    raise Exception(
                        "Turnstile 连续点击失败（浏览器交互异常），等待重启重试"
                    )
            click_attempted = True
            last_click_round = _
            sleep_with_cancel(3.0, cancel_callback)
            continue
        sleep_with_cancel(POLL_INTERVAL, cancel_callback)

    raise Exception("Turnstile 获取 token 失败")


def _try_click_turnstile_frame(log_callback=None):
    """通过 Playwright frame API 点击 Turnstile checkbox。

    全链路诊断日志 + 多策略点击：
    1. 遍历 frames 找到 Turnstile frame（日志输出找到/未找到 + frame URL）
    2. 在 frame 内搜索 checkbox 元素（日志输出尝试了哪些选择器）
    3. 找到则点击；未找到则走 body 坐标点击 fallback
    4. frame 内点击失败则尝试 page 级 iframe 坐标点击
    """
    try:
        raw_page = page.raw_page
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] Turnstile 点击失败：无法获取 raw_page: {exc}")
        return False

    # ---- 遍历 Playwright frames 找到 Turnstile frame ----
    turnstile_frame = None
    all_frame_urls = []
    for frame in raw_page.frames:
        frame_url = str(frame.url or "")
        all_frame_urls.append(frame_url[:80])
        if "challenges.cloudflare.com" in frame_url or "turnstile" in frame_url.lower():
            turnstile_frame = frame
            break

    if not turnstile_frame:
        if log_callback:
            log_callback(
                f"[Debug] Turnstile frame 未找到。当前 frames({len(all_frame_urls)}): "
                f"{all_frame_urls}"
            )
        return False

    frame_url = str(turnstile_frame.url or "")
    if log_callback:
        log_callback(f"[Debug] Turnstile frame 已定位: {frame_url[:100]}")

    # ---- 策略 1：frame body 坐标点击（Turnstile 实际交互方式）----
    # Turnstile iframe 内没有 checkbox DOM 元素（inputs=[]），
    # 交互区域是 canvas/overlay，只能通过坐标点击。
    # checkbox 标准位置在 iframe 左侧 24px 处。
    try:
        body_info = turnstile_frame.evaluate(
            """
() => {
  const b = document.body;
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return { w: r.width, h: r.height };
}
            """,
            timeout=5000,
        )
        if log_callback:
            bi = body_info or {}
            log_callback(
                f"[Debug] Turnstile frame body: w={bi.get('w', 0):.0f} h={bi.get('h', 0):.0f}"
            )

        if not body_info or body_info.get("w", 0) <= 0:
            if log_callback:
                log_callback("[Debug] Turnstile frame body 未渲染好，跳过")
            return False

        click_x = 24
        click_y = body_info["h"] / 2
        turnstile_frame.click("body", position={"x": click_x, "y": click_y}, timeout=3000)
        if log_callback:
            log_callback(f"[*] 已点击 Turnstile frame body ({click_x}, {click_y:.0f})")
        return True
    except Exception as frame_click_exc:
        if log_callback:
            log_callback(f"[Debug] Turnstile frame body 点击失败: {frame_click_exc}")
        # force 重试：跳过 actionability 检查（Xvfb/虚拟显示器下 perform click 可能挂起）
        try:
            click_x = 24
            click_y = 0
            try:
                body_info = turnstile_frame.evaluate(
                    "() => { const b = document.body; if (!b) return null; "
                    "const r = b.getBoundingClientRect(); return { w: r.width, h: r.height }; }",
                    timeout=5000,
                )
                click_y = (body_info or {}).get("h", 0) / 2
            except Exception:
                click_y = 32
            turnstile_frame.locator("body").click(
                position={"x": click_x, "y": click_y}, force=True, timeout=3000
            )
            if log_callback:
                log_callback(f"[*] 已 force 点击 Turnstile frame body ({click_x}, {click_y:.0f})")
            return True
        except Exception as force_exc:
            if log_callback:
                log_callback(f"[Debug] Turnstile force 点击失败: {force_exc}")

    # ---- 策略 2：page 级 iframe 坐标点击（frame 点击被 CSP 拦截 / shadow DOM 内）----
    # 注意：不能用 raw_page.query_selector 找 iframe——MUI 的 Turnstile iframe 在
    # shadow DOM 内，query_selector 不穿透 shadow root。frame_element() 直接返回
    # 已定位 frame 对应的 iframe 元素，任何嵌套深度都能拿到。
    # 用 ElementHandle.click（带 timeout）替代 raw_page.mouse.click——
    # 后者无超时参数，Xvfb 下协议调用可能无限挂起导致整轮卡死。
    try:
        iframe_el = turnstile_frame.frame_element()
        box = iframe_el.bounding_box()
        if box and box["width"] > 0:
            iframe_el.click(
                position={"x": 24, "y": box["height"] / 2},
                timeout=4000,
            )
            if log_callback:
                log_callback(f"[*] 已在 page 级点击 Turnstile iframe 元素")
            return True
        if log_callback:
            log_callback(f"[Debug] Turnstile iframe 元素无尺寸: {box}")
    except Exception as page_click_exc:
        if log_callback:
            log_callback(f"[Debug] Turnstile page 级点击失败: {page_click_exc}")
    return False
