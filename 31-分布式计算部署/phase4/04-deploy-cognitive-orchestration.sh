#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 4a/4b: 认知守护 + DreamOS 编排 部署
# 用法: sudo bash 04-deploy-cognitive-orchestration.sh
# 说明: 远端统一 systemd 托管
#   1) cognitive-daemon.service            常驻，监听仓库文件变更 → 认知闭环
#   2) dreamos-scheduler.service           常驻，DreamOS 每小时全币种调度
#   3) dreamos-dynamic-evaluator.service   常驻，动态评估(6h)
# 注意: start_scheduler.py 的 logging.FileHandler(dreamos/logs/scheduler.log)
#       要求 logs 目录已存在，否则模块导入即崩；本脚本先补齐该目录。
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
PY="/home/${DEPLOY_USER}/venv-trading/bin/python"
COG_DIR="${REPO_DIR}/4-MEMORY/9-工具与接口"
ARCH_DIR="${REPO_DIR}/1-ARCHITECTURE"
DREAMOS_DIR="${ARCH_DIR}/dreamos"
LOG_DIR="/home/${DEPLOY_USER}/logs/cognitive"

echo "============================================"
echo "  Phase 4a/4b — 认知守护 + DreamOS 编排 (systemd)"
echo "============================================"

# 0. 校验关键文件
for p in "${COG_DIR}/cognitive_daemon.py" "${DREAMOS_DIR}/cli/start_scheduler.py" \
         "${DREAMOS_DIR}/cli/run_dynamic_evaluator.py" "${PY}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done

# 1. 目录准备（dreamos/logs 缺失会导致调度器崩溃）
mkdir -p "${LOG_DIR}" "${DREAMOS_DIR}/logs"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}" "${DREAMOS_DIR}/logs"

# 2. unit 写入
echo ">>> [1/3] 写入 cognitive-daemon.service"
cat > /etc/systemd/system/cognitive-daemon.service <<EOF
[Unit]
Description=Dreambuddy Cognitive Daemon (file-change watcher -> cognitive loop)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${REPO_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${COG_DIR}"
ExecStart=${PY} -u ${COG_DIR}/cognitive_daemon.py --watch . --interval 5 --debounce 8 --verbose
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/daemon.out.log
StandardError=append:${LOG_DIR}/daemon.err.log

[Install]
WantedBy=multi-user.target
EOF

echo ">>> [2/3] 写入 dreamos-scheduler.service"
cat > /etc/systemd/system/dreamos-scheduler.service <<EOF
[Unit]
Description=Dream OS Scheduler (hourly multi-coin scan)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${ARCH_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${ARCH_DIR}"
ExecStart=${PY} ${DREAMOS_DIR}/cli/start_scheduler.py
Restart=always
RestartSec=15
StandardOutput=append:${LOG_DIR}/dreamos-scheduler.out.log
StandardError=append:${LOG_DIR}/dreamos-scheduler.err.log

[Install]
WantedBy=multi-user.target
EOF

echo ">>> [3/3] 写入 dreamos-dynamic-evaluator.service"
cat > /etc/systemd/system/dreamos-dynamic-evaluator.service <<EOF
[Unit]
Description=Dream OS Dynamic Evaluator (6h interval)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${ARCH_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${ARCH_DIR}"
ExecStart=${PY} -m dreamos.cli.run_dynamic_evaluator --interval 21600 --log-level INFO
Restart=always
RestartSec=15
StandardOutput=append:${LOG_DIR}/dynamic-evaluator.out.log
StandardError=append:${LOG_DIR}/dynamic-evaluator.err.log

[Install]
WantedBy=multi-user.target
EOF

# 3. 启用
echo ">>> daemon-reload + enable --now"
systemctl daemon-reload
systemctl enable --now cognitive-daemon.service
systemctl enable --now dreamos-scheduler.service
systemctl enable --now dreamos-dynamic-evaluator.service

sleep 8

# 4. 验证
echo ""
echo "=== 服务状态 ==="
for s in cognitive-daemon dreamos-scheduler dreamos-dynamic-evaluator; do
    printf "%-28s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo ""
echo "=== cognitive-daemon 日志尾部 ==="
tail -n 8 "${LOG_DIR}/daemon.err.log" 2>/dev/null || echo "(日志尚未产生)"
echo ""
echo "=== dreamos-scheduler 日志尾部 ==="
tail -n 8 "${LOG_DIR}/dreamos-scheduler.err.log" 2>/dev/null || echo "(日志尚未产生)"
echo ""
echo "============================================"
echo "  ✓ Phase 4a/4b 部署完成 (systemd)"
echo "  日志: ${LOG_DIR}/"
echo "  命令: systemctl status cognitive-daemon dreamos-scheduler"
echo "============================================"
