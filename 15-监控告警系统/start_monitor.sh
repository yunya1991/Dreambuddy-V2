#!/bin/bash
# 统一监控告警系统启动脚本

cd "$(dirname "$0")"

export FEISHU_APP_ID="cli_aa9442bde4b89be9"
export FEISHU_APP_SECRET="dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"

LOG_FILE="../logs/monitor_scheduler.log"

echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] 启动统一监控告警系统..." >> "$LOG_FILE"

nohup /opt/anaconda3/bin/python3 scheduler.py >> "$LOG_FILE" 2>&1 &

PID=$!
echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] 监控调度器已启动，PID=$PID" >> "$LOG_FILE"

echo "监控调度器已启动，PID=$PID"
echo "日志文件: $LOG_FILE"
