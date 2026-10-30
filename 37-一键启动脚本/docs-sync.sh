#!/bin/bash
# docs-sync.sh — 文档自动同步（三端协作 P0/P1，云端）
# 契约见 44-三端协作架构系统/docs/tech/SPEC-dual-end-collab-governance.md §5.2：
#   1) 只读：只 fetch + ff-only 拉取，从不推送
#   2) 不绕 G4：仅当待同步提交的**全部**变更都落在文档路径内才拉取；
#      任何含代码/配置的提交一律跳过，交由 update.sh + G4 部署窗口
#   3) 失败可见：拉取失败 exit 2（systemd/journal 变红，Actions 同步失败）；
#      网络不可达 FAIL-OPEN exit 0（避免告警风暴）
# 用法：由 docs-sync.timer（15 分钟）或 GitHub Actions SSH 触发（forced command）调用
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO/logs"
LOG_FILE="$LOG_DIR/docs-sync.log"
STATUS_FILE="$LOG_DIR/docs-sync.status.json"
LOCK_FILE="$LOG_DIR/docs-sync.lock"
MAX_LOG_BYTES=1048576
WATCH_PATHS=("44-三端协作架构系统" "docs" "developers")

mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%F %T')] $1" >> "$LOG_FILE"; printf '%s\n' "$1"; }

write_status() {
  local result="$1" head_sha="${2:-}" remote_sha="${3:-}"
  printf '{"ts":"%s","result":"%s","head":"%s","remote":"%s"}\n' \
    "$(date '+%F %T')" "$result" "$head_sha" "$remote_sha" > "$STATUS_FILE"
}

# 单实例：timer 与 Actions 触发互斥，避免并发 fetch/pull 撞 index.lock
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "SKIP: 已有实例在运行，本次退出"
  exit 0
fi

# 日志轮转：超过 1MB 保留一份历史后截断（不引入 logrotate 依赖）
if [ -f "$LOG_FILE" ] && [ "$(wc -c < "$LOG_FILE")" -gt "$MAX_LOG_BYTES" ]; then
  cp "$LOG_FILE" "$LOG_FILE.1"
  : > "$LOG_FILE"
fi

cd "$REPO" || { log "FATAL: 无法进入仓库目录"; exit 1; }

# 1. 只拉取远端引用，不改动工作区
if ! git fetch origin main >> "$LOG_FILE" 2>&1; then
  log "WARN: git fetch 失败（网络或凭证问题），本次跳过（FAIL-OPEN）"
  write_status "fetch_failed"
  exit 0
fi

LOCAL_HEAD=$(git rev-parse HEAD 2>/dev/null || true)
REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null || true)

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
  log "OK: 已同步（$LOCAL_HEAD），无需拉取"
  write_status "in_sync" "$LOCAL_HEAD" "$REMOTE_HEAD"
  exit 0
fi

ALL_CHANGED=$(git diff --name-only "$LOCAL_HEAD" "$REMOTE_HEAD" 2>/dev/null || true)
DOC_CHANGED=$(git diff --name-only "$LOCAL_HEAD" "$REMOTE_HEAD" -- "${WATCH_PATHS[@]}" 2>/dev/null || true)

if [ -z "$DOC_CHANGED" ]; then
  log "SKIP: 远端有新提交（$REMOTE_HEAD）但文档路径无变更"
  write_status "no_doc_change" "$LOCAL_HEAD" "$REMOTE_HEAD"
  exit 0
fi

# 2. 关键门禁：出现任何非文档路径变更即不拉取（避免绕过 G4 部署窗口）
if [ "$ALL_CHANGED" != "$DOC_CHANGED" ]; then
  log "SKIP: 待同步提交含非文档路径变更，交由 update.sh + G4 处理"
  echo "$ALL_CHANGED" | grep -vE "^(44-三端协作架构系统|docs|developers)/" | head -10 >> "$LOG_FILE"
  write_status "code_pending" "$LOCAL_HEAD" "$REMOTE_HEAD"
  exit 0
fi

# 3. 文档路径存在未提交的**已跟踪**改动时拒绝覆盖（避免冲掉人工修改）
#    未跟踪文件（??）不阻断：云端侧评审草稿常以新文件落盘，且 ff-only 拉取不会覆盖它们
DIRTY=$(git status --porcelain -- "${WATCH_PATHS[@]}" 2>/dev/null | grep -v '^??' || true)
if [ -n "$DIRTY" ]; then
  log "FAIL: 文档路径存在未提交改动，拒绝覆盖"
  printf '%s\n' "$DIRTY" | head -10 >> "$LOG_FILE"
  write_status "dirty_worktree" "$LOCAL_HEAD" "$REMOTE_HEAD"
  exit 2
fi

log "INFO: 文档路径变更，开始 ff-only 拉取："
echo "$DOC_CHANGED" | head -20 >> "$LOG_FILE"

# 4. ff-only 拉取（不产生合并提交）
if git pull --ff-only origin main >> "$LOG_FILE" 2>&1; then
  NEW_HEAD=$(git rev-parse HEAD)
  log "SYNCED: $LOCAL_HEAD -> $NEW_HEAD"
  write_status "synced" "$NEW_HEAD" "$REMOTE_HEAD"
  exit 0
else
  log "FAIL: ff-only 拉取失败（本地与远端冲突），需人工处理"
  write_status "pull_failed" "$LOCAL_HEAD" "$REMOTE_HEAD"
  exit 2
fi
