#!/bin/bash

cd "$(dirname "$0")/../.."

mkdir -p logs

echo "启动易经推理轮询交易器..."
echo "配置: 6币种(BTC/ETH/SOL/BNB/XRP/DOGE) | 1小时间隔 | 置信度0.35"
echo "日志: logs/trading_stdout.log"

nohup python3 -m scripts.memory_l4.polling_trader \
    --interval 3600 \
    --coins BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,LINK,LTC,DOT,NEAR,ATOM,UNI,APT,FIL,ARB,OP,INJ,SUI,SEI,TIA,AAVE,LDO,STX,IMX,GRT,SPX,XAU \
    --confidence 0.35 \
    --max-positions 10 \
    --position-pct 0.10 \
    > logs/trading_stdout.log 2>&1 &

PID=$!
echo "交易器已启动 (PID: $PID)"
echo "PID写入: .workbuddy/memory_l4/guardian/trader_pid.txt"
echo $PID > .workbuddy/memory_l4/guardian/trader_pid.txt

sleep 3
echo "检查启动状态..."
if ps -p $PID > /dev/null; then
    echo "✅ 交易器运行中"
else
    echo "❌ 交易器启动失败，请检查日志"
    cat logs/trading_stdout.log
fi