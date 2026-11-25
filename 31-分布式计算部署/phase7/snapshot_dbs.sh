#!/bin/bash
# ============================================================
# Dreambuddy V2 — DB 快照脚本（供 dreambuddy-snapshot.service 调用）
# 方案 B：核心库不再对主库做全量 .backup，而是硬链接 dal-backup 产出的静止副本。
#   - 主库 18G+ 时 `sqlite3 .backup` 无法在合理时间内完成，被 timeout 杀掉后会
#     留下与源库等量的 .tmp（2026-11-25 每 10 分钟 18.5G，直接打满根分区）。
#   - dal-backup 的 `VACUUM INTO` 产物本身就是一致性副本，硬链接（同盘）零 IO、
#     零额外空间，且同名前缀文件只在该副本更新时才变化，本地 rsync 增量才有意义。
# 认知库较小（~1.3G），仍用 sqlite3 .backup 生成一致性快照。
# 环境变量: REPO_DIR / OUT_DIR / BACKUP_DIR
# ============================================================
set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
OUT_DIR="${OUT_DIR:-/home/luke/sync-snapshots}"
BACKUP_DIR="${BACKUP_DIR:-${REPO_DIR}/19-数据访问层/data/backups}"

mkdir -p "${OUT_DIR}"

# 任何退出路径（含 systemd 的 SIGTERM）都清掉本轮临时产物，避免残留吃盘
cleanup_tmp() {
    local f
    for f in "${OUT_DIR}"/*.tmp "${OUT_DIR}"/*.tmp-shm "${OUT_DIR}"/*.tmp-wal; do
        [ -e "${f}" ] || continue
        if ! fuser -s "${f}" 2>/dev/null; then
            rm -f -- "${f}"
        fi
    done
}
trap cleanup_tmp EXIT INT TERM

rc=0

# ── 1) 核心库：硬链接最新一份 dal-backup 静止副本 ──────────────
CORE_DST="${OUT_DIR}/dreambuddy_core.db"
latest_backup="$(ls -1t "${BACKUP_DIR}"/dreambuddy_core_*.db 2>/dev/null | head -1)"
if [ -z "${latest_backup}" ]; then
    echo "[SKIP] 无可用 dal-backup 副本: ${BACKUP_DIR}/dreambuddy_core_*.db（保留旧快照）"
    rc=1
elif [ "$(head -c 15 "${latest_backup}")" != "SQLite format 3" ]; then
    echo "[ERROR] 备份副本头非法（可能未写完），跳过: ${latest_backup}"
    rc=1
else
    new_link="${CORE_DST}.new"
    rm -f -- "${new_link}"
    if ln "${latest_backup}" "${new_link}" 2>/dev/null; then
        mv -f -- "${new_link}" "${CORE_DST}"
        echo "[OK] dreambuddy_core.db -> 硬链接 ${latest_backup} ($(stat -c%s "${CORE_DST}") bytes)"
    else
        # 跨文件系统时退化为整文件拷贝（非预期路径，正常同盘不会走到）
        if cp -f -- "${latest_backup}" "${new_link}" && mv -f -- "${new_link}" "${CORE_DST}"; then
            echo "[OK] dreambuddy_core.db -> 拷贝 ${latest_backup} ($(stat -c%s "${CORE_DST}") bytes)"
        else
            rm -f -- "${new_link}"
            echo "[ERROR] 快照落盘失败: ${latest_backup}"
            rc=1
        fi
    fi
fi

# ── 2) 认知库：sqlite3 .backup 一致性快照 ─────────────────────
COG_SRC="${REPO_DIR}/4-MEMORY/data/cognitive_memory.db"
COG_DST="${OUT_DIR}/cognitive_memory.db"
COG_TMP="${COG_DST}.tmp"
if [ ! -f "${COG_SRC}" ]; then
    echo "[WARN] 源文件缺失, 跳过: ${COG_SRC}"
else
    free_kb="$(df -Pk "${OUT_DIR}" | awk 'NR==2 {print $4}')"
    src_kb="$(du -k "${COG_SRC}" | awk '{print $1}')"
    need_kb=$((src_kb * 13 / 10))
    if [ "${free_kb}" -lt "${need_kb}" ]; then
        echo "[SKIP] 空间不足: 需 ${need_kb}K, 可用 ${free_kb}K: ${COG_SRC}"
        rc=1
    else
        rm -f -- "${COG_TMP}"
        backup_ok=0
        for attempt in 1 2 3; do
            if sqlite3 "${COG_SRC}" ".timeout 10000" ".backup '${COG_TMP}'"; then
                backup_ok=1
                break
            fi
            echo "[WARN] .backup 第 ${attempt} 次失败(锁冲突), 5s 后重试: ${COG_SRC}"
            rm -f -- "${COG_TMP}"
            sleep 5
        done
        if [ "${backup_ok}" != "1" ] || [ ! -s "${COG_TMP}" ]; then
            echo "[ERROR] .backup 失败或产物为空: ${COG_SRC}"
            rm -f -- "${COG_TMP}"
            rc=1
        else
            chk="$(sqlite3 "${COG_TMP}" 'PRAGMA quick_check;' | head -1)"
            if [ "${chk}" != "ok" ]; then
                echo "[ERROR] quick_check=${chk}: ${COG_TMP}"
                rm -f -- "${COG_TMP}"
                rc=1
            else
                mv -f -- "${COG_TMP}" "${COG_DST}"
                echo "[OK] cognitive_memory.db -> ${COG_DST} (quick_check=ok, $(stat -c%s "${COG_DST}") bytes)"
            fi
        fi
    fi
fi

exit ${rc}
