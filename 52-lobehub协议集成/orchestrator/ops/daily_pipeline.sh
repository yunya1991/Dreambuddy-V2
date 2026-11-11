#!/bin/bash
# 52-LobeHub 每日流水线：shadow 批量 → 蒸馏桥消费。
# 用途：作为 launchd / crontab 被 macOS TCC 拦截时的统一入口，
# 供产品 Schedule 定时任务或人工手动调用；幂等（桥按游标 + 内容指纹去重）。
set -uo pipefail

ROOT="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/52-lobehub协议集成"
PY="/opt/anaconda3/bin/python3"
LOG_DIR="$ROOT/orchestrator/logs"
mkdir -p "$LOG_DIR"

started_at="$(date -Iseconds)"

cd "$ROOT/orchestrator" || exit 1
"$PY" shadow_batch.py --max 5 --n-per-side 2 >> "$LOG_DIR/shadow_batch.cron.log" 2>&1
shadow_rc=$?

cd "$ROOT/bridge" || exit 1
"$PY" distill_bridge.py --once >> "$ROOT/bridge/logs/bridge.cron.log" 2>&1
bridge_rc=$?

echo "$started_at shadow_rc=$shadow_rc bridge_rc=$bridge_rc" >> "$LOG_DIR/pipeline.log"
echo "shadow_rc=$shadow_rc bridge_rc=$bridge_rc"
exit $(( shadow_rc != 0 || bridge_rc != 0 ))
