#!/bin/bash
# ============================================================
# Dreambuddy V2 — Phase 7/5: 本地只读镜像 + gene_data 过渡期双向 merge
# 关联: SPEC/PLAN-本地远端双写分叉治理与torch可用性（阶段5）
# 用法: bash 08-local-mirror.sh   （由 LaunchAgent com.dreambuddy.dbsync 定时调用）
# 说明:
#   1) 认知库/核心库：远端快照（/home/luke/sync-snapshots）→ 本地对应路径（只读镜像）
#   2) gene_data：过渡期双向 merge（先上行本地新增 → 远端，再下行远端 → 本地），
#      两边均不使用 --delete，保证过渡期不丢数据
#   均以 luke 身份经 sudo -n 执行远端 rsync（repo 属主 luke）。
# ============================================================
set -uo pipefail

ROOT="/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2"
LOG="${ROOT}/31-分布式计算部署/phase7/mirror.log"

# 经 Phase4 建立的免密 SSH 别名（ubuntu 用户 + 专用 key），避免密码认证偶发失败。
REMOTE="dreambuddy-remote"
RSH="ssh -o BatchMode=yes"
# 远端 rsync 以 luke 身份运行（读/写 repo 与快照目录）
RPATH="--rsync-path=sudo -n -u luke -H rsync"

SNAP_REMOTE="/home/luke/sync-snapshots"
LOCAL_MEM="${ROOT}/4-MEMORY/data"
LOCAL_DAL="${ROOT}/19-数据访问层/data"

GENE_LOCAL="${ROOT}/23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data"
GENE_REMOTE="/home/luke/dreambuddy/23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data"

ts() { date '+%F %T'; }
echo "[$(ts)] === local-mirror start ===" >> "${LOG}"

FAILED=0
# 1) 认知库：远端快照 → 本地只读镜像
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${REMOTE}:${SNAP_REMOTE}/cognitive_memory.db" \
    "${LOCAL_MEM}/cognitive_memory.db" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] cognitive_memory.db mirror rc=${RC}" >> "${LOG}"

# 2) 核心库：远端快照 → 本地只读镜像
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${REMOTE}:${SNAP_REMOTE}/dreambuddy_core.db" \
    "${LOCAL_DAL}/dreambuddy_core.db" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] dreambuddy_core.db mirror rc=${RC}" >> "${LOG}"

# 3) gene_data 双向 merge（不含 --delete）
#   3a. 上行：本地新增 → 远端
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${GENE_LOCAL}/" "${REMOTE}:${GENE_REMOTE}/" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] gene_data up-merge rc=${RC}" >> "${LOG}"
#   3b. 下行：远端 → 本地
rsync -az "${RPATH}" --no-perms --no-owner --no-group -e "${RSH}" \
    "${REMOTE}:${GENE_REMOTE}/" "${GENE_LOCAL}/" >> "${LOG}" 2>&1
RC=$?; [ "${RC}" -ne 0 ] && FAILED=1
echo "[$(ts)] gene_data down-merge rc=${RC}" >> "${LOG}"

echo "[$(ts)] === local-mirror done FAILED=${FAILED} ===" >> "${LOG}"
exit "${FAILED}"
