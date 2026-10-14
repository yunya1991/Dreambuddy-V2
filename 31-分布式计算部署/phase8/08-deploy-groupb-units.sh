#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 8: 组 B 补云端单元 (signal-scanner / memory-cleanup)
# 用法: sudo bash 08-deploy-groupb-units.sh
# 前置: 仓库已 git pull 到最新（含 scanner.py 去硬编码 / run_memory_cleanup.sh 可移植改造）
# 说明:
#   1) signal-scanner.service  simple, 12-三屏信号池扫描（每 300s），写 signal_pool/pool.json
#   2) memory-cleanup.service  oneshot, 每日 02:05 清理 experiments/ab-trading 记忆文件
#   3) memory-cleanup.timer    定时触发
# 注: etl-worker 本轮暂缓（云端暂无 events/ 数据源且缺 psycopg2）
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
DEPLOY_HOME="/home/${DEPLOY_USER}"
REPO_DIR="${DEPLOY_HOME}/dreambuddy"
PY="${DEPLOY_HOME}/venv-trading/bin/python"
TREND_DIR="${REPO_DIR}/12-三屏趋势系统"
CLASSIC_DIR="${REPO_DIR}/10-经典指标系统"
AB_DIR="${REPO_DIR}/experiments/ab-trading"
LOG_DIR="${DEPLOY_HOME}/logs/groupb"

echo "============================================"
echo "  Phase 8 — 组 B 补云端 (signal-scanner / memory-cleanup)"
echo "============================================"

# 0. 校验
for p in "${TREND_DIR}/signal_pool/scanner.py" \
         "${CLASSIC_DIR}/ml_trade_service.py" \
         "${AB_DIR}/scripts/run_memory_cleanup.sh" \
         "${AB_DIR}/core/memory/memory_manager.py" \
         "${PY}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done

# 依赖预检（signal-scanner 依赖 pandas）
if ! "${PY}" -c "import pandas" >/dev/null 2>&1; then
    echo "[WARN] ${PY} 未安装 pandas — signal-scanner 将无法运行"
    echo "       修复: ${DEPLOY_HOME}/venv-trading/bin/pip install pandas"
fi
if ! "${PY}" -c "import requests" >/dev/null 2>&1; then
    echo "[WARN] ${PY} 未安装 requests — signal-scanner 可能无法运行"
fi

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. signal-scanner
echo ">>> [1/3] 写入 signal-scanner.service"
cat > /etc/systemd/system/signal-scanner.service <<EOF
[Unit]
Description=Dreambuddy 12-trend signal pool scanner (every 300s)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${TREND_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHONPATH=${CLASSIC_DIR}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=${PY} signal_pool/scanner.py --daemon --interval 300
Restart=always
RestartSec=30
StandardOutput=append:${LOG_DIR}/signal-scanner.log
StandardError=append:${LOG_DIR}/signal-scanner.err.log

[Install]
WantedBy=multi-user.target
EOF

# 3. memory-cleanup
echo ">>> [2/3] 写入 memory-cleanup.service + timer"
cat > /etc/systemd/system/memory-cleanup.service <<EOF
[Unit]
Description=Dreambuddy ab-trading memory cleanup (daily 02:05)

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${AB_DIR}
Environment="HOME=${DEPLOY_HOME}"
Environment="PYTHON_BIN=${PY}"
ExecStart=/bin/bash ${AB_DIR}/scripts/run_memory_cleanup.sh
TimeoutStartSec=600
StandardOutput=append:${LOG_DIR}/memory-cleanup.log
StandardError=append:${LOG_DIR}/memory-cleanup.err.log
EOF

cat > /etc/systemd/system/memory-cleanup.timer <<EOF
[Unit]
Description=Memory cleanup daily 02:05

[Timer]
OnCalendar=*-*-* 02:05:00
Persistent=true
Unit=memory-cleanup.service

[Install]
WantedBy=timers.target
EOF

# 4. 启用
echo ">>> [3/3] daemon-reload + enable --now"
systemctl daemon-reload
systemctl enable --now signal-scanner.service memory-cleanup.timer

echo ""
echo "=== 状态 ==="
echo -n "signal-scanner.service: "; systemctl is-active signal-scanner.service || true
echo -n "memory-cleanup.timer:   "; systemctl is-active memory-cleanup.timer || true
systemctl list-timers --all | grep -E "memory-cleanup" || true
echo ""
echo "============================================"
echo "  ✓ Phase 8 部署完成"
echo "  日志: ${LOG_DIR}/"
echo "  手动触发: sudo systemctl start memory-cleanup.service"
echo "  验证: systemctl status signal-scanner"
echo "        tail -n 30 ${LOG_DIR}/signal-scanner.log"
echo "        cat ${TREND_DIR}/signal_pool/pool.json | head -c 200"
echo "============================================"
