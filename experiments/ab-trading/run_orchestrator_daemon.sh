#!/bin/bash
# AB-Trading 记忆与SKILL驱动调度器 - 后台守护脚本
# 使用 --daemon 模式：每10分钟检查触发条件，常规4H执行 + 事件驱动 + Agent自主调度

SCRIPT_DIR="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading"
LOG_FILE="$SCRIPT_DIR/logs/orchestrator.log"

cd "$SCRIPT_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] AB-Trading 调度器守护进程启动 (--daemon模式)" >> "$LOG_FILE"

# --daemon 模式：内部循环，每10分钟检查触发条件
# 支持：常规4H心跳 / 市场波动触发 / Agent自主申请 / 重要事件窗口
/opt/anaconda3/bin/python3 "$SCRIPT_DIR/orchestrator.py" --daemon >> "$LOG_FILE" 2>&1
