set -e
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
bash "${ROOT_DIR}/ops/launchd/install_8092.sh" 8093 explore
