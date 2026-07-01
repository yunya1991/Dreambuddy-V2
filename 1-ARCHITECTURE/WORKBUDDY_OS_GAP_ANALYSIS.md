# WorkBuddy OS 模块化注册表 — 逐项比对报告

> **版本**: v1.0
> **日期**: 2026-06-30
> **目的**: 根据核心思维链技术文档和系统实践逐一比对，找出缺失项
> **原则**: 技术文档是"设计意图"，系统实践是"实现状态"，比对找出差距

---

## 一、比对方法论

### 1.1 比对维度

| 维度 | 说明 |
|------|------|
| **技术文档定义** | 来自 SKILL_REGISTRY.md、A系列调度链、三屏系统架构等 |
| **实验代码实现** | 来自 experiments/ab-trading/core/nodes/ |
| **生产代码集成** | 来自 6-TRADING/skills/ 和 10-经典指标系统/ |
| **缺失项** | 有文档定义但无代码实现 |
| **待升级项** | 有代码实现但未接入模块化注册表 |

### 1.2 状态定义

| 状态 | 符号 | 说明 |
|------|------|------|
| **已实现并注册** | ✅ | 有代码实现，已纳入模块化注册表 |
| **已实现未注册** | ⚠️ | 有代码实现，未纳入模块化注册表 |
| **仅文档定义** | ❌ | 技术文档有定义，无代码实现 |
| **缺失** | 🔴 | 核心功能缺失，需要新建 |

---

## 二、A链 (AI交易能力) — 逐项比对

### 2.1 A链完整清单

| 模块ID | 模块名称 | 技术文档定义 | 实验代码 | 6-TRADING SKILL | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------------|------------|----------|
| **A0** | 矛盾论 | A0矛盾论：多维度分析，4维评分定主矛盾 | ✅ a0_contradiction.py | dream-contradiction-theory | ⚠️ 已实现，未注册 | 需接入注册表 |
| **A1** | 深度调研 | dream-strategy-research：Tavily宏观+OKX行情+链上+ETF+FGI | ✅ a1_research.py | dream-strategy-research | ⚠️ 已实现，未注册 | 需接入注册表 |
| **A2** | 第一性原理 | dream-first-principles：阻力最小+MA轨迹+矛盾处理 | ✅ a2_analysis.py | dream-first-principles | ⚠️ 已实现，未注册 | 需接入注册表 |
| **A3** | 策略设计 | dream-strategy-designer：多情景合成+红队分析 | ✅ a3_strategy.py | dream-strategy-designer | ⚠️ 已实现，未注册 | 需接入注册表 |
| **A4** | 战术验证 | dream-tactical-validator：Demo账户3层索引验证 | ✅ a4_gate.py | dream-tactical-validator | ⚠️ 已实现，未注册 | 需接入注册表 |
| **A5** | 战术执行 | dream-tactical-executor：读phase7+实盘执行 | ❌ | dream-tactical-executor | ❌ 无实现 | **需新建** |
| **A6** | 情报监控 | dream-intelligence-monitor：每小时P0/P1告警 | ❌ | dream-intelligence-monitor | ❌ 无实现 | **需新建** |
| **A7** | 实践门禁 | A7-practice-theory：5项门禁检查 | ❌ | A7-practice-theory | ❌ 无实现 | **需新建** |
| **A8** | 知行合一 | A8-theory-practice-verification：自我批评+进化 | ❌ | A8-theory-practice-verification | ❌ 无实现 | **需新建** |
| **A9** | 离场决策 | dream-exit-skill-v2：4层离场链 | ✅ a9_exit.py | dream-exit-skill-v2 | ⚠️ 已实现，未注册 | 需接入注册表 |

**A链比对汇总**: ✅ 已实现 5个 | ⚠️ 已实现未注册 5个 | ❌ 缺失 4个 (A5/A6/A7/A8)

### 2.2 三屏交易系统

| 模块ID | 模块名称 | 技术文档定义 | 实验代码 | 6-TRADING SKILL | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------------|------------|----------|
| Screen1 | 第一屏：周线方向 | dream-screen1-first：七维牛熊评分+大师辩论 | ❌ | dream-screen1-first | ❌ 无实现 | **需新建** |
| Screen2 | 第二屏：日线预设 | dream-screen2-second：A1-A3+回测+贝叶斯 | ❌ | dream-screen2-second | ❌ 无实现 | **需新建** |
| Screen3 | 第三屏：实时执行 | dream-screen3-third：A7+A4+GateC+A5+A6+A9 | ❌ | dream-screen3-third | ❌ 无实现 | **需新建** |

**三屏交易比对汇总**: ✅ 已实现 0个 | ⚠️ 已实现未注册 0个 | ❌ 缺失 3个 (全缺)

### 2.3 情报闭环

| 模块ID | 模块名称 | 技术文档定义 | 实验代码 | 6-TRADING SKILL | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------------|------------|----------|
| 做梦部 | 做梦部 | dream-oneirology：弗洛伊德梦分析 | ✅ oneirology.py | dream-oneirology | ⚠️ 已实现，未注册 | 需接入注册表 |
| 大师辩论 | 大师辩论 | master-seminar：多空阵营大师辩论 | ❌ | master-seminar | ❌ 无实现 | **需新建** |

**情报闭环比对汇总**: ✅ 已实现 1个 | ⚠️ 已实现未注册 0个 | ❌ 缺失 1个 (大师辩论)

### 2.4 复盘进化

| 模块ID | 模块名称 | 技术文档定义 | 实验代码 | 6-TRADING SKILL | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------------|------------|----------|
| 数据分析 | 数据分析 | dream-data-analysis：episodes量化分析 | ❌ | dream-data-analysis | ❌ 无实现 | **需新建** |
| 知识库 | 知识库 | dream-knowledge：regime/classic/master | ❌ | dream-knowledge | ❌ 无实现 | **需新建** |

**复盘进化比对汇总**: ✅ 已实现 0个 | ⚠️ 已实现未注册 0个 | ❌ 缺失 2个 (数据分析/知识库)

---

## 三、C链 (经典量化能力) — 逐项比对

### 3.1 C链完整清单

| 模块ID | 模块名称 | 技术文档定义 | 实验代码 | 10-经典指标系统 | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------------|------------|----------|
| C1 | 技术扫描 | 经典指标系统API：RSI/MACD/EMA/ATR | ✅ c1_tech_scan.py | ml_trade_service.py | ⚠️ 已实现，未注册 | 需接入注册表 |
| C2 | Regime识别 | dream-regime-detector：7分类+MasterFit | ❌ | - | ❌ 无实现 | **需新建** |
| C3 | 信号评分 | dream-signal-scoring-spec：8维评分 | ❌ | - | ❌ 无实现 | **需新建** |
| C4 | 风险仓位 | dream-risk-position-sizing：风险预算 | ❌ | - | ❌ 无实现 | **需新建** |
| C5 | 执行成本 | dream-execution-cost-model：费率+滑点 | ❌ | - | ❌ 无实现 | **需新建** |

**C链比对汇总**: ✅ 已实现 1个 | ⚠️ 已实现未注册 1个 | ❌ 缺失 4个 (C2-C5)

### 3.2 指标库

| 模块ID | 模块名称 | 技术文档定义 | 10-经典指标系统 | 注册表状态 | 缺失分析 |
|--------|----------|--------------|------------------|------------|----------|
| 指标计算 | 指标计算 | RSI/MACD/MA/Bollinger/Ichimoku/ATR | ✅ talib/ | ⚠️ 已实现 | 需接入注册表 |
| 策略库 | 策略库 | 经典10策略/马丁/突破 | ✅ ml_trade_service.py | ⚠️ 已实现 | 需接入注册表 |
| 回测引擎 | 回测引擎 | dream-backtest | ❌ | ❌ 无实现 | **需新建** |
| 执行引擎 | 执行引擎 | OKX/Freqtrade | ✅ ml_trade_service.py | ⚠️ 已实现 | 需接入注册表 |

---

## 四、F链 (基本面能力) — 逐项比对

### 4.1 F链完整清单

| 模块ID | 模块名称 | 技术文档定义 | 实验代码 | 9-基本面分析 | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------------|------------|----------|
| F1 | 新闻聚合 | 新闻采集+摘要 | ✅ f1_news.py | nanoclaw/ | ⚠️ 已实现，未注册 | 需接入注册表 |
| F2 | 资金流分析 | ETF资金流+净流入+大额转账 | ✅ f2_fund_flow.py | engines/signal_engine.py | ⚠️ 已实现，未注册 | 需接入注册表 |
| F3 | 情绪分析 | FGI+费率+多空比 | ✅ f3_sentiment.py | engines/sentiment_engine.py | ⚠️ 已实现，未注册 | 需接入注册表 |
| F4 | 链上指标 | 链上数据+巨鲸追踪 | ❌ | nanoclaw/flow/ | ❌ 无实现 | **需新建** |
| F5 | 宏观数据 | 宏观事件+DXY+利率 | ❌ | nanoclaw/narrative/ | ❌ 无实现 | **需新建** |

**F链比对汇总**: ✅ 已实现 3个 | ⚠️ 已实现未注册 3个 | ❌ 缺失 2个 (F4/F5)

---

## 五、G域 (治理能力) — 逐项比对

| 模块ID | 模块名称 | 技术文档定义 | 6-TRADING SKILL | 注册表状态 | 缺失分析 |
|--------|----------|--------------|------------------|------------|----------|
| G1 | 宪法校验 | dream-constitution | ❌ | dream-constitution | ❌ 无实现 | **需新建** |
| G2 | 合规审查 | ai-trading-compliance：R0-R3分级+9项门禁 | ❌ | ai-trading-compliance | ❌ 无实现 | **需新建** |
| G3 | 成本控制 | dream-cost-control：成本归因+Tavily预算 | ❌ | dream-cost-control | ❌ 无实现 | **需新建** |
| G4 | 性能评估 | dream-performance-review：5维量化评分 | ❌ | dream-performance-review | ❌ 无实现 | **需新建** |

**G域比对汇总**: ✅ 已实现 0个 | ❌ 缺失 4个 (全缺)

---

## 六、T域 (工具能力) — 逐项比对

| 模块ID | 模块名称 | 技术文档定义 | 实现位置 | 注册表状态 | 缺失分析 |
|--------|----------|--------------|----------|------------|----------|
| T1 | Tavily搜索 | tavily：实时网络搜索 | ❌ | ❌ 无实现 | **需新建** |
| T2 | 产物归档 | artifact-alignment-manager | ❌ | ❌ 无实现 | **需新建** |
| T3 | 经验教训 | learning-lesson-distiller | ❌ | ❌ 无实现 | **需新建** |
| T4 | 策略记忆 | dream-knowledge | ❌ | ❌ 无实现 | **需新建** |
| T5 | 自动修复 | auto-repair | ❌ | ❌ 无实现 | **需新建** |

**T域比对汇总**: ✅ 已实现 0个 | ❌ 缺失 5个 (全缺)

---

## 七、缺失汇总

### 7.1 高优先级缺失 (影响核心交易链路)

| 优先级 | 模块 | 说明 | 影响 |
|--------|------|------|------|
| P0 | **A5_战术执行** | 实盘下单核心，无则无法执行交易 | 阻塞交易闭环 |
| P0 | **A6_情报监控** | 持仓期监控核心，无则无法监控 | 阻塞持仓管理 |
| P0 | **A7_实践门禁** | 交易前最后门禁，无则无风控 | 阻塞风控 |
| P0 | **Screen3_实时执行** | 三屏执行层核心，无则三屏不闭环 | 阻塞三屏系统 |
| P1 | **A8_知行合一** | 复盘进化核心，无则系统无法进化 | 阻塞学习闭环 |
| P1 | **C2_Regime识别** | 市场状态分类，无则无法做Regime适配 | 影响策略匹配 |

### 7.2 中优先级缺失 (影响完整性)

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P2 | **Screen1_周线方向** | 三屏第一屏 |
| P2 | **Screen2_日线预设** | 三屏第二屏 |
| P2 | **大师辩论** | A3策略设计增强 |
| P2 | **C3_信号评分** | 入场信号强度评估 |
| P2 | **C4_风险仓位** | 仓位管理 |
| P2 | **C5_执行成本** | 费率滑点计算 |

### 7.3 低优先级缺失 (长期建设)

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P3 | **数据分析** | 复盘量化分析 |
| P3 | **知识库** | 策略知识库 |
| P3 | **F4_链上指标** | 链上数据 |
| P3 | **F5_宏观数据** | 宏观事件 |
| P3 | **G域(4个)** | 治理能力 |
| P3 | **T域(5个)** | 工具能力 |

---

## 八、实现建议

### Phase 1: 核心链路补全 (1-2周)

```
目标: 让核心交易链路(A0-A9 + Screen3)能够闭环运行

优先级排序:
1. A5_战术执行 (P0) - 交易执行核心
2. A6_情报监控 (P0) - 持仓监控核心
3. A7_实践门禁 (P0) - 风控核心
4. Screen3_实时执行 (P0) - 三屏闭环
5. A8_知行合一 (P1) - 学习闭环
6. C2_Regime识别 (P1) - 状态分类
```

### Phase 2: 三屏系统补全 (2-3周)

```
目标: 让三屏交易体系完整运行

优先级排序:
1. Screen1_周线方向
2. Screen2_日线预设
3. Screen3_实时执行 (已在Phase1)
4. 大师辩论
```

### Phase 3: C/F链补全 (3-4周)

```
目标: 让C链和F链模块化接入

优先级排序:
1. C2_Regime识别
2. C3_信号评分
3. C4_风险仓位
4. C5_执行成本
5. F4_链上指标
6. F5_宏观数据
```

### Phase 4: 治理和工具 (长期)

```
目标: 完善治理和工具能力

优先级排序:
1. G1_宪法校验
2. G2_合规审查
3. G3_成本控制
4. T1-T5 工具能力
5. G4_性能评估
6. 数据分析/知识库
```

---

## 九、已实现未注册的模块 (接入注册表即可)

以下模块已有代码实现，只需接入模块化注册表即可：

| 模块 | 实现位置 | 注册表配置 |
|------|---------|-----------|
| A0_矛盾论 | experiments/ab-trading/core/nodes/a0_contradiction.py | 需添加 adapter 配置 |
| A1_调研 | experiments/ab-trading/core/nodes/a1_research.py | 需添加 adapter 配置 |
| A2_第一性原理 | experiments/ab-trading/core/nodes/a2_analysis.py | 需添加 adapter 配置 |
| A3_策略设计 | experiments/ab-trading/core/nodes/a3_strategy.py | 需添加 adapter 配置 |
| A4_门禁 | experiments/ab-trading/core/nodes/a4_gate.py | 需添加 adapter 配置 |
| A9_离场 | experiments/ab-trading/core/nodes/a9_exit.py | 需添加 adapter 配置 |
| C1_技术扫描 | experiments/ab-trading/core/nodes/c1_tech_scan.py | 需添加 adapter 配置 |
| F1_新闻 | experiments/ab-trading/core/nodes/f1_news.py | 需添加 adapter 配置 |
| F2_资金流 | experiments/ab-trading/core/nodes/f2_fund_flow.py | 需添加 adapter 配置 |
| F3_情绪 | experiments/ab-trading/core/nodes/f3_sentiment.py | 需添加 adapter 配置 |
| 做梦部 | experiments/ab-trading/core/nodes/oneirology.py | 需添加 adapter 配置 |

---

*报告版本: v1.0 | 日期: 2026-06-30 | 比对范围: A/C/F/G/T 五域完整清单*
