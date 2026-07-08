---
title: "📋 提案汇总报告"
department: governance
type: proposal
date: "2026-04-22T20:48:00"
status: completed
---

# 📋 提案汇总报告

**生成时间**: 2026-04-22 20:48 CST  
**提案总数**: 4个  
**来源**: dream_insight_summary_20260422.md + dream_advisor_consultation_20260422.md

---

## 提案清单

| 提案ID | 标题 | 类型 | 优先级 | require_shadow |
|:-------|:-----|:-----|:-------|:---------------|
| PROPOSAL-20260422-01 | EP46执行报告强制补齐机制 | policy_patch | 🔴 P0 | false |
| PROPOSAL-20260422-02 | 提案快速通道(≤4h落地) | policy_patch | 🔴 P0 | true |
| PROPOSAL-20260422-03 | 入场时机质量评分 | scoring_spec_update | 🟠 P1 | true |
| PROPOSAL-20260422-04 | 价格-情绪背离识别 | scoring_spec_update | 🟠 P1 | true |

---

## 提案详情

### 1. PROPOSAL-20260422-01: EP46执行报告强制补齐机制
- **问题**: A5执行后无报告，Episode固化断链
- **变更**: A5执行=下单+报告，无报告=未执行
- **目标文件**: dream-tactical-executor/SKILL.md

### 2. PROPOSAL-20260422-02: 提案快速通道
- **问题**: 10项提案堆积，最长等待72h
- **变更**: P4→10min / P3→30min / P2→2h / P1→4h
- **目标文件**: boss-secretary/SKILL.md

### 3. PROPOSAL-20260422-03: 入场时机质量评分
- **问题**: 只评方向不评时机，EP46损失27倍收益
- **变更**: 新增timing_score (0-100)，综合评分×0.3权重
- **目标文件**: dream-signal-scoring-spec/SKILL.md

### 4. PROPOSAL-20260422-04: 价格-情绪背离识别
- **问题**: FGI背离信号缺失，机构吸筹无法识别
- **变更**: 新增背离检测规则，正背离→警告，极度背离→阻断
- **目标文件**: dream-intelligence-monitor/SKILL.md

---

## 下一步操作

### 方案A: 批量影子验证
调用 `hermes-shadow-verification-gate` 对4个提案执行影子验证

### 方案B: 逐个处理
指定某个提案单独执行验证+落地

### 方案C: 手工审批
直接查看提案内容，手工确认后执行

---

## 提案文件位置
```
~/.workbuddy/skills/boss-secretary/mailbox/proposals/
├── PROPOSAL-20260422-01_ep46_execution_report.md
├── PROPOSAL-20260422-02_proposal_fast_track.md
├── PROPOSAL-20260422-03_timing_quality_score.md
└── PROPOSAL-20260422-04_fgi_divergence.md
```

---

*提案汇总生成: learning-proposal-generator | 2026-04-22 20:48 CST*

---

## 落地状态 (2026-04-29)

**状态**: ✅ 归档处理

**处理方式**: 顾问已内嵌SKILL直接调用 (2026-04-26)，无需独立会诊流程。顾问结论已体现在A系列报告中。

**归档位置**: ~/.workbuddy/skills/boss-secretary/reports/
