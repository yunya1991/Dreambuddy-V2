#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 2: 易经数据服务 (port 8765) 部署
# 作用: 三屏趋势 + BDSM 快照 API，供前端 three-screens / bdsm 页面调用
# 用法: sudo bash 01-deploy-yijing-data-server.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
YIJING_DIR="${REPO_DIR}/11-易经推理系统"
VENV="/home/${DEPLOY_USER}/venv-trading"
LOG_DIR="/home/${DEPLOY_USER}/logs/yijing"

echo "============================================"
echo "  Phase 2 — 易经数据服务 (8765) 部署"
echo "============================================"

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. 安装依赖（若缺）
echo ">>> [1/3] 检查依赖"
"${VENV}/bin/pip" install requests pandas numpy ccxt python-dotenv scikit-learn lightgbm 2>/dev/null | tail -1

# 3. 本地启动测试（3秒）
echo ">>> [2/3] 启动测试"
cd "${YIJING_DIR}"
"${VENV}/bin/python3" -c "import data_server_fixed; print('import OK')" 2>&1 | tail -3

# 4. 安装 systemd service
echo ">>> [3/3] 安装 systemd service"
cp "${SCRIPT_DIR}/yijing-data-server.service" /etc/systemd/system/yijing-data-server.service
systemctl daemon-reload
systemctl enable --now yijing-data-server.service
sleep 3

# 5. 验证
echo ""
echo "=== 服务状态 ==="
systemctl is-active yijing-data-server.service && echo "✓ running" || echo "✗ failed"

echo "=== 端口监听 ==="
ss -tlnp | grep 8765 || echo "⚠️  8765 未监听"

echo "=== API 测试 ==="
curl -s -m 30 "http://127.0.0.1:8765/api/bdsm/snapshot" 2>&1 | head -c 200
echo ""

echo ""
echo "============================================"
echo "  ✓ 易经数据服务部署完成"
echo "  日志: ${LOG_DIR}/data-server.log"
echo "  命令: systemctl status yijing-data-server"
echo "============================================"
