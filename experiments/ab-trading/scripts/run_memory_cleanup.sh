#!/bin/bash
# 记忆模块清理 — launchd / systemd 通用入口
# 本地：每日 02:05 由 com.dreambuddy.memory_cleanup 触发
# 云端：memory-cleanup.timer (02:05) 触发
#（策略更新在 02:00 执行，完成后再做记忆清理，避免资源竞争）
set -e

# 脚本位于 <repo>/experiments/ab-trading/scripts/，据此推导工程目录（去硬编码）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${AB_DIR}"
export PATH="${PATH}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
if [ -z "${PYTHON_BIN}" ]; then
    echo "ERROR: python3 not found (set PYTHON_BIN or PATH)" >&2
    exit 1
fi

"${PYTHON_BIN}" -c "from core.memory.memory_manager import MemoryManager; m = MemoryManager(); m.clean_expired_memories()"
