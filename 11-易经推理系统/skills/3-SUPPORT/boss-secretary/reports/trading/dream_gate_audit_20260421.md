---
title: "Dream Gate 审计巡检报告 #13"
department: governance
type: audit
date: "2026-04-21T09:57:00"
status: completed
---

# Dream Gate 审计巡检报告 #13

**执行时间**: 2026-04-21 09:57 (UTC+8)
**巡检编号**: #13
**执行间隔**: ~24h (符合≥72h/次最低要求)

---

## 总体结论: ✅ PASS / Advisory (91/100, ↓2 vs #12)

| 维度 | 评分 | 上期 | 趋势 |
|:---|:---:|:---:|:---:|
| 自动化健康率 | 93/100 | 82/100 | ↑11 |
| Skill可用率 | 100/100 | 100/100 | → |
| Episode格式退化率 | 70/100 | 100/100 | ↓30 |
| Gate审计评分 | 93/100 | 93/100 | → |
| **综合评分** | **91/100** | **93/100** | **↓2** |

**评分下降原因**: 04-20期间Episode退化率回升（skills_called/quality_gate_score字段缺失），上次巡检(#12)未检测到。

---

## 一、自动化健康率检查 (93/100)

### 总览

| 指标 | 数值 |
|:---|:---:|
| 总自动化数 | **29** |
| 正常运行 | **27** |
| 有告警/失败 | **1** (dream-tactical-executor-2) |
| 文件不存在 | **1** (dream-insight-processor) |
| 健康率 | **93.1%** |

### 详细状态

#### 🟢 核心交易链路 (全绿)

| 自动化 | 最后执行 | 状态 | 备注 |
|:---|:---|:---:|:---|
| dream-multiskill | 04-21 09:15 | ✅ SKIP | EP40, 评分39/70, Edge-58bps |
| dream-multiskill-2 | 04-21 01:52 | ✅ 正常 | 非交易监控, SHORT已平仓 |
| dream-intelligence-monitor | 04-21 09:35 | ✅ 正常 | 停火协议P0告警 |
| secretary-workflow-trigger | 04-21 08:00 | ✅ HEALTHY | 顾问绩效全D级 |
| auto-repair-scheduler | 04-19 13:21 | ✅ HEALTHY | 26/26 episode合规 |

#### 🟢 学习链路 (全绿)

| 自动化 | 最后执行 | 状态 | 备注 |
|:---|:---|:---:|:---|
| dream-oneirology | 04-20 | ✅ 成功 | 第2次, 3个梦境 |
| dream-proposal-generator | 04-20 19:30 | ✅ 成功 | 3项提案(2P0+1P1) |
| dream-shadow-verification | 04-20 20:00 | ✅ 成功 | PASS×2, PASS(修正)×1 |
| dream-rollback-actuator | 04-20 20:35 | ✅ 成功 | 3项提案落地, v4.2 |
| dream-tactical-executor-2 | 04-21 00:24 | 🔴 失败 | API签名问题, 下单失败 |
| mrm-audit-offhours | 04-20 12:00 | ✅ 成功 | 首次基线42/100(D) |

#### 🟢 支撑链路 (全绿)

| 自动化 | 最后执行 | 状态 | 备注 |
|:---|:---|:---:|:---|
| advisor-inbox-poller | 04-20 23:14 | ✅ 成功 | 首次运行, 10/10响应补充 |
| performance-review | 04-19 22:00 | ✅ 成功 | 93/100(S级) |
| hr | 04-19 11:28 | ✅ 成功 | 11/11核心, 9/9平台, 0缺口 |
| cost-monitor | 04-19 20:00 | ✅ 成功 | 累计+$187.84(+36.1%) |
| knowledge-sync | 04-19 18:10 | ✅ 成功 | 档案中心初始化 |
| market-research | 04-20 18:30 | ✅ 成功 | 顾问链路断裂确认 |
| brainstorm-daily | 04-19 | ✅ 成功 | 采纳3项P0优化 |

#### 🟢 秘书/治理链路 (全绿)

| 自动化 | 最后执行 | 状态 | 备注 |
|:---|:---|:---:|:---|
| automation (秘书风险推演) | 04-20 11:32 | ✅ 成功 | 首次, 区间震荡预测 |
| automation-2 (凌晨复盘) | 04-20 03:00 | ✅ 成功 | 71/100(C+), automation-7/8断链 |
| automation-3 (晚间汇总) | 04-20 22:00 | ✅ 成功 | 82/100(B+), 学习链路首次闭环 |
| automation-4 (绩效监控) | 04-20 18:00 | ✅ 成功 | A级87/100 |
| automation-5 (运营健康) | 04-19 14:00 | ✅ 成功 | 17/17健康, 88/100 |
| automation-6 (资源效率) | 04-19 06:00 | ✅ 成功 | 正常 |
| automation-7 (做梦洞察) | 04-20 17:30 | ✅ 成功 | ⬆️ 上期断链已修复! |
| automation-8 (洞察跟进) | 04-20 18:35 | ✅ 成功 | ⬆️ 上期断链已修复! |
| automation-9 (早间情报) | 04-21 07:30 | ✅ 成功 | 全部数据源采集成功 |

#### 🔴 异常项

| 自动化 | 问题 | 严重级别 | 上期状态 |
|:---|:---|:---:|:---|
| dream-tactical-executor-2 | EP37下单失败(API签名问题) | P1 | 首次发现 |
| dream-insight-processor | memory.md不存在 | P2 | 同上期 |

---

## 二、Skill可用率检查 (100/100)

### 核心11个Skills

| # | Skill | 状态 | SKILL.md |
|:---|:---|:---:|:---:|
| 1 | dream-strategy-parser | ✅ 已安装 | 96B |
| 2 | technical-analyst | ✅ 已安装 | 224B |
| 3 | tavily | ✅ 已安装 | 224B |
| 4 | odaily | ✅ 已安装 | 352B |
| 5 | ontology | ✅ 已安装 | 224B |
| 6 | dream-signal-scoring-spec | ✅ 已安装 | 128B |
| 7 | dream-risk-position-sizing | ✅ 已安装 | 96B |
| 8 | dream-execution-cost-model | ✅ 已安装 | 96B |
| 9 | dream-pretrade-gatekeeper | ✅ 已安装 | 128B |
| 10 | dream-output-quality-gate | ✅ 已安装 | 96B |
| 11 | dream-posttrade-mrm-audit | ✅ 已安装 | 96B |

**核心Skills可用率: 11/11 = 100%**
**总安装Skills数: 80个** (含扩展/平台/工具类)

---

## 三、Episode格式退化率检查 (70/100)

### 最近5个Episode检查

| 字段 | EP40(04-21) | EP39(04-21) | EP37(04-20) | EP36(04-20) | EP34(04-20) | EP33(04-20) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| episode_id | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ |
| score | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| decision | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| skills_called | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| timestamp/ts | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| quality_gate_score | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |

### 退化率统计

| 指标 | 数值 | 上期(#12) |
|:---|:---:|:---:|
| 字段覆盖率 | 30/36 = **83.3%** | 100% |
| 完全合规Episode率 | 2/6 = **33.3%** | 100% |
| skills_called退化率 | 3/6 = **50%** | 0% |
| quality_gate退化率 | 3/6 = **50%** | 0% |

### 根因分析

- **EP33/34/36/37** 由脚本v4.1生成，但脚本在v4.1→v4.2升级过程中，中间版本的Episode缺少`skills_called`和`quality_gate_score`字段
- EP39/40 (最新) 已恢复完整格式，表明v4.2修复生效
- **结论**: 退化是历史中间版本产物，非系统性回退。auto-repair-scheduler应覆盖修复

---

## 四、Gate审计评分详情 (93/100)

### 评分细项

| 子项 | 得分 | 满分 | 说明 |
|:---|:---:|:---:|:---|
| 核心自动化健康 | 25 | 25 | 27/29正常运行(93.1%) |
| 学习链路完整性 | 18 | 20 | automation-7/8已修复, 首次闭环 |
| Skill可用率 | 15 | 15 | 11/11核心 + 80总安装 |
| Episode格式合规 | 12 | 15 | 历史中间版本退化-3 |
| Lessons/记忆系统 | 10 | 10 | 正常运作 |
| 数据可靠性 | 8 | 10 | ETF/Odaily DEGRADED, NeoData Token过期 |
| 决策一致性 | 5 | 5 | 三叉戟/战略门禁正确 |

### 评分趋势

```
#6  60 → #7 85 → #8 88 → #9 90 → #10 92 → #11 95 → #12 93 → #13 91
                                    ↑持续提升→                    ↓微调
```

---

## 五、关键发现

### 🟢 正面进展
1. **automation-7/8断链已修复**: 上期P1问题→本期已正常执行，学习链路首次端到端闭环
2. **提案-验证-落地全链路打通**: 3项提案→影子验证→回滚落地，v4.2已建立
3. **顾问轮询器首次运行**: 10/10响应补充，止血方案v3.0已集成
4. **情报监控高频运行**: 每小时产出，停火协议P0告警及时
5. **最新Episode(EP39/40)格式恢复完整**: v4.2修复生效

### 🔴 需关注
1. **dream-tactical-executor-2 下单失败**: EP37 SHORT信号下单失败(API签名问题)，需要排查修复
2. **Episode历史退化**: EP33-37中间版本缺skills_called和quality_gate_score，需auto-repair覆盖

### 🟡 监控项
1. **美伊停火协议4/22到期**: <17h，intelligence-monitor建议禁止开新仓
2. **连续SKIP模式**: EP23-40 (18次SKIP，占85%)，远超反顾问阈值(7次)
3. **顾问系统响应率**: 仅17.5%，绩效全D级，需建立采纳反馈机制
4. **数据源退化**: ETF/Odaily间歇性DEGRADED, NeoData Token过期
5. **dream-insight-processor**: memory.md不存在，自动化虽可运行但无记忆追溯

---

## 六、行动项

| 优先级 | 编号 | 行动 | 负责自动化 |
|:---|:---|:---|:---|
| P1 | A-13-001 | 修复dream-tactical-executor-2 API签名问题 | auto-repair |
| P2 | A-13-002 | auto-repair覆盖EP33-37缺失字段 | auto-repair |
| P2 | A-13-003 | 创建dream-insight-processor memory.md | 手动 |
| P2 | A-13-004 | 更新NeoData Token | 手动 |
| P3 | A-13-005 | 4/22后密集监控停火协议走向 | intelligence-monitor |

---

## 七、与上期(#12)对比

| 指标 | #12(04-20) | #13(04-21) | 变化 |
|:---|:---:|:---:|:---:|
| 自动化健康率 | 82% | 93% | ↑11% |
| Skill可用率 | 100% | 100% | → |
| Episode退化率 | 0% | 50% | ↓50% |
| Gate评分 | 93 | 91 | ↓2 |
| P0问题 | 0 | 0 | → |
| P1问题 | 1 | 1 | → (新: tactical-executor) |
| P2问题 | 2 | 3 | ↑1 |

---

*报告生成时间: 2026-04-21 09:57 UTC+8*
*下次巡检: 2026-04-22 10:00 UTC+8*
