#!/bin/bash
# status-cloud.sh — 云端服务状态速查（只读，无副作用）
# 用法: ./status-cloud.sh
set -euo pipefail
REMOTE="dreambuddy-remote"

ssh "$REMOTE" 'bash -s' <<'EOF'
echo "===== 服务状态 ====="
for u in \
  dreambuddy-frontend product-hub yijing-data-server \
  yijing-polling-trader v15-api v15-capital-api trailing-stop-runner signal-scanner \
  m25-strategy-generation m26-strategy-lib m27-governance m28-signal-trigger fundamental \
  dreamos-scheduler dreamos-dynamic-evaluator \
  datacenter-scheduler cognitive-daemon etl-worker \
  hermes-gateway group-poller hermes-dashboard dreambuddy-continual-training; do
  printf "%-35s active=%-10s enabled=%s\n" "$u" \
    "$(systemctl is-active $u 2>/dev/null)" \
    "$(systemctl is-enabled $u 2>/dev/null)"
done
echo ""
echo "===== 定时器状态 ====="
systemctl list-timers --all --no-pager --plain 2>/dev/null | \
  grep -E "dreambuddy|v15|yijing|datacenter|dal|ranking|memory|ab-" || echo "(无匹配定时器)"
echo ""
echo "===== 数据层 Docker ====="
sudo docker ps --format "{{.Names}}\t{{.Status}}" 2>/dev/null || echo "(docker 查询失败)"
echo ""
echo "===== 端口监听 ====="
ss -tln | grep -E ":(3001|3456|8765|8770|8771|8093|8094|8095|8096|9094|9119)" || echo "(业务端口无监听)"
EOF
