#!/bin/bash
# ============================================================
# Dreambuddy-V2 Git 跟踪关系建立/修复脚本
# 用途：
#   1. 新环境部署后，把本地代码目录关联到 GitHub 远端
#   2. 跟踪关系损坏时重建
# 核心经验（2026-08-08 实践总结）：
#   - GitHub 直连在国内慢/超时，拉取走 gh-proxy 镜像加速
#   - 推送需直连 GitHub（镜像只读，不支持 push）
#   - 用 reset --mixed 关联远端，保留本地现有文件不被覆盖
# 用法：bash git-setup-tracking.sh
# ============================================================
set -e

REPO_DIR="/home/ubuntu/Dreambuddy-V2-main"
GITHUB_URL="https://github.com/yunya1991/Dreambuddy-V2.git"
# 可用镜像列表（按优先级，拉取失败会自动尝试下一个）
MIRRORS=(
    "https://gh-proxy.com/https://github.com/yunya1991/Dreambuddy-V2.git"
    "https://mirror.ghproxy.com/https://github.com/yunya1991/Dreambuddy-V2.git"
    "https://ghproxy.net/https://github.com/yunya1991/Dreambuddy-V2.git"
)

cd "$REPO_DIR"

# 1. 初始化仓库（若尚未初始化）
if [ ! -d .git ]; then
    echo "=== 初始化 git 仓库 ==="
    git init
    git symbolic-ref HEAD refs/heads/main
fi

# 2. 配置 remote（fetch 先用第一个镜像，push 直连 GitHub）
echo "=== 配置 remote ==="
git remote remove origin 2>/dev/null || true
git remote add origin "${MIRRORS[0]}"
git remote set-url --push origin "$GITHUB_URL"

# 3. 拉取远端 main（依次尝试镜像，浅拉取加速）
if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
    echo "=== 拉取远端 main（浅拉取 + 镜像加速）==="
    OK=0
    for m in "${MIRRORS[@]}"; do
        echo ">>> 尝试: $m"
        if timeout 60 git fetch --depth 1 "$m" main:refs/remotes/origin/main 2>&1 | tail -2; then
            if git rev-parse --verify origin/main >/dev/null 2>&1; then
                echo ">>> 成功"
                OK=1
                break
            fi
        fi
        echo ">>> 失败，换下一个镜像"
    done
    [ "$OK" = "1" ] || { echo "所有镜像均失败，请检查网络或配置代理"; exit 1; }
else
    echo "=== origin/main 已存在，跳过拉取 ==="
fi

# 4. 关联本地 main 到远端（保留本地文件）
echo "=== 建立跟踪（保留本地文件）==="
git reset --mixed origin/main
git branch --set-upstream-to=origin/main main

# 5. 结果确认
echo "=== 完成 ==="
echo "远端提交: $(git rev-parse --short origin/main)"
echo "本地与远端差异: $(git status -s | wc -l) 项"
git status -s | head -10
echo ""
echo "remote 配置:"
git remote -v
