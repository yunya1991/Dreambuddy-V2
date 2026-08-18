set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

cd "${ROOT_DIR}"

pytest tests -q -m "not slow"

python -m py_compile backend/src/_embedded_ml_trade_service_source.py backend/src/ml_trade_service.py

(
  cd frontend
  npm run lint
)

echo "pre_release_gate: ok"
