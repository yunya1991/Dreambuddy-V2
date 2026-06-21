#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RESEARCH_ROOT="${RESEARCH_ROOT:-/Users/zhangjiangtao/ft_userdata/基本面分析_fundamental}"
LOG_DIR="${PROJECT_DIR}/user_data/logs"
MANIFEST="${PROJECT_DIR}/user_data/fundamental_sync/last_sync.json"
POLICY_STATE="${PROJECT_DIR}/user_data/fundamental_sync/policy_state.json"
SYNC_BASELINE_SEC="${SYNC_BASELINE_SEC:-28800}"
SYNC_BURST_SEC="${SYNC_BURST_SEC:-900}"
SYNC_BURST_HOLD_SEC="${SYNC_BURST_HOLD_SEC:-7200}"
SYNC_SLA_SEC="${SYNC_SLA_SEC:-900}"

mkdir -p "${LOG_DIR}"

cd "${PROJECT_DIR}"
"${PYTHON_BIN}" tools/fundamental_research_sync.py \
  --research-root "${RESEARCH_ROOT}" \
  --trading-root "${PROJECT_DIR}" \
  --manifest "${MANIFEST}" \
  --policy-state "${POLICY_STATE}" \
  --baseline-sec "${SYNC_BASELINE_SEC}" \
  --burst-sec "${SYNC_BURST_SEC}" \
  --burst-hold-sec "${SYNC_BURST_HOLD_SEC}" \
  --sla-sec "${SYNC_SLA_SEC}" \
  >> "${LOG_DIR}/fundamental_sync.log" 2>&1
