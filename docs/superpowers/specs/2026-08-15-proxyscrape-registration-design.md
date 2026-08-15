# Grok Register → ProxyScrape 注册链路改写设计

- 日期：2026-08-15
- 状态：已批准（2026-08-15）
- 范围：将 grok-register 的注册目标从 xAI Grok 改写为 ProxyScrape（移植 proxyscrape_reg 的注册链路），保留 Web 控制台 / 任务协调 / 邮箱渠道 / Camoufox 浏览器基础设施。

## 背景

当前仓库 `D:/Project/grok-register` 是 xAI Grok 账号批量注册管理工具：Camoufox 浏览器自动化 + SSO→OAuth 授权交换 + CPA / Grok2API JSON 导出 + GrokIQ 联动。

目标仓库 `D:/Project/proxyscrape_reg` 已实现生产验证的 ProxyScrape 注册链路：

1. 浏览器打开 `dashboard.proxyscrape.com/v2/sign-up`，填写表单（邮箱/密码/确认 + MUI terms checkbox）
2. 等 Cloudflare Turnstile 完成（sitekey `0x4AAAAAAAFWUVCKyusT9T8r`）
3. `POST /v4/account/auth/register` → access_token
4. `POST /v4/account/verify-email`（验证码）→ `POST /v4/account/typeform` → `POST /v4/account/auth/me` 拿 AccountID
5. `GET /v4/account/{AccountID}/datacenter_shared/proxy-list?type=getproxies&protocol=http` 下载代理列表
6. 产出 `accounts.txt`（`email----password----created_at----expire_at`）+ `proxy_lists/<email>.http.txt`，可选 Resin 入池

## 决策记录

| 决策 | 选项 | 结论 |
|---|---|---|
| 浏览器栈 | Camoufox(Firefox)/Chromium+DrissionPage | **保留 Camoufox + Playwright 原生过 Turnstile**（用户拍板）。turnstilePatch 是 Chrome 扩展不可用；复用现有 `getTurnstileToken` 的 Playwright frame 点击 + 轮询模式 |
| 功能范围 | 精简 / 最大化 / 最小核心 | **精简**：保留 Web 控制台 + 任务协调 + 邮箱渠道 + 账号管理；移除 grok 特有；新增代理列表下载与可选 Resin 入池 |
| 代码形态 | 就地改写 / 新仓库 / 双链路共存 | **就地改写** grok-register 仓库；grok 代码删除是预期结果 |

## 移除清单（grok 特有）

### 后端

- `backend/integrations/`：`auth_exchange.py`、`grok2api_client.py`、`sub2api_client.py`、`grokiq.py`、`sso_checker.py`
- `backend/registration/`：`login_flow.py`；`signup_flow.py` **保留通用 Playwright 原生交互与 Turnstile 工具**（`_native_*` 原生输入、`getTurnstileToken`、`raise_if_cancelled`/`sleep_with_cancel` 转发、`_deps`/`_runtime` 注入框架），**移除 grok 专属页面步骤**（SSO cookie、set_birth_date、set_tos、NSFW、grok.com 页面交互）；PS 专属页面步骤进新增的 `ps_signup_flow.py`
- `backend/web/`：`relogin_jobs.py`、`sso_check_jobs.py`、`account_exports.py`
- `engine.py` 中：`_s2cpa` / `_grok2api` / `_sub2api` 注入、SSO 风控族（`RegistrationRiskDenied`、`apply_risk_bot_flag`、`backfill_access_token_bot_risk`、`backfill_registration_risk_bot_risk`）、NSFW/生日/TOS 接口、`sso_pending` / `sso_risk_rejected` 附属文件逻辑
- 配置键：`cpa_*`、`grok2api_*`、`grokiq_*`、`sub2api_*`、`sso_detailed_risk_check`、`cpa_token_mode`

### 前端

- 页面/路由/导航：`Relogin`、`SsoCheck`、`Credentials`；`reloginHistory.ts`、`ssoCheckHistory.ts`
- `api.ts` 中 relogin / sso-check / grok2api-import 相关方法

### 测试

- `test_sso_checker.py`、`test_sub2api_client.py`、`test_grok2api_client.py`、`test_grokiq.py`、`test_relogin_jobs.py`、`test_sso_check_jobs.py`、`test_registration_risk.py`、`test_registration_risk_bot_flag.py`、`test_access_token_bot_risk.py`、`test_auth_artifact_loading.py`、`test_login_flow.py`

## 新增模块

| 模块 | 职责 | 移植来源 |
|---|---|---|
| `backend/integrations/ps_api.py` | PS REST API 封装：`ps_register_api` / `ps_verify_email_api` / `ps_resend_verification_code` / `ps_complete_typeform` / `ps_fetch_me` / `ps_pick_subaccount` / `ps_fetch_proxy_credentials` / `ps_download_proxy_list`。curl_cffi（沿用 `http_post`/`http_get` 注入），`application/x-www-form-urlencoded` + Bearer，端点默认同源 `dashboard.proxyscrape.com/v2` | `register_core.py` 的 `ps_*` 函数族（`_ps_endpoint` / `_ps_auth_headers`） |
| `backend/registration/ps_signup_flow.py` | 浏览器步骤：`open_ps_signup_page`（先开同源页再清 localStorage 登录态）、`fill_ps_signup_form`（MUI 受控输入 + terms checkbox 原生点击，复用 `_native_*` CDP 模式）、`wait_ps_turnstile_done` + `submit_ps_signup_and_wait_token`（等 CF 完成后点 Continue，读页面 access_token） | `register_core.py` 的 `open_ps_signup_page` / `fill_ps_signup_form` / `accept_ps_terms_checkbox` / `submit_ps_signup_and_wait_token` / `read_ps_access_token_from_page` |
| `backend/integrations/ps_resin.py` | 可选 Resin 入池：`resin_push_subscription` / `resin_list_subscriptions` / `resin_delete_subscription` / `resin_find_subscription_by_name`（强制直连、可关 TLS 校验） | `register_core.py` 的 `_resin_*` 函数族 |
| `backend/registration/ps_accounting.py`（可选拆分） | 账号记录与代理文件：`save_account_record`（`email----password----created_at----expire_at`）、`save_proxy_list_file`、`delete_proxy_list_file` | `register_core.py` 同名函数，路径改为 `data/` 下 |

## 数据流（单账号，替换现有 worker 循环）

```
邮箱渠道取邮箱（保留 6 家：duckmail/cloudflare/yyds/mailnest/cloudmail/outlookemail）
→ open_ps_signup_page（清登录态）
→ fill_ps_signup_form(email, password)（MUI 受控 + terms checkbox）
→ wait_ps_turnstile_done → submit_ps_signup_and_wait_token → access_token
→ 收验证码（邮箱渠道 wait_for_code）→ ps_verify_email_api
→ ps_complete_typeform（ps_skip_typeform 可跳过）→ ps_fetch_me → AccountID
→ ps_download_proxy_list → data/proxy_lists/{email}.http.txt
→ persist（SQLite + 账号记录）→ 可选 resin_push_subscription
```

**成功标准**：`access_token` + `AccountID` + 代理列表下载成功（替代原 `cpa_detail["status"]=="success"`）。

## 存储与配置

- 保留 `RegistrationRepository` SQLite 主存储（WAL、列迁移 `PRAGMA user_version`）与 `data/accounts/{email}.txt`；账号记录扩展字段：`access_token`、`account_id`、`expire_at`、`proxy_file`、`resin_status`（走现有列迁移机制）
- `accounts.txt` 行格式沿用 proxyscrape_reg：`email----password----created_at----expire_at`（默认 7 天 `account_valid_days`），位置 `data/accounts/accounts.txt`
- `DEFAULT_CONFIG` 新增：`ps_dashboard_base`（默认 `https://dashboard.proxyscrape.com/v2`）、`ps_api_base`（空 = 同源）、`ps_password_length`（14）、`ps_skip_typeform`（false）、`ps_proxy_list_dir`（`data/proxy_lists`）、`account_valid_days`（7）、`resin_base_url`、`resin_auth_token`、`resin_subscriptions_path`、`resin_timeout`、`resin_verify_tls`、`ps_turnstile_sitekey`
- `config.example.json`、前端设置页同步；`data/` 目录布局新增 `proxy_lists/`

## 错误处理与失败分类

- 保留：`RegistrationCancelled` / `AccountRetryNeeded` / `EmailDomainRejected`、`classify_failure` 结构、`persist_registration_result`（失败截图、traceback 截断）
- 移除：`RegistrationRiskDenied`、`apply_risk_bot_flag`、`backfill_*`（grok 风控）
- `FAIL_*` 调整：保留 `domain_rejected` / `already_registered` / `code_timeout` / `browser` / `other`；**移除** `registration_risk` / `sso_timeout` / `stuck_retry` / `cpa`；**新增** `FAIL_PS_FORM`（表单/Turnstile/提交）、`FAIL_PS_REGISTER`（注册 API 拒绝）、`FAIL_PS_VERIFY`（验证邮箱/typeform）、`FAIL_PS_PROXY`（me/代理列表下载）。`FAIL_LABELS` 中文映射同步，`empty_fail_stats`/`format_fail_stats` 自动适配
- PS API 响应约定：`{success: bool, error?: str}`（与 `register_core.py` 的 `_parse_consent_result` 同族），失败转抛带语义的异常

## 前端

- **移除**：Relogin / SsoCheck / Credentials 页面、路由、导航项、IndexedDB 历史库
- **修改**：
  - Register 页（`view="new"`）：去 CPA/Grok2API 配置段，保留 邮箱商/数量/并发/代理/密码长度等 PS 相关项
  - Accounts 页：列调整为 邮箱/密码/创建时间/有效期/代理文件/Resin 状态；操作：下载代理列表文件、查看、删除
  - Dashboard：统计项去 grok 指标（如风控统计），保留 成功/失败/进行中
  - Settings：`/settings/tokenauth`（原 CPA/Grok2API）改为 PS 相关设置或移除；`/settings/registration` 更新字段；新增 Resin 配置段
- `api.ts` 类型与方法同步：移除 relogin/sso-check/grok2api-import；新增账号代理文件下载端点（`GET /api/accounts/{id}/proxy-list`）

## 测试

- **删除**：grok 专属 11 个测试文件（见移除清单）
- **修改**：`test_signup_flow.py` → PS 步骤（fake page + `_deps` 注入）；`test_job_tracking.py` 更新进度标记正则；engine 相关测试更新流程与失败分类
- **新增**：
  - `test_ps_api.py`：mock `ps_api.requests.Session`（沿用使用处模块 patch 约定），断言 form-urlencoded 头、Bearer、端点 URL、错误响应
  - `test_ps_signup_flow.py`：fake page/locator，验证 MUI 受控输入、terms checkbox、Turnstile 等待与提交
  - `test_ps_resin.py`：mock 请求，断言订阅推送/删除/查找与直连行为
  - repository 测试补充扩展字段与迁移
- **保留**：repository / mailbox / proxy / browser / runtime_paths / console_auth / config_file_view / failure_screenshots
- CI 不变：`compileall` + `unittest discover -s backend/tests -v` + 前端 build

## 保持不动

- Camoufox 浏览器栈：`automation/session.py`、`page_adapter.py`、`_native_*` 输入模式、profile 生命周期
- 协调器架构：`RegistrationJobCoordinator`、日志环形缓冲、SQLite 快照恢复
- Web 认证：PBKDF2 + 签名 cookie、`GROK_WEB_COOKIE_SECURE`
- 邮箱渠道全部 6 家 provider
- Docker/Compose/entrypoint/CI 结构（浏览器仍是 Camoufox）

## 验证标准

1. `python -m unittest discover -s backend/tests -v` 全绿
2. `npm run build` 通过（front/dist 无残留 grok 页面路由）
3. `python -m compileall -q backend` 通过
4. 本地 `backend.web.cli` 启动，`/api/health`、`/api/config`（ps_* 键存在、cpa_* 键不存在）、`/api/stats` 正常
5. 注册流程冒烟（可选，需真实邮箱/代理）：单账号任务跑通 注册→验证→代理列表落盘

## 后续（本期不做）

- pool_webui 式号池监控看板与过期自动清理（Resin 删除接口已预留，看板后续接入）
- Hotmail/Outlook 邮箱渠道（proxyscrape_reg 有，grok-register 无——OutlookEmail 池已覆盖同类需求）
- 多架构镜像、真无头模式
