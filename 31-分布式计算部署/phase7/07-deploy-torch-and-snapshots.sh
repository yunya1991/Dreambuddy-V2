#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 7: 补齐 CPU torch + torchsde + mcp，并部署 DB 快照 timer
# 关联: SPEC/PLAN-本地远端双写分叉治理与torch可用性（阶段3）
# 用法: sudo bash 07-deploy-torch-and-snapshots.sh
# 说明:
#   1) 在 /home/luke/venv-trading 幂等安装 CPU 版 torch + torchsde（消除 NF-AGI-03 静默降级）
#   2) 补装 mcp 包（供认知库 SSH stdio 托管：cognitive_mcp_server）
#   3) 部署 dreambuddy-snapshot.service/.timer：定时对 cognitive_memory.db /
#      dreambuddy_core.db 执行 sqlite3 .backup → /home/luke/sync-snapshots/（避免 WAL 半写）
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
PY="/home/${DEPLOY_USER}/venv-trading/bin/python"
LOG_DIR="/home/${DEPLOY_USER}/logs/redundant"
SNAP_DIR="/home/${DEPLOY_USER}/sync-snapshots"
EVO_DIR="${REPO_DIR}/23-四层闭环自进化交易架构"
MCP_DIR="${REPO_DIR}/4-MEMORY/9-工具与接口"

echo "============================================"
echo "  Phase 7 — CPU torch/torchsde/mcp + DB 快照 timer"
echo "============================================"

# 0. 校验
if [ ! -x "${PY}" ]; then
    echo "[ERROR] 缺少 venv python: ${PY}"
    exit 1
fi

mkdir -p "${LOG_DIR}" "${SNAP_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}" "${SNAP_DIR}"

# 1. CPU torch（幂等：已存在则跳过）
echo ">>> [1/4] 安装 CPU 版 torch"
if "${PY}" -c "import torch" 2>/dev/null; then
    echo "    torch 已安装: $("${PY}" -c 'import torch;print(torch.__version__)')，跳过"
else
    "${PY}" -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
fi

# 2. torchsde
echo ">>> [2/4] 安装 torchsde"
if "${PY}" -c "import torchsde" 2>/dev/null; then
    echo "    torchsde 已安装: $("${PY}" -c 'import torchsde;print(torchsde.__version__)')，跳过"
else
    "${PY}" -m pip install --no-cache-dir torchsde
fi

# 3. mcp 包（认知 MCP server 依赖）
echo ">>> [3/5] 安装 mcp"
if "${PY}" -c "import mcp" 2>/dev/null; then
    echo "    mcp 已安装，跳过"
else
    "${PY}" -m pip install --no-cache-dir mcp
fi

# 3b. sqlite-vec（向量检索加速，recall SLA ≤200ms 的关键依赖）
echo ">>> [3b/5] 安装 sqlite-vec"
if "${PY}" -c "import sqlite_vec" 2>/dev/null; then
    echo "    sqlite-vec 已安装，跳过"
else
    "${PY}" -m pip install --no-cache-dir sqlite-vec
fi

# 4. 校验 SDE 后端 + mcp server 冒烟
echo ">>> [4/4] 校验可观测性"
PYTHONPATH="${EVO_DIR}" "${PY}" -c "
from dreambuddy_evolution.engines.sde_solver import SDESolver, log_runtime_backends
st = SDESolver().status()
print('    status:', st)
assert st['neural_sde'], 'torch 不可用'
assert st['torchsde'], 'torchsde 不可用'
log_runtime_backends()
print('    ✓ torch/torchsde 校验通过')
"
PYTHONPATH="${MCP_DIR}" "${PY}" -c "import cognitive_mcp_server" \
    && echo "    ✓ cognitive_mcp_server 导入成功"

# 5. 快照 service/timer
echo ">>> 写入 dreambuddy-snapshot.service/.timer"
SNAP_SCRIPT="${REPO_DIR}/31-分布式计算部署/phase7/snapshot_dbs.sh"
if [ ! -f "${SNAP_SCRIPT}" ]; then
    echo "[ERROR] 缺少快照脚本: ${SNAP_SCRIPT}"
    exit 1
fi
chmod +x "${SNAP_SCRIPT}" || true

cat > /etc/systemd/system/dreambuddy-snapshot.service <<EOF
[Unit]
Description=Dreambuddy DB snapshot (sqlite3 .backup for cognitive/core)

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="REPO_DIR=${REPO_DIR}"
Environment="OUT_DIR=${SNAP_DIR}"
ExecStart=/bin/bash ${SNAP_SCRIPT}
TimeoutStartSec=600
StandardOutput=append:${LOG_DIR}/snapshot.log
StandardError=append:${LOG_DIR}/snapshot.err.log
EOF

cat > /etc/systemd/system/dreambuddy-snapshot.timer <<EOF
[Unit]
Description=Dreambuddy DB snapshot every 10min

[Timer]
OnCalendar=*-*-* *:0/10:00
Persistent=true
Unit=dreambuddy-snapshot.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now dreambuddy-snapshot.timer
echo ">>> 立即触发一次快照"
systemctl start dreambuddy-snapshot.service || true

echo ""
echo "=== Timer 状态 ==="
systemctl list-timers --all | grep -E "dreambuddy-snapshot" || true
echo "=== 快照文件 ==="
ls -la "${SNAP_DIR}/" || true
echo "=== 服务状态 ==="
systemctl is-active dreambuddy-snapshot.timer
systemctl show dreambuddy-snapshot.service -p NRestarts --value
echo ""
echo "============================================"
echo "  ✓ Phase 7 部署完成"
echo "  回滚: systemctl disable --now dreambuddy-snapshot.timer"
echo "============================================"
