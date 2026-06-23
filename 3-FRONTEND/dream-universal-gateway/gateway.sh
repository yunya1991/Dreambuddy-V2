#!/bin/bash
# Dream Universal Gateway 管理脚本
# Dream Gateway Management Script

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT=3000
LOG_FILE="/tmp/dreambuddy.log"
PID_FILE=".dreambuddy.pid"

case "$1" in
  start)
    # 检查是否已在运行
    if lsof -i :$PORT > /dev/null 2>&1; then
      echo "⚠️  Gateway 已在端口 $PORT 上运行"
      exit 1
    fi

    # 检查是否已构建
    if [ ! -d ".next" ]; then
      echo "📦 首次运行，正在构建..."
      pnpm run build
    fi

    echo "🚀 启动 Dream Gateway..."
    pnpm run start > "$LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    sleep 5
    
    if lsof -i :$PORT > /dev/null 2>&1; then
      echo "✅ Dream Gateway 已启动 (PID: $PID)"
      echo "   Dashboard: http://localhost:$PORT/dashboard"
      echo "   日志: $LOG_FILE"
    else
      echo "❌ 启动失败，请查看日志: $LOG_FILE"
    fi
    ;;

  stop)
    if [ -f "$PID_FILE" ]; then
      PID=$(cat "$PID_FILE")
      if kill -0 $PID 2>/dev/null; then
        echo "🛑 停止 Dream Gateway (PID: $PID)..."
        kill $PID
        rm -f "$PID_FILE"
        echo "✅ 已停止"
      else
        echo "⚠️  PID 文件存在但进程已不存在"
        rm -f "$PID_FILE"
      fi
    else
      PIDS=$(pgrep -f "next start -p $PORT")
      if [ -n "$PIDS" ]; then
        echo "🛑 停止 Dream Gateway..."
        pkill -f "next start -p $PORT"
        echo "✅ 已停止"
      else
        echo "ℹ️  Gateway 未运行"
      fi
    fi
    ;;

  status)
    echo "🔍 Dream Gateway 状态检查"
    echo "========================="
    if lsof -i :$PORT > /dev/null 2>&1; then
      echo "✅ 服务状态: 运行中"
      lsof -i :$PORT | tail -1
    else
      echo "❌ 服务状态: 未运行"
    fi
    echo ""
    echo "🌐 访问地址:"
    echo "   Dashboard: http://localhost:$PORT/dashboard"
    echo "   登录页: http://localhost:$PORT/login"
    ;;

  log)
    if [ -f "$LOG_FILE" ]; then
      tail -20 "$LOG_FILE"
    else
      echo "ℹ️  日志文件不存在"
    fi
    ;;

  *)
    echo "用法: $0 {start|stop|status|log}"
    echo ""
    echo "命令:"
    echo "  start   - 启动服务"
    echo "  stop    - 停止服务"
    echo "  status  - 查看状态"
    echo "  log     - 查看最近日志"
    exit 1
    ;;
esac
