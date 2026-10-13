#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 6: 冗余/补充单元 (systemd oneshot + timer)
# 用法: sudo bash 06-deploy-redundant-units.sh
# 说明:
#   1) yijing-monitor.service   oneshot，每 4h 易经推理健康巡检 + 自进化
#      （yijing_monitor 对缺失 GH_TOKEN / 飞书凭据有保护，缺则跳过对应步骤）
#   2) ranking-trigger.service  oneshot，每 4h POST 产物中台触发榜单重算
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
PY="/home/${DEPLOY_USER}/venv-trading/bin/python"
YJ_DIR="${REPO_DIR}/11-易经推理系统"
LOG_DIR="/home/${DEPLOY_USER}/logs/redundant"

echo "============================================"
echo "  Phase 6 — 冗余单元 (yijing-monitor / ranking-trigger)"
echo "============================================"

# 0. 校验
for p in "${YJ_DIR}/scripts/memory_l4/yijing_monitor.py" "${PY}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. yijing-monitor
echo ">>> [1/2] 写入 yijing-monitor oneshot + timer"
cat > /etc/systemd/system/yijing-monitor.service <<EOF
[Unit]
Description=Dreambuddy Yijing monitor (health check + self-evolution)

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${YJ_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${YJ_DIR}"
ExecStart=${PY} -m scripts.memory_l4.yijing_monitor
TimeoutStartSec=1800
StandardOutput=append:${LOG_DIR}/yijing-monitor.log
StandardError=append:${LOG_DIR}/yijing-monitor.err.log
EOF

cat > /etc/systemd/system/yijing-monitor.timer <<EOF
[Unit]
Description=Yijing monitor every 4h

[Timer]
OnCalendar=*-*-* 00,04,08,12,16,20:05:00
Persistent=true
Unit=yijing-monitor.service

[Install]
WantedBy=timers.target
EOF

# 3. ranking-trigger
echo ">>> [2/2] 写入 ranking-trigger oneshot + timer"
cat > /etc/systemd/system/ranking-trigger.service <<EOF
[Unit]
Description=Dreambuddy trading-ranking trigger (product hub 3456)

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
Environment="HOME=/home/${DEPLOY_USER}"
ExecStart=/bin/bash -c 'curl -s -X POST http://127.0.0.1:3456/api/trading-ranking/trigger -H "Content-Type: application/json" -d "{}"'
TimeoutStartSec=1800
StandardOutput=append:${LOG_DIR}/ranking-trigger.log
StandardError=append:${LOG_DIR}/ranking-trigger.err.log
EOF

cat > /etc/systemd/system/ranking-trigger.timer <<EOF
[Unit]
Description=Trading-ranking trigger every 4h

[Timer]
OnCalendar=*-*-* 01,05,09,13,17,21:05:00
Persistent=true
Unit=ranking-trigger.service

[Install]
WantedBy=timers.target
EOF

# 4. 启用
echo ">>> daemon-reload + enable --now"
systemctl daemon-reload
systemctl enable --now yijing-monitor.timer ranking-trigger.timer

echo ""
echo "=== Timer 状态 ==="
systemctl list-timers --all | grep -E "yijing-monitor|ranking-trigger" || true
echo ""
echo "============================================"
echo "  ✓ Phase 6 部署完成"
echo "  日志: ${LOG_DIR}/"
echo "  手动触发: sudo systemctl start yijing-monitor.service"
echo "============================================"
