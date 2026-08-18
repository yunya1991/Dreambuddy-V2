#!/bin/bash
# ml_trade_service 守护进程 —— 进程挂了自动拉起
# 用法: bash ops/launchd/watchdog_8092.sh &

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PORT=8092
LOG_FILE="${PROJECT_DIR}/user_data/logs/ml_trade_service_8092.log"
PID_FILE="${PROJECT_DIR}/user_data/logs/ml_trade_service_8092.pid"
CHECK_INTERVAL=5

mkdir -p "$(dirname "$LOG_FILE")"

echo "[watchdog] starting, project=${PROJECT_DIR}, port=${PORT}" >> "${LOG_FILE}.watchdog"

while true; do
  if ! lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')][watchdog] service down, restarting..." >> "${LOG_FILE}.watchdog"

    cd "${PROJECT_DIR}"
    ML_USER_DATA_DIR="${PROJECT_DIR}/user_data" \
    nohup python3 ml_trade_service.py >> "${LOG_FILE}" 2>&1 &
    NEW_PID=$!
    echo "${NEW_PID}" > "${PID_FILE}"

    sleep 3
    if lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')][watchdog] restarted ok, pid=${NEW_PID}" >> "${LOG_FILE}.watchdog"
    else
      echo "[$(date '+%Y-%m-%d %H:%M:%S')][watchdog] restart failed" >> "${LOG_FILE}.watchdog"
    fi
  fi
  sleep "${CHECK_INTERVAL}"
done
