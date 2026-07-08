---
title: "顾问Prompt模板评估报告"
department: governance
type: pending_task
date: "2026-04-27T00:00:00"
status: in_progress
---

# 顾问Prompt模板评估报告

**日期**: 2026-04-27
**评估周期**: 2026-04-19 至 2026-04-27
**评估者**: P1-3-advisor-prompt-review 自动化任务

---

## 执行摘要

本报告对 Dream-MultiSkill 顾问团队的 13 个顾问 Prompt 模板进行了系统性评估，重点考察 **设计意图 vs 实际调用表现** 的匹配度。

### 核心发现

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| 模板完整度 | 7.5/10 | SOUL.md + PROTOCOL.md 结构完整 |
| 实际使用率 | 4/10 | `advisor_direct_call.py` 基于规则引擎，非真实 Agent |
| 与 SKILL 集成度 | 3/10 | dream-multiSkill 仅有模糊的"顾问评审"引用 |
| 输出规范性 | 5/10 | 设计的复杂格式 vs 实际规则引擎输出 |

---

## 一、顾问团队架构概览

### 1.1 已部署顾问 (13个)

| 类别 | 顾问ID | 名称 | 类型 | 优先级 |
|:---|:---|:---|:---|:---:|
| **核心顾问** | ADVISOR-QT | 量化交易顾问 | Builder | P0 |
| | ADVISOR-RM | 风险管理顾问 | Reviewer | P0 |
| | ADVISOR-MR | 宏观研究顾问 | Builder | P0 |
| | ADVISOR-SC | 战略参谋长 | Orchestrator | P0 |
| **紧急响应** | ADVISOR-ER | 紧急响应顾问 | Orchestrator | P1 |
| **扩展顾问** | ADVISOR-RP | 风险预判顾问 | Reviewer | P1 |
| | ADVISOR-EE | 执行工程顾问 | Builder | P1 |
| | ADVISOR-KB | 大师知识顾问 | Builder | P2 |
| | ADVISOR-TR | 趋势研判顾问 | Builder | P2 |
| | ADVISOR-SA | 架构评审顾问 | Reviewer | P2 |
| | ADVISOR-HR | 绩效考核顾问 | Reviewer | P3 |
| | ADVISOR-CO | 成本控制顾问 | Reviewer | P3 |
| | ADVISOR-OP | 运营协调顾问 | Orchestrator | P3 |

### 1.2 模板文件结构

```
~/.workbuddy/advisor-team/agents/
├── advisor-qt/
│   ├── SOUL.md       ✅ (175行)
│   ├── PROTOCOL.md   ✅ (78行)
│   └── inbox/
├── advisor-rm/
│   ├── SOUL.md       ✅ (142行)
│   ├── PROTOCOL.md   ✅ (79行)
│   └── inbox/
├── advisor-mr/
│   ├── SOUL.md       ✅ (156行)
│   └── inbox/
├── advisor-sc/
│   ├── SOUL.md       ⚠️ (仅53行，结构不完整)
│   └── inbox/
└── ... (其他顾问结构类似)
```

---

## 二、各顾问模板详细评估

---

### 2.1 ADVISOR-QT (量化交易顾问)

**有效性评分: 6.5/10**

| 评估维度 | 评分 | 说明 |
|:---|:---:|:---|
| 清晰度 | 7/10 | 身份定义清晰，核心能力明确 |
| 可执行性 | 6/10 | 评分标准有量化阈值，但缺少具体算法实现 |
| 与 SKILL 契合度 | 6/10 | 被 `advisor_direct_call.py` 规则引擎替代 |

#### 设计意图 vs 实际表现

| 设计意图 | 实际表现 | 差距 |
|:---|:---|:---:|
| AI Agent 基于 SOUL.md 做独立判断 | 规则引擎基于 `base_confidence` + 简单阈值生成 | **高** |
| 输出 `verdict: AGREE/DISAGREE/PARTIAL/NEED_MORE_DATA` | 规则引擎输出相同字段 | 中 |
| 置信度基于技术指标综合计算 | 置信度 = `base_confidence + 信号调整 + SKIP惩罚` | **高** |
| 信号质量评分多维度 | 实际只有 `signal_score` 简单传递 | **高** |

#### 问题点

1. **⚠️ 核心能力未实现**: SOUL.md 描述的"技术指标分析(RSI, MACD, EMA, Bollinger Bands)"未被调用
2. **⚠️ 评分标准冲突**: SOUL.md 定义 `强BUY: score≥45 + edge>0 + RSI<40`，但 `advisor_direct_call.py` 规则引擎未实现 RSI 条件检查
3. **✅ 协作关系定义清晰**: 与 RM/MR/EE 的依赖关系在 SOUL.md 中有明确定义

#### 改进建议

```markdown
【建议1】实现真正的指标计算
- 在 advisor_direct_call.py 中添加 RSI/MACD 计算
- 或在 SKILL 层预处理后传递给顾问

【建议2】更新 SOUL.md 评分阈值
- 与实际使用的规则引擎对齐
- 或将 SOUL.md 定位为"理想状态"，规则引擎定位为"当前实现"
```

---

### 2.2 ADVISOR-RM (风险管理顾问)

**有效性评分: 7/10**

| 评估维度 | 评分 | 说明 |
|:---|:---:|:---|
| 清晰度 | 8/10 | 风险等级定义清晰，熔断条件具体 |
| 可执行性 | 7/10 | 仓位算法有明确定义，但缺少波动率计算 |
| 与 SKILL 契合度 | 6/10 | 与 dream-risk-position-sizing 存在功能重叠 |

#### 设计意图 vs 实际表现

| 设计意图 | 实际表现 | 差距 |
|:---|:---|:---:|
| 仓位建议 = f(风险预算, ATR, 账户余额) | 仓位建议 = "5-10%" 或 "3-5%" 固定范围 | **高** |
| VaR 估算基于持仓和波动率 | VaR = "需基于ATR计算" 占位符 | **高** |
| 熔断条件包含具体价格/百分比 | 熔断条件基于 skip_count 和 risk_level 简单触发 | 中 |
| 一票否决权 | 规则引擎实现为 `DISAGREE` verdict | 中 |

#### 问题点

1. **⚠️ VaR 计算缺失**: SOUL.md 定义了 VaR 估算能力，但实际返回占位符
2. **⚠️ 与 dream-risk-position-sizing 重叠**: 两个组件功能边界模糊
3. **✅ 熔断条件可执行**: `当回撤>5% → 禁止新开仓` 等规则可直接实现

#### 改进建议

```markdown
【建议1】整合 dream-risk-position-sizing
- 明确 ADVISOR-RM 负责"定性风险判断"
- dream-risk-position-sizing 负责"定量仓位计算"

【建议2】实现真实的 VaR 估算
- 调用 `okx` CLI 获取历史波动率
- 基于正态分布计算 95% VaR
```

---

### 2.3 ADVISOR-MR (宏观研究顾问)

**有效性评分: 5.5/10**

| 评估维度 | 评分 | 说明 |
|:---|:---:|:---|
| 清晰度 | 6/10 | 宏观分析框架清晰，但数据源过时 |
| 可执行性 | 5/10 | 依赖外部数据源，无实时接入方案 |
| 与 SKILL 契合度 | 5/10 | dream-multiSkill 使用 Tavily 替代了 MR 的功能 |

#### 设计意图 vs 实际表现

| 设计意图 | 实际表现 | 差距 |
|:---|:---|:---:|
| 数据源: Trading Economics/央行官网/财联社 | 规则引擎仅使用 FGI 简单判断 | **极高** |
| 宏观评分算法: 美联储政策/经济数据/地缘风险 | 仅使用 `fgi > 60 → RISK_ON` | **极高** |
| 风险窗口识别 | 风险窗口未在响应中体现 | **高** |

#### 问题点

1. **🚨 核心功能被 SKILL 替代**: dream-multiSkill Step0 调用 Tavily 执行宏观搜索，与 MR 功能高度重叠
2. **⚠️ 数据源过时**: SOUL.md 列出的数据源(P1: Trading Economics)未被实际调用
3. **⚠️ 与 dream-first-principles 冲突**: 第一性原理分析可能包含宏观内容

#### 改进建议

```markdown
【建议1】重新定位 ADVISOR-MR
- 作为 dream-first-principles 的宏观补充层
- 专注于"地缘政治风险"和"政策解读"(Tavily 不擅长的领域)

【建议2】添加 Polymarket 数据接入
- 预测市场概率是 MR 的独特优势
- 与 dream-intelligence-monitor 宏观资产池监控协同
```

---

### 2.4 ADVISOR-SC (战略参谋长)

**有效性评分: 4/10**

| 评估维度 | 评分 | 说明 |
|:---|:---:|:---|
| 清晰度 | 5/10 | 角色定义简洁，但缺少详细执行逻辑 |
| 可执行性 | 3/10 | 无 PROTOCOL.md，响应格式未定义 |
| 与 SKILL 契合度 | 4/10 | 与 dream-strategy-designer 功能高度重叠 |

#### 设计意图 vs 实际表现

| 设计意图 | 实际表现 | 差距 |
|:---|:---|:---:|
| 制定交易战略，匹配 regime | 无对应实现 | **极高** |
| 协调多顾问意见 | 仅在会诊场景中被动参与 | 高 |
| 识别战略窗口期 | 无主动识别能力 | **极高** |

#### 问题点

1. **🚨 SOUL.md 结构不完整**: 仅 53 行，缺少详细决策逻辑和响应格式
2. **🚨 缺少 PROTOCOL.md**: 其他核心顾问都有 PROTOCOL.md，SC 缺失
3. **⚠️ 与 dream-strategy-designer 功能重叠**: 两者都负责"战略制定"
4. **⚠️ 在会诊记录中未被使用**: 2026-04-25/26 的顾问会诊中，SC 未被明确调用

#### 改进建议

```markdown
【建议1】补充 SC PROTOCOL.md
- 定义 STRATEGY_REVIEW 场景的输入输出格式
- 明确 SC 与 dream-strategy-designer 的分工

【建议2】重新定位 SC 为"战略协调者"
- 聚焦于多顾问意见汇总
- 不再做具体的策略设计(交给 QT/KB)
```

---

### 2.5 ADVISOR-EE (执行工程顾问)

**有效性评分: 7/10**

| 评估维度 | 评分 | 说明 |
|:---|:---:|:---|
| 清晰度 | 8/10 | 执行成本模型定义详细，OKX 参数具体 |
| 可执行性 | 7/10 | 与 dream-execution-cost-model 功能对齐 |
| 与 SKILL 契合度 | 6/10 | 存在功能重叠但有明确边界 |

#### 设计意图 vs 实际表现

| 设计意图 | 实际表现 | 差距 |
|:---|:---|:---:|
| 执行成本分析: 手续费/滑点/冲击成本 | 规则引擎未实现 | 高 |
| OKX 特定优化: 最小交易量/挂单费率 | 规则引擎未实现 | 高 |
| 推荐执行策略: 冰山单/TWAP | 响应中仅有占位符 | 高 |
| 与 dream-execution-cost-model 协同 | 未见实际协同调用 | **高** |

#### 亮点

1. **✅ OKX 参数具体**: `最小交易量: 1张`, `挂单费率: 0.02%`, `吃单费率: 0.05%` 可直接使用
2. **✅ 与 OKX CLI 协同**: 触发条件包含"大单(>50张)提交前"，可对接 OKX API
3. **✅ 局限性声明清晰**: 明确不做的领域，减少职责混乱

---

### 2.6 ADVISOR-KB (大师知识顾问)

**有效性评分: 6/10**

| 评估维度 | 评分 | 说明 |
|:---|:---:|:---|
| 清晰度 | 7/10 | 知识库结构完整，大师方法论定义详细 |
| 可执行性 | 5/10 | 知识库目录存在但内容可能不完整 |
| 与 SKILL 契合度 | 6/10 | 与 learning-recall-pack 功能相关 |

#### 设计意图 vs 实际表现

| 设计意图 | 实际表现 | 差距 |
|:---|:---|:---:|
| 大师方法论检索: Livermore/Soros/Buffett 等 | 规则引擎仅返回 "需基于MA/EMA确认" | **极高** |
| 历史案例匹配 | 无实际案例库调用 | **极高** |
| 知识蒸馏: 将大师经验编译为可执行规则 | 无实现 | **极高** |

#### 问题点

1. **⚠️ 知识库目录已定义但内容可能缺失**: `knowledge_base/masters/livermore/rules.md` 等文件是否存在未验证
2. **⚠️ 与 learning-recall-pack 功能重叠**: 两者都做"历史经验召回"
3. **✅ 大师方法论定义有价值**: Livermore/Sperandeo/孙子等可作为决策参考框架

---

## 三、架构层面问题分析

### 3.1 核心矛盾: 设计 vs 实现

```
设计意图                    实际实现
┌─────────────────────────────────────────────┐
│  SOUL.md (AI Agent)    →  真正的 AI 顾问    │  ❌ 未实现
│  PROTOCOL.md           →  Agent 调用协议    │  ❌ 未实现
│  inbox/                →  异步响应机制       │  ❌ 未实现
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  advisor_direct_call.py →  规则引擎替代品    │  ✅ 已实现
│  ADVISOR_PROFILES       →  能力画像字典     │  ✅ 已实现
│  quick_review()         →  快捷调用入口     │  ✅ 已实现
└─────────────────────────────────────────────┘
```

### 3.2 与 dream-multiSkill 的集成问题

**dream-multiSkill SKILL.md 中的顾问引用**:
```markdown
# Step 3 中提到:
"调用 agent-team-orchestration 技能，快速组建一个由
'趋势跟随者'、'均值回归交易员'和'宏观研究员'组成的微型 Agent 团队"

# 但 advisor-team 中的顾问是:
- ADVISOR-QT (量化交易)
- ADVISOR-RM (风险管理)
- ADVISOR-MR (宏观研究)
- ADVISOR-SC (战略参谋)
- ...共 13 个
```

**问题**: 引用的是 `agent-team-orchestration` 技能，不是 `advisor-team`。

### 3.3 会诊记录中的实际使用

| 会诊日期 | 会诊类型 | 调用的顾问 | 实际效果 |
|:---|:---|:---|:---|
| 2026-04-25 | STRATEGY_REVIEW | RM, TA, DC, EX, CM, PM | SC 未被调用 |
| 2026-04-26 | POSITION_REVIEW | RM, TA, DC, SC, QT | 部分顾问代号不匹配(TA/DC vs QT/RM) |

**问题**: 会诊请求中的顾问代号(如 TA, DC)与 advisor-team 中的 ID(advisor-qt, advisor-rm)不一致。

---

## 四、改进建议汇总

### 4.1 高优先级 (P0)

| 建议 | 影响范围 | 实施难度 |
|:---|:---|:---:|
| **补充 ADVISOR-SC PROTOCOL.md** | 核心顾问完整性 | 中 |
| **统一会诊代号**: SC→QT, DC→? | 会诊调用一致性 | 低 |
| **明确 SC vs dream-strategy-designer 分工** | 架构清晰度 | 高 |

### 4.2 中优先级 (P1)

| 建议 | 影响范围 | 实施难度 |
|:---|:---|:---:|
| 实现真实的技术指标计算(RSI/MACD) | QT/MR 准确性 | 高 |
| 实现 VaR 估算 | RM 完整性 | 中 |
| 重新定位 MR: 聚焦地缘政治/政策解读 | MR 独特价值 | 中 |
| 整合 dream-risk-position-sizing 与 ADVISOR-RM | 功能边界 | 高 |

### 4.3 低优先级 (P2)

| 建议 | 影响范围 | 实施难度 |
|:---|:---|:---:|
| 建立 KB 知识库内容 | KB 可用性 | 高 |
| 添加 Polymarket 数据接入 | MR 增强 | 中 |
| 文档化 SOUL.md 与规则引擎的关系 | 可维护性 | 低 |

---

## 五、结论

### 5.1 整体评估

| 指标 | 评分 | 趋势 |
|:---|:---:|:---:|
| 模板完整度 | 7.5/10 | → |
| 实际使用率 | 4/10 | → |
| 与 SKILL 集成度 | 3/10 | ↓ |
| 架构一致性 | 5/10 | ↓ |

**综合评分: 4.9/10 (需要改进)**

### 5.2 关键发现

1. **⚠️ 顾问系统存在"设计过度、实现不足"问题**: 13 个顾问的 Prompt 模板设计精良，但实际使用基于规则引擎，未发挥 AI Agent 的潜力

2. **⚠️ 会诊代号不一致**: 会诊请求中使用 TA/DC/EX 等缩写，与 advisor-team 中的 advisor-qt/advisor-rm/advisor-ee 不匹配

3. **⚠️ 与 dream-multiSkill 集成薄弱**: SKILL.md 中提到"微型 Agent 团队"，但 advisor-team 未被正式引用

4. **✅ 顾问能力矩阵设计合理**: REGISTRY.md 中的场景-顾问映射表可用作后续集成参考

### 5.3 后续行动

```
P0 (本周内):
├── 补充 ADVISOR-SC PROTOCOL.md
├── 统一会诊代号命名规范
└── 明确 SC 角色定位

P1 (本月内):
├── 评估是否升级为真正的 AI Agent 调用
├── 整合重叠功能的 SKILL
└── 补充 KB 知识库内容

P2 (下季度):
├── 建立顾问绩效追踪机制
├── 实现 VaR 和技术指标真实计算
└── 完善 Polymarket 数据接入
```

---

*报告生成时间: 2026-04-27 08:57 CST*
*评估执行: P1-3-advisor-prompt-review 自动化任务*
