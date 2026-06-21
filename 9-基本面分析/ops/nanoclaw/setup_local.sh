set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NANO_DIR="${ROOT_DIR}/ops/nanoclaw"

if [ ! -f "${NANO_DIR}/jobs.local.json" ]; then
  cp "${NANO_DIR}/jobs.sample.json" "${NANO_DIR}/jobs.local.json"
fi

if [ ! -f "${NANO_DIR}/swarms.local.json" ]; then
  cp "${NANO_DIR}/swarms.sample.json" "${NANO_DIR}/swarms.local.json"
fi

python3 -m json.tool "${NANO_DIR}/jobs.local.json" >/dev/null
python3 -m json.tool "${NANO_DIR}/swarms.local.json" >/dev/null

echo "local config ready"
echo "jobs: ${NANO_DIR}/jobs.local.json"
echo "swarms: ${NANO_DIR}/swarms.local.json"
