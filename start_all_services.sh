#!/bin/bash
# Dream OS 交易系统 - 统一启动脚本
# 用途: 启动所有关键交易服务 (launchd 替代方案)
# 用法: ./start_all_services.sh [start|stop|status]

PROJECT_ROOT="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
PYTHON="/opt/anaconda3/bin/python3"
PID_DIR="$PROJECT_ROOT/.run"
LOG_DIR="$PROJECT_ROOT/logs"

mkdir -p "$PID_DIR" "$LOG_DIR"

# ── 服务定义 ──────────────────────────────────────────────
# 格式: "名称|工作目录|命令|日志文件"
SERVICES=(
  "dreamos_scheduler|$PROJECT_ROOT/1-ARCHITECTURE/dreamos|$PYTHON $PROJECT_ROOT/1-ARCHITECTURE/dreamos/cli/start_scheduler.py|$LOG_DIR/dreamos_scheduler.log"
  "yijing_polling_trader|$PROJECT_ROOT/11-易经推理系统|$PYTHON -m scripts.memory_l4.polling_trader --interval 3600 --coins BTC,ETH,SOL,BNB,XRP,ADA,AVAX,NEAR,SUI,APT,DOT,ATOM,LTC,LINK,ARB,OP,UNI,AAVE,DOGE,PEPE,NVDA,TSLA,MSFT,META,GOOGL,AAPL,AMZN,COIN,XAU,XAG --confidence 0.70 --max-positions 5 --position-pct 0.10|$LOG_DIR/yijing_polling_trader.log"
  "v15_orchestrator|$PROJECT_ROOT/14-V15经典马丁策略|bash -c 'while true; do $PYTHON run.py orchestrator >> logs/orchestrator.log 2>&1; sleep 900; done'|$LOG_DIR/v15_orchestrator_daemon.log"
  "v15_light_poll|$PROJECT_ROOT/14-V15经典马丁策略|bash -c 'while true; do $PYTHON run.py poll_light >> logs/v15_light_poll.log 2>&1; sleep 300; done'|$LOG_DIR/v15_light_poll_daemon.log"
  "cognitive_daemon|$PROJECT_ROOT|$PYTHON -u $PROJECT_ROOT/4-MEMORY/9-工具与接口/cognitive_daemon.py --watch . --interval 5 --debounce 8 --verbose|$LOG_DIR/cognitive_daemon.log"
  "dynamic_evaluator|$PROJECT_ROOT/1-ARCHITECTURE|$PYTHON -m dreamos.cli.run_dynamic_evaluator --interval 21600 --log-level INFO|$LOG_DIR/dynamic_evaluator.log"
)

# ── 函数 ──────────────────────────────────────────────────

is_running() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    local pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

start_service() {
  local name="$1"
  local workdir="$2"
  local cmd="$3"
  local logfile="$4"
  local pid_file="$PID_DIR/$name.pid"

  if is_running "$pid_file"; then
    echo "[SKIP] $name 已在运行 (PID: $(cat "$pid_file"))"
    return 0
  fi

  cd "$workdir"
  nohup bash -c "$cmd" >> "$logfile" 2>&1 &
  local pid=$!
  echo "$pid" > "$pid_file"
  sleep 2

  if kill -0 "$pid" 2>/dev/null; then
    echo "[OK] $name 启动成功 (PID: $pid)"
  else
    echo "[FAIL] $name 启动失败"
    rm -f "$pid_file"
  fi
}

stop_service() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"

  if is_running "$pid_file"; then
    local pid=$(cat "$pid_file")
    kill "$pid" 2>/dev/null
    sleep 2
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null
    fi
    echo "[OK] $name 已停止 (PID: $pid)"
  else
    echo "[SKIP] $name 未运行"
  fi
  rm -f "$pid_file"
}

status_service() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"

  if is_running "$pid_file"; then
    local pid=$(cat "$pid_file")
    echo "[RUNNING] $name (PID: $pid)"
  else
    echo "[STOPPED] $name"
  fi
}

# ── 主逻辑 ────────────────────────────────────────────────

case "${1:-start}" in
  start)
    echo "=== Dream OS 交易系统启动 ==="
    echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    for svc in "${SERVICES[@]}"; do
      IFS='|' read -r name workdir cmd logfile <<< "$svc"
      start_service "$name" "$workdir" "$cmd" "$logfile"
    done
    echo ""
    echo "=== 启动完成 ==="
    ;;

  stop)
    echo "=== 停止 Dream OS 交易系统 ==="
    for svc in "${SERVICES[@]}"; do
      IFS='|' read -r name workdir cmd logfile <<< "$svc"
      stop_service "$name"
    done
    echo ""
    echo "=== 停止完成 ==="
    ;;

  status)
    echo "=== Dream OS 交易系统状态 ==="
    echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    for svc in "${SERVICES[@]}"; do
      IFS='|' read -r name workdir cmd logfile <<< "$svc"
      status_service "$name"
    done
    ;;

  restart)
    $0 stop
    sleep 3
    $0 start
    ;;

  *)
    echo "用法: $0 {start|stop|status|restart}"
    exit 1
    ;;
esac
