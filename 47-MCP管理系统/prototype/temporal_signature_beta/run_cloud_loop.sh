#!/usr/bin/env bash
# run_cloud_loop.sh — 云端全自动闭环：历史回填(幂等) → 消融 → 门禁推进
# SPEC §4.6.13 云端闭环方案。由 dreambuddy-ablation-loop.timer 每 6h 触发。
set -euo pipefail

REPO="/home/luke/dreambuddy"
PY="/home/luke/venv-trading/bin/python"
MAIL="$REPO/.workbuddy/agent_mail"
PROTO="$REPO/47-MCP管理系统/prototype/temporal_signature_beta"

cd "$REPO"

echo "[$(date -Iseconds)] [1/3] backfill (idempotent)..."
"$PY" "$PROTO/backfill_trajectories.py" --store "$MAIL/trajectories.jsonl" || echo "backfill skipped/failed (FAIL-OPEN)"

echo "[$(date -Iseconds)] [2/3] ablation..."
"$PY" "$PROTO/run_ablation.py" \
  --input "$MAIL/trajectories.jsonl" \
  --output "$MAIL/ablation_result.json" || echo "ablation failed (FAIL-OPEN)"

echo "[$(date -Iseconds)] [3/3] gate promote..."
"$PY" -m mcp_shells._shared.shadow_gate --promote \
  --ablation "$MAIL/ablation_result.json" || echo "promote failed (FAIL-OPEN)"

echo "[$(date -Iseconds)] loop done"
