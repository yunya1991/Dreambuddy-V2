#!/usr/bin/env bash
# 40 日更流水线 cron 包装器：执行流水线并把成功/失败推给 Pushgateway。
# 背景：2026-11-10~11-18 流水线因 macro 序列被冷删持续 exit=1，但没有 push_job，
# 导致 Daily40PipelineFailedOrLate / JobFailed 无数据、不能告警，只能等 ArtifactStale 兜底。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$MODULE_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_FILE="${PIPELINE_LOG:-/tmp/40_daily_pipeline_cron.log}"
LOCK_FILE="${PIPELINE_LOCK:-/tmp/40_daily_pipeline.lock}"

START_TS=$(date +%s)
cd "$MODULE_DIR" || exit 1
PYTHON_BIN="$PYTHON_BIN" flock -n "$LOCK_FILE" bash scripts/run_daily_pipeline.sh >> "$LOG_FILE" 2>&1
STATUS=$?
DURATION=$(( $(date +%s) - START_TS ))

if [ "$STATUS" -eq 0 ]; then
  JOB_STATUS=success
else
  JOB_STATUS=failed
fi
bash "$REPO_ROOT/15-监控告警系统/scripts/push_job.sh" 40_daily "$JOB_STATUS" "$DURATION" || true
exit "$STATUS"
