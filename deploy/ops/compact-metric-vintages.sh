#!/usr/bin/env bash
# mm_metric_vintages 去重收敛 + 空间回收（C 阶段，须在低峰窗口执行，root 运行）
#
# 做什么：在线 .backup 兜底 → 停采集调度器 → 压缩重复观测（--apply --vacuum）
#        → quick_check → 恢复调度器。
# 为什么：压缩重建表需要 DDL 事务，VACUUM 需要独占连接，二者都不能和采集并发。
# 窗口：仅允许 01:30-03:30（避开 04:00 的 dal-backup），--force 可跳过检查。
set -euo pipefail

DB="/home/luke/dreambuddy/19-数据访问层/data/dreambuddy_core.db"
REPO="/home/luke/dreambuddy"
PY="/home/luke/venv-trading/bin/python"
SCRIPT="$REPO/19-数据访问层/scripts/retain_metric_vintages.py"
BACKUP_DIR="$REPO/19-数据访问层/data/backups"
LOG="/home/luke/logs/datacenter/mm-vintage-compact.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

hm=$(date +%H%M)
if [ "$hm" -lt 130 ] || [ "$hm" -gt 330 ]; then
  if [ "${1:-}" != "--force" ]; then
    log "当前 $hm 不在 01:30-03:30 窗口，拒绝执行（--force 可强制）"
    exit 1
  fi
fi

size=$(stat -c %s "$DB")
avail=$(df -B1 --output=avail / | tail -1 | tr -d ' ')
need=$((size * 12 / 10))
if [ "$avail" -lt "$need" ]; then
  log "空间不足：库 ${size}B，需要 ${need}B，可用 ${avail}B"
  exit 1
fi

stamp=$(date +%Y%m%d_%H%M%S)
snapshot="$BACKUP_DIR/dreambuddy_core_preevict_$stamp.db"
log "1/4 在线备份 → $snapshot"
sudo -n -u luke sqlite3 "$DB" ".backup '$snapshot'"
sudo -n -u luke sqlite3 "$snapshot" "PRAGMA quick_check;" | tee -a "$LOG"

was_active=$(systemctl is-active datacenter-scheduler.service || true)
log "2/4 停止采集调度器（原状态: $was_active）"
systemctl stop datacenter-scheduler.service || true

set +e
log "3/4 压缩 + VACUUM"
sudo -n -u luke -H "$PY" "$SCRIPT" --db "$DB" --apply --vacuum 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e

if [ "$was_active" = "active" ]; then
  log "4/4 恢复采集调度器"
  systemctl start datacenter-scheduler.service
  sleep 5
  log "调度器状态: $(systemctl is-active datacenter-scheduler.service)"
fi

sudo -n -u luke sqlite3 "$DB" "PRAGMA quick_check;" | tee -a "$LOG"
log "完成 rc=$rc，磁盘: $(df -h / | tail -1)"
exit "$rc"
