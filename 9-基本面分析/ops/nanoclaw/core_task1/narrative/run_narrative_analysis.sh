#!/bin/bash
# 加密市场叙事分析 Skill - 快速运行脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 默认参数
HOURS=24
OUTPUT=""
MOCK=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        hours)
            HOURS="$2"
            shift 2
            ;;
        --mock)
            MOCK=true
            shift
            ;;
        -o|--output)
            OUTPUT="$2"
            shift 2
            ;;
        -h|--help)
            echo "加密市场叙事分析 Skill - 使用说明"
            echo ""
            echo "用法:"
            echo "  ./run_narrative_analysis.sh [选项]"
            echo ""
            echo "选项:"
            echo "  hours <N>      分析最近 N 小时的事件 (默认：24)"
            echo "  --mock         使用模拟数据演示"
            echo "  -o, --output   指定输出文件路径"
            echo "  -h, --help     显示帮助信息"
            echo ""
            echo "示例:"
            echo "  # 分析最近 24 小时 (使用真实数据)"
            echo "  ./run_narrative_analysis.sh"
            echo ""
            echo "  # 分析最近 4 小时"
            echo "  ./run_narrative_analysis.sh hours 4"
            echo ""
            echo "  # 使用模拟数据演示"
            echo "  ./run_narrative_analysis.sh --mock"
            echo ""
            echo "  # 输出到指定文件"
            echo "  ./run_narrative_analysis.sh --mock -o my_narrative_brief.md"
            echo ""
            exit 0
            ;;
        *)
            echo "未知选项：$1"
            echo "使用 -h 或 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 构建命令
CMD="python3 scripts/narrative_analyzer.py --hours $HOURS"

if [ "$MOCK" = true ]; then
    CMD="$CMD --mock"
fi

if [ -n "$OUTPUT" ]; then
    CMD="$CMD --output $OUTPUT"
fi

# 执行
echo "========================================"
echo "加密市场叙事分析 Skill"
echo "========================================"
echo ""
eval $CMD

echo ""
echo "========================================"
echo "运行完成!"
echo "========================================"
