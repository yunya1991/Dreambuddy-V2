#!/usr/bin/env bash
# run_train_loop.sh — 本地训练↔云端感知闭环一条命令：pull → ablation → push（SPEC §4.6.13）
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PY=${PYTHON:-python3}

echo "[1/3] pull trajectories from cloud"
bash "$SCRIPT_DIR/pull_trajectories.sh"

echo "[2/3] run ablation (F1/F2)"
"$PY" "$SCRIPT_DIR/run_ablation.py"

echo "[3/3] push ablation_result to cloud"
bash "$SCRIPT_DIR/push_ablation.sh"

echo "done; cloud gate will read ablation_result.json on next cycle."
