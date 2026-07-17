#!/bin/bash

# Dream OS BCRM 2.0 升级版自动调度器启动脚本
# 使用方式:
#   ./start_dreamos_scheduler.sh run_once    # 单次扫描
#   ./start_dreamos_scheduler.sh scheduled   # 定时调度(每小时)
#   ./start_dreamos_scheduler.sh status      # 查看状态

set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
PYTHONPATH="$PROJECT_DIR/1-ARCHITECTURE:$PYTHONPATH"
LOG_DIR="$SCRIPT_DIR/logs"
PID_FILE="$LOG_DIR/dreamos_scheduler.pid"
LOG_FILE="$LOG_DIR/dreamos_scheduler.log"

mkdir -p "$LOG_DIR"

export PYTHONPATH

run_once() {
    echo "🚀 启动 Dream OS BCRM 2.0 单次扫描..."
    cd "$SCRIPT_DIR"
    python cli/dreamos_full_scheduler.py --mode run_once --dry-run --log-level INFO
}

start_scheduled() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "⚠️ 调度器已在运行 (PID: $PID)"
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    
    echo "🚀 启动 Dream OS BCRM 2.0 定时调度器..."
    cd "$SCRIPT_DIR"
    nohup python cli/dreamos_full_scheduler.py --mode scheduled --dry-run --log-level INFO > "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    echo "✅ 调度器已启动 (PID: $PID)"
    echo "日志文件: $LOG_FILE"
}

stop_scheduler() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "🛑 停止调度器 (PID: $PID)..."
            kill "$PID"
            sleep 2
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID"
            fi
        fi
        rm -f "$PID_FILE"
        echo "✅ 调度器已停止"
    else
        echo "⚠️ 调度器未运行"
    fi
}

show_status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "✅ 调度器正在运行 (PID: $PID)"
            echo "日志文件: $LOG_FILE"
            echo ""
            echo "最近10条日志:"
            tail -10 "$LOG_FILE"
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    echo "🛑 调度器未运行"
}

show_help() {
    echo "Dream OS BCRM 2.0 升级版自动调度器"
    echo ""
    echo "用法:"
    echo "  ./start_dreamos_scheduler.sh <命令>"
    echo ""
    echo "命令:"
    echo "  run_once    - 执行单次扫描(10个币种)"
    echo "  scheduled   - 启动定时调度(每小时执行一次)"
    echo "  stop        - 停止调度器"
    echo "  status      - 查看调度器状态"
    echo "  tail        - 查看实时日志"
    echo "  help        - 显示帮助"
    echo ""
    echo "支持币种: BTC, ETH, SOL, AVAX, LINK, DOT, MATIC, BNB, OP, ARB"
    echo "核心功能: WDH时间特征 + 美林时钟 + 增量学习闭环"
}

case "${1:-}" in
    run_once)
        run_once
        ;;
    scheduled)
        start_scheduled
        ;;
    stop)
        stop_scheduler
        ;;
    status)
        show_status
        ;;
    tail)
        tail -f "$LOG_FILE"
        ;;
    help)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac