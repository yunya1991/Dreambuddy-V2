#!/bin/bash
# status-local.sh — 本地服务状态速查（只读，无副作用）
# 用法: ./status-local.sh
# 注: launchctl list 在本机看不到这些 agent，改用 launchctl print 逐个判定
set -uo pipefail
UID_="$(id -u)"

LABELS=(
  com.dreambuddy.yijing_data_server
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
  com.ft.strategy_gen.8095
  com.dreambuddy.datacenter
  com.dreambuddy.dc-scheduler
  com.dreambuddy.memory_cleanup
  com.dreambuddy.etl-worker
  com.dreambuddy.continual-training
  ai.hermes.gateway
  ai.hermes.dashboard
)

echo "===== 项目 LaunchAgents 状态 (launchctl print) ====="
for L in "${LABELS[@]}"; do
  out="$(launchctl print "gui/$UID_/$L" 2>&1)"
  if echo "$out" | grep -q "Could not find"; then
    printf "%-42s %s\n" "$L" "未加载"
  else
    st="$(echo "$out" | grep -m1 'state = ' | sed 's/^[[:space:]]*//;s/state = //')"
    ec="$(echo "$out" | grep -m1 'last exit code' | sed 's/^[[:space:]]*//;s/last exit code = //')"
    printf "%-42s %-18s %s\n" "$L" "${st:-?}" "${ec:+last-exit=$ec}"
  fi
done
echo ""
echo "===== 项目相关进程 ====="
ps aux | grep -iE "polling_trader|data_server_fixed|ml_trade|signal_scanner|trailing_stop|etl_worker|continual|yijing|v15|dreamos|hermes" | \
  grep -v grep | awk '{printf "pid=%-7s ", $2; for(i=11;i<=NF&&i<=14;i++) printf "%s ", $i; print ""}' || echo "(无)"
echo ""
echo "===== 业务端口监听 ====="
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -E ":(3001|3002|3456|8125|8765|8770|8771|8092|8093|8094|8095|8096|9094|9119)" || echo "(业务端口无监听)"
echo ""
echo "===== 保留项(应仍在) ====="
launchctl list 2>/dev/null | grep -E "evolution_scheduler|dbsync|cognitive" || echo "(launchd 未加载 — 训练 oneshot 为按需运行属正常)"
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -E ":(5432|6379|11434)" | awk '{print $1, $9}'
