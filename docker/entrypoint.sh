#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${PS_DATA_DIR:-/app/data}"
LOG_DIR="${PS_LOG_DIR:-/app/logs}"
CONFIG_FILE="${PS_CONFIG_FILE:-${DATA_DIR}/config.json}"

mkdir -p "$DATA_DIR" "$LOG_DIR" "$DATA_DIR/accounts"

if [[ ! -e "$CONFIG_FILE" ]]; then
  python - "$CONFIG_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

source = Path("/app/config.example.json")
target = Path(sys.argv[1])
config = json.loads(source.read_text(encoding="utf-8"))


def env_int(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


config["browser_headless"] = False
config["outlookemail_api_base"] = os.environ.get(
    "PS_OUTLOOKEMAIL_API_BASE", "http://outlook-email:5000"
).strip()
target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  echo "[docker] 已创建容器默认配置: $CONFIG_FILE"
elif [[ -d "$CONFIG_FILE" ]]; then
  echo "[docker] 配置路径是目录而不是文件: $CONFIG_FILE" >&2
  exit 1
fi

# Bind mount 可能由宿主机 root 创建，启动时修正容器内权限。
chown -R app:app "$DATA_DIR" "$LOG_DIR"

LOG_FILE="$LOG_DIR/container-$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[docker] DISPLAY=${DISPLAY:-:99}"
echo "[docker] Camoufox 模式: 有头（Xvfb 虚拟显示器）"
echo "[docker] 配置: $CONFIG_FILE"
echo "[docker] 数据: $DATA_DIR"
echo "[docker] 日志: $LOG_FILE"

export HOME=/home/app
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-/opt/camoufox-cache}
export DISPLAY=${DISPLAY:-:99}
export PS_FORCE_HEADED=${PS_FORCE_HEADED:-1}

exec gosu app xvfb-run \
  --auto-servernum \
  --server-args="-screen 0 ${XVFB_SCREEN:-1920x1080x24} -nolisten tcp" \
  "$@"
