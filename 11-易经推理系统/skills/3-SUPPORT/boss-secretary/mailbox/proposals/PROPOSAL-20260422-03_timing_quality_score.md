---
title: "Proposal: 入场时机质量评分"
department: governance
type: proposal
date: "2026-04-22T20:48:00"
status: completed
tags: ["urgent"]
proposal_id: "PROPOSAL-20260422-03"
priority: "🟠 P1"
proposal_type: "scoring_spec_update"
---

# Proposal: 入场时机质量评分

**提案ID**: PROPOSAL-20260422-03  
**生成时间**: 2026-04-22 20:48 CST  
**提案类型**: scoring_spec_update  
**触发来源**: dream_insight_summary_20260422.md (议题4)  
**优先级**: 🟠 P1  
**require_shadow_verification**: true

---

## 提案摘要

EP46方向100%正确，但时机D级（入场在反弹80-90%位置）。最佳窗口比EP46多赚$2,915（27倍）。当前系统只评方向，不评入场位置优劣。

---

## 根因分析

1. **评分缺失**: 只有方向评分(0-100)，无时机评分
2. **决策偏差**: FOMO驱动，忽视A5的WAIT指令
3. **反馈缺失**: 没有机制惩罚"方向对+时机错"

---

## 变更内容

### 目标文件
`~/.workbuddy/skills/dream-signal-scoring-spec/SKILL.md`

### 变更类型
scoring_spec_update

### 变更内容
在dream-signal-scoring-spec中新增"时机评分"维度：

```markdown
## 新增维度: 入场时机质量评分 (Timing Quality Score)

### 评分因素
| 因素 | 权重 | 说明 |
|:-----|:----:|:-----|
| 相对位置 | 40% | 距离最近支撑/压力的百分比 |
| 确认度 | 30% | 是否等待回踩确认 |
| 波动率匹配 | 20% | 入场时机与ATR的关系 |
| 计划服从度 | 10% | 是否遵守A5建议的入场价 |

### 时机评分计算
```
timing_score = 
  relative_position * 0.4 +
  confirmation * 0.3 +
  volatility_match * 0.2 +
  plan_compliance * 0.1

时机等级:
- A (90-100): 回踩确认入场，波动率匹配，计划服从
- B (70-89): 部分确认入场，轻微偏离
- C (50-69): 追涨/追跌入场，明显偏离
- D (0-49): FOMO入场，严重偏离计划
```

### 综合评分调整
```
final_score = direction_score * 0.7 + timing_score * 0.3

EP46案例:
- direction_score: 85 (方向正确)
- timing_score: 30 (D级时机)
- final_score: 68.5 (综合C+)
```

### 与三叉戟整合
- 入场时机纳入"战术评分"分支
- 时机D级时触发额外风险提示
- 时机D级时降低目标仓位上限
```

---

## 证据引用

- `dream_insight_summary_20260422.md`: EP46方向正确+时机错误
- `dream_advisor_consultation_20260422.md`: 议题4 时机量化方案
- EP46数据: 最佳窗口$75,498 vs 实际入场$78,075

---

## Rollback Plan

**rollback_plan_id**: ROLLBACK-PROPOSAL-20260422-03

**rollback_steps**:
1. 删除dream-signal-scoring-spec/SKILL.md中新增的"入场时机质量评分"章节
2. 恢复原评分公式

**rollback验证**: 确认评分恢复到v2.3状态

---

## reason_codes

- `R007`: 时机评分缺失
- `R008`: FOMO驱动惩罚缺失
- `R009`: 收益差距27倍

---

## 状态

| 阶段 | 状态 | 时间 |
|:-----|:-----|:-----|
| 生成 | ✅ | 2026-04-22 20:48 |
| 影子验证 | ⚠️ PASS (带条件) | 2026-04-22 20:51 |
| 审批 | ✅ 自动通过 | 2026-04-22 20:58 |
| 回测 | ✅ 通过 | 2026-04-22 20:58 |
| 落地 | ✅ 已落地 | 2026-04-22 20:58 |

---

## 验证结论

**decision**: ✅ PASS (回测通过)

**理由**: 时机评分能有效过滤D级入场时机，建议权重0.2

**metrics_delta**:
- trade_count: -10~20% ✅
- skip_rate: +5~15% ✅
- pnl: +3~8% 📊 待实盘验证
- max_drawdown: -2~5% 📊 待实盘验证

**回测报告**: `BACKTEST-REPORT-20260422.md`

**落地参数**:
```yaml
timing_score_weight: 0.2  # 从0.1提升
skip_rate_threshold: 0.30
timing_level_D_filter: true
```

---

*提案生成: learning-proposal-generator | 2026-04-22 20:48 CST*
*影子验证: hermes-shadow-verification-gate | 2026-04-22 20:51 CST*
*回测: market-practice-simulator | 2026-04-22 20:58 CST*
*落地: 2026-04-22 20:58 CST*
