set -e

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
UIDN="$(id -u)"

launchctl bootout "gui/${UIDN}" "${PLIST_DST}" >/dev/null 2>&1 || true
rm -f "${PLIST_DST}"
