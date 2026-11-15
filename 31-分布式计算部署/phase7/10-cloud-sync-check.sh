#!/usr/bin/env bash
# 三端同步状态检查（本地 → GitHub → 云端）
# 用法: bash 31-分布式计算部署/phase7/10-cloud-sync-check.sh
# 输出本地 / GitHub / 云端三地的 git HEAD，判定是否对齐。
# 退出码: 0=全对齐, 1=有偏差
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="${SYNC_BRANCH:-main}"
CLOUD_HOST="${CLOUD_HOST:-dreambuddy-remote}"
CLOUD_REPO="${CLOUD_REPO:-/home/luke/dreambuddy}"

echo "=== 三端同步状态检查 (branch=$BRANCH) ==="
echo "时间: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo

# 1. 本地 HEAD
LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null || echo 'UNKNOWN')"
LOCAL_BRANCH="$(git branch --show-current 2>/dev/null || echo 'detached')"
echo "[本地]   branch=$LOCAL_BRANCH  HEAD=$LOCAL_HEAD"

# 2. GitHub 远端 HEAD
GITHUB_HEAD="$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}' || echo 'UNKNOWN')"
echo "[GitHub] branch=$BRANCH  HEAD=$GITHUB_HEAD"

# 3. 云端 HEAD
CLOUD_HEAD="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$CLOUD_HOST" \
  "sudo -n -u luke -H git -C '$CLOUD_REPO' rev-parse HEAD 2>/dev/null" \
  || echo 'UNREACHABLE')"
echo "[云端]   branch=$BRANCH  HEAD=$CLOUD_HEAD"
echo

# 判定
ALIGNED=true
if [[ "$LOCAL_HEAD" != "$GITHUB_HEAD" ]]; then
  echo "⚠️  本地与 GitHub 不对齐"
  ALIGNED=false
fi
if [[ "$CLOUD_HEAD" != "$GITHUB_HEAD" ]]; then
  echo "⚠️  云端与 GitHub 不对齐（需要在云端执行 git pull）"
  ALIGNED=false
fi

if [[ "$ALIGNED" == true ]]; then
  echo "✅ 三端完全对齐: $GITHUB_HEAD"
  exit 0
else
  echo "❌ 三端未对齐，请按 本地→GitHub→云端 路径同步"
  exit 1
fi
