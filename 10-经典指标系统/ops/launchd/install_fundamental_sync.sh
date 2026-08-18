set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="${ROOT_DIR}/ops/launchd/com.ft.fundamental_research_sync.plist"

INTERVAL_SEC_ARG="${1:-600}"
RESEARCH_ROOT_ARG="${2:-/Users/zhangjiangtao/ft_userdata/基本面分析_fundamental}"
PYTHON_BIN_ARG="${3:-python3}"
SYNC_BASELINE_SEC_ARG="${4:-28800}"
SYNC_BURST_SEC_ARG="${5:-900}"
SYNC_BURST_HOLD_SEC_ARG="${6:-7200}"
SYNC_SLA_SEC_ARG="${7:-900}"
LABEL="com.ft.fundamental_research_sync"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

for N in "${INTERVAL_SEC_ARG}" "${SYNC_BASELINE_SEC_ARG}" "${SYNC_BURST_SEC_ARG}" "${SYNC_BURST_HOLD_SEC_ARG}" "${SYNC_SLA_SEC_ARG}"; do
case "${N}" in
  ''|*[!0-9]*)
    echo "invalid numeric arg: ${N}" >&2
    exit 2
    ;;
esac
done
if [ "${INTERVAL_SEC_ARG}" -lt 60 ]; then
  echo "interval sec too small: ${INTERVAL_SEC_ARG}" >&2
  exit 2
fi
if [ "${SYNC_BURST_SEC_ARG}" -lt 60 ]; then
  echo "burst sec too small: ${SYNC_BURST_SEC_ARG}" >&2
  exit 2
fi
if [ "${SYNC_BASELINE_SEC_ARG}" -lt "${SYNC_BURST_SEC_ARG}" ]; then
  echo "baseline sec must be >= burst sec" >&2
  exit 2
fi

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${ROOT_DIR}/user_data/logs"

python3 - <<PY
from pathlib import Path
src = Path(r"${PLIST_SRC}")
dst = Path(r"${PLIST_DST}")
text = src.read_text(encoding="utf-8")
text = text.replace("__PROJECT_DIR__", r"${ROOT_DIR}")
text = text.replace("__INTERVAL_SEC__", str(int("${INTERVAL_SEC_ARG}")))
text = text.replace("__LABEL__", str("${LABEL}"))
text = text.replace("__RESEARCH_ROOT__", r"${RESEARCH_ROOT_ARG}")
text = text.replace("__PYTHON_BIN__", r"${PYTHON_BIN_ARG}")
text = text.replace("__SYNC_BASELINE_SEC__", str(int("${SYNC_BASELINE_SEC_ARG}")))
text = text.replace("__SYNC_BURST_SEC__", str(int("${SYNC_BURST_SEC_ARG}")))
text = text.replace("__SYNC_BURST_HOLD_SEC__", str(int("${SYNC_BURST_HOLD_SEC_ARG}")))
text = text.replace("__SYNC_SLA_SEC__", str(int("${SYNC_SLA_SEC_ARG}")))
dst.write_text(text, encoding="utf-8")
print(str(dst))
PY

/usr/bin/plutil -lint "${PLIST_DST}"

UIDN="$(id -u)"
launchctl bootout "gui/${UIDN}" "${PLIST_DST}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/${UIDN}" "${PLIST_DST}"
launchctl enable "gui/${UIDN}/${LABEL}" || true
launchctl kickstart -k "gui/${UIDN}/${LABEL}"

sleep 2
tail -n 5 "${ROOT_DIR}/user_data/logs/fundamental_sync.log" || true
