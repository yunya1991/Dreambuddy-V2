#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2: 前端重新构建（接入三屏+BDSM）
# 作用: 更新 NEXT_PUBLIC_TREND_SYSTEM_URL → /api/trend，重新 build + 重启
# 用法: sudo bash 04-rebuild-frontend.sh
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
FRONTEND_DIR="${REPO_DIR}/3.1-FRONTEND"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

echo "============================================"
echo "  Phase 2 — 前端重新构建"
echo "============================================"

# 加载环境
if [ -f "${ENV_FILE}" ]; then
    set -a
    source "${ENV_FILE}"
    set +a
fi

DOMAIN="${DOMAIN:?ERROR: DOMAIN 未设置}"

# 1. 更新 .env.cloud 中的 TREND_SYSTEM_URL
echo ">>> [1/3] 更新 NEXT_PUBLIC_TREND_SYSTEM_URL"
sed -i "s|^NEXT_PUBLIC_TREND_SYSTEM_URL=.*|NEXT_PUBLIC_TREND_SYSTEM_URL=https://${DOMAIN}/api/trend|" "${ENV_FILE}"
grep "NEXT_PUBLIC_TREND_SYSTEM_URL" "${ENV_FILE}"

# 2. 重新生成 .env.production + build
echo ">>> [2/3] 重新构建前端"
cd "${FRONTEND_DIR}"

# 重新生成 .env.production（复用 phase1 脚本的逻辑）
set -a
source "${ENV_FILE}"
set +a

cat > "${FRONTEND_DIR}/.env.production" << EOF
NEXT_PUBLIC_DOMAIN=https://${DOMAIN}
NEXTAUTH_URL=https://${DOMAIN}
AUTH_URL=https://${DOMAIN}
AUTH_TRUST_HOST=true
NEXT_PUBLIC_TREND_SYSTEM_URL=https://${DOMAIN}/api/trend
NEXT_PUBLIC_BRIDGE_URL=${NEXT_PUBLIC_BRIDGE_URL:-http://127.0.0.1:3847}
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}
TAVILY_API_KEY=${TAVILY_API_KEY:-}
EOF

chown "${DEPLOY_USER}:${DEPLOY_USER}" "${FRONTEND_DIR}/.env.production"
sudo -u "${DEPLOY_USER}" pnpm build 2>&1 | tail -5

# 3. 重启前端
echo ">>> [3/3] 重启前端 PM2 进程"
pm2 restart dreambuddy-frontend 2>/dev/null || pm2 restart all

sleep 3

echo ""
echo "=== 验证 ==="
pm2 list | grep frontend
echo ""
echo "✓ 前端重新构建完成"
echo "  三屏页面: https://${DOMAIN}/dashboard/three-screens"
echo "  BDSM页面: https://${DOMAIN}/dashboard/bdsm"
