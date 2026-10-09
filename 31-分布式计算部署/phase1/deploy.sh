#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 一键部署入口
# 用法:
#   1. scp 仓库到云服务器: scp -r dreambuddy-v2 luke@<云IP>:~/dreambuddy
#   2. ssh luke@<云IP>
#   3. cd ~/dreambuddy && bash 31-分布式计算部署/phase1/deploy.sh
#
# 也可单独执行每步:
#   sudo bash 01-cloud-init.sh    # 环境初始化
#   bash 02-deploy-data.sh        # 数据层
#   bash 03-deploy-frontend.sh    # 前端
#   bash 04-deploy-v15.sh         # V15 策略
#   sudo bash 05-nginx-ssl.sh     # Nginx + SSL
#   sudo bash 06-deploy-hermes.sh # 飞书网关
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

echo "============================================"
echo "  Dreambuddy V2 — Phase 1 部署"
echo "  云端核心上线: 前端 + V15 + 数据层 + Nginx + Hermes"
echo "============================================"
echo ""

# ── 检查 .env.cloud ──
DEPLOY_USER="${DEPLOY_USER:-luke}"
ENV_FILE="/home/${DEPLOY_USER}/.config/dreambuddy/.env.cloud"

if [ ! -f "${ENV_FILE}" ]; then
    echo ">>> [0/7] 配置 .env.cloud"
    echo "  .env.cloud 不存在, 从模板创建..."
    mkdir -p "$(dirname "${ENV_FILE}")"
    cp .env.cloud.example "${ENV_FILE}"
    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${ENV_FILE}"
    echo ""
    echo "  ⚠ 请编辑 ${ENV_FILE} 填写密钥后重新运行:"
    echo "     vim ${ENV_FILE}"
    echo "  必填项: POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD, NEXTAUTH_SECRET, DOMAIN"
    exit 1
fi
echo "✓ .env.cloud 就绪"

# ── 逐步部署 ──
echo ""
echo ">>> [1/7] 云端环境初始化"
if [ "$(id -u)" -ne 0 ]; then
    echo "  需要 sudo 权限, 切换..."
    sudo bash 01-cloud-init.sh
else
    bash 01-cloud-init.sh
fi

echo ""
echo ">>> [2/7] 数据层部署 (PG + Redis + MinIO)"
bash 02-deploy-data.sh

echo ""
echo ">>> [3/7] 前端部署 (Next.js 15)"
bash 03-deploy-frontend.sh

echo ""
echo ">>> [4/7] V15 马丁策略部署"
bash 04-deploy-v15.sh

echo ""
echo ">>> [5/7] Nginx 反代 + SSL"
if [ "$(id -u)" -ne 0 ]; then
    sudo bash 05-nginx-ssl.sh
else
    bash 05-nginx-ssl.sh
fi

echo ""
echo ">>> [6/7] 飞书网关 (Hermes) 部署"
if [ "$(id -u)" -ne 0 ]; then
    sudo bash 06-deploy-hermes.sh
else
    bash 06-deploy-hermes.sh
fi

echo ""
echo ">>> [7/7] 日志轮转 + 健康检查"
# 安装 logrotate 配置
if [ -f logrotate-dreambuddy.conf ]; then
    cp logrotate-dreambuddy.conf /etc/logrotate.d/dreambuddy 2>/dev/null && echo "✓ logrotate 配置已安装" || echo "⚠ logrotate 安装跳过 (非 root)"
fi

# 运行健康检查
echo "  运行健康检查..."
bash healthcheck.sh || echo "  ⚠ 部分检查未通过, 请查看上方报告"

# ── 完成 ──
set -a
source "${ENV_FILE}"
set +a

echo ""
echo "============================================"
echo "  Phase 1 部署完成"
echo "============================================"
echo "  前端:      https://${DOMAIN}"
echo "  V15 盯盘:  每 5min poll_light + 每 15min orchestrator"
echo "  V15 API:   http://127.0.0.1:8771 (决策) + http://127.0.0.1:8770 (资金管理)"
echo "  数据层:    PG:5432 Redis:6379 MinIO:9000"
echo "  飞书网关:  hermes-gateway.service"
echo ""
echo "  验证:"
echo "    bash healthcheck.sh"
echo "    curl -s https://${DOMAIN}/health"
echo "    systemctl list-timers v15-*"
echo "    pm2 list"
echo "    docker ps"
echo "    systemctl status hermes-gateway v15-api v15-capital-api"
echo ""
echo "  更新代码: bash update.sh"
echo "============================================"
