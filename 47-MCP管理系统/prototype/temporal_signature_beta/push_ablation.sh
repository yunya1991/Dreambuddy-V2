#!/usr/bin/env bash
# push_ablation.sh — 把本地 ablation_result.json 上传到云端门禁路径（SPEC §4.6.13 [3]）
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOCAL="$SCRIPT_DIR/ablation_result.json"
REMOTE="dreambuddy-remote:/home/luke/dreambuddy/.workbuddy/agent_mail/ablation_result.json"

if [[ ! -f "$LOCAL" ]]; then
  echo "missing $LOCAL; run run_ablation.py first" >&2
  exit 1
fi

scp "$LOCAL" "$REMOTE"
echo "pushed $LOCAL -> $REMOTE"
