set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${CORE_DIR}/.env"

API_BASE_PROD="${REPORT_API_BASE_PROD:-http://8.209.238.108/api/v1}"
API_BASE_TEST="${REPORT_API_BASE_TEST:-http://8.209.238.108/api/v1}"
PUSH_MODE="${REPORT_PUSH_MODE:-prod}"
STATE_FILE="${REPORT_PUSH_STATE_FILE:-${CORE_DIR}/raw/report_push_state.json}"
RECEIPT_FILE="${REPORT_PUSH_RECEIPT_FILE:-${CORE_DIR}/raw/report_push_outbox.jsonl}"
API_KEY="${INTERNAL_API_KEY:-}"
TRANSFORM_PROFILE="${REPORT_PUSH_TRANSFORM_PROFILE:-daily_report_v2_tavily}"
TAVILY_KEY="${TAVILY_API_KEY:-}"

_normalize_url() {
  local v
  v="$1"
  v="$(printf '%s' "${v}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  v="${v#\`}"
  v="${v%\`}"
  v="$(printf '%s' "${v}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  printf '%s' "${v}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --api-key)
      API_KEY="${2:-}"
      shift 2
      ;;
    --mode)
      PUSH_MODE="${2:-prod}"
      shift 2
      ;;
    --api-base-prod)
      API_BASE_PROD="${2:-$API_BASE_PROD}"
      shift 2
      ;;
    --api-base-test)
      API_BASE_TEST="${2:-$API_BASE_TEST}"
      shift 2
      ;;
    --tavily-api-key)
      TAVILY_KEY="${2:-}"
      shift 2
      ;;
    *)
      echo "unsupported arg: $1" >&2
      exit 2
      ;;
  esac
done

API_BASE_PROD="$(_normalize_url "${API_BASE_PROD}")"
API_BASE_TEST="$(_normalize_url "${API_BASE_TEST}")"

if [ -z "${API_KEY}" ]; then
  printf "INTERNAL_API_KEY: "
  stty -echo
  IFS= read -r API_KEY
  stty echo
  printf "\n"
fi

if [ -z "${API_KEY}" ]; then
  echo "empty INTERNAL_API_KEY" >&2
  exit 2
fi

mkdir -p "${CORE_DIR}/raw"
umask 077
cat >"${ENV_FILE}" <<EOF
REPORT_PUSH_MODE=${PUSH_MODE}
REPORT_API_BASE_PROD=${API_BASE_PROD}
REPORT_API_BASE_TEST=${API_BASE_TEST}
INTERNAL_API_KEY=${API_KEY}
REPORT_PUSH_STATE_FILE=${STATE_FILE}
REPORT_PUSH_RECEIPT_FILE=${RECEIPT_FILE}
REPORT_PUSH_TRANSFORM_PROFILE=${TRANSFORM_PROFILE}
TAVILY_API_KEY=${TAVILY_KEY}
EOF

chmod 600 "${ENV_FILE}" || true
echo "${ENV_FILE}"
