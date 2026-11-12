#!/bin/bash
# ============================================================
# rollback_deploy.sh — L2-8B 灰度自动部署一键回滚
#
# SPEC-33-G §2.11.4 L2-8 / §2.11.7 / §5 回滚表：
#   灰度部署（L2-B）→ 回滚 = 切回上一镜像/版本；健康检查失败、冒烟失败、观察期劣化即触发。
#
# 用法:
#   rollback_deploy.sh --env gray [--reason "..."] [--drill] [--yes] [--state-dir DIR]
#
# 状态文件: ${STATE_DIR}/<env>.json
#   {"current":{"version","commit","released_at"},"previous":{...},
#    "restart_cmd":"","health_cmd":""}
#
# --drill : 只校验（状态文件结构完整 / previous 非空 / restart_cmd 与 health_cmd
#           已配置且可解析），写 ${STATE_DIR}/<env>.drill.json；不重启任何服务、不改状态文件。
# 真实回滚: 目录锁（pid + 过期清理，兼容 macOS 无 flock 命令）→ 交换 current/previous
#           并原子写回 → restart_cmd → health_cmd；健康失败 exit 3 并标记 health=fail；
#           成功写 ${STATE_DIR}/<env>.rollback.jsonl 留痕。
#
# 禁止: 不删任何业务数据、不 git push、不改状态目录以外的文件。
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-${SCRIPT_DIR}/../runtime/deploy}"
LOCK_TTL_MIN="${LOCK_TTL_MIN:-60}"

ENV=""
REASON="unspecified"
DRILL=false
CONFIRM=false

usage() {
    cat <<'EOF'
用法: rollback_deploy.sh --env <gray|staging|production> [选项]

选项:
  --env <name>        环境名（gray = 灰度）
  --reason <text>     回滚原因（写入留痕）
  --drill             只校验状态文件与命令配置，写 <env>.drill.json，不重启服务
  --yes               跳过交互确认
  --state-dir <dir>   状态目录（默认 33-REA/runtime/deploy）
  -h, --help          显示帮助
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --env) ENV="${2:-}"; shift ;;
        --reason) REASON="${2:-unspecified}"; shift ;;
        --drill) DRILL=true ;;
        --yes|-y) CONFIRM=true ;;
        --state-dir) STATE_DIR="${2:-}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "[rollback-deploy] 未知参数: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [ -z "${ENV}" ]; then
    echo "[rollback-deploy] 必须指定 --env" >&2
    usage >&2
    exit 2
fi

case " gray staging production " in
    *" ${ENV} "*) ;;
    *)
        echo "[rollback-deploy] 未知环境: ${ENV}（允许: gray staging production）" >&2
        exit 2
        ;;
esac

if ! command -v python3 >/dev/null 2>&1; then
    echo "[rollback-deploy] 需要 python3 解析 JSON 状态文件" >&2
    exit 2
fi

STATE_FILE="${STATE_DIR}/${ENV}.json"
DRILL_FILE="${STATE_DIR}/${ENV}.drill.json"
LOG_FILE="${STATE_DIR}/${ENV}.rollback.jsonl"
LOCK_DIR="${STATE_DIR}/.${ENV}.rollback.lock"
NOW="$(date '+%Y-%m-%dT%H:%M:%S%z')"

# ---------------------------------------------------------------- --drill

run_drill() {
    python3 - "${STATE_FILE}" "${ENV}" "${NOW}" "${DRILL_FILE}" <<'PY'
import json
import os
import shlex
import sys

state_path, env, now, drill_path = sys.argv[1:5]
checks = []


def add(check_id, passed, reason):
    checks.append({"id": check_id, "passed": bool(passed), "reason": reason})


doc = None
error = ""
try:
    with open(state_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
except FileNotFoundError:
    error = "状态文件不存在: %s" % state_path
except (OSError, ValueError) as exc:
    error = "状态文件解析失败: %s" % exc

is_doc = isinstance(doc, dict)
add("state_file", is_doc, "状态文件可解析" if is_doc else (error or "状态文件顶层不是 JSON 对象"))
doc = doc if is_doc else {}

current = doc.get("current") if isinstance(doc.get("current"), dict) else {}
previous = doc.get("previous") if isinstance(doc.get("previous"), dict) else {}

current_ok = bool(str(current.get("version") or "").strip() or str(current.get("commit") or "").strip())
add("current", current_ok, "current 含 version/commit" if current_ok else "current 缺失或为空")
add("previous", bool(previous), "previous 非空" if previous else "previous 为空，无可回滚版本")

restart_cmd = str(doc.get("restart_cmd") or "").strip()
health_cmd = str(doc.get("health_cmd") or "").strip()
add("restart_cmd", bool(restart_cmd), "restart_cmd 已配置" if restart_cmd else "restart_cmd 未配置")
add("health_cmd", bool(health_cmd), "health_cmd 已配置" if health_cmd else "health_cmd 未配置")


def parse_ok(command):
    if not command:
        return False
    try:
        return bool(shlex.split(command))
    except ValueError:
        return False


add("restart_cmd_parse", parse_ok(restart_cmd), "restart_cmd 可解析" if parse_ok(restart_cmd) else "restart_cmd 不可解析或为空")
add("health_cmd_parse", parse_ok(health_cmd), "health_cmd 可解析" if parse_ok(health_cmd) else "health_cmd 不可解析或为空")

overall = "pass" if all(item["passed"] for item in checks) else "fail"
report = {"env": env, "checked_at": now, "overall": overall, "checks": checks}
parent = os.path.dirname(drill_path) or "."
os.makedirs(parent, exist_ok=True)
tmp = drill_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
os.replace(tmp, drill_path)
print("[rollback-deploy] drill overall=%s → %s" % (overall, drill_path))
sys.exit(0 if overall == "pass" else 1)
PY
}

if [ "${DRILL}" = "true" ]; then
    run_drill
    exit $?
fi

# ---------------------------------------------------------------- 前置校验

if [ ! -f "${STATE_FILE}" ]; then
    echo "[rollback-deploy] 状态文件不存在: ${STATE_FILE}" >&2
    exit 2
fi

PREVIOUS_OK="$(python3 - "${STATE_FILE}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        doc = json.load(fh)
except (OSError, ValueError):
    print("0")
    raise SystemExit(0)
previous = doc.get("previous") if isinstance(doc, dict) else None
print("1" if isinstance(previous, dict) and previous else "0")
PY
)"
if [ "${PREVIOUS_OK}" != "1" ]; then
    echo "[rollback-deploy] 无 previous 版本，拒绝回滚（不静默成功）: ${STATE_FILE}" >&2
    exit 2
fi

RESTART_CMD="$(python3 - "${STATE_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    doc = json.load(fh)
print(doc.get("restart_cmd") or "")
PY
)" || { echo "[rollback-deploy] 读取 restart_cmd 失败" >&2; exit 2; }

HEALTH_CMD="$(python3 - "${STATE_FILE}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    doc = json.load(fh)
print(doc.get("health_cmd") or "")
PY
)" || { echo "[rollback-deploy] 读取 health_cmd 失败" >&2; exit 2; }

if [ -z "${RESTART_CMD}" ] || [ -z "${HEALTH_CMD}" ]; then
    echo "[rollback-deploy] restart_cmd / health_cmd 未配置，拒绝回滚: ${STATE_FILE}" >&2
    exit 2
fi

if [ "${CONFIRM}" != "true" ]; then
    if [ ! -t 0 ]; then
        echo "[rollback-deploy] 非交互环境必须显式 --yes，已拒绝执行" >&2
        exit 6
    fi
    printf '[rollback-deploy] 确认回滚 %s ? [y/N] ' "${ENV}"
    read -r answer
    case "${answer}" in
        y|Y|yes) ;;
        *) echo "[rollback-deploy] 已取消"; exit 0 ;;
    esac
fi

# ---------------------------------------------------------------- 目录锁

acquire_lock() {
    mkdir -p "${STATE_DIR}" || return 1
    if mkdir "${LOCK_DIR}" 2>/dev/null; then
        echo "$$" > "${LOCK_DIR}/pid"
        return 0
    fi
    local holder=""
    if [ -f "${LOCK_DIR}/pid" ]; then
        holder="$(cat "${LOCK_DIR}/pid" 2>/dev/null || true)"
    fi
    local stale=0
    if [ -z "${holder}" ] || ! kill -0 "${holder}" 2>/dev/null; then
        stale=1
    elif [ -n "$(find "${LOCK_DIR}" -maxdepth 0 -mmin +"${LOCK_TTL_MIN}" 2>/dev/null)" ]; then
        stale=1
    fi
    if [ "${stale}" -eq 1 ]; then
        echo "[rollback-deploy] 清理过期锁（holder=${holder:-unknown}）" >&2
        rm -rf "${LOCK_DIR}"
        if mkdir "${LOCK_DIR}" 2>/dev/null; then
            echo "$$" > "${LOCK_DIR}/pid"
            return 0
        fi
    fi
    echo "[rollback-deploy] 回滚锁被占用（pid=${holder:-unknown}）: ${LOCK_DIR}" >&2
    return 1
}

if ! acquire_lock; then
    exit 4
fi
trap 'rm -rf "${LOCK_DIR}"' EXIT

# ---------------------------------------------------------------- 交换版本

SWAP_OUT="$(python3 - "${STATE_FILE}" <<'PY'
import json
import os
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    doc = json.load(fh)
if not isinstance(doc, dict):
    print("状态文件顶层不是 JSON 对象", file=sys.stderr)
    raise SystemExit(2)
current = doc.get("current") if isinstance(doc.get("current"), dict) else {}
previous = doc.get("previous") if isinstance(doc.get("previous"), dict) else {}
if not previous:
    print("previous 为空，无可回滚版本", file=sys.stderr)
    raise SystemExit(2)
doc["current"], doc["previous"] = previous, current
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
os.replace(tmp, path)
print(json.dumps(current, ensure_ascii=False, sort_keys=True))
print(json.dumps(previous, ensure_ascii=False, sort_keys=True))
PY
)" || { echo "[rollback-deploy] 交换 current/previous 失败" >&2; exit 2; }

FROM_JSON="$(printf '%s\n' "${SWAP_OUT}" | head -n 1)"
TO_JSON="$(printf '%s\n' "${SWAP_OUT}" | tail -n 1)"
echo "[rollback-deploy] ${ENV}: ${FROM_JSON} → ${TO_JSON}  原因: ${REASON}"

mark_health_fail() {
    python3 - "${STATE_FILE}" "${NOW}" <<'PY'
import json
import os
import sys

path, now = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
except (OSError, ValueError):
    raise SystemExit(0)
if not isinstance(doc, dict):
    raise SystemExit(0)
doc["health"] = "fail"
doc["health_failed_at"] = now
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
os.replace(tmp, path)
PY
}

append_log() {
    python3 - "${LOG_FILE}" "${NOW}" "${ENV}" "${REASON}" "$1" "$2" "${FROM_JSON}" "${TO_JSON}" <<'PY'
import json
import os
import sys

path, now, env, reason, health, ok, src, dst = sys.argv[1:9]
row = {
    "ts": now,
    "env": env,
    "reason": reason,
    "health": health,
    "ok": ok == "true",
    "from": json.loads(src),
    "to": json.loads(dst),
}
parent = os.path.dirname(path) or "."
os.makedirs(parent, exist_ok=True)
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
PY
}

# ---------------------------------------------------------------- 重启 + 健康

echo "[rollback-deploy] restart_cmd: ${RESTART_CMD}"
if ! bash -c "${RESTART_CMD}"; then
    mark_health_fail
    append_log "fail" "false"
    echo "[rollback-deploy] restart_cmd 执行失败（exit 5），状态已标记 health=fail" >&2
    exit 5
fi

echo "[rollback-deploy] health_cmd: ${HEALTH_CMD}"
if ! bash -c "${HEALTH_CMD}"; then
    mark_health_fail
    append_log "fail" "false"
    echo "[rollback-deploy] 健康检查失败（exit 3），状态已标记 health=fail" >&2
    exit 3
fi

append_log "pass" "true"
echo "[rollback-deploy] ✓ 回滚完成，留痕: ${LOG_FILE}"
exit 0
