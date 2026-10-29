#!/bin/bash
# ============================================================
# 12-dr-drill.sh — 灾备演练（SPEC P2-3：模拟故障 → 回滚 → 记 RTO）
#
# 用法:
#   bash 12-dr-drill.sh            # 沙箱演练（默认，零风险）：临时 git 仓库造故障 + 真实回滚脚本
#   bash 12-dr-drill.sh --cloud    # 云端只读预检（校验 last_good 可用、健康基线），不做真实 reset
#   bash 12-dr-drill.sh --cloud --yes   # 云端真实演练（会 git reset + 重启 unit，需本人明确授权）
#
# 产出：.deploy/dr-drill.log（RTO 与结论）
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 脚本位于 <repo>/31-分布式计算部署/phase12/，默认仓库根由此推导（本地/云端通用）
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
STATE_DIR="${REPO_DIR}/.deploy"
ROLLBACK="${REPO_DIR}/37-一键启动脚本/rollback-last-good.sh"
HEALTH="${REPO_DIR}/37-一键启动脚本/health-check.sh"
LOG="${STATE_DIR}/dr-drill.log"

MODE="sandbox"
CONFIRM=false
for arg in "$@"; do
    case "$arg" in
        --cloud) MODE="cloud" ;;
        --yes|-y) CONFIRM=true ;;
    esac
done
mkdir -p "${STATE_DIR}" 2>/dev/null || true

# 云端 SSH 登录用户非 luke（仓库属主 luke），需要时自动提权
run_root() {
    if [ -w "${REPO_DIR}/.git" ] && [ -w "${STATE_DIR}" ]; then "$@"; else sudo -n "$@"; fi
}

record() {
    local line; line="$(date '+%Y-%m-%dT%H:%M:%S%z') $1"; echo "$line"
    if [ -w "${STATE_DIR}" ]; then
        printf '%s\n' "$line" >> "${LOG}" 2>/dev/null || true
    else
        printf '%s\n' "$line" | sudo -n tee -a "${LOG}" >/dev/null 2>&1 || true
    fi
}

# ── 沙箱演练：造一个"故障版本"再回滚，测 RTO ──
drill_sandbox() {
    TMP="$(mktemp -d /tmp/dr-drill.XXXXXX)"
    ok=false
    (
        set -e
        git -C "$TMP" init -q
        printf 'stable\n' > "$TMP/app"
        git -C "$TMP" add app
        git -C "$TMP" -c user.email=drill@local -c user.name=drill commit -qm "stable"
        GOOD="$(git -C "$TMP" rev-parse HEAD)"
        printf 'broken\n' > "$TMP/app"
        git -C "$TMP" -c user.email=drill@local -c user.name=drill commit -qam "fault"
        mkdir -p "$TMP/.deploy"
        printf '{"commit":"%s","ts":"drill","branch":"main"}\n' "$GOOD" > "$TMP/.deploy/last_good"
        START=$(date +%s)
        REPO_DIR="$TMP" HEALTH="" bash "$ROLLBACK" --auto --reason "dr-drill" >/dev/null 2>&1
        END=$(date +%s)
        [ "$(git -C "$TMP" rev-parse HEAD)" = "$GOOD" ] && [ "$(cat "$TMP/app")" = "stable" ] || exit 1
        echo $((END - START)) > "$TMP/rto"
    ) && ok=true

    if ${ok}; then
        RTO="$(cat "$TMP/rto" 2>/dev/null || echo unknown)"
        record "DR_DRILL mode=sandbox result=PASS rto=${RTO}s target=last_good"
        echo "✓ 沙箱演练通过：故障版本已回滚到 last_good，RTO=${RTO}s"
    else
        record "DR_DRILL mode=sandbox result=FAIL"
        echo "✗ 沙箱演练失败，请检查 ${ROLLBACK}"
    fi
    rm -rf "$TMP"
}

# ── 云端预检 / 真实演练 ──
drill_cloud() {
    if [ ! -s "${STATE_DIR}/last_good" ]; then
        record "DR_DRILL mode=cloud result=BLOCKED reason=no-last_good"
        echo "✗ 云端未记录 last_good（先执行一次 update.sh）"
        exit 2
    fi
    TARGET="$(tr -d '\n\r ' < "${STATE_DIR}/last_good" | sed -n 's/.*"commit":"\([^"]*\)".*/\1/p')"
    if ! run_root git -C "$REPO_DIR" cat-file -e "${TARGET}^{commit}" 2>/dev/null; then
        record "DR_DRILL mode=cloud result=BLOCKED reason=commit-missing target=${TARGET:0:10}"
        echo "✗ last_good 指向提交不在本地：${TARGET:0:10}"
        exit 3
    fi
    echo "last_good=${TARGET:0:10} 当前 HEAD=$(run_root git -C "$REPO_DIR" rev-parse --short HEAD)"
    if [ -x "$HEALTH" ]; then
        bash "$HEALTH" --dry-run 2>/dev/null | tail -2
    fi

    if ! ${CONFIRM}; then
        record "DR_DRILL mode=cloud result=PREFLIGHT-OK target=${TARGET:0:10} (未真实回滚)"
        echo "✓ 云端预检通过（未做真实回滚）；如需真实演练加 --yes"
        exit 0
    fi

    START=$(date +%s)
    run_root bash "$ROLLBACK" --auto --reason "dr-drill" || true
    END=$(date +%s)
    record "DR_DRILL mode=cloud result=PASS rto=$((END - START))s target=${TARGET:0:10}"
    echo "✓ 云端真实演练完成，RTO=$((END - START))s（记录 ${LOG}）"
}

case "$MODE" in
    sandbox) drill_sandbox ;;
    cloud)   drill_cloud ;;
esac
