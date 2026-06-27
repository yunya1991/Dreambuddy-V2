#!/bin/zsh
# Agent A 定时执行脚本
# 用法：每4小时执行一次

set -e

REPO_DIR="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
WORK_DIR="$REPO_DIR/experiments/ab-trading"
LOG_DIR="$WORK_DIR/logs/agent_a"
ENV_FILE="$WORK_DIR/config/.env"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/${TIMESTAMP}_run.log"

cd "$WORK_DIR"

# 加载环境变量
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent A 开始执行" >> "$LOG_FILE"

python3 agents/agent_a_runner.py >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent A 执行完成，退出码: $EXIT_CODE" >> "$LOG_FILE"

exit $EXIT_CODE
