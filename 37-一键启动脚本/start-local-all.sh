#!/bin/bash
# start-local-all.sh — 一键恢复本地全量 LaunchAgents（分层暂停的逆操作）
# 用法: ./start-local-all.sh
# 注意: 只恢复"分层暂停清单"内的 agents；训练/治理类从未停过，无需恢复
set -euo pipefail
UID_="$(id -u)"
PLIST_DIR="$HOME/Library/LaunchAgents"

LABELS=(
  # Layer 1 看板
  com.dreambuddy.yijing_data_server
  # Layer 2 交易系统
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
  # Layer 3 研究/前端/数据
  # 注: 原 com.ft.dashboard.3001 / com.ft.ml_trade_service.{explore,pilot,prod,8092}
  #     / com.ft.explore.ml_trade_service / com.ft.fundamental_research_sync
  #     / com.ft_userdata.web_server 指向已废弃的 ft_userdata/经典指标机器学习系统,
  #     于 2026-10-16 归档至 ~/Library/LaunchAgents/_archived_legacy_ftuserdata_20261016/
  com.ft.strategy_gen.8095
  com.dreambuddy.datacenter
  com.dreambuddy.dc-scheduler
  com.dreambuddy.memory_cleanup
  com.dreambuddy.etl-worker
  com.dreambuddy.continual-training
  ai.hermes.gateway
  ai.hermes.dashboard
)

echo ">> 恢复本地 LaunchAgents..."
OK=0; FAIL=0
for label in "${LABELS[@]}"; do
  plist="$PLIST_DIR/$label.plist"
  if [ ! -f "$plist" ]; then
    echo "   skip(无 plist): $label"; continue
  fi
  # bootstrap 对已加载的 agent 会返回 "already bootstrapped"，故不以其返回码判定
  launchctl bootstrap "gui/$UID_" "$plist" >/dev/null 2>&1 || true
  # 用 launchctl print 作为真实判据（launchctl list 在本机不可靠）
  if launchctl print "gui/$UID_/$label" >/dev/null 2>&1; then
    echo "   OK: $label"; OK=$((OK+1))
  else
    echo "   ⚠️ 失败: $label"; FAIL=$((FAIL+1))
  fi
done
echo ">> 完成: 成功 $OK / 失败 $FAIL 。运行 ./status-local.sh 核验。"
[ "$FAIL" = "0" ]
