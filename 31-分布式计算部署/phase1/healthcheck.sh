#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 统一健康检查
# 用法: bash healthcheck.sh [--json]
# 检查: 前端 / V15 API / V15 timers / Docker / Hermes / 系统资源
# ============================================================

JSON_MODE=false
[ "${1:-}" = "--json" ] && JSON_MODE=true

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

# 加载环境变量
if [ -f "${ENV_FILE}" ]; then
    set -a
    source "${ENV_FILE}" 2>/dev/null || true
    set +a
fi

PASS=0
FAIL=0
WARN=0
RESULTS=()

check() {
    local name="$1"
    local status="$2"
    local detail="$3"
    if [ "${status}" = "ok" ]; then
        PASS=$((PASS + 1))
        RESULTS+=("✓ ${name}: ${detail}")
    elif [ "${status}" = "warn" ]; then
        WARN=$((WARN + 1))
        RESULTS+=("⚠ ${name}: ${detail}")
    else
        FAIL=$((FAIL + 1))
        RESULTS+=("✗ ${name}: ${detail}")
    fi
}

echo "============================================"
echo "  Dreambuddy V2 — Phase 1 健康检查"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"
echo ""

# ── 1. 前端服务 (PM2 / port 3001) ──
if command -v pm2 &>/dev/null && pm2 jlist 2>/dev/null | grep -q "dreambuddy-frontend"; then
    FE_STATUS=$(pm2 jlist 2>/dev/null | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ "${FE_STATUS}" = "online" ]; then
        check "前端 (PM2)" "ok" "online (port 3001)"
    else
        check "前端 (PM2)" "warn" "status=${FE_STATUS}"
    fi
else
    check "前端 (PM2)" "fail" "进程未找到"
fi

# HTTP 检查
FE_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:3001 2>/dev/null || echo "000")
if echo "${FE_HTTP}" | grep -q "200\|307\|308"; then
    check "前端 HTTP" "ok" "HTTP ${FE_HTTP}"
else
    check "前端 HTTP" "warn" "HTTP ${FE_HTTP} (可能启动中)"
fi

# ── 2. V15 决策 API (port 8771) ──
V15_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8771/health 2>/dev/null || echo "000")
if echo "${V15_HTTP}" | grep -q "200"; then
    check "V15 决策 API" "ok" "HTTP ${V15_HTTP} (port 8771)"
else
    check "V15 决策 API" "fail" "HTTP ${V15_HTTP} (port 8771)"
fi

# ── 3. V15 资金管理 API (port 8770) ──
CAP_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8770/status 2>/dev/null || echo "000")
if echo "${CAP_HTTP}" | grep -q "200"; then
    check "V15 资金管理 API" "ok" "HTTP ${CAP_HTTP} (port 8770)"
else
    check "V15 资金管理 API" "fail" "HTTP ${CAP_HTTP} (port 8770)"
fi

# ── 4. V15 systemd timers ──
if systemctl is-active --quiet v15-orchestrator.timer 2>/dev/null; then
    check "V15 Orchestrator Timer" "ok" "active (15min)"
else
    check "V15 Orchestrator Timer" "fail" "未激活"
fi

if systemctl is-active --quiet v15-poll-light.timer 2>/dev/null; then
    check "V15 Poll Light Timer" "ok" "active (5min)"
else
    check "V15 Poll Light Timer" "fail" "未激活"
fi

# ── 5. V15 API systemd services ──
if systemctl is-active --quiet v15-api.service 2>/dev/null; then
    check "V15 API Service" "ok" "running"
else
    check "V15 API Service" "fail" "未运行"
fi

if systemctl is-active --quiet v15-capital-api.service 2>/dev/null; then
    check "V15 Capital API Service" "ok" "running"
else
    check "V15 Capital API Service" "fail" "未运行"
fi

# ── 6. Docker 容器 (PG + Redis + MinIO) ──
if command -v docker &>/dev/null; then
    for container in dreambuddy-pg dreambuddy-redis dreambuddy-minio; do
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${container}$"; then
            check "Docker ${container}" "ok" "running"
        else
            check "Docker ${container}" "fail" "未运行"
        fi
    done
else
    check "Docker" "fail" "docker 命令不可用"
fi

# ── 7. Hermes 飞书网关 ──
if systemctl is-active --quiet hermes-gateway.service 2>/dev/null; then
    check "Hermes 网关" "ok" "running"
elif systemctl is-enabled --quiet hermes-gateway.service 2>/dev/null; then
    check "Hermes 网关" "warn" "已注册但未运行 (凭据未配置?)"
else
    check "Hermes 网关" "warn" "未注册 (运行 06-deploy-hermes.sh)"
fi

# ── 8. Nginx ──
if systemctl is-active --quiet nginx 2>/dev/null; then
    check "Nginx" "ok" "running"
else
    check "Nginx" "warn" "未运行 (运行 05-nginx-ssl.sh)"
fi

# ── 9. HTTPS 域名 (如果配置了 DOMAIN) ──
if [ -n "${DOMAIN:-}" ]; then
    HTTPS_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://"${DOMAIN}" 2>/dev/null || echo "000")
    if echo "${HTTPS_HTTP}" | grep -q "200\|307\|308"; then
        check "HTTPS ${DOMAIN}" "ok" "HTTP ${HTTPS_HTTP}"
    else
        check "HTTPS ${DOMAIN}" "warn" "HTTP ${HTTPS_HTTP} (SSL 未配置?)"
    fi
fi

# ── 10. 系统资源 ──
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "${DISK_PCT}" -lt 80 ]; then
    check "磁盘空间" "ok" "${DISK_PCT}% 已用"
elif [ "${DISK_PCT}" -lt 90 ]; then
    check "磁盘空间" "warn" "${DISK_PCT}% 已用"
else
    check "磁盘空间" "fail" "${DISK_PCT}% 已用 (紧急!)"
fi

MEM_PCT=$(free | awk '/Mem:/{printf "%.0f", $3/$2*100}')
if [ "${MEM_PCT}" -lt 80 ]; then
    check "内存使用" "ok" "${MEM_PCT}% 已用"
elif [ "${MEM_PCT}" -lt 90 ]; then
    check "内存使用" "warn" "${MEM_PCT}% 已用"
else
    check "内存使用" "fail" "${MEM_PCT}% 已用 (紧急!)"
fi

# ── 输出结果 ──
if [ "${JSON_MODE}" = true ]; then
    echo "{"
    echo "  \"pass\": ${PASS},"
    echo "  \"fail\": ${FAIL},"
    echo "  \"warn\": ${WARN},"
    echo "  \"checks\": ["
    for i in "${!RESULTS[@]}"; do
        sep=$([ $i -lt $((${#RESULTS[@]} - 1)) ] && echo "," || echo "")
        echo "    \"${RESULTS[$i]}\"${sep}"
    done
    echo "  ]"
    echo "}"
    exit 0
fi

echo "─── 检查结果 ───"
for r in "${RESULTS[@]}"; do
    echo "  ${r}"
done

echo ""
echo "============================================"
echo "  总计: ✓ ${PASS} 通过  ⚠ ${WARN} 警告  ✗ ${FAIL} 失败"
echo "============================================"

if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
