#!/bin/bash
# stop-cloud-layered.sh — 云端服务分层暂停（仅保留训练/数据/反思/治理链）
# 用法: ./stop-cloud-layered.sh [1|2|all]
#   layer 1: 前端/看板   dreambuddy-frontend(3001) product-hub(3456) yijing-data-server(8765)
#   layer 2: 交易/研究   交易链5 + 研究API4 + dreamos2 + 交易timer6
#   all:     1 + 2
# 保留不动: continual-training / datacenter-* / snapshot / dal-* / memory-cleanup
#           / hermes三单元 / etl-worker / cognitive-daemon / docker / nginx
# 恢复: ./start-cloud-all.sh
set -euo pipefail
REMOTE="dreambuddy-remote"

LAYER1_SERVICES=(
  dreambuddy-frontend
  product-hub
  yijing-data-server
)

LAYER2_SERVICES=(
  yijing-polling-trader
  v15-api
  v15-capital-api
  trailing-stop-runner
  signal-scanner
  m25-strategy-generation
  m26-strategy-lib
  m27-governance
  m28-signal-trigger
  fundamental
  dreamos-scheduler
  dreamos-dynamic-evaluator
)

LAYER2_TIMERS=(
  v15-poll-light
  v15-orchestrator
  ranking-trigger
  yijing-monitor
  ab-monitor
  ab-orchestrator
)

stop_services() {
  local units=("$@")
  echo ">> 停止并禁用服务: ${units[*]}"
  ssh "$REMOTE" "sudo systemctl disable --now ${units[*]}" || true
  for u in "${units[@]}"; do
    printf "   %-32s active=%-10s enabled=%s\n" "$u" \
      "$(ssh "$REMOTE" "systemctl is-active $u" 2>/dev/null)" \
      "$(ssh "$REMOTE" "systemctl is-enabled $u" 2>/dev/null)"
  done
}

stop_timers() {
  local names=("$@")
  local units=("${names[@]/%/.timer}")
  echo ">> 停止并禁用定时器: ${units[*]}"
  ssh "$REMOTE" "sudo systemctl disable --now ${units[*]}" || true
  for u in "${units[@]}"; do
    printf "   %-32s active=%-10s enabled=%s\n" "$u" \
      "$(ssh "$REMOTE" "systemctl is-active $u" 2>/dev/null)" \
      "$(ssh "$REMOTE" "systemctl is-enabled $u" 2>/dev/null)"
  done
}

LAYER="${1:-all}"
case "$LAYER" in
  1)
    stop_services "${LAYER1_SERVICES[@]}"
    ;;
  2)
    stop_services "${LAYER2_SERVICES[@]}"
    stop_timers "${LAYER2_TIMERS[@]}"
    ;;
  all)
    stop_services "${LAYER1_SERVICES[@]}"
    stop_services "${LAYER2_SERVICES[@]}"
    stop_timers "${LAYER2_TIMERS[@]}"
    ;;
  *)
    echo "用法: $0 [1|2|all]" >&2
    exit 1
    ;;
esac
echo ">> 完成。运行 ./status-cloud.sh 查看全量状态。"
