#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 Nginx 反代 + SSL
# 用法: sudo bash 05-nginx-ssl.sh
# 前置: 03-deploy-frontend.sh 已完成, 域名已解析到服务器 IP
# 产出: Nginx HTTPS 反代 + Let's Encrypt SSL 证书
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

# 加载域名
if [ -f "${ENV_FILE}" ]; then
    set -a
    source "${ENV_FILE}"
    set +a
fi

DOMAIN="${DOMAIN:-}"
if [ -z "${DOMAIN}" ]; then
    echo "ERROR: DOMAIN 未设置"
    echo "请在 ${ENV_FILE} 中设置 DOMAIN=your-domain.com"
    exit 1
fi

echo "============================================"
echo "  Phase 1 — Nginx 反代 + SSL"
echo "  域名: ${DOMAIN}"
echo "============================================"

# ── 1. 安装 Nginx + Certbot ──
echo ">>> [1/4] 安装 Nginx + Certbot"
apt install -y nginx certbot python3-certbot-nginx
echo "✓ Nginx + Certbot installed"

# ── 2. 生成 Nginx 站点配置 ──
echo ">>> [2/4] 生成 Nginx 站点配置"
NGINX_CONF="/etc/nginx/sites-available/dreambuddy"

cat > "${NGINX_CONF}" << 'EOF'
# Dreambuddy V2 — Nginx 反代配置
# 前端 Next.js (3001) + V15 API (8771) + 数据层 (仅本地)

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name DOMAIN_PLACEHOLDER;
    return 301 https://$host$request_uri;
}

# HTTPS 主站
server {
    listen 443 ssl http2;
    server_name DOMAIN_PLACEHOLDER;

    # SSL 证书 (certbot 会自动填充)
    # ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 请求体限制 (模型上传等)
    client_max_body_size 100M;

    # 前端 Next.js
    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # V15 策略 API
    location /api/v15/ {
        proxy_pass http://127.0.0.1:8771/api/v15-ct/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # V15 资金管理 API
    location /api/capital/ {
        proxy_pass http://127.0.0.1:8770/api/capital/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 健康检查 (无需认证)
    location /health {
        proxy_pass http://127.0.0.1:3001/api/health;
        access_log off;
    }

    # MinIO Console (仅限内网, 可选)
    # location /minio/ {
    #     proxy_pass http://127.0.0.1:9001/;
    #     proxy_set_header Host $host;
    #     proxy_set_header X-Real-IP $remote_addr;
    # }

    # 静态资源缓存
    location /_next/static/ {
        proxy_pass http://127.0.0.1:3001;
        expires 365d;
        add_header Cache-Control "public, immutable";
    }

    # gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript;
    gzip_min_length 1000;
}
EOF

# 替换域名占位符
sed -i "s/DOMAIN_PLACEHOLDER/${DOMAIN}/g" "${NGINX_CONF}"
echo "✓ Nginx 配置生成: ${NGINX_CONF}"

# 启用站点
ln -sf "${NGINX_CONF}" /etc/nginx/sites-enabled/dreambuddy
rm -f /etc/nginx/sites-enabled/default

# 测试配置
nginx -t
echo "✓ Nginx 配置测试通过"

# ── 3. 启动 Nginx ──
echo ">>> [3/4] 启动 Nginx (HTTP, 临时)"
systemctl restart nginx
systemctl enable nginx
echo "✓ Nginx started (HTTP only, waiting for SSL)"

# ── 4. Let's Encrypt SSL ──
echo ">>> [4/4] 申请 Let's Encrypt SSL 证书"
echo "  域名: ${DOMAIN}"
echo "  请确认域名 DNS 已解析到本服务器 IP"
echo ""

read -p "域名已解析? 确认申请 SSL 证书? (y/N): " confirm
if [ "${confirm}" != "y" ] && [ "${confirm}" != "Y" ]; then
    echo "跳过 SSL 申请, 稍后手动运行:"
    echo "  certbot --nginx -d ${DOMAIN} -d www.${DOMAIN} --non-interactive --agree-tos -m ${SSL_EMAIL:-admin@${DOMAIN}}"
    echo ""
    echo "  Nginx 当前以 HTTP 模式运行"
    exit 0
fi

certbot --nginx -d "${DOMAIN}" -d "www.${DOMAIN}" \
    --non-interactive \
    --agree-tos \
    -m "${SSL_EMAIL:-admin@${DOMAIN}}" \
    --redirect

echo "✓ SSL 证书已获取并配置"

# 自动续期 (certbot 默认已配置 systemd timer)
echo ""
echo ">>> SSL 自动续期:"
systemctl list-timers certbot.timer --no-pager 2>/dev/null || \
    echo "  (certbot timer 未找到, 检查: certbot renew --dry-run)"

# ── 最终验证 ──
echo ""
echo "============================================"
echo "  Nginx + SSL 部署完成"
echo "============================================"
echo "  HTTPS:     https://${DOMAIN}"
echo "  HTTP→HTTPS: 自动重定向"
echo "  前端:      https://${DOMAIN}"
echo "  V15 API:   https://${DOMAIN}/api/v15/"
echo "  健康检查:  https://${DOMAIN}/health"
echo ""
echo "  SSL 续期:  certbot renew --dry-run"
echo "  Nginx 日志: tail -f /var/log/nginx/access.log"
echo "             tail -f /var/log/nginx/error.log"
echo "============================================"
