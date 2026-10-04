#!/bin/bash
# 启动真实 Chrome 浏览器（在 TRAE 沙箱外运行）
# 用法: ./start_chrome.sh [端口号] [用户数据目录]
#
# 为什么需要这个脚本？
# TRAE IDE 的文件系统沙箱限制了 Chrome 访问 ~/Library/Application Support/Google/Chrome/
# （Crashpad 崩溃报告目录）。在沙箱内启动 Chrome 会被沙箱拦截。
# 解决方案：在沙箱外（普通终端）启动 Chrome，然后通过 CDP 连接。

PORT=${1:-9222}
USER_DATA_DIR=${2:-"$HOME/chrome-real-env"}

echo "Starting Google Chrome with CDP on port $PORT"
echo "User data dir: $USER_DATA_DIR"

# 检查 Chrome 是否已在运行
if curl -s "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
    echo "✓ Chrome is already running with CDP on port $PORT"
    exit 0
fi

# 启动 Chrome
open -na "Google Chrome" --args \
    --remote-debugging-port="$PORT" \
    --user-data-dir="$USER_DATA_DIR" \
    --no-first-run \
    --no-default-browser-check

# 等待 CDP 就绪
echo "Waiting for Chrome CDP to be ready..."
for i in $(seq 1 15); do
    if curl -s "http://localhost:$PORT/json/version" > /dev/null 2>&1; then
        echo "✓ Chrome CDP is ready on port $PORT"
        echo "  CDP URL: http://localhost:$PORT"
        exit 0
    fi
    sleep 1
done

echo "✗ Chrome CDP failed to start within 15 seconds"
exit 1
