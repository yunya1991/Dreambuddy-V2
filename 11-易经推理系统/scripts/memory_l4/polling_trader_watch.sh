#!/bin/bash
# ============================================================
#  polling_trader 启动包装脚本（给 launchd 调用）
#  功能：
#    1. 进入正确 cwd 并设置 env
#    2. 启动前清旧心跳锁 + 杀孤儿进程
#    3. 启动失败 / 进程退出 5s 内会被 launchd 自动重新起
#    4. 日志分文件（stdout + stderr），每次启动追加
# ============================================================
set -u

PROJ="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统"
PYTHON="/opt/anaconda3/bin/python3"
LOG_DIR="$PROJ/logs"
GUARDIAN_DIR="$PROJ/.workbuddy/memory_l4/guardian"
PID_FILE="$LOG_DIR/trader.pid"

mkdir -p "$LOG_DIR"
mkdir -p "$GUARDIAN_DIR"

# ---------- 启动前清理 ----------
# 清心跳锁（本脚本已用 launchd 做保活，ProcessGuardian 互斥反而会导致拒绝启动）
rm -f "$GUARDIAN_DIR/heartbeat.json"

# 若存在旧 trader.pid 指向的存活进程，且它是我们前一版自己起的 → 尝试先软杀 2s 后硬杀
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if /bin/ps -p "$OLD_PID" -o comm= 2>/dev/null | /usr/bin/grep -q "python"; then
    echo "[$(date '+%F %T')] [watch.sh] 清旧 PID=$OLD_PID" >> "$LOG_DIR/daemon_watch.log"
    kill -TERM "$OLD_PID" 2>/dev/null || true
    sleep 2
    kill -KILL "$OLD_PID" 2>/dev/null || true
  fi
fi

# ---------- 进入项目目录 + 写启动元数据 ----------
cd "$PROJ" || exit 2

{
  echo ""
  echo "=========================================================================="
  echo "[$(date '+%F %T')] [watch.sh] >>> 启动 polling_trader (restart #$(/bin/ps -axo pid,command | /usr/bin/grep -c '[p]olling_trader' 2>/dev/null), cwd=$PWD)"
  echo "=========================================================================="
} >> "$LOG_DIR/polling_trader_stdout.log"

# ---------- 启动 trader：--no-guardian 让 launchd 接管保活 ----------
export PYTHONUNBUFFERED=1
exec "$PYTHON" -u -m scripts.memory_l4.polling_trader \
  --no-guardian \
  --interval 3600 \
  --coins "MU,SNDK,XAG,XAU,BTC,ETH,SOL,NVDA,GOOGL,AMZN" \
  --bar "1H" \
  --confidence 0.35 \
  --max-positions 3 \
  >> "$LOG_DIR/polling_trader_stdout.log" \
  2>> "$LOG_DIR/polling_trader_stderr.log"
