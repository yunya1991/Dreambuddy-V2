set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="${ROOT_DIR}/ops/launchd/com.ft.ml_trade_service.8092.plist"

PORT_ARG="${1:-8092}"
PROFILE_ARG="${2:-}"
case "${PORT_ARG}" in
  ''|*[!0-9]*)
    echo "invalid port: ${PORT_ARG}" >&2
    exit 2
    ;;
esac
if [ "${PORT_ARG}" -le 0 ] || [ "${PORT_ARG}" -ge 65536 ]; then
  echo "invalid port: ${PORT_ARG}" >&2
  exit 2
fi

case "${PROFILE_ARG}" in
  ""|"prod"|"explore"|"pilot")
    ;;
  *)
    echo "invalid profile: ${PROFILE_ARG}" >&2
    exit 2
    ;;
esac

PROFILE="${PROFILE_ARG}"
if [ -z "${PROFILE}" ]; then
  PROFILE="p${PORT_ARG}"
fi

if [ "${PROFILE_ARG}" = "prod" ] || [ "${PROFILE_ARG}" = "explore" ] || [ "${PROFILE_ARG}" = "pilot" ]; then
  LABEL="com.ft.ml_trade_service.${PROFILE_ARG}"
else
  LABEL="com.ft.ml_trade_service.${PORT_ARG}"
fi

USER_DATA_DIR="${ROOT_DIR}/user_data"
if [ "${PROFILE_ARG}" = "prod" ] || [ "${PROFILE_ARG}" = "explore" ] || [ "${PROFILE_ARG}" = "pilot" ]; then
  USER_DATA_DIR="${ROOT_DIR}/user_data_${PROFILE_ARG}"
fi
STRICT_USER_DOTENV="0"
if [ "${PROFILE_ARG}" = "explore" ] || [ "${PROFILE_ARG}" = "pilot" ]; then
  STRICT_USER_DOTENV="1"
fi
LOG_DIR="${USER_DATA_DIR}/logs"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${LOG_DIR}"

python3 - <<PY
from pathlib import Path
src = Path(r"${PLIST_SRC}")
dst = Path(r"${PLIST_DST}")
text = src.read_text(encoding="utf-8")
text = text.replace("__PROJECT_DIR__", r"${ROOT_DIR}")
text = text.replace("__PORT__", str(int("${PORT_ARG}")))
text = text.replace("__LABEL__", str("${LABEL}"))
text = text.replace("__PROFILE__", str("${PROFILE}"))
text = text.replace("__ML_USER_DATA_DIR__", r"${USER_DATA_DIR}")
text = text.replace("__ML_STRICT_USER_DOTENV__", str("${STRICT_USER_DOTENV}"))
text = text.replace("__LOG_DIR__", r"${LOG_DIR}")
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
curl -sS "http://127.0.0.1:${PORT_ARG}/health"
