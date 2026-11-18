#!/usr/bin/env bash
# 为定时任务类 systemd 服务补 Pushgateway 打点（ExecStopPost）。
# 背景：pushgateway 上长期只有空数据，JobFailed / *Stale 规则无 series 永不触发。
# 用法（云端 root）：bash deploy/systemd/install-job-push.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/luke/dreambuddy}"
PUSH_JOB="$REPO_ROOT/15-监控告警系统/scripts/push_job.sh"
UNIT_DIR="/etc/systemd/system"

install_one() {
  local unit="$1" job="$2"
  mkdir -p "$UNIT_DIR/${unit}.d"
  cat > "$UNIT_DIR/${unit}.d/20-push-job.conf" <<EOF
[Service]
ExecStopPost=/bin/bash -c '$PUSH_JOB $job \$([ "\$EXIT_STATUS" = "0" ] && echo success || echo failed) || true'
EOF
  echo "installed: ${unit}.d/20-push-job.conf -> $job"
}

install_one dreambuddy-43-strategic-publish.service publish_43
install_one dreambuddy-nn-live-chain.service live_50
install_one dreambuddy-shadow-driver.service shadow_50

systemctl daemon-reload
echo "daemon-reload done"
