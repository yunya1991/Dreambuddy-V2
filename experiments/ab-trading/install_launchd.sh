#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="${SCRIPT_DIR}/com.dreambuddy.screen_orchestrator.plist"
LABEL="com.dreambuddy.screen_orchestrator"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${SCRIPT_DIR}/logs"
UIDN="$(id -u)"

echo "=========================================="
echo "  三屏马丁编排器 - Launchd 安装脚本"
echo "=========================================="
echo ""

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${LOG_DIR}"

echo "[1/5] 复制 plist 到 LaunchAgents..."
cp "${PLIST_SRC}" "${PLIST_DST}"
echo "  → ${PLIST_DST}"
echo ""

echo "[2/5] 验证 plist 语法..."
plutil -lint "${PLIST_DST}"
echo ""

echo "[3/5] 卸载旧服务（如果存在）..."
launchctl bootout "gui/${UIDN}/${LABEL}" 2>/dev/null || true
launchctl unload "${PLIST_DST}" 2>/dev/null || true
echo "  完成"
echo ""

echo "[4/5] 加载并启用服务..."
launchctl bootstrap "gui/${UIDN}" "${PLIST_DST}"
launchctl enable "gui/${UIDN}/${LABEL}"
echo "  完成"
echo ""

echo "[5/5] 触发首次运行..."
launchctl kickstart "gui/${UIDN}/${LABEL}"
echo "  完成"
echo ""

echo "=========================================="
echo "  ✅ 安装完成！"
echo "=========================================="
echo ""
echo "服务标签: ${LABEL}"
echo "运行间隔: 每 10 分钟"
echo "日志文件: ${LOG_DIR}/screen_orchestrator_launchd.log"
echo ""
echo "常用命令："
echo "  查看状态: launchctl list | grep ${LABEL}"
echo "  手动触发: launchctl kickstart gui/${UIDN}/${LABEL}"
echo "  查看日志: tail -f ${LOG_DIR}/screen_orchestrator_launchd.log"
echo "  停止服务: launchctl bootout gui/${UIDN}/${LABEL}"
echo "  卸载服务: launchctl unload ${PLIST_DST}"
echo ""
