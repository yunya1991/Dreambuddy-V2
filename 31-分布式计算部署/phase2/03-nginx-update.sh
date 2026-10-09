#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2: Nginx 配置更新
# 作用: 添加三屏趋势 + BDSM API (8765) 的路径代理
# 用法: sudo bash 03-nginx-update.sh
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

if [ -f "${ENV_FILE}" ]; then
    set -a
    source "${ENV_FILE}"
    set +a
fi

DOMAIN="${DOMAIN:-}"
NGINX_CONF="/etc/nginx/sites-available/dreambuddy"

echo "============================================"
echo "  Phase 2 — Nginx 配置更新"
echo "============================================"

if [ ! -f "${NGINX_CONF}" ]; then
    echo "ERROR: ${NGINX_CONF} 不存在，请先执行 Phase 1"
    exit 1
fi

# 检查是否已配置
if grep -q "api/trend" "${NGINX_CONF}"; then
    echo "✓ /api/trend 已配置，跳过"
else
    echo ">>> 添加 /api/trend 代理 (→ 8765)"
    # 在 /api/capital/ 之后插入
    sed -i '/location \/api\/capital\//,/}/a\
\
    # 三屏趋势 + BDSM API (易经数据服务 8765)\
    location /api/trend/ {\
        proxy_pass http://127.0.0.1:8765/;\
        proxy_http_version 1.1;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
        proxy_read_timeout 120s;\
    }' "${NGINX_CONF}"
fi

# 测试并重载
echo ">>> 测试 Nginx 配置"
nginx -t && systemctl reload nginx

echo ""
echo "=== 验证 ==="
echo "  三屏趋势: https://${DOMAIN}/api/trend/api/trend-screen?symbol=BTC"
echo "  BDSM快照: https://${DOMAIN}/api/trend/api/bdsm/snapshot"
echo ""
echo "✓ Nginx 配置更新完成"
