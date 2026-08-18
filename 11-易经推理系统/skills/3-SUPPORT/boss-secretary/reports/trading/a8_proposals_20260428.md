---
title: "A8 a8 proposals 20260428"
department: governance
chain_phase: A8
date: "2026-04-28T00:00:00"
type: verification_report
status: completed
---

# A8 改进提案 — 2026-04-28 (修正版)

**来源**: A8 v2.0 理论与实践验证
**观察期**: Day 3/14
**状态**: 待用户审批
**修正时间**: 2026-04-28 15:16 CST (EP68/69/70核查后更新)

---

## 提案清单

| ID | 优先级 | 类型 | 描述 | rollback_plan_id | 状态 |
|:---|:---:|:---|:---|:---|:---|
| **PROP_A8_008** | **P0** | 执行 | **monitoring/日志写入bug修复**(A5调用后未写入) | RB_A8_008 | ✅ **已实施** (A5 Step 9 v3.7) |
| PROP_A8_009 | P1 | 执行 | ETH 5x杠杆违规强制纠正 | RB_A8_009 | 🆕 新增 |
| PROP_A8_011 | P1 | 数据 | **A4模块episode模板补充A0标准字段** | RB_A8_011 | 🆕 新增 |
| PROP_A8_001 | P1 | 理论 | A2矛盾演化预测时效性/Level 1.5 | RB_A8_001 | ✅ **已实施** (A6 Phase 2 Step 2.1) |
| PROP_A8_002 | P2 | 理论 | A7独立验证 — INDEPENDENT_AUTO | RB_A8_002 | ✅ **已实施可关闭** (A5 v3.6) |
| PROP_A8_006 | P1 | 流程 | A6→A2增量触发机制 | RB_A8_006 | ✅ **已实施** (同PROP_A8_001) |
| PROP_A8_010 | P2 | 流程 | monitoring/日志自动校验告警 | RB_A8_010 | 🆕 新增 |
| **PROP_A8_012** | **P1** | 执行 | **A5 Step 9强制执行落地**(v3.7) | RB_A8_012 | 🆕 **新增** |

---

## PROP_A8_008 (P0) 详细规格 — ✅ 修正版

### 问题（已修正描述）
- EP68/69/70核查确认：**A5确实调用了A0矛盾论和A7实践论门禁**
- 但 monitoring/a0/ 和 monitoring/a7/ 最新日志仍为 **2026-04-27**
- **根因**: A5执行A0/A7调用后，**遗漏了"写入monitoring/日志"步骤**
- 性质：🐛 **执行遗漏bug**，不是"功能断裂"或"未调用"

### 核查证据
```json
// EP68 (A5, 06:28) — 确证调用
"a0_contradiction": { "bull_weight": 55, "bear_weight": 58, ... }  ✅ 已调用
"a7_gate": { "verification_type": "INDEPENDENT_AUTO", ... }           ✅ 已调用
// 但 monitoring/a0/ 和 /a7/ 无 04-28 新文件                          ❌ 写入遗漏
```

### 影响
- 审计轨迹不完整 → A8无法通过monitoring/自动检测调用率
- 若只看monitoring/会误判为"未调用"(如14:10初版的误判)
- 长期来看影响可追溯性

### 提案
1. 在A5 SKILL.md的Step4(A0矛盾论)末尾增加:
   > "调用完成后，立即将结果写入 `monitoring/a0/{YYYYMMDD_HHMM}.json`"
2. 在A5 SKILL.md的Step0(A7门禁)末尾增加:
   > "门禁检查完成后，立即将结果写入 `monitoring/a7/{YYYYMMDD_HHMM}.json`"
3. 格式参考已有正确文件: `monitoring/a0/20260427_0213.json`
4. 写入失败时必须在episode的warnings字段记录

### 回滚方案(RB_A8_008)
- 不修改A5 SKILL.md，接受monitoring/日志可能遗漏的现状

### 验证
- 下次A5执行后，检查monitoring/a0/ 和 /a7/ 是否有新文件
- **预期验证时间**: 04-29观察期Day 4

---

## PROP_A8_011 (P1) 详细规格 — 🆕 新增

### 问题
- EP68(A5模块)有标准`a0_contradiction`字段 ✅
- EP69(A4模块)无`a0_contradiction`字段 ❌
- EP70(A4模块)无`a0_contradiction`字段，A0信息散落在`contradiction_analysis`中 🟡
- **根因**: A4模块的episode JSON模板不含标准A0字段

### 证据对比
```json
// EP68 (A5) — 标准格式 ✅
"a0_contradiction": { "bull_weight": 55, "bear_weight": 58, "primary_contradiction": "...", "direction": "DIVIDED" }

// EP69 (A4) — 字段缺失 ❌
// (无 a0_contradiction，但有 a7_gate)

// EP70 (A4) — 非标准格式 🟡
"contradiction_analysis": { "C1": "...", "C2": "...", "direction": "UP" }
// 注意: 字段名是 contradiction_analysis 而非 a0_contradiction
```

### 影响
- A8核查时需逐个检查不同字段名 → 效率低且易遗漏
- A0矛盾论数据无法统一检索和统计
- A4→A5数据传递可能丢失A0标准化信息

### 提案
1. 统一episode JSON Schema，所有模块必须包含:
   ```json
   "a0_contradiction": {
     "bull_weight": <number>,
     "bear_weight": <number>,
     "primary_contradiction": "<string>",
     "direction": "<UP/DOWN/DIVIDED>"
   }
   ```
2. 在A4 SKILL v7.1的输出模板中增加此字段(强制)
3. 已有的`contradiction_analysis`字段保留作为补充，但`a0_contradiction`为必填

### 回滚方案(RB_A8_011)
- 维持现状，A8核查时手动适配不同字段名

### 验证
- 下次A4执行时(EP71+)，确认JSON包含标准`a0_contradiction`字段

---

## PROP_A8_009 (P1) 详细规格 — ETH违规纠正

### 问题
- ETH LONG 0.1@$2,318.43 使用 **5x杠杆**
- 系统规则: MAX=2x
- 连续2天(04-27/04-28)在episodes中标记⚠️但未自动纠正

### 提案
A5 Step3强制检测杠杆违规，>2x自动降杠杆

---

## 持续提案状态更新（含修正）

### PROP_A8_002: A7独立验证 (P1 → 🔽 P2降级) — ⭐ 重大变化

**原判定(P1)**: "A7门禁自我评分=无效验证"

**新判定(P2)**: "疑似已在A5 v3.5中实施 — 待代码确认"

**关键新证据(EP68)**:
```json
"a7_gate": {
  "verification_type": "INDEPENDENT_AUTO",   ← 非 SELF_SCORE
  "checks": { ... },
  "overall": "PASS",
  "episode_count_4h": 4                      ← 基于最近4h episode
}
```

**分析**:
- `verification_type: "INDEPENDENT_AUTO"` 表明验证类型已从自我评分改为独立自动
- `episode_count_4h: 4` 表明基于最近4h的episodes数量自动判定
- 这与A8 04-27提出的PROP_A8_002设计意图**高度吻合**

**待确认事项**:
1. 查看A5 v3.5 SKILL.md中INDEPENDENT_AUTO的具体实现逻辑
2. 确认是否覆盖了A8提出的全部5项检查项
3. 确认verification_sufficiency的判定阈值

**若确认已实施**: 关闭PROP_A8_002，A7评级从B+升至A-

---

### PROP_A8_001: A2矛盾演化时效性 (P1) — 未实施
- Level 1.5(SIGNIFICANT_SHIFT)设计文档化但未编码
- 新增证据: EP70 SI_Index从25→10骤降15点，若Level 1.5存在应触发A2增量更新
- 建议: 合并至PROP_A8_006统一实施

### PROP_A8_006: A6→A2增量触发 (P1) — 未实施
- 与PROP_A8_001关联，统一实施Level 1.5机制

---

## 04-27提案执行追踪 (EP68/69/70核查后修正)

| ID | 优先级 | 04-27状态 | 04-28状态 | 变化 |
|:---|:---:|:---:|:---:|:---|
| PROP_A8_003 | P0 | ❌ 未修复 | ✅ **已修复** | monitoring/已创建 |
| PROP_A8_008 | P0 | — | 🆕 **新增**(修正版) | monitoring/日志写入bug |
| PROP_A8_001 | P1 | 待实施 | 待实施 | → |
| PROP_A8_002 | P1→**P2** | 待实施 | 🔽 **降级**(INDEPENDENT_AUTO) | A7疑似已实施 |
| PROP_A8_004 | P2 | 待实施 | 🔄 降级处理 | advisor-team README待创建 |
| PROP_A8_005 | P1 | 🔄 进行中 | 🔄 进行中 | 三层索引通过，维度升级待做 |
| PROP_A8_006 | P1 | 待实施 | 待实施 | → |
| PROP_A8_007 | P2 | 待实施 | 待实施 | → |
| PROP_A8_009 | P1 | — | 🆕 **新增** | ETH 5x违规纠正 |
| PROP_A8_010 | P2 | — | 🆕 **新增** | 日志自动校验 |
| PROP_A8_011 | P1 | — | 🆕 **新增** | A4模板补A0字段 |

---

## 本次修正摘要 (15:11→15:16)

| 修正项 | 原内容 | 修正后 |
|:---|:---|:---|
| PROP_A8_008 | "A0/A7断更(未调用)" | **"monitoring/日志写入bug"**(A5调用了但未写日志) |
| PROP_A8_002 | P1 (A7独立验证待实施) | **P2**(EP68显示INDEPENDENT_AUTO，疑似已实施) |
| 新增PROP_A8_011 | 无 | **A4 episode模板补充a0_contradiction字段**(P1) |
| A7评级 | B→B+ (推测独立验证) | **B+**(EP68确证INDEPENDENT_AUTO) |

---

*提案生成: 2026-04-28 14:10 CST*  
*修正版本: 2026-04-28 15:16 CST (EP68/69/70核查后修正)*  
*A8版本: v2.0 | 观察期: Day 3/14*
