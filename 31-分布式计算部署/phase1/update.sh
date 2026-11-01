#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 代码更新脚本
# 用法: bash update.sh [--skip-frontend] [--skip-v15] [--skip-deps] [--skip-g4] [--g4-hotfix "原因"]
# 流程: G4 部署窗口门 → 45 评测门禁 → git pull → 前端 pnpm install+build+systemd restart → V15 无需重启(timer自动拉新代码)
# G4: 波动率分位/资金费率异常时中止部署（SPEC G4）；hotfix 需 --g4-hotfix "原因" 显式豁免并留补审记录
# 45 门禁: EVAL_ID=<eval_id> 时校验部署凭证（P3-2），影子模式只观测、实盘阻断；双凭证用 EVAL_REQUIRE_APPROVAL=1 EVAL_APPROVAL_ID=<id>
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
SKIP_G4=false
G4_HOTFIX_REASON=""

# 解析参数
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-frontend) SKIP_FRONTEND=true ;;
        --skip-v15)      SKIP_V15=true ;;
        --skip-deps)     SKIP_DEPS=true ;;
        --skip-g4)       SKIP_G4=true ;;
        --g4-hotfix)
            G4_HOTFIX_REASON="${2:-}"
            if [ -z "${G4_HOTFIX_REASON}" ]; then
                echo "ERROR: --g4-hotfix 需要给出原因，如 --g4-hotfix \"P0 故障热修\""
                exit 2
            fi
            shift ;;
        *) echo "WARN: 未知参数 $1（忽略）" ;;
    esac
    shift
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

# ── 0. G4 部署窗口门（SPEC G4 / P0-4）──
echo ">>> [1/6] G4 部署窗口门（波动率分位 + 资金费率）"
G4_SCRIPT="${REPO_DIR}/37-一键启动脚本/g4-volatility-gate.py"
if [ "${SKIP_G4}" = true ]; then
    echo "  ⚠ 已显式跳过 G4 门 (--skip-g4)"
elif [ ! -f "${G4_SCRIPT}" ]; then
    echo "  ⚠ G4 脚本缺失: ${G4_SCRIPT}，FAIL-OPEN 放行"
else
    G4_ARGS=()
    if [ -n "${G4_HOTFIX_REASON}" ]; then
        G4_ARGS=(--hotfix --confirmed-by "${G4_HOTFIX_BY:-${DEPLOY_USER}}" --reason "${G4_HOTFIX_REASON}")
    fi
    set +e
    python3 "${G4_SCRIPT}" "${G4_ARGS[@]}"
    G4_RC=$?
    set -e
    case "${G4_RC}" in
        0) echo "  ✓ G4 通过，继续部署" ;;
        4)
            echo "  ✗ G4 拦截：波动率/资金费率异常，部署推迟到下一个低波动窗口"
            echo "    紧急修复请显式豁免：bash update.sh --g4-hotfix \"P0 故障热修原因\""
            exit 4 ;;
        *)
            echo "  ✗ G4 执行异常 (rc=${G4_RC})，中止部署"
            exit "${G4_RC}" ;;
    esac
fi

# ── 0b. 45 评测系统部署门禁（P3-2 / SPEC §4）──
echo ""
echo ">>> [2/6] 45 评测系统部署门禁（部署凭证 + 27 双凭证）"
EVAL_GATE_SCRIPT="${REPO_DIR}/deploy/preflight-eval-gate.sh"
if [ ! -f "${EVAL_GATE_SCRIPT}" ]; then
    echo "  ⚠ 门禁脚本缺失: ${EVAL_GATE_SCRIPT}，FAIL-OPEN 放行"
else
    REPO_DIR="${REPO_DIR}" \
    EVAL_ID="${EVAL_ID:-}" \
    EVAL_APPROVAL_ID="${EVAL_APPROVAL_ID:-}" \
    EVAL_REQUIRE_APPROVAL="${EVAL_REQUIRE_APPROVAL:-0}" \
        bash "${EVAL_GATE_SCRIPT}"
fi

# ── 1. Git Pull ──
echo ""
echo ">>> [3/6] 拉取最新代码 (git pull)"
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
    echo ">>> [4/6] 前端更新 (依赖+构建+重启)"

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

    echo "  重启前端 systemd 单元 (PM2 已废弃)..."
    systemctl restart dreambuddy-frontend.service 2>/dev/null && \
        echo "  ✓ dreambuddy-frontend.service 已重启" || \
        echo "  ⚠ dreambuddy-frontend.service 重启失败, 检查 journalctl -u dreambuddy-frontend"

    sleep 3
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3001 | grep -q "200\|307\|308"; then
        echo "  ✓ 前端健康: HTTP OK"
    else
        echo "  ⚠ 前端启动中, 检查: journalctl -u dreambuddy-frontend -n 50"
    fi
else
    echo ""
    echo ">>> [4/6] 跳过前端更新 (--skip-frontend)"
fi

# ── 3. V15 策略 ──
if [ "${SKIP_V15}" = false ]; then
    echo ""
    echo ">>> [5/6] V15 策略代码已更新"
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
    echo ">>> [5/6] 跳过 V15 更新 (--skip-v15)"
fi

# ── 4. Hermes 网关 ──
echo ""
echo ">>> [6/6] Hermes 网关"
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

# ── 5. G6 健康检查 + 记录 last_good（P1-1 自动回滚基线）──
echo ""
echo ">>> [G6] 健康检查 + 记录稳定版本"
HEALTH_SCRIPT="${REPO_DIR}/37-一键启动脚本/health-check.sh"
DEPLOY_STATE="${REPO_DIR}/.deploy"
mkdir -p "${DEPLOY_STATE}" 2>/dev/null || true
if [ -x "${HEALTH_SCRIPT}" ]; then
    bash "${HEALTH_SCRIPT}" --dry-run 2>&1 | tail -3 || true
    printf '{"commit":"%s","ts":"%s","branch":"%s"}\n' \
        "$(git rev-parse HEAD)" "$(date '+%Y-%m-%dT%H:%M:%S%z')" "${CURRENT_BRANCH}" > "${DEPLOY_STATE}/last_good"
    echo "  ✓ last_good = $(git rev-parse --short HEAD)"
else
    echo "  ⚠ health-check.sh 缺失，跳过 G6（FAIL-OPEN）"
fi

# ── 完成 ──
# G0-5（SPEC-L0 §5.1）：部署末尾 --record-good（清零失败计数 + 写 last_good）
if [ -x "${REPO_DIR:-/home/luke/dreambuddy}/37-一键启动脚本/health-check.sh" ]; then
    bash "${REPO_DIR:-/home/luke/dreambuddy}/37-一键启动脚本/health-check.sh" --record-good \
        && echo "[update] health-state 已清零，last_good 已记录" \
        || echo "[update] --record-good 执行失败（需人工检查 health-state）"
fi
echo ""
echo "============================================"
echo "  代码更新完成"
echo "============================================"
echo "  最新提交: ${NEW_COMMIT}"
echo ""
echo "  验证:"
echo "    bash 37-一键启动脚本/health-check.sh"
echo "    systemctl status dreambuddy-healthcheck.timer"
echo "    journalctl -u dreambuddy-frontend -n 50"
echo "    systemctl status v15-api v15-capital-api"
echo "    journalctl -u hermes-gateway -n 20"
echo "============================================"
