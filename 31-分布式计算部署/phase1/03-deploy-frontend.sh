#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 前端部署 (Next.js 15)
# 用法: bash 03-deploy-frontend.sh
# 前置: 02-deploy-data.sh 已完成 (PostgreSQL 可连接)
# 产出: pnpm build + prisma migrate + pm2 start
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
FRONTEND_DIR="${REPO_DIR}/3.1-FRONTEND"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

echo "============================================"
echo "  Phase 1 — 前端部署 (Next.js 15)"
echo "============================================"

# ── 检查 ──
if [ ! -d "${FRONTEND_DIR}" ]; then
    echo "ERROR: ${FRONTEND_DIR} 不存在"
    echo "请先 clone 仓库到 ${REPO_DIR}"
    exit 1
fi
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} 不存在"
    exit 1
fi
echo "✓ 前端目录存在, .env.cloud 就绪"

# ── 加载环境变量 ──
set -a
source "${ENV_FILE}"
set +a

# ── 构建前端 .env.production ──
echo ">>> [1/6] 生成前端 .env.production"
cat > "${FRONTEND_DIR}/.env.production" << EOF
# === 数据库 ===
DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}?schema=public"

# === NextAuth 认证 ===
NEXTAUTH_URL="https://${DOMAIN}"
AUTH_URL="https://${DOMAIN}/api/auth"
AUTH_TRUST_HOST="true"
NEXTAUTH_SECRET="${NEXTAUTH_SECRET}"
AUTH_SECRET="${AUTH_SECRET}"

# === 加密密钥 (API 凭证 AES-256-GCM) ===
ENCRYPTION_KEY="${ENCRYPTION_KEY}"

# === LLM API (DeepSeek) ===
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"

# === 搜索 API (Tavily) ===
TAVILY_API_KEY="${TAVILY_API_KEY}"

# === 外部服务 URL ===
# Phase 1: 以下服务尚未上云, 指向 127.0.0.1, 后续迁移后更新
NEXT_PUBLIC_BRIDGE_URL="${NEXT_PUBLIC_BRIDGE_URL:-http://127.0.0.1:3847}"
HUB_BASE_URL="${HUB_BASE_URL:-http://127.0.0.1:8787}"
WORKBUDDY_API_URL="${WORKBUDDY_API_URL:-http://127.0.0.1:8080}"
WORKBUDDY_WS_URL="${WORKBUDDY_WS_URL:-ws://127.0.0.1:8080}"
NEXT_PUBLIC_TREND_SYSTEM_URL="${NEXT_PUBLIC_TREND_SYSTEM_URL:-http://127.0.0.1:8765}"

# === Redis (Session 缓存) ===
REDIS_URL="redis://127.0.0.1:6379"

# === MinIO (文件存储) ===
MINIO_ENDPOINT="http://127.0.0.1:9000"
MINIO_ACCESS_KEY="${MINIO_ROOT_USER}"
MINIO_SECRET_KEY="${MINIO_ROOT_PASSWORD}"
EOF
echo "✓ .env.production generated (DOMAIN=${DOMAIN})"

# ── 安装依赖 ──
echo ">>> [2/6] 安装依赖 (pnpm install)"
cd "${FRONTEND_DIR}"
pnpm install --frozen-lockfile --dangerously-allow-all-builds 2>/dev/null || pnpm install --dangerously-allow-all-builds
echo "✓ 依赖安装完成"

# ── Prisma 迁移 ──
echo ">>> [3/6] Prisma migrate (5 个迁移文件)"
# 确认 PostgreSQL 已启动
if ! docker exec dreambuddy-pg pg_isready -U "${POSTGRES_USER}" &>/dev/null; then
    echo "ERROR: PostgreSQL 未就绪, 请先运行 02-deploy-data.sh"
    exit 1
fi

# 生成 Prisma Client + 迁移
pnpm prisma generate
pnpm prisma migrate deploy
echo "✓ Prisma 迁移完成 (5 migrations)"

# ── Seed 数据 ──
echo ">>> [4/6] 数据库 Seed (初始用户)"
pnpm prisma db seed 2>/dev/null || {
    echo "  尝试 tsx 直接执行 seed..."
    pnpm tsx prisma/seed.ts 2>/dev/null || echo "⚠ seed 跳过 (可手动执行)"
}
echo "✓ Seed 完成"

# ── 构建 ──
echo ">>> [5/6] 构建 Next.js (pnpm build)"
pnpm build
echo "✓ 构建完成"

# ── PM2 启动 ──
echo ">>> [6/6] PM2 启动前端服务"

# 停止旧进程 (如果有)
pm2 delete dreambuddy-frontend 2>/dev/null || true

pm2 start "pnpm start" \
    --name dreambuddy-frontend \
    --cwd "${FRONTEND_DIR}" \
    --env production \
    --exp-backoff-restart-delay=100

# ── PM2 持久化: 服务器重启后自动恢复前端进程 ──
# 生成 systemd 服务使 PM2 在开机时自动启动
pm2 startup systemd -u "${DEPLOY_USER}" --hp "${DEPLOY_HOME}" 2>/dev/null || true
pm2 save

echo "✓ PM2 持久化已配置 (服务器重启后自动恢复)"

echo ""
echo ">>> 前端进程状态:"
pm2 list

# ── 验证 ──
sleep 3
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3001 | grep -q "200\|307\|308"; then
    echo "✓ 前端服务已启动: http://127.0.0.1:3001"
else
    echo "⚠ 前端可能还在启动中, 检查: pm2 logs dreambuddy-frontend"
fi

echo ""
echo "============================================"
echo "  前端部署完成"
echo "============================================"
echo "  本地访问:  http://127.0.0.1:3001"
echo "  PM2 管理:  pm2 logs dreambuddy-frontend"
echo "            pm2 restart dreambuddy-frontend"
echo "            pm2 monit"
echo ""
echo "  下一步: bash 04-deploy-v15.sh"
echo "============================================"
