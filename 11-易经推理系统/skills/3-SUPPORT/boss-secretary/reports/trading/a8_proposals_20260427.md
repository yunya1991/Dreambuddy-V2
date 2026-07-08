---
title: "A8 a8 proposals 20260427"
department: governance
chain_phase: A8
date: "2026-04-28T00:00:00"
type: verification_report
status: completed
---

# A8 改进提案 — 2026-04-27

**来源**: A8 v2.0 理论与实践验证
**观察期**: Day 2/14

---

## 提案清单

| ID | 优先级 | 类型 | 描述 | rollback_plan_id |
|:---|:---:|:---|:---|:---|
| PROP_A8_001 | P1 | 理论 | A2矛盾演化预测时效性 | RB_A8_001 |
| PROP_A8_002 | P1 | 理论 | A7门禁独立验证机制 | RB_A8_002 |
| PROP_A8_003 | **P0** | 执行 | monitoring/目录强制创建 | RB_A8_003 |
| PROP_A8_004 | P2 | 执行 | advisor-team工作空间空目录清理+README | RB_A8_004 |
| PROP_A8_005 | P1 | 执行 | 三叉戟增加地缘风险维度(8→9维) | RB_A8_005 |
| PROP_A8_006 | **P1** | 流程 | A6→A2增量触发机制 | RB_A8_006 |
| PROP_A8_007 | P2 | 流程 | PTSD检测自动化 | RB_A8_007 |

---

## PROP_A8_003 (P0) 详细规格

### 问题
- MEMORY.md声称"调度日志monitoring/a0,a7"
- monitoring/目录不存在
- A0/A7调用无持久化审计轨迹

### 提案
1. 创建 `monitoring/a0/` 和 `monitoring/a7/` 目录
2. A5每次调用A0后，写入 `monitoring/a0/{YYYYMMDD_HHMM}.json`
3. A5每次调用A7后，写入 `monitoring/a7/{YYYYMMDD_HHMM}.json`
4. 日志格式:
```json
{
  "timestamp": "ISO8601",
  "agent": "A5",
  "gate": "A0|A7",
  "result": "PASS|FAIL|CONDITIONAL_PASS",
  "details": { ... },
  "evidence_refs": ["episodes/xxx.json"]
}
```

### 回滚方案(RB_A8_003)
- 删除monitoring/目录
- 从A5 SKILL.md中移除日志写入指令

### 验证
- A5下次执行后，检查monitoring/下是否有新文件

---

## PROP_A8_005 (P1) 详细规格

### 问题
- L_TRIDENT_VS_A0: 三叉戟BUY触发但A0矛盾分析HOLD时，靠人工裁定
- L_DISTILL_002: 地缘风险需作为三叉戟独立维度
- PROP_DISTILL_002(蒸馏部)已提议但未实施

### 提案
三叉戟评分从7维→9维:
```
原7维: FGI(15) + 费率(5) + ETF(10) + 价格变化(5) + 区间位置(5) + 地缘(-10) + 动量(0)
→ 新9维: FGI(15) + 费率(5) + ETF(10) + 价格变化(5) + 区间位置(5) + 地缘风险(10) + 动量(5) + 宏观共振(5) + OI变化(5)
```

新增维度:
- **地缘风险**(10分): geopolitical_risk=HIGH→0分, MEDIUM→5分, LOW→10分
- **宏观共振**(5分): 5资产同涨/跌→5分, 3/5→3分, 分散→0分
- **OI变化**(5分): OI增加+价格涨→5分, OI减少+价格涨→0分(假突破风险)

### 回滚方案(RB_A8_005)
- 恢复7维评分
- 保留L_TRIDENT_VS_A0人工裁定规则

### 关联
- PROP_DISTILL_002 (蒸馏部)
- L_DISTILL_002 (Lesson)
- L_TRIDENT_VS_A0 (Lesson, 已升级)

---

## PROP_A8_004 (P2→降级) 详细规格

### 问题(修正)
- **原判定**: "advisor-team空置=退化" → **误判**
- **实际**: 04-26架构升级，顾问从"异步邮箱"升级为"内联同步调用"
- **全局路径**: `~/.workbuddy/advisor-team/` 含13顾问+`advisor_direct_call.py`，正常运作
- **workspace路径**: `advisor-team/` 为空目录(无实际用途)

### 提案(降级为P2)
1. 在workspace的`advisor-team/`下创建`README.md`，说明架构升级：
   ```markdown
   # advisor-team (已迁移)
   顾问系统已升级为内联同步调用模式(2026-04-26)。
   活跃顾问目录: ~/.workbuddy/advisor-team/
   调用方式: advisor_direct_call.py (内联调用)
   详见: 宪法§12 + 各SKILL.md的advisor集成部分
   ```
2. 确认A3 `strategy_directive.json`中`advisor_review.status=PENDING`是否需要回填机制

### 回滚方案(RB_A8_004)
- 删除README.md，恢复空目录状态

---

## PROP_A8_006 (P2→P1升级) 详细规格

### 问题
- A6检测到P1级市场变化(如$78,500突破、1H趋势转空)但未触发A1/A2更新
- A2凌晨01:30报告到14:00已过时(bear主导60% vs 实际多方55%)
- 当前只有"全链重启(REVERSAL)"和"不触发"两种状态，缺少中间路径

### 提案: A6→A2增量触发机制
1. **新增Level 1.5 (SIGNIFICANT_SHIFT)**: A6检测到以下任一条件时触发A2增量更新
   - Edge从≥+20变为≤-10(或反向) — 信号方向剧变
   - SI_Index从≥+30变为≤+10(或反向) — 信号强度骤降
   - 1H趋势方向与日线趋势方向背离 — 时间框架冲突
   - 费率从负转正(或反向) — L_FUNDING_FLIP触发

2. **增量更新内容**:
   - 仅更新A2矛盾图谱(不重启A1调研)
   - 更新方向: 记录旧判定→新判定→变化原因
   - 输出: `reports/trading/a2_contradiction_incremental_{HHMM}.json`

3. **不触发条件**(防止过度触发):
   - 距上次A2更新<2小时
   - Edge变化幅度<15
   - 非交易时段(00:00-01:00)

### 回滚方案(RB_A8_006)
- 移除Level 1.5，恢复5级响应体系
- A2仅在凌晨定时运行或REVERSAL级全链重启时更新

### 验证
- 下次A6检测到Edge剧变时，检查是否生成a2_incremental文件
- 对比A2更新后的预测准确率是否提升(目标: >60%)

---

*提案生成: 2026-04-27 14:11 CST*
*更新: 2026-04-27 14:40 CST (修正advisor判定+升级PROP_A8_006)*
*状态: 待用户审批*
