#!/bin/bash
# ============================================================
# rollback-last-good.sh — G5 自动/手动回滚到上一稳定提交（SPEC P1-1）
#
# 用法:
#   rollback-last-good.sh --auto --reason "health-check x3 fail"   # watchdog 调用，无需确认
#   rollback-last-good.sh --yes --reason "手动回滚"                 # 人工回滚
#
# 行为:
#   1. 读 .deploy/last_good（update.sh 部署成功后写的稳定提交）
#   2. git reset --hard <commit>（只回代码，不动 untracked 运行态数据）
#   3. 重启关键 unit，复检健康
#   4. 写 .deploy/rollback-log.jsonl 留痕
# 禁止: 不清理 untracked、不删数据库、不 force push
# ============================================================
set -uo pipefail

REPO_DIR="${REPO_DIR:-/home/luke/dreambuddy}"
STATE_DIR="${REPO_DIR}/.deploy"
LAST_GOOD="${STATE_DIR}/last_good"
ROLLBACK_LOG="${STATE_DIR}/rollback-log.jsonl"
HEALTH="${REPO_DIR}/37-一键启动脚本/health-check.sh"
UNITS=(dreambuddy-frontend yijing-data-server v15-api v15-capital-api)

AUTO=false; CONFIRM=false; REASON="unspecified"
while [ $# -gt 0 ]; do
    case "$1" in
        --auto) AUTO=true; CONFIRM=true ;;
        --yes|-y) CONFIRM=true ;;
        --reason) REASON="${2:-unspecified}"; shift ;;
    esac
    shift
done

cd "${REPO_DIR}" || { echo "[rollback] 仓库不存在: ${REPO_DIR}"; exit 1; }

if [ ! -s "${LAST_GOOD}" ]; then
    echo "[rollback] 无 ${LAST_GOOD}（从未成功部署过），放弃自动回滚，转人工"
    exit 2
fi
TARGET="$(tr -d '\n\r ' < "${LAST_GOOD}" | sed -n 's/.*"commit":"\([^"]*\)".*/\1/p')"
if [ -z "${TARGET}" ]; then
    echo "[rollback] last_good 解析失败: $(cat "${LAST_GOOD}")"
    exit 3
fi
git fetch --all --quiet 2>/dev/null || true
if ! git cat-file -e "${TARGET}^{commit}" 2>/dev/null; then
    echo "[rollback] 目标提交不存在于本地: ${TARGET}（fetch 后仍缺失）"
    exit 4
fi

CURRENT="$(git rev-parse --short HEAD)"
echo "[rollback] 当前 HEAD=${CURRENT} → 目标 ${TARGET:0:10}  原因: ${REASON}"
if ! ${CONFIRM}; then
    printf '[rollback] 确认回滚到 %s ? [y/N] ' "${TARGET:0:10}"
    read -r ans
    case "${ans}" in y|Y|yes) ;; *) echo "[rollback] 已取消"; exit 0 ;; esac
fi

git reset --hard "${TARGET}" || { echo "[rollback] reset 失败"; exit 5; }
echo "[rollback] ✓ 代码已回滚到 $(git rev-parse --short HEAD)"

for unit in "${UNITS[@]}"; do
    if systemctl is-enabled --quiet "${unit}.service" 2>/dev/null; then
        systemctl restart "${unit}.service" 2>/dev/null && echo "  ✓ ${unit} 已重启" || echo "  ⚠ ${unit} 重启失败"
    fi
done
sleep 15

HEALTH_RESULT="unknown"
if [ -x "${HEALTH}" ]; then
    HEALTH_RESULT="$(bash "${HEALTH}" 2>&1 | grep -o 'status=[A-Z]*' | head -1)"
fi

NOW="$(date '+%Y-%m-%dT%H:%M:%S%z')"
printf '{"ts":"%s","from":"%s","to":"%s","reason":"%s","auto":%s,"health":"%s"}\n' \
    "${NOW}" "${CURRENT}" "${TARGET:0:10}" "${REASON}" "${AUTO}" "${HEALTH_RESULT}" >> "${ROLLBACK_LOG}"
echo "[rollback] 已记录 ${ROLLBACK_LOG}（health=${HEALTH_RESULT}）"
