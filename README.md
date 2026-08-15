# ProxyScrape Register

ProxyScrape Register 为本项目的名称，实际功能是 ProxyScrape 账号批量注册：基于 FastAPI、React 和 Camoufox 的 Web 注册管理工具，支持注册任务、账号管理、代理列表下载，以及可选的 Resin 代理池入池。

[部署文档](DEPLOYMENT.md) · [Web 说明](WEB.md)

## 界面预览

### 工作概览

![ProxyScrape Register 工作概览](docs/images/dashboard.png)

### 注册、监控与账号

| 新建注册 | 运行监控 | 账号列表 |
| --- | --- | --- |
| ![新建注册页面](docs/images/register.png) | ![运行监控页面](docs/images/runtime.png) | ![账号管理页面](docs/images/accounts.png) |

## 功能

- Web 控制台：任务进度、实时日志、账号管理和系统设置
- Camoufox 浏览器，支持多 worker 和异常进程清理
- 支持 Cloudflare、DuckMail / Mail.tm、YYDS、MailNest、OutlookEmail、CloudMail
- ProxyScrape 批量注册（access_token + AccountID + 代理列表下载）
- 代理列表本地保存与下载（data/proxy_lists/）
- 可选 Resin 代理池入池
- 首次访问创建唯一管理员账号
- Docker Compose 部署，支持无桌面 Linux 服务器
- GitHub Actions 自动构建 GHCR 镜像

## Docker 快速启动

宿主机只需安装 Docker 和 Docker Compose。

```bash
git clone https://github.com/xujw3/ps_reg.git
cd ps-register
cp .env.example .env
docker compose build
docker compose up -d
```

访问：`http://服务器IP:8787`

查看状态和日志：

```bash
docker compose ps
docker compose logs -f ps-register
curl http://127.0.0.1:8787/api/health
```

容器内使用 **Xvfb + 有头 Camoufox**，服务器不需要桌面环境。Docker 模式会强制关闭无头模式。

如果配置里的代理是 `127.0.0.1:7897`，Compose 会自动映射到宿主机代理。宿主机代理软件需要允许局域网连接（监听 `0.0.0.0` 或 Docker 网桥地址）。

完整说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。

### 可选 OutlookEmail 邮箱池

Compose 已集成 [`ghcr.io/assast/outlookemail:latest`](https://github.com/assast/outlookEmail)，默认不随主服务启动。需要选择 OutlookEmail 邮箱、导入账号或读取邮件时，在 `.env` 修改登录密码和 `SECRET_KEY`，然后启动可选 profile：

```bash
docker compose --profile outlookemail up -d
```

访问地址：

```text
ProxyScrape Register: http://服务器IP:8787
OutlookEmail:  http://服务器IP:5000
```

`5000` 默认映射到宿主机所有网卡。主容器内的 API Base 使用：

```text
http://outlook-email:5000
```

Docker 首次生成 `data/config.json` 时会预填该内部地址；已有配置可在“系统设置 → Outlook 邮箱池”中填写。

OutlookEmail 数据保存在 `outlookemail-data/`，并已被 Git 和 Docker 构建上下文忽略。完整配置见 [DEPLOYMENT.md](DEPLOYMENT.md#可选-outlookemail-邮箱池)。

## Resin 代理池入池（可选）

注册成功后，可将下载的代理列表入池到 Resin 代理池。仅需配置 `resin_base_url` 与 `resin_auth_token` 即可启用；入池失败不影响注册成功判定。完整配置见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 配置文件

### 本机运行

读取根目录：

```text
config.json
```

首次使用：

```bash
cp config.example.json config.json
```

### Docker 运行

读取宿主机：

```text
data/config.json
```

使用已有的本地配置：

```bash
mkdir -p data
cp config.json data/config.json
docker compose restart ps-register
```

也可以在 Web 的“系统设置”中修改配置。

Docker 配置中与 ProxyScrape / Resin 相关的核心键：

```json
{
  "ps_dashboard_base": "https://dashboard.proxyscrape.com/v2",
  "ps_api_base": "",
  "ps_signup_url": "",
  "ps_password_length": 14,
  "ps_skip_typeform": true,
  "ps_proxy_protocol": "http",
  "ps_proxy_format": "userpass",
  "ps_proxy_list_dir": "data/proxy_lists",
  "account_valid_days": 7,
  "resin_base_url": "",
  "resin_auth_token": "",
  "resin_timeout": 30,
  "resin_verify_tls": false,
  "resin_ephemeral": false
}
```

## 本机运行

要求：Python 3.10+、Node.js 22+。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m camoufox fetch

cd front
npm install
npm run build
cd ..

cp config.example.json config.json
./start-web.sh
```

访问：`http://127.0.0.1:8787`

Windows 启动：

```powershell
.venv\Scripts\python.exe -m backend.web.cli --host 127.0.0.1 --port 8787
```

## 主要配置

建议直接在 Web 设置页填写。

| 配置项 | 说明 |
| --- | --- |
| `email_provider` | 邮箱服务商 |
| `register_count` | 注册数量 |
| `register_workers` | 并发数量，默认 1 |
| `proxy` | 注册浏览器与 ProxyScrape API 请求使用的 HTTP(S) 代理；支持 `http://host:port` 和 `http://user:password@host:port`，凭据中的特殊字符需使用 URL 百分号编码 |
| `browser_headless` | 本机无头模式；Docker 中强制关闭 |
| `ps_dashboard_base` | ProxyScrape Dashboard 基础地址，默认 `https://dashboard.proxyscrape.com/v2` |
| `ps_api_base` | ProxyScrape API 基础地址，留空与前端一致走 Dashboard 同源 |
| `ps_signup_url` | 注册页地址，留空使用默认注册页 |
| `ps_password_length` | 账号密码长度，默认 14（10–32） |
| `ps_skip_typeform` | 跳过注册问卷 Typeform，默认 true |
| `ps_proxy_protocol` | 代理列表协议，默认 http |
| `ps_proxy_format` | 代理凭据格式，默认 userpass |
| `ps_proxy_list_dir` | 代理列表保存目录，默认 `data/proxy_lists` |
| `account_valid_days` | 账号有效天数判定，默认 7 |
| `resin_base_url` | Resin 代理池基础地址，留空不启用 |
| `resin_auth_token` | Resin 鉴权 Token，与 `resin_base_url` 同时配置即启用入池 |
| `resin_cookie` | Resin 会话 Cookie（可选，与 Token 二选一） |
| `resin_timeout` | Resin 请求超时秒数，默认 30 |
| `resin_verify_tls` | 是否校验 Resin TLS 证书，默认 false |
| `resin_ephemeral` | 节点按有效期标记临时，到期由 Resin 驱逐，默认 false |

配置模板见 [`config.example.json`](config.example.json)。

## 数据目录

```text
data/
├── config.json                   # Docker 配置
├── web_auth.json                 # Web 管理员认证
├── accounts/                     # 账号和注册结果
└── proxy_lists/                  # ProxyScrape 代理列表（{email}.http.txt）

logs/                             # 运行日志
outlookemail-data/                # 可选 OutlookEmail 数据
```

`data/`、`logs/` 和本地 `config.json` 已被 Git 忽略。

## 常用命令

```bash
# 停止服务
docker compose down

# 更新本地构建
git pull
docker compose up -d --build

# 验证有头 Camoufox
docker compose run --rm ps-register python /app/docker/camoufox_smoke.py

# 后端测试
.venv/bin/python -m unittest discover -s backend/tests -v

# 前端构建
cd front && npm run build
```

## 常见问题

### Docker 修改配置后未生效

Docker 读取 `data/config.json`，不是根目录 `config.json`。修改后执行：

```bash
docker compose restart ps-register
```

### Camoufox 未安装

```bash
.venv/bin/python -m camoufox fetch
.venv/bin/python -m camoufox version
```

### 公网 HTTPS 登录状态异常

在 `.env` 中设置：

```dotenv
PS_WEB_COOKIE_SECURE=1
```

然后重建容器：

```bash
docker compose up -d --force-recreate
```

## 项目结构

```text
front/                  React 前端
backend/                Python 后端
  web/                  FastAPI、认证与任务调度
  registration/         注册编排、仓储和结果产物
  automation/           Camoufox 浏览器运行时
  integrations/         代理、连通性与 ProxyScrape / Resin 集成
  mailbox/              邮箱渠道适配
  shared/               公共路径等基础设施
backend/tests/          后端测试
docker/                 容器启动与浏览器验证
docs/images/            Web 界面截图
.github/workflows/      GitHub Actions
data/                   运行数据
  screenshots/          浏览器注册失败现场截图
logs/                   运行日志
outlookemail-data/      可选 OutlookEmail 数据
compose.yaml            Docker Compose 配置
```

## Stars 趋势

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/stars-trend-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/images/stars-trend-light.svg">
  <img alt="ProxyScrape Register Stars 趋势" src="docs/images/stars-trend-light.svg">
</picture>

> 图表由 GitHub Actions 每 6 小时读取最新 Stars 总数并自动更新，浅色与深色主题会随 GitHub 页面设置切换。

## 友情链接

- [Linux.do 社区](https://linux.do)

## License

[MIT](LICENSE)
