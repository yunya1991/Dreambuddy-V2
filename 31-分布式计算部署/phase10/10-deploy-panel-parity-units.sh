#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 10: 云端监控面板对齐（ab-trading 生产者上云）
# 用法: sudo bash 10-deploy-panel-parity-units.sh
# 前置: 仓库已 git pull 到最新（含本次去硬编码改造）
#   - 11-易经推理系统/data_server_fixed.py   （15 处 macOS 硬编码 → _REPO_ROOT 推导）
#   - 11-易经推理系统/scripts/memory_l4/polling_trader.py（agi_snapshot 写盘去硬编码）
#   - experiments/ab-trading/scripts/run_agent_a.sh（仓库根自推导 + PYTHON_BIN）
# 说明:
#   面板 /api/state 的 logs_a/logs_b 读 experiments/ab-trading/logs/agent_a|agent_b 的 *.json，
#   生产者（本地 launchd com.dreambuddy.ab_monitor / ab_orchestrator，4h 周期）此前未上云
#   → 云端该两区块为空。本脚本按 phase8 范式补等价 systemd 单元：
#     1) ab-monitor.service      auto_monitor.py（检查 Agent A/B 日志新鲜度并按需触发）
#     2) ab-orchestrator.service orchestrator.py（4H 决策调度）
#     3) 两者均配 .timer（OnBootSec=5min + OnUnitActiveSec=4h，等价 launchd StartInterval=14400）
#   安全: 云端显式 AUTO_EXECUTE=false —— 禁止云端实盘下单，云端仅产出面板所需日志
#         （本地凭据 config/.env 被 .gitignore 忽略，云端本就不存在，此处再显式钉死）
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
PY="${DEPLOY_HOME}/venv-trading/bin/python"
AB_DIR="${REPO_DIR}/experiments/ab-trading"
YIJING_DIR="${REPO_DIR}/11-易经推理系统"
LOG_DIR="${DEPLOY_HOME}/logs/abtrading"

echo "============================================"
echo "  Phase 10 — 云端面板对齐 (ab-monitor / ab-orchestrator)"
echo "============================================"

# 0. 校验关键文件
for p in "${AB_DIR}/auto_monitor.py" \
         "${AB_DIR}/orchestrator.py" \
         "${AB_DIR}/agents/agent_a_runner.py" \
         "${AB_DIR}/agents/agent_b_runner.py" \
         "${YIJING_DIR}/data_server_fixed.py" \
         "${PY}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done
if [ ! -f "${AB_DIR}/config/.env" ]; then
    echo "[WARN] 缺少 ${AB_DIR}/config/.env（被 .gitignore 忽略，云端正常现象）"
    echo "       影响: Agent 走默认参数，AUTO_EXECUTE 保持 false（不实盘）"
fi

# 依赖预检
for mod in requests dotenv; do
    if ! "${PY}" -c "import ${mod}" >/dev/null 2>&1; then
        echo "[WARN] ${PY} 未安装 ${mod} — ab 生产者可能无法运行"
    fi
done

# 1. 目录
mkdir -p "${LOG_DIR}" "${AB_DIR}/logs/agent_a" "${AB_DIR}/logs/agent_b"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}" "${AB_DIR}/logs"

# 2. ab-monitor
echo ">>> [1/4] 写入 ab-monitor.service + timer"
cat > /etc/systemd/system/ab-monitor.service <<EOF
[Unit]
Description=Dreambuddy ab-trading auto monitor (Agent A/B freshness, every 4h)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${AB_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="AUTO_EXECUTE=false"
Environment="PYTHONUNBUFFERED=1"
ExecStart=${PY} auto_monitor.py
TimeoutStartSec=1800
StandardOutput=append:${LOG_DIR}/ab-monitor.log
StandardError=append:${LOG_DIR}/ab-monitor.err.log
EOF

cat > /etc/systemd/system/ab-monitor.timer <<EOF
[Unit]
Description=ab-trading auto monitor every 4h

[Timer]
OnBootSec=5min
OnUnitActiveSec=4h
Persistent=true
Unit=ab-monitor.service

[Install]
WantedBy=timers.target
EOF

# 3. ab-orchestrator
echo ">>> [2/4] 写入 ab-orchestrator.service + timer"
cat > /etc/systemd/system/ab-orchestrator.service <<EOF
[Unit]
Description=Dreambuddy ab-trading orchestrator (4H decision scheduling)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${AB_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="AUTO_EXECUTE=false"
Environment="PYTHONUNBUFFERED=1"
ExecStart=${PY} orchestrator.py
TimeoutStartSec=1800
StandardOutput=append:${LOG_DIR}/ab-orchestrator.log
StandardError=append:${LOG_DIR}/ab-orchestrator.err.log
EOF

cat > /etc/systemd/system/ab-orchestrator.timer <<EOF
[Unit]
Description=ab-trading orchestrator every 4h

[Timer]
OnBootSec=8min
OnUnitActiveSec=4h
Persistent=true
Unit=ab-orchestrator.service

[Install]
WantedBy=timers.target
EOF

# 4. 启用 + 重启面板
echo ">>> [3/4] daemon-reload + enable --now"
systemctl daemon-reload
systemctl enable --now ab-monitor.timer ab-orchestrator.timer

echo ">>> [4/4] 重启面板服务（加载去硬编码代码）"
systemctl restart yijing-data-server.service
sleep 3

echo ""
echo "=== 状态 ==="
echo -n "ab-monitor.timer:      "; systemctl is-active ab-monitor.timer || true
echo -n "ab-orchestrator.timer: "; systemctl is-active ab-orchestrator.timer || true
echo -n "yijing-data-server:    "; systemctl is-active yijing-data-server.service || true
systemctl list-timers --all | grep -E "ab-monitor|ab-orchestrator" || true
echo ""
echo "=== 首轮手动触发（立即产出面板日志，不等 4h） ==="
systemctl start ab-monitor.service || true
echo "  已触发 ab-monitor.service（Type=oneshot，日志见 ${LOG_DIR}/ab-monitor.log）"
echo ""
echo "============================================"
echo "  ✓ Phase 10 部署完成"
echo "  验证: ls ${AB_DIR}/logs/agent_a ${AB_DIR}/logs/agent_b"
echo "        curl -s http://127.0.0.1:8765/api/state | head -c 300"
echo "        journalctl -u ab-monitor -n 30 --no-pager"
echo "============================================"
