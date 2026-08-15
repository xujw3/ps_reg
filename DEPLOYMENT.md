# 部署说明

Docker Compose 是推荐方式。容器内使用 Xvfb 运行有头 Camoufox，因此无桌面、只有 SSH 的 Linux 服务器也能运行。

## Docker Compose：本地构建

要求：Docker Engine、Docker Compose。

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose ps
```

访问：`http://服务器IP:8787`

查看状态：

```bash
curl http://127.0.0.1:8787/api/health
docker compose logs -f ps-register
```

验证 Camoufox：

```bash
docker compose run --rm ps-register python /app/docker/camoufox_smoke.py
```

停止或更新：

```bash
docker compose down
git pull
docker compose up -d --build
```

## Docker 配置

Docker 读取：

```text
data/config.json
```

使用已有根目录配置：

```bash
mkdir -p data
cp config.json data/config.json
docker compose restart ps-register
```

没有 `data/config.json` 时，首次启动会从 `config.example.json` 自动生成。

持久化目录：

```text
data/    配置、账号、Web 登录、代理列表（proxy_lists/）
logs/    运行日志
```

`.env` 常用设置：

```dotenv
PS_REGISTER_IMAGE=ps-register:local
PS_WEB_PORT=8787
PS_SHM_SIZE=1gb
PS_WEB_COOKIE_SECURE=0
```

公网 HTTPS 使用：

```dotenv
PS_WEB_COOKIE_SECURE=1
```

如果 `data/config.json` 中的代理是 `http://127.0.0.1:7897`，Compose 会自动改用宿主机地址 `host.docker.internal:7897`。宿主机代理软件必须开启“允许局域网连接”或监听 `0.0.0.0`，否则容器仍然连不上。

## 可选 OutlookEmail 邮箱池

`compose.yaml` 已把上游 [`assast/outlookEmail`](https://github.com/assast/outlookEmail) 镜像作为可选 `outlookemail` profile 接入。默认的 `docker compose up -d` 只启动 ProxyScrape Register；选择 OutlookEmail 邮箱、导入账号、读取验证码或停用邮箱时启动完整组合：

```bash
cp .env.example .env
```

先在 `.env` 至少修改：

```dotenv
OUTLOOKEMAIL_PORT=5000
OUTLOOKEMAIL_LOGIN_PASSWORD=请设置强密码
OUTLOOKEMAIL_SECRET_KEY=请设置随机长字符串
```

生成 `SECRET_KEY`：

```bash
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

启动：

```bash
docker compose --profile outlookemail pull outlook-email
docker compose --profile outlookemail up -d
docker compose --profile outlookemail ps
```

端口：

| 服务 | 容器端口 | 默认宿主机端口 | 监听范围 |
| --- | ---: | ---: | --- |
| ProxyScrape Register | 8787 | 8787 | 所有网卡 |
| OutlookEmail | 5000 | 5000 | 所有网卡 |

浏览器访问 `http://服务器IP:5000`，使用 `OUTLOOKEMAIL_LOGIN_PASSWORD` 登录。在 OutlookEmail 设置页生成“对外 API Key”，然后在 ProxyScrape Register 的“系统设置 → Outlook 邮箱池”填写：

```text
API Base: http://outlook-email:5000
API Key:  OutlookEmail 页面生成的对外 API Key
```

如果使用 `temp` 来源，可填写相同的管理网页登录密码，主服务会自动获取 Session Cookie。数据持久化到：

```text
outlookemail-data/
```

停止全部服务：

```bash
docker compose --profile outlookemail down
```

OutlookEmail 的在线 Docker 更新功能需要挂载 `/var/run/docker.sock`，该 socket 具备宿主 Docker 管理能力。无需在线更新时可在 `.env` 设置：

```dotenv
OUTLOOKEMAIL_DOCKER_UPDATE_ENABLED=false
```

端口默认公开到所有宿主机网卡；公网服务器应通过防火墙、反向代理或安全组限制 `5000` 的访问来源。

## 使用 GHCR 镜像

将镜像名改为全小写：

```dotenv
PS_REGISTER_IMAGE=ghcr.io/xujw3/ps_reg:latest
```

```bash
docker compose pull
docker compose up -d
```

私有镜像先登录：

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u GITHUB_USER --password-stdin
```

GitHub Actions 规则：

- `master` / `main`：构建并发布 amd64
- `v*` 标签：构建并发布 amd64、arm64
- Pull Request：只测试和构建，不发布
- `workflow_dispatch`：支持手动触发

需要免登录分发时，在 GitHub Packages 将容器包设为 Public。

## Resin 代理池入池（可选）

注册成功后，可将下载的代理列表入池到 Resin 代理池。在 `data/config.json` 中配置 `resin_base_url` 与 `resin_auth_token` 即可启用；入池失败不影响注册成功判定。

```json
{
  "resin_base_url": "https://resin.example.com",
  "resin_auth_token": "替换为真实 Token",
  "resin_cookie": "",
  "resin_timeout": 30,
  "resin_verify_tls": false,
  "resin_ephemeral": false
}
```

`resin_base_url` 留空时跳过入池；`resin_cookie` 可选，与 Token 二选一。其余 `resin_*` 键（订阅路径 `resin_subscriptions_path`、更新间隔 `resin_update_interval`、临时节点驱逐延迟 `resin_ephemeral_node_evict_delay` 等）见 `config.example.json`。

## 本机 Python 运行

要求：Python 3.10+、Node.js 22+。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m camoufox fetch

cd front && npm install && npm run build && cd ..
cp config.example.json config.json
./start-web.sh
```

本机读取根目录 `config.json`，访问 `http://127.0.0.1:8787`。

## 反向代理

将域名反代到：

```text
http://127.0.0.1:8787
```

HTTPS 部署时设置 `PS_WEB_COOKIE_SECURE=1`。反向代理需转发 `Host`、`X-Forwarded-For` 和 `X-Forwarded-Proto`。

## 资源建议

- 内存：至少 2 GB
- 共享内存：默认 `1gb`
- 磁盘：预留 5 GB
- amd64 镜像内容大小：约 1.04 GB

多并发时可在 `.env` 提高 `PS_SHM_SIZE`。

## 常见问题

### 配置未生效

Docker 修改 `data/config.json` 后重启：

```bash
docker compose restart ps-register
```

检查容器配置路径：

```bash
docker compose exec ps-register \
  python -c "import os; print(os.environ['PS_CONFIG_FILE'])"
```

应为 `/app/data/config.json`。

### 宿主机代理连接失败

确认代理软件允许 Docker 网桥访问，并检查容器内解析：

```bash
docker compose exec ps-register getent hosts host.docker.internal
```

Linux 宿主机使用 `127.0.0.1` 监听代理时，需在代理软件中开启 Allow LAN；只改容器配置地址不能绕过宿主机监听限制。

### 浏览器启动失败

```bash
docker compose run --rm ps-register python /app/docker/camoufox_smoke.py
docker compose logs --tail=200 ps-register
```

### 端口被占用

在 `.env` 修改：

```dotenv
PS_WEB_PORT=18787
```

然后：

```bash
docker compose up -d --force-recreate
```
