set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="${ROOT_DIR}/ops/launchd/com.ft.dashboard.plist"

UI_PORT_ARG="${1:-3001}"

case "${UI_PORT_ARG}" in
  ''|*[!0-9]*)
    echo "invalid ui port: ${UI_PORT_ARG}" >&2
    exit 2
    ;;
esac
if [ "${UI_PORT_ARG}" -le 0 ] || [ "${UI_PORT_ARG}" -ge 65536 ]; then
  echo "invalid ui port: ${UI_PORT_ARG}" >&2
  exit 2
fi


LABEL="com.ft.dashboard.${UI_PORT_ARG}"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${ROOT_DIR}/user_data/logs"

if [ ! -x "${ROOT_DIR}/frontend/node_modules/.bin/vite" ]; then
  if [ -f "${ROOT_DIR}/frontend/package-lock.json" ]; then
    (cd "${ROOT_DIR}/frontend" && npm ci)
  else
    (cd "${ROOT_DIR}/frontend" && npm install)
  fi
fi

python3 - <<PY
from pathlib import Path
src = Path(r"${PLIST_SRC}")
dst = Path(r"${PLIST_DST}")
text = src.read_text(encoding="utf-8")
text = text.replace("__PROJECT_DIR__", r"${ROOT_DIR}")
text = text.replace("__UI_PORT__", str(int("${UI_PORT_ARG}")))
text = text.replace("__LABEL__", str("${LABEL}"))
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
curl -sS -m 2 "http://127.0.0.1:${UI_PORT_ARG}/api/health" || true
