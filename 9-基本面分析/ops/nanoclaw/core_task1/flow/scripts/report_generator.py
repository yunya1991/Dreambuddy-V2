#!/usr/bin/env python3
"""
综合报告生成模块

功能：
1. 整合新闻信号与资金流信号
2. 生成综合分析报告
3. 输出交易建议与仓位管理指导
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

# 配置
OUTPUT_DIR = Path("/workspace/ops/nanoclaw/core_task1/flow/outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# 报告模板
# =============================================================================

def generate_comprehensive_report(
    news_signal: dict,
    flow_signal: dict,
    fused_signal: dict,
    extra_notes: str = None
) -> str:
    """
    生成综合分析报告

    Args:
        news_signal: 新闻情感信号结果
        flow_signal: 资金流信号结果
        fused_signal: 融合信号结果
        extra_notes: 额外注释

    Returns:
        Markdown 格式报告
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 解读文本
    sentiment_text = interpret_sentiment(news_signal.get("sentiment", 0))
    flow_text = interpret_flow(flow_signal.get("composite", 0))
    fused_text = interpret_fused(fused_signal.get("fused_signal", 0))

    # 仓位建议
    position_advice = generate_position_advice(fused_signal)

    # 风险警示
    risk_warnings = generate_risk_warnings(news_signal, flow_signal, fused_signal)

    report = f"""# 加密市场综合分析报告

**生成时间**: {ts}
**报告类型**: 新闻 + 资金流融合分析

---

## 📊 信号总览

| 信号类型 | 数值 | 解读 |
|----------|------|------|
| **新闻情感** | {news_signal.get('sentiment', 0):+.4f} | {sentiment_text} |
| **资金流** | {flow_signal.get('composite', 0):+.4f} | {flow_text} |
| **融合信号** | {fused_signal.get('fused_signal', 0):+.4f} | {fused_text} |

---

## 📰 新闻信号详情

**事件数量**: {news_signal.get('event_count', 0)}
**加权总和**: {news_signal.get('weighted_sum', 0):.4f}

### 事件分布
| 类型 | 数量 |
|------|------|
| 正面事件 | {news_signal.get('breakdown', {}).get('positive_events', 0)} |
| 负面事件 | {news_signal.get('breakdown', {}).get('negative_events', 0)} |
| 中性事件 | {news_signal.get('breakdown', {}).get('neutral_events', 0)} |

### 按类型统计
"""

    # 添加类型统计
    by_type = news_signal.get('breakdown', {}).get('by_type', {})
    if by_type:
        for event_type, stats in list(by_type.items())[:5]:
            avg_sentiment = stats['sentiment_sum'] / stats['count'] if stats['count'] > 0 else 0
            report += f"| {event_type} | {stats['count']} | {avg_sentiment:+.2f} |\n"
    else:
        report += "| 无数据 | - | - |\n"

    report += f"""
---

## 💰 资金流信号详情

### 各层信号
| 层级 | 得分 | 解读 |
|------|------|------|
| 外生资金层 | {flow_signal.get('layer_signals', {}).get('exogenous', 0):+.4f} | {'资金流入' if flow_signal.get('layer_signals', {}).get('exogenous', 0) > 0 else '资金流出'} |
| 内生杠杆层 | {flow_signal.get('layer_signals', {}).get('leverage', 0):+.4f} | {'杠杆偏高' if flow_signal.get('layer_signals', {}).get('leverage', 0) > 0 else '杠杆偏低'} |
| 链上行为层 | {flow_signal.get('layer_signals', {}).get('onchain', 0):+.4f} | {'链上活跃' if flow_signal.get('layer_signals', {}).get('onchain', 0) > 0 else '链上低迷'} |

**置信度**: {flow_signal.get('confidence', 0):.2f}

---

## 🎯 融合信号分析

### 权重配置
| 信号源 | 权重 | 说明 |
|--------|------|------|
| 新闻 | {fused_signal.get('news_weight', 0):.2f} | {'新闻主导' if fused_signal.get('news_weight', 0) > 0.5 else '均衡' if fused_signal.get('news_weight', 0) > 0.4 else '资金流主导'} |
| 资金流 | {fused_signal.get('flow_weight', 0):.2f} | {'更可靠' if fused_signal.get('flow_weight', 0) > 0.5 else '参考'} |

### 状态检测
- **市场状态**: {fused_signal.get('market_state', 'unknown')}
- **信号冲突**: {'⚠️ 是' if fused_signal.get('conflict_flag') else '✅ 否'}

{risk_warnings}
---

## 💡 操作建议

### 仓位建议
{position_advice}

### 风险提示
"""

    # 添加风险等级
    risk_level = fused_signal.get('fused_signal', 0)
    if risk_level > 0.5:
        report += "- ✅ 低风险：信号一致向好，可积极配置"
    elif risk_level > 0:
        report += "- ⚠️ 中低风险：谨慎看多，控制仓位"
    elif risk_level > -0.5:
        report += "- ⚠️ 中高风险：防守为主，等待右侧"
    else:
        report += "- 🚨 高风险：信号一致看空，建议离场"

    if extra_notes:
        report += f"\n\n---\n\n## 📝 额外说明\n\n{extra_notes}\n"

    report += """
---

*本报告由 crypto-flow-analysis + crypto-news-digest 联合生成 | 仅供研究参考*
*风险提示：加密货币市场波动剧烈，请谨慎决策*
"""

    return report

def interpret_sentiment(sentiment: float) -> str:
    """解读新闻情感信号"""
    if sentiment > 0.5:
        return "强烈正面"
    elif sentiment > 0.2:
        return "正面"
    elif sentiment > -0.2:
        return "中性"
    elif sentiment > -0.5:
        return "负面"
    else:
        return "强烈负面"

def interpret_flow(composite: float) -> str:
    """解读资金流信号"""
    if composite > 0.6:
        return "资金流一致看多"
    elif composite > 0.2:
        return "资金流偏向看多"
    elif composite > -0.2:
        return "资金流中性"
    elif composite > -0.6:
        return "资金流偏向看空"
    else:
        return "资金流一致看空"

def interpret_fused(fused: float) -> str:
    """解读融合信号"""
    if fused > 0.5:
        return "强烈买入信号"
    elif fused > 0.2:
        return "买入信号"
    elif fused > -0.2:
        return "持有观望"
    elif fused > -0.5:
        return "卖出信号"
    else:
        return "强烈卖出信号"

def generate_position_advice(fused_signal: dict) -> str:
    """生成仓位建议"""
    fused = fused_signal.get('fused_signal', 0)
    confidence = fused_signal.get('confidence', 0.5)
    conflict = fused_signal.get('conflict_flag', False)

    if conflict:
        return "**建议**: 降低仓位，等待信号一致\n**仓位**: 30-40%"

    if fused > 0.5:
        if confidence > 0.7:
            return "**建议**: 积极配置\n**仓位**: 70-80%"
        else:
            return "**建议**: 逢低布局\n**仓位**: 60-70%"
    elif fused > 0.2:
        return "**建议**: 谨慎看多\n**仓位**: 55-65%"
    elif fused > -0.2:
        return "**建议**: 持有观望\n**仓位**: 50%"
    elif fused > -0.5:
        return "**建议**: 逢高减仓\n**仓位**: 35-45%"
    else:
        return "**建议**: 防守为主\n**仓位**: 10-20%"

def generate_risk_warnings(news_signal: dict, flow_signal: dict, fused_signal: dict) -> str:
    """生成风险警示"""
    warnings = []

    # 检查信号冲突
    if fused_signal.get('conflict_flag'):
        warnings.append("⚠️ **信号冲突警告**: 新闻与资金流方向不一致，建议降低风险敞口")

    # 检查极端新闻情感
    news_sentiment = news_signal.get('sentiment', 0)
    if abs(news_sentiment) > 0.7:
        warnings.append(f"⚠️ **极端新闻情感**: {news_sentiment:+.2f}，可能存在情绪化波动")

    # 检查极端资金流
    flow_composite = flow_signal.get('composite', 0)
    if abs(flow_composite) > 0.7:
        warnings.append(f"⚠️ **极端资金流**: {flow_composite:+.2f}，可能存在大幅波动")

    # 检查置信度
    confidence = flow_signal.get('confidence', 0.5)
    if confidence < 0.4:
        warnings.append(f"⚠️ **低置信度**: {confidence:.2f}，信号可靠性较低")

    if warnings:
        return "\n".join(warnings)
    else:
        return "✅ 无重大风险信号"

# =============================================================================
# 保存报告
# =============================================================================

def save_comprehensive_report(result: dict, extra_notes: str = None) -> str:
    """
    保存综合报告到文件

    Args:
        result: 信号融合结果字典
        extra_notes: 额外注释

    Returns:
        报告文件路径
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"comprehensive_report_{ts}.md"
    filepath = OUTPUT_DIR / filename

    report = generate_comprehensive_report(
        news_signal=result.get('news_signal', {}),
        flow_signal=result.get('flow_signal', {}),
        fused_signal=result.get('fused_signal', {}),
        extra_notes=extra_notes
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"[REPORT] Saved comprehensive report: {filepath}")
    return str(filepath)

# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == "__main__":
    import sys

    # 加载最新的融合结果
    fusion_files = sorted(OUTPUT_DIR.glob("signal_fusion_*.json"))

    if not fusion_files:
        print("[ERROR] No signal fusion result found. Run signal_fusion.py first.")
        sys.exit(1)

    latest_fusion = fusion_files[-1]

    with open(latest_fusion, "r", encoding="utf-8") as f:
        result = json.load(f)

    # 生成报告
    report_path = save_comprehensive_report(result)
    print(f"\n[INFO] Report generated: {report_path}")
