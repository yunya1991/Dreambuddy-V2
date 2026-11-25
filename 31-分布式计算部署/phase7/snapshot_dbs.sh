#!/bin/bash
# ============================================================
# Dreambuddy V2 — DB 快照脚本（供 dreambuddy-snapshot.service 调用）
# 用 sqlite3 .backup 生成一致性快照，避免 WAL 半写；并做 integrity_check。
# 环境变量: REPO_DIR(默认 /home/luke/dreambuddy) / OUT_DIR(默认 /home/luke/sync-snapshots)
# ============================================================
set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
OUT_DIR="${OUT_DIR:-/home/luke/sync-snapshots}"
mkdir -p "${OUT_DIR}"

# name:src 列表
SRCS=(
    "cognitive_memory.db:${REPO_DIR}/4-MEMORY/data/cognitive_memory.db"
    "dreambuddy_core.db:${REPO_DIR}/19-数据访问层/data/dreambuddy_core.db"
)

rc=0
for item in "${SRCS[@]}"; do
    name="${item%%:*}"
    src="${item#*:}"
    if [ ! -f "${src}" ]; then
        echo "[WARN] 源文件缺失, 跳过: ${src}"
        continue
    fi
    dst="${OUT_DIR}/${name}"
    tmp="${dst}.tmp"
    # 空间预检：全量副本需与源文件等量空间（×1.3 含余量），不足则跳过本轮
    free_kb="$(df -Pk "${OUT_DIR}" | awk 'NR==2 {print $4}')"
    src_kb="$(du -k "${src}" | awk '{print $1}')"
    need_kb=$((src_kb * 13 / 10))
    if [ "${free_kb}" -lt "${need_kb}" ]; then
        echo "[SKIP] 空间不足: 需 ${need_kb}K, 可用 ${free_kb}K: ${src}"
        rc=1
        continue
    fi
    rm -f "${tmp}"
    backup_ok=0
    for attempt in 1 2 3; do
        if sqlite3 "${src}" ".timeout 10000" ".backup '${tmp}'"; then
            backup_ok=1
            break
        fi
        echo "[WARN] .backup 第 ${attempt} 次失败(锁冲突), 5s 后重试: ${src}"
        rm -f "${tmp}"
        sleep 5
    done
    if [ "${backup_ok}" != "1" ]; then
        echo "[ERROR] .backup 失败(已重试 3 次): ${src}"
        rm -f "${tmp}"
        rc=1
        continue
    fi
    if [ ! -s "${tmp}" ]; then
        echo "[ERROR] .backup 产物为空: ${tmp}"
        rm -f "${tmp}"
        rc=1
        continue
    fi
    chk="$(sqlite3 "${tmp}" 'PRAGMA integrity_check;' | head -1)"
    if [ "${chk}" != "ok" ]; then
        echo "[ERROR] integrity_check=${chk}: ${tmp}"
        rm -f "${tmp}"
        rc=1
        continue
    fi
    mv -f "${tmp}" "${dst}"
    echo "[OK] ${name} -> ${dst} (integrity=ok, $(stat -c%s "${dst}") bytes)"
done

exit ${rc}
