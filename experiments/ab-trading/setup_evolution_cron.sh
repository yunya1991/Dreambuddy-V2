#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# 安装 / 卸载 Agent A 每日进化复盘 cron 任务（每日凌晨2点执行）
# 用法：
#   ./setup_evolution_cron.sh install    安装每日凌晨2点触发
#   ./setup_evolution_cron.sh remove     移除 cron 任务
#   ./setup_evolution_cron.sh status     查看当前 cron 状态
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_TAG="# ab-trading-evolution"
CRON_JOB="0 2 * * * cd \"$SCRIPT_DIR\" && /opt/homebrew/bin/python3 -c \"from evolution_scheduler import EvolutionScheduler; s = EvolutionScheduler(); s.run_daily_inspection()\" >> logs/evolution_cron.log 2>&1  $CRON_TAG"

case "${1:-status}" in
  install)
    mkdir -p "${SCRIPT_DIR}/logs"
    if crontab -l 2>/dev/null | grep -q "$CRON_TAG"; then
        echo "[跳过] 进化复盘 cron 任务已存在"
        crontab -l | grep "$CRON_TAG"
        exit 0
    fi
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "[✓] 进化复盘 cron 已安装（每日凌晨 02:00 触发）："
    echo "    $CRON_JOB"
    echo ""
    echo "主日志文件: ${SCRIPT_DIR}/logs/evolution.log"
    echo "cron 日志: ${SCRIPT_DIR}/logs/evolution_cron.log"
    ;;
  remove)
    crontab -l 2>/dev/null | grep -v "$CRON_TAG" | crontab - || true
    echo "[✓] 进化复盘 cron 任务已移除"
    ;;
  status)
    echo "── 当前 crontab ──"
    crontab -l 2>/dev/null || echo "(空)"
    echo ""
    echo "── 最近10条进化主日志 ──"
    tail -10 "$SCRIPT_DIR/logs/evolution.log" 2>/dev/null || echo "(暂无日志)"
    echo ""
    echo "── 最近10条 cron 触发日志 ──"
    tail -10 "$SCRIPT_DIR/logs/evolution_cron.log" 2>/dev/null || echo "(暂无日志)"
    ;;
  *)
    echo "用法: $0 [install|remove|status]"
    exit 1
    ;;
esac
