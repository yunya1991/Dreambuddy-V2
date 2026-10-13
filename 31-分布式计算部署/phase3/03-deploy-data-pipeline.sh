#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 3: 数据管道服务 (18 采集 / 19 backfill + DAL 维护) 部署
# 用法: sudo bash 03-deploy-data-pipeline.sh
# 说明: 远端统一 systemd 托管（不再使用 launchd/pm2）
#   1) datacenter-scheduler.service  常驻，18-数据获取中心 持续采集（内含每 10min 18→19 回填）
#   2) datacenter-backfill.timer     每小时 oneshot，补 18→19 mm_metrics（含 chart 展平）
#   3) dal-backup / dal-integrity / dal-rotate  oneshot + timer，SQLite 备份/校验/轮转
# ============================================================
set -e

DEPLOY_USER="${DEPLOY_USER:-luke}"
REPO_DIR="/home/${DEPLOY_USER}/dreambuddy"
PY="/home/${DEPLOY_USER}/venv-trading/bin/python"
DC_DIR="${REPO_DIR}/18-数据获取中心"
DAL_DIR="${REPO_DIR}/19-数据访问层"
CLN_DIR="${REPO_DIR}/20-数据清洗中心"
LOG_DIR="/home/${DEPLOY_USER}/logs/datacenter"

echo "============================================"
echo "  Phase 3 — 数据管道 (18/19) 部署 (systemd)"
echo "============================================"
echo "DEPLOY_USER=${DEPLOY_USER}"
echo "REPO_DIR=${REPO_DIR}"
echo "PY=${PY}"

# 0. 校验关键路径
for p in "${DC_DIR}/data_center_scheduler.py" "${DAL_DIR}/scripts/backfill_18_records.py" "${DAL_DIR}/dreambuddy_dal/cron_runner.py" "${PY}"; do
    if [ ! -e "$p" ]; then
        echo "[ERROR] 缺少关键文件: $p"
        exit 1
    fi
done

# 1. 日志目录
mkdir -p "${LOG_DIR}"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "${LOG_DIR}"

# 2. systemd unit 写入
echo ">>> [1/4] 写入 18 采集调度 unit"
cat > /etc/systemd/system/datacenter-scheduler.service <<EOF
[Unit]
Description=Dreambuddy Data Center Scheduler (18 collection pipeline)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${DC_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${DC_DIR}:${CLN_DIR}:${DAL_DIR}/scripts"
ExecStart=${PY} data_center_scheduler.py
Restart=always
RestartSec=10
StandardOutput=append:${LOG_DIR}/scheduler.out.log
StandardError=append:${LOG_DIR}/scheduler.err.log

[Install]
WantedBy=multi-user.target
EOF

echo ">>> [2/4] 写入 18→19 回填 oneshot + timer"
cat > /etc/systemd/system/datacenter-backfill.service <<EOF
[Unit]
Description=Dreambuddy 18->19 backfill (mm_metrics)

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${DAL_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${DAL_DIR}"
ExecStart=/bin/bash -c '${PY} ${DAL_DIR}/scripts/backfill_18_records.py && ${PY} ${DAL_DIR}/scripts/backfill_chart_to_mm_metrics.py'
StandardOutput=append:${LOG_DIR}/backfill.out.log
StandardError=append:${LOG_DIR}/backfill.err.log
EOF

cat > /etc/systemd/system/datacenter-backfill.timer <<EOF
[Unit]
Description=Hourly 18->19 mm_metrics backfill

[Timer]
OnCalendar=*:15
Persistent=true
Unit=datacenter-backfill.service

[Install]
WantedBy=timers.target
EOF

echo ">>> [3/4] 写入 DAL 备份/校验/轮转 oneshot + timer"
DAL_DATA_DIR="${DAL_DIR}/data"

cat > /etc/systemd/system/dal-backup.service <<EOF
[Unit]
Description=Dreambuddy DAL SQLite backup

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${DAL_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${DAL_DIR}"
Environment="DATA_DIR=${DAL_DATA_DIR}"
Environment="DAL_DB_PATH=${DAL_DATA_DIR}/dreambuddy_core.db"
Environment="BACKUP_DIR=${DAL_DATA_DIR}/backups"
Environment="BACKUP_KEEP=7"
ExecStart=${PY} -m dreambuddy_dal.cron_runner backup --no-encrypt
StandardOutput=append:${LOG_DIR}/dal-backup.log
StandardError=append:${LOG_DIR}/dal-backup.err.log
EOF

cat > /etc/systemd/system/dal-backup.timer <<EOF
[Unit]
Description=Daily DAL SQLite backup (04:00)

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true
Unit=dal-backup.service

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/dal-integrity.service <<EOF
[Unit]
Description=Dreambuddy DAL SQLite integrity check

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${DAL_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${DAL_DIR}"
Environment="DATA_DIR=${DAL_DATA_DIR}"
Environment="DAL_DB_PATH=${DAL_DATA_DIR}/dreambuddy_core.db"
ExecStart=${PY} -m dreambuddy_dal.cron_runner integrity
StandardOutput=append:${LOG_DIR}/dal-integrity.log
StandardError=append:${LOG_DIR}/dal-integrity.err.log
EOF

cat > /etc/systemd/system/dal-integrity.timer <<EOF
[Unit]
Description=DAL SQLite integrity check (every 6h)

[Timer]
OnCalendar=*-*-* 00,06,12,18:30:00
Persistent=true
Unit=dal-integrity.service

[Install]
WantedBy=timers.target
EOF

cat > /etc/systemd/system/dal-rotate.service <<EOF
[Unit]
Description=Dreambuddy DAL backup rotation

[Service]
Type=oneshot
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
WorkingDirectory=${DAL_DIR}
Environment="HOME=/home/${DEPLOY_USER}"
Environment="PYTHONPATH=${DAL_DIR}"
Environment="DATA_DIR=${DAL_DATA_DIR}"
Environment="BACKUP_DIR=${DAL_DATA_DIR}/backups"
Environment="BACKUP_KEEP=7"
ExecStart=${PY} -m dreambuddy_dal.cron_runner rotate
StandardOutput=append:${LOG_DIR}/dal-rotate.log
StandardError=append:${LOG_DIR}/dal-rotate.err.log
EOF

cat > /etc/systemd/system/dal-rotate.timer <<EOF
[Unit]
Description=Daily DAL backup rotation (05:00)

[Timer]
OnCalendar=*-*-* 05:00:00
Persistent=true
Unit=dal-rotate.service

[Install]
WantedBy=timers.target
EOF

# 3. 启用
echo ">>> [4/4] daemon-reload + enable + restart"
systemctl daemon-reload
systemctl enable --now datacenter-scheduler.service
systemctl enable --now datacenter-backfill.timer
systemctl enable --now dal-backup.timer dal-integrity.timer dal-rotate.timer

sleep 6

# 4. 验证
echo ""
echo "=== 服务状态 ==="
systemctl is-active datacenter-scheduler || true
echo "=== Timer 状态 ==="
systemctl list-timers --all | grep -E "datacenter-backfill|dal-backup|dal-integrity|dal-rotate" || true
echo "=== 18 采集日志尾部 ==="
tail -n 5 "${LOG_DIR}/scheduler.out.log" 2>/dev/null || echo "(日志尚未产生)"
echo ""

echo "============================================"
echo "  ✓ 数据管道部署完成 (systemd)"
echo "  日志: ${LOG_DIR}/"
echo "  命令: systemctl status datacenter-scheduler"
echo "============================================"
