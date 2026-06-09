#!/bin/bash
# ============================================================
# 6-TRADING 腾讯云部署 — 02 代码部署 + 配置
# 用法: bash 02-clone-and-config.sh
# 前置: 01 已完成, .env 文件已放到 /home/luke/.hermes/.env
# ============================================================
set -e

echo "=== 6-TRADING 代码部署 ==="

# ── Clone 仓库 ──
cd /home/luke/tmp
if [ -d "Dreambuddy-V2" ]; then
    echo "Repo exists, pulling latest..."
    cd Dreambuddy-V2 && git pull origin main
else
    git clone https://github.com/yunya1991/Dreambuddy-V2.git
    cd Dreambuddy-V2
fi

# ── 检查 .env ──
if [ ! -f /home/luke/.hermes/.env ]; then
    echo "ERROR: /home/luke/.hermes/.env 不存在！"
    echo "请先从 Windows 复制: C:\\Users\\luke.zhang\\.hermes\\.env"
    echo "scp .env luke@<云服务器IP>:/home/luke/.hermes/.env"
    exit 1
fi
echo "✓ .env found"

# ── Lark CLI 绑定 ──
echo "Binding lark-cli to Hermes..."
lark-cli config bind --source hermes --identity bot-only

# ── 路径替换 C:\tmp → /home/luke/tmp ──
echo "Replacing Windows paths..."
find /home/luke/.hermes/cron -name "*.json" -exec sed -i 's|C:\\\\tmp|/home/luke/tmp|g' {} +
find /home/luke/.hermes/skills -name "*.md" -exec sed -i 's|C:/tmp|/home/luke/tmp|g' {} +

# ── 创建必要目录 ──
mkdir -p /home/luke/.hermes/logs
chown -R luke:luke /home/luke/tmp /home/luke/.hermes

# ── 复制 poller 脚本 ──
if [ -f /home/luke/tmp/deploy/group_poller.py ]; then
    cp /home/luke/tmp/deploy/group_poller.py /home/luke/tmp/group_poller.py
    echo "✓ group_poller.py deployed"
fi

# ── 初始化频道目录（防止重启丢失群组） ──
cat > /home/luke/.hermes/channel_directory.json << 'CDEOF'
{
  "platforms": {
    "feishu": [
      {"id": "oc_0b8badf8770b13c9359145a939a3eb8c", "name": "DM", "type": "dm"},
      {"id": "oc_36c575b6f39a8df3dd75057a96685a21", "name": "Trading-Research", "type": "group"},
      {"id": "oc_36c8543cea823b7546fcaad55d111f9f", "name": "Trading-Desk", "type": "group"},
      {"id": "oc_9cf9f141613b4e6a0f34651843cf8b9b", "name": "Trading-Management", "type": "group"},
      {"id": "oc_8868a5c84f3d8427afa9ed1a9ad7fb76", "name": "Trading-Review", "type": "group"},
      {"id": "oc_20fcedf0c35035568ea8fa947380f75d", "name": "Trading-RiskControl", "type": "group"}
    ]
  }
}
CDEOF
echo "✓ channel_directory.json initialized"

echo ""
echo "=== 代码部署完成 ==="
echo "下一步: sudo bash 03-systemd-services.sh"
