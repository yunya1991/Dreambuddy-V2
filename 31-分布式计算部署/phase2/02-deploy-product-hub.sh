#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2: 产物中台 (port 3456) 部署
# 作用: 交易榜单 Next.js 应用，供前端 /dashboard/ranking 页面调用
# 用法: sudo bash 02-deploy-product-hub.sh
# 说明: 远端统一使用 systemd 托管（不再使用 pm2）
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
HUB_DIR="${REPO_DIR}/7-产物中台/系统研究索引体系"
LOG_DIR="/home/${DEPLOY_USER}/logs/product-hub"

# PostgreSQL 连接（dreambuddy-pg docker 容器）
DB_URL="${HUB_DATABASE_URL:-postgresql://dreambuddy:xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE@127.0.0.1:5432/dreambuddy?schema=public}"

echo "============================================"
echo "  Phase 2 — 产物中台 (3456) 部署 (systemd)"
echo "============================================"

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. 环境变量（.env 被 gitignore，需运行时生成）
echo ">>> [1/4] 写入 .env"
cat > "${HUB_DIR}/.env" <<EOF
DATABASE_URL="${DB_URL}"
REPO_ROOT="${REPO_DIR}"
EOF
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${HUB_DIR}/.env"

# 3. 安装依赖 + Prisma client 生成
echo ">>> [2/4] 安装依赖 + prisma generate"
cd "${HUB_DIR}"
sudo -u "${DEPLOY_USER}" npm install --no-audit --no-fund 2>&1 | tail -3
sudo -u "${DEPLOY_USER}" npx prisma generate 2>&1 | tail -5

# 4. Build
echo ">>> [3/4] 构建 (next build)"
sudo -u "${DEPLOY_USER}" npm run build 2>&1 | tail -10

# 5. 注册 systemd 服务
echo ">>> [4/4] 注册 product-hub.service (systemd)"
cat > /etc/systemd/system/product-hub.service <<EOF
[Unit]
Description=Dreambuddy Product Hub (Next.js 14, port 3456)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${HUB_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="NODE_ENV=production"
Environment="DATABASE_URL=${DB_URL}"
Environment="REPO_ROOT=${REPO_DIR}"
Environment="PYTHONPATH=${REPO_DIR}/19-数据访问层"
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=5
StandardOutput=append:${LOG_DIR}/out.log
StandardError=append:${LOG_DIR}/err.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable product-hub
systemctl restart product-hub

sleep 6

# 6. 验证（失败不中断脚本）
echo ""
echo "=== 服务状态 ==="
systemctl is-active product-hub || true
echo "=== 端口监听 ==="
ss -tlnp | grep 3456 || echo "⚠️  3456 未监听"
echo "=== API 测试 ==="
curl -s -m 10 "http://127.0.0.1:3456/api/trading-ranking/today" 2>&1 | head -c 200 || true
echo ""

echo ""
echo "============================================"
echo "  ✓ 产物中台部署完成 (systemd)"
echo "  日志: ${LOG_DIR}/"
echo "  命令: systemctl status product-hub"
echo "============================================"
