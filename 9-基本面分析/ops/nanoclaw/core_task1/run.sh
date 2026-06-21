#!/bin/bash
# 核心任务 1：一键执行脚本
# 用于手动执行或 cron 定时任务调用

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b-instruct}"
LEDGER_VERSION="${LEDGER_VERSION:-auto}"
ARTIFACT_LIFECYCLE_ENABLED="${ARTIFACT_LIFECYCLE_ENABLED:-1}"
ARTIFACT_LIFECYCLE_DRY_RUN="${ARTIFACT_LIFECYCLE_DRY_RUN:-0}"
ARTIFACT_LIFECYCLE_LOG_FILE="${ARTIFACT_LIFECYCLE_LOG_FILE:-${SCRIPT_DIR}/logs/artifact_lifecycle.log}"

show_help() {
cat << EOF
用法:
  ./run.sh [--ledger-version VER]

说明:
  默认执行 24h 简报生成，启用本地 Ollama。
  --ledger-version auto = 主账本 V9.3 + 灰度叠加账本 V9.8 Onchain

可选账本版本:
  auto | 9.3 | 9.5 | 9.7_direct | 9.8_onchain

示例:
  ./run.sh
  ./run.sh --ledger-version auto
  ./run.sh --ledger-version 9.3
EOF
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    show_help
    exit 0
fi

if [ "$1" = "--ledger-version" ]; then
    if [ -z "$2" ]; then
        echo "错误：--ledger-version 需要指定版本"
        exit 1
    fi
    LEDGER_VERSION="$2"
fi

echo "=========================================="
echo "  核心任务 1:24h 加密 + 宏观新闻简报"
echo "=========================================="
echo ""

# 执行 Python 脚本（默认启用本地 Ollama）
python3 scripts/news_digest_v2.py --hours 24 --json --use-ollama --ollama-model "$OLLAMA_MODEL" --ledger-version "$LEDGER_VERSION"

# 检查执行结果
if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "  ✅ 执行成功"
    echo "=========================================="
    echo ""
    echo "输出文件:"
    ls -lt outputs/*.md | head -3
    echo ""
    echo "原始数据:"
    ls -lt raw/*.json | head -5
    if [ "${ARTIFACT_LIFECYCLE_ENABLED}" = "1" ]; then
        mkdir -p "${SCRIPT_DIR}/logs"
        DRY_RUN_FLAG=""
        if [ "${ARTIFACT_LIFECYCLE_DRY_RUN}" = "1" ]; then
            DRY_RUN_FLAG="--dry-run"
        fi
        python3 scripts/artifact_lifecycle.py cleanup --project-root "${SCRIPT_DIR}" --archive-root "${SCRIPT_DIR}/archive/artifacts" ${DRY_RUN_FLAG} >> "${ARTIFACT_LIFECYCLE_LOG_FILE}" 2>&1 || true
    fi
else
    echo ""
    echo "=========================================="
    echo "  ❌ 执行失败"
    echo "=========================================="
    exit 1
fi
