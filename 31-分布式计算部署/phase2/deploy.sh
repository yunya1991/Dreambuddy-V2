#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2 一键部署入口
# 目标: 易经数据服务(8765) + 产物中台(3456) + Nginx代理 + 前端重构建
# 用法: cd ~/dreambuddy && bash 31-分布式计算部署/phase2/deploy.sh
#
# 也可单独执行:
#   sudo bash 01-deploy-yijing-data-server.sh   # 8765 数据服务
#   sudo bash 02-deploy-product-hub.sh          # 3456 产物中台
#   sudo bash 03-nginx-update.sh                # Nginx 代理
#   sudo bash 04-rebuild-frontend.sh            # 前端重构建
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

echo "============================================"
echo "  Dreambuddy V2 — Phase 2 部署"
echo "  易经数据服务 + 产物中台 + 前端接入"
echo "============================================"
echo ""

echo ">>> [1/4] 部署易经数据服务 (8765)"
sudo bash 01-deploy-yijing-data-server.sh

echo ""
echo ">>> [2/4] 部署产物中台 (3456)"
sudo bash 02-deploy-product-hub.sh

echo ""
echo ">>> [3/4] 更新 Nginx 代理"
sudo bash 03-nginx-update.sh

echo ""
echo ">>> [4/4] 重新构建前端"
sudo bash 04-rebuild-frontend.sh

echo ""
echo "============================================"
echo "  ✓ Phase 2 部署完成"
echo "============================================"
echo ""
echo "  三屏趋势: https://<DOMAIN>/dashboard/three-screens"
echo "  BDSM快照: https://<DOMAIN>/dashboard/bdsm"
echo "  交易榜单: https://<DOMAIN>/dashboard/ranking"
echo ""
