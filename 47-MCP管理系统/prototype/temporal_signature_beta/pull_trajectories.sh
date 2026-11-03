#!/usr/bin/env bash
# pull_trajectories.sh — 从云端拉取 trajectories.jsonl 到本地（SPEC §4.6.13 [1]）
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOCAL="$SCRIPT_DIR/data/trajectories_cloud.jsonl"
REMOTE="dreambuddy-remote:/home/luke/dreambuddy/.workbuddy/agent_mail/trajectories.jsonl"

mkdir -p "$SCRIPT_DIR/data"
scp "$REMOTE" "$LOCAL"
echo "pulled $(wc -l < "$LOCAL") lines -> $LOCAL"
