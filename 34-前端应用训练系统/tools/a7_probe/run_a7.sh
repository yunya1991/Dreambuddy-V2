#!/usr/bin/env bash
# A7 单进程多会话实跑驱动（sandbox profile，stub LLM，不消耗额度）
#
# 用法：bash 34-前端应用训练系统/tools/a7_probe/run_a7.sh
# 证据：stderr 的 A7_STUB 行（同 pid、并发峰值）+ dsh 输出中的 ROOT_DONE/CHILD_DONE。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DSH_HOME_DIR="$ROOT/1-ARCHITECTURE/dream-harness-bridge/.dsh-home"
PROFILE_DIR="$DSH_HOME_DIR/profiles/sandbox"
PLUGIN_SRC="$ROOT/34-前端应用训练系统/tools/a7_probe/stub_llm_plugin"
PLUGIN_DST="$PROFILE_DIR/node_modules/dsh-plugin-stub-llm"
PATCH_FILE="$ROOT/34-前端应用训练系统/tools/a7_probe/a7.patch.yml"

rm -rf "$PLUGIN_DST"
cp -R "$PLUGIN_SRC" "$PLUGIN_DST"

export DSH_HOME="$DSH_HOME_DIR"
exec dsh --profile sandbox --patch "$PATCH_FILE" "A7-SPAWN 单进程多会话并发验证：请启动两个子会话"
