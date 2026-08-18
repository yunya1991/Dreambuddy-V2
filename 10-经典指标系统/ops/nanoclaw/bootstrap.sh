set -e

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NANO_DATA_DIR="${ROOT_DIR}/user_data/nanoclaw"
NANO_REPO_DIR="${ROOT_DIR}/user_data/agent_repo/nanoclaw"
NANO_REPO_URL="${NANO_REPO_URL:-https://github.com/qwibitai/nanoclaw.git}"
MLTS_BASE_URL="${MLTS_BASE_URL:-http://127.0.0.1:8092}"

mkdir -p "${ROOT_DIR}/user_data/agent_repo"
mkdir -p "${NANO_DATA_DIR}/workspace"
mkdir -p "${NANO_DATA_DIR}/state"
mkdir -p "${NANO_DATA_DIR}/logs"

if [ ! -d "${NANO_REPO_DIR}/.git" ]; then
  if ! git clone "${NANO_REPO_URL}" "${NANO_REPO_DIR}"; then
    rm -rf "${NANO_REPO_DIR}"
    mkdir -p "${NANO_REPO_DIR}"
    printf "repo_clone_failed=1\nrepo_url=%s\n" "${NANO_REPO_URL}" > "${NANO_REPO_DIR}/CLONE_FAILED.txt"
  fi
fi

cat > "${NANO_DATA_DIR}/mounts_ro.txt" <<EOF
EOF

RO_CANDIDATES=(
  "${ROOT_DIR}/user_data/agent_outbox"
  "${ROOT_DIR}/user_data_prod/agent_outbox"
  "${ROOT_DIR}/user_data_pilot/agent_outbox_pilot"
  "${ROOT_DIR}/user_data_explore/agent_outbox_explore"
)

for p in "${RO_CANDIDATES[@]}"; do
  if [ -d "${p}" ]; then
    printf "%s\n" "${p}" >> "${NANO_DATA_DIR}/mounts_ro.txt"
  fi
done

cat > "${NANO_DATA_DIR}/mounts_rw.txt" <<EOF
${NANO_DATA_DIR}/workspace
${NANO_DATA_DIR}/state
${NANO_DATA_DIR}/logs
EOF

cat > "${NANO_DATA_DIR}/mount-allowlist.json" <<EOF
{
  "allowedRoots": [
    {
      "path": "${ROOT_DIR}/user_data",
      "allowReadWrite": false,
      "description": "QF system user_data (read-only)"
    },
    {
      "path": "${ROOT_DIR}/user_data_prod",
      "allowReadWrite": false,
      "description": "QF system user_data_prod (read-only)"
    },
    {
      "path": "${ROOT_DIR}/user_data_pilot",
      "allowReadWrite": false,
      "description": "QF system user_data_pilot (read-only)"
    },
    {
      "path": "${ROOT_DIR}/user_data_explore",
      "allowReadWrite": false,
      "description": "QF system user_data_explore (read-only)"
    },
    {
      "path": "${NANO_DATA_DIR}",
      "allowReadWrite": true,
      "description": "NanoClaw workspace/state/logs (read-write)"
    }
  ],
  "blockedPatterns": [],
  "nonMainReadOnly": true
}
EOF

cat > "${NANO_DATA_DIR}/env.nanoclaw.local" <<EOF
MLTS_BASE_URL=${MLTS_BASE_URL}
CONTAINER_RUNTIME=container
NANO_MOUNTS_RO_FILE=${NANO_DATA_DIR}/mounts_ro.txt
NANO_MOUNTS_RW_FILE=${NANO_DATA_DIR}/mounts_rw.txt
NANO_MOUNT_ALLOWLIST_PATH=${NANO_DATA_DIR}/mount-allowlist.json
NANO_STATE_DIR=${NANO_DATA_DIR}/state
NANO_WORKSPACE_DIR=${NANO_DATA_DIR}/workspace
NANO_LOG_DIR=${NANO_DATA_DIR}/logs
EOF

echo "NanoClaw 初始化完成"
echo "1) cd \"${NANO_REPO_DIR}\""
echo "2) claude"
echo "3) 在 Claude Code 中执行 /setup 与渠道技能安装"
if [ -f "${NANO_REPO_DIR}/CLONE_FAILED.txt" ]; then
  echo "4) 当前网络未完成仓库拉取，先修复网络后执行: git clone ${NANO_REPO_URL} ${NANO_REPO_DIR}"
fi
