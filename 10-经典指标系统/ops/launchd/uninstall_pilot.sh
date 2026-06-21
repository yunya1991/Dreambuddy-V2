set -e
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
bash "${ROOT_DIR}/ops/launchd/uninstall_8092.sh" 8094 pilot
