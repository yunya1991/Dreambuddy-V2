#!/bin/bash
# Agent B 策略参数优化定时任务脚本
# 每日凌晨2点执行，基于 Agent B 记忆模块和经典技术指标驱动策略参数优化
# 日志输出: logs/agent_b.log

cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading || exit 1

/opt/homebrew/bin/python3 -c "from agents.agent_b_runner import update_classic_strategy_params; update_classic_strategy_params()"
