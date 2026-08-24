#!/bin/bash
# ============================================================
#  polling_trader LIVE 配置（加密货币 300s 轮询）启动包装脚本
#  由 launchd plist 调用：com.dreambuddy.yijing_live_300s
#  参数同用户周六手动启动的 LIVE 配置：
#    --interval 300 --confidence 0.7955 --max-positions 5 --position-pct 0.20
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
# 清心跳锁（ProcessGuardian 互斥 → launchd 已接管保活，避免拒绝启动）
rm -f "$GUARDIAN_DIR/heartbeat.json"

# 若存在旧 trader.pid 指向的存活进程 → 软杀2s后硬杀
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if /bin/ps -p "$OLD_PID" -o comm= 2>/dev/null | /usr/bin/grep -q "python"; then
    echo "[$(date '+%F %T')] [live_300s.sh] 清旧 PID=$OLD_PID" >> "$LOG_DIR/daemon_watch.log"
    kill -TERM "$OLD_PID" 2>/dev/null || true
    sleep 2
    kill -KILL "$OLD_PID" 2>/dev/null || true
  fi
fi

cd "$PROJ" || exit 2

{
  echo ""
  echo "=========================================================================="
  echo "[$(date '+%F %T')] [live_300s.sh] >>> 启动 polling_trader LIVE(300s) | cwd=$PWD"
  echo "=========================================================================="
} >> "$LOG_DIR/polling_trader_stdout.log"

# 环境变量：代理 + 飞书密钥（与之前手动启动时完全一致）
export HTTPS_PROXY="http://127.0.0.1:7890"
export HTTP_PROXY="http://127.0.0.1:7890"
export FEISHU_APP_ID="cli_aa9442bde4b89be9"
export FEISHU_APP_SECRET="dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"
export PYTHONUNBUFFERED=1

exec "$PYTHON" -u -m scripts.memory_l4.polling_trader \
  --no-guardian \
  --interval 300 \
  --confidence 0.7955 \
  --max-positions 5 \
  --position-pct 0.20 \
  >> "$LOG_DIR/trading_screen.log" \
  2>> "$LOG_DIR/trading_screen_stderr.log"
