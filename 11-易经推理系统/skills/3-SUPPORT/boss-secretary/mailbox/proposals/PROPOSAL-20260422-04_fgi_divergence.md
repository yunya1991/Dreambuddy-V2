---
title: "Proposal: 价格-情绪背离识别"
department: governance
type: proposal
date: "2026-04-22T20:48:00"
status: completed
tags: ["urgent"]
proposal_id: "PROPOSAL-20260422-04"
priority: "🟠 P1"
proposal_type: "scoring_spec_update"
---

# Proposal: 价格-情绪背离识别

**提案ID**: PROPOSAL-20260422-04  
**生成时间**: 2026-04-22 20:48 CST  
**提案类型**: scoring_spec_update  
**触发来源**: dream_insight_summary_20260422.md (议题3)  
**优先级**: 🟠 P1  
**require_shadow_verification**: true

---

## 提案摘要

FGI背离信号: 价格从$74,766涨到$78,420(+4.8%)，但FGI从33→32几乎不变。系统缺失"价格-情绪背离"识别维度。

---

## 根因分析

1. **维度缺失**: FGI与价格联动是假设，但未考虑背离情况
2. **信号误用**: FGI是散户情绪指标，用于指导"聪明钱决策"
3. **解读盲区**: 没有机制识别"机构沉默吸筹"场景

---

## 变更内容

### 目标文件
`~/.workbuddy/skills/dream-intelligence-monitor/SKILL.md`

### 变更类型
scoring_spec_update

### 变更内容
在dream-intelligence-monitor中新增"价格-情绪背离"检测规则：

```markdown
## 新增: 价格-情绪背离检测 (v2.3 新增)

### 背离定义
| 类型 | 条件 | 信号 |
|:-----|:-----|:-----|
| 正背离 | 价格涨+FGI不涨 | 机构吸筹预警 🟡 |
| 负背离 | 价格跌+FGI不跌 | 机构出货预警 🟠 |
| 极度背离 | 价格涨+FGI下降 | 即将回调预警 🔴 |

### 检测阈值
```
背离强度 = |price_change_pct - fgi_change| / fgi_change

- 强度 < 0.5: 无背离
- 强度 0.5-1.0: 轻度背离
- 强度 1.0-2.0: 中度背离 → 警告
- 强度 > 2.0: 极度背离 → 阻断
```

### 信号触发规则
```python
# 正背离场景 (机构吸筹)
if price_24h_change > 0.05 and fgi_change < 0.1:
    alert("POSITIVE_DIVERGENCE", level="WARNING")
    # 建议: 谨慎追多，等待回踩

# 极度背离场景 (即将回调)
if price_24h_change > 0.08 and fgi_change < 0:
    alert("EXTREME_DIVERGENCE", level="CRITICAL")
    # 建议: 平多/开空，止损设在近期高点
```

### 整合到信号评分
- 背离信号作为"情绪维度"的修正因子
- 正背离时降低追多信号权重
- 极度背离时触发交易阻断
```

---

## 证据引用

- `dream_insight_summary_20260422.md`: FGI背离暗示机构吸筹
- `dream_advisor_consultation_20260422.md`: 议题3 FGI背离方案
- 实时数据: 04-22 01:31 FGI33→17:00 FGI32，价格+4.8%

---

## Rollback Plan

**rollback_plan_id**: ROLLBACK-PROPOSAL-20260422-04

**rollback_steps**:
1. 删除dream-intelligence-monitor/SKILL.md中新增的"价格-情绪背离检测"章节
2. 恢复原监控规则

**rollback验证**: 确认监控恢复到v2.2状态

---

## reason_codes

- `R010`: FGI背离信号缺失
- `R011`: 机构吸筹识别盲区
- `R012`: 维度定义不完整

---

## 状态

| 阶段 | 状态 | 时间 |
|:-----|:-----|:-----|
| 生成 | ✅ | 2026-04-22 20:48 |
| 影子验证 | ⚠️ PASS (带条件) | 2026-04-22 20:51 |
| 审批 | ✅ 自动通过 | 2026-04-22 20:58 |
| 回测 | ✅ 通过(带条件) | 2026-04-22 20:58 |
| 落地 | ✅ 已落地 | 2026-04-22 20:58 |

---

## 验证结论

**decision**: ✅ PASS (回测通过，监控假阳性率)

**理由**: 背离检测逻辑有效，阈值校准完成

**metrics_delta**:
- alert_count: +20~50% ✅
- pnl: +2~5% 📊 待实盘验证
- signal_accuracy: +5~10% 📊 待实盘验证

**回测报告**: `BACKTEST-REPORT-20260422.md`

**落地参数**:
```yaml
divergence_threshold_mild: 0.5
divergence_threshold_moderate: 1.0
divergence_threshold_extreme: 2.0
false_positive_alert: 0.40
```

---

*提案生成: learning-proposal-generator | 2026-04-22 20:48 CST*
*影子验证: hermes-shadow-verification-gate | 2026-04-22 20:51 CST*
*回测: market-practice-simulator | 2026-04-22 20:58 CST*
*落地: 2026-04-22 20:58 CST*
