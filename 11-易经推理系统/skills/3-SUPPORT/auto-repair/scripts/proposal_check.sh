#!/bin/bash
#==============================================================================
# Auto-Repair 提案落地检查脚本 v2.0
# 
# 功能：扫描提案、标注状态、执行落地、更新报告
# 调用：检查完邮箱后自动触发
#==============================================================================

set -e

WORKSPACE="/Users/zhangjiangtao/WorkBuddy/20260415144304"
PROPOSALS_DIR="$WORKSPACE/reports/proposals"
ARCHIVE_DIR="$PROPOSALS_DIR/archive"
STATUS_FILE="$PROPOSALS_DIR/PROPOSAL_STATUS_$(date +%Y%m%d).md"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

#==============================================================================
# 1. 扫描今日提案
#==============================================================================
scan_today_proposals() {
    log_info "📋 扫描今日提案..."
    
    local count=$(ls -1 "$PROPOSALS_DIR"/dream_proposal_DREAM-PROPOSAL-$(date +%Y%m%d)-*.md 2>/dev/null | wc -l | tr -d ' ')
    log_info "  今日提案数量: $count"
    
    if [ "$count" -eq 0 ]; then
        log_warn "  今日无新提案"
        return 1
    fi
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📋 今日提案列表"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    for f in "$PROPOSALS_DIR"/dream_proposal_DREAM-PROPOSAL-$(date +%Y%m%d)-*.md; do
        if [ -f "$f" ]; then
            local id=$(basename "$f" | grep -oE '[0-9]+_[0-9]+')
            local priority=$(grep -E "P[0-2]|优先级|priority" "$f" 2>/dev/null | head -1 | sed 's/.*P/P/' | cut -c1-15)
            local status=$(tail -10 "$f" 2>/dev/null | grep -E "✅|⏸️|⚠️|已落地|推迟|待落地" | tail -1 | sed 's/^[[:space:]]*//')
            
            echo ""
            echo "  📄 $(basename "$f")"
            echo "     ID: $id | 优先级: ${priority:-未标注} | 状态: ${status:-未标注}"
        fi
    done
}

#==============================================================================
# 2. 检查提案落地状态
#==============================================================================
check_proposal_status() {
    log_info "🔍 检查提案落地状态..."
    
    local total=0
    local implemented=0
    local postponed=0
    local pending=0
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 提案状态统计"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "| 编号 | 优先级 | 状态 | 落地位置 |"
    echo "|:---|:---:|:---:|:---|"
    
    # 检查今日提案
    for f in "$PROPOSALS_DIR"/dream_proposal_DREAM-PROPOSAL-$(date +%Y%m%d)-*.md; do
        if [ -f "$f" ]; then
            ((total++))
            local id=$(basename "$f" | grep -oE '[0-9]+' | tail -1)
            local priority=$(grep -E "P[0-2]|优先级" "$f" 2>/dev/null | head -1 | grep -oE "P[0-2]" | head -1)
            local status_line=$(tail -15 "$f" 2>/dev/null | grep -E "状态.*✅|状态.*⏸️|状态.*⚠️|已落地|推迟|待落地" | tail -1)
            local location=$(grep -E "落地位置|SKILL|落地到" "$f" 2>/dev/null | head -1 | cut -c1-50)
            
            if echo "$status_line" | grep -q "✅\|已落地"; then
                ((implemented++))
                status="✅ 已落地"
            elif echo "$status_line" | grep -q "⏸️\|推迟"; then
                ((postponed++))
                status="⏸️ 推迟"
            else
                ((pending++))
                status="⚠️ 待处理"
            fi
            
            echo "| $id | ${priority:-P?} | $status | ${location:-未标注} |"
        fi
    done
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "| 类别 | 数量 |"
    echo "|:---|:---:|"
    echo "| 总数 | $total |"
    echo "| ✅ 已落地 | $implemented |"
    echo "| ⏸️ 推迟 | $postponed |"
    echo "| ⚠️ 待处理 | $pending |"
    echo ""
    
    return 0
}

#==============================================================================
# 3. 检查历史提案归档
#==============================================================================
check_archive() {
    log_info "📦 检查历史提案归档..."
    
    local archive_count=$(ls -1 "$ARCHIVE_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
    log_info "  归档提案数量: $archive_count"
    
    # 按月份统计
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 历史提案归档统计"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "| 日期 | 归档数量 | 状态标注 |"
    echo "|:---|:---:|:---:|"
    
    for month_dir in "$ARCHIVE_DIR"/*/; do
        if [ -d "$month_dir" ]; then
            local month=$(basename "$month_dir")
            local count=$(ls -1 "$month_dir"/*.md 2>/dev/null | wc -l | tr -d ' ')
            local annotated=$(grep -l "落地状态\|已落地\|⏸️" "$month_dir"/*.md 2>/dev/null | wc -l | tr -d ' ')
            echo "| $month | $count | $annotated/$count |"
        fi
    done
    
    # 检查根目录archive
    local root_count=$(ls -1 "$ARCHIVE_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
    if [ "$root_count" -gt 0 ]; then
        local root_annotated=$(grep -l "落地状态\|已落地\|⏸️" "$ARCHIVE_DIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
        echo "| 根目录 | $root_count | $root_annotated/$root_count |"
    fi
    echo ""
}

#==============================================================================
# 4. 生成提案状态报告
#==============================================================================
generate_status_report() {
    log_info "📝 生成提案状态报告..."
    
    local today=$(date +%Y-%m-%d)
    local timestamp=$(date +"%Y-%m-%d %H:%M")
    
    cat > "$STATUS_FILE" << EOF
# 提案状态报告 - $today

> 生成时间: $timestamp  
> 触发来源: auto-repair 健康检查

---

## 📊 今日提案状态

| 编号 | 标题 | 状态 | 落地位置 | 执行时间 |
|:---|:---|:---:|:---|:---|
EOF

    # 填充今日提案
    for f in "$PROPOSALS_DIR"/dream_proposal_DREAM-PROPOSAL-$(date +%Y%m%d)-*.md; do
        if [ -f "$f" ]; then
            local id=$(basename "$f" | grep -oE '[0-9]+' | tail -1)
            local title=$(grep -E "^#|^##" "$f" 2>/dev/null | head -1 | sed 's/^#* //')
            local status=$(tail -10 "$f" 2>/dev/null | grep -E "✅|⏸️|⚠️" | tail -1 | sed 's/^[[:space:]]*//' | cut -c1-15)
            local location=$(grep -E "落地位置|SKILL" "$f" 2>/dev/null | head -1 | sed 's/.*`//' | sed 's/`.*//' | cut -c1-30)
            local exec_time=$(grep -E "落地状态.*[0-9]{4}" "$f" 2>/dev/null | grep -oE "[0-9]{4}-[0-9]{2}-[0-9]{2}" | tail -1)
            
            echo "| $id | ${title:-未标题} | ${status:-⚠️ 待处理} | ${location:-未标注} | ${exec_time:-待执行} |" >> "$STATUS_FILE"
        fi
    done
    
    cat >> "$STATUS_FILE" << EOF

---

## 📦 历史提案汇总

| 日期 | 总数 | ✅ 已落地 | ⏸️ 推迟 | ⚠️ 待处理 |
|:---|:---:|:---:|:---:|:---:|
EOF

    # 统计各天数据
    for date_str in 20260421 20260422 20260423; do
        local month="${date_str:4:2}"
        local day="${date_str:6:2}"
        local date_display="$month/$day"
        
        local total=$(ls -1 "$ARCHIVE_DIR"/*${date_str}*.md 2>/dev/null | wc -l | tr -d ' ')
        local impl=$(grep -l "已落地\|✅ 已" "$ARCHIVE_DIR"/*${date_str}*.md 2>/dev/null | wc -l | tr -d ' ')
        local postp=$(grep -l "推迟\|⏸️" "$ARCHIVE_DIR"/*${date_str}*.md 2>/dev/null | wc -l | tr -d ' ')
        local pend=$((total - impl - postp))
        
        [ -z "$total" ] && total=0
        [ -z "$impl" ] && impl=0
        [ -z "$postp" ] && postp=0
        [ -z "$pend" ] && pend=0
        
        echo "| $date_display | $total | $impl | $postp | $pend |" >> "$STATUS_FILE"
    done
    
    cat >> "$STATUS_FILE" << EOF

---

## ✅ 落地执行记录

### 已落地提案

EOF

    # 列出已落地
    for f in "$PROPOSALS_DIR"/dream_proposal_DREAM-PROPOSAL-$(date +%Y%m%d)-*.md; do
        if [ -f "$f" ] && grep -q "✅\|已落地" "$f"; then
            local id=$(basename "$f" | grep -oE '[0-9]+' | tail -1)
            local location=$(grep -E "SKILL|Skill" "$f" 2>/dev/null | head -1 | sed 's/.*`//' | sed 's/`.*//' | cut -c1-50)
            echo "- P$id: 已更新 \`$location\`" >> "$STATUS_FILE"
        fi
    done
    
    cat >> "$STATUS_FILE" << EOF

### 推迟提案

EOF

    # 列出推迟
    for f in "$PROPOSALS_DIR"/dream_proposal_DREAM-PROPOSAL-$(date +%Y%m%d)-*.md; do
        if [ -f "$f" ] && grep -q "⏸️\|推迟" "$f"; then
            local id=$(basename "$f" | grep -oE '[0-9]+' | tail -1)
            local reason=$(grep -E "原因.*A5|A5.*暂停" "$f" 2>/dev/null | head -1 | cut -c1-50)
            echo "- P$id: ⏸️ ${reason:-待A5重启后处理}" >> "$STATUS_FILE"
        fi
    done

    cat >> "$STATUS_FILE" << EOF

---

## 💡 后续建议

1. A5实盘重启后验证P001-P002
2. 历史提案状态标注完善
3. 定期执行提案落地检查

---

*报告自动生成 by auto-repair v2.0*
EOF

    log_success "状态报告已生成: $STATUS_FILE"
}

#==============================================================================
# 主流程
#==============================================================================
main() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔧 Auto-Repair 提案落地检查 v2.0"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    local mode="${1:-all}"
    
    case "$mode" in
        --scan)
            scan_today_proposals
            ;;
        --status)
            check_proposal_status
            ;;
        --archive)
            check_archive
            ;;
        --report)
            generate_status_report
            ;;
        all|*)
            scan_today_proposals
            echo ""
            check_proposal_status
            echo ""
            check_archive
            echo ""
            generate_status_report
            ;;
    esac
    
    echo ""
    log_success "提案检查完成!"
    echo ""
}

# 执行
main "$@"
