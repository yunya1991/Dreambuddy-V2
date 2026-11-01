#!/bin/bash
# ============================================================
# 45 评测系统 — 季度 golden set 回归（P4-6 / SPEC §8.3 §8.5）
# 用法:
#   BASELINE_CONFIG=<path>/config/baseline.yaml bash deploy/quarterly-baseline.sh
#   crontab 示例（每季度首日 03:00）:
#     0 3 1 */3 * BASELINE_CONFIG=/path/config/baseline.yaml \
#         /path/deploy/quarterly-baseline.sh >> /var/log/eval-baseline.log 2>&1
#
# 语义:
#   - 直接以 evalctl baseline 退出码判定（0 OK / 2 REGRESSION / 3 INCONCLUSIVE / 4 ERROR）
#   - 报告默认落 45-评测系统/artifacts/baseline/<YYYYMMDD>.json
# ============================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
EVAL_DIR="${EVAL_DIR:-${REPO_DIR}/45-评测系统}"
CONFIG="${BASELINE_CONFIG:-${EVAL_DIR}/config/baseline.yaml}"
OUT="${BASELINE_OUT:-${EVAL_DIR}/artifacts/baseline/$(date +%Y%m%d).json}"

if [ ! -d "${EVAL_DIR}" ]; then
    echo "  ⚠ 45 评测系统缺失 (${EVAL_DIR})，跳过季度回归"
    exit 4
fi

if [ -x "${EVAL_DIR}/.venv/bin/python" ]; then
    PYTHON="${EVAL_DIR}/.venv/bin/python"
else
    PYTHON="${PYTHON:-python3}"
fi

mkdir -p "$(dirname "${OUT}")"

echo ">>> 45 季度回归: config=${CONFIG} out=${OUT}"
set +e
(cd "${EVAL_DIR}" && "${PYTHON}" -m api.cli baseline --config "${CONFIG}" --out "${OUT}")
EVAL_RC=$?
set -e

case "${EVAL_RC}" in
    0) echo "  ✓ 回归通过（无退化）" ;;
    2) echo "  ✗ 检测到退化：请复核 case 明细（报告 ${OUT}）" ;;
    3) echo "  ⚠ INCONCLUSIVE：配对样本不足或未配置 case" ;;
    *) echo "  ✗ 季度回归执行异常 (rc=${EVAL_RC})" ;;
esac
exit "${EVAL_RC}"
