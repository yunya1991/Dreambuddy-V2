#!/bin/bash
# Daily Scheduler 守护进程 — launchd 安装脚本
# 背景：Trae Code 沙箱下，StartCalendarInterval 模式的 launchd 可能遇到权限问题
# 本脚本安装常驻型（KeepAlive）Python 守护进程，内部按日时钟触发：
#   每日 02:00 → Agent B 策略参数优化
#   每日 02:05 → 记忆模块清理
#
# 用法: bash scripts/install_daily_scheduler_launchd.sh [install|remove|status|kickstart]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.dreambuddy.daily_scheduler"
PLIST_SRC="$PROJECT_DIR/com.dreambuddy.daily_scheduler.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DST="$LAUNCH_AGENTS_DIR/${LABEL}.plist"
UID_NUM=$(id -u)
ACTION="${1:-install}"

echo "=================================================="
echo "  Daily Scheduler (Python 常驻守护) — Launchd 管理"
echo "=================================================="
echo
echo "说明：启动后进程 24/7 常驻，内部时钟触发："
echo "  每日 02:00  策略优化 (logs/agent_b.log)"
echo "  每日 02:05  记忆清理 (logs/memory_cleanup.log)"
echo "  守护日志:   logs/daily_scheduler_daemon.log"
echo

mkdir -p "$LAUNCH_AGENTS_DIR"
mkdir -p "$PROJECT_DIR/logs"

case "$ACTION" in
  install)
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

    echo "[5/5] 加载 & 启动服务（RunAtLoad=true 会立即启动）..."
    launchctl bootstrap "gui/${UID_NUM}" "$PLIST_DST"
    launchctl enable "gui/${UID_NUM}/${LABEL}"
    echo "  完成"
    echo

    sleep 2
    if launchctl list | grep -q "$LABEL"; then
        echo "✅ 运行中：$(launchctl list | grep "$LABEL" | awk '{print "PID="$1" 状态="$2}')"
    fi
    echo

    echo "=================================================="
    echo "  ✅ 安装完成！"
    echo "=================================================="
    echo
    echo "服务标签:   $LABEL"
    echo "模式:       KeepAlive 常驻守护（崩溃自动重启）"
    echo "Python 模块: daily_scheduler_daemon.py（内部时钟调度）"
    echo "守护日志:   $PROJECT_DIR/logs/daily_scheduler_daemon.log"
    echo "stdouterr:  $PROJECT_DIR/logs/daily_scheduler_stdouterr.log"
    echo
    echo "常用命令:"
    echo "  查看状态:   launchctl list | grep $LABEL"
    echo "  重启:       launchctl kickstart -k gui/${UID_NUM}/${LABEL}"
    echo "  手动冒烟:   cd $PROJECT_DIR && python3 daily_scheduler_daemon.py --run-now"
    echo "  停止服务:   launchctl bootout gui/${UID_NUM}/${LABEL}"
    ;;

  remove)
    echo "[1/2] 卸载服务..."
    launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    echo "  完成"
    echo

    echo "[2/2] 删除 plist 文件..."
    rm -f "$PLIST_DST"
    echo "  完成"
    echo

    echo "✅ 已移除 $LABEL 服务"
    ;;

  status)
    echo "── 服务状态 ──"
    if launchctl list | grep -q "$LABEL"; then
        echo "✅ 服务已加载 & 运行中：$(launchctl list | grep "$LABEL")"
    else
        echo "❌ 服务未安装或未加载"
    fi
    echo

    echo "── 最近 15 条调度守护日志 ──"
    tail -15 "$PROJECT_DIR/logs/daily_scheduler_daemon.log" 2>/dev/null || echo "(暂无日志)"
    echo

    echo "── 最近 10 条 stdout/stderr ──"
    tail -10 "$PROJECT_DIR/logs/daily_scheduler_stdouterr.log" 2>/dev/null || echo "(暂无日志)"
    ;;

  kickstart)
    echo "重启 Daily Scheduler 守护进程..."
    launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"
    sleep 2
    if launchctl list | grep -q "$LABEL"; then
        echo "✅ 已重启：$(launchctl list | grep "$LABEL")"
    fi
    echo "请查看日志确认："
    echo "  tail -f $PROJECT_DIR/logs/daily_scheduler_daemon.log"
    ;;

  *)
    echo "用法: $0 [install|remove|status|kickstart]"
    exit 1
    ;;
esac
