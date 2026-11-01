#!/bin/bash
# ============================================================
# 45 评测系统 — 部署前置门禁（P3-2 / SPEC §4 §13.4）
# 用法:
#   EVAL_ID=<eval_id> bash deploy/preflight-eval-gate.sh
#   EVAL_ID=<eval_id> EVAL_APPROVAL_ID=<27 审批 id> EVAL_REQUIRE_APPROVAL=1 \
#       bash deploy/preflight-eval-gate.sh        # P3-4 双凭证
#
# 语义:
#   - 直接以 evalctl enforce 的退出码判定（0 放行 / 2 拦截 / 3 INCONCLUSIVE / 4 ERROR）
#   - 影子模式（config/categories.yaml 的 gate.shadow=true）只观测并退出 0；
#     转实盘（shadow=false）后同一脚本即阻断，无需改本脚本
#   - 45 模块或 CLI 缺失 → FAIL-OPEN 放行并告警（引导期/未装配环境不阻塞整站部署）
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
EVAL_DIR="${EVAL_DIR:-${REPO_DIR}/45-评测系统}"
EVAL_ID="${EVAL_ID:-}"
APPROVAL_ID="${EVAL_APPROVAL_ID:-}"
REQUIRE_APPROVAL="${EVAL_REQUIRE_APPROVAL:-0}"

if [ ! -d "${EVAL_DIR}" ]; then
    echo "  ⚠ 45 评测系统缺失 (${EVAL_DIR})，门禁 FAIL-OPEN 放行"
    exit 0
fi

if [ -x "${EVAL_DIR}/.venv/bin/python" ]; then
    PYTHON="${EVAL_DIR}/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi

ARGS=(enforce --kind deploy --eval-id "${EVAL_ID}")
if [ "${REQUIRE_APPROVAL}" = "1" ]; then
    ARGS+=(--require-approval --approval-id "${APPROVAL_ID}")
fi

echo ">>> 45 部署门禁: eval_id=${EVAL_ID:-<空>} 双凭证=$([ "${REQUIRE_APPROVAL}" = "1" ] && echo on || echo off)"
set +e
(cd "${EVAL_DIR}" && "${PYTHON}" -m api.cli "${ARGS[@]}")
EVAL_RC=$?
set -e

case "${EVAL_RC}" in
    0) echo "  ✓ 45 门禁放行（PASS 或影子观测）" ;;
    2) echo "  ✗ 45 门禁拦截：无有效凭证，拒绝部署（SPEC P3-2）" ;;
    3) echo "  ✗ 45 门禁 INCONCLUSIVE：评测证据不足，拒绝部署" ;;
    *) echo "  ✗ 45 门禁执行异常 (rc=${EVAL_RC})，中止部署" ;;
esac
exit "${EVAL_RC}"
