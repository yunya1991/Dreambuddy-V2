#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
STATE_DIR="${SCRIPT_DIR}/data"
PYTHON="/opt/anaconda3/bin/python3"
SCRIPT="${SCRIPT_DIR}/screen_orchestrator.py"
PID_FILE="${STATE_DIR}/screen_watchdog.pid"
WATCHDOG_LOG="${LOG_DIR}/screen_watchdog.log"
INTERVAL=600

mkdir -p "${LOG_DIR}"
mkdir -p "${STATE_DIR}"

log() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" | tee -a "${WATCHDOG_LOG}"
}

if [ -f "${PID_FILE}" ]; then
    OLD_PID=$(cat "${PID_FILE}")
    if kill -0 "${OLD_PID}" 2>/dev/null; then
        log "看门狗已在运行 (PID ${OLD_PID})，退出"
        exit 0
    else
        log "清理旧 PID 文件 (PID ${OLD_PID} 不存在)"
        rm -f "${PID_FILE}"
    fi
fi

echo $$ > "${PID_FILE}"
log "看门狗启动 (PID $$)，间隔 ${INTERVAL}s"

cleanup() {
    log "看门狗收到退出信号，清理中..."
    rm -f "${PID_FILE}"
    exit 0
}
trap cleanup SIGTERM SIGINT SIGHUP

run_count=0
while true; do
    run_count=$((run_count + 1))
    log "--- 第 ${run_count} 次运行 ---"

    start_ts=$(date +%s)
    if "${PYTHON}" "${SCRIPT}" >> "${WATCHDOG_LOG}" 2>&1; then
        end_ts=$(date +%s)
        duration=$((end_ts - start_ts))
        log "执行完成，耗时 ${duration}s"
    else
        end_ts=$(date +%s)
        duration=$((end_ts - start_ts))
        log "⚠️ 执行失败 (退出码 $?)，耗时 ${duration}s"
    fi

    sleep "${INTERVAL}" &
    wait $!
done
