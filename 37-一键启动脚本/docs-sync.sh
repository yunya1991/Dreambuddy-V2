#!/bin/bash
# docs-sync.sh — 文档自动同步（三端协作 P0）：定时拉取文档相关路径变更
# 原则：只拉不推、ff-only、FAIL-OPEN（失败告警不阻塞，不影响云端运行态）
# 机制：fetch 后比对本地与远端 HEAD，仅当监控路径有变更时执行 ff-only 拉取
# 产出：日志写入 logs/docs-sync.log
# 用法：由 systemd timer（docs-sync.timer，15 分钟周期）自动调用，也可手动执行
set -uo pipefail

REPO="/home/luke/dreambuddy"
LOG_DIR="$REPO/logs"
LOG_FILE="$LOG_DIR/docs-sync.log"
WATCH_PATHS=("44-三端协作架构系统" "docs" "developers")

log() {
  echo "[$(date '+%F %T')] $1" >> "$LOG_FILE"
}

mkdir -p "$LOG_DIR"
cd "$REPO" || { log "FATAL: 无法进入仓库目录"; exit 1; }

# 1. 拉取远端引用（不改动工作区）
if ! git fetch origin main >> "$LOG_FILE" 2>&1; then
  log "WARN: git fetch 失败（网络或凭证问题），本次跳过，FAIL-OPEN"
  exit 0
fi

LOCAL_HEAD=$(git rev-parse HEAD 2>/dev/null)
REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null)

if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
  log "OK: 本地与远端一致（$LOCAL_HEAD），无需同步"
  exit 0
fi

# 2. 检查监控路径是否有变更
CHANGED_FILES=$(git diff --name-only "$LOCAL_HEAD" "$REMOTE_HEAD" -- "${WATCH_PATHS[@]}" 2>/dev/null)
if [ -z "$CHANGED_FILES" ]; then
  log "OK: 远端有新提交（$REMOTE_HEAD）但监控路径无变更，跳过拉取（代码变更走 update.sh + G4 门禁）"
  exit 0
fi

log "INFO: 检测到文档路径变更，开始 ff-only 拉取："
echo "$CHANGED_FILES" | head -20 >> "$LOG_FILE"

# 3. ff-only 拉取（不产生合并提交；本地运行时数据冲突时失败并告警）
if git pull --ff-only origin main >> "$LOG_FILE" 2>&1; then
  NEW_HEAD=$(git rev-parse HEAD)
  log "OK: 同步完成 $LOCAL_HEAD -> $NEW_HEAD"
else
  log "WARN: ff-only 拉取失败（可能本地运行时数据与远端冲突），FAIL-OPEN 跳过，待人工处理"
  exit 0
fi
