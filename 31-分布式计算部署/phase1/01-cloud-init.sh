#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 云端环境初始化
# 目标: Ubuntu 22.04 LTS (腾讯云轻量 4C8G 香港节点)
# 用法: sudo bash 01-cloud-init.sh
# 产出: Docker + Node.js 22 + Python 3.12 + PM2 + Git + 用户/目录
# ============================================================
set -e

echo "============================================"
echo "  Dreambuddy V2 — Phase 1 云端环境初始化"
echo "============================================"

# ── 1. 系统更新 + 基础依赖 ──
echo ">>> [1/6] 系统更新 + 基础依赖"
apt update -y && apt upgrade -y
apt install -y curl wget git build-essential unzip jq htop vim \
    ca-certificates gnupg lsb-release software-properties-common

# ── 2. Docker ──
echo ">>> [2/6] 安装 Docker"
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    echo "✓ Docker installed"
else
    echo "✓ Docker already installed: $(docker --version)"
fi

# Docker Compose v2 (插件形式随 Docker 安装)
if docker compose version &>/dev/null; then
    echo "✓ Docker Compose v2 ready"
else
    echo "⚠ Docker Compose v2 not found, installing plugin..."
    apt install -y docker-compose-plugin
fi

# ── 3. Node.js 22 + pnpm + PM2 ──
echo ">>> [3/6] 安装 Node.js 22 + pnpm + PM2"
if ! command -v node &>/dev/null || [[ "$(node -v | cut -dv -f2 | cut -d. -f1)" -lt 20 ]]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt install -y nodejs
fi
echo "✓ Node.js: $(node --version)"

# pnpm (全局)
npm install -g pnpm@latest
echo "✓ pnpm: $(pnpm --version)"

# PM2 (进程管理 — 前端 Next.js)
npm install -g pm2@latest
echo "✓ PM2: $(pm2 --version)"

# ── 4. Python 3.12 ──
echo ">>> [4/6] 安装 Python 3.12"
if ! python3.12 &>/dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt install -y python3.12 python3.12-venv python3.12-dev
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
fi
echo "✓ Python: $(python3 --version 2>&1)"

# Python 依赖 (V15 策略需要)
pip3 install --break-system-packages -q requests pandas numpy ccxt python-dotenv || \
    pip3 install requests pandas numpy ccxt python-dotenv

# ── 5. 用户 + 目录 ──
echo ">>> [5/6] 创建用户和目录"
DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"

id -u "${DEPLOY_USER}" &>/dev/null || useradd -m -s /bin/bash "${DEPLOY_USER}"

# 加入 docker 组
usermod -aG docker "${DEPLOY_USER}"

# 目录结构
mkdir -p "${DEPLOY_HOME}/dreambuddy"
mkdir -p "${DEPLOY_HOME}/.config/dreambuddy"
mkdir -p "${DEPLOY_HOME}/logs"

chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${DEPLOY_HOME}/dreambuddy" \
    "${DEPLOY_HOME}/.config" "${DEPLOY_HOME}/logs"

echo "✓ 用户 ${DEPLOY_USER} 就绪, 已加入 docker 组"

# ── 6. 防火墙 ──
echo ">>> [6/6] 配置防火墙 (ufw)"
if ! command -v ufw &>/dev/null; then
    apt install -y ufw
fi
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp       # SSH
ufw allow 80/tcp       # HTTP (Nginx)
ufw allow 443/tcp      # HTTPS (Nginx + SSL)
# 数据库/Redis/MinIO 仅 127.0.0.1 访问, 不开放公网
echo "y" | ufw enable
echo "✓ ufw 已配置: 仅开放 22/80/443"

# ── 汇总 ──
echo ""
echo "============================================"
echo "  Phase 1 环境初始化完成"
echo "============================================"
echo "  Docker:    $(docker --version)"
echo "  Compose:   $(docker compose version 2>&1 | head -1)"
echo "  Node.js:   $(node --version)"
echo "  pnpm:      $(pnpm --version)"
echo "  PM2:       $(pm2 --version)"
echo "  Python:    $(python3 --version 2>&1)"
echo "  部署用户:  ${DEPLOY_USER}"
echo "  仓库目录:  ${DEPLOY_HOME}/dreambuddy"
echo ""
echo "  下一步:"
echo "    1. ssh ${DEPLOY_USER}@<云IP>"
echo "    2. cd ~/dreambuddy && git clone <repo_url> ."
echo "    3. cp 31-分布式计算部署/phase1/.env.cloud .env  # 填写密钥"
echo "    4. bash 31-分布式计算部署/phase1/02-deploy-data.sh"
echo "============================================"
