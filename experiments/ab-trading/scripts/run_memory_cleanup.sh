#!/bin/bash
# 记忆模块清理 — launchd 调用入口
# 每日 02:05 由 com.dreambuddy.memory_cleanup 触发
# （策略更新在 02:00 执行，完成后再做记忆清理，避免资源竞争）
set -e
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PYTHONIOENCODING=utf-8
export PYTHONUNBUFFERED=1
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
/opt/homebrew/bin/python3 -c "from core.memory.memory_manager import MemoryManager; m = MemoryManager(); m.clean_expired_memories()"
