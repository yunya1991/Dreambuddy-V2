#!/usr/bin/env bash
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
STATE_DIR="${SCRIPT_DIR}/data"
PYTHON="/opt/anaconda3/bin/python3"
SCRIPT="${SCRIPT_DIR}/screen_orchestrator.py"
MAIN_PID_FILE="${STATE_DIR}/screen_daemon_main.pid"
WATCH_PID_FILE="${STATE_DIR}/screen_daemon_watch.pid"
LOG_FILE="${LOG_DIR}/screen_daemon.log"
INTERVAL=600
MAX_RESTARTS=10
RESTART_WINDOW=3600

mkdir -p "${LOG_DIR}"
mkdir -p "${STATE_DIR}"

log() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*" | tee -a "${LOG_FILE}"
}

is_running() {
    local pid_file="$1"
    if [ -f "${pid_file}" ]; then
        local pid=$(cat "${pid_file}")
        if kill -0 "${pid}" 2>/dev/null; then
            return 0
        else
            rm -f "${pid_file}"
        fi
    fi
    return 1
}

run_worker() {
    local run_count=0
    local restart_times=()

    while true; do
        run_count=$((run_count + 1))
        log "[WORKER] --- 第 ${run_count} 次运行 ---"

        local start_ts=$(date +%s)
        if "${PYTHON}" "${SCRIPT}" >> "${LOG_FILE}" 2>&1; then
            local end_ts=$(date +%s)
            log "[WORKER] 执行完成，耗时 $((end_ts - start_ts))s"
        else
            local end_ts=$(date +%s)
            log "[WORKER] ⚠️ 执行失败 (退出码 $?)，耗时 $((end_ts - start_ts))s"
        fi

        local now=$(date +%s)
        restart_times=($(for t in "${restart_times[@]}"; do
            if [ $((now - t)) -lt "${RESTART_WINDOW}" ]; then
                echo "$t"
            fi
        done))

        if [ "${#restart_times[@]}" -ge "${MAX_RESTARTS}" ]; then
            log "[WORKER] ⚠️ ${RESTART_WINDOW}s 内重启超过 ${MAX_RESTARTS} 次，冷却 ${INTERVAL}s"
            sleep "${INTERVAL}"
            restart_times=()
        else
            sleep "${INTERVAL}" &
            wait $!
        fi
    done
}

run_watchdog() {
    echo $$ > "${WATCH_PID_FILE}"
    log "[WATCHDOG] 监控进程启动 (PID $$)"

    while true; do
        if ! is_running "${MAIN_PID_FILE}"; then
            log "[WATCHDOG] ⚠️ 主进程未运行，启动中..."
            run_worker &
            local worker_pid=$!
            echo "${worker_pid}" > "${MAIN_PID_FILE}"
            log "[WATCHDOG] ✅ 主进程已启动 (PID ${worker_pid})"
        fi
        sleep 30 &
        wait $!
    done
}

case "${1:-start}" in
    start)
        if is_running "${WATCH_PID_FILE}"; then
            local watch_pid=$(cat "${WATCH_PID_FILE}")
            log "守护进程已在运行 (监控 PID ${watch_pid})"
            exit 0
        fi
        log "启动三屏马丁守护进程..."
        run_watchdog &
        disown
        sleep 1
        if is_running "${WATCH_PID_FILE}"; then
            log "✅ 守护进程启动成功"
        else
            log "❌ 守护进程启动失败"
            exit 1
        fi
        ;;
    stop)
        log "停止守护进程..."
        if is_running "${MAIN_PID_FILE}"; then
            kill "$(cat "${MAIN_PID_FILE}")" 2>/dev/null || true
            rm -f "${MAIN_PID_FILE}"
            log "主进程已停止"
        fi
        if is_running "${WATCH_PID_FILE}"; then
            kill "$(cat "${WATCH_PID_FILE}")" 2>/dev/null || true
            rm -f "${WATCH_PID_FILE}"
            log "监控进程已停止"
        fi
        log "✅ 已停止"
        ;;
    status)
        echo "=== 三屏马丁守护进程状态 ==="
        if is_running "${WATCH_PID_FILE}"; then
            echo "监控进程: 运行中 (PID $(cat "${WATCH_PID_FILE}"))"
        else
            echo "监控进程: 未运行"
        fi
        if is_running "${MAIN_PID_FILE}"; then
            echo "工作进程: 运行中 (PID $(cat "${MAIN_PID_FILE}"))"
        else
            echo "工作进程: 未运行"
        fi
        echo ""
        echo "日志文件: ${LOG_FILE}"
        echo "最近日志:"
        tail -5 "${LOG_FILE}" 2>/dev/null || echo "(无日志)"
        ;;
    restart)
        "$0" stop
        sleep 1
        "$0" start
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
