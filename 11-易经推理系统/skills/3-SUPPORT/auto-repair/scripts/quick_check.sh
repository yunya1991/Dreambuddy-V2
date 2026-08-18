#!/bin/bash
# Auto-Repair 快速健康检查
# 用法: ./quick_check.sh

cd ~/.workbuddy/skills/auto-repair

echo "======================================"
echo "🔧 Auto-Repair 账户隔离快速检查"
echo "======================================"
echo ""

echo "1️⃣ 检查账户策略一致性..."
python3 scripts/account_monitor.py --check policy
echo ""

echo "2️⃣ 检查OKX配置..."
python3 scripts/account_monitor.py --check config | head -20
echo ""

echo "3️⃣ 生成完整报告..."
python3 scripts/account_monitor.py --scan -o /tmp/auto_repair_$(date +%Y%m%d_%H%M%S).md
echo ""

echo "✅ 检查完成！报告保存在 /tmp/auto_repair_*.md"
