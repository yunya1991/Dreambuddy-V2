#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 9: G0-1a 云端 trailing-stop-runner 等价物
# 用法: sudo bash 09-deploy-trailing-stop-runner.sh
# 前置: 仓库已 git pull 到最新（含 16-调控系统/scripts/run_trailing_stop_runner.sh）
# 说明:
#   补齐红线 G0-1a —— 本地 com.dreambuddy.trailing-stop-runner (--real 实盘移动止损)
#   在云端的等价 systemd 单元。与本地共用同一可移植入口脚本，保证行为一致。
#   1) 冒烟：--once --dry-run（不下单），失败则拒绝 enable
#   2) trailing-stop-runner.service simple 常驻 --real (300s)，Restart=always
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
PY="${DEPLOY_HOME}/venv-trading/bin/python"
CTRL_DIR="${REPO_DIR}/16-调控系统"
ENTRY="${CTRL_DIR}/scripts/run_trailing_stop_runner.sh"
RUNNER="${CTRL_DIR}/scripts/trailing_stop_runner.py"
ENV_FILE="${REPO_DIR}/14-V15经典马丁策略/config/.env.local"
OKX_CLIENT="${REPO_DIR}/14-V15经典马丁策略/lib/okx_client.py"
LOG_DIR="${DEPLOY_HOME}/logs/trailing"

echo "============================================"
echo "  Phase 9 — 云端 trailing-stop-runner 等价物 (G0-1a)"
echo "============================================"

# 0. 校验关键文件
for p in "${ENTRY}" "${RUNNER}" \
         "${CTRL_DIR}/core/trailing_stop/component.py" \
         "${CTRL_DIR}/core/exit_executor.py" \
         "${CTRL_DIR}/config/trailing_stop.json" \
         "${OKX_CLIENT}" \
         "${PY}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done
if [ ! -f "${ENV_FILE}" ]; then
    echo "[WARN] 缺少 OKX 凭据文件: ${ENV_FILE} — real 模式将无法真实下单"
fi

# 依赖预检
for mod in requests pandas ccxt; do
    if ! "${PY}" -c "import ${mod}" >/dev/null 2>&1; then
        echo "[WARN] ${PY} 未安装 ${mod} — trailing-stop-runner 可能无法运行"
    fi
done

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. 冒烟（--once --dry-run，拒绝带风险上线）
echo ">>> [1/3] 冒烟测试: --once --dry-run（不下单）"
if ! sudo -u "${DEPLOY_USER}" -H bash -lc \
        "PYTHON_BIN='${PY}' TRAILING_INTERVAL=300 timeout 300 bash '${ENTRY}' --once --dry-run"; then
    echo ""
    echo "[ERROR] 冒烟未通过 —— 拒绝 enable trailing-stop-runner.service"
    exit 1
fi
echo ">>> 冒烟通过 ✓"

# 3. 写入 systemd 单元
echo ">>> [2/3] 写入 trailing-stop-runner.service"
cat > /etc/systemd/system/trailing-stop-runner.service <<EOF
[Unit]
Description=Dreambuddy 16-control trailing stop runner (OKX real, every 300s)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${CTRL_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHON_BIN=${PY}"
Environment="TRAILING_INTERVAL=300"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/bin/bash ${ENTRY}
Restart=always
RestartSec=30
StandardOutput=append:${LOG_DIR}/trailing-stop-runner.log
StandardError=append:${LOG_DIR}/trailing-stop-runner.err.log

[Install]
WantedBy=multi-user.target
EOF

# 4. 启用
echo ">>> [3/3] daemon-reload + enable --now"
systemctl daemon-reload
systemctl enable --now trailing-stop-runner.service

echo ""
echo "=== 状态 ==="
echo -n "trailing-stop-runner.service: "; systemctl is-active trailing-stop-runner.service || true
systemctl status trailing-stop-runner.service --no-pager | head -n 12 || true
echo ""
echo "============================================"
echo "  ✓ Phase 9 部署完成（红线 G0-1a 闭环）"
echo "  云端日志: ${LOG_DIR}/trailing-stop-runner.log"
echo "            ${CTRL_DIR}/logs/trailing_runner_YYYYMMDD.log"
echo "  验证: systemctl status trailing-stop-runner"
echo "        tail -n 30 ${LOG_DIR}/trailing-stop-runner.log"
echo "  注: 云端 agent_a/b/c 与三屏 127.0.0.1:8092 无数据源 →"
echo "      每轮会有相应缺失日志（与本地同构，不影响 V15/易经 仓位评估）"
echo "============================================"
