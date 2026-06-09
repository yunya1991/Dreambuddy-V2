#!/bin/bash
# ============================================================
# 6-TRADING 腾讯云部署 — 01 环境依赖安装
# 目标: Ubuntu 22.04 LTS
# 用法: sudo bash 01-install-deps.sh
# ============================================================
set -e

echo "=== 6-TRADING 环境安装 ==="

apt update -y && apt upgrade -y
apt install -y curl wget git build-essential unzip jq

# Python 3.12
add-apt-repository -y ppa:deadsnakes/ppa
apt install -y python3.12 python3.12-venv python3.12-dev
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# Node.js 24 + npm
curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
apt install -y nodejs

# Hermes CLI
pip3 install hermes-cli --break-system-packages 2>/dev/null || pip3 install hermes-cli

# Lark CLI
npm install -g @larksuite/cli

# Python deps
pip3 install requests pandas numpy --break-system-packages 2>/dev/null || pip3 install requests pandas numpy

# 用户和目录
id -u luke &>/dev/null || useradd -m -s /bin/bash luke
mkdir -p /home/luke/tmp /home/luke/.hermes/{logs,sessions,cron,skills,scripts}
chown -R luke:luke /home/luke/tmp /home/luke/.hermes

echo ""
echo "=== 依赖安装完成 ==="
python3 --version
node --version
npm --version
echo "下一步: bash 02-clone-and-config.sh"
