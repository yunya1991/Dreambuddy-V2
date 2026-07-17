#!/bin/bash

cd "$(dirname "$0")/../.."

mkdir -p logs

echo "启动易经推理轮询交易器..."
echo "配置: 29币种(含SPX/XAU TradFi) | 1小时间隔 | 置信度0.55 | 最大持仓10 | BCRM 2.0 (辩证ML引擎) | 逐仓模式(独立保证金) | 易经专属离场层"
echo "日志: logs/trading_stdout.log"

nohup env FEISHU_APP_ID="cli_aa9442bde4b89be9" FEISHU_APP_SECRET="dnHO43AQ68jua7Z8XEAQ3gJwNoMeYQ70" /opt/anaconda3/bin/python3 -m scripts.memory_l4.polling_trader \
    --interval 3600 \
    --coins BTC,ETH,SOL,BNB,XRP,DOGE,ADA,AVAX,LINK,LTC,DOT,NEAR,ATOM,UNI,APT,FIL,ARB,OP,INJ,SUI,SEI,TIA,AAVE,LDO,STX,IMX,GRT,SPX,XAU \
    --confidence 0.55 \
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