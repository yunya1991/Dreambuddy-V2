#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ASSET="${1:-BTC}"

node "${SCRIPT_DIR}/scripts/multi_agent_bridge.mjs" --asset "${ASSET}"

