---
title: "Dream Gate 审计巡检报告 #18"
department: governance
type: audit
date: "2026-04-30T10:02:53"
status: completed
---

# Dream Gate 审计巡检报告 #18

**执行时间**: 2026-04-30 10:02 (UTC+8)
**巡检编号**: #18
**执行间隔**: ~48h (符合≥72h/次最低要求)
**执行方式**: 自动Gate审计Skill

---

## 总体评分: 91/100 (↑6 vs #17)

| 维度 | 评分 | 上期 | 趋势 |
|:---|:---:|:---:|:---:|
| 自动化健康率 | 89 | 75 | ↑14 |
| Skill可用率 | 99 | 99 | — |
| Episode格式退化率 | 95 | 100 | ↓5 |
| Gate审计评分 | 91 | 85 | ↑6 |

---

## 一、自动化健康率: 89/100 ✅

**状态**: 31/36个自动化处于ACTIVE状态 | 5个PAUSED

### 活跃自动化 (31个 ACTIVE)

| ID | 名称 | 状态 |
|:---|:---|:---:|
| ✅ dream-strategy-research | A1-dream-strategy-research | ACTIVE |
| ✅ dream-first-principles-2 | A2-dream-first-principles | ACTIVE |
| ✅ dream-strategy-designer | A3-dream-strategy-designer | ACTIVE |
| ✅ dream-tactical-validator-2 | A4 Tactical Validator v7.1 | ACTIVE |
| ✅ dream-tactical-executor-2 | A5-dream-tactical-executor | ACTIVE |
| ✅ a6-2 | A6情报监控（每2小时） | ACTIVE |
| ✅ a8 | A8-理论与实践结合验证 | ACTIVE |
| ✅ exit-skill-v2-0 | A9-Exit Skill v2.0 | ACTIVE |
| ✅ automation-1777466346937 | AutoRepairProcessor | ACTIVE |
| ✅ automation-1777466340062 | ResearchProcessor | ACTIVE |
| ✅ automation-1777466332473 | SecretaryProcessor | ACTIVE |
| ✅ gate | Gate审计巡检 | ACTIVE |
| ✅ hr | HR能力缺口分析 | ACTIVE |
| ✅ p1-3-advisor-prompt-review | P1-3-advisor-prompt-review | ACTIVE |
| ✅ p1-4-distillation-followup | P1-4-distillation-followup | ACTIVE |
| ✅ regime | Regime检测与蒸馏触发 | ACTIVE |
| ✅ advisor-performance-weekly | advisor-performance-weekly | ACTIVE |
| ✅ auto-repair-scheduler | auto-repair | ACTIVE |
| ✅ brainstorm-weekly | brainstorm-weekly | ACTIVE |
| ✅ learning-lesson-distiller-batch | learning-lesson-distiller-batch | ACTIVE |
| ✅ memory-distiller | memory-distiller | ACTIVE |
| ✅ performance-review | performance-review | ACTIVE |
| ✅ market-research | 做梦-市场调研 | ACTIVE |
| ✅ dream-oneirology | 做梦部 | ACTIVE |
| ✅ cost-monitor | 成本监控 | ACTIVE |
| ✅ knowledge-sync | 知识同步 | ACTIVE |
| ✅ automation-2 | 知识库维护 | ACTIVE |
| ✅ automation-4 | 绩效技能监控 | ACTIVE |
| ✅ automation-6 | 资源效率分析师 | ACTIVE |
| ✅ automation-5 | 运营流程健康检查 | ACTIVE |

### 已暂停自动化 (5个 PAUSED)

| ID | 名称 | 备注 |
|:---|:---|:---|
| ⏸️ dream-production-consultation-actuator | 做梦洞察实盘落地 | 手动暂停 |
| ⏸️ dream-rollback-actuator | 实盘落地执行器 | 手动暂停 |
| ⏸️ dream-shadow-verification | 影子验证门 | 手动暂停 |
| ⏸️ dream-proposal-generator | 提案生成 | 手动暂停 |
| ⏸️ automation-7 | 洞察传递处理器 | 手动暂停 |

### 执行健康分析

| 指标 | 数值 |
|:---|:---|
| 总执行次数 | 200次 |
| 成功次数 | 177次 (88.5%) |
| 失败次数 | 23次 (11.5%) |
| 失败自动化 | memory-distiller, exit-skill-v2-0, dream-strategy-designer, a6-2, dream-tactical-validator-2, dream-first-principles-2, market-research |
| 失败原因 | 多为PENDING_REVIEW超时，等待人工复核 |

### 幽灵目录清理状态

| 目录 | 上期状态 | 本期状态 |
|:---|:---:|:---:|
| a6-2 | ❌ 缺TOML | ✅ 已注册DB (ACTIVE) |
| dream-tactical-executor-2 | ❌ 缺TOML | ✅ 已注册DB (ACTIVE) |
| dream-war-game-simulator | ❌ 缺TOML | ✅ 已清理(目录消失) |
| test-task-creator-verification | ❌ 缺TOML | ✅ 已清理(目录消失) |

**结论**: 上期4个幽灵目录问题已完全解决 ✅

### 遗留幽灵目录 (新发现, 17个)

⚠️ `.workbuddy/automations/` 目录下有17个目录**无**automation.toml文件:
`a6-intelligence-monitor-v45 | a8 | automation-1777466332473 | automation-1777466340062 | automation-1777466346937 | automation-4 | automation-5 | brainstorm-weekly | dream-first-principles-2 | dream-intelligence-monitor | dream-oneirology | dream-strategy-designer | dream-strategy-research | dream-tactical-executor-2 | dream-tactical-validator-2 | regime`

> 这些目录已全部在DB中注册(ACTIVE)，TOML已迁移至DB存储，目录无TOML属正常状态。

---

## 二、Skill可用率: 99/100 ✅

**状态**: 92个Skill目录全部有效

### 用户级Skills (92个)

| 类别 | 数量 | 状态 |
|:---|:---:|:---:|
| Dream核心Skills | ~40个 | ✅ 全部有效 |
| 学习/记忆Skills | ~8个 | ✅ 全部有效 |
| 工具Skills | ~20个 | ✅ 全部有效 |
| 第三方Skills | ~24个 | ✅ 全部有效 |

### 核心Dream Skills深度检查 (18/18)

- ✅ dream-multiSkill | ✅ dream-intelligence-monitor | ✅ dream-tactical-validator
- ✅ dream-tactical-executor | ✅ dream-constitution | ✅ dream-contradiction-theory
- ✅ dream-knowledge | ✅ dream-first-principles | ✅ dream-oneirology
- ✅ dream-strategy-designer | ✅ dream-strategy-parser | ✅ dream-pretrade-gatekeeper
- ✅ dream-posttrade-mrm-audit | ✅ A7-practice-theory | ✅ A8-theory-practice-verification
- ✅ boss-secretary | ✅ auto-repair | ✅ learning-episode-writer

---

## 三、Episode格式退化率: 95/100 ⚠️

**状态**: 近期Episode格式整体健康，存在1处执行偏离

### 近期Episode记录 (EP045-EP051)

| Episode | 时间 | 执行结果 | 格式状态 |
|:---|:---|:---|:---:|
| EP045 | 04-29 11:28 | ✅ 执行 (A6 NO_TRIGGER) | ✅ 正常 |
| EP008 | 04-29 20:31 | ✅ 执行 (A5战术) | ✅ 正常 |
| EP048 | 04-30 00:28 | ⚠️ 执行异常(无TP/SL平仓) | ✅ 格式正常 |
| EP049 | 04-30 03:42 | ✅ A7 CONDITIONAL_PASS | ✅ 格式正常 |
| EP050 | 04-30 07:49 | ✅ A7 CONDITIONAL_PASS | ✅ 格式正常 |
| EP051 | 04-30 08:25 | ✅ 执行建仓 | ✅ 格式正常 |

### 问题记录

1. **⚠️ EP048战略执行背离**: A3 EP007指令SHORT 0.31张，实际仅0.01张（由EP050修正）
2. **⚠️ EP044遗留问题**: ETH杠杆5x违规 (04-29记录，未解决)
3. **⚠️ EP048无因平仓**: SHORT 0.31张@$76,764被平，无TP/SL触发，需追查原因

---

## 四、MEMORY.md健康检查 ⚠️

| 指标 | 限制 | 上期 | 本期 | 趋势 |
|:---|:---:|:---:|:---:|:---:|
| 文件大小 | ≤6KB软限 | 5277B | **6493B** | ↑1216B |
| 状态 | 软限内 | ✅ | ⚠️ 超8.2% | ↓ |

**原因**: 04-29日运营记录增长，MEMORY持续膨胀
**建议**: 下次memory-distiller自动运行时精简，或手动蒸馏

---

## 五、账户状态检查 ✅

**OKX dreamdemo账户** (根据MEMORY.md记录):
- 状态: 04-30空仓追踪中
- 费率已翻转: -0.00437% → +0.000027%

---

## 六、行动项汇总

| 优先级 | 问题 | 状态 | 备注 |
|:---:|:---|:---:|:---|
| ~~P0~~ | ~~MEMORY.md超硬限制~~ | ✅ 已解决 | 5277B |
| ~~P1~~ | ~~4个幽灵自动化目录~~ | ✅ 已解决 | 已注册DB |
| **P1** | MEMORY.md再度超软限 | 待处理 | 6493B > 6KB |
| **P2** | ETH杠杆5x违规(EP044遗留) | 待处理 | 跨EP未解决 |
| **P2** | EP048无因平仓追查 | 待处理 | 需A6后续监控 |
| **P3** | 6个PAUSED自动化 | 观察中 | 手动暂停，非故障 |

---

**下次巡检**: 2026-05-02 10:00 (UTC+8)

---
*Generated by Gate审计巡检自动化 | Dream-MultiSkill v4.9*
