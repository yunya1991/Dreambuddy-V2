#!/bin/bash
# 用 screen 启动独立会话运行交易进程，避免工具会话退出导致进程终止
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统

export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export FEISHU_APP_ID="cli_aa9442bde4b89be9"
export FEISHU_APP_SECRET="dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"

mkdir -p logs

# 杀掉旧进程和旧 screen 会话
pkill -f "scripts.memory_l4.polling_trader" 2>/dev/null
screen -S yijing_trading -X quit 2>/dev/null
sleep 2

# 用 screen 启动 detached 会话
screen -dmS yijing_trading bash -c '
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
export FEISHU_APP_ID="cli_aa9442bde4b89be9"
export FEISHU_APP_SECRET="dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70"
exec /opt/anaconda3/bin/python3 -u -m scripts.memory_l4.polling_trader \
    --interval 300 \
    --confidence 0.7955 \
    --max-positions 5 \
    --position-pct 0.20 \
    > logs/trading_screen.log 2>&1
'

sleep 3
echo "screen 会话状态:"
screen -ls 2>/dev/null | grep yijing || echo "无 yijing 会话"
echo "进程状态:"
ps aux | grep polling_trader | grep -v grep | awk '{print "PID="$2" CPU="$3"% MEM="$4"%"}' || echo "进程未运行"
