#!/usr/bin/env bash
# 三端代码同步编排器：本地 → GitHub → 云端
# 用法: bash 31-分布式计算部署/phase7/11-sync-to-cloud.sh [commit message]
# 流程:
#   1. 本地 git add -A && git commit (如有未提交改动)
#   2. git push origin <branch>
#   3. 云端 stash → git pull --ff-only → stash pop (冲突取 GitHub 版)
#   4. 记录同步日志到 sync-log.jsonl
# 硬约束: 禁止 rsync/scp 直传代码，必须经 GitHub 中转。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

BRANCH="${SYNC_BRANCH:-main}"
CLOUD_HOST="${CLOUD_HOST:-dreambuddy-remote}"
CLOUD_REPO="${CLOUD_REPO:-/home/luke/dreambuddy}"
LOG_FILE="$REPO_ROOT/31-分布式计算部署/phase7/sync-log.jsonl"
MSG="${1:-sync: 本地代码同步到云端 ($(date -u '+%Y-%m-%d %H:%M UTC'))}"

TS="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "=== 三端同步 $TS ==="
echo "分支: $BRANCH"

# ── 1. 本地提交 ──
if [[ -n "$(git status --porcelain)" ]]; then
  echo "[1/4] 本地有未提交改动，正在提交..."
  git add -A
  git commit -m "$MSG" --no-edit
else
  echo "[1/4] 本地无未提交改动，跳过 commit"
fi
LOCAL_BEFORE="$(git rev-parse HEAD)"

# ── 2. 推送到 GitHub ──
echo "[2/4] 推送到 GitHub origin/$BRANCH ..."
# 如果当前分支不是目标分支，先推送当前分支再快进目标分支
CUR_BRANCH="$(git branch --show-current)"
if [[ "$CUR_BRANCH" != "$BRANCH" ]]; then
  git push origin "$CUR_BRANCH"
  git push origin "$CUR_BRANCH:$BRANCH"
else
  git push origin "$BRANCH"
fi
GITHUB_HEAD="$(git ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')"
echo "      GitHub HEAD = $GITHUB_HEAD"

# ── 3. 云端拉取 ──
echo "[3/4] 云端从 GitHub 拉取..."
ssh -o BatchMode=yes "$CLOUD_HOST" bash -s <<EOF
set -e
cd "$CLOUD_REPO"
sudo -n -u luke -H git stash push -u -m "sync-auto-$TS" 2>/dev/null || true
sudo -n -u luke -H git -C "$CLOUD_REPO" pull --ff-only origin "$BRANCH"
# 恢复 stash，代码文件冲突取 GitHub 版
if sudo -n -u luke -H git stash list | grep -q "sync-auto-$TS"; then
  sudo -n -u luke -H git stash pop 2>/dev/null || {
    echo "[stash] 检测到冲突，代码文件取 GitHub 版"
    for f in \$(sudo -n -u luke -H git diff --name-only --diff-filter=U); do
      sudo -n -u luke -H git checkout --theirs "\$f"
      sudo -n -u luke -H git add "\$f"
    done
    sudo -n -u luke -H git stash drop
  }
fi
CLOUD_HEAD=\$(sudo -n -u luke -H git rev-parse HEAD)
echo "CLOUD_HEAD=\$CLOUD_HEAD"
EOF
CLOUD_HEAD="$(ssh -o BatchMode=yes "$CLOUD_HOST" "sudo -n -u luke -H git -C '$CLOUD_REPO' rev-parse HEAD")"

# ── 4. 记录同步日志 ──
echo "[4/4] 记录同步日志..."
STATUS="success"
if [[ "$CLOUD_HEAD" != "$GITHUB_HEAD" ]]; then
  STATUS="misaligned"
fi
echo "{\"ts\":\"$TS\",\"branch\":\"$BRANCH\",\"local_head\":\"$LOCAL_BEFORE\",\"github_head\":\"$GITHUB_HEAD\",\"cloud_head\":\"$CLOUD_HEAD\",\"status\":\"$STATUS\",\"actor\":\"sync-to-cloud\"}" >> "$LOG_FILE"

echo
if [[ "$STATUS" == "success" ]]; then
  echo "✅ 同步完成: 本地→GitHub→云端 三端对齐 $GITHUB_HEAD"
  exit 0
else
  echo "❌ 同步异常: GitHub=$GITHUB_HEAD 云端=$CLOUD_HEAD"
  exit 1
fi
