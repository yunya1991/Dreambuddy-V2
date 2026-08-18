#!/bin/bash
# 三屏趋势系统 — 服务启动脚本
# 用 nohup 守护进程替代 launchd（沙箱环境兼容）

TREND_SYSTEM="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统"
EXECUTOR_DIR="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading"
PYTHON="/opt/anaconda3/bin/python3"
LOG_DIR_TREND="$TREND_SYSTEM/logs"
LOG_DIR_EXEC="$EXECUTOR_DIR/logs"

mkdir -p "$LOG_DIR_TREND" "$LOG_DIR_EXEC"

# ===== 1. 启动信号池扫描器（守护进程，每5分钟扫描）=====
echo "[1/2] 启动信号池扫描器..."
pkill -f "scanner.py --daemon" 2>/dev/null
sleep 1
nohup "$PYTHON" "$TREND_SYSTEM/signal_pool/scanner.py" --daemon --interval 300 \
    > "$LOG_DIR_TREND/signal_scanner.log" 2>&1 &
SCANNER_PID=$!
echo "  PID: $SCANNER_PID"
echo "  日志: $LOG_DIR_TREND/signal_scanner.log"
echo "  模式: 守护进程，每300秒扫描一次"

# ===== 2. 启动执行器定时循环（每60秒执行一次）=====
echo "[2/2] 启动执行器定时循环..."
pkill -f "screen_executor.py.*run.*scheduled" 2>/dev/null
sleep 1

# 执行器循环脚本（内嵌）
nohup bash -c '
while true; do
    /opt/anaconda3/bin/python3 /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_executor.py run scheduled 2>&1
    sleep 60
done
' > "$LOG_DIR_EXEC/trend_executor_loop.log" 2>&1 &
EXECUTOR_PID=$!
echo "  PID: $EXECUTOR_PID"
echo "  日志: $LOG_DIR_EXEC/trend_executor_loop.log"
echo "  模式: 每60秒执行一次交易检查"

echo ""
echo "=== 服务已启动 ==="
echo "  信号扫描器: PID $SCANNER_PID (每5分钟刷新信号池)"
echo "  交易执行器: PID $EXECUTOR_PID (每60秒检查交易信号)"
echo ""
echo "停止服务: pkill -f 'scanner.py --daemon'; pkill -f 'screen_executor.py.*run.*scheduled'"
