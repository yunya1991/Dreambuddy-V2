#!/bin/bash
# 44 三端协作系统 — 技术文档双向同步工具
# SPEC: 44-三端协作架构系统/docs/tech/SPEC-dual-end-collab-governance.md §5.3
#
# 用法：
#   bash docs_sync.sh status
#   bash docs_sync.sh pull [--end local|cloud]   # 默认 local
#   bash docs_sync.sh push "<提交说明>" [--allow-main]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCOPE="44-三端协作架构系统"
END="local"

cd "$REPO_ROOT"

say() { printf '%s\n' "$*"; }
die() { printf 'BLOCK  %s\n' "$*" >&2; exit 1; }

parse_end() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --end) END="${2:-}"; shift 2 ;;
      *) shift ;;
    esac
  done
  case "$END" in
    local|cloud) ;;
    *) die "--end 只接受 local 或 cloud" ;;
  esac
}

cmd_status() {
  git fetch origin main --quiet 2>/dev/null || say "（fetch 失败，使用本地 origin/main 引用）"
  local counts behind ahead
  counts="$(git rev-list --left-right --count HEAD...origin/main)"
  behind="$(printf '%s' "$counts" | awk '{print $1}')"
  ahead="$(printf '%s' "$counts" | awk '{print $2}')"
  say "HEAD      : $(git rev-parse --short HEAD)"
  say "origin/main: $(git rev-parse --short origin/main)"
  say "behind/ahead: ${behind}/${ahead}"
  if [ "$behind" = "0" ] && [ "$ahead" = "0" ]; then
    say "同步状态  : SYNCED"
  else
    say "同步状态  : PENDING（待 pull 或待 push）"
  fi
  if [ -n "$(git status --porcelain -- "$SCOPE")" ]; then
    say "44 目录改动: 未提交"
    git status --porcelain -- "$SCOPE"
  else
    say "44 目录改动: 干净"
  fi
}

cmd_pull() {
  [ -z "$(git status --porcelain -- "$SCOPE")" ] || die "44 目录有未提交改动，先提交或清理后再拉取"
  say "=== fetch origin main ==="
  git fetch origin main
  if [ "$END" = "cloud" ]; then
    say "=== 云端路径级同步（仅 $SCOPE，绕开代码部署窗口）==="
    git checkout origin/main -- "$SCOPE"
    git reset --quiet -- "$SCOPE"
  else
    say "=== ff-only 合并 ==="
    git merge --ff-only origin/main
  fi
  say "✓ 同步完成，HEAD=$(git rev-parse --short HEAD)"
}

cmd_push() {
  local msg="${1:-}" allow_main="${2:-}"
  [ -n "$msg" ] || die "缺少提交说明：push \"<msg>\""
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$branch" = "main" ] && [ "$allow_main" != "--allow-main" ]; then
    die "禁止直推 main（SPEC 红线 3）；请改用分支 + PR，确需直推加 --allow-main"
  fi
  [ -n "$(git status --porcelain -- "$SCOPE")" ] || { say "44 目录无改动，无需推送"; return 0; }
  git add -- "$SCOPE"
  git commit -m "$msg"
  git push origin HEAD
  say "✓ 已推送 $branch（仅 $SCOPE）"
}

cmd="${1:-status}"
shift || true
case "$cmd" in
  status) parse_end "$@"; cmd_status ;;
  pull)   parse_end "$@"; cmd_pull ;;
  push)
    msg="${1:-}"; shift || true
    allow=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --allow-main) allow="--allow-main"; shift ;;
        --end) END="${2:-}"; shift 2 ;;
        *) shift ;;
      esac
    done
    cmd_push "$msg" "$allow"
    ;;
  *) die "未知子命令：$cmd（status|pull|push）" ;;
esac
