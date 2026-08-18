#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TELEGRAM_ON_FAIL="${TELEGRAM_ON_FAIL:-1}"

EXTRA_ARGS="${EXTRA_ARGS:---transport http --base-url http://127.0.0.1:8092 --eval-mode rolling --family lr --key max_open_trades --folds 5 --n-init 8 --n-iter 24 --apply-config --order-test --order-notional-usdc 100 --order-auto-bump-to-min --order-ignore-cooldown --order-ignore-post-close-freeze}"

if [[ "${TELEGRAM_ON_FAIL}" == "1" || "${TELEGRAM_ON_FAIL}" == "true" || "${TELEGRAM_ON_FAIL}" == "TRUE" ]]; then
  TG_FLAG="--telegram-on-fail"
else
  TG_FLAG=""
fi

cd "${PROJECT_DIR}"
${PYTHON_BIN} tools/paramopt_bayes_validation_cron.py \
  --project-dir "${PROJECT_DIR}" \
  --python-exe "${PYTHON_BIN}" \
  ${TG_FLAG} \
  --extra-args "${EXTRA_ARGS}"
