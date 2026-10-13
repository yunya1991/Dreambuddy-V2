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
    rm -f "${tmp}"
    if ! sqlite3 "${src}" ".backup '${tmp}'"; then
        echo "[ERROR] .backup 失败: ${src}"
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
