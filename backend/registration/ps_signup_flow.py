# -*- coding: utf-8 -*-
"""ProxyScrape 注册页浏览器流程。

在 dashboard.proxyscrape.com/v2/sign-up 上完成表单填写、条款勾选、
Turnstile 等待与提交后 accessToken 轮询。复用 ``signup_flow`` 的
page 代理、取消/休眠工具与 Turnstile 处理。
"""
from __future__ import annotations

import json
import time

from backend.automation.session import (
    active_page,
    page,
    restart_browser,
    start_browser,
)
from backend.integrations import ps_api
from backend.registration import signup_flow

raise_if_cancelled = signup_flow.raise_if_cancelled
sleep_with_cancel = signup_flow.sleep_with_cancel
_gr = ps_api._gr


def _ensure_page():
    if active_page() is None:
        start_browser()
    return page


def _ps_dashboard_base() -> str:
    return ps_api._ps_dashboard_base()


def _ps_signup_url() -> str:
    return str(_gr().config.get("ps_signup_url") or f"{_ps_dashboard_base()}/sign-up")


def _ps_run_js(page_obj, script: str, *args, log_callback=None):
    """run_js 封装：list/dict 参数先 JSON 字符串化。"""
    safe_args = []
    for a in args:
        if isinstance(a, (list, dict, tuple)):
            safe_args.append(json.dumps(a, ensure_ascii=False))
        else:
            safe_args.append(a)
    try:
        return page_obj.run_js(script, *safe_args)
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] run_js 失败: {exc}")
        raise


def _ps_parse_js_result(raw):
    if raw is None:
        return {}
    if isinstance(raw, (dict, list, int, float, bool)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            return {"raw": s}
    return {"raw": str(raw)}


def clear_ps_auth_session(log_callback=None, cancel_callback=None) -> bool:
    """清除 ProxyScrape 登录态（先打开同源页再清 storage）。"""
    page_obj = active_page()
    if page_obj is None:
        return False
    base = _ps_dashboard_base()
    for url in (f"{base}/login", f"{base}/sign-up", "https://dashboard.proxyscrape.com/"):
        try:
            page_obj.get(url)
            sleep_with_cancel(0.3, cancel_callback)
            break
        except Exception:
            continue
    try:
        page_obj.run_js(
            r"""
try { localStorage.removeItem('accessToken'); } catch(e) {}
try { localStorage.removeItem('access_token'); } catch(e) {}
try { localStorage.removeItem('refreshToken'); } catch(e) {}
try { localStorage.removeItem('userData'); } catch(e) {}
try { localStorage.removeItem('rtnUrl'); } catch(e) {}
try { localStorage.clear(); } catch(e) {}
try { sessionStorage.clear(); } catch(e) {}
try {
  document.cookie.split(';').forEach(function(c){
    var n = c.replace(/^ +/, '').split('=')[0];
    document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
    document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.proxyscrape.com';
    document.cookie = n + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=dashboard.proxyscrape.com';
  });
} catch(e) {}
return true;
"""
        )
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] clear PS storage 失败: {exc}")
    return True


def _ps_signup_form_ready(page_obj) -> dict:
    """检测是否真的在注册表单页（而不是已登录 dashboard）。"""
    try:
        raw = _ps_run_js(
            page_obj,
            r"""
var url = String(location.href || '');
var hasEmail = !!document.querySelector('input[type="email"], input[name="email"], input[placeholder*="Email" i], input[placeholder*="email" i]');
var hasPwd = !!document.querySelector('input[type="password"], input[name="password"]');
var token = '';
try { token = String(localStorage.getItem('accessToken') || localStorage.getItem('access_token') || ''); } catch(e) {}
var bodyText = '';
try { bodyText = String((document.body && document.body.innerText) || '').slice(0, 300); } catch(e) {}
return JSON.stringify({
  url: url,
  hasEmail: hasEmail,
  hasPwd: hasPwd,
  tokenLen: token.length,
  onSignup: /sign-up|signup/i.test(url),
  onLogin: /\/login/i.test(url),
  onDashboard: /\/v2\/?$|\/overview|\/services|\/account/i.test(url) && !/sign-up|login|verify|typeform/i.test(url),
  title: String(document.title || ''),
  bodyHint: bodyText.replace(/\s+/g, ' ').slice(0, 120)
});
"""
        )
        st = _ps_parse_js_result(raw)
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def open_ps_signup_page(log_callback=None, cancel_callback=None) -> None:
    """打开注册页；若残留登录态导致跳转，强制清会话并重开。"""
    page_obj = _ensure_page()
    url = _ps_signup_url()

    def _goto_signup(tag: str = ""):
        if log_callback:
            log_callback(f"[*] 打开注册页{('(' + tag + ')') if tag else ''}: {url}")
        page_obj.get(url)
        sleep_with_cancel(0.6, cancel_callback)

    # 每次进注册前先清登录态，避免复用浏览器时卡在 dashboard
    try:
        clear_ps_auth_session(log_callback=log_callback, cancel_callback=cancel_callback)
        page_obj = active_page() or page_obj
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] 预清理登录态异常: {exc}")

    _goto_signup("1")

    deadline = time.time() + 45
    last_st = {}
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        page_obj = active_page() or page_obj
        last_st = _ps_signup_form_ready(page_obj)
        if last_st.get("hasEmail") and last_st.get("hasPwd") and last_st.get("onSignup"):
            if log_callback:
                log_callback(f"[*] 注册表单已就绪: {last_st.get('url')}")
            sleep_with_cancel(0.4, cancel_callback)
            return

        if last_st.get("tokenLen", 0) > 20 or last_st.get("onDashboard") or (
            last_st and not last_st.get("onSignup") and not last_st.get("hasEmail")
        ):
            if log_callback:
                log_callback(f"[!] 未落到注册表单，当前={last_st}，清理登录态重开")
            clear_ps_auth_session(log_callback=log_callback, cancel_callback=cancel_callback)
            page_obj = active_page() or page_obj
            _goto_signup("retry")
            sleep_with_cancel(0.8, cancel_callback)
            continue
        sleep_with_cancel(0.5, cancel_callback)

    if log_callback:
        log_callback(f"[!] 注册页等待超时，完整重启浏览器后再开: {last_st}")
    restart_browser()
    page_obj = active_page()
    if page_obj is None:
        raise Exception("浏览器重启后页面未就绪")
    _goto_signup("after-restart")
    deadline2 = time.time() + 30
    while time.time() < deadline2:
        raise_if_cancelled(cancel_callback)
        last_st = _ps_signup_form_ready(page_obj)
        if last_st.get("hasEmail") and last_st.get("hasPwd"):
            return
        sleep_with_cancel(0.5, cancel_callback)

    raise Exception(f"无法打开注册表单页（可能仍登录态/被重定向）: {last_st}")


def _ps_set_input_value(page_obj, selectors, value, log_callback=None, label="field") -> bool:
    """写入 React/MUI 受控输入框（原生 setter + input/change 事件）。"""
    value = str(value or "")
    js = r"""
var selectors = [];
try { selectors = JSON.parse(arguments[0]); } catch(e) { selectors = [String(arguments[0] || '')]; }
var value = String(arguments[1] || '');
function pick(sel){ try { return document.querySelector(sel); } catch(e) { return null; } }
var el = null;
for (var i = 0; i < selectors.length; i++) {
  el = pick(selectors[i]);
  if (el) break;
}
if (!el) return JSON.stringify({ok:false, reason:'not_found'});
el.focus();
var desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
if (desc && desc.set) desc.set.call(el, value); else el.value = value;
try { if (el._valueTracker) el._valueTracker.setValue(''); } catch(e) {}
el.dispatchEvent(new Event('input', {bubbles:true}));
el.dispatchEvent(new Event('change', {bubbles:true}));
el.dispatchEvent(new Event('blur', {bubbles:true}));
return JSON.stringify({ok:true, value:String(el.value||''), name:el.name||'', id:el.id||''});
"""
    try:
        result = _ps_parse_js_result(
            _ps_run_js(page_obj, js, selectors, value, log_callback=log_callback)
        )
        if isinstance(result, dict) and result.get("ok"):
            if log_callback:
                shown = value if label == "email" else ("*" * min(8, len(value)))
                log_callback(f"[*] 已填写 {label}: {shown}")
            return True
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] JS 填写 {label} 失败: {exc}")
    return False


def fill_ps_signup_form(email: str, password: str, log_callback=None, cancel_callback=None) -> None:
    """在 /sign-up 页面填写邮箱、密码、确认密码，并勾选服务条款。"""
    page_obj = _ensure_page()
    raise_if_cancelled(cancel_callback)
    if log_callback:
        log_callback(f"[*] 填写注册表单: {email}")

    email_ok = _ps_set_input_value(
        page_obj,
        [
            'input[name="email"]',
            'input[type="email"]',
            'input[placeholder*="Email" i]',
            'input[placeholder*="email" i]',
            'input[id*="email" i]',
        ],
        email,
        log_callback=log_callback,
        label="email",
    )
    if not email_ok:
        raise Exception("未找到邮箱输入框，无法填写 email")

    sleep_with_cancel(0.25, cancel_callback)
    pwd_ok = _ps_set_input_value(
        page_obj,
        [
            'input[name="password"]',
            '#auth-login-v2-password',
            'input[type="password"]',
        ],
        password,
        log_callback=log_callback,
        label="password",
    )
    if not pwd_ok:
        raise Exception("未找到密码输入框，无法填写 password")

    sleep_with_cancel(0.25, cancel_callback)
    confirm_ok = _ps_set_input_value(
        page_obj,
        [
            'input[name="password_confirm"]',
            '#auth-login-v2-confirm-password',
            'input[placeholder*="Confirm" i]',
            'form input[type="password"]:nth-of-type(2)',
        ],
        password,
        log_callback=log_callback,
        label="password_confirm",
    )
    if not confirm_ok:
        # 有的布局第二个 password 就是确认框
        try:
            _ps_run_js(
                page_obj,
                r"""
var value = String(arguments[0] || '');
var pwds = Array.from(document.querySelectorAll('input[type="password"]'));
if (pwds.length < 2) return false;
var el = pwds[1];
el.focus();
var desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
if (desc && desc.set) desc.set.call(el, value); else el.value = value;
el.dispatchEvent(new Event('input', {bubbles:true}));
el.dispatchEvent(new Event('change', {bubbles:true}));
el.dispatchEvent(new Event('blur', {bubbles:true}));
return true;
""",
                password,
            )
            confirm_ok = True
            if log_callback:
                log_callback("[*] 已填写 password_confirm (第2个 password)")
        except Exception:
            confirm_ok = False
    if not confirm_ok and log_callback:
        log_callback("[!] 未找到确认密码框，继续尝试提交")

    sleep_with_cancel(0.2, cancel_callback)
    terms_ok = accept_ps_terms_checkbox(
        page_obj, log_callback=log_callback, cancel_callback=cancel_callback
    )
    if not terms_ok:
        raise Exception("未能勾选服务条款（terms and conditions），Continue 按钮会保持禁用")

    # 校验页面上的值
    try:
        raw_snapshot = _ps_run_js(
            page_obj,
            r"""
var email = (document.querySelector('input[name="email"], input[type="email"]') || {}).value || '';
var pwds = Array.from(document.querySelectorAll('input[type="password"]')).map(function(e){ return e.value || ''; });
var boxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
var checked = boxes.some(function(b){ return !!b.checked; });
var submit = document.querySelector('button[type="submit"]');
return JSON.stringify({
  email: email,
  passwordLen: (pwds[0]||'').length,
  confirmLen: (pwds[1]||'').length,
  pwdCount: pwds.length,
  termsChecked: checked,
  submitDisabled: submit ? !!submit.disabled : null,
  submitText: submit ? String(submit.textContent||'').trim() : ''
});
""",
        )
        snapshot = _ps_parse_js_result(raw_snapshot)
        if log_callback and isinstance(snapshot, dict):
            log_callback(
                f"[*] 表单快照: email={snapshot.get('email')!r} "
                f"pwdLen={snapshot.get('passwordLen')} confirmLen={snapshot.get('confirmLen')} "
                f"terms={snapshot.get('termsChecked')} submitDisabled={snapshot.get('submitDisabled')}"
            )
        if isinstance(snapshot, dict):
            page_email = str(snapshot.get("email") or "").strip().lower()
            if page_email and page_email != email.strip().lower():
                raise Exception(f"邮箱填写校验失败: page={page_email} expect={email}")
            if int(snapshot.get("passwordLen") or 0) < 8:
                raise Exception("密码填写校验失败: 页面 password 为空或过短")
            if not snapshot.get("termsChecked"):
                raise Exception("服务条款勾选校验失败: checkbox 仍未 checked")
    except Exception as exc:
        if "校验失败" in str(exc) or "未能勾选" in str(exc):
            raise
        if log_callback:
            log_callback(f"[Debug] 表单快照失败: {exc}")


def accept_ps_terms_checkbox(
    page_obj=None, log_callback=None, cancel_callback=None, retries: int = 6
) -> bool:
    """强制勾选 ProxyScrape 注册页 terms checkbox（MUI 受控）。"""
    page_obj = page_obj or active_page()
    if page_obj is None:
        return False

    def _status() -> dict:
        try:
            raw = _ps_run_js(
                page_obj,
                r"""
var boxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
var checked = boxes.filter(function(b){ return b.checked; }).length;
var total = boxes.length;
var aria = Array.from(document.querySelectorAll('[role="checkbox"], .MuiCheckbox-root'));
var ariaChecked = aria.some(function(n){
  return n.getAttribute('aria-checked') === 'true' || n.classList.contains('Mui-checked');
});
var submit = document.querySelector('button[type="submit"]');
var labels = boxes.map(function(b){
  var host = b.closest('label') || b.closest('.MuiFormControlLabel-root') || b.parentElement || {};
  var t = (host.textContent || '').trim();
  return t.replace(/\s+/g, ' ').slice(0, 80);
});
return JSON.stringify({
  total: total,
  checked: checked,
  ariaChecked: ariaChecked,
  submitDisabled: submit ? !!submit.disabled : null,
  labels: labels
});
""",
            )
            return _ps_parse_js_result(raw)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] terms status 失败: {exc}")
        return {}

    def _force_check_js() -> dict:
        """核心：定位 terms 相关 checkbox，强制 checked + 触发 React onChange。"""
        try:
            raw = _ps_run_js(
                page_obj,
                r"""
var out = {ok:false, method:'', detail:''};
function isTerms(t){
  return /I accept|terms and conditions|terms|condition|服务条款|接受/i.test(String(t||''));
}
function fireReactChange(el, checked){
  var desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked');
  if (desc && desc.set) desc.set.call(el, checked); else el.checked = checked;
  try { if (el._valueTracker) el._valueTracker.setValue(String(!checked)); } catch(e) {}
  el.dispatchEvent(new Event('click', {bubbles:true}));
  el.dispatchEvent(new Event('input', {bubbles:true}));
  el.dispatchEvent(new Event('change', {bubbles:true}));
  try { el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window})); } catch(e) {}
  var keys = Object.keys(el);
  var pKey = keys.find(function(k){ return k.indexOf('__reactProps$')===0 || k.indexOf('__reactEventHandlers$')===0; });
  if (pKey && el[pKey]) {
    var props = el[pKey];
    var evt = {target: el, currentTarget: el, type:'change', bubbles:true, preventDefault:function(){}, stopPropagation:function(){}};
    try { if (typeof props.onChange === 'function') props.onChange(evt); } catch(e) {}
    try { if (typeof props.onClick === 'function') props.onClick(evt); } catch(e) {}
  }
  var root = el.closest('.MuiButtonBase-root, .MuiCheckbox-root, span');
  if (root) {
    var rKey = Object.keys(root).find(function(k){ return k.indexOf('__reactProps$')===0 || k.indexOf('__reactEventHandlers$')===0; });
    if (rKey && root[rKey]) {
      var rp = root[rKey];
      var fake = {target:{checked:true}, currentTarget:{checked:true}, preventDefault:function(){}, stopPropagation:function(){}};
      try { if (typeof rp.onChange === 'function') rp.onChange(fake); } catch(e) {}
      try { if (typeof rp.onClick === 'function') rp.onClick(fake); } catch(e) {}
    }
    try { root.click(); } catch(e) {}
  }
  return !!el.checked;
}

var boxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
out.detail = 'boxCount=' + boxes.length;
var ranked = [];
for (var i=0;i<boxes.length;i++){
  var el = boxes[i];
  var wrap = el.closest('label') || el.closest('.MuiFormControlLabel-root') || el.parentElement;
  var txt = (wrap && wrap.textContent) || '';
  ranked.push({el:el, score: isTerms(txt)?10:1, txt: String(txt).slice(0,60)});
}
ranked.sort(function(a,b){ return b.score - a.score; });

for (var j=0;j<ranked.length;j++){
  var item = ranked[j];
  var host = item.el.closest('.MuiFormControlLabel-root, label') || item.el.parentElement;
  if (host) {
    var muiRoot = host.querySelector('.MuiCheckbox-root, .MuiButtonBase-root');
    if (muiRoot) { try { muiRoot.click(); } catch(e) {} }
  }
  if (fireReactChange(item.el, true)) {
    out.ok = true; out.method = 'force_checkbox'; out.detail = item.txt;
    return JSON.stringify(out);
  }
}

var roles = Array.from(document.querySelectorAll('[role="checkbox"], .MuiCheckbox-root'));
for (var r=0;r<roles.length;r++){
  var n = roles[r];
  if (n.closest('a')) continue;
  try { n.click(); } catch(e) {}
  if (n.getAttribute('aria-checked') === 'true' || n.classList.contains('Mui-checked')) {
    out.ok = true; out.method = 'role_checkbox'; return JSON.stringify(out);
  }
}

var labels = Array.from(document.querySelectorAll('.MuiFormControlLabel-root, label'));
for (var k=0;k<labels.length;k++){
  var lab = labels[k];
  if (!isTerms(lab.textContent || '')) continue;
  var boxRoot = lab.querySelector('.MuiCheckbox-root, .MuiButtonBase-root, input[type="checkbox"]');
  if (!boxRoot) continue;
  try { boxRoot.click(); } catch(e) {}
  var input = lab.querySelector('input[type="checkbox"]');
  if (input && fireReactChange(input, true)) {
    out.ok = true; out.method = 'label_root'; return JSON.stringify(out);
  }
  if (input && input.checked) {
    out.ok = true; out.method = 'label_input_checked'; return JSON.stringify(out);
  }
}
return JSON.stringify(out);
""",
            )
            return _ps_parse_js_result(raw)
        except Exception as exc:
            if log_callback:
                log_callback(f"[Debug] terms force js 失败: {exc}")
        return {"ok": False}

    for attempt in range(1, max(1, retries) + 1):
        raise_if_cancelled(cancel_callback)
        st = _status()
        if st.get("checked") or st.get("ariaChecked"):
            if log_callback:
                log_callback(f"[*] 服务条款已勾选 (attempt={attempt})")
            return True

        if log_callback:
            log_callback(f"[*] 尝试勾选服务条款 #{attempt}: {st}")

        forced = _force_check_js()
        if log_callback:
            log_callback(f"[*] terms force 结果: {forced}")
        sleep_with_cancel(0.3, cancel_callback)
        st2 = _status()
        if st2.get("checked") or st2.get("ariaChecked"):
            if log_callback:
                log_callback(f"[*] 服务条款勾选成功 (attempt={attempt})")
            return True

        sleep_with_cancel(0.35, cancel_callback)
        st3 = _status()
        if st3.get("checked") or st3.get("ariaChecked"):
            if log_callback:
                log_callback(f"[*] 服务条款勾选成功 (attempt={attempt})")
            return True

    st_final = _status()
    if log_callback:
        log_callback(f"[!] 服务条款仍未勾选: {st_final}")
    return bool(st_final.get("checked") or st_final.get("ariaChecked"))


def read_ps_access_token_from_page(page_obj=None) -> str:
    page_obj = page_obj or active_page()
    if page_obj is None:
        return ""
    try:
        token = _ps_run_js(
            page_obj,
            r"""
try {
  return localStorage.getItem('accessToken')
    || localStorage.getItem('access_token')
    || sessionStorage.getItem('accessToken')
    || '';
} catch(e) { return ''; }
""",
        )
        return str(token or "").strip()
    except Exception:
        return ""


def wait_ps_turnstile_done(timeout: float = 60, log_callback=None, cancel_callback=None) -> str:
    """等待 Turnstile 通过并返回 token；超时抛异常。

    getTurnstileToken 内部已完成轮询并校验 token 长度（≥80），
    这里只做外层 deadline 保护与取消检查。
    """
    deadline = time.time() + max(5.0, float(timeout))
    token = ""
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        token = signup_flow.getTurnstileToken(
            log_callback=log_callback, cancel_callback=cancel_callback
        )
        if token:
            return str(token)
        sleep_with_cancel(2.0, cancel_callback)
    raise Exception("Turnstile 等待超时，未获取到有效 token")


def _ps_form_ready_state(page_obj) -> dict:
    """读取条款/Turnstile/Continue 按钮状态。"""
    try:
        raw = _ps_run_js(
            page_obj,
            r"""
var submit = document.querySelector('button[type="submit"]');
var boxes = Array.from(document.querySelectorAll('input[type="checkbox"]'));
var ts = String((document.querySelector('input[name="cf-turnstile-response"]') || {}).value || '');
var byApi = '';
try {
  if (window.turnstile && typeof turnstile.getResponse === 'function') {
    byApi = String(turnstile.getResponse() || '');
  }
} catch(e) {}
return JSON.stringify({
  disabled: submit ? !!submit.disabled : true,
  terms: boxes.some(function(b){ return b.checked; }),
  tsLen: ts.length,
  apiLen: byApi.length,
  hasSubmit: !!submit
});
""",
        )
        st = _ps_parse_js_result(raw)
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _ps_click_continue_button(page_obj, log_callback=None, force_unlock: bool = False) -> str:
    """点击 Continue/Sign Up（默认不强制解锁 disabled）。"""
    try:
        ok = _ps_run_js(
            page_obj,
            r"""
var forceUnlock = !!arguments[0];
var terms = Array.from(document.querySelectorAll('input[type="checkbox"]')).some(function(x){ return x.checked; });
if (!terms) return 'no_terms';
var ts = String((document.querySelector('input[name="cf-turnstile-response"]') || {}).value || '');
var byApi = '';
try {
  if (window.turnstile && typeof turnstile.getResponse === 'function') {
    byApi = String(turnstile.getResponse() || '');
  }
} catch(e) {}
if (ts.length < 80 && byApi.length < 80) return 'no_turnstile';

var btns = Array.from(document.querySelectorAll('button'));
var b = null;
for (var i=0;i<btns.length;i++){
  var t = String(btns[i].textContent || '').replace(/\s+/g,' ').trim();
  if (/^Continue$/i.test(t) || /Sign Up/i.test(t) || /注册|继续/.test(t)) { b = btns[i]; break; }
}
if (!b) b = document.querySelector('button[type="submit"]');
if (!b) return 'none';
if (b.disabled && !forceUnlock) return 'disabled';
if (forceUnlock) {
  b.disabled = false;
  b.removeAttribute('disabled');
  b.classList.remove('Mui-disabled');
  try { b.removeAttribute('aria-disabled'); } catch(e) {}
  try { b.style.pointerEvents = 'auto'; } catch(e) {}
}
b.click();
return 'clicked';
""",
            bool(force_unlock),
        )
        ok = str(ok or "").strip()
        if log_callback:
            log_callback(f"[*] 点击 Continue 结果: {ok}")
        return ok
    except Exception as exc:
        if log_callback:
            log_callback(f"[Debug] 点击 Continue 失败: {exc}")
        return "error"


def submit_ps_signup_and_wait_token(
    timeout: float = 60, log_callback=None, cancel_callback=None
) -> str:
    """等 Turnstile 完成后点击一次 Continue，等待 accessToken。"""
    page_obj = _ensure_page()

    if not accept_ps_terms_checkbox(
        page_obj, log_callback=log_callback, cancel_callback=cancel_callback, retries=3
    ):
        raise Exception("提交前条款仍未勾选，Continue 保持禁用")

    wait_ps_turnstile_done(timeout=timeout, log_callback=log_callback, cancel_callback=cancel_callback)

    wait_deadline = time.time() + 45
    last_st = {}
    ready = False
    while time.time() < wait_deadline:
        raise_if_cancelled(cancel_callback)
        st = _ps_form_ready_state(page_obj)
        if st:
            last_st = st
            if log_callback:
                log_callback(f"[*] 提交前状态: {st}")
            if st.get("terms") is False:
                accept_ps_terms_checkbox(
                    page_obj, log_callback=log_callback, cancel_callback=cancel_callback, retries=2
                )
                continue
            ts_ok = int(st.get("tsLen") or 0) >= 80 or int(st.get("apiLen") or 0) >= 80
            if st.get("terms") and ts_ok and not st.get("disabled"):
                ready = True
                break
            if st.get("terms") and ts_ok:
                sleep_with_cancel(0.8, cancel_callback)
                st2 = _ps_form_ready_state(page_obj)
                if st2:
                    last_st = st2
                if st2 and st2.get("terms") and not st2.get("disabled"):
                    ready = True
                    break
                ready = True
                break
        sleep_with_cancel(0.6, cancel_callback)

    if not ready:
        raise Exception(f"Turnstile/条款未就绪，拒绝点击 Continue: {last_st}")

    if log_callback:
        log_callback(f"[*] CF 已通过，准备点击 Continue 一次: {last_st}")

    force = bool(last_st.get("disabled"))
    click_result = _ps_click_continue_button(page_obj, log_callback=log_callback, force_unlock=force)
    if click_result == "no_terms":
        accept_ps_terms_checkbox(
            page_obj, log_callback=log_callback, cancel_callback=cancel_callback, retries=2
        )
        click_result = _ps_click_continue_button(page_obj, log_callback=log_callback, force_unlock=True)
    if click_result == "no_turnstile":
        raise Exception(f"Turnstile 未完成，跳过点击: {last_st}")
    if click_result not in ("clicked", "form"):
        click_result = _ps_click_continue_button(page_obj, log_callback=log_callback, force_unlock=True)
    if click_result not in ("clicked", "form"):
        raise Exception(f"无法点击注册提交按钮: {click_result}, state={last_st}")
    if log_callback:
        log_callback(f"[*] Continue 已触发（仅一次）: {click_result}")

    deadline = time.time() + max(5.0, float(timeout))
    last_url = ""
    while time.time() < deadline:
        raise_if_cancelled(cancel_callback)
        token = read_ps_access_token_from_page(page_obj)
        if token and len(token) > 20:
            if log_callback:
                log_callback(f"[+] 页面已写入 accessToken (len={len(token)})")
            return token
        try:
            last_url = str(page_obj.url or "")
        except Exception:
            last_url = ""
        sleep_with_cancel(0.6, cancel_callback)

    token = read_ps_access_token_from_page(page_obj)
    if token:
        return token
    raise Exception(f"提交注册后未拿到 accessToken，当前URL={last_url}")
