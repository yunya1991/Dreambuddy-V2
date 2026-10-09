#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 代码更新脚本
# 用法: bash update.sh [--skip-frontend] [--skip-v15] [--skip-deps]
# 流程: git pull → 前端 pnpm install+build+pm2 restart → V15 无需重启(timer自动拉新代码)
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
FRONTEND_DIR="${REPO_DIR}/3.1-FRONTEND"
V15_DIR="${REPO_DIR}/14-V15经典马丁策略"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

SKIP_FRONTEND=false
SKIP_V15=false
SKIP_DEPS=false

# 解析参数
for arg in "$@"; do
    case "${arg}" in
        --skip-frontend) SKIP_FRONTEND=true ;;
        --skip-v15)      SKIP_V15=true ;;
        --skip-deps)     SKIP_DEPS=true ;;
    esac
done

echo "============================================"
echo "  Dreambuddy V2 — 代码更新"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo ""

# ── 0. 前置检查 ──
if [ ! -d "${REPO_DIR}/.git" ]; then
    echo "ERROR: ${REPO_DIR} 不是 git 仓库"
    exit 1
fi

# 检查是否有未提交的本地修改
cd "${REPO_DIR}"
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo "⚠ 检测到本地未提交的修改:"
    git status --short
    echo ""
    echo "  建议先 stash 或 commit, 继续? (y/N)"
    read -r CONFIRM
    [ "${CONFIRM}" != "y" ] && exit 0
    git stash 2>/dev/null || true
fi

# ── 1. Git Pull ──
echo ">>> [1/4] 拉取最新代码 (git pull)"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "  当前分支: ${CURRENT_BRANCH}"

git fetch --all
git pull --ff-only 2>/dev/null || {
    echo "  fast-forward 失败, 尝试 rebase..."
    git pull --rebase
}

NEW_COMMIT=$(git rev-parse --short HEAD)
echo "✓ 代码已更新: ${NEW_COMMIT}"

# 恢复 stash (如果有)
git stash pop 2>/dev/null || true

# ── 2. 前端更新 ──
if [ "${SKIP_FRONTEND}" = false ]; then
    echo ""
    echo ">>> [2/4] 前端更新 (依赖+构建+重启)"

    cd "${FRONTEND_DIR}"

    # 重新生成 .env.production (配置可能更新)
    if [ -f "${ENV_FILE}" ]; then
        set -a
        source "${ENV_FILE}"
        set +a

        echo "  重新生成 .env.production..."
        cat > .env.production << EOF
DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}?schema=public"
NEXTAUTH_URL="https://${DOMAIN}"
AUTH_URL="https://${DOMAIN}/api/auth"
AUTH_TRUST_HOST="true"
NEXTAUTH_SECRET="${NEXTAUTH_SECRET}"
AUTH_SECRET="${AUTH_SECRET}"
ENCRYPTION_KEY="${ENCRYPTION_KEY}"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"
TAVILY_API_KEY="${TAVILY_API_KEY}"
NEXT_PUBLIC_BRIDGE_URL="${NEXT_PUBLIC_BRIDGE_URL:-http://127.0.0.1:3847}"
HUB_BASE_URL="${HUB_BASE_URL:-http://127.0.0.1:8787}"
WORKBUDDY_API_URL="${WORKBUDDY_API_URL:-http://127.0.0.1:8080}"
WORKBUDDY_WS_URL="${WORKBUDDY_WS_URL:-ws://127.0.0.1:8080}"
NEXT_PUBLIC_TREND_SYSTEM_URL="${NEXT_PUBLIC_TREND_SYSTEM_URL:-http://127.0.0.1:8765}"
REDIS_URL="redis://127.0.0.1:6379"
MINIO_ENDPOINT="http://127.0.0.1:9000"
MINIO_ACCESS_KEY="${MINIO_ROOT_USER}"
MINIO_SECRET_KEY="${MINIO_ROOT_PASSWORD}"
EOF
        echo "  ✓ .env.production 已更新"
    fi

    # Prisma 迁移 (如果有新迁移)
    echo "  检查 Prisma 迁移..."
    if [ -d "prisma/migrations" ]; then
        pnpm prisma generate 2>/dev/null
        pnpm prisma migrate deploy 2>/dev/null && echo "  ✓ Prisma 迁移完成" || echo "  ✓ 无新迁移"
    fi

    if [ "${SKIP_DEPS}" = false ]; then
        echo "  安装依赖..."
        pnpm install --frozen-lockfile 2>/dev/null || pnpm install
        echo "  ✓ 依赖已安装"
    fi

    echo "  构建 Next.js..."
    pnpm build
    echo "  ✓ 构建完成"

    echo "  重启 PM2 前端进程..."
    pm2 restart dreambuddy-frontend --update-env 2>/dev/null || {
        echo "  ⚠ PM2 重启失败, 尝试重新启动..."
        pm2 start "pnpm start" --name dreambuddy-frontend --cwd "${FRONTEND_DIR}" --env production
    }
    pm2 save
    echo "  ✓ 前端已重启"

    sleep 3
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3001 | grep -q "200\|307\|308"; then
        echo "  ✓ 前端健康: HTTP OK"
    else
        echo "  ⚠ 前端启动中, 检查: pm2 logs dreambuddy-frontend"
    fi
else
    echo ""
    echo ">>> [2/4] 跳过前端更新 (--skip-frontend)"
fi

# ── 3. V15 策略 ──
if [ "${SKIP_V15}" = false ]; then
    echo ""
    echo ">>> [3/4] V15 策略代码已更新"
    echo "  V15 使用 systemd timer (oneshot 模式)"
    echo "  下次 timer 触发时自动使用新代码, 无需重启"

    # 如果有 Python 依赖更新
    if [ "${SKIP_DEPS}" = false ]; then
        echo "  检查 Python 依赖..."
        sudo -u "${DEPLOY_USER}" python3 -c "import requests, pandas, numpy, ccxt, dotenv" 2>/dev/null || {
            echo "  安装缺失依赖..."
            pip3 install --break-system-packages requests pandas numpy ccxt python-dotenv
        }
        echo "  ✓ Python 依赖就绪"
    fi

    # 重启 V15 API 长驻服务 (拉取新代码)
    echo "  重启 V15 API 服务..."
    systemctl restart v15-api.service 2>/dev/null && echo "  ✓ v15-api 已重启" || true
    systemctl restart v15-capital-api.service 2>/dev/null && echo "  ✓ v15-capital-api 已重启" || true
else
    echo ""
    echo ">>> [3/4] 跳过 V15 更新 (--skip-v15)"
fi

# ── 4. Hermes 网关 ──
echo ""
echo ">>> [4/4] Hermes 网关"
if systemctl is-active --quiet hermes-gateway.service 2>/dev/null; then
    systemctl restart hermes-gateway.service
    sleep 2
    if systemctl is-active --quiet hermes-gateway.service; then
        echo "  ✓ hermes-gateway 已重启"
    else
        echo "  ⚠ hermes-gateway 重启后异常"
    fi
else
    echo "  hermes-gateway 未运行, 跳过"
fi

# ── 完成 ──
echo ""
echo "============================================"
echo "  代码更新完成"
echo "============================================"
echo "  最新提交: ${NEW_COMMIT}"
echo ""
echo "  验证:"
echo "    bash healthcheck.sh"
echo "    pm2 logs dreambuddy-frontend --lines 20"
echo "    systemctl status v15-api v15-capital-api"
echo "    journalctl -u hermes-gateway -n 20"
echo "============================================"
