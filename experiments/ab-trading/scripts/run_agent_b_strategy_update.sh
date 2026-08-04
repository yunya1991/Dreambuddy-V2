#!/bin/bash
# Agent B 策略参数更新 — launchd 调用入口
# 每日 02:00 由 com.dreambuddy.agent-b-strategy-update 触发
set -e
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
/opt/homebrew/bin/python3 -c "from agents.agent_b_runner import update_classic_strategy_params; update_classic_strategy_params()"
