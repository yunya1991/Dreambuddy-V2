#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2: 产物中台 (port 3456) 部署
# 作用: 交易榜单 Next.js 应用，供前端 /dashboard/ranking 页面调用
# 用法: sudo bash 02-deploy-product-hub.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
HUB_DIR="${REPO_DIR}/7-产物中台/系统研究索引体系"
LOG_DIR="/home/${DEPLOY_USER}/logs/product-hub"

echo "============================================"
echo "  Phase 2 — 产物中台 (3456) 部署"
echo "============================================"

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. 安装依赖
echo ">>> [1/3] 安装依赖"
cd "${HUB_DIR}"
sudo -u "${DEPLOY_USER}" npm install --no-audit --no-fund 2>&1 | tail -3

# 3. Build
echo ">>> [2/3] 构建 (next build)"
sudo -u "${DEPLOY_USER}" npm run build 2>&1 | tail -10

# 4. 启动 (PM2)
echo ">>> [3/3] 启动服务 (PM2)"
pm2 delete product-hub 2>/dev/null || true
pm2 start npm --name product-hub -- start -- \
    -- -p 3456 \
    -o "${LOG_DIR}/out.log" \
    -e "${LOG_DIR}/err.log"
pm2 save

sleep 5

# 5. 验证
echo ""
echo "=== 服务状态 ==="
pm2 list | grep product-hub

echo "=== 端口监听 ==="
ss -tlnp | grep 3456 || echo "⚠️  3456 未监听"

echo "=== API 测试 ==="
curl -s -m 10 "http://127.0.0.1:3456/api/trading-ranking/health" 2>&1 | head -c 200
echo ""

echo ""
echo "============================================"
echo "  ✓ 产物中台部署完成"
echo "  日志: ${LOG_DIR}/"
echo "  命令: pm2 logs product-hub"
echo "============================================"
