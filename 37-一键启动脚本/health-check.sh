#!/bin/bash
# ============================================================
# health-check.sh — G6 健康检查 + 连续失败自动回滚触发（SPEC P1-1）
#
# 运行位置：云端（systemd timer dreambuddy-healthcheck.timer，每 5 分钟）
# 用法:
#   health-check.sh                 常规巡检；连续失败达阈值 → 调 rollback-last-good.sh
#   health-check.sh --record-good   部署成功后调用：清零失败计数并写 last_good
#   health-check.sh --dry-run       只输出结果，不改状态、不触发回滚
#
# FAIL-OPEN：pg/redis 客户端不存在 → 记 SKIP，不计失败；端点不可达才计失败
# ============================================================
set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
STATE_DIR="${REPO_DIR}/.deploy"
STATE_FILE="${STATE_DIR}/health-state"
LOG_FILE="${STATE_DIR}/health-log.jsonl"
THRESHOLD="${HEALTH_FAIL_THRESHOLD:-3}"
ROLLBACK="${REPO_DIR}/37-一键启动脚本/rollback-last-good.sh"

RECORD_GOOD=false
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        --record-good) RECORD_GOOD=true ;;
        --dry-run) DRY_RUN=true ;;
    esac
done

mkdir -p "${STATE_DIR}"
NOW="$(date '+%Y-%m-%dT%H:%M:%S%z')"
FAILS=0
CHECKS=0
SKIPS=0
DETAILS=""

fail() { FAILS=$((FAILS + 1)); DETAILS="${DETAILS}{\"check\":\"$1\",\"result\":\"FAIL\",\"detail\":\"$2\"},"; }
ok()   { DETAILS="${DETAILS}{\"check\":\"$1\",\"result\":\"OK\",\"detail\":\"$2\"},"; }
skip() { SKIPS=$((SKIPS + 1)); DETAILS="${DETAILS}{\"check\":\"$1\",\"result\":\"SKIP\",\"detail\":\"$2\"},"; }

# ── 1. 关键 unit 存活 ──
for unit in v15-api dreambuddy-frontend yijing-data-server yijing-polling-trader hermes-gateway trailing-stop-runner; do
    CHECKS=$((CHECKS + 1))
    if systemctl is-active --quiet "${unit}.service" 2>/dev/null; then
        ok "unit:${unit}" active
    else
        fail "unit:${unit}" "$(systemctl is-active "${unit}.service" 2>/dev/null || echo not-found)"
    fi
done

# ── 2. HTTP 端点 ──
for ep in "http://127.0.0.1:8771/health" "http://127.0.0.1:3001" "http://127.0.0.1:8765"; do
    CHECKS=$((CHECKS + 1))
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "${ep}" 2>/dev/null)"; code="${code:-000}"
    case "${code}" in
        2*|3*) ok "http:${ep}" "${code}" ;;
        000)   fail "http:${ep}" "unreachable" ;;
        *)     fail "http:${ep}" "${code}" ;;
    esac
done

# ── 3. PostgreSQL / Redis（客户端缺失则 SKIP）──
CHECKS=$((CHECKS + 1))
if command -v pg_isready >/dev/null 2>&1; then
    if pg_isready -q 2>/dev/null; then ok "pg" ready; else fail "pg" "not-ready"; fi
else
    skip "pg" "pg_isready-not-installed"
fi

CHECKS=$((CHECKS + 1))
if command -v redis-cli >/dev/null 2>&1; then
    if [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then ok "redis" pong; else fail "redis" "no-pong"; fi
else
    skip "redis" "redis-cli-not-installed"
fi

# ── 4. systemd failed 单元（告警不判失败，避免误回滚）──
FAILED_UNITS="$(systemctl list-units --failed --no-legend --no-pager 2>/dev/null | wc -l | tr -d ' ')"

# ── 结果汇总 ──
PREV_FAILS="$(cat "${STATE_FILE}" 2>/dev/null || echo 0)"
[ -n "${PREV_FAILS}" ] || PREV_FAILS=0
DETAILS="${DETAILS%,}"

if ${RECORD_GOOD}; then
    CUR_FAILS=0
elif [ "${FAILS}" -eq 0 ]; then
    CUR_FAILS=0
else
    CUR_FAILS=$((PREV_FAILS + 1))
fi

STATUS="HEALTHY"
ACTION="none"
if [ "${FAILS}" -gt 0 ]; then
    STATUS="DEGRADED"
    if [ "${CUR_FAILS}" -ge "${THRESHOLD}" ]; then
        STATUS="CRITICAL"
        ACTION="manual_rollback_required"
    fi
fi

LINE="{\"ts\":\"${NOW}\",\"status\":\"${STATUS}\",\"fails\":${FAILS},\"consecutive\":${CUR_FAILS},\"checks\":${CHECKS},\"skips\":${SKIPS},\"failed_units\":${FAILED_UNITS},\"action\":\"${ACTION}\",\"details\":[${DETAILS}]}"
echo "${LINE}" | tee -a "${LOG_FILE}" 2>/dev/null || echo "${LINE}"
echo "[health] status=${STATUS} fails=${FAILS}/${CHECKS} consecutive=${CUR_FAILS}/${THRESHOLD} failed_units=${FAILED_UNITS}"

if ${DRY_RUN}; then
    echo "[health] dry-run：不写状态、不回滚"
    exit 0
fi

echo "${CUR_FAILS}" > "${STATE_FILE}"

if [ "${ACTION}" = "manual_rollback_required" ]; then
    # G0-5（SPEC-L0 §5.1）：回滚需人工确认，禁止连续失败即自动 git reset --hard
    echo "[health] 连续 ${CUR_FAILS} 次失败 ≥ ${THRESHOLD} → 需人工回滚（不再自动触发）"
    echo "[health] 人工回滚命令: ${ROLLBACK} --yes --reason 'manual: consecutive=${CUR_FAILS}'"
fi

exit $([ "${FAILS}" -eq 0 ] && echo 0 || echo 1)
