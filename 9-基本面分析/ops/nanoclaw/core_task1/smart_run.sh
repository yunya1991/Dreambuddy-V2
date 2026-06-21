#!/bin/bash
# 核心任务 1：智能命令行入口
# 支持自然语言式命令

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

show_help() {
    cat << EOF
========================================
  核心任务 1：新闻简报生成系统
========================================

用法:
  ./smart_run.sh [命令] [选项]

命令:
  daily       - 生成每日简报（24 小时，默认）
  hours N     - 生成最近 N 小时的简报
  now         - 立即生成简报（同 daily）
  help        - 显示帮助

选项:
  -j, --json    同时输出 JSON
  -o FILE       指定输出文件名
  --model NAME  指定本地 Ollama 模型（默认 qwen2.5:7b-instruct）
  --ledger-version VER  事件账本版本（auto/9.3/9.5/9.7_direct/9.8_onchain）
  --update-mode MODE  更新模式（auto/anchor/delta/reset）
  --anchor-date DATE  指定锚点日期（YYYY-MM-DD）
  --anchor-session NAME  指定锚点时段（auto/apac/eu/us）
  --force-anchor      强制锚点模式

默认账本策略:
  --ledger-version auto = 主账本 V9.3 + 灰度叠加账本 V9.8 Onchain

示例:
  ./smart_run.sh                      # 默认每日简报
  ./smart_run.sh hours 4              # 最近 4 小时
  ./smart_run.sh hours 12 --json      # 最近 12 小时 + JSON
  ./smart_run.sh hours 2 -o my.md     # 最近 2 小时，自定义文件名
  ./smart_run.sh hours 4 --model qwen2.5:7b-instruct
  ./smart_run.sh hours 6 --ledger-version auto
  ./smart_run.sh hours 6 --ledger-version 9.3
  ./smart_run.sh daily --update-mode anchor
  ./smart_run.sh hours 2 --update-mode delta

========================================
EOF
}

# 参数转换：将 -j 转换为 --json
ARGS=()
for arg in "$@"; do
    case "$arg" in
        "-j")
            ARGS+=("--json")
            ;;
        "-q"|"--quiet")
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct}"
CLEAN_ARGS=()
i=0
while [ $i -lt ${#ARGS[@]} ]; do
    if [ "${ARGS[$i]}" = "--model" ]; then
        j=$((i + 1))
        if [ $j -ge ${#ARGS[@]} ]; then
            echo "错误：--model 需要指定模型名"
            exit 1
        fi
        OLLAMA_MODEL="${ARGS[$j]}"
        i=$((i + 2))
        continue
    fi
    CLEAN_ARGS+=("${ARGS[$i]}")
    i=$((i + 1))
done

# 解析命令
case "${CLEAN_ARGS[0]}" in
    "daily"|"now"|"")
        python3 scripts/news_digest_v2.py --hours 24 --use-ollama --ollama-model "$OLLAMA_MODEL" "${CLEAN_ARGS[@]:1}"
        ;;
    "hours")
        if [ -z "${CLEAN_ARGS[1]}" ]; then
            echo "错误：请指定小时数"
            echo "示例：./smart_run.sh hours 4"
            exit 1
        fi
        python3 scripts/news_digest_v2.py --hours "${CLEAN_ARGS[1]}" --use-ollama --ollama-model "$OLLAMA_MODEL" "${CLEAN_ARGS[@]:2}"
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        echo "未知命令：${ARGS[0]}"
        show_help
        exit 1
        ;;
esac
