#!/bin/zsh
set -e

# M25 用户策略生成系统 (port 8095) launchd 安装脚本
# 用法: ./install_strategy_gen.sh

ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}/25-用户策略生成系统"
PLIST_SRC="${SERVICE_DIR}/ops/launchd/com.ft.strategy_gen.8095.plist"
LABEL="com.ft.strategy_gen.8095"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
PORT=8095

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${ROOT_DIR}/10-经典指标系统/user_data/logs"

# plist 已使用绝对路径，直接复制
cp "${PLIST_SRC}" "${PLIST_DST}"

/usr/bin/plutil -lint "${PLIST_DST}"

UIDN="$(id -u)"
launchctl bootout "gui/${UIDN}" "${PLIST_DST}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UIDN}" "${PLIST_DST}"
launchctl enable "gui/${UIDN}/${LABEL}" || true
launchctl kickstart -k "gui/${UIDN}/${LABEL}"

sleep 2
echo "--- health check ---"
curl -sS -m 3 "http://127.0.0.1:${PORT}/health" || echo "WARN: health check failed"
