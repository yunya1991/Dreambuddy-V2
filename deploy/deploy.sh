#!/bin/bash
# ============================================================
# 6-TRADING 腾讯云一键部署
# 用法:
#   1. scp deploy/ luke@<云IP>:/home/luke/tmp/
#   2. scp .env luke@<云IP>:/home/luke/.hermes/.env
#   3. ssh luke@<云IP>
#   4. cd /home/luke/tmp/deploy && sudo bash deploy.sh
# ============================================================
set -e

echo "============================================"
echo "  6-TRADING 腾讯云一键部署"
echo "============================================"
echo ""

# Phase 1: 依赖
echo ">>> Phase 1/3: 安装依赖"
bash "$(dirname "$0")/01-install-deps.sh"

# Phase 2: 代码 + 配置
echo ""
echo ">>> Phase 2/3: 部署代码"
bash "$(dirname "$0")/02-clone-and-config.sh"

# Phase 3: 服务
echo ""
echo ">>> Phase 3/3: 启动服务"
bash "$(dirname "$0")/03-systemd-services.sh"

echo ""
echo "============================================"
echo "  部署完成！"
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):9119"
echo "  日志:      tail -f /home/luke/.hermes/logs/gateway.log"
echo "============================================"
