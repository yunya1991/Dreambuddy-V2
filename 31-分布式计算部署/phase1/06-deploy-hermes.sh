#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 飞书网关 (Hermes) 部署
# 用法: bash 06-deploy-hermes.sh
# 前置: 01-cloud-init.sh 已完成, Python 3.12 已安装
# 产出: hermes-gateway systemd 服务 (飞书消息网关)
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
HERMES_HOME="${DEPLOY_HOME}/.hermes"
HERMES_VENV="${HERMES_HOME}/.venv"
HERMES_CONFIG="${HERMES_HOME}/config.yaml"
HERMES_ENV="${HERMES_HOME}/.env"
HERMES_LOG_DIR="${HERMES_HOME}/logs"
SOURCE_CONFIG="${REPO_DIR}/deploy/hermes/config.yaml"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"

echo "============================================"
echo "  Phase 1 — 飞书网关 (Hermes) 部署"
echo "============================================"

# ── 检查 ──
if [ ! -f "${SOURCE_CONFIG}" ]; then
    echo "ERROR: ${SOURCE_CONFIG} 不存在"
    exit 1
fi
echo "✓ Hermes 配置源文件存在"

# ── 创建 Hermes 目录结构 ──
echo ">>> [1/6] 创建 Hermes 目录结构"
mkdir -p "${HERMES_HOME}" "${HERMES_LOG_DIR}" "${HERMES_HOME}/memories" "${HERMES_HOME}/cron"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${HERMES_HOME}"
echo "✓ ${HERMES_HOME}/ 目录就绪"

# ── Python 虚拟环境 ──
echo ">>> [2/6] 创建 Hermes Python 虚拟环境"
if [ ! -d "${HERMES_VENV}" ]; then
    sudo -u "${DEPLOY_USER}" python3 -m venv "${HERMES_VENV}"
    echo "✓ venv 创建完成"
else
    echo "✓ venv 已存在, 跳过"
fi

# 安装 hermes-cli
echo "  安装 hermes-cli..."
sudo -u "${DEPLOY_USER}" "${HERMES_VENV}/bin/pip" install --quiet hermes-cli 2>/dev/null || {
    echo "  hermes-cli pip 安装失败, 尝试全局安装..."
    pip3 install --break-system-packages hermes-cli
    # 使用全局 hermes
    HERMES_BIN="hermes"
    ln -sf "$(which hermes)" "${HERMES_VENV}/bin/hermes" 2>/dev/null || true
}
echo "✓ hermes-cli 已安装"

# ── 复制配置 ──
echo ">>> [3/6] 复制 config.yaml"
cp "${SOURCE_CONFIG}" "${HERMES_CONFIG}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${HERMES_CONFIG}"
echo "✓ config.yaml 已复制"

# ── 生成 .env (飞书凭据) ──
echo ">>> [4/6] 生成 Hermes .env (飞书凭据)"

# 加载云端环境变量
set -a
source "${ENV_FILE}" 2>/dev/null || true
set +a

cat > "${HERMES_ENV}" << EOF
# === Hermes 环境变量 ===
HERMES_HOME=${HERMES_HOME}

# === DeepSeek API (Hermes LLM) ===
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}

# === 飞书应用凭据 ===
# 从 .env.cloud 或手动填写
LARK_APP_ID=${LARK_APP_ID:-}
LARK_APP_SECRET=${LARK_APP_SECRET:-}

# === 飞书 OpenAPI (lark-cli) ===
# lark-cli 需要单独绑定: lark-cli auth login
EOF
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${HERMES_ENV}"
chmod 600 "${HERMES_ENV}"
echo "✓ .env 已生成 (请填写飞书凭据)"

# 检查飞书凭据是否已填写
if [ -z "${LARK_APP_ID:-}" ] || [ -z "${LARK_APP_SECRET:-}" ]; then
    echo ""
    echo "  ⚠ 飞书凭据未配置!"
    echo "  请编辑 ${HERMES_ENV} 填写:"
    echo "    LARK_APP_ID=cli_xxxxx"
    echo "    LARK_APP_SECRET=xxxxx"
    echo ""
    echo "  然后绑定 lark-cli:"
    echo "    sudo -u ${DEPLOY_USER} ${HERMES_VENV}/bin/lark-cli auth login"
    echo ""
    echo "  完成后运行: sudo systemctl start hermes-gateway"
    echo ""
    echo "  (脚本继续注册 systemd 服务...)"
fi

# ── 注册 systemd 服务 ──
echo ">>> [5/6] 注册 hermes-gateway systemd 服务"

# 确定 hermes 可执行路径
if [ -x "${HERMES_VENV}/bin/hermes" ]; then
    HERMES_EXEC="${HERMES_VENV}/bin/hermes"
elif command -v hermes &>/dev/null; then
    HERMES_EXEC="$(which hermes)"
else
    echo "ERROR: hermes 可执行文件未找到"
    exit 1
fi

cat > /etc/systemd/system/hermes-gateway.service << EOF
[Unit]
Description=Hermes Gateway — 飞书消息网关
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
WorkingDirectory=${HERMES_HOME}
Environment="HOME=${DEPLOY_HOME}"
Environment="HERMES_HOME=${HERMES_HOME}"
ExecStart=${HERMES_EXEC} gateway run --replace
Restart=always
RestartSec=10
StandardOutput=append:${HERMES_LOG_DIR}/gateway.log
StandardError=append:${HERMES_LOG_DIR}/gateway.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable hermes-gateway.service

echo "✓ hermes-gateway.service 已注册"

# ── 启动服务 (仅在凭据已配置时) ──
echo ">>> [6/6] 启动验证"

if [ -n "${LARK_APP_ID:-}" ] && [ -n "${LARK_APP_SECRET:-}" ]; then
    systemctl start hermes-gateway.service
    sleep 3
    if systemctl is-active --quiet hermes-gateway.service; then
        echo "✓ hermes-gateway 已启动并运行"
    else
        echo "⚠ hermes-gateway 启动失败, 检查日志:"
        echo "  journalctl -u hermes-gateway -n 20"
        echo "  tail -20 ${HERMES_LOG_DIR}/gateway.log"
    fi
else
    echo "⚠ 凭据未配置, 跳过自动启动"
    echo "  配置后手动启动: sudo systemctl start hermes-gateway"
fi

echo ""
echo "============================================"
echo "  飞书网关 (Hermes) 部署完成"
echo "============================================"
echo "  配置目录:  ${HERMES_HOME}/"
echo "  配置文件:  ${HERMES_CONFIG}"
echo "  环境变量:  ${HERMES_ENV}"
echo "  日志目录:  ${HERMES_LOG_DIR}/"
echo ""
echo "  管理命令:"
echo "    systemctl status hermes-gateway"
echo "    systemctl restart hermes-gateway"
echo "    journalctl -u hermes-gateway -f"
echo "    tail -f ${HERMES_LOG_DIR}/gateway.log"
echo ""
echo "  下一步: bash healthcheck.sh"
echo "============================================"
