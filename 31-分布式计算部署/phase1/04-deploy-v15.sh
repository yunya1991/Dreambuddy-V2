#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 1 V15 马丁策略部署
# 用法: bash 04-deploy-v15.sh
# 前置: 02-deploy-data.sh 已完成, V15 config/.env.local 已配置
# 产出: systemd timer (orchestrator 15min) + cron (poll_light 5min)
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
V15_DIR="${REPO_DIR}/14-V15经典马丁策略"
V15_ENV_LOCAL="${V15_DIR}/config/.env.local"
ENV_FILE="${DEPLOY_HOME}/.config/dreambuddy/.env.cloud"
LOG_DIR="${DEPLOY_HOME}/logs/v15"

echo "============================================"
echo "  Phase 1 — V15 马丁策略部署"
echo "============================================"

# ── 检查 ──
if [ ! -d "${V15_DIR}" ]; then
    echo "ERROR: ${V15_DIR} 不存在"
    exit 1
fi
echo "✓ V15 目录存在"

# ── 检查 .env.local (OKX 凭据) ──
if [ ! -f "${V15_ENV_LOCAL}" ]; then
    echo "⚠ config/.env.local 不存在, 创建模板..."
    mkdir -p "${V15_DIR}/config"
    cat > "${V15_ENV_LOCAL}" << 'EOF'
# === V15 云端配置 (腾讯云) ===
# 数据源: Hyperliquid (paper 模式) 或 OKX (实盘)
V15_DATA_SOURCE=hyperliquid
V15_EXECUTION=paper

# OKX 凭据 (实盘时填写)
OKX_API_KEY=
OKX_SECRET_KEY=
OKX_PASSPHRASE=

# Hyperliquid (paper 模式时填写)
HL_API_WALLET=
EOF
    chown "${DEPLOY_USER}:${DEPLOY_USER}" "${V15_ENV_LOCAL}"
    echo "  已生成模板, 请填写凭据: vim ${V15_ENV_LOCAL}"
    echo "  填写后重新运行本脚本"
    exit 0
fi
echo "✓ config/.env.local 存在"

# ── 创建日志/数据目录 ──
mkdir -p "${LOG_DIR}" "${V15_DIR}/logs" "${V15_DIR}/data"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${V15_DIR}/logs" "${V15_DIR}/data" "${LOG_DIR}"

# ── Python 依赖确认 ──
echo ">>> [1/3] 检查 Python 依赖"
PYTHON_BIN="python3"
if ! ${PYTHON_BIN} -c "import requests, pandas, numpy, ccxt, dotenv" 2>/dev/null; then
    echo "  安装缺失依赖..."
    pip3 install --break-system-packages requests pandas numpy ccxt python-dotenv
fi
echo "✓ Python 依赖就绪"

# ── 测试 V15 可执行性 ──
echo ">>> [2/3] 测试 V15 信号模块"
cd "${V15_DIR}"
if sudo -u "${DEPLOY_USER}" ${PYTHON_BIN} run.py signal BTC 2>&1 | head -20; then
    echo "✓ V15 信号模块可执行"
else
    echo "⚠ V15 信号测试失败, 检查配置和依赖"
    echo "  手动测试: cd ${V15_DIR} && python3 run.py signal BTC"
    exit 1
fi

# ── 注册 systemd timer ──
echo ">>> [3/3] 注册 systemd timer (orchestrator + poll_light)"

# Orchestrator Service
cat > /etc/systemd/system/v15-orchestrator.service << EOF
[Unit]
Description=V15 Orchestrator — 马丁策略自主调度 (15min)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User=${DEPLOY_USER}
WorkingDirectory=${V15_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHONPATH=${V15_DIR}/lib:${V15_DIR}/core"
ExecStart=${PYTHON_BIN} ${V15_DIR}/run.py orchestrator
StandardOutput=append:${LOG_DIR}/orchestrator.log
StandardError=append:${LOG_DIR}/orchestrator.log
TimeoutStartSec=600
EOF

# Orchestrator Timer (每 15 分钟)
cat > /etc/systemd/system/v15-orchestrator.timer << EOF
[Unit]
Description=V15 Orchestrator Timer (15min)

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

# Poll Light Service
cat > /etc/systemd/system/v15-poll-light.service << EOF
[Unit]
Description=V15 Poll Light — 持仓状态同步 (5min)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User=${DEPLOY_USER}
WorkingDirectory=${V15_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHONPATH=${V15_DIR}/lib:${V15_DIR}/core"
ExecStart=${PYTHON_BIN} ${V15_DIR}/run.py poll_light
StandardOutput=append:${LOG_DIR}/poll_light.log
StandardError=append:${LOG_DIR}/poll_light.log
TimeoutStartSec=300
EOF

# Poll Light Timer (每 5 分钟)
cat > /etc/systemd/system/v15-poll-light.timer << EOF
[Unit]
Description=V15 Poll Light Timer (5min)

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF

# 注册 + 启动
systemctl daemon-reload
systemctl enable --now v15-orchestrator.timer
systemctl enable --now v15-poll-light.timer

echo "✓ systemd timers 已注册并启动"

# ── V15 API 长驻服务 (决策 API 8771 + 资金管理 API 8770) ──
echo ">>> [额外] 注册 V15 API 长驻服务"

# V15 决策 API Service (端口 8771)
cat > /etc/systemd/system/v15-api.service << EOF
[Unit]
Description=V15 Strategy HTTP API — 决策信号服务 (端口 8771)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
WorkingDirectory=${V15_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHONPATH=${V15_DIR}/lib:${V15_DIR}/core"
ExecStart=${PYTHON_BIN} ${V15_DIR}/run.py api --port 8771
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/api.log
StandardError=append:${LOG_DIR}/api.log

[Install]
WantedBy=multi-user.target
EOF

# V15 资金管理 API Service (端口 8770)
cat > /etc/systemd/system/v15-capital-api.service << EOF
[Unit]
Description=V15 Capital Management API — 资金管理服务 (端口 8770)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
WorkingDirectory=${V15_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHONPATH=${V15_DIR}/lib:${V15_DIR}/core"
ExecStart=${PYTHON_BIN} ${V15_DIR}/run.py capital_engine api --port 8770
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/capital-api.log
StandardError=append:${LOG_DIR}/capital-api.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now v15-api.service
systemctl enable --now v15-capital-api.service

echo "✓ V15 API 服务已注册并启动"
echo "  v15-api.service         → http://127.0.0.1:8771 (决策信号)"
echo "  v15-capital-api.service → http://127.0.0.1:8770 (资金管理)"

# ── 验证 ──
echo ""
echo ">>> Timer 状态:"
systemctl list-timers v15-* --no-pager

echo ""
echo ">>> 手动触发一次 orchestrator 验证..."
systemctl start v15-orchestrator.service
sleep 5
if systemctl is-active --quiet v15-orchestrator.service; then
    echo "  orchestrator 正在运行 (正常, oneshot 完成后变 inactive)"
else
    echo "  orchestrator 执行完成, 检查日志: tail -20 ${LOG_DIR}/orchestrator.log"
fi

echo ""
echo "============================================"
echo "  V15 马丁策略部署完成"
echo "============================================"
echo "  Orchestrator:  每 15min 自动运行"
echo "  Poll Light:    每 5min 同步持仓状态"
echo "  决策 API:      http://127.0.0.1:8771 (v15-api.service)"
echo "  资金管理 API:  http://127.0.0.1:8770 (v15-capital-api.service)"
echo "  日志目录:      ${LOG_DIR}/"
echo ""
echo "  管理命令:"
echo "    systemctl list-timers v15-*"
echo "    systemctl status v15-api v15-capital-api"
echo "    systemctl start v15-orchestrator.service   # 手动触发"
echo "    tail -f ${LOG_DIR}/orchestrator.log"
echo "    tail -f ${LOG_DIR}/poll_light.log"
echo "    tail -f ${LOG_DIR}/api.log"
echo ""
echo "  下一步: bash 05-nginx-ssl.sh"
echo "============================================"
