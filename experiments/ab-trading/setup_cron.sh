#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# 安装 / 卸载 系统级 crontab（macOS launchctl 也可用，这里用 crontab）
# 用法：
#   ./setup_cron.sh install    安装每4H触发一次
#   ./setup_cron.sh remove     移除 cron 任务
#   ./setup_cron.sh status     查看当前 cron 状态
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_TAG="# ab-trading-experiment"
CRON_JOB="0 */4 * * * cd \"$SCRIPT_DIR\" && bash run_cycle.sh >> logs/cron.log 2>&1  $CRON_TAG"

case "${1:-status}" in
  install)
    # 检查是否已安装
    if crontab -l 2>/dev/null | grep -q "$CRON_TAG"; then
        echo "[跳过] cron 任务已存在"
        crontab -l | grep "$CRON_TAG"
        exit 0
    fi
    # 追加到现有 crontab
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "[✓] cron 已安装（每4小时触发一次）："
    echo "    $CRON_JOB"
    echo ""
    echo "提示：首次启动前请先在 config/.env 填写 API keys"
    echo "      并将 AUTO_EXECUTE=true 改为开启实盘"
    ;;
  remove)
    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - || true
    echo "[✓] cron 任务已移除"
    ;;
  status)
    echo "── 当前 crontab ──"
    crontab -l 2>/dev/null || echo "(空)"
    echo ""
    echo "── 最近10条 cron 日志 ──"
    tail -20 "$SCRIPT_DIR/logs/cron.log" 2>/dev/null || echo "(暂无日志)"
    ;;
  *)
    echo "用法: $0 [install|remove|status]"
    exit 1
    ;;
esac
