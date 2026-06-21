set -e

LABEL="com.ft.fundamental_research_sync"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
UIDN="$(id -u)"

launchctl bootout "gui/${UIDN}" "${PLIST_DST}" >/dev/null 2>&1 || true
rm -f "${PLIST_DST}"
