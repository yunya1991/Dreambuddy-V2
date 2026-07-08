#!/bin/bash
# validate_all_timestamps.sh - 批量验证产物时间戳
# 路径: ~/.workbuddy/skills/artifact-alignment-manager/scripts/
# 用法: bash validate_all_timestamps.sh [目录]
# 不带参数时检查所有 artifacts 目录

ARTIFACTS_DIR="${1:-$HOME/.workbuddy/artifacts}"
ERRORS=0
WARNINGS=0

echo "🔍 时间戳批量验证开始..."
echo "📁 检查目录: $ARTIFACTS_DIR"
echo "---"

# 检查单个文件的时间戳格式
check_file() {
    local file="$1"
    local ts=$(grep -m1 "^date:" "$file" 2>/dev/null | sed 's/^date:.*"\(.*\)".*/\1/')

    if [ -z "$ts" ]; then
        echo "🔴 $file: 缺少 date 字段"
        ERRORS=$((ERRORS+1))
        return
    fi

    if ! echo "$ts" | grep -qE '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$'; then
        echo "🔴 $file: 格式错误 [$ts]"
        ERRORS=$((ERRORS+1))
        return
    fi

    # 检查月/日补零
    if echo "$ts" | grep -qE '-\d-\dT'; then
        echo "🟡 $file: 缺少补零 [$ts]"
        WARNINGS=$((WARNINGS+1))
    fi
}

# 遍历所有 .md 文件
if [ -d "$ARTIFACTS_DIR" ]; then
    find "$ARTIFACTS_DIR" -name "*.md" -type f | while read -r f; do
        check_file "$f"
    done
else
    echo "⚠️ 目录不存在: $ARTIFACTS_DIR"
    exit 1
fi

echo "---"
echo "📊 验证完成: 🔴 $ERRORS 个错误, 🟡 $WARNINGS 个警告"

if [ $ERRORS -gt 0 ]; then
    echo "🔴 P0 违规存在，禁止投递！"
    exit 1
fi

exit 0
