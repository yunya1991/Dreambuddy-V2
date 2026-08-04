#!/bin/bash
# Agent B 策略参数优化 — launchd 安装脚本
# 每日凌晨 2:00 触发，日志输出到 logs/agent_b.log
# 用法: bash scripts/install_strategy_update_launchd.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.dreambuddy.agent-b-strategy-update"
PLIST_SRC="$PROJECT_DIR/com.dreambuddy.agent-b-strategy-update.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DST="$LAUNCH_AGENTS_DIR/${LABEL}.plist"
UID_NUM=$(id -u)

echo "=================================================="
echo "  Agent B 策略参数优化 — Launchd 安装"
echo "=================================================="
echo

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$PROJECT_DIR/logs"

echo "[1/5] 复制 plist 到 LaunchAgents..."
cp "$PLIST_SRC" "$PLIST_DST"
echo "  → $PLIST_DST"
echo

echo "[2/5] 清除扩展属性（com.apple.provenance 等）..."
xattr -c "$PLIST_DST" 2>/dev/null || true
echo "  完成"
echo

echo "[3/5] 验证 plist 语法..."
plutil -lint "$PLIST_DST"
echo

echo "[4/5] 卸载旧服务（如果存在）..."
launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
launchctl unload "$PLIST_DST" 2>/dev/null || true
echo "  完成"
echo

echo "[5/5] 加载服务..."
launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DST"
launchctl enable "gui/${UID_NUM}/${LABEL}"
echo "  完成"
echo

echo "=================================================="
echo "  ✅ 安装完成！"
echo "=================================================="
echo
echo "服务标签:   $LABEL"
echo "触发时间:   每日 02:00 (StartCalendarInterval)"
echo "入口脚本:   $PROJECT_DIR/scripts/run_agent_b_strategy_update.sh"
echo "业务日志:   $PROJECT_DIR/logs/agent_b.log"
echo "stdout日志: $PROJECT_DIR/logs/agent_b_strategy_update_stdout.log"
echo "stderr日志: $PROJECT_DIR/logs/agent_b_strategy_update_stderr.log"
echo
echo "常用命令:"
echo "  查看状态:   launchctl list | grep $LABEL"
echo "  手动触发:   launchctl kickstart gui/${UID_NUM}/${LABEL}"
echo "  查看业务日志: tail -f $PROJECT_DIR/logs/agent_b.log"
echo "  停止服务:   launchctl bootout gui/${UID_NUM}/${LABEL}"
