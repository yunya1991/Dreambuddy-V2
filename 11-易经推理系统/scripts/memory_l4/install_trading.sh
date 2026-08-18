#!/bin/bash

echo "============================================"
echo "  易经推理交易系统 - 完整安装脚本"
echo "============================================"
echo ""

BASE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_FILE="$BASE_DIR/scripts/memory_l4/com.yijing.trading.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "[1/5] 创建日志目录..."
mkdir -p "$BASE_DIR/logs"
echo "✅ 日志目录已创建"

echo ""
echo "[2/5] 设置启动脚本权限..."
chmod +x "$BASE_DIR/scripts/memory_l4/start_trading.sh"
echo "✅ 启动脚本权限已设置"

echo ""
echo "[3/5] 安装 LaunchAgent..."
mkdir -p "$LAUNCH_AGENTS_DIR"

if [ -f "$PLIST_FILE" ]; then
    cp "$PLIST_FILE" "$LAUNCH_AGENTS_DIR/"
    echo "✅ plist 文件已复制到 $LAUNCH_AGENTS_DIR"
else
    echo "❌ plist 文件不存在: $PLIST_FILE"
    exit 1
fi

echo ""
echo "[4/5] 加载 LaunchAgent..."
launchctl load "$LAUNCH_AGENTS_DIR/com.yijing.trading.plist"
if [ $? -eq 0 ]; then
    echo "✅ LaunchAgent 加载成功"
else
    echo "⚠️ 加载失败，尝试强制加载..."
    launchctl unload "$LAUNCH_AGENTS_DIR/com.yijing.trading.plist" 2>/dev/null
    launchctl load "$LAUNCH_AGENTS_DIR/com.yijing.trading.plist"
    if [ $? -eq 0 ]; then
        echo "✅ LaunchAgent 强制加载成功"
    else
        echo "❌ LaunchAgent 加载失败，请手动执行:"
        echo "   launchctl load ~/Library/LaunchAgents/com.yijing.trading.plist"
    fi
fi

echo ""
echo "[5/5] 验证安装..."
sleep 3
launchctl list | grep com.yijing.trading
if [ $? -eq 0 ]; then
    echo "✅ LaunchAgent 已注册"
else
    echo "⚠️ LaunchAgent 未在列表中"
fi

echo ""
echo "检查交易器进程..."
pgrep -f "polling_trader"
if [ $? -eq 0 ]; then
    echo "✅ 交易器进程运行中"
else
    echo "❌ 交易器进程未运行，正在启动..."
    "$BASE_DIR/scripts/memory_l4/start_trading.sh"
fi

echo ""
echo "============================================"
echo "  安装完成！"
echo "============================================"
echo ""
echo "交易器配置:"
echo "  - 轮询间隔: 1小时"
echo "  - 交易币种: BTC, ETH, SOL, BNB, XRP, DOGE"
echo "  - 置信度阈值: 0.35"
echo "  - 最大持仓: 5个"
echo ""
echo "日志文件:"
echo "  - $BASE_DIR/logs/trading_stdout.log"
echo "  - $BASE_DIR/logs/trading_stderr.log"
echo ""
echo "常用命令:"
echo "  查看状态: launchctl list | grep com.yijing.trading"
echo "  停止服务: launchctl unload ~/Library/LaunchAgents/com.yijing.trading.plist"
echo "  手动启动: $BASE_DIR/scripts/memory_l4/start_trading.sh"
echo "  查看日志: tail -f $BASE_DIR/logs/trading_stdout.log"