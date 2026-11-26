#!/bin/bash
# 备份/完整性检查结束后回收 WAL，防止长读事务把 -wal 撑大（2026-11-25 曾累积到 12G）。
# 幂等；失败不阻塞主任务（调用方用 `-` 前缀）。
set -u

REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
DB="${DAL_DB_PATH:-${REPO_DIR}/19-数据访问层/data/dreambuddy_core.db}"
COG_DB="${COG_DB_PATH:-${REPO_DIR}/4-MEMORY/data/cognitive_memory.db}"
PY="${PYTHON_BIN:-/home/luke/venv-trading/bin/python}"

checkpoint_one() {
    local db="$1"
    if [ ! -f "$db" ]; then
        echo "[SKIP] 库不存在: $db"
        return 0
    fi
    "$PY" - "$db" <<'PYCODE'
import sqlite3
import sys

db = sys.argv[1]
conn = sqlite3.connect(db, timeout=60)
try:
    busy, log_pages, ckpt_pages = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    print(f"[WAL] {db}: busy={busy} log={log_pages} ckpt={ckpt_pages}")
finally:
    conn.close()
PYCODE
}

# 主库（DAL）与认知库都回收：认知库有常驻进程长连接，WAL 曾单日涨到 1.37G
checkpoint_one "$DB"
checkpoint_one "$COG_DB"
