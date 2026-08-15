# ProxyScrape 注册链路改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 grok-register（xAI Grok 批量注册 Web 工具）就地改写为 ProxyScrape 注册链路，保留 Web 控制台 / 任务协调 / 邮箱渠道 / Camoufox 浏览器基础设施，移除 grok 特有逻辑（CPA/Grok2API/GrokIQ/SSO/relogin）。

**Architecture:** 保留现有分层（web → registration.engine → automation/mailbox/integrations）。删除 grok 特有模块，新增 `ps_api.py`（PS REST 封装，configure 注入 http）、`ps_signup_flow.py`（Playwright 页面步骤，复用 signup_flow 通用工具）、`ps_resin.py`（可选入池）。engine 的 worker 循环与 persist 改写为 PS 链路，失败分类与配置键全面替换，前端移除 3 个页面并改造 4 个页面。

**Tech Stack:** Python 3.10+ / FastAPI / Camoufox(Playwright API) / curl_cffi / SQLite(WAL) / React 18 + TS + Vite + Tailwind。

## Global Constraints

- 浏览器栈：**保留 Camoufox**（Firefox 系），Turnstile 用现有 Playwright frame 点击 + 轮询模式（`signup_flow.getTurnstileToken`），**不引入** DrissionPage / Chrome / turnstilePatch。
- 依赖注入沿用仓库约定：模块级 `_deps` dict + `configure(**kwargs)`；`http_get`/`http_post` 作函数参数或经 configure 注入；禁止新模块直接 import engine（循环依赖）。
- HTTP 统一 curl_cffi：engine 的 `direct_http_session()`（trust_env=False）；PS 请求默认带 `Content-Type: application/x-www-form-urlencoded` 与 `Origin: https://dashboard.proxyscrape.com`，Bearer 认证。
- 成功标准：`access_token` + `AccountID` + 代理列表下载成功（替代原 `cpa_detail["status"]=="success"`）。
- 失败分类 `FAIL_*`：保留 `domain_rejected`/`already_registered`/`code_timeout`/`browser`/`other`；移除 `registration_risk`/`sso_timeout`/`stuck_retry`/`cpa`；新增 `FAIL_PS_FORM`/`FAIL_PS_REGISTER`/`FAIL_PS_VERIFY`/`FAIL_PS_PROXY`。
- 移植来源：`D:/Project/proxyscrape_reg/register_core.py`（下文以 `PS_CORE` 简称，行号引用该文件）。
- 测试：stdlib unittest，patch 使用处模块；`gr.config` 快照恢复约定；测试必须在仓库根 `D:/Project/grok-register` 运行。
- 前端：后端所有接口返回 `{ok: boolean, ...}`；`cn()` 复用；移除页面不留残留 import/路由。
- 每个任务独立可测；每任务结束跑相关测试 + commit。

---

### Task 1: 基线验证

**Files:**
- Run only（无代码改动）

**Interfaces:** 无

- [ ] **Step 1: 运行现有全量测试确认基线**

Run（仓库根）：`python -m unittest discover -s backend/tests -v 2>&1 | tail -20`
Expected: 全部通过（或记录既有失败清单作为基线，不修）
- [ ] **Step 2: 确认前端可构建**

Run: `cd front && npm run build`
Expected: 构建成功（dist 存在）
- [ ] **Step 3: 记录基线**

在 `docs/superpowers/plans/` 下建 `baseline-notes.md`，记录：测试总数/失败数、前端构建状态。后续任务以"不劣于基线"为回归线。
- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/baseline-notes.md
git commit -m "chore: record rewrite baseline"
```

---

### Task 2: store.py 移除 grok 专属方法与字段

**Files:**
- Modify: `backend/registration/store.py`
- Modify: `backend/tests/test_registration_repository.py`

**Interfaces:**
- Consumes: 无
- Produces: `RegistrationRepository` 保留 `add_result`（record dict 键不变）、`list_results`/`get_results_by_ids`/`stats`/`delete_results`/`has_success`/`has_registered_or_consumed`/`import_existing_accounts`/`get_job_snapshot`/`save_job_snapshot`/`latest_web_batch_id`；删除 `enqueue_grokiq_event`/`recover_grokiq_deliveries`/`claim_grokiq_delivery`/`retry_grokiq_delivery`/`complete_grokiq_delivery`/`grokiq_deliveries`/`update_relogin_result`/`update_sso_check_result`/`update_bot_risk_by_email`/`backfill_registration_risk_bot_risk`/`update_remote_import_status`

- [ ] **Step 1: 删除 grokiq outbox 方法与 relogin/sso/bot_risk 方法**

从 `store.py` 删除：`enqueue_grokiq_event`(327)、`recover_grokiq_deliveries`(375)、`claim_grokiq_delivery`(389)、`retry_grokiq_delivery`(423)、`complete_grokiq_delivery`(452)、`grokiq_deliveries`(472)、`update_relogin_result`(743)、`update_sso_check_result`(894)、`update_bot_risk_by_email`(955)、`backfill_registration_risk_bot_risk`(978)、`update_remote_import_status`(997)。保留 `_initialize` 中 grokiq_outbox 表 DDL（旧库兼容，不删表）。
- [ ] **Step 2: 更新测试**

在 `test_registration_repository.py` 删除引用已删方法的测试用例（grok2api_remote_*/relogin/sso_check/bot_risk/grokiq outbox 相关）。保留：add_result/list/stats/delete/has_success/迁移/import_existing_accounts/job_snapshot 测试。
- [ ] **Step 3: 运行测试**

Run: `python -m unittest discover -s backend/tests -v 2>&1 | tail -30`
Expected: test_registration_repository 通过；其他文件若引用已删方法，记入 Task 5 修复清单（本任务不修 engine/web 引用，允许该阶段测试红，见 Step 4 提交说明）。
- [ ] **Step 4: Commit**

```bash
git add backend/registration/store.py backend/tests/test_registration_repository.py
git commit -m "refactor: drop grok-specific repository methods"
```

---

### Task 3: engine.py 移除 grok 特有逻辑

**Files:**
- Modify: `backend/registration/engine.py`
- Modify: `backend/tests/test_signup_flow.py`（仅删 grok 用例）

**Interfaces:**
- Consumes: 无
- Produces: engine 不再引用 `_s2cpa`/`_grok2api`/`_sub2api`/`_grokiq`；`DEFAULT_CONFIG` 移除 grok 键；异常族移除 `RegistrationRiskDenied`；`classify_failure` 调整；`persist_registration_result` 移除 `cpa_detail`/`nsfw_status`/`sso_saved` 参数（Task 9 会再加 PS 参数，本任务先删除）

- [ ] **Step 1: 删除 grok 异常与风控族**

删除：`RegistrationRiskDenied` 类、`apply_risk_bot_flag`、`backfill_access_token_bot_risk`、`backfill_registration_risk_bot_risk` 函数；`_append_sso_pending`/`_append_sso_risk_rejected`/`_inspect_sso_detailed_risk`/`ensure_sso_oauth_eligible`/`add_sso_to_cpa` 函数；NSFW 相关（`encode_grpc_nsfw_settings`/`update_nsfw_settings`/`enable_nsfw_via_browser`/`enable_nsfw_for_token`）；grok 页面 API（`set_birth_date`/`set_tos_accepted`）。
- [ ] **Step 2: 调整失败分类**

`FAIL_*` 常量：删 `FAIL_RISK`/`FAIL_STUCK`/`FAIL_SSO`/`FAIL_CPA`；新增 `FAIL_PS_FORM`/`FAIL_PS_REGISTER`/`FAIL_PS_VERIFY`/`FAIL_PS_PROXY`；`FAIL_LABELS` 同步（ps_form="表单/Turnstile"、ps_register="注册API"、ps_verify="验证邮箱"、ps_proxy="代理列表"）；`classify_failure` 删除 sso/risk/cpa 分支。
- [ ] **Step 3: DEFAULT_CONFIG 移除 grok 键**

删除键：`enable_nsfw`、`cpa_auto_add`、`sso_detailed_risk_check`、`cpa_token_mode`、`cpa_auth_dir`、`cpa_remote_url`、`cpa_management_key`、`grok2api_auth_dir`、`grok2api_remote_url`、`grok2api_remote_username`、`grok2api_remote_password`、`grok2api_auto_import`、`cpa_upload_enabled`、`sub2api_enabled`、`sub2api_remote_url`、`sub2api_api_key`、`sub2api_group_ids`、`sub2api_proxy_id`、`sub2api_concurrency`、`sub2api_priority`、`sub2api_name_prefix`、`grokiq_webhook_enabled`、`grokiq_webhook_url`、`grokiq_webhook_token`、`grokiq_webhook_timeout_seconds`。
- [ ] **Step 4: 删除 grok 邮箱停用/SSO 相关转发**

删除 `is_outlookemail_registration` 之外不再需要的转发不删；删除 `cpa_conversion_succeeded`/`registration_counts_as_success`/`cpa_failure_reason`/`default_email_disable_detail` 中对 cpa 的依赖（保留函数骨架，Task 9 改为 PS 判定）。删除 `maybe_disable_outlookemail_for_consumed_failure`/`disable_outlookemail_consumed`/`disable_outlookemail_after_cpa_success`（保留 `outlookemail_*` provider 转发本身）。
- [ ] **Step 5: 清理 import 与 _wire_runtime_modules**

删除模块顶部 `_s2cpa`/`_grok2api`/`_sub2api`/`_grokiq` import（或延迟 import 处）；`_wire_runtime_modules` 删除 `_grokiq`/NSFW 相关注入（signup_flow.configure 保留 get_email_and_token 等）。
- [ ] **Step 6: 修 test_signup_flow 中 grok 用例**

删除引用已删函数（`wait_for_sso_cookie`/`fill_profile_and_submit`/`getTurnstileToken` 保留；删除 `authorize_device_in_browser` 等 SSO/device 相关用例）。本任务不新增测试。
- [ ] **Step 7: 运行测试**

Run: `python -m unittest discover -s backend/tests -v 2>&1 | tail -40`
Expected: 不再出现 `ImportError`/`NameError`（引用已删符号的测试用例已删；application.py/jobs.py 的引用留到 Task 5，允许剩余失败）。
- [ ] **Step 8: Commit**

```bash
git add backend/registration/engine.py backend/tests/test_signup_flow.py
git commit -m "refactor: strip grok logic from engine"
```

---

### Task 4: signup_flow.py 精简为通用工具

**Files:**
- Modify: `backend/registration/signup_flow.py`

**Interfaces:**
- Consumes: 无
- Produces: 保留 `configure`/`last_acquired_email`/`last_profile`/`_AccountRetryNeeded`/`raise_if_cancelled`/`sleep_with_cancel`/`_native_*`（attr/is_usable/label/elements/click_action/type_element/input_candidates/fill_email/fill_code/fill_profile）/`_dismiss_cookie_consent`/`getTurnstileToken`/`_try_click_turnstile_frame`/`_fill_cf_turnstile_token`/`_try_sync_turnstile`/`detect_email_domain_rejection`/`raise_if_email_domain_rejected`/`build_profile`；删除 grok 页面步骤：`click_email_signup_button`/`open_signup_page`/`has_profile_form`/`_profile_page_snapshot`/`_wait_profile_page_after_code`/`fill_email_and_submit`/`fill_code_and_submit`/`fill_profile_and_submit`/`detect_account_already_registered`/`wait_for_sso_cookie`/`authorize_device_in_browser`/`_click_device_button_native`/`_email_page_advanced_once`/`_wait_email_page_advanced`/`_has_code_verification_input`/`_should_retry_cf`

- [ ] **Step 1: 删除 grok 页面步骤**

按上述清单删除函数与仅它们使用的常量（`SIGNUP_URL`/`CF_FIRST_RETRY_AFTER` 等保留 getTurnstileToken 需要的）。`AccountAlreadyRegistered`/`_ALREADY_REGISTERED_PATTERNS` 保留（PS 注册复用"已存在"检测）。
- [ ] **Step 2: 运行测试**

Run: `python -m unittest backend.tests.test_signup_flow -v 2>&1 | tail -20`
Expected: 保留用例通过（已删用例在 Task 3 处理）。
- [ ] **Step 3: Commit**

```bash
git add backend/registration/signup_flow.py
git commit -m "refactor: trim signup_flow to shared playwright utilities"
```

---

### Task 5: web 层移除 grok 端点与协调器

**Files:**
- Modify: `backend/web/application.py`
- Modify: `backend/web/jobs.py`
- Modify: `backend/tests/test_console_authentication.py`（若引用 grok helper）

**Interfaces:**
- Consumes: Task 2/3 已删方法
- Produces: `create_app()` 不再注册 `/api/accounts/relogin*`、`/api/accounts/sso-check*`、`/api/accounts/{id}/grok2api/import`、`/api/accounts/{id}/auth-json*`、`/api/accounts/auth-json/{kind}/download`、`/api/accounts/actionable-ids`（action=relogin|sso_check 分支删除）；startup 钩子不再调用 `backfill_*`、不再 start/stop `grokiq_notifier`；删除 `_find_account_auth_file`/`_find_account_grok2api_files`/`_load_account_auth_json`/`_find_account_sso_file`/`_account_has_sso`/`_load_account_sso`/`_record_auth_path`/`_relogin_screenshot_file` helper

- [ ] **Step 1: 删除 helper 与端点**

删除上述 helper 函数与相关端点 handler（含 `api_account_relogin_status`/`api_account_actionable_ids`/`api_accounts_sso_check_prepare`/`api_accounts_sso_check`/`api_accounts_relogin`/`api_account_auth_json_download`/`api_account_relogin`/`api_account_grok2api_import`/`api_account_relogin_screenshot`/`api_account_auth_json`/`api_account_auth_json_download`/`api_accounts_auth_json_download`）。保留 `_stream_file`（Task 9 复用）。
- [ ] **Step 2: 移除协调器 import 与启动逻辑**

删除 `from backend.web import relogin_jobs`/`sso_check_jobs` import；`relogin_coordinator`/`sso_check_coordinator` 引用；startup/shutdown 中 `grokiq_notifier.start()/stop()` 与 `backfill_*` 调用。
- [ ] **Step 3: jobs.py 清理**

删除 jobs.py 中引用 `gr.registration_log` 装饰时对 grok 阶段的兼容（保留机制，进度正则 Task 11 更新）。
- [ ] **Step 4: 删除已删模块文件**

```bash
git rm backend/web/relogin_jobs.py backend/web/sso_check_jobs.py backend/web/account_exports.py backend/integrations/auth_exchange.py backend/integrations/grok2api_client.py backend/integrations/sub2api_client.py backend/integrations/grokiq.py backend/integrations/sso_checker.py backend/registration/login_flow.py backend/tests/test_sso_checker.py backend/tests/test_sub2api_client.py backend/tests/test_grok2api_client.py backend/tests/test_grokiq.py backend/tests/test_relogin_jobs.py backend/tests/test_sso_check_jobs.py backend/tests/test_registration_risk.py backend/tests/test_registration_risk_bot_flag.py backend/tests/test_access_token_bot_risk.py backend/tests/test_auth_artifact_loading.py backend/tests/test_login_flow.py
```
- [ ] **Step 5: 全量测试**

Run: `python -m unittest discover -s backend/tests -v 2>&1 | tail -30`
Expected: 现有保留测试全绿（这是删除阶段完成线）。若有残留引用（如 engine 还引用 `_grokiq`），回到 Task 3 补齐。
- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: remove grok web endpoints, coordinators and integration modules"
```

---

### Task 6: ps_api.py — PS REST 封装

**Files:**
- Create: `backend/integrations/ps_api.py`
- Create: `backend/tests/test_ps_api.py`

**Interfaces:**
- Consumes: `configure(**kwargs)` 注入 `http_post`/`http_get`（engine 提供）
- Produces（签名固定，后续任务依赖）:
```python
PS_TURNSTILE_SITEKEY = "0x4AAAAAAAFWUVCKyusT9T8r"
def configure(**kwargs) -> None
def ps_dashboard_base() -> str
def ps_api_base() -> str
def generate_password(length=None) -> str          # ≥8 大写数字特殊，clamp [10,32]
def ps_register_api(email, password, turnstile_token, log_callback=None) -> dict
def ps_verify_email_api(access_token, verification_code, log_callback=None) -> dict
def ps_resend_verification_code(access_token, log_callback=None) -> dict
def ps_complete_typeform(access_token, log_callback=None) -> dict   # ps_skip_typeform→{"success":True,"skipped":True}
def ps_fetch_me(access_token) -> dict
def ps_pick_subaccount(me_body, preferred_type="datacenter_shared") -> dict
def ps_fetch_proxy_credentials(access_token, account_id, *, protocol="http", proxy_type="datacenter_shared", log_callback=None) -> dict
def ps_download_proxy_list(access_token, account_id, *, protocol="http", proxy_type="datacenter_shared", fmt="userpass", log_callback=None) -> list[str]
def ps_failure_reason(result) -> str               # 从 dict 提取 error 文案
```

- [ ] **Step 1: 写失败测试**

`test_ps_api.py`：`setUp` 用 `configure(http_post=fake, http_get=fake)`，`tearDown` 重置 `configure(http_post=None, http_get=None)`；断言：
- `ps_register_api` 调 `http_post` 且 URL 含 `/v4/account/auth/register`、data 含 `email`/`password`/`cf_turnstile_token`、headers 含 `application/x-www-form-urlencoded`
- `ps_verify_email_api` 带 Bearer 头
- `ps_fetch_me` 返回解析 body
- `generate_password` 满足长度/字符类（`assertRegex` 大写/数字/特殊）
- `ps_complete_typeform` 在 config `ps_skip_typeform=True` 时短路（不调 http_post）
- `ps_download_proxy_list` 解析代理行返回 list
- 错误响应（`{"success": false, "error": "..."}`）→ `ps_failure_reason` 提取

- [ ] **Step 2: 运行验证失败**

Run: `python -m unittest backend.tests.test_ps_api -v 2>&1 | tail -10`
Expected: FAIL（ModuleNotFoundError）
- [ ] **Step 3: 实现 ps_api.py**

移植自 `PS_CORE:2662-3754`（`_ps_dashboard_base`/`_ps_api_base`/`_ps_auth_headers`/`generate_password`/`ps_register_api`/`ps_verify_email_api`/`ps_resend_verification_code`/`ps_complete_typeform`/`ps_fetch_me`/`ps_pick_subaccount`/`ps_fetch_proxy_credentials`/`ps_download_proxy_list`/`_ps_endpoint`）。改动：HTTP 调用改走 `_deps["http_post"]`/`_deps["http_get"]`；`config` 经 `configure(**kwargs)` 注入的 `get_config` 回调或直接延迟 `from backend.registration import engine as gr; gr.config`（与 web/jobs 同款 `_gr()` 延迟 import，避免循环）；`ps_skip_typeform`/`ps_password_length`/`ps_proxy_list_dir` 等配置键读取。
- [ ] **Step 4: 运行测试验证通过**

Run: `python -m unittest backend.tests.test_ps_api -v 2>&1 | tail -10`
Expected: PASS
- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ps_api.py backend/tests/test_ps_api.py
git commit -m "feat: add proxyscrape REST API client"
```

---

### Task 7: ps_signup_flow.py — 浏览器页面步骤

**Files:**
- Create: `backend/registration/ps_signup_flow.py`
- Create: `backend/tests/test_ps_signup_flow.py`

**Interfaces:**
- Consumes: `signup_flow` 的 `page`（automation.session 代理）、`_native_*` 工具、`getTurnstileToken`、`raise_if_cancelled`/`sleep_with_cancel`、`_deps`
- Produces:
```python
def open_ps_signup_page(log_callback=None, cancel_callback=None) -> None
def fill_ps_signup_form(email, password, log_callback=None, cancel_callback=None) -> None
def wait_ps_turnstile_done(timeout=60, log_callback=None, cancel_callback=None) -> None
def submit_ps_signup_and_wait_token(timeout=60, log_callback=None, cancel_callback=None) -> str   # 返回 access_token
def read_ps_access_token_from_page(page=None) -> str
```

- [ ] **Step 1: 写失败测试**

`test_ps_signup_flow.py`：复用 `test_signup_flow.py` 的 fake page/locator 模式（`_Page`/`NativeInput`/`_raw` 包装）。断言：
- `open_ps_signup_page`：先 goto dashboard 同源页再清 localStorage，再 goto `/v2/sign-up`（验证 `page.get` 调用序列）；残留登录态检测（`_ps_signup_form_ready` 判定）
- `fill_ps_signup_form`：MUI 受控输入写入（`_ps_set_input_value` 用 `arguments[0]` 原生 setter），password/confirm 两个输入框 + terms checkbox 被点击（`accept_ps_terms_checkbox` 逻辑）
- `submit_ps_signup_and_wait_token`：等 Turnstile 完成后点 Continue（disabled 解锁逻辑），轮询 `read_ps_access_token_from_page`（localStorage `ps_access_token` 键或页面 JS 读取）返回 token；超时抛异常
- patch 点：`ps_signup_flow.page`（模块级名）、`signup_flow.getTurnstileToken`、`_native_click_action`、`_deps`

- [ ] **Step 2: 运行验证失败**

Run: `python -m unittest backend.tests.test_ps_signup_flow -v 2>&1 | tail -10`
Expected: FAIL
- [ ] **Step 3: 实现 ps_signup_flow.py**

移植自 `PS_CORE:2706-3453`（`_ps_signup_form_ready`/`open_ps_signup_page`/`_ps_run_js`/`_ps_parse_js_result`/`_ps_set_input_value`/`fill_ps_signup_form`/`accept_ps_terms_checkbox`/`read_ps_access_token_from_page`/`_ps_form_ready_state`/`_ps_click_continue_button`/`submit_ps_signup_and_wait_token`）。改动：DrissionPage `page.run_js` → 本仓库 `page.run_js`（page_adapter 已包装）或 `_raw` locator；`page.get(...)` → `refresh_active_page()` + `page.get`；`_native_type_element` 复用；Turnstile 等待调用 `signup_flow.getTurnstileToken`（PS 页面只需等 token 写入 + 点 Continue，不调 reset）。access_token 读取：PS 注册成功会在页面 localStorage 写入 access token（`PS_CORE:3250 read_ps_access_token_from_page` 的读取逻辑），浏览器端 HTTP 响应拦截不可用则读 localStorage。
- [ ] **Step 4: 运行测试验证通过**

Run: `python -m unittest backend.tests.test_ps_signup_flow -v 2>&1 | tail -10`
Expected: PASS
- [ ] **Step 5: Commit**

```bash
git add backend/registration/ps_signup_flow.py backend/tests/test_ps_signup_flow.py
git commit -m "feat: add proxyscrape signup browser flow"
```

---

### Task 8: ps_resin.py — 可选 Resin 入池

**Files:**
- Create: `backend/integrations/ps_resin.py`
- Create: `backend/tests/test_ps_resin.py`

**Interfaces:**
- Consumes: `configure(**kwargs)` 注入 `http_post`/`http_get`/`http_delete`
- Produces:
```python
def configure(**kwargs) -> None
def resin_push_subscription(email, proxies, *, log_callback=None) -> dict
def resin_list_subscriptions(*, limit=100, keyword="") -> list[dict]
def resin_delete_subscription(subscription_id, *, log_callback=None) -> dict
def resin_find_subscription_by_name(name, subscriptions=None) -> dict | None
def resin_enabled() -> bool   # resin_base_url 与 resin_auth_token 均非空
```

- [ ] **Step 1: 写失败测试**

`test_ps_resin.py`：`configure` 注入 fake http 函数；断言：
- `resin_enabled`：空 base/token → False
- `resin_push_subscription`：POST `{base}/api/v1/subscriptions`，`Authorization: Bearer {token}`，body 含 `name`（邮箱前缀）与 `content`（`http://user:pass@ip:port` 多行）
- `resin_list_subscriptions` 解析分页/列表
- `resin_delete_subscription`：DELETE `{base}/api/v1/subscriptions/{id}`
- `resin_find_subscription_by_name` 大小写不敏感匹配
- 未配置时 `resin_push_subscription` 抛异常

- [ ] **Step 2: 运行验证失败**

Run: `python -m unittest backend.tests.test_ps_resin -v 2>&1 | tail -10`
Expected: FAIL
- [ ] **Step 3: 实现 ps_resin.py**

移植自 `PS_CORE:3756-4005`（`_resin_subscription_name`/`_proxies_to_resin_content`/`_resin_base_and_path`/`_resin_auth_headers`/`_resin_request`/`resin_list_subscriptions`/`resin_delete_subscription`/`resin_find_subscription_by_name`/`resin_push_subscription`）。改动：`_resin_request` 改走注入的 http 函数；配置键 `resin_base_url`/`resin_auth_token`/`resin_subscriptions_path`/`resin_timeout`/`resin_verify_tls`。
- [ ] **Step 4: 运行测试验证通过**

Run: `python -m unittest backend.tests.test_ps_resin -v 2>&1 | tail -10`
Expected: PASS
- [ ] **Step 5: Commit**

```bash
git add backend/integrations/ps_resin.py backend/tests/test_ps_resin.py
git commit -m "feat: add resin subscription push client"
```

---

### Task 9: engine 改写 — PS 注册编排

**Files:**
- Modify: `backend/registration/engine.py`
- Modify: `backend/tests/test_job_tracking.py`（进度标记）
- Modify: `backend/tests/test_proxy_routing.py`（若引用 cpa_detail）

**Interfaces:**
- Consumes: Task 6 `ps_api.*`、Task 7 `ps_signup_flow.*`、Task 8 `ps_resin.*`、signup_flow 通用工具
- Produces:
```python
def ps_detail_succeeded(ps_detail=None) -> bool        # access_token+account_id 非空且 error 空
def ps_failure_reason_detail(ps_detail=None) -> str
def persist_registration_result(*, batch_id, source, started_at, email="", password="", status="failure", provider="", worker_id=0, ps_detail=None, email_disable_detail=None, failure_type="", failure_reason="", screenshot_path="", account_file="", extra=None, log_callback=None) -> int | None
def run_registration(count)                            # worker 循环改为 PS 链路
```

- [ ] **Step 1: 重写 persist_registration_result**

签名替换 `cpa_detail`→`ps_detail`、删 `sso_saved`/`nsfw_status`；从 `ps_detail` 提取 `access_token`/`account_id`/`expire_at`/`proxy_file`/`resin_status` 写入 add_result record；删 GrokIQ outbox 触发块；`email_disable_detail` 逻辑保留（outlookemail 停用）。
- [ ] **Step 2: 新增 PS 判定函数**

`ps_detail_succeeded`/`ps_failure_reason_detail`；保留 `email_registered_successfully` 判定（已注册邮箱不再取用）。
- [ ] **Step 3: 重写 run_registration worker 循环**

单账号流程（替换原 open_signup_page→fill_email_and_submit→...→add_sso_to_cpa 链）：
```python
# 伪代码骨架（实现时替换原 worker 内 try 块）
open_ps_signup_page(log_callback=..., cancel_callback=...)
email, dev_token, submitted_at = get_email_and_token()          # 邮箱渠道
password = ps_api.generate_password()
fill_ps_signup_form(email, password, log_callback=..., cancel_callback=...)
wait_ps_turnstile_done(log_callback=..., cancel_callback=...)
access_token = submit_ps_signup_and_wait_token(log_callback=..., cancel_callback=...)
code = get_oai_code(dev_token, email, log_callback=..., cancel_callback=...)   # 渠道取验证码
verify = ps_api.ps_verify_email_api(access_token, code, log_callback=...)
typeform = ps_api.ps_complete_typeform(access_token, log_callback=...)
me = ps_api.ps_fetch_me(access_token)
sub = ps_api.ps_pick_subaccount(me)
proxies = ps_api.ps_download_proxy_list(access_token, sub["id"], log_callback=...)
proxy_file = save_proxy_list_file(email, proxies, log_callback=...)   # data/proxy_lists/{email}.http.txt
expire_at = (now + account_valid_days).isoformat()
ps_detail = {"access_token":..., "account_id":..., "expire_at":..., "proxy_file":..., "resin_status": "skipped"}
if ps_resin.resin_enabled():
    resin_status = "success" if ps_resin.resin_push_subscription(email, proxies) else "failed"
# 账号文件 data/accounts/{email}.txt: email----password----access_token（原子写）
# 成功 → _persist_result(status="success", ps_detail=ps_detail) → i+=1
```
失败路径：`classify_failure` 分类 → `_persist_result(status="failure", failure_type=...)`；`capture_failure_screenshot` 保留；outlookemail 停用逻辑保留（`disable_outlookemail_consumed` 改为按 PS 失败原因）。`_token_mode_map`/`cpa_auto_add`/TokenAuth 摘要日志删除，改为 PS 配置摘要日志（`ps_dashboard_base`/`resin_enabled`）。
- [ ] **Step 4: 新增账号/代理文件函数**

`save_proxy_list_file(email, proxies, log_callback=None) -> str`（写 `data/proxy_lists/{email}.http.txt`，原子写）；`account_file_for_email` 复用；`data/proxy_lists/` 目录 ensure。
- [ ] **Step 5: _wire_runtime_modules 注入**

`ps_api.configure(http_post=http_post, http_get=http_get, http_delete=http_delete)`；`ps_resin.configure(...)` 同款；signup_flow.configure 保留（页面步骤共用 `_deps`）。
- [ ] **Step 6: 更新进度日志标记**

worker 日志沿用 `[*]`/`[+]`/`[-]` 约定：`[*] 打开 ProxyScrape 注册页`、`[*] 填写注册表单`、`[*] 等待 Turnstile`、`[*] 验证邮箱`、`[*] 下载代理列表`、`[+] 注册成功: {email}`、`[-] ...`。`test_job_tracking.py` 的进度正则同步更新。
- [ ] **Step 7: 运行测试**

Run: `python -m unittest discover -s backend/tests -v 2>&1 | tail -40`
Expected: 保留测试全绿（除明确标注的基线失败）。
- [ ] **Step 8: Commit**

```bash
git add backend/registration/engine.py backend/tests/test_job_tracking.py backend/tests/test_proxy_routing.py
git commit -m "feat: rewrite engine to proxyscrape registration pipeline"
```

---

### Task 10: store.py 扩展 PS 字段

**Files:**
- Modify: `backend/registration/store.py`
- Modify: `backend/tests/test_registration_repository.py`

**Interfaces:**
- Consumes: Task 9 persist 调用
- Produces: `add_result` 接受新键 `access_token`/`account_id`/`expire_at`/`proxy_file`/`resin_status`；`RESULT_COLUMNS` 追加；`_initialize` migrations 追加 5 列；`PRAGMA user_version` 升到 8

- [ ] **Step 1: 写失败测试**

`test_registration_repository.py` 新增用例：`add_result` 传入新键 → `get_results_by_ids` 读回一致；旧库迁移（`executescript(OLD_SCHEMA)` 造 `user_version=7` 库）→ 断言新列存在且默认值正确。
- [ ] **Step 2: 运行验证失败**

Run: `python -m unittest backend.tests.test_registration_repository -v 2>&1 | tail -10`
Expected: FAIL（新键未入库/列缺失）
- [ ] **Step 3: 实现**

`RESULT_COLUMNS` 追加 5 键；`_initialize` DDL 新库加 5 列（`access_token TEXT NOT NULL DEFAULT ''`、`account_id TEXT NOT NULL DEFAULT ''`、`expire_at TEXT NOT NULL DEFAULT ''`、`proxy_file TEXT NOT NULL DEFAULT ''`、`resin_status TEXT NOT NULL DEFAULT 'skipped'`）；migrations dict 追加（旧库 ALTER）；`user_version` 置 8；`add_result` record 传递新键。
- [ ] **Step 4: 运行测试验证通过**

Run: `python -m unittest backend.tests.test_registration_repository -v 2>&1 | tail -10`
Expected: PASS
- [ ] **Step 5: Commit**

```bash
git add backend/registration/store.py backend/tests/test_registration_repository.py
git commit -m "feat: extend repository with proxyscrape account fields"
```

---

### Task 11: web 层新增 PS 端点与配置面

**Files:**
- Modify: `backend/web/application.py`
- Modify: `backend/web/jobs.py`
- Modify: `config.example.json`
- Modify: `backend/tests/test_config_file_view.py`（若断言旧键）

**Interfaces:**
- Consumes: Task 9/10
- Produces:
  - `GET /api/accounts/{account_id}/proxy-list` → `FileResponse`（代理文件，media_type `text/plain`）
  - `POST /api/connectivity` 保留
  - `CONFIG_PUBLIC_KEYS` 更新为 PS 键集合
  - `jobs.py` 进度正则更新：`打开注册页`→`打开 ProxyScrape 注册页`、`创建邮箱并提交`→`填写注册表单`、`拉取验证码`→`验证邮箱`、`[+] 注册成功`/`[-] 域名拒绝:` 保留；新增 `下载代理列表` stage

- [ ] **Step 1: 写失败测试（config 白名单）**

`test_config_file_view.py` 新增：`PUT /api/config` 写 `ps_dashboard_base` 生效、`cpa_auto_add` 被忽略/拒绝。
- [ ] **Step 2: 实现 application.py**

`CONFIG_PUBLIC_KEYS` = `DEFAULT_CONFIG` 键白名单（从 engine 导出或用显式元组）；新增 proxy-list 端点（`_find_account_proxy_file(record)` 读 `proxy_file` 字段，校验路径在 `DATA_DIR/proxy_lists/` 内，防穿越——复用 `_path_within`）；`_public_config` 同步。
- [ ] **Step 3: 更新 config.example.json**

移除全部 grok 键（同 Task 3 清单）；新增：`ps_dashboard_base`、`ps_api_base`、`ps_password_length`、`ps_skip_typeform`、`ps_proxy_list_dir`、`account_valid_days`、`resin_base_url`、`resin_auth_token`、`resin_subscriptions_path`、`resin_timeout`、`resin_verify_tls`。
- [ ] **Step 4: 更新 jobs.py 进度正则**

按上面映射更新 `_update_progress_from_log` 匹配串。
- [ ] **Step 5: 运行测试**

Run: `python -m unittest backend.tests.test_config_file_view backend.tests.test_job_tracking -v 2>&1 | tail -20`
Expected: PASS
- [ ] **Step 6: Commit**

```bash
git add backend/web/application.py backend/web/jobs.py config.example.json backend/tests/test_config_file_view.py
git commit -m "feat: add proxyscrape config surface and proxy-list endpoint"
```

---

### Task 12: 前端 API 层更新

**Files:**
- Modify: `front/src/lib/api.ts`

**Interfaces:**
- Consumes: Task 11 端点
- Produces: 删除 relogin/ssoCheck/grok2apiImport 相关方法与类型；`AccountRecord` 增加 `access_token`/`account_id`/`expire_at`/`proxy_file`/`resin_status`，删除 `sso_risk_check`/`grokiq_delivery`；新增 `fetchProxyList(accountId)`（URL 下载）/`downloadProxyList(ids)`；`AuthKind` 删除（如无其他使用）；`JobStatus` 字段不变

- [ ] **Step 1: 更新 api.ts**

按上面清单删除/新增方法；`request<T>`/`downloadAuthArchive` 保留（下载代理列表复用其 blob 模式，改名 `downloadProxyList`：POST `/api/accounts/{kind}/download` 不再适用，改 `GET /api/accounts/{id}/proxy-list` 直接浏览器下载或 fetch blob）。
- [ ] **Step 2: 类型检查**

Run: `cd front && npx tsc --noEmit`
Expected: 通过（或仅剩 Task 13/14 页面引用残留，记录清单）
- [ ] **Step 3: Commit**

```bash
git add front/src/lib/api.ts
git commit -m "feat: update frontend api layer for proxyscrape"
```

---

### Task 13: 前端删除 grok 页面与路由

**Files:**
- Delete: `front/src/pages/Relogin.tsx`、`front/src/pages/ReloginHistory.tsx`、`front/src/pages/SsoCheck.tsx`、`front/src/pages/Credentials.tsx`、`front/src/components/ReloginHistoryDialog.tsx`、`front/src/components/ReloginReportDialog.tsx`、`front/src/lib/reloginHistory.ts`、`front/src/lib/ssoCheckHistory.ts`
- Modify: `front/src/App.tsx`、`front/src/app/navigation.ts`

**Interfaces:**
- Produces: 路由删除 `/accounts/relogin*`、`/accounts/sso-check*`、`/accounts/credentials`；导航删除"账号重新登录"/"SSO 风控检查"/"授权文件管理"项；`mobilePrimaryItems` 同步

- [ ] **Step 1: 删除文件**

`git rm` 上述 8 个文件。
- [ ] **Step 2: 更新 App.tsx 与 navigation.ts**

删除相关 import/Route/导航项；保留 `/overview`、`/accounts`、`/registration/*`、`/settings/*` 路由；旧路由不加重定向（本期直接移除）。
- [ ] **Step 3: 类型检查 + 构建**

Run: `cd front && npx tsc --noEmit && npm run build`
Expected: 通过
- [ ] **Step 4: Commit**

```bash
git add -A front/src
git commit -m "refactor: remove grok pages and routes from frontend"
```

---

### Task 14: 前端页面改造（Register/Accounts/Dashboard/Settings）

**Files:**
- Modify: `front/src/pages/Register.tsx`、`front/src/pages/Accounts.tsx`、`front/src/pages/Dashboard.tsx`、`front/src/pages/Settings.tsx`、`front/src/components/AccountBatchActions.tsx`（若引用已删方法）

**Interfaces:**
- Consumes: Task 12 api.ts
- Produces:
  - Register（view="new"）：去 CPA/Grok2API 配置段；表单含 邮箱商/数量/并发/账号间隔（保留）+ PS 段（密码长度、ps_skip_typeform）
  - Accounts：列 邮箱/状态/创建时间/有效期/代理文件/Resin；详情操作含"下载代理列表"；批量操作删 relogin/sso-check/auth-export，保留 删除
  - Dashboard：统计卡片改 成功/失败/进行中（去风控/CPA 指标）；`ssoRiskCheck` 相关展示删除
  - Settings：`/settings/registration` 更新字段（去 CPA/Grok2API/NSFW）；`/settings/tokenauth` 改为 PS/Resin 配置（或改名保留路由）；`/settings/mail` 保留
  - `ui.tsx` 不动

- [ ] **Step 1: 逐页改造**

按上面清单改 4 个页面 + `AccountBatchActions`；删除对已删 api 方法的调用（tsc 报错即清单）。
- [ ] **Step 2: 类型检查 + 构建**

Run: `cd front && npx tsc --noEmit && npm run build`
Expected: 通过
- [ ] **Step 3: Commit**

```bash
git add -A front/src
git commit -m "feat: adapt pages to proxyscrape workflow"
```

---

### Task 15: 文档与全量验证

**Files:**
- Modify: `README.md`、`WEB.md`、`DEPLOYMENT.md`（功能描述与配置表更新）、`front/src/index.html`（title 若含 grok）
- Modify: `docs/superpowers/specs/2026-08-15-proxyscrape-registration-design.md`（无需改，仅核对）

**Interfaces:** 无

- [ ] **Step 1: 更新文档**

README 功能清单/配置表/API 摘要改为 ProxyScrape；WEB.md 目录与主要 API 更新；DEPLOYMENT.md 配置键示例更新；删除 grok 相关截图引用可保留（图片不动）。
- [ ] **Step 2: 全量后端测试**

Run: `python -m unittest discover -s backend/tests -v 2>&1 | tail -20`
Expected: 全绿（或与基线一致）
- [ ] **Step 3: compileall**

Run: `python -m compileall -q backend`
Expected: 无输出
- [ ] **Step 4: 前端构建**

Run: `cd front && npm run build`
Expected: 成功
- [ ] **Step 5: 本地启动冒烟**

Run: `python -m backend.web.cli --host 127.0.0.1 --port 8787`（后台）→ `curl http://127.0.0.1:8787/api/health` 返回 ok → `curl http://127.0.0.1:8787/api/config` 含 `ps_dashboard_base` 且不含 `cpa_auto_add` → 停服。
- [ ] **Step 6: Commit**

```bash
git add README.md WEB.md DEPLOYMENT.md front/src/index.html
git commit -m "docs: update for proxyscrape registration"
```

---

## 自审记录

- **Spec 覆盖**：移除清单 → Task 2/3/4/5/13；新增模块 → Task 6/7/8；数据流 → Task 9；存储与配置 → Task 10/11；失败分类 → Task 3/9；前端 → Task 12/13/14；测试策略 → 各任务内嵌；保持不动 → 无任务（约束）；验证标准 → Task 15；后续不做 → 明确排除。
- **占位符扫描**：无 TBD/TODO；Task 9 Step 3 为伪代码骨架（有明确实现指令与移植来源，非占位）。
- **类型一致性**：`ps_detail` dict 键（access_token/account_id/expire_at/proxy_file/resin_status）在 Task 9/10/11/12 一致；`ps_api`/`ps_resin` 签名在 Task 6/8 定义、Task 9 消费；`FAIL_PS_*` 常量在 Task 3 定义、Task 9 使用。
