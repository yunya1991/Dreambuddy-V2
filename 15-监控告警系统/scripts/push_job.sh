#!/usr/bin/env bash
# 任务指标推送（v2.0 骨架）
# 用法：push_job.sh <job> <success|failed> [duration_seconds] [records]
# 示例：push_job.sh 40_daily success 812 17
# 说明：只允许推送"最后一次运行"与"最后一次成功"；失败时不覆盖上次成功时间，
#       由 JobFailed / *Stale 规则分别判定"失败"与"断更"。
set -euo pipefail

JOB="${1:?usage: push_job.sh <job> <success|failed> [duration] [records]}"
STATUS="${2:-success}"
DURATION="${3:-0}"
RECORDS="${4:-0}"
PG="${PUSHGATEWAY_URL:-http://127.0.0.1:9091}"
NOW="$(date +%s)"

if [[ "$STATUS" != "success" && "$STATUS" != "failed" ]]; then
  echo "invalid status: $STATUS (expected success|failed)" >&2
  exit 2
fi

STATUS_VAL=1
[[ "$STATUS" == "failed" ]] && STATUS_VAL=0

# 每次运行都推送
cat <<EOF | curl -sS --fail --data-binary @- "${PG}/metrics/job/${JOB}"
# TYPE dreambuddy_job_last_run_timestamp_seconds gauge
dreambuddy_job_last_run_timestamp_seconds ${NOW}
# TYPE dreambuddy_job_status gauge
dreambuddy_job_status ${STATUS_VAL}
# TYPE dreambuddy_job_duration_seconds gauge
dreambuddy_job_duration_seconds ${DURATION}
# TYPE dreambuddy_job_records gauge
dreambuddy_job_records ${RECORDS}
EOF

# 仅成功时更新"最后成功时间"
if [[ "$STATUS" == "success" ]]; then
  cat <<EOF | curl -sS --fail --data-binary @- "${PG}/metrics/job/${JOB}"
# TYPE dreambuddy_job_last_success_timestamp_seconds gauge
dreambuddy_job_last_success_timestamp_seconds ${NOW}
EOF
fi
