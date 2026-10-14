#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 7/5: 本地↔远端 DB 同步（认知库按 id 双边聚合 v2）
# 关联: SPEC/PLAN-本地远端双写分叉治理与torch可用性（阶段5）· 认知库多节点聚合 v2
# 用法: bash 08-local-mirror.sh   （由 LaunchAgent com.dreambuddy.dbsync 定时调用）
#
# 认知库 cognitive_memory.db —— 多节点聚合（不再整文件替换，保住本地 inode 与本地写入）:
#   1) 下行取数 : 远端一致性快照 → 本地常驻副本（rsync 增量，仅传差异块）
#   2) 上行汇总 : 本地独有行(id 不在快照) → 远端权威 live（INSERT OR IGNORE by id）
#   3) 下行合并 : 快照 → 本地（INSERT OR REPLACE by id，云端权威版本覆盖同名行；本地独有行保留）
# 核心库 dreambuddy_core.db —— 远端快照 → 本地只读镜像（整文件 rsync，本地不写）
# gene_data —— 过渡期双向 merge（先上行 → 再下行，均不使用 --delete）
# 均以 luke 身份经 sudo -n 执行远端 rsync / sqlite（repo 属主 luke）。
# ============================================================
set -uo pipefail

ROOT="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
LOG="${ROOT}/31-分布式计算部署/phase7/mirror.log"

# 经 Phase4 建立的免密 SSH 别名（ubuntu 用户 + 专用 key），避免密码认证偶发失败。
SSH_ALIAS="dreambuddy-remote"
RSH="ssh -o BatchMode=yes"
# 远端 rsync 以 luke 身份运行（读/写 repo 与快照目录）
RPATH="--rsync-path=sudo -n -u luke -H rsync"

SNAP_REMOTE="/home/luke/sync-snapshots"
REMOTE_LIVE_COG="/home/luke/dreambuddy/4-MEMORY/data/cognitive_memory.db"
LOCAL_MEM="${ROOT}/4-MEMORY/data"
LOCAL_DAL="${ROOT}/19-数据访问层/data"
LOCAL_COG="${LOCAL_MEM}/cognitive_memory.db"
SNAP_LOCAL="${LOCAL_MEM}/.sync-snapshot/cognitive_memory.db"

GENE_LOCAL="${ROOT}/23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data"
GENE_REMOTE="/home/luke/dreambuddy/23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data"

# memories 表列（两侧 schema 一致）
COLS="id,content,vector,quality_level,confidence,tags,memory_type,source,created_at,updated_at,verify_count,level,known_gaps,observations"
# memories 表 DDL（用于生成上行临时库）
COG_DDL="CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT NOT NULL, vector BLOB, quality_level TEXT DEFAULT 'C', confidence REAL DEFAULT 0.0, tags TEXT DEFAULT '[]', memory_type TEXT DEFAULT 'experience', source TEXT DEFAULT '', created_at TEXT DEFAULT '', updated_at TEXT DEFAULT '', verify_count INTEGER DEFAULT 0, level TEXT DEFAULT 'observation', known_gaps TEXT DEFAULT '[]', observations TEXT DEFAULT '[]')"

ts() { date '+%F %T'; }
mkdir -p "${LOCAL_MEM}/.sync-snapshot"
TMP="$(mktemp -d)"; trap 'rm -rf "${TMP}"' EXIT

echo "[$(ts)] === local-mirror start ===" >> "${LOG}"
FAILED=0

# ── 1) 下行取数：远端快照 → 本地常驻副本（增量 rsync）──
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${SSH_ALIAS}:${SNAP_REMOTE}/cognitive_memory.db" "${SNAP_LOCAL}" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] cognitive snapshot pull rc=${RC}" >> "${LOG}"

if [ "${RC}" -eq 0 ]; then
    # ── 2) 上行汇总：本地独有行 → 临时小库 → 远端权威 live ──
    UP_N="$(sqlite3 "${TMP}/cog_up.db" \
        "${COG_DDL}; \
         ATTACH 'file:${LOCAL_COG}?mode=ro' AS l; \
         ATTACH '${SNAP_LOCAL}' AS s; \
         INSERT OR IGNORE INTO main.memories (${COLS}) \
           SELECT ${COLS} FROM l.memories AS lm WHERE lm.id NOT IN (SELECT id FROM s.memories); \
         SELECT count(*) FROM main.memories;" 2>>"${LOG}")"
    RC2=$?
    if [ "${RC2}" -eq 0 ] && [ "${UP_N:-0}" -gt 0 ]; then
        rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
            "${TMP}/cog_up.db" "${SSH_ALIAS}:${SNAP_REMOTE}/_local_cog_up.db" >> "${LOG}" 2>&1
        RC3=$?
        if [ "${RC3}" -eq 0 ]; then
            ssh -o BatchMode=yes "${SSH_ALIAS}" bash -s >> "${LOG}" 2>&1 <<REMOTE
set -e
sudo -n -u luke sqlite3 "${REMOTE_LIVE_COG}" "ATTACH '${SNAP_REMOTE}/_local_cog_up.db' AS l; INSERT OR IGNORE INTO main.memories (${COLS}) SELECT ${COLS} FROM l.memories; DETACH l;"
sudo -n -u luke rm -f "${SNAP_REMOTE}/_local_cog_up.db"
REMOTE
            RC4=$?; [ "${RC4}" -ne 0 ] && FAILED=1
            echo "[$(ts)] cognitive up-merge rows=${UP_N} rc=${RC4}" >> "${LOG}"
        else
            FAILED=1
            echo "[$(ts)] cognitive up-merge upload rc=${RC3}" >> "${LOG}"
        fi
    else
        echo "[$(ts)] cognitive up-merge rows=0 (no local-only) rc=${RC2}" >> "${LOG}"
    fi

    # ── 3) 下行合并：快照 → 本地（REPLACE by id，本地独有行不受影响）──
    sqlite3 "${LOCAL_COG}" \
        "PRAGMA busy_timeout=20000; \
         ATTACH '${SNAP_LOCAL}' AS s; \
         INSERT OR REPLACE INTO main.memories (${COLS}) \
           SELECT ${COLS} FROM s.memories AS sm \
           WHERE sm.id NOT IN (SELECT id FROM main.memories) \
              OR sm.updated_at > (SELECT m.updated_at FROM main.memories AS m WHERE m.id = sm.id); \
         DETACH s;" >/dev/null 2>>"${LOG}"
    RC5=$?; [ "${RC5}" -ne 0 ] && FAILED=1
    echo "[$(ts)] cognitive down-merge rc=${RC5}" >> "${LOG}"
else
    echo "[$(ts)] skip cognitive merge (snapshot pull failed)" >> "${LOG}"
fi

# ── 4) 核心库：远端快照 → 本地只读镜像 ──
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${SSH_ALIAS}:${SNAP_REMOTE}/dreambuddy_core.db" \
    "${LOCAL_DAL}/dreambuddy_core.db" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] dreambuddy_core.db mirror rc=${RC}" >> "${LOG}"

# ── 5) gene_data 双向 merge（不含 --delete）──
#   5a. 上行：本地新增 → 远端
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${GENE_LOCAL}/" "${SSH_ALIAS}:${GENE_REMOTE}/" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] gene_data up-merge rc=${RC}" >> "${LOG}"
#   5b. 下行：远端 → 本地
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${SSH_ALIAS}:${GENE_REMOTE}/" "${GENE_LOCAL}/" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] gene_data down-merge rc=${RC}" >> "${LOG}"

echo "[$(ts)] === local-mirror done FAILED=${FAILED} ===" >> "${LOG}"
exit "${FAILED}"
