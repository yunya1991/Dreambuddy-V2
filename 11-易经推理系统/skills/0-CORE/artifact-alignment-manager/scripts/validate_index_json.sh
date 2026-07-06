#!/bin/bash
# validate_index_json.sh - 验证 index.json 时间戳
# 路径: ~/.workbuddy/skills/artifact-alignment-manager/scripts/
# 用法: bash validate_index_json.sh [目录]
# 不带参数时检查所有 artifacts/index.json

ARTIFACTS_DIR="${1:-$HOME/.workbuddy/artifacts}"
ERRORS=0
WARNINGS=0

echo "🔍 index.json 时间戳验证开始..."
echo "📁 检查目录: $ARTIFACTS_DIR"
echo "---"

# 遍历所有 index.json
find "$ARTIFACTS_DIR" -name "index.json" -type f | while read -r idx; do
    echo "📄 检查: $idx"

    # 使用 python3 解析 JSON
    if command -v python3 &> /dev/null; then
        python3 -c "
import json
import sys
import os

idx = '$idx'
errors = 0
warnings = 0

try:
    with open(idx, 'r') as f:
        items = json.load(f)

    for i, item in enumerate(items):
        date = item.get('date', '')
        chain_phase = item.get('chain_phase', 'unknown')
        rel_path = item.get('rel_path', '')

        # 检查是否存在
        if not date:
            print(f'  🔴 [{chain_phase}] {rel_path}: date 字段为空')
            errors += 1
            continue

        # 检查格式
        import re
        if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+\d{2}:\d{2}$', date):
            print(f'  🔴 [{chain_phase}] {rel_path}: 格式错误 [{date}]')
            errors += 1
            continue

        # 检查补零
        if re.search(r'-\d-\dT', date):
            print(f'  🟡 [{chain_phase}] {rel_path}: 缺少补零 [{date}]')
            warnings += 1

    print(f'  📊 {os.path.dirname(idx)}: 🔴 {errors} 个错误, 🟡 {warnings} 个警告')
    if errors > 0:
        sys.exit(1)

except Exception as e:
    print(f'  ⚠️ 解析错误: {e}')
    sys.exit(1)
" || true
    else
        echo "  ⚠️ python3 不可用，跳过"
    fi
done

echo "---"
echo "📊 验证完成: 🔴 $ERRORS 个错误, 🟡 $WARNINGS 个警告"

if [ $ERRORS -gt 0 ]; then
    echo "🔴 P0 违规存在，index.json 必须修复！"
    exit 1
fi

exit 0
