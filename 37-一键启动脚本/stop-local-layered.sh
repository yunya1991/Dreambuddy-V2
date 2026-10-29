#!/bin/bash
# stop-local-layered.sh — 本地服务分层暂停（本地进入"仅训练"模式）
# 用法: ./stop-local-layered.sh [1|2|3|all]
#   layer 1: 看板     yijing_data_server(8765)
#   layer 2: 交易系统  polling-trader / trailing-stop-runner / v15 / yijing_trading 等
#   layer 3: 研究/前端/数据冗余  ft.* / hermes / datacenter / continual-training(云端已覆盖) 等
# 保留不动: evolution_scheduler(训练) / dbsync / cognitive-ttl / l3.commandcenter.*(独立项目)
#           / homebrew postgres、redis、ollama(训练基础设施)
# 恢复: ./start-local-all.sh
set -euo pipefail
UID_="$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"

LAYER1_LABELS=(
  com.dreambuddy.yijing_data_server
)
LAYER1_PATTERNS=(
  "11-易经推理系统/data_server_fixed.py"
)

LAYER2_LABELS=(
  dreambuddy.yijing.polling-trader
  com.dreambuddy.yijing_trading
  com.dreambuddy.yijing_live_300s
  com.dreambuddy.yijing_monitor
  com.dreambuddy.trailing-stop-runner
  com.dreambuddy.v15_light_poll
  com.dreambuddy.v15_orchestrator
  com.dreambuddy.signal_scanner
  com.dreambuddy.ab_monitor
  com.dreambuddy.ab_orchestrator
  com.dreambuddy.screen_monitor
  com.dreambuddy.screen_orchestrator
  com.dreambuddy.trend_executor
  com.dreambuddy.agent-b-strategy-update
  com.dreambuddy.dreamos
  com.dreambuddy.ranking-trigger
)
LAYER2_PATTERNS=(
  "scripts.memory_l4.polling_trader"
  "trailing_stop_runner.py"
  "signal_pool/scanner.py"
  "dreamos.cli.run_dynamic_evaluator"
  "run.py poll_light"
)

LAYER3_LABELS=(
  com.ft.dashboard.3001
  com.ft.ml_trade_service.explore
  com.ft.ml_trade_service.pilot
  com.ft.ml_trade_service.prod
  com.ft.ml_trade_service.8092
  com.ft.explore.ml_trade_service
  com.ft.strategy_gen.8095
  com.ft.fundamental_research_sync
  com.ft_userdata.web_server
  com.dreambuddy.datacenter
  com.dreambuddy.dc-scheduler
  com.dreambuddy.memory_cleanup
  com.dreambuddy.etl-worker
  com.dreambuddy.continual-training
  ai.hermes.gateway
  ai.hermes.dashboard
)
LAYER3_PATTERNS=(
  "ml_trade_service"
  "etl_worker.py"
)

bootout_labels() {
  for label in "$@"; do
    if launchctl bootout "gui/$UID_/$label" 2>/dev/null; then
      echo "   bootout: $label"
    elif launchctl unload "$PLIST_DIR/$label.plist" 2>/dev/null; then
      echo "   unload:  $label"
    else
      echo "   skip(未加载): $label"
    fi
  done
}

kill_patterns() {
  for pat in "$@"; do
    if pkill -f "$pat" 2>/dev/null; then
      echo "   kill: $pat"
    fi
  done
}

LAYER="${1:-all}"
case "$LAYER" in
  1)
    echo ">> Layer 1 看板"; bootout_labels "${LAYER1_LABELS[@]}"; kill_patterns "${LAYER1_PATTERNS[@]}" ;;
  2)
    echo ">> Layer 2 交易系统"; bootout_labels "${LAYER2_LABELS[@]}"; kill_patterns "${LAYER2_PATTERNS[@]}" ;;
  3)
    echo ">> Layer 3 研究/前端/数据冗余"; bootout_labels "${LAYER3_LABELS[@]}"; kill_patterns "${LAYER3_PATTERNS[@]}" ;;
  all)
    echo ">> Layer 1 看板"; bootout_labels "${LAYER1_LABELS[@]}"; kill_patterns "${LAYER1_PATTERNS[@]}"
    echo ">> Layer 2 交易系统"; bootout_labels "${LAYER2_LABELS[@]}"; kill_patterns "${LAYER2_PATTERNS[@]}"
    echo ">> Layer 3 研究/前端/数据冗余"; bootout_labels "${LAYER3_LABELS[@]}"; kill_patterns "${LAYER3_PATTERNS[@]}" ;;
  *) echo "用法: $0 [1|2|3|all]" >&2; exit 1 ;;
esac
echo ">> 完成。运行 ./status-local.sh 查看状态。"
