#!/bin/bash
# AB-Trading 记忆与SKILL驱动调度器 - 后台守护脚本
# 每4小时执行一次 orchestrator.py

SCRIPT_DIR="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading"
LOG_FILE="$SCRIPT_DIR/logs/orchestrator.log"

cd "$SCRIPT_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 AB-Trading 调度器守护进程启动" >> "$LOG_FILE"

while true; do
    # 执行 orchestrator
    /opt/anaconda3/bin/python3 "$SCRIPT_DIR/orchestrator.py" >> "$LOG_FILE" 2>&1

    # 记录执行完成
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⏳ 等待4小时后再次执行..." >> "$LOG_FILE"

    # 等待4小时 (14400秒)
    sleep 14400
done