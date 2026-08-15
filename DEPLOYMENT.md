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

**`.env` 与 `data/config.json` 的分工**：

| 文件 | 作用 |
| --- | --- |
| `.env` | 仅 compose 基础设施参数：镜像名（`PS_REGISTER_IMAGE`）、端口（`PS_WEB_PORT`）、共享内存（`PS_SHM_SIZE`）、安全 Cookie（`PS_WEB_COOKIE_SECURE`）等 |
| `data/config.json` | **业务配置主体**：邮箱商与接口凭据、ProxyScrape 参数（`ps_*`）、Resin（`resin_*`）、代理等；可在 Web「系统设置」修改，或直接编辑后 `docker compose restart ps-register` |

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

## 使用 GHCR 镜像

GitHub Actions 构建并发布镜像到 `ghcr.io/xujw3/ps_reg`。**不需要克隆仓库**，在服务器上直接建一个目录部署：

```bash
mkdir -p ps-reg && cd ps-reg
mkdir -p data logs
```

创建 `compose.yaml`：

```yaml
services:
  ps-register:
    image: ghcr.io/xujw3/ps_reg:latest
    container_name: ps-register
    restart: unless-stopped
    ports:
      - "8787:8787"
    environment:
      TZ: UTC
      PS_WEB_COOKIE_SECURE: 0   # 公网 HTTPS 反代时改 1
      PS_FORCE_HEADED: "1"
      PS_CONFIG_FILE: /app/data/config.json
      PS_DOCKER_PROXY_HOST: host.docker.internal
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    shm_size: 1gb
    security_opt:
      - seccomp=unconfined
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3).read()"]
      interval: 30s
      timeout: 5s
      start_period: 20s
      retries: 3
```

拉取并启动：

```bash
docker pull ghcr.io/xujw3/ps_reg:latest
docker compose up -d
```

首次启动自动生成 `data/config.json`（从镜像内 `config.example.json` 复制），业务配置（邮箱商、ProxyScrape、Resin）在 Web「系统设置」修改，或编辑 `data/config.json` 后重启：

```bash
docker compose restart ps-register
```

更新镜像：

```bash
docker pull ghcr.io/xujw3/ps_reg:latest
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
