set -e

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

if [ "${PROFILE_ARG}" = "prod" ] || [ "${PROFILE_ARG}" = "explore" ] || [ "${PROFILE_ARG}" = "pilot" ]; then
  LABEL="com.ft.ml_trade_service.${PROFILE_ARG}"
else
  LABEL="com.ft.ml_trade_service.${PORT_ARG}"
fi
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
UIDN="$(id -u)"

launchctl bootout "gui/${UIDN}" "${PLIST_DST}" >/dev/null 2>&1 || true
rm -f "${PLIST_DST}"
