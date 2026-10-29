#!/bin/bash
# start-cloud-all.sh — 一键恢复云端全量服务（分层暂停的逆操作）
# 用法: ./start-cloud-all.sh
# 动作: 对全部 service + timer 执行 enable --now，最后输出状态核验
set -euo pipefail
REMOTE="dreambuddy-remote"

ALL_SERVICES=(
  # 前端/看板
  dreambuddy-frontend
  product-hub
  yijing-data-server
  # 交易链
  yijing-polling-trader
  v15-api
  v15-capital-api
  trailing-stop-runner
  signal-scanner
  # 研究/策略 API
  m25-strategy-generation
  m26-strategy-lib
  m27-governance
  m28-signal-trigger
  fundamental
  # DreamOS 编排
  dreamos-scheduler
  dreamos-dynamic-evaluator
  # 训练/数据/反思/治理（保留链，幂等确保）
  datacenter-scheduler
  cognitive-daemon
  etl-worker
  hermes-gateway
  group-poller
  hermes-dashboard
)

ALL_TIMERS=(
  # 交易调度
  v15-poll-light
  v15-orchestrator
  ranking-trigger
  yijing-monitor
  ab-monitor
  ab-orchestrator
  # 训练/数据/治理（保留链，幂等确保）
  dreambuddy-continual-training
  datacenter-backfill
  dreambuddy-snapshot
  dal-backup
  dal-integrity
  dal-rotate
  memory-cleanup
)

echo ">> [1/3] 启用并启动全部服务 (${#ALL_SERVICES[@]} 个)..."
ssh "$REMOTE" "sudo systemctl enable --now ${ALL_SERVICES[*]}"

echo ">> [2/3] 启用并启动全部定时器 (${#ALL_TIMERS[@]} 个)..."
ssh "$REMOTE" "sudo systemctl enable --now ${ALL_TIMERS[*]/%/.timer}"

echo ">> [3/3] 状态核验:"
FAIL=0
for u in "${ALL_SERVICES[@]}"; do
  st="$(ssh "$REMOTE" "systemctl is-active $u" 2>/dev/null)"
  [ "$st" = "active" ] || { echo "   ⚠️  $u = $st"; FAIL=1; }
done
for t in "${ALL_TIMERS[@]}"; do
  st="$(ssh "$REMOTE" "systemctl is-active $t.timer" 2>/dev/null)"
  [ "$st" = "active" ] || { echo "   ⚠️  $t.timer = $st"; FAIL=1; }
done
if [ "$FAIL" = "0" ]; then
  echo "   ✅ 全部服务与定时器已恢复 active"
else
  echo "   存在未恢复单元，请用 ./status-cloud.sh 排查（journalctl -u <unit> 查看日志）"
  exit 1
fi
