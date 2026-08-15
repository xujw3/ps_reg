# Repository Guidelines

## Project Overview

Grok Register：基于 FastAPI + React + Camoufox 的 xAI (Grok) 账号批量注册管理工具。注册账号后自动生成 CPA / Grok2API 授权 JSON 并可导入远程服务，可通过持久 Webhook Outbox 与 GrokIQ 联动。Web 控制台为单管理员账号（PBKDF2 哈希，存 `data/web_auth.json`）。

## Architecture & Data Flow

分层架构（Web 层不承载邮箱/浏览器实现，只做协议与控制台状态）：

```
backend.web（FastAPI + 3 个 single-flight 协调器）
  → backend.registration.engine（编排中枢 ~3500 行：配置/异常/HTTP/主循环/持久化）
    → backend.automation.session（Camoufox 浏览器，thread-local 隔离）
    → backend.mailbox.*（各邮箱渠道，注入 http 客户端）
    → backend.integrations.*（auth_exchange 授权交换 / proxy / network_checks / grokiq / sso_checker）
```

跨层通信三机制（新增代码必须沿用其一，禁止绕过）：

1. **`configure()` 全局回调注入**：`signup_flow._deps`（`Dict[str, Any]`，`_wire_runtime_modules()` 写入邮箱/取消/异常类回调）、`automation/session.configure(get_proxies, is_debug, is_headless, get_locale)`。模块底部调用 `load_config()`、engine import 即加载配置。
2. **`threading.local` 运行时状态**：`signup_flow._runtime`（`last_email`/`last_profile`）、`session._tls`（`browser`/`page`/`profile_dir`）。
3. **模块级单例**：`get_registration_repository()`（双检锁懒加载）、`job_coordinator` / `relogin_coordinator` / `sso_check_coordinator`、`grokiq_notifier`（后台投递线程，startup start / shutdown stop）。

注册主流程：`POST /api/job/start` → `RegistrationJobCoordinator.start`（先 `_bs.allow_browser_launches()`）→ 后台线程 `load_config()` + `_wire_runtime_modules()` → `run_registration(count)`。单账号循环：`open_signup_page` → `fill_email_and_submit`（返回 `(email, dev_token, submitted_at)`）→ `fill_code_and_submit` → `fill_profile_and_submit` → `wait_for_sso_cookie` → `ensure_sso_oauth_eligible` → 写 `data/accounts/{email}.txt`（`email----password----sso`，`.tmp`+`os.replace` 原子写）→ `add_sso_to_cpa` → **`cpa_detail["status"]=="success"` 是唯一成功标准**（`registration_counts_as_success`）→ `persist_registration_result`。

HTTP 统一走 `curl_cffi.requests`：`direct_http_session()`（`trust_env=False`，不读环境代理，默认直连 `proxies={}`、`timeout=15`）；仅 xAI/Grok 相关调用显式注入代理（`get_proxies()` = `resolve_proxy_url(config["proxy"])`）。**TLS 指纹（JA3/JA4）敏感：curl_cffi 锁定 `==0.13.0`，升级会改变指纹导致被风控识别。**

## Key Directories

| 目录 | 用途 |
| --- | --- |
| `backend/web/` | FastAPI 路由（内联 `@app.*` handler，无 Router）、CLI、注册/relogin/SSO 三个协调器 |
| `backend/registration/` | `engine.py` 编排中枢、`signup_flow.py` 页面步骤、`login_flow.py` 重登、`store.py` SQLite 仓储、`artifacts.py` |
| `backend/automation/` | `session.py` Camoufox 生命周期与 profile 清理、`page_adapter.py` Playwright→DrissionPage 风格适配 |
| `backend/integrations/` | `auth_exchange.py`（SSO→token 三路径 + JWT bfs 解析）、`proxy.py`、`network_checks.py`、`grokiq.py`、`sso_checker.py`、`grok2api_client.py`、`sub2api_client.py` |
| `backend/mailbox/` | 邮箱渠道：duck_mail、outlook_pool、cloudflare_worker、yyds_mail、mail_nest、cloud_mail（纯函数 + 注入 http 客户端） |
| `backend/shared/` | `paths.py`：`PROJECT_ROOT` / `DATA_ROOT`(data/) / `STATIC_ROOT`(front/dist) |
| `backend/tests/` | 26 个 stdlib unittest 测试 |
| `front/src/` | React 18 + TS：`pages/`、`components/`（ui.tsx 基础组件）、`lib/`（api.ts、IndexedDB 历史库）、`app/navigation.ts` |
| `data/` | 运行数据（gitignore）：accounts/、cpa_auth/、grok2api_auth/、web_auth.json |
| `docker/` | entrypoint.sh、camoufox_smoke.py |

## Development Commands

```bash
# 安装（必须额外下载浏览器引擎）
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m camoufox fetch

# 后端运行（仓库根）
.venv/bin/python -m backend.web.cli --host 127.0.0.1 --port 8787   # Windows: .venv\Scripts\python.exe
# 或 ./start-web.sh（自动探测 .venv/bin/python）

# 前端
cd front && npm run dev        # vite :5173，/api 代理到 127.0.0.1:8787
cd front && npm run build      # 产物 front/dist（由 FastAPI STATIC_ROOT 托管）

# 测试（必须在仓库根运行：测试断言路径布局 == 仓库根）
.venv/bin/python -m unittest discover -s backend/tests -v

# Docker
docker compose build && docker compose up -d
docker compose --profile outlookemail up -d        # 可选 OutlookEmail 邮箱池
docker compose -f compose.yaml -f compose.grokiq.yaml up -d   # 叠加 GrokIQ
docker compose run --rm grok-register python /app/docker/camoufox_smoke.py  # 有头冒烟
```

**没有 lint / format 脚本**（无 ruff/black/eslint 配置）；CI 只跑 `compileall` + unittest + 前端 build。改了 `requirements.txt` 或前端后需重建镜像。

## Code Conventions & Common Patterns

### 依赖注入
- 模块级 `_deps: Dict[str, Any] = {}` + `configure(**kwargs)` 做 `_deps.update(kwargs)`；通过 `_deps['key']()` 调用避免循环 import。
- 邮箱/探测模块用**构造注入**：函数签名直传 `http_get` / `http_post` / `session_factory`（如 `duckmail_provider.get_domains(http_get, base, key)`、`outlook_pool.acquire_email(http_get, session_factory, ...)`、`SsoChecker(session_factory=...)`）。
- 循环依赖用函数内延迟 import（`_gr()`、`from backend.registration import engine as gr`）。

### 错误处理
- 语义化异常族（engine.py）：`RegistrationCancelled`（空类，停止信号）、`AccountRetryNeeded`、`EmailDomainRejected`（带 `email`/`message`）、`RegistrationRiskDenied`（带 `bot_risk`/`bot_flag_source`）、`signup_flow.AccountAlreadyRegistered`。
- `classify_failure(exc)` 产出 `FAIL_*` 常量（domain_rejected / already_registered / registration_risk / code_timeout / browser / cpa / stuck_retry / sso_timeout / other），中文标签在 `FAIL_LABELS`。
- 持久化失败不打断主流程（内部 try/except 返回 None）；`apply_risk_bot_flag` 把风控标记写入 `cpa_detail["bot_risk"]`/`["bfs"]`。

### 并发
- 协调器统一 `threading.RLock` + 状态 dict + `threading.Thread(daemon=True)`；`status()` 返回**浅拷贝**（items 逐条 `dict(item)`），禁止泄漏内部可变状态。
- 协作式停止：`raise_if_cancelled(cancel_callback)` 抛 `RegistrationCancelled`；`sleep_with_cancel` 按 0.2s 分片轮询。
- 线程隔离：每个 worker 线程独立 Camoufox 实例（`_tls`）；写盘用专用锁（`accounts_lock`/`stats_lock`）。

### 配置
- `DEFAULT_CONFIG` 深合并加载（`load_config()`），`config` 是模块级 dict；Web 层只暴露 `CONFIG_PUBLIC_KEYS` 白名单键。
- 环境变量覆盖：`_environment_bool` / `_environment_int` 解析 `GROK_*`（`GROK_FORCE_HEADED` 强制有头、`GROK_DOCKER_PROXY_HOST` 重写本地代理主机、`GROK_CONFIG_FILE` 配置路径、`GROK_WEB_COOKIE_SECURE` cookie Secure 标志）。
- 任务运行中 `PUT/POST /api/config` 返回 409（前端约定同样适用 relogin/sso-check）。

### 日志
- 所有浏览器/邮箱/编排函数带 `log_callback=None` 参数；前缀约定：`[*]` 信息、`[!]` 警告、`[-]` 失败、`[+]` 成功、`[Debug]` 细节（info 级别被 `should_emit_log` 过滤）。
- 多 worker 加 `[W{wid+1}]`；`registration_log` 加 `[HH:MM:SS]` 时间戳 `print(..., flush=True)`。
- **日志即进度**：`jobs.py._update_progress_from_log` 正则匹配日志文本（"打开注册页"/"创建邮箱并提交"/"[+] 注册成功" 等）更新 stage——新增流程日志注意保持可解析。

### 返回约定
- 校验/诊断类：`(ok, message)` 或 `(name, ok, detail)` 元组（`network_checks.CheckResult`）。
- 流程结果：dict 状态（`status`/`error`/`verdict` 字段）；`cpa_detail` dict 是贯穿全流程的结果载体（`add_sso_to_cpa(..., result_out=cpa_detail)` 原地写）。
- 文件写入一律 `.tmp` + `os.replace` 原子替换；Windows 下 `os.chmod(0o600)` 失败静默。

### 命名
- 模块内部函数/常量 `_` 前缀（`_deps`/`_tls`/`_bs`/`_s2cpa`/`_environment_bool`）。
- provider 转发函数 `{provider}_{操作}`（`cloudflare_create_account`、`yyds_get_messages`）；邮箱操作三件套固定命名 `get_email_and_token` / `get_oai_code` / `wait_for_code`，engine 按 provider 分发。
- 文件头 `# -*- coding: utf-8 -*-` + 中文 docstring；`from __future__ import annotations`。

### 前端
- `api.ts` 统一 `request<T>`：默认 `Content-Type: application/json`；错误判定 `!response.ok || data?.ok === false`；**后端所有接口必须返回 `{ok: boolean, ...}`**；401 + `auth_required` → dispatch `grok-auth-required` CustomEvent。
- 全局状态经 window 事件：`grok-auth-required`（认证失效）、`grok-job-state`（detail `{running}`，Register.tsx 派发，App.tsx 监听）。
- 组件复用 `components/ui.tsx`（Button/Card/Select/Switch/Badge/StatCard/PaginationBar/Toast 等 16 个，无外部 UI 库）+ `cn()`（clsx + tailwind-merge）。
- 主题走 `index.css` `:root` HSL CSS 变量（`--primary 204 86% 55%` 等）；**新增颜色必须先在 `:root` 定义变量再在 tailwind.config.js 注册**。
- 历史持久化照 `lib/reloginHistory.ts` 模式：独立 IndexedDB 库（keyPath `run_id`），DB 打开失败静默降级内存。

## Important Files

| 文件 | 说明 |
| --- | --- |
| `backend/web/application.py` | FastAPI 入口：全部 API 路由（handler 命名 `api_*`）、管理员会话（PBKDF2 + HMAC 签名 cookie）、SPA 静态托管（`/assets` mount + `/{path}` fallback，`api/*` → 404） |
| `backend/web/jobs.py` | `RegistrationJobCoordinator`：single-flight、ring-buffer 日志（2000 条）、SQLite 快照恢复 |
| `backend/registration/engine.py` | 编排中枢：DEFAULT_CONFIG、异常族、`run_registration` 主循环、`persist_registration_result`、provider 转发层、`http_get/post` |
| `backend/registration/signup_flow.py` | 页面步骤：`_native_*` CDP 原生输入（防 `isTrusted=false`）、Turnstile 处理、`fill_*_and_submit` 系列 |
| `backend/automation/session.py` | Camoufox 运行时：`IsolatedCamoufox`、`_SessionProxy` 惰性代理、profile 清理（守卫 `_PROFILE_ROOT_MARKER`）、`kill_all_camoufox_processes` |
| `backend/integrations/auth_exchange.py` | SSO→token 三路径（device_browser/device_flow/auth_code）、`decode_jwt_payload`/`access_token_bfs`、CPA/Grok2API 文件写入 |
| `backend/registration/store.py` | `RegistrationRepository`：SQLite WAL、每操作独立连接、`PRAGMA user_version` 列迁移、`SQLITE_IN_BATCH_SIZE=900` |
| `backend/shared/paths.py` | 路径约定：`PROJECT_ROOT`/`DATA_ROOT`/`STATIC_ROOT` |
| `front/src/lib/api.ts` | 前端 API 封装（约 30 方法 + 全部类型） |
| `front/src/App.tsx` | 认证门 + job 轮询（3s，失败退避 5s）+ 全路由 |
| `config.example.json` | 配置模板；本机 `config.json`，Docker 为 `data/config.json`（entrypoint 首启从 example 生成并注入 env） |
| `.github/workflows/docker.yml` | CI：test（Python 3.12 compileall + unittest；node 22 build）+ docker（GHCR，main/master → amd64，`v*` → amd64+arm64，PR 只测不推） |

## Runtime/Tooling Preferences

- Python 3.10+（CI 3.12、本地 3.13）；Node.js 22+；无 Bun。
- **必须** `python -m camoufox fetch` 下载浏览器引擎（Docker 镜像已预下载到 `/opt/camoufox-cache`）。
- `playwright` 不直接列依赖，由 camoufox 隐式带版本；session.py 用其私有 API（`playwright._impl._connection` 等），升级 camoufox 前必须验证兼容。
- 前端别名 `@` → `src`：`vite.config.ts` 与 `tsconfig.json` 两处必须同步；`vite outDir` 与后端 `STATIC_ROOT` 联动。
- Docker 强制有头（`GROK_FORCE_HEADED=1` + Xvfb）；`security_opt: seccomp=unconfined`、`shm_size` 1gb、非 root `app` 用户。
- 代理约定：config 里 `127.0.0.1:xxxx` 在容器内经 `GROK_DOCKER_PROXY_HOST`（= host.docker.internal）自动改写；日志输出必须经 `redact_proxy_url`/`redact_proxy_text` 脱敏认证代理。

## Testing & QA

- **纯 stdlib unittest，无 pytest、无覆盖率配置**。命令：`python -m unittest discover -s backend/tests -v`（仓库根；`test_runtime_paths.py` 断言路径布局）。
- 文件命名 `test_<被测模块>.py`，类 `<Subject>Tests(unittest.TestCase)`，方法 `test_<行为性短语>`；断言用 `assertEqual/assertIn/assertRaises(Regex)` + mock 断言。
- **Mock 使用处模块的单例**（不要重建 engine）：
  - `mock.patch.object(engine._s2cpa, "sso_to_token"/"write_cpa_auth"/"inspect_sso_account_state", ...)`
  - `mock.patch.object(engine.outlookemail_provider, "acquire_email"/"disable_account", ...)`
  - `mock.patch.object(engine, "get_registration_repository", return_value=store)`
  - `mock.patch.object(<module>.requests, "Session", return_value=fake_session)`（requests 是模块级 import）
  - `mock.patch.object(engine, "DATA_DIR", tmp)` / `mock.patch("backend.registration.engine.CONFIG_FILE", str(path))`
- **全局态快照恢复是硬约定**：`setUp: self.original_config = dict(gr.config)` → `tearDown: gr.config.clear(); gr.config.update(self.original_config)`；`browser_session.configure(...)` 每个测试前配置、tearDown 重置默认 lambda；`signup_flow._deps` 用 `mock.patch.dict`。
- 数据隔离：SQLite 一律 `tempfile.TemporaryDirectory()` + `RegistrationRepository(Path(tmp)/"results.sqlite3")`；迁移测试先 `executescript(OLD_SCHEMA)` 再造库，断言 `PRAGMA user_version`。
- **零真实网络/浏览器**：网络走 fake session；`_tcp_open` 被 patch；真实 HTTP 仅本地 `socketserver.TCPServer(("127.0.0.1", 0), ...)`（test_proxy_routing 验证 Basic 认证）；浏览器只用 fake page/locator。
- 协调器测试：真实启动后台线程，patch `_run_record` 即时返回 + `threading.Event` 门控 + `_wait_idle(coordinator, timeout=2)` 轮询（0.01s 间隔）；退避断言 `mock.patch("...time.sleep")` 检查 `[2, 4]`。
- 新功能需测试时：优先函数构造注入（直接传 fake），避免引入 pytest 依赖；测试注释用中文说明复刻的故障背景。
