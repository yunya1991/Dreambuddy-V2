set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${CORE_DIR}"
python3 scripts/push_report_api.py --preflight --timeout-sec "${PREFLIGHT_TIMEOUT_SEC:-8}"
