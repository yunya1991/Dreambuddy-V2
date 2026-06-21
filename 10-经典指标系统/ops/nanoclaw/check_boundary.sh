set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NANO_DATA_DIR="${ROOT_DIR}/user_data/nanoclaw"
RO_FILE="${NANO_DATA_DIR}/mounts_ro.txt"
RW_FILE="${NANO_DATA_DIR}/mounts_rw.txt"

if [ ! -f "${RO_FILE}" ]; then
  echo "missing ${RO_FILE}" >&2
  exit 2
fi

if [ ! -f "${RW_FILE}" ]; then
  echo "missing ${RW_FILE}" >&2
  exit 2
fi

while IFS= read -r p; do
  [ -z "${p}" ] && continue
  if [ ! -d "${p}" ]; then
    echo "ro mount not found: ${p}" >&2
    exit 2
  fi
done < "${RO_FILE}"

while IFS= read -r p; do
  [ -z "${p}" ] && continue
  if [ ! -d "${p}" ]; then
    echo "rw mount not found: ${p}" >&2
    exit 2
  fi
done < "${RW_FILE}"

SENSITIVE_HITS="$(grep -E '/(\.env|keys?|secrets?|credentials?|config(_prod)?\.json)$' "${RO_FILE}" "${RW_FILE}" || true)"
if [ -n "${SENSITIVE_HITS}" ]; then
  echo "sensitive path detected in mount list" >&2
  echo "${SENSITIVE_HITS}" >&2
  exit 3
fi

echo "boundary check passed"
