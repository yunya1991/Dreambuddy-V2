#!/bin/bash
# 记忆模块清理 — launchd 安装脚本
# 每周日凌晨 3:00 触发，日志输出到 logs/memory_cleanup.log（业务）和 logs/memory_cleanup_launchd.log（stdout/stderr）
# 用法: bash scripts/install_memory_cleanup_launchd.sh [install|remove|status|kickstart]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.dreambuddy.memory_cleanup"
PLIST_SRC="$PROJECT_DIR/com.dreambuddy.memory_cleanup.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_DST="$LAUNCH_AGENTS_DIR/${LABEL}.plist"
UID_NUM=$(id -u)
ACTION="${1:-install}"

echo "=================================================="
echo "  记忆模块清理 — Launchd 管理"
echo "=================================================="
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
    echo "触发时间:   每周日 03:00 (Weekday=0, StartCalendarInterval)"
    echo "执行命令:   cd $PROJECT_DIR && python3 -c 'from core.memory.memory_manager import MemoryManager; m = MemoryManager(); m.clean_expired_memories()'"
    echo "业务日志:   $PROJECT_DIR/logs/memory_cleanup.log"
    echo "stdout日志: $PROJECT_DIR/logs/memory_cleanup_launchd.log"
    echo
    echo "常用命令:"
    echo "  查看状态:   launchctl list | grep $LABEL"
    echo "  手动触发:   launchctl kickstart gui/${UID_NUM}/${LABEL}"
    echo "  查看业务日志: tail -f $PROJECT_DIR/logs/memory_cleanup.log"
    echo "  停止服务:   launchctl bootout gui/${UID_NUM}/${LABEL}"
    echo "  重新安装:   bash $0 install"
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
        echo "✅ 服务已加载"
    else
        echo "❌ 服务未安装或未加载"
    fi
    echo

    echo "── 最近10条业务日志 ──"
    tail -10 "$PROJECT_DIR/logs/memory_cleanup.log" 2>/dev/null || echo "(暂无日志)"
    echo

    echo "── 最近10条 launchd stdout/stderr ──"
    tail -10 "$PROJECT_DIR/logs/memory_cleanup_launchd.log" 2>/dev/null || echo "(暂无日志)"
    ;;

  kickstart)
    echo "手动触发记忆清理任务..."
    launchctl kickstart "gui/${UID_NUM}/${LABEL}"
    echo "✅ 已触发，请查看日志确认执行结果"
    echo "  tail -f $PROJECT_DIR/logs/memory_cleanup.log"
    ;;

  *)
    echo "用法: $0 [install|remove|status|kickstart]"
    exit 1
    ;;
esac
