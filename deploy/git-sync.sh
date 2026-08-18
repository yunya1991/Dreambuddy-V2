#!/bin/bash
# ============================================================
# Dreambuddy-V2 Git 日常同步脚本
# 功能：拉取远端最新代码（镜像加速）+ 推送本地修改（直连 GitHub）
# 用法：
#   bash git-sync.sh status          # 查看本地与远端状态（默认）
#   bash git-sync.sh pull            # 仅拉取远端最新代码
#   bash git-sync.sh push "提交说明"  # 提交并推送本地修改
#   bash git-sync.sh sync "提交说明"  # 先拉取再推送（完整同步）
# ============================================================
set -e

REPO_DIR="/home/ubuntu/Dreambuddy-V2-main"
GITHUB_URL="https://github.com/yunya1991/Dreambuddy-V2.git"
MIRROR_URL="https://gh-proxy.com/https://github.com/yunya1991/Dreambuddy-V2.git"

cd "$REPO_DIR"

# 确保 remote 配置正确：fetch 走镜像加速，push 直连 GitHub
ensure_remote() {
    git remote set-url origin "$MIRROR_URL" 2>/dev/null || git remote add origin "$MIRROR_URL"
    git remote set-url --push origin "$GITHUB_URL"
}

ensure_remote

case "${1:-status}" in
    pull)
        echo "=== 拉取远端最新代码（镜像加速）==="
        git pull --ff-only origin main 2>/dev/null || git pull --rebase origin main
        echo "✓ 拉取完成"
        ;;
    push)
        MSG="${2:-update $(date '+%Y-%m-%d %H:%M')}"
        echo "=== 本地修改 ==="
        git status -s
        if [ -z "$(git status -s)" ]; then
            echo "无本地修改，无需推送"
            exit 0
        fi
        git add -A
        git commit -m "$MSG"
        echo "=== 推送到 GitHub ==="
        git push origin main
        echo "✓ 推送完成"
        ;;
    sync)
        MSG="${2:-sync $(date '+%Y-%m-%d %H:%M')}"
        echo "=== 1/2 拉取远端最新 ==="
        git pull --rebase origin main || echo "（拉取有冲突，请先手动处理）"
        echo "=== 2/2 推送本地修改 ==="
        if [ -n "$(git status -s)" ]; then
            git add -A && git commit -m "$MSG"
        fi
        git push origin main
        echo "✓ 同步完成"
        ;;
    status|*)
        echo "=== 仓库状态 ==="
        git status -sb | head -3
        echo "--- 本地修改 ---"
        git status -s
        echo "--- 最近提交 ---"
        git log --oneline -3 2>/dev/null || echo '(无提交记录)'
        ;;
esac
