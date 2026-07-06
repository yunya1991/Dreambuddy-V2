#!/bin/bash
# Auto-Repair 完整健康检查脚本 v1.2
# 包含五阶段完整检查清单
# v1.2: 移除顾问邮箱检查（2026-04-26 废弃，顾问内嵌SKILL）

echo "=============================================="
echo "🔧 Auto-Repair 完整健康检查 v1.1"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="
echo ""

REPORT_DIR="/tmp/auto_repair_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

echo "📁 报告目录: $REPORT_DIR"
echo ""

# ==================== 第一阶段：账户隔离 ====================
echo "=============================================="
echo "🔒 第一阶段：账户隔离检查"
echo "=============================================="
echo ""

echo "1.1 检查账户策略一致性..."
python3 ~/.workbuddy/skills/auto-repair/scripts/account_monitor.py --check policy > "$REPORT_DIR/1_policy.json" 2>&1
echo "    结果: $(grep -q 'is_consistent.*true' "$REPORT_DIR/1_policy.json" && echo '✅ 一致' || echo '❌ 不一致')"

echo "1.2 检查OKX配置..."
python3 ~/.workbuddy/skills/auto-repair/scripts/account_monitor.py --check config > "$REPORT_DIR/2_config.json" 2>&1
echo "    结果: $(grep -q '"issues": \[\]' "$REPORT_DIR/2_config.json" && echo '✅ 无问题' || echo '⚠️ 有问题')"

echo "1.3 检测账户混淆风险..."
python3 ~/.workbuddy/skills/auto-repair/scripts/account_monitor.py --scan > "$REPORT_DIR/3_confusion.md" 2>&1
CONFU_COUNT=$(grep -c "账户混淆风险" "$REPORT_DIR/3_confusion.md" 2>/dev/null || echo "0")
echo "    结果: 检测到 $CONFU_COUNT 个潜在混淆"

echo ""

# ==================== 第二阶段：四邮箱状态 ====================
echo "=============================================="
echo "📬 第二阶段：三邮箱状态检查（顾问已内嵌SKILL）"
echo "=============================================="
echo ""

python3 ~/.workbuddy/skills/auto-repair/scripts/mailbox_monitor.py > "$REPORT_DIR/4_mailbox.md" 2>&1
echo "    秘书邮箱: $(grep -A1 '秘书邮箱' "$REPORT_DIR/4_mailbox.md" | grep '状态' | awk '{print $2}')"
echo "    调研部: $(grep -A1 '调研部' "$REPORT_DIR/4_mailbox.md" | grep '状态' | awk '{print $2}')"
echo "    待修复: $(grep -A1 '待修复' "$REPORT_DIR/4_mailbox.md" | grep '状态' | awk '{print $2}')"
echo "    (顾问邮箱已废弃，顾问内嵌SKILL直接调用)"

echo ""

# ==================== 第三阶段：提案状态 ====================
echo "=============================================="
echo "📋 第三阶段：提案生命周期检查"
echo "=============================================="
echo ""

cd /Users/zhangjiangtao/WorkBuddy/20260415144304/reports/proposals

TODAY_PROPOSALS=$(ls dream_proposal_*20260424*.md 2>/dev/null | wc -l | tr -d ' ')
ARCHIVE_COUNT=$(ls archive/*.md 2>/dev/null | wc -l | tr -d ' ')

echo "    今日(4/24)提案: $TODAY_PROPOSALS 个"
echo "    已归档提案: $ARCHIVE_COUNT 个"

if [ "$ARCHIVE_COUNT" -lt 20 ]; then
    echo "    ⚠️ 历史提案(4/20-4/23)建议归档"
fi

# 检查P0提案
if [ -f "dream_proposal_DREAM-PROPOSAL-20260424-001.md" ]; then
    echo "    ✅ P0提案001存在"
fi
if [ -f "dream_proposal_DREAM-PROPOSAL-20260424-002.md" ]; then
    echo "    ✅ P0提案002存在"
fi

echo ""

# ==================== 第四阶段：系统配置 ====================
echo "=============================================="
echo "⚙️ 第四阶段：系统配置检查"
echo "=============================================="
echo ""

# Skill数量
SKILL_COUNT=$(ls -d ~/.workbuddy/skills/*/ 2>/dev/null | wc -l | tr -d ' ')
echo "    已安装Skill: $SKILL_COUNT 个"

# 记忆文件
MEMORY_FILES=$(ls /Users/zhangjiangtao/WorkBuddy/20260415144304/.workbuddy/memory/*.md 2>/dev/null | wc -l | tr -d ' ')
echo "    记忆文件: $MEMORY_FILES 个"

# OKX API测试
echo "    OKX API: $(okx market ticker instId BTC-USDT-SWAP 2>&1 | grep -q 'BTC' && echo '✅ 正常' || echo '❌ 异常')"

echo ""

# ==================== 汇总报告 ====================
echo "=============================================="
echo "📊 健康检查汇总"
echo "=============================================="

echo ""
echo "✅ 检查完成！"
echo "📁 详细报告: $REPORT_DIR"
echo ""
ls -la "$REPORT_DIR/"
}
