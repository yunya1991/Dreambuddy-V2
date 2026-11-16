#!/bin/bash
# ============================================================
# Dreambuddy — 前端双实例滚动部署（蓝绿）
# 前置: systemd 模板单元 dreambuddy-frontend@.service（3001/3002 双实例）
#       nginx upstream dreambuddy_next 同时挂载 3001/3002 + proxy_next_upstream
# 效果: build 后逐个重启实例，另一实例继续服务，nginx 自动故障转移 → 无 502 白屏窗口
# 用法: sudo bash 05-frontend-rolling-deploy.sh
# ============================================================
set -euo pipefail

FRONTEND_DIR="${FRONTEND_DIR:-/home/luke/dreambuddy/3.1-FRONTEND}"
DEPLOY_USER="${DEPLOY_USER:-luke}"
PORTS="${PORTS:-3001 3002}"

health() {
    curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$1/login"
}

wait_healthy() {
    local port="$1"
    for _ in $(seq 1 30); do
        if health "$port"; then
            echo "  ✔ ${port} healthy"
            return 0
        fi
        sleep 2
    done
    echo "  ✘ ${port} health check failed (60s)"
    return 1
}

echo ">>> [1/3] 构建前端"
sudo -u "$DEPLOY_USER" bash -lc "cd '$FRONTEND_DIR' && pnpm build"

echo ">>> [2/3] 逐个重启实例（另一实例保持服务）"
for port in $PORTS; do
    echo "  restart dreambuddy-frontend@${port}"
    systemctl restart "dreambuddy-frontend@${port}"
    wait_healthy "$port"
done

echo ">>> [3/3] 校验 nginx 与实例状态"
nginx -t
systemctl reload nginx
systemctl is-active dreambuddy-frontend@3001 dreambuddy-frontend@3002

echo "✓ 滚动部署完成（全程无 502 窗口）"
