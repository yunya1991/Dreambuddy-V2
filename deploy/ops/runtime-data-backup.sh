#!/bin/bash
# ============================================================
# Dreambuddy 关键运行时数据每日备份（git clean -fdx 删除风险的兜底）
# 由 runtime-data-backup.timer 每日 03:30 触发
#
# 2026-11-26 调整：不再复制 19-数据访问层/data/dreambuddy_core.db
#   - 原因：`cp -a` 对运行中的库是撕裂副本（不一致，无恢复价值），且每日
#     额外写 18.8G，是 04:00 备份窗口磁盘尖峰与 HostDiskWillFillIn24h 误报的主因。
#   - 替代：核心库由 dal-backup（VACUUM INTO + sha256）负责，仓库外已有
#     sync-snapshots/dreambuddy_core.db 硬链接指向同一 inode，git clean 删不到。
# ============================================================
set -uo pipefail
REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/luke/runtime-data-backup/daily}"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${BACKUP_ROOT}/${TS}"

CRITICAL_PATHS=(
    "11-易经推理系统/.workbuddy/memory_l4/stats"
    "39-金融语义蒸馏系统/trade_cases.jsonl"
    "39-金融语义蒸馏系统/case_statistics.json"
    "39-金融语义蒸馏系统/causal_candidates.json"
    "4-MEMORY/data/cognitive_memory.db"
)

mkdir -p "${BACKUP_DIR}"
count=0
for p in "${CRITICAL_PATHS[@]}"; do
    if [ -e "${REPO_DIR}/${p}" ]; then
        mkdir -p "${BACKUP_DIR}/$(dirname "${p}")"
        cp -a "${REPO_DIR}/${p}" "${BACKUP_DIR}/${p}"
        count=$((count+1))
    fi
done
echo "[OK] $(date '+%F %T') 备份 ${count} 项关键数据 -> ${BACKUP_DIR}"

# 保留最近 14 天备份（实际按 cleanup-cloud-backups.sh 的 KEEP_DAILY 收敛到 1 份）
find "${BACKUP_ROOT}" -maxdepth 1 -mindepth 1 -type d -mtime +14 -exec rm -rf {} + 2>/dev/null || true
exit 0
