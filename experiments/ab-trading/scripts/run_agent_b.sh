#!/bin/zsh
# Agent B 定时执行脚本（Dreambuddy OS）
# 用法：每1小时执行一次

set -e

REPO_DIR="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
WORK_DIR="$REPO_DIR/experiments/ab-trading"
LOG_DIR="$WORK_DIR/logs/agent_b"
ENV_FILE="$WORK_DIR/config/.env"

mkdir -p "$LOG_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/${TIMESTAMP}_run.log"

cd "$WORK_DIR"

# 加载环境变量
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent B (Dreambuddy OS) 开始执行" >> "$LOG_FILE"

python3 agents/agent_b_runner.py >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Agent B 执行完成，退出码: $EXIT_CODE" >> "$LOG_FILE"

exit $EXIT_CODE
