#!/usr/bin/env bash
set -euo pipefail

# Repo root
REPO_DIR="/Users/zhangjiangtao/ft_userdata"
cd "$REPO_DIR"

# Load .env if present (export all variables)
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Defaults (can be overridden by .env)
REQ_DELAY="${BINANCE_REQ_DELAY_SEC:-1.0}"
SYMBOL_DELAY="${BINANCE_SYMBOL_DELAY_SEC:-0.5}"
TOP_N="${BINANCE_TOP_N:-100}"
BATCH_SIZE="${BINANCE_BATCH_SIZE:-25}"
INTERVAL="${BINANCE_INTERVAL:-5m}"

PY="$REPO_DIR/venv/bin/python"
SCRIPT="$REPO_DIR/scripts/binance_tsdb_incremental.py"
LOG_DIR="$REPO_DIR/user_data/logs"
mkdir -p "$LOG_DIR"

echo "[binance_ingest_hourly] $(date '+%Y-%m-%d %H:%M:%S') start" >> "$LOG_DIR/binance_ingest_cron.log"
for i in 0 1 2 3; do
  BINANCE_REQ_DELAY_SEC="$REQ_DELAY" \
  BINANCE_SYMBOL_DELAY_SEC="$SYMBOL_DELAY" \
  BINANCE_TOP_N="$TOP_N" \
  BINANCE_BATCH_SIZE="$BATCH_SIZE" \
  BINANCE_BATCH_INDEX="$i" \
  BINANCE_INTERVAL="$INTERVAL" \
  "$PY" "$SCRIPT" >> "$LOG_DIR/binance_ingest_cron.log" 2>&1 || true
done
echo "[binance_ingest_hourly] $(date '+%Y-%m-%d %H:%M:%S') done" >> "$LOG_DIR/binance_ingest_cron.log"

