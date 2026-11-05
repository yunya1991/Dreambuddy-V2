# SPEC-49 神经网络交易系统框架协议 v0.8

- 状态：🟡 v0.8 评审稿（已按代码核验 + 架构一致性审计 + 修复建议 + 评审决议；本文只定义架构、协议契约与提案，不含实现代码）
- 日期：2026-11-05
- 归属：49-交易框架协议（交易域总体框架与协议唯一事实源）
- 上游输入：数据层（18 采集 / 19 DAL / 20 清洗 / 21 特征 / 38 数据库）、39 金融语义蒸馏、9 基本面分析
- 宏观层：40 周期神经网络 → 43 战略承接推演层（宏观弹性约束生成）
- 协调层：42 神经网络交易协调层（插件总线 / 参数治理 / 信号归一化）
- 子交易系统：11-BCRM2.0、11-BDSM、29 事件驱动（以及未来插件）
- **矛盾裁决与最终决策层：23 四层闭环自进化交易架构**
- 执行层：L0 trade-exec MCP（paper 唯一出口）、11 域 okx_client 旁路网关（live 唯一出口）
- 分析层：L2 DreamOS / DSH Worker（只读观察，不进入闭环）
- **代码基线**：工作区代码快照约 `be75caa7`（2026-11-05 08:31Z）；trade-exec 相关文件来自 `1eb0076`（通过 git 对象读取）。提交基线为 `f27fddfc`（2026-11-05 15:42Z）；`1eb0076` 之后的提交均为 48-涌现架构（emergence），未触及 23/40/42/43/trade-exec，故本 SPEC 的交易域核验结论仍适用。技术文档可能滞后，**文档与代码冲突处以代码为准**；工作区尚未同步 origin/main 全部对象。

---

## §0 Executive Summary

### 0.1 系统定位

我们搭建的是一个**神经网络式交易系统**：

- **输入层**：数据、语义、基本面特征。
- **宏观层**：40 宏观周期神经网络 → 43 更细的战略层，生成**宏观弹性约束**。
- **协调层**：42 作为插件总线，把宏观约束与各子交易系统的候选信号统一归一化。
- **子交易系统层**：BCRM2.0、BDSM、29 事件驱动（未来可插入更多策略）——它们是**传感器与候选信号源**。
- **矛盾裁决与最终决策层**：23 通过矛盾系统 + 矛盾 Transformer 识别宏观与微观冲突，做矛盾转化与最小阻力路径求解，输出唯一最终决策信号。
- **执行层**：L0 trade-exec MCP（paper）/ 11 旁路（live）。
- **反馈层**：成交/PnL/拒单 → 样本 → 训练/进化 → 反哺 23 与宏观层。

### 0.2 23 的定位：矛盾裁决器 + 最终决策器（本版核心修正）

23 **不是简单的信号输出口，也不是信号聚合器**。它的不可替代价值在于：

1. **矛盾系统**：多路径（bdsm / bcrm / strategic / deep_reasoning / l2_gene / synthesized）生成候选矛盾 → 共振检测 → 4 维冲突裁决 → Wyckoff/Minervini 主导性评估 → 识别主要矛盾。
2. **矛盾 Transformer**：Q = 价格路径签名，K/V = 36 个外生因子，8 个 head（目标配置；代码默认 4 head/32 dim，实际由 checkpoint 决定）与矛盾维度对齐；context 注入 NeuralSDE drift，形成“当前主矛盾”的力量表示。
3. **双链路交叉验证**：Granger 因果链（过去主矛盾）vs 当前主矛盾识别器；一致 / 分歧 / 持续分歧 + 结构性断裂 → **质变**。目标接入 Attention 权重（`AttentionAggregator` 已实现、生产未接线）。
4. **最小阻力路径**：五/六维阻力场 + HJB / 变分法 / 路径积分，求主导矛盾约束下的最优路径。
5. **宏观与微观的冲突转化**：宏观战略层只是**弹性约束**（调制先验/仓位/阈值），微观子系统的量变（力量累积、排序变化）在 23 内被转化为质变（结构性断裂、主要矛盾切换），最终预测并输出唯一决策信号。

一句话：**宏观层提供弹性约束，子交易系统提供微观量变，23 负责矛盾转化与最优控制求解，输出最终决策。**

### 0.3 九条收口决策

1. **40 → 43 = 宏观弹性约束层**：40 提供长周期结构约束（`cycle_state` / `strategy_mapping`），43 提供战略档位（`strategic_tier` / `war_state` / `position_band`）。
2. **宏观层只是约束，不是决策**：40/43 调制 23 的评分、仓位与阈值，不直接产生交易信号。
3. **所有子交易系统必须消费宏观弹性约束**：BCRM2.0、BDSM、29、23 无例外；未来插件同样必须订阅。
4. **42 = 插件总线 + 约束分发 + 参数治理**：新增策略通过 `registry.yaml` + `adapters/` 接入，零代码侵入。
5. **23 = 矛盾裁决器 + 唯一最终决策出口（全标的）**：识别宏观/微观冲突、做矛盾转化与最小阻力路径求解，输出 FinalDecisionSignal v1。
6. **执行统一收口**：paper 走 L0 trade-exec MCP；live 走 11 域 okx_client 旁路，**实盘链路永不暴露 MCP**。
7. **L1 闭环、L2 只读**：L1 自身是“信号→执行→反馈→训练→再信号”的闭环；L2 只能通过 `l1.trading.mcp` 只读观察。
8. **13 风控优先**：任何宏观约束、42 参数、23 裁决都不得放宽 13 风控门禁。
9. **编号口径**：40 周期神经网络、42 协调层、43 战略承接；41 是文件索引系统，不参与交易链。

### 0.4 不做什么

| 禁止 | 原因 |
|---|---|
| 不把 23 实现成“信号求和器” | 23 的价值是矛盾转化 + 最优路径求解 |
| 不在 42 内做策略决策或下单 | 42 只做汇聚/归一化/参数治理 |
| 不让子交易系统绕过 42 直接向 23/执行侧发信号 | 42 是唯一插件接入面 |
| 不让任何模块绕过 23 直接向执行侧出信号 | 23 是唯一最终决策出口 |
| 不让 L1 交易层 MCP 做策略判定 | H1：判定与交易热路径 in-process |
| 不让 L2 触发信号/执行/训练 | L2 只读观察 |
| 不让 trade-exec MCP 触真实交易所 | 实盘链路永不暴露 MCP |
| 不放宽 13 风控 / 48 域三关门禁 | 风控与验收门禁优先于任何参数 |

### 0.5 阅读口径：现状 vs 目标

- **§2 架构图与 §4 机制默认描述目标态**；现状以 §6（46 条差距）与 §11（35 条冲突）为准。
- 图中 `13→16→22` 是完整目标管道；现状只有 13 已接线，16/22 未接线（§6）。
- 图中“所有子交易系统受宏观约束”是目标；现状只有 11 `war_state` 被 23 消费，40/43 宏观约束“注入但零消费”（§11）。
- 任何“已落地/已接线”表述均应以 §10 代码核验结论为准；文档与代码冲突时以代码为准。

---

## §1 分层与模块映射

### 1.1 七层职责

| 层 | 组成 | 职责 | 不做什么 |
|---|---|---|---|
| **输入层** | 18/19/20/21/38、39、9 | 行情、宏观、特征、语义、基本面 | 不产生交易信号 |
| **宏观弹性约束层** | 40 → 43 | 长周期结构约束 → 战略档位/仓位带/风控守卫 | 不下单、不直接出交易信号 |
| **协调层** | 42 | 插件注册、SignalSchema 归一化、约束分发、参数治理 | 不做策略判断、不下单 |
| **子交易系统层** | 11-BCRM2.0、11-BDSM、29 | 传感器 + 候选信号生成；必须受宏观约束 | 不绕过 42、不直接下单 |
| **矛盾裁决与最终决策层** | **23** | **矛盾识别/转化 + 矛盾 Transformer + 最小阻力路径 + 最终决策** | 不执行下单 |
| **执行层** | L0 trade-exec MCP（paper）/ 11 旁路（live） | 风控→定容→执行→对账 | 不改写策略、不触实盘（MCP） |
| **反馈层** | L0 样本、11 成交、23 训练/进化 | 样本→训练→进化→反哺 23 与宏观层 | 不直接改生产参数（须走门禁） |

### 1.2 模块映射

| 模块 | 层 | 角色 | 当前关键产物 |
|---|---|---|---|
| 39 金融语义蒸馏 | 输入层 | 知识生产 SSoT | `l3_synthesis.json`、`semantic_events.jsonl`、`contradiction_events.jsonl` |
| 9 基本面分析 | 输入层 | 基本面/情感特征 | FinBERT 情感、基本面评分 |
| 18/19/20/21/38 | 输入层 | 采集→清洗→DAL→特征→库 | FRED、yfinance、ccxt、FeatureHub、F&G |
| **40 周期神经网络** | 宏观层 | 长周期结构约束 | `cycle_state.json`、`strategy_mapping.json`、`fund_flow.json`、`washout_verdicts.json` |
| **43 战略承接推演** | 宏观层 | 战略档位/弹性约束 | `strategic_extension_signal.json`、`strategic_elements_history.jsonl` |
| **42 协调层** | 协调层 | 插件总线/参数治理 | `registry.yaml`、`bus_state.json`、`params_active.json` |
| 11-BCRM2.0 | 子交易系统 | 辩证 ML 技术分析 | 五域状态、BCRM2 inference、`position_factor` / `sl_tighten` |
| 11-BDSM | 子交易系统 | 基本面/价值驱动 | `bdsm_snapshot_*.json`、`direction_constraint` / `cap_multiplier` |
| 29 事件驱动 | 子交易系统 | 离散宏观事件脉冲 | `EventSignal`、`event_driven_state.json`（由 23 写） |
| **23 四层闭环自进化** | **决策层** | **矛盾裁决 + 最终决策** | FinalDecisionSignal v1、`23_signal_state.json`（目标） |
| L0 trade-exec MCP | 执行层 | paper 唯一出口 | 9 工具、paper 账本、执行样本 |
| 11 okx_client | 执行层 | live 唯一出口（旁路） | 实盘订单、成交（不经 MCP） |
| 13 通用风控 | 执行层 | 事前风控（fail-closed） | RiskCheckPort |
| 16 调控系统 | 执行层 | 资金定容 | capital_allocator / control |
| 22 执行引擎 | 执行层 | 订单路由/算法/滑点/审计 | OrderPort |

### 1.3 编号口径

- **40**：周期神经网络（宏观周期）。
- **42**：神经网络交易协调层（插件总线）。
- **43**：战略承接推演层（更细战略层）。
- **41**：文件索引系统，**不参与交易链**（用户 2026-11-05 确认）。

---

## §2 目标架构

### 2.1 总图

```text
┌──────────────────────────── 输入层 ────────────────────────────────┐
│  18 采集 → 20 清洗 → 19 DAL → 21 特征 → 38 数据库                  │
│  39 语义蒸馏（L3 综合/事件/术语）      9 基本面（FinBERT 情感/评分） │
└───────────────────────────────┬────────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────────┐
│  宏观弹性约束层（传感器 + 约束调制器）                              │
│  40 周期神经网络 → cycle_state / strategy_mapping                   │
│                   │                                                 │
│                   ▼                                                 │
│  43 战略承接推演 → strategic_tier / war_state / position_band / exposure_hint │
│                   │                                                 │
│                   ▼  MacroElasticConstraint v1                      │
├─────────────────────────────────────────────────────────────────────┤
│  42 神经网络协调层（插件总线 / SignalSchema / 参数治理）              │
│      约束分发 + 候选信号汇聚（F1→F2→F3→F5）                          │
├─────────────────────────────────────────────────────────────────────┤
│  子交易系统层（传感器 + 候选信号，全部受宏观弹性约束）                │
│  BCRM2.0 / BDSM / 29 事件驱动 / 未来插件                             │
│      候选信号（已受约束）                                            │
├─────────────────────────────────────────────────────────────────────┤
│  ★ 23 矛盾裁决与最终决策层                                           │
│  双链路：矛盾论链路 + 矛盾 Transformer 链路                          │
│  矛盾识别（共振→冲突裁决→主导性）→ 量变/质变 → 最小阻力路径          │
│  四层闭环：L1 状态 → L2 基因库 → L3 Shadow-RL → L4 Bellman           │
│  三条作用通道：路径评分 / 弹性仓位 / 交叉验证阈值                    │
│      输出：FinalDecisionSignal v1（唯一最终决策）                    │
├─────────────────────────────────────────────────────────────────────┤
│  执行层                                                              │
│  paper：L0 trade-exec MCP（13→16→22→对账）                           │
│  live ：11 域 okx_client 旁路（EXECUTION_AUTHORITY + execution_rights）│
├─────────────────────────────────────────────────────────────────────┤
│  反馈层：成交/PnL/拒单/跳过 → 样本 → 训练/进化 → 反哺 23 / 40 / 43    │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 输入层 → 宏观层

| 上游 | 下游 | 输入内容 | 接口 |
|---|---|---|---|
| 39 语义蒸馏 | 40 | `l3_synthesis.json`、`contradiction_events.jsonl`、`semantic_events.jsonl` | 文件只读；P5 gate 阈值 200/1000 条 |
| 39 / 21 / 9 | 40 P6 | L1-L3 语义 token、FeatureHub 特征、FinBERT 情感 | Encoder 输入（当前门禁锁定） |
| 18 | 40 | FRED（FEDFUNDS/DFII10/T10YIE/T10Y2Y/BAMLH0A0HYM2）、yfinance（DXY/TNX/GC=F/GSPC）、ccxt 8 币 | 数据采集接口 |
| 40 | 43 | `cycle_state`、`fund_flow`、`washout_verdicts` | 只读，7×24h TTL，fail-open |
| 18 / 9 | 43 | F&G 情绪、基本面评分（五维 fundamental 20） | PostgreSQL / SQLite / FinBERT |
| 18/19/21/38 | 23/11/29 | 行情、特征、DAL 查询 | 19-DAL / `l0.data.mcp` |

### 2.3 宏观弹性约束层（40 → 43）

**40 的约束产物（长周期结构约束）**

- `cycle_state.json`：`real_cycle{state, confidence(high/medium/low), current_rate}`、`technical_anchor.assets{sym}{above, distance_pct}`、`sector_transmission{state, regime}`。
- `strategy_mapping.json`：`strategy_suggestion{stance, position_band_pct[min,max], crypto_layer_focus}`、`adjustments_applied`、`risk_guards{freshness(24h 降档/48h stale), event_window(FOMC/CPI ±2 日冻结), clock_degradation, tail_confidence, effective_confidence}`。

**43 的约束产物（更细战略档位）**

- 五维：macro_policy 20 / technical 25 / capital_flow 20 / market_sentiment 15 / fundamental 20。
- 四档：`≥75 attack（仓位 80-100%）` / `60-74 defend（20-50%）` / `50-59 light_defense（0-20%）` / `<50 full_freeze（0%）`。
- `war_state`：FREEZE → 连续 3 日总分 ≥60 → ACTIVE；<58 回冻；三类资产隔离。
- 否决：`dao<40` 一票冻结；`fa<40` 不开新仓。
- 输出：`strategic_extension`（`tier / position_band / war_state / exposure_hint`）。

**合并规则（MacroElasticConstraint）**：

- 40 给出**外层仓位带**与风控守卫；43 在该带内**收窄**为战略档位。
- 冲突时取**更保守**的一侧（min 仓位上限、max 风控强度）。
- `strategy_mapping.position_band` 与 `strategic_extension.position_band` 的交集为最终可用仓位带。
- 13 风控始终可进一步收紧，不得被放宽。
- **宏观层是约束调制器，不是决策层**：它不直接输出交易信号，只调制 23 的评分、仓位与阈值。

### 2.4 协调层（42）

- **不是 MCP 壳**：42 是 L1 内部 JSON 文件总线（`runtime/bus_state.json`），L1 MCP 是它之上的协议面。
- **插件注册**：`registry.yaml` 声明 `name / publisher / publish / subscribe / horizon / enabled / mode`。
- **适配器**：每个源一个 `adapters/<source>_adapter.py`，只读源状态 → 映射 SignalSchema → `SignalBus.publish()` → `flush()`。
- **过滤链**：F1 新鲜度 → F2 置信度（<0.30 降级 neutral）→ F3 冲突检测（同标的多源反向打 `conflict_flags`）→ F5 归一化（附 `shadow`）。
- **约束通道**：`macro_constraint`（40+43 合并后的约束）与 `elastic_params`（6 参数）；子交易系统通过订阅获取。
- **输入/输出边界**：42 只做输入汇聚；23 输出不回写 42 参与裁决。如需观测，可只读镜像到 output channel（`source=23-evolution`），不进入候选池。
- **红线**：不下单、不写回子系统状态、fail-open、13 风控优先。

### 2.5 子交易系统层（传感器 + 候选信号）

| 子系统 | 当前状态 | 目标约束方式 |
|---|---|---|
| 11-BCRM2.0 | 战略层 `enable_five_domain=False`、`shadow_mode=True`；不读 40/43/42 | 增加只读约束入口；`position_factor` / `sl_tighten` 受档位钳制；战术级信号上 42 |
| 11-BDSM | `enable_bdsm_war_state_check` 默认 False，独立验证 | 打开校验，改读 43/42 的 `war_state`；`cap_multiplier` 受约束 |
| 29 事件驱动 | 独立影子；`event_dominance` 有 `filter_level` 骨架 | 发布时叠加宏观档位；事件强度 × 约束乘数；四档否决 |
| 未来插件 | — | 按 §3.4 插件契约接入，必须订阅 `macro_constraint` |

> **DEC-01/02/06/07/08/09/10 决议（2026-11-06）**：
> - 11 的 bcrm / bdsm / strategy / event_arbitrage / washout 五个子池**全部作为信号源**，经 42（**状态文件 + 只读适配器**）透传给 23；11 只保留 live 执行网关。
> - 23 的唯一决策权威覆盖**全标的**；调度为**全标的 1h、高风险标的 300s**。
> - **A0-A9 保留为信号源，执行只认 23**。
> - 23 不可用时，**仅 11 子池的离场/平仓模块接管，禁止新开仓**。
> - 23 双重角色中立性：**自票上限 + 独立矛盾证据复核 + 审计**。

> 子交易系统是“传感器 + 候选信号源”，不是最终决策者。它们的量变（力量累积、排序变化）由 23 转化为质变与最终决策。

### 2.6 矛盾裁决与最终决策层（23）

#### 2.6.1 双链路

| 链路 | 作用 | 关键实现 |
|---|---|---|
| **矛盾论链路** | 识别主要矛盾/次要矛盾、矛盾迁移 | `contradiction_identifier.py`：共振 → 4 维冲突裁决 → Wyckoff/Minervini 主导性 |
| **矛盾 Transformer 链路** | 表示当前主矛盾的力量与维度排名 | `cross_attention.py` + `neural_sde_model.py`：Q=价格签名，K/V=36 因子，8 head（目标配置）维度对齐，context 注入 SDE drift |
| **交叉验证（现状）** | 过去/当前主矛盾冲突判定 | `cross_validation_gate.py`：Granger（过去主矛盾）vs **矛盾论识别器**（当前主矛盾，A_dim 取自 `primary_contradiction.dimension`） |
| **交叉验证（目标）** | 让 attention 权重参与交叉验证 | 接入 `AttentionAggregator`（模块已实现、生产未接线），形成 Granger vs Attention |

> **现状说明**：`evolution_pipeline.py:1256-1258` 的 A_dim 来自矛盾论识别器，不是 attention；`AttentionAggregator` 只在测试与 `C_DIM_TO_3` 映射中被引用，生产管线未调用。文档里的“Granger vs Attention”是目标设计。

> **事件驱动主矛盾检测器**（fomc/inflation/credit/ai_capex）已实现，但全仓无生产调用点；`enable_primary_contradiction_detector` 未注册进 `AGI_SWITCHES`（默认 False）。当前属“模块存在、未接线”。

**矛盾论链路三步法**：

1. **共振检测**：6 条路径（bdsm / bcrm / strategic / deep_reasoning / l2_gene / synthesized）同向度 ≥60%。
2. **冲突裁决**（resonance < 0.6）：4 维评分——力量对比 0.40 / 时间紧迫性 0.15 / 证据一致性 0.25 / 市场影响权重 0.20（W6 学习权重可替换默认值）。
3. **主导性评估**：Wyckoff Cause & Effect + Effort vs Result；Minervini 趋势模板 + VCP 收缩比。

输出：`{dimension, timeframe, direction, strength, confidence, cause_score, effort_result, continuation_score}`。

#### 2.6.2 矛盾维度体系（两套编号并存）

**路径来源映射（C 编号）**：

| 维度 | 含义 | 路径来源 | 市场影响权重 |
|---|---|---|---|
| C1 | 资金面 | bdsm | 0.25 |
| C2 | 情绪面 | trend_following / grid_trading | 0.15 |
| C3 | 技术面 | bcrm | 0.20 |
| C4 | 宏观 | strategic | 0.30 |
| C6 | 时序/估值 | deep_reasoning | 0.10 |
| C7 | 隐性/叙事 | synthesized | 0.10 |
| C8 | 宏观交叉 | l2_gene | 0.10 |

> 权重按“路径来源”定义；`grid_trading` 在维度映射中但不在权重表（默认 0.05）；无 C5 维度。

**真实市场维度（D 编号，重建目标）**：

| 维度 | 含义 | 输入 | 状态 |
|---|---|---|---|
| D1 | 宏观利率 | CPI surprise + fedwatch | 已设计/待重建 |
| D2 | 资金流 | 资金费率 / 多空比 / OI / 清算 | 部分数据待采集 |
| D3 | 技术 | 路径共振传入 | 已有 |
| D4 | 情绪 | F&G | 已有 |
| 扩展 | C6 估值 / C7 叙事 / C8 VIX | 市值 z、稳定币 7 日变化、VIX | 设计态 |

> 当前 `contradiction_identifier.py` 的 C 编号本质是“路径来源映射”；D 编号是真实市场矛盾维度。49 要求在 P2 完成 C→D 重建，避免“维度=路径”的语义失真。
>
> **维度力量 v2 的实际状态**：`enable_dimension_force_v2=True`；评估块打印日志，但结果经 `_last_dimension_forces` 传入 `identify()`，由 T5 对 `strength` 做 [0.7,1.3] 调制——**已参与主矛盾裁决**。`agi_config.py:88` 与 `evolution_pipeline.py:1083-1084` 的“影子期只记录日志”注释已过时。
> z-score 窗口：D1 24 月 / D2 30 天 / D4 90 天；只读 19-DAL，percentile→neutral 降级。
> **拆分说明**：D 维度评估器（`dimension_force_evaluator`）已实现并经 T5 参与裁决；C→D identifier 重建（把 `contradiction_identifier` 的 C 编号改为 D 编号）尚未完成，两者不是同一件事。

#### 2.6.3 矛盾 Transformer

```text
Q = 价格路径签名 log_sig_t
K,V = 36 个外生因子（10 个基本面模块，FactorEncoder）
factor_head_mask (8 × 36)：每个 head 只看所属矛盾维度
scores = Q·Kᵀ/√d + mask
weights = softmax(scores) × head_multipliers(cycle_phase)
context = Σ weights · V
drift = net([S_t, time, context, regime, transition])   # NeuralSDE
```

- **8 个 head 是目标/checkpoint 配置** ↔ C1/C2/C3/C4/C6/C7/C8/news；attention weights = 该维度因子影响力排名。代码默认 `n_heads=4 / cross_attn_dim=32`，实际 head 数由 checkpoint 决定；8 head/64 dim 是消融建议/目标配置，不是部署默认。
- **impact_multiplier**：8 维 × **9 个周期阶段键**（neutral + expectation×4 + event + repricing×3），CausalEngine ATE 分桶校准。
- **当前模型**：NeuralSDE 已训练（36 因子；训练报告 `final_loss=0.0119`、`best_val=0.0105`，文档中的 0.0136 已落后）；checkpoint 序列化 `factor_head_mask`；`cross_attn_dim=64` 消融 MAE 改善 69.8%（建议配置）。
- **AttentionAggregator**：模块已实现，但生产管线未调用；当前仅 `cross_validation_gate` 使用其 `C_DIM_TO_3/get_factor_dimensions` 映射。接入是 P2 工作。
- **输出**：context 注入 SDE drift；不直接产生交易信号，而是主矛盾的力量表示。

#### 2.6.4 量变 → 质变

**量变**：矛盾力量数值变化，排序不变（`contradiction_shift_accumulator` 记录矩阵快照）。

**质变**（四条件全满足）：

1. `persistence=14` 个快照内、首快照后连续 **13 次**评估满足“新矛盾力量 > 旧矛盾”；
2. `gap > 0.15`；
3. 方向相反；
4. `StructuralBreakDetector` 至少一项断裂（MS-GARCH 波动率 / 相关性 Welch t-test / Hurst 形态）。

质变 → `shift={shifted_from, shifted_to, new_direction, structural_break_type, consecutive_count}` → HJB `shift_points` 路径切换 → `CrossValidationGate.quality_change` → `FTCEvolutionBridge.run_gene_innovation` 基因创新（快照 + 三级审核门禁）。

> **阈值现状**：`contradiction_shift_accumulator` 的结构断裂阈值为 **0.4**（v1.2；原 1.0 在 statsmodels fallback 下不可触发）。另 `CrossValidationGate` 的质变条件是 `divergence_count ≥ persistence(5)` 且 `break_score ≥ threshold`；pipeline 实际传 **1.0**（类默认 0.4 被覆盖），该条件大概率不可触发。断裂检测实际使用 Welch t-test；CUSUM 仅为命名与依赖守卫。

#### 2.6.5 最小阻力路径

- **阻力向量**：6 组件（筹码 / 清算 / 趋势 / 资金费率 / 订单簿 / OI）+ 矛盾调制（对齐 −30% / 逆向 +50%）。
- **Level0 d\***：`d* = argmin dᵀ g d`。
- **路径求解三级降级**：HJB PDE（权重 70%，W2 已启用；docstring 的 30% 已过期）→ 变分法 → 路径积分（≥1000 条蒙特卡洛；`S = α·成本 + β·风险 + γ·不确定性`）。
- **输出**：`d_star`、`ri`、`optimal_path`、`hjb_value`。

> **路径选择现状**：`_select_optimal_path` 最终仍是 `scored.sort(); best=scored[0]` 的纯 argmax；且外生度量 `get_primary_contradiction` 可整体替换主矛盾（“外生度量优先”）。这与“矛盾间对抗识别主导者”的目标仍有差距（文档评估约 30%）。

#### 2.6.6 四层闭环

| 层 | 内容 | 输入 → 输出 |
|---|---|---|
| **L1 状态空间** | ResistanceVector + DAL 微观结构（funding/OI）+ 子系统调制 | 市场数据 → 5 维 R 向量 |
| **L2 策略知识** | 基因库 `top_combinations_by_ess`、路径库、FTC 思维链 | 历史/知识 → 候选路径 |
| **L3 Shadow-RL** | state=R 向量、action、reward（平仓注入真实 PnL） | 探索 → `shadow_rl_samples.jsonl` |
| **L4 最优目标** | Bellman `td_update` → `V(symbol)=l4_v`；HJB 最优路径 | 反馈 → 最优目标 |

#### 2.6.7 最终输出（FinalDecisionSignal v1）

23 输出不是简单聚合，而是：

```text
action / strategic_tier(43) / position_tier(23) / position_mult / regime / d_star / ri / l4_v
+ primary_contradiction{dimension, direction, strength, confidence, cause_score, effort_result, continuation_score,
                        dimension_force_mod, causal_ate, gate_state, meta_cognition, position_multiplier}
+ contradiction_shift{shifted_from, shifted_to, new_direction, structural_break_type, consecutive_count}
+ elastic_result{position_mult, t_max, deviation, constraint_active, aligned, rebound_risk}
+ cross_validation{g_dim, a_dim, consistent, confidence_mult, divergence_count, quality_change}
+ path{optimal_path, hjb_value, path_score, resistance_vector}
+ constraint_id / constraint_applied_at
```

### 2.7 执行层

- **paper（现状）**：`23 信号 → 前置过滤(中性/过期/幂等) → 执行权 → 行情+定容 → 13 风控(fail-closed) → paper 下单 → 落账`。RiskCheckPort 已真实桥接 13；**16 定容与 22 执行引擎尚未接线**，定容由 13 的 `RiskEngine.calculate_position` 或 `risk_exposure_hint × balance` 兜底；OrderPort 为自包含 `OKXPaperLedger`。
- **paper（目标）**：接入 16 `capital_allocator` 与 22 `tee_core`（P3）。
- **live**：`23 信号 → 11 polling_trader（EXECUTION_AUTHORITY）→ okx_client 直连`；不经 MCP。
- **标的级互斥**：`47-MCP管理系统/registry/execution_rights.json` 声明 `paper / live:11-bypass / disabled`；同一标的同一时刻单出口。

### 2.8 反馈层

- L0 trade-exec 产出执行样本：`on_order_filled / on_risk_rejected / on_signal_skipped` → `ml_data/samples.jsonl`。
- `execution_sample_loader` → `execution_policy_training.jsonl` → `executor_agent` 策略。
- 23 的 Shadow-RL / 基因库 / Bellman 反馈；真实平仓 PnL 经 `trade_settlement_bridge` 回注 L3。
- 反馈可反哺 40/43 的约束校准（建议制，须经 P5/P6 或战略门禁采纳，不得直接改模型权重）。

### 2.9 L1 闭环与 L2 观察面

```text
【L1 内部闭环】
输入层 → 40 → 43 → 42（MacroElasticConstraint）
      → BCRM2 / BDSM / 29（受约束候选信号）
      → 23 双链路矛盾裁决 + 最小阻力路径 → FinalDecisionSignal
      → L0 paper / 11 live
      → 成交/PnL/拒单反馈 → 样本 → 训练/进化 → 反哺 23 / 40 / 43

【L2 观察面（闭环外）】
L2 ──只读 tools/call──▶ l1.trading.mcp ──读──▶ 23/42/40/43 状态、L0 持仓/余额/事前风控
          ✗ 不触发信号   ✗ 不触发执行   ✗ 不参与训练
```

---

## §3 协议契约

### 3.1 MacroElasticConstraint v1（宏观弹性约束）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `constraint_id` | string | ✅ | 确定性幂等键（建议 `sha1(source|ts|version)`） |
| `source` | enum | ✅ | `40-cycle` / `43-strategic` / `merged`（42 合并后） |
| `ts` | ISO8601 | ✅ | 生成时间 |
| `expires_at` | ISO8601 | ✅ | 过期时间；消费方必须校验 |
| `mode` | enum | ✅ | `shadow` / `live`；shadow 只观测不裁决 |
| `confidence` | number [0,1] | ✅ | 约束置信度 |
| `regime` | string | ⬜ | 40 周期状态（hiking/cutting/plateau；美林象限） |
| `stance` | string | ⬜ | 40 策略建议 stance |
| `strategic_tier` | enum | ⬜ | 43 四档：`attack` / `defend` / `light_defense` / `full_freeze`（代码值；与 23 的 `position_tier` 区分） |
| `war_state` | enum | ⬜ | `ACTIVE` / `FREEZE` 等 |
| `direction_bias` | enum | ⬜ | `long` / `short` / `neutral` |
| `position_band_pct` | [number, number] | ⬜ | 最终可用仓位带（40 外层 ∩ 43 档位） |
| `position_cap_pct` | number [0,1] | ⬜ | 单策略/单标的仓位上限 |
| `risk_budget_multiplier` | number [0,1] | ⬜ | 风险预算乘数 |
| `strategy_overrides` | object | ⬜ | 按策略类型的差异化乘数/否决 |
| `elastic_params` | object | ⬜ | 42 六参数：`long_threshold_multiplier` / `position_size_factor` / `long_short_ratio_cap` / `weight_adjust_limit` / `cooldown_period_hours` / `risk_budget_ratio` |
| `risk_guards` | object | ⬜ | `freshness_stale_hours` / `event_window_freeze` / `clock_degradation` / `effective_confidence` |
| `component_constraints` | array | ⬜ | 40 `strategy_mapping` + 43 `strategic_extension` 摘要 |
| `payload` | object | ⬜ | 原始字段透传与审计 |

> 说明：`43-strategic` 是**约束来源枚举**；43 发布的 SignalSchema `source` 固定为 `strategic_extension`，两者不是同一字段。

**合并与优先级**：

1. 40 外层带 → 43 档位收窄 → 42 合并 → 子交易系统应用 → 23 复核。
2. 冲突取更保守值（`min(position_cap)`、`max(风控强度)`）。
3. `mode=shadow` 只进入矛盾识别与审计；`mode=live` 才可生效。
4. 13 风控可继续收紧；任何约束不得放宽 13。

### 3.2 SignalSchema v1（候选信号）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `signal_id` | string | ✅ | 确定性幂等键 |
| `source` | string | ✅ | 见下方 Canonical source registry |
| `mode` | enum | ✅ | `live` / `paper` / `shadow`；信号模式（与 43/42 的 constraint `mode`、执行 `mode` 区分） |
| `ts` | ISO8601 | ✅ | 生成时间 |
| `symbol` | string | ✅ | OKX instId；40 宏观信号用 `MACRO` |
| `direction` | enum | ✅ | `long` / `short` / `neutral` |
| `confidence` | number [0,1] | ✅ | 置信度 |
| `horizon` | enum | ✅ | `minutes` / `hours` / `days` / `weeks` |
| `risk_exposure_hint` | number [0,1] | ✅ | 建议风险暴露 |
| `expires_at` | ISO8601 | ✅ | 过期时间 |
| `shadow` | boolean | ⬜ | 兼容字段；`true` 等价 `mode=shadow`，新代码用 `mode` |
| `constraint_id` | string | ⬜ | 已应用的宏观约束 ID |
| `constraint_applied_at` | ISO8601 | ⬜ | 约束应用时间（防重复） |
| `payload` | object | ⬜ | 子系统特有字段 |

**Canonical source registry（唯一枚举）**：

| source | 含义 | 备注 |
|---|---|---|
| `11-bcrm` | BCRM2.0 战术/战略 | 11 内部战略层与 43 是不同源，勿混用 |
| `bdsm` | BDSM 快照 | 每日 23:50；历史命名，迁移期可双写 `11-bdsm` |
| `11-strategy` | 11 战略子池 | DEC-01 信号源 |
| `11-event-arbitrage` | 11 事件套利子池 | DEC-01 信号源 |
| `11-washout` | 11 洗盘子池 | DEC-01 信号源 |
| `29-event` | 事件驱动 | 由 23 写状态、42 转发 |
| `40-cycle` | 40 周期信号 | `symbol=MACRO` |
| `strategic_extension` | 43 战略承接 | 文档别名 `43-strategic-extension` **废弃** |
| `23-contradiction` | 23 矛盾识别 | 仅内部/观测 |
| `23-evolution` | 23 最终决策 | 唯一执行出口 |
| `11-strategic` | 11 五域战略状态 | 仅 SubSystemBridge 内部使用，不与 43 混用 |

> 代码统一使用 `strategic_extension`（42 适配器与 23 `data_pipeline` 均按此匹配）。

### 3.3 FinalDecisionSignal v1（23 最终决策）

在 SignalSchema v1 基础上，`source` 固定 `23-evolution`，`payload` 必须包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| `action` | enum | `long` / `short` / `light_long` / `light_short` / `WAIT` |
| `position_tier` | enum | `trend` / `standard` / `probe` / `none`（23 仓位档；与 43 的 `strategic_tier` 区分） |
| `position_mult` | number | 现状 `base × regime_mult`；目标加 `macro_mult` |
| `d_star` / `ri` / `l4_v` | number | Level0 / 反馈 / Bellman |
| `regime` | string | 市场状态 |
| `primary_contradiction` | object | `{dimension, direction, strength, confidence, cause_score, effort_result, continuation_score, dimension_force_mod, causal_ate, gate_state, meta_cognition, position_multiplier}` |
| `contradiction_shift` | object | `{shifted_from, shifted_to, new_direction, structural_break_type, consecutive_count}` |
| `elastic_result` | object | `{position_mult, t_max, deviation, constraint_active, aligned, rebound_risk}`；实际应用点是 `ri = ri × mult`（经 tier 间接影响仓位），不是直接乘到最终 `position_mult` |
| `cross_validation` | object | `{g_dim, a_dim, consistent, confidence_mult, divergence_count, quality_change}` |
| `path` | object | `{optimal_path, hjb_value, path_score, resistance_vector}` |
| `constraint_id` / `constraint_applied_at` | string | 已应用宏观约束与时间 |

### 3.4 42 插件注册与约束通道

**注册声明（`registry.yaml`）**

```yaml
- name: <plugin_id>
  publisher: <module-or-path>
  publish: [signal]
  subscribe: [macro_constraint, elastic_params]
  horizon: hours|days|weeks          # 必填
  enabled: true
  adapter: adapters/<plugin_id>_adapter.py
  mode: shadow|live
```

**适配器五步**：

1. 只读源状态文件（fail-open）。
2. 读取 42 最新 `MacroElasticConstraint`（fail-open 回退保守默认）。
3. 应用约束：`confidence × risk_budget_multiplier`、`risk_exposure_hint ≤ position_cap_pct`、方向冲突降级/否决。
4. 映射 SignalSchema v1，写入 `constraint_id` / `constraint_applied_at`。
5. `SignalBus.publish()` → `flush()`。

**红线**：不下单、不写回子系统状态、fail-open、13 风控优先。

### 3.5 子交易系统约束消费契约

| 系统 | 必须消费的字段 | 应用点 | 当前缺口 |
|---|---|---|---|
| BCRM2.0 | `strategic_tier` / `war_state` / `position_cap_pct` / `direction_bias` | `position_factor` / `sl_tighten` / 战术信号发布 | 无约束入口；需新增只读适配 |
| BDSM | `war_state` / `position_cap_pct` / `cap_multiplier` | `direction_constraint` / `cap_multiplier` / 每日快照 | `enable_bdsm_war_state_check` 默认 False |
| 29 事件驱动 | `strategic_tier` / `risk_budget_multiplier` / `event_window_freeze` | `EventSignal.strength` × 乘数；`filter_level` 否决 | 未接约束；影子态 |
| 23 | 全部字段（作为最终复核） | 三条作用通道 + 最小阻力路径 | 宏观约束注入但零消费 |
| 未来插件 | `macro_constraint` / `elastic_params` | 发布前应用 | 按 §3.4 接入 |

### 3.6 23 输出契约

- 输出文件（目标）：`23-四层闭环自进化交易架构/runtime/signals/23_signal_state.json`。
- 迁移期回退：`11-易经推理系统/data/event_driven_state.json`。
- `source="23-evolution"`；内容为 FinalDecisionSignal v1。
- 进程内返回 dict 与文件字段同名。
- 输出前只做**约束复核**（更保守值），不重复相乘；保留 `constraint_id` / `constraint_applied_at`。

### 3.7 L0 trade-exec 调用契约

见 [SPEC-L0-TRADE-EXEC-MCP-v0.1](../47-MCP管理系统/docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md)。

- 工具：`place_order` / `cancel_order` / `ingest_signal`（写，需 Mandate）；`get_positions` / `get_balance` / `pre_trade_check` / `get_account_mode` / `reconcile` / `read_signals`（读）。
- 现状：9 工具（3 写 + 6 读）；`requires_mandate` 由注册表/宿主强制，server 代码本身不校验。
- paper-only：无 OKX 凭证/签名；execution_rights 三态（paper / live:11-bypass / disabled）拒绝非 paper。
- 前置过滤顺序：中性/过期/幂等 → 执行权 → 行情+定容 → 风控 → paper 下单 → 落账。
- **13/16/22 现状（远端 `b4e661b4` 核验）**：13 已通过 `RiskBridge` 接线（`pre_trade_check` + `calculate_position`/PositionSizer）；16 `capital_allocator` **未 import**；22 `tee_core` **未 import**，OrderPort 为自包含 `OKXPaperLedger`。详见 §12.6。
- **6-TRADING 旁路**：`dream_trade_exec.py` 直连 OKX `/trade/order`；`trade_exec_api.py` 独立 paper/live API；需 R-L0-03 收口。
- **23 唯一出口闸门（目标，P2/P4）**：L0 `ingest_signal` 只接受 `source=23-evolution`（或经 L1 编排校验的 inline 信号）；`source=42` 仅用于只读观测，执行侧必须拒绝。`read_signals` 默认源改为 `["23"]`，42 原始信号只用于分析。
- `forward_signal` 只允许 `source=23-evolution` 且 `mode=live` 的信号进入 L0。
- 执行侧 `fail-closed`；信号侧 `fail-open`。

### 3.8 L1 交易层 MCP 工具契约（`l1.trading.mcp`，10 工具）

| # | 工具 | 读写 | 调用方 | Mandate | 作用 |
|---|---|---|---|---|---|
| 1 | `get_signal_state` | read | L2 Worker / 编排侧 | 否 | 读 23 最终决策 |
| 2 | `get_bus_state` | read | L2 Worker / 编排侧 | 否 | 读 42 总线 |
| 3 | `get_constraint_state` | read | L2 Worker / 编排侧 | 否 | 读最新 MacroElasticConstraint |
| 4 | `get_cycle_state` | read | L2 Worker / 编排侧 | 否 | 读 40 周期状态 |
| 5 | `get_strategic_extension` | read | L2 Worker / 编排侧 | 否 | 读 43 战略承接 |
| 6 | `get_decision_diagnostics` | read | L2 Worker / 编排侧 | 否 | 读 23 主矛盾/质变/交叉验证/路径诊断 |
| 7 | `get_training_status` | read | L2 Worker / 编排侧 | 否 | 训练样本/策略行/版本状态 |
| 8 | `get_positions` | read | L2 Worker / 编排侧 | 否 | 代理 L0 `get_positions` |
| 9 | `get_balance` | read | L2 Worker / 编排侧 | 否 | 代理 L0 `get_balance` |
| 10 | `forward_signal` | write | **L1 闭环内部（非 L2）** | ✅ | 23 信号 → L0 `ingest_signal`（paper） |

> **设计态**：`mcp_shells/l1_trading/` 当前不存在；本表是评审通过后落地的工具契约，不是已实现接口。
>
> **调用方枚举**：`L2 Worker`（只读）、`L2 编排`（只读 + 受 Mandate 写）、`L1 内部编排`（写）。读工具三类均可；写工具仅 `L1 内部编排`。
>
> 训练触发 `trigger_training` 属于 L1 闭环内部控制面，不进入 L2 工具面。

### 3.9 UpperLayerContext v1（注入 23 的上层信息）

| 字段 | 来源 | 频率 | TTL | mode | 消费点 |
|---|---|---|---|---|---|
| `macro_regime` | 40 `real_cycle.state + confidence` | 小时 | 24h | shadow→live | ② R 向量 / ③ 主矛盾先验 |
| `strategic_tier` / `war_state` | 43 `strategic_extension`（统一源） | 小时 | 24h | shadow→live | ① 前置否决 / ② 统一温度 |
| `position_band_pct` | 40 `strategy_mapping` ∩ 43 档位 | 小时 | 24h | shadow→live | ⑦ `macro_mult` |
| `position_cap_pct` / `cap_multiplier` | 43 / 16 | 小时/实时 | 24h | live | ⑦ `macro_mult` / ⑥ 阈值 |
| `risk_budget_multiplier` | 42 `elastic_params` | 事件 | 24h | live | ⑤ 路径评分 / ⑥ 阈值 |
| `capital_allocation` | 16（equity/available/per-symbol cap） | 实时 | — | live | ① 否决 / ⑥ 阈值 |
| `risk_gate_status` | 13（engine 可用/熔断/黑名单） | 实时 | — | live | ① 否决 |
| `semantic_context` | 39 `l3_synthesis` / 矛盾事件摘要 | 6h/日 | 48h | shadow 先行 | ③ 主矛盾先验 |
| `fundamental_context` | 9 FinBERT / 五维分 | 日 | 72h | shadow 先行 | ③ 主矛盾先验 |
| `execution_feedback` | L0 fills/PnL、11 平仓 | 事件 | — | live | ⑨ Bellman reward |
| 公共字段 | `constraint_id / ts / expires_at / mode / component_sources` | — | — | — | 42 合并 |

**注入点与防重复**：

| # | 环节 | 字段 | 作用 | 防双计 |
|---|---|---|---|---|
| ① | 前置过滤 | `strategic_tier=full_freeze` / `war_state=FREEZE` / `risk_gate_status` | 否决新开仓 | 纯 veto |
| ② | R 向量调制 | 统一 `war_state` 温度 | 替换 11-only 调制 | 单一 war_state 源 |
| ③ | 主矛盾先验 | `macro_regime` / `semantic_context` / `fundamental_context` | `identify()` 的 `weight_factor` 先验 | 只调权重，不调 strength |
| ④ | Transformer | `macro_regime`（已在 SDE drift） | 保持 | 已有，不重复 |
| ⑤ | 路径评分 | `direction_bias` 对齐项 | 独立 `macro_alignment` 项 | 与矛盾对齐并列，不叠加 |
| ⑥ | tier 阈值 | `risk_gate_status` / `capital_allocation` | 阈值上浮/降档 | 只动阈值 |
| ⑦ | position_mult | `position_band_pct` / `position_cap_pct` | 唯一 `macro_mult = base×regime×macro` | elastic 仍只在 ri |
| ⑧ | 交叉验证 | 宏观 vs 微观 | 第三验证源（M 维） | 只影响 `confidence_mult`，不乘仓位 |
| ⑨ | Bellman reward | `execution_feedback.realized_pnl` | 替换 `quality_score−0.5` | 单一 reward 源 |

**优先级**：`13 风控(fail-closed) > execution_rights > 23 最终裁决（在 band∩cap∩budget 包络内）> 43 strategic_tier/40 band(live) > 统一 war_state > 微观候选信号`。

**mode=shadow**：只进入 ③ 先验与审计日志，不进入 ①⑥⑦；晋升 live 需 paper 对比 ≥2 周 + 人工评审。

**DEC-07 调度**：23 全标的 1h；高风险标的 300s；记录各标的 `age`，超 TTL 降级。
**DEC-10 中立性**：23 自身候选设**自票上限**，须独立矛盾证据复核并审计。
**DEC-15 诊断脱敏**：L1 MCP 只暴露摘要 + 置信度；原始权重/张量不下发。

> 现状：23 唯一真正消费的上层信息是 11 `war_state`（SubSystemBridge）；40/43 的 `macro_constraint` / `strategic_extension` 注入但零消费。最小接线顺序见 §11.4。

---

## §4 关键机制

### 4.1 约束传导链（一次信号的完整路径）

```text
输入层（39/9/数据）
  → 40 cycle_state + strategy_mapping
  → 43 strategic_extension（tier/war_state/position_band）
  → 42 合并为 MacroElasticConstraint（mode=shadow|live）
  → 子交易系统适配器：应用约束 → 候选 SignalSchema
  → 23 双链路矛盾识别 + 矛盾 Transformer + 最小阻力路径
  → FinalDecisionSignal v1（唯一输出）
  → L0 paper / 11 live
  → 成交/PnL/拒单 → 样本 → 训练/进化
  → 反哺 23 / 40 / 43
```

### 4.2 三条作用通道（23 的核心机制）

| 通道 | 机制 | 当前状态 | 目标 |
|---|---|---|---|
| **① 路径评分调制** | 主矛盾对齐 ×(1+0.2×S)；逆向 ×(1−0.3×S) | 已落地（实测 strength 0.315-0.382） | 叠加宏观约束对齐项 |
| **② 弹性乘数（作用于 ri）** | `elastic_position_mult = floor + (1−floor)×sigmoid(steepness×(1−Δp/T_max))`，`steepness=3`；`T_max = base×S_p/(S_p+S_m)`；`ri = ri × elastic_position_mult`；`combined_mult = EG3L × WinProb × BTCλ × Elastic` | 已接线（`enable_elastic_constraint=True`） | 增加 `Macro_multiplier` 因子；最终 `position_mult` 目前仍只有 `base×regime_mult` |
| **③ 交叉验证乘数 + 阈值** | 一致 ×1.15；分歧 ×0.9；入场阈值 ×`1/conf_mult` | `enable_cross_validation_gate=True`（2026-10-07 激活） | 加入宏观 vs 微观第三验证源 |

> 宏观弹性约束应通过这三条通道生效，而不是另造一套乘数语义。当前 40/43 约束在 engines/core/pipeline 中**零消费**，这是 P2 的核心接线工作。

> **两个“弹性”要区分**：`MacroElasticConstraint`（40/43）是外部宏观约束；`elastic_constraint_resolver`（`position_mult = floor + (1−floor)×sigmoid(steepness×(1−Δp/T_max))`）是 23 内部主/次矛盾弹簧模型，实际乘在 `ri` 上（经 tier 间接影响仓位），不是直接乘最终 `position_mult`。二者最终在 `combined_mult` 中相乘，不得混用同一字段。

**唯一乘数合成顺序（目标）**：

1. `13 position_modifier`（最终钳位，不可放宽）
2. `execution_rights`（标的级单出口）
3. `macro_mult = position_cap_pct × risk_budget_multiplier`（全局唯一一次）
4. `position_mult = base × regime_mult × macro_mult`
5. `11 war_state`：仅在 ② R 向量调制中使用，不再单独乘仓位
6. `23 elastic_position_mult`：只作用于 `ri`，经 `position_tier` 间接影响仓位
7. 11 只做风控钳位，不重复缩放

> 11 的 `_combined_mult = EG3L×WinProb×BTCλ×Elastic` 是 11 内部风控门（F1 试错通道），不是第二个 `position_mult`；目标由 23 统一输出 `position_mult`，11 仅钳位。

> **DEC-12 路径选择**：`DominanceResolver` 采用**成对支配 + 可解释矩阵**；argmax 仅作 shadow 回退。
> **DEC-16 D2 数据**：统一接 **19-DAL**（OI/清算）；覆盖率 ≥90% 才进 live。

### 4.3 量变 → 质变的四个条件

1. `persistence=14` 个快照内、首快照后连续 **13 次**评估满足“新矛盾力量 > 旧矛盾”；
2. `gap > 0.15`；
3. 方向相反；
4. `StructuralBreakDetector` 至少一项断裂。

仅排序变化 = 量变；四条件全满足 = 质变。质变触发：HJB 路径切换 + `quality_change` + 基因创新（三级审核门禁）。

> 另一个质变判定通道 `CrossValidationGate`：`divergence_count ≥ persistence(5)` 且 `break_score ≥ 1.0`（pipeline 实际值；类默认 0.4 被覆盖）——阈值 1.0 下大概率不可触发，P2 修复。断裂检测实际为 Welch t-test；CUSUM 仅为命名。

### 4.4 冲突、TTL 与降级

- **TTL 表（现状 → 目标）**：

| 源 | 现状 | 目标 |
|---|---|---|
| 40 `cycle_state` → 23 | 72h | 24h 硬过期（72h 内降档） |
| 42 `bus_state` | 24h | 24h + `expires_at` |
| 43 `strategic_extension` | 7 天 | 24h（7×24h 上限） |
| 40 `strategy_mapping` | 无消费 | 24h |

消费方只以 `expires_at` 为准；禁止各自实现不同 TTL（§6）。
- **shadow → live**：`mode=shadow` 仅观测/矛盾识别；晋升 live 需满足 paper 对比 ≥2 周、命中率/回撤达标、人工评审。
- **fail-open**：约束缺失时回退保守默认；执行侧 13 风控仍 fail-closed。
- **冲突**：40 与 43 冲突取更保守；子策略与约束冲突按 `strategy_overrides` 降级或否决；宏观与微观冲突由 23 双链路交叉验证裁决。

### 4.5 新策略插件接入流程

1. 在 `42/registry.yaml` 声明 `name/publisher/publish/subscribe/horizon/enabled/mode`。
2. 在 `42/adapters/` 新增适配器（五步，见 §3.4）。
3. 明确该策略的约束消费点（§3.5）与 `strategy_overrides`。
4. 以 `mode=shadow` 先上总线；通过 paper 对比后转 `live`。
5. 不得新增直连交易所路径；执行仍走 L0 / 11 旁路。

### 4.6 23 双角色与防重复

- **策略参与者**：23 自身的自进化候选信号受约束。
- **最终仲裁者**：汇总所有候选信号 + 宏观约束 + 矛盾链，输出唯一 FinalDecisionSignal。
- **防重复**：信号携带 `constraint_id` / `constraint_applied_at`；23 只复核不重复相乘。
- **中立性（DEC-10）**：23 自身候选设**自票上限**，不得单独决定主导者；须独立矛盾证据复核并审计。
- **降级（DEC-06）**：23 不可用时，仅 11 子池的离场/平仓模块接管，**禁止新开仓**。

### 4.7 shadow → live 晋升

| 约束源 | 当前 | 晋升条件 |
|---|---|---|
| 40 `strategy_mapping` | 已产出，未被消费 | 接入 42 约束通道；paper 对比 ≥2 周 |
| 43 `strategic_extension` | shadow=true | paper 对比 ≥2 周；命中率/回撤达标；人工评审 |
| 42 `elastic_params` | v1.0 默认、无消费者 | 订阅面接线；参数非默认；灰度放量 |
| 23 高阶仲裁 | `enable_cross_validation_gate=True`，但部分维度/结构断裂参数待修 | v0.7 五个 P0 前置闭环；paper 验证 |

---

## §5 训练、反馈与信号生产（L1 闭环）

### 5.1 闭环结构

```text
23 FinalDecisionSignal → L0 paper / 11 live 执行
        → 成交/PnL/拒单/跳过反馈
        → 样本落盘 → executor_agent / 23 L3-L4 训练进化
        → 反哺 23；约束校准建议反哺 40/43（建议制，需门禁采纳）
```

### 5.2 样本来源

| 样本 | 路径 | 产生方 |
|---|---|---|
| 执行样本 | `mcp_shells/l0_trade_exec/ml_data/samples.jsonl` | trade-exec MCP `_emit_sample()` |
| 执行策略训练行 | `23-.../dreambuddy_evolution/data/execution_policy_training.jsonl` | `execution_sample_loader.py` |
| Shadow-RL 样本 | `23-.../dreambuddy_evolution/gene_data/shadow_rl_samples.jsonl` | 23 L3 探索（约 275 万条） |
| 矛盾样本 | `23-.../dreambuddy_evolution/data/contradiction_samples.json` | W6 权重学习（生产链路待补齐） |
| 约束审计样本 | `49-交易框架协议/runtime/constraint_audit.jsonl`（规划） | 42 / 子策略适配器 |

### 5.3 训练管线

1. **执行策略（Phase 1b）**：`execution_sample_loader` → `executor_agent` 可注入 policy；≥2 周 paper 样本后训练；硬钳位（乘数 ≤1.0、方向不可改）。
2. **进化管线**：`EvolutionPipeline`（L1 状态→L2 基因库→L3 Shadow-RL→L4 Bellman）；`shadow_backtest` + `trade_settlement_bridge` 真实 PnL 回注。
3. **矛盾权重学习（W6）**：延迟标注 + ≥500 样本岭回归最小二乘（含 0.7/0.3 平滑）；`ContradictionFeedback` 贝叶斯升级/降级，截断 [0.3,1.5]。

> **Bellman reward 现状**：`kline_event_handler` 与 `run_symbol` 两条链路的 Bellman reward 都用 `quality_score−0.5`；真实 PnL 只注入 ShadowRL（初始占位 0.0，平仓时由 `TradeSettlementBridge` 回填）。Bellman 尚无真实回报信号。
4. **约束校准**：40/43 约束命中率、回撤、错杀率 → 建议制反馈；不得直接改模型权重，须经 P5/P6 或战略门禁采纳。
5. **约束**：不并入 6 域 DomainCouplingHead；不改变既有 checkpoint 维度；48 域三关门禁保持。

### 5.4 信号生产时序

| 频率 | 任务 | 出口 |
|---|---|---|
| 每 300s | 11 polling_trader（A0-A9 / BCRM2 / BDSM） | 11 内部 + 状态文件 |
| 每小时 :18/:48 | 43 战略承接推演 | `strategic_extension_signal.json` |
| 每小时 | 40 周期/策略映射 | `cycle_state.json` / `strategy_mapping.json` |
| 每小时 | 42 约束合并 + 候选信号汇聚 | `bus_state.json` + 约束视图 |
| 每小时 | 23 `KlineEventHandler`（约 50 币） | FinalDecisionSignal / `23_signal_state.json` |
| 每小时 | trade-exec `execution_sample_loader` | `execution_policy_training.jsonl` |
| 每日 23:50 | BDSM 快照 | `bdsm_snapshot_YYYYMMDD.json` |

**目标调度顺序**：40(:05) → 43(:18/:48) → 42(:50) → 23(:55)。42 必须校验 43 信号的 `ts/expires_at`，不得把上一轮 43 信号当本轮；23 记录各源 `age`，超过 TTL 降级。

### 5.5 触发契约

- 训练触发 `trigger_training` 属 L1 闭环内部控制面，L2 不可调用。
- `pipeline=execution_policy`：同步运行样本落盘；`pipeline=evolution`：写任务文件排队。
- `dry_run` 只返回命令/任务，不执行。

---

## §6 现状差距（2026-11-05 调研 + 代码核验）

| 差距 | 现状（代码核验） | 影响 | 阶段 |
|---|---|---|---|
| 40 `strategy_mapping` 约束链无消费者 | 42/43/23 零引用；仅前端展示 + 40 自身 p5 读 `effective_confidence` 作特征 | 最终仓位带/风控守卫未进入约束链 | P2 |
| 43 `strategic_extension` 是 shadow | `shadow=True` 硬编码；23 5g 注入但不参与裁决 | 宏观弹性约束在实盘不生效 | P2 |
| 23 `macro_constraint` 注入不裁决 | `data_pipeline` 注入 `kline_data["macro_constraint"]`，engines/core/pipeline 零消费 | 约束形同虚设 | P2 |
| 23 路径选择非真正“矛盾对抗” | `_select_optimal_path` 最终为纯 argmax；外生度量可整体替换主矛盾 | 23 的核心价值未完全兑现 | P2 |
| 矛盾维度语义失真 | C 编号实为路径来源映射；D1-D4 重建未完成（评估器已通过 T5 参与裁决） | 主矛盾识别口径不稳 | P2 |
| 双链路 A_dim 不是 attention | A_dim=`primary_contradiction.dimension`；`AttentionAggregator` 生产未接线 | 文档的 Granger vs Attention 未落地 | P2 |
| 事件驱动主矛盾检测器未接线 | fomc/inflation/credit/ai_capex 无生产调用；开关未注册进 `AGI_SWITCHES` | 事件主矛盾不生效 | P2 |
| Transformer 配置与文档不一致 | 代码默认 4 head/32 dim；8/64 为目标/消融配置；训练报告 final_loss=0.0119（文档 0.0136） | 部署模型与文档口径漂移 | P2 |
| 交叉验证阈值不可触发 | pipeline `structural_break_threshold=1.0`、persistence=5；类默认 0.4 被覆盖 | 质变检测可能漏报 | P2 |
| 结构断裂实现名不副实 | 实际使用 Welch t-test；CUSUM 仅为命名/依赖守卫 | v0.7 评审结论需修正 | P2 |
| 阻力向量微观结构 | 6 组件已启用（W1），D2 衍生品数据待采集 | 资金流维度不完整 | P3 |
| W6 样本链路 | 学习器+S4 缓存修复已落地；本地无 `contradiction_samples.json`，云端待验证 | 权重自学习闭环待确认 | P3 |
| BCRM2 不收约束 | `enable_five_domain=False`、`shadow_mode=True` | 战术信号不受宏观约束 | P3 |
| BDSM 不收约束 | `enable_bdsm_war_state_check=False` | 基本面策略独立跑 | P3 |
| 29 不收约束 | 影子态、无宏观档位；Phase3 共享事件层未做 | 事件脉冲不衰减 | P3 |
| 子系统桥接绕过 42 | `SubSystemBridge` 直接读 polling_trader 内存态 | 插件总线未真正统一 | P1/P3 |
| 双 war_state 来源 | 11 内部五域 vs 43；未统一 | 约束口径冲突 | P2 |
| 42 参数通道零流量 | 6 参数 v1.0 默认；仅 43 声明订阅；无分发器 | 参数化约束未闭环 | P1 |
| `bus_state.json` 整文件覆盖 | 每适配器新建 SignalBus；当前 10 条全部 `source=bdsm` | 多源/多约束无法共存 | P1 |
| registry 缺 `horizon` | 6 publisher 全 enabled；仅 43 subscribe；无 horizon | 跨周期冲突无法治理 | P1 |
| TTL 不一致 | 23 72h / 42 24h / 43 7 天 | 同一约束在不同消费点语义不同 | P2 |
| 路径硬编码 | 42=6 适配器、23=2、43=3、40=22；trade-exec MCP 信号源默认路径 | 本地不可运行 | P1 |
| 40 P5/P6 门禁 | P5 x1 1/100、0.14/2 周；P6 锁死；P1-P4 为规则引擎 | “神经网络”当前主要是规则 + 锁住的 Encoder | P4 |
| 43 encoder 接口空 | `load_encoder_outputs()` 恒空 | P6 特征未接入 | P4 |
| 输出未 SignalSchema 化 | 裸 dict + `event_driven_state.json` shadow；无 `signal_id/expires_at` | 消费方各自造字段 | P2 |
| Bellman reward 无真实回报 | 两条链路都用 `quality_score−0.5`；真实 PnL 只注入 ShadowRL（占位 0.0） | 训练信号偏差 | P4 |
| 16/22 未真正接入 trade-exec MCP | 13 已接线（RiskBridge）；16 `capital_allocator` 未 import；22 `tee_core` 未 import；OrderPort 为自包含 paper ledger | 执行管道与 SPEC 目标不符 | P3 |
| 6-TRADING 直连旁路 | `dream_trade_exec.py` 直连 OKX 签名下单；`trade_exec_api.py` 独立 paper/live API | 绕过 L0/23/13 | P3 |
| 23 不可用无降级协议 | 当前无“仅离场/平仓接管、禁止开仓”的实现 | 单点故障风险 | P2 |
| 23 双重角色中立性 | 自身候选与仲裁未隔离；无自票上限/独立复核 | 自评偏置风险 | P2 |
| 23 全标的调度未实现 | 当前约 50 币/小时；无高风险 300s 分层 | 与“全标的唯一权威”不匹配 | P2 |
| 11→42 状态文件适配未实现 | 11 子池状态未落文件；42 适配器仍直读各自源 | DEC-08 未落地 | P1 |
| L1 诊断脱敏未实现 | `get_decision_diagnostics` 仅设计 | 原始权重可能外泄 | P3 |
| L1 交易层 MCP 仅设计态 | `mcp_shells/l1_trading/` 不存在；49 目录仅 SPEC | 尚未实现 | P0/P1 |
| `source` 命名口径漂移 | 代码用 `strategic_extension`；文档用 `43-strategic-extension` | 文档/代码不一致 | P1 |
| `dimension_force_v2` 注释过时 | 实际经 T5 参与裁决；注释仍称“只记录日志” | 文档落后 | P2 |
| 29 Phase3 未完成 | Phase1/2 已接，共享事件层未做 | 事件驱动仍影子 | P3 |
| 11 子池直下单绕过 23 | bcrm(5)/bdsm(3)/strategy(3)/event_arbitrage(2)/washout(2) 用 11 自身方向/置信度直接 `okx_client.place_order`；仅 evolution 池走 23 | 23 唯一出口未闭环 | P4 |
| L0 MCP 允许 42 原始信号执行 | `ingest_signal` source 枚举含 `42`；`read_signals` 默认 `["23","42"]` | 可直接绕过 23 | P2/P4 |
| live 旁路不经 13 | 11 全文无 `RiskEngine/13-通用风控` 引用；paper 经 RiskBridge | “13 优先”在 live 落空 | P3/P4 |
| 12 Aster 直连 DEX | `12-三屏趋势系统/live/aster_executor.py` 用自身 .env 凭证直连 | 完全脱离 23/L0/13 | P3 |
| 14/16 执行器 | 14 V15 与 16 `exit_executor` 经 `OKXSimulatedClient` 下单；16 为平仓路径 | 旁路 23/L0 | P3/P4 |
| 双 regime 体系 | 11 自有 regime 表 + BCRM `_regime_multipliers` + 23 `regime_mult` | 语义重叠/冲突 | P2 |
| 五域状态双通道 | 11 five_domain 同时经 SubSystemBridge（内存）与 42 适配器（`11-bcrm`） | 未来 23 订阅 42 时需去重 | P2 |
| 多乘数叠加 | 11 `_combined_mult`、23 `regime_mult`、43 `position_band`、42 params、13 modifier 无统一顺序 | 重复缩放/抵消 | P2 |
| 29 仅 mock 执行 | `run.py trader` 为 mock 循环；开/平仓是占位 | SPEC 不应称“可独立执行” | P3 |

### 6.1 23 核心能力实现折扣（代码核验）

| 断言 | 结论 | 代码证据 | 剩余工作 |
|---|---|---|---|
| `_select_optimal_path` 只是独立评分取最高，不是矛盾间对抗识别主导者（约 30%） | ✅ **真实缺口**（但非完全独立评分：矛盾识别会先调制评分，最终选择仍是 argmax） | `evolution_pipeline.py:1536-1555`（score 调制后 `sort/argmax`）；`:1188-1191`（外生度量可整体替换主矛盾） | P2：实现“矛盾间对抗 → 主导者”选择器；定义验收基线 |
| 矛盾维度实为路径来源映射，需重建 D1-D4 | ⚠️ **部分真实**：identifier 仍是 C 路径映射；D1-D4 评估器已存在并经 T5 参与裁决；C→D identifier 重建未完成 | `contradiction_identifier.py:232-252`；`dimension_force_evaluator.py:167-198,460`；`evolution_pipeline.py:1128-1135` | P2：把 identifier 的 C 编号迁移到 D 编号；D2 补齐 OI/清算 |
| 阻力向量缺资金费率/订单簿/OI | ❌ **不是真实缺口**：代码已实现 6 组件并启用；⚠️ 数据完整性可能不足（fallback/字段缺失） | `resistance_vector.py:233-245`（W_V2：筹码/清算/趋势/资金费率/订单簿/OI）；`_calc_funding_pressure` / `_calc_orderbook_imbalance` / OI 函数 | P3：确认 funding/orderbook/OI 字段在实盘数据中非空；补 fallback 监控 |
| W6 样本链路断裂，`contradiction_samples.json` 从未生成 | ⚠️ **部分真实/已缓解**：机制存在 + S4 缓存修复已落地；本地无文件属运行时产物；生产是否持续生成需云端验证 | `contradiction_identifier.py:79-198`（500 样本、延迟标注、24h 学习、`_save`）；`evolution_pipeline.py` S4 缓存 | P3：云端验证样本文件持续增长；补监控 |
| HJB 仅 30% 权重，不是最终决策者 | ⚠️ **前半不成立**（实际 70%，`enable_hjb_dominant=True`）；**后半成立**（HJB 是评分组件，不是唯一决策者） | `evolution_pipeline.py:1526-1530`；`agi_config.py:70` | P2：保留 70% 口径；docstring 30% 需修正 |

---

## §7 迁移路线

| 阶段 | 内容 | 验收 |
|---|---|---|
| **P0（本次）** | 49 协议 v0.7 评审：七层架构、MacroElasticConstraint v1、FinalDecisionSignal v1、UpperLayerContext v1、23 矛盾裁决定位、代码核验与冲突审计、评审决议 | SPEC 评审通过；merge 后 v1 契约进入禁改期（DEC-03） |
| **P1** | 42 总线：多源合并 + TTL、`macro_constraint`/`elastic_params` 分发、registry 加 `horizon`、路径环境变量；**11→42 状态文件适配（R-42-05）**；子系统桥接改读 42；统一 `source` 命名 | 6 源共存；约束可订阅；无硬编码路径 |
| **P1.5** | L1 交易层 MCP 实现（`l1.trading.mcp` + 注册表；10 工具契约测试） | 只读面可用；写工具 Mandate 生效 |
| **P2** | 40→43→42 约束合并：消费 `strategy_mapping`；统一 war_state 来源；23 消费宏观约束（UpperLayerContext）；C→D 映射**先冻结、shadow 对比**；`DominanceResolver` 成对支配；接入 `AttentionAggregator` 与事件驱动主矛盾检测器；修正 CV 阈值（1.0/0.4）；**23 降级（DEC-06）、中立性（DEC-10）、全标的 1h/高风险 300s（DEC-07）**；D2 接 19-DAL（DEC-16）；L0 `source=23-evolution` 闸门 | 合并约束可查询；23 三条通道叠加宏观约束；主矛盾对抗选择占比 ≥90%（现状约 30% 基线） |
| **P3** | 子交易系统接入约束：BCRM2/BDSM/29 全部应用；插件契约上线；W6 样本链路稳定；**16 `capital_allocator` + 22 `tee_core` 实际接线（R-L0-02）**；12 Aster 与 6-TRADING 直连路径收口（R-L0-03） | 四系统约束命中率可观测；FULL_FREEZE 实测否决；paper 管道 13→16→22 完整 |
| **P4** | 23 唯一出口 + 执行收口：11 子池（bcrm/bdsm/strategy/event_arbitrage/washout）降为信号源；**A0-A9 保留信号源、执行只认 23（DEC-09）**；12/14/16 `exit_executor` 迁移；live 接入 13（DEC-13）；FinalDecisionSignal SignalSchema 化；Bellman reward 统一 | 单信号出口；单标的单执行出口；live 经 13 |
| **P5** | 训练/反馈闭环：执行策略 Phase 1b、约束校准建议、L2 只读 MCP 分析；shadow→live 晋升 | 训练行达标；约束晋升 live；L2 SLO 达标 |

> **P0/P1 门禁**：
> - v0.6 为冻结前最后一版；merge 后 `SignalSchema v1` / `FinalDecisionSignal v1` / `MacroElasticConstraint v1` / `UpperLayerContext v1` 进入禁改期，变更须版本号 + ADR（DEC-03）。
> - **§12.1 评审列 29 项未全部回填前，禁止任何 P1 动工**（DEC-04）；未回填期间只能做评审、文档与只读验证。

---

## §8 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 23 被误实现为“信号求和器” | 高 | 以矛盾识别 + 最小阻力路径为验收标准；保留 `primary_contradiction` / `contradiction_shift` 诊断字段 |
| 宏观约束与微观信号冲突无裁决 | 高 | 双链路交叉验证 + 三条通道；分歧期阈值上浮 |
| 约束链重复应用 | 高 | `constraint_id` / `constraint_applied_at` 审计；23 只复核不重复相乘 |
| shadow 约束误当 live | 高 | `mode` 强制校验；shadow 只进矛盾/审计 |
| 质变检测漏报（Welch t-test/HMM/阈值；CUSUM 仅命名） | 高 | v0.7 P0 前置闭环；SPRT 在线监测；质变日志 |
| 42 单文件总线竞争 | 中 | 原子写 + 多源合并 + TTL；后续 StateStore |
| 插件泛滥/口径漂移 | 中 | registry 唯一事实源；horizon/约束订阅必填；CI 校验 |
| 训练数据污染 | 中 | paper 样本与实盘样本分目录；OOD 隔离；48 域三关门禁不放宽 |
| 实盘旁路风险 | 高 | execution_rights + EXECUTION_AUTHORITY 双闸门；13 风控 fail-closed |

---

## §9 文件索引

| 文件 | 作用 |
|---|---|
| `49-交易框架协议/SPEC.md` | 本协议（本次唯一交付物） |
| `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` | 系统总体架构 SSoT |
| `40-周期神经网络系统/SPEC.md` | 40 周期神经网络 |
| `43-战略承接推演层/SPEC.md` | 43 战略承接推演 |
| `42-神经网络交易协调层/SPEC.md` | 42 插件总线/参数治理 |
| `23-四层闭环自进化交易架构/README.md` | 23 总览 |
| `23-.../docs/矛盾Transformer架构.md` | 矛盾 Transformer 架构 |
| `23-.../docs/矛盾论与Transformer架构融合方案.md` | 双链路融合方案 |
| `23-.../docs/三维度矛盾论理论框架.md` | 矛盾论理论框架 |
| `23-.../SPEC-主要矛盾识别与最小阻力路径设计.md` | 主矛盾识别/路径 |
| `23-.../SPEC-各维度矛盾计算重建.md` | C→D 维度重建 |
| `23-.../SPEC-矛盾论实现断裂修复与阻力场升级.md` | 阻力场升级 |
| `23-.../SPEC-主矛盾对实质交易影响链路修复.md` | 三条作用通道 |
| `23-.../dreambuddy_evolution/agi_config.py` | AGI 开关（弹性/CV/Granger 默认 True） |
| `23-.../dreambuddy_evolution/engines/kline_event_handler.py` | 23 实盘主链 |
| `23-.../dreambuddy_evolution/evolution_pipeline.py` | 23 批处理/路径选择 |
| `23-.../dreambuddy_evolution/core/contradiction_identifier.py` | 主矛盾识别 |
| `23-.../dreambuddy_evolution/core/contradiction_shift_accumulator.py` | 量变/质变 |
| `23-.../dreambuddy_evolution/core/cross_attention.py` | 矛盾 Transformer |
| `23-.../dreambuddy_evolution/core/cross_validation_gate.py` | 双链路交叉验证 |
| `23-.../dreambuddy_evolution/core/elastic_constraint_resolver.py` | 弹性仓位 |
| `23-.../dreambuddy_evolution/core/hjb_solver.py` | 最小阻力路径 |
| `11-易经推理系统/scripts/memory_l4/polling_trader.py` | 11 实盘主 daemon |
| `29-事件驱动策略系统/README.md` | 29 事件驱动 |
| `39-金融语义蒸馏系统/SPEC.md` | 39 语义蒸馏 |
| `mcp_shells/l0_trade_exec/server.py` | L0 交易执行 MCP（paper；origin/main `1eb0076`，本地未同步） |
| `47-MCP管理系统/docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md` | L0 执行 MCP SPEC（origin/main `1eb0076`，本地未同步） |
| `47-MCP管理系统/registry/execution_rights.json` | 标的级执行权注册表（origin/main `1eb0076`，本地未同步） |
| `mcp_shells/l1_trading/` | L1 交易层 MCP（**设计态，未创建**；评审后落地） |

---

## §10 代码核验结论（2026-11-05）

> 核验口径：以工作区磁盘代码 + `origin/main`(`1eb0076`) trade-exec 对象为准；文档仅参考。以下为关键结论，证据为 `文件:行号`。

| # | 结论 | 证据 |
|---|---|---|
| 1 | C1-C8 权重按路径来源定义；无 C5；`grid_trading` 默认 0.05 | `contradiction_identifier.py:232-252,725` |
| 2 | 三步法/4 维权重/共振阈值 0.6 成立 | `contradiction_identifier.py:86,228,709-770` |
| 3 | 维度力量 v2 已通过 T5 参与主矛盾裁决（[0.7,1.3]），非“只记录日志” | `evolution_pipeline.py:1128-1135`；`contradiction_identifier.py:368-392` |
| 4 | 事件驱动主矛盾检测器无生产调用、开关未注册（默认关） | `primary_contradiction_detector.py:6-10,185-186`；`agi_config.py:40-113` |
| 5 | 质变 persistence=14（首快照后 13 次）；shift 阈值 0.4；CV gate 实际阈值 1.0、persistence 5 | `contradiction_shift_accumulator.py:59,91-95,157`；`evolution_pipeline.py:1312-1313`；`cross_validation_gate.py:40,50` |
| 6 | 双链路 A_dim 来自矛盾论识别器，不是 attention；AttentionAggregator 未接线 | `evolution_pipeline.py:1256-1258`；`attention_aggregator.py` 仅测试引用 |
| 7 | Transformer 代码默认 4 head/32 dim；8/64 为目标/消融配置；训练报告 final_loss=0.0119 | `cross_attention.py:71-72`；`neural_sde_model.py:142-143`；`data/neural_sde_v1.training_report.json` |
| 8 | impact_multiplier 为 8 维 × 9 阶段 | `exogenous_data_bridge.py:832-887` |
| 9 | `_select_optimal_path` 纯 argmax；外生度量可替换主矛盾 | `evolution_pipeline.py:1552-1555,1188-1191` |
| 10 | 弹性乘数作用于 `ri`，`position_mult` 仅 `base×regime_mult` | `engine_router.py:328-333`；`kline_event_handler.py:401,463` |
| 11 | `macro_constraint`/`strategic_extension` 在 engines/core/pipeline 零消费 | 全树 grep；仅 `data_pipeline.py:380-396` 注入 |
| 12 | Bellman reward 两条链路均为 `quality_score−0.5`；真实 PnL 仅 ShadowRL | `kline_event_handler.py:560`；`evolution_pipeline.py:1926-1927,1845-1858` |
| 13 | SubSystemBridge 直接读 polling_trader 内存，绕过 42 | `subsystem_bridge.py:52-53,74,90,117,131-132,150-151` |
| 14 | 42 不是 MCP 壳；bus_state 当前 10 条全 bdsm；params 零消费者 | `mcp_capabilities.yaml` 无 42；`signal_bus.py`；`runtime/bus_state.json`；grep `params_active` |
| 15 | 43 `shadow=True` 硬编码；档位 `light_defense`；不读 strategy_mapping | `signal_publisher.py:145-156,153,176`；`cycle_state_adapter.py:29-31` |
| 16 | 硬编码路径：42=6 适配器、23=2、43=3、40=22 | 全树 grep `/home/luke/dreambuddy` |
| 17 | L0 trade-exec 9 工具、paper-only、execution_rights 三态；16/22 未接线 | `server.py:1476-1488`；`execution_rights.json`；SPEC-L0 §4 |
| 18 | L1 交易层 MCP 未实现；49 仅 SPEC | `mcp_shells/l1_trading/` 不存在；`49-交易框架协议/` 仅 SPEC.md |

---

## §11 架构一致性与冲突审计（2026-11-05）

> 审计维度：① SPEC 内部一致性；② 执行路径与数据流（对照代码）；③ 23 上层信息注入。以下冲突按“信号/契约/约束/执行/状态/注入”分类，给出目标规则与阶段。

### 11.1 冲突矩阵

| ID | 类别 | 冲突 | 目标规则 / 处理 | 阶段 |
|---|---|---|---|---|
| A-01 | 信号权 | 11 的 bcrm(5)/bdsm(3)/strategy(3)/event_arbitrage(2)/washout(2) 子池用自身方向/置信度直接下单；仅 evolution 池走 23 | **已决议 DEC-01**：子池降为信号源，经 42 透传给 23；11 仅保留 live 执行网关；过渡期显式双轨 | P4 |
| A-02 | 信号权 | L0 `ingest_signal` 支持 `source=42`；`read_signals` 默认 `["23","42"]`，可绕过 23 | `ingest_signal` 仅接受 `23-evolution`；`read_signals` 默认 `["23"]`；42 只读 | P2/P4 |
| A-03 | 决策权 | 11 的 A0-A9/BCRM/BDSM 与 23 的 action/tier 双权威，冲突无优先级 | **已决议 DEC-02**：23 为全标的唯一决策权威；11 的 A0-A9/BCRM/BDSM 降为信号源，只做风控钳位与执行 | P4 |
| A-04 | 决策权 | 11 自有 regime 表 + BCRM `_regime_multipliers` + 23 `regime_mult` 三套 regime | 宏观 regime 单一源 40/43；23 内部 regime 只用于路径；11 regime 退役/只读 | P2 |
| A-05 | 信号权 | 29 仅有 mock 循环，开/平仓是占位；SPEC 曾称“可独立执行” | 改为“mock/影子”；不列为执行权威 | P3 |
| A-06 | 信号权 | 6-TRADING `dream_trade_exec.py` 直连 OKX 签名下单；`trade_exec_api.py` 独立 paper/live API | 收口到 L0/11，或明确只读/调试用途（R-L0-03） | P3 |
| A-07 | 执行权 | 文档称 13/16/22 已统一 L0 MCP，但代码仅 13 接线；16/22 未 import | 13 保持；16/22 实际接线（R-L0-02）；文档与代码对齐 | P3 |
| A-08 | 降级 | 23 不可用时无“仅离场/平仓、禁止开仓”的实现 | **DEC-06**：仅 11 离场/平仓模块接管，禁止新开仓 | P2 |
| A-09 | 中立性 | 23 自身候选与最终仲裁未隔离 | **DEC-10**：自票上限 + 独立矛盾证据复核 + 审计 | P2 |
| A-10 | 调度 | 23 当前约 50 币/小时，与“全标的唯一权威”不匹配 | **DEC-07**：全标的 1h；高风险 300s | P2 |
| B-01 | 契约 | `forward_signal` 要求 `mode=live`，SignalSchema 无 `mode` 字段 | SignalSchema 增加 `mode(live/paper/shadow)`；`shadow` 为兼容字段 | P0 |
| B-02 | 契约 | 两个 `tier` 同名不同义（43 战略档 vs 23 仓位档） | 改名 `strategic_tier`（43）/ `position_tier`（23） | P0 |
| B-03 | 契约 | source 命名混用：`strategic` / `strategic_extension` / `43-strategic` / `43-strategic-extension` | Canonical source registry；`strategic_extension` 唯一；区分 `11-strategic` 与 `strategic_extension`（43） | P0/P1 |
| B-04 | 契约 | 读工具调用方“编排侧”未定义；写工具如何被调用未说明 | 枚举 `L2 Worker` / `L2 编排` / `L1 内部编排` | P0 |
| B-05 | 契约 | 42 被称“输入汇聚”，但 `23-contradiction` 作为 source、23 输出是否回写 42 未定义 | 42 输入-only；23 输出只读镜像，不参与裁决 | P1 |
| B-06 | 安全 | L1 MCP 诊断可能暴露原始权重/张量 | **DEC-15**：只暴露摘要 + 置信度；原始权重不下发 | P3 |
| C-01 | 约束/乘数 | 11 `_combined_mult`、23 `regime_mult`、43 `position_band`、42 params、13 modifier 无统一顺序 | 唯一公式：`13 > execution_rights > macro_mult=cap×risk_budget > position_mult=base×regime×macro`；11 war_state 只在 R 向量；23 elastic 只在 ri；11 只钳位 | P2 |
| C-02 | 约束应用 | 适配器五步“应用约束”、§4.2“三条通道”、§3.6“23 只复核”三处说法冲突 | 适配器发布前应用一次；23 只复核；三通道是 23 内部机制，不重复应用宏观约束 | P2 |
| C-03 | 约束 TTL | 23 72h / 42 24h / 43 7 天；现状与目标混写 | §4.4 TTL 表现状/目标分列；消费方只认 `expires_at` | P2 |
| C-04 | 数据流 | 11 five_domain 同时经 SubSystemBridge（内存）与 42 适配器（`11-bcrm`） | 按 `(source, ts)` 去重；42 接入后 SubSystemBridge 直读退役 | P2 |
| C-05 | 时序 | 40/43/42/23 均“每小时”，无先后约束；42 可能读到上一轮 43 | 目标顺序 40:05 → 43:18/48 → 42:50 → 23:55；23 记录各源 age | P2 |
| C-06 | 数据流 | 11→42 无跨进程落地方式，42 适配器仍直读各自源 | **DEC-08**：11 写状态文件；42 只读适配器消费（R-42-05） | P1 |
| D-01 | 执行/风控 | 11 live 旁路全文无 13 RiskEngine 引用；paper 经 RiskBridge | 11 建仓前接 13 `pre_trade_check`；过渡期声明 11 自有风控 | P3/P4 |
| D-02 | 执行 | 12 `live/aster_executor.py` 用自身 .env 凭证直连 DEX | P3 迁移首位：改走 L0 paper 或 11 旁路 | P3 |
| D-03 | 执行 | 14 V15 与 16 `exit_executor` 经 `OKXSimulatedClient` 下单；16 平仓路径 | 14 声明 paper 隔离；16 收口到 11/L0 | P3/P4 |
| D-04 | 阶段 | P3 写“16/22 接入”，P4 又写“12/14/16 迁移”；L1 MCP 无实现阶段 | P3=16 capital_allocator + 22；P4=12/14/16 exit_executor；新增 P1.5 L1 MCP | P0 |
| D-05 | 状态 | `event_driven_state.json` 由 23 写，42 标 `29-event`、MCP 标 `23-evolution` | 目标 `23_signal_state.json`；迁移期只读镜像；source 统一 `23-evolution` | P2 |
| E-01 | 文档 | 架构图把 `13→16→22`、全系统受约束画成现状 | §0.5 阅读口径；§6/§11 为现状 | P0 |
| E-02 | 文档 | 8 head / 64 dim 未标“目标配置” | 已加“目标/checkpoint 配置”；代码默认 4/32 | P0 |
| E-03 | 文档 | D 维度评估器已参与裁决 vs C→D identifier 待重建混写 | 拆分为“评估器状态”与“identifier 重建状态” | P0 |
| E-04 | 验收 | “主矛盾识别 ≥90%”无基线 | 以当前约 30% 为基线，定义审计口径 | P2 |
| F-01 | 上层注入 | 23 唯一真正消费的上层信息是 11 `war_state`；40/43 注入零消费 | UpperLayerContext v1（§3.9）；8 步接线（§11.4） | P2 |
| F-02 | 上层注入 | 13 风控状态、16 资金定容、39 语义未进 23 | 注入 `risk_gate_status` / `capital_allocation` / `semantic_context` | P3 |
| F-03 | 上层注入 | Bellman reward 仍用 `quality_score−0.5`；真实 PnL 只在 ShadowRL | 用 `execution_feedback.realized_pnl` 替换 | P4 |
| F-04 | 上层注入 | `AttentionAggregator`、事件驱动主矛盾检测器未接线 | 接成双链路/事件主矛盾；P2 | P2 |

### 11.2 目标优先级（唯一规则）

```text
13 风控（fail-closed，不可放宽）
  > execution_rights（标的级单出口）
  > 23 最终裁决（在 position_band ∩ position_cap ∩ risk_budget 包络内）
  > 43 strategic_tier / 40 position_band（仅 live）
  > 统一 war_state
  > 微观候选信号
```

- 宏观与微观冲突：23 双链路交叉验证裁决；分歧期 `confidence×0.9` 且入场阈值 ×`1/conf_mult`；`full_freeze`/`FREEZE` 否决开仓。
- `mode=shadow` 只进入主矛盾先验与审计，不进入前置否决、阈值、position_mult。
- 任何约束不得放宽 13；任何执行不得绕过 `execution_rights`。

### 11.3 架构优化建议（只记录，不在本轮实施）

1. **23 注入 UpperLayerContext**：把 40 宏观 regime、43 strategic_tier/war_state、40 strategy_mapping 仓位带、16 资金、13 风控状态、39 语义、9 基本面统一为一份上下文，按 §3.9 的 9 个注入点消费，避免 23 继续“盲判”。
2. **单一 war_state 源**：以 43 为唯一宏观 war_state；11 内部五域降为局部状态；SubSystemBridge 改读 43（11 兜底）。
3. **单一 position_mult 所有者**：23 输出最终 position_mult；11 只做风控钳位；42 params 只进 macro_mult；13 最终钳位。
4. **42 明确输入-only**：原始候选信号只进 23，不得直连执行；23 输出只读镜像。
5. **单一 regime 源**：40/43 宏观 regime 统一；23 内部 regime 只用于路径；11 自有 regime 退役。
6. **状态文件收口**：23 写 `23_signal_state.json`，11/42/L0 只读；迁移期 `event_driven_state.json` 仅镜像。

### 11.4 UpperLayerContext 最小接线顺序（已存在未接线优先）

1. **统一 war_state 源**：SubSystemBridge 增读 43，11 兜底（改一个方法）。
2. **消费 5f/5g**：`_apply_high_order_factors` 读已注入的 `macro_constraint` / `strategic_extension`，实现①否决 + ②统一温度。
3. **40 `strategy_mapping` → 42 约束通道 → ⑦ `macro_mult`**。
4. **42 `elastic_params` 订阅分发 → ⑤⑥**。
5. **39 `semantic_context` → ③ identify 先验**。
6. **`AttentionAggregator` 接线 → ⑧ 交叉验证第三源**。
7. **13/16 状态注入 → ①⑥**。
8. **Bellman 换真实 PnL → ⑨**。

### 11.5 结论

最尖锐的五个冲突：**A-01（11 子池绕过 23）、A-02（L0 允许 42 原始信号执行）、D-01（live 不经 13）、C-01（多乘数叠加）、A-03（11 vs 23 双决策权威）**。这五项决定“23 唯一出口 + 13 风控优先”是否真正成立；其余冲突多为契约/命名/文档口径问题，可在 P1/P2 一并收口。

---

## §12 修复建议（供其他 Agent 评审）

> 定位：本节是**提案**，不是已批准方案。每项建议给出问题、根因、改动面、验收、阶段、风险/回滚；评审结论填入“评审”列。原则：先契约后实现、先 shadow 后 live、13 风控不可放宽、任何修复可回滚、不得新增绕过 23 的执行路径。

### 12.1 修复建议总表

| ID | 对应问题 | 修复建议 | 改动面 | 验收 | 阶段 | 评审 |
|---|---|---|---|---|---|---|
| **R-23-01** | §6.1 路径选择纯 argmax；外生度量可替换主矛盾 | 新增 `DominanceResolver`：候选路径**成对支配**比较，输出可解释 dominance 矩阵+主导者；argmax 仅作 shadow 回退；外生度量降为**先验**，不得整体替换（DEC-12） | `evolution_pipeline._select_optimal_path`；新增 `core/dominance_resolver.py`；`contradiction_identifier` 输出 | 主导者判定可追溯；**shadow ≥2 周硬性时间窗**；paper 对比不劣于 argmax | P2 | ☐ |
| **R-23-02** | C 编号仍是路径来源映射 | 建立 C→D 映射层：**先冻结映射**，identifier 输出 D1-D4/C6/C7/C8/NEWS，保留 C 别名双写；shadow 对比旧口径通过后按 D 裁决（DEC-11） | `contradiction_identifier.py`；`dimension_force_evaluator.py` | 映射冻结；D 标签输出；C 别名兼容；主矛盾口径不漂移 | P2 | ☐ |
| **R-23-03** | D2 仅 long_short_ratio + funding_rate，缺 OI/清算 | D2 增补 OI/清算；**统一接 19-DAL**；缺失走 percentile→neutral；监控非空率（DEC-16） | `dimension_force_evaluator.evaluate_d2`；19-DAL | D2 非空率 ≥90%；降级可观测 | P3 | ☐ |
| **R-23-04** | W6 样本链路曾断裂 | 保证单实例缓存；`contradiction_samples.json` 原子写 + 监控；≥500 样本触发学习并记录权重变化 | `contradiction_identifier`；云端 cron | 样本持续增长；学习触发可观测；权重版本可追溯 | P3 | ☐ |
| **R-23-05** | HJB docstring 写 30%，实际 70% | 统一文档与代码为 70%（`enable_hjb_dominant=True`）；明确 HJB 只是评分组件 | docstring；SPEC | 文档/代码一致 | P0 | ☐ |
| **R-23-06** | AttentionAggregator 未接线；A_dim 用识别器 | 用 `last_attn_weights` 聚合出 A_dim，作为 CV gate 的第三源；与现有 A_dim 双跑 shadow 对比 | `cross_validation_gate`；`evolution_pipeline` Phase 2.5 | A_dim 来源开关化；分歧统计可比；不影响现有裁决 | P2 | ☐ |
| **R-23-07** | 事件驱动主矛盾检测器未接线 | 注册开关 `enable_primary_contradiction_detector`；在 pipeline 调用，shadow 先行 | `agi_config`；`evolution_pipeline` | 检测器输出可见；live 前零决策影响 | P2 | ☐ |
| **R-23-08** | 23 仅消费 11 war_state | 实现 §3.9 UpperLayerContext v1 与 9 个注入点；按 §11.4 顺序接线 | 23 data_pipeline / R 向量 / identify / tier / position_mult | 每字段有消费者与审计；无重复乘数 | P2-P4 | ☐ |
| **R-11-01** | 11 五子池直接下单绕过 23 | 子池降为信号源，经 **42** 透传给 23；**A0-A9 保留为信号源，执行只认 23**；11 仅保留 live 执行网关（**全标的**）；过渡期用 execution_rights 标注双轨（DEC-01/02/09） | `polling_trader` 子池；`execution_rights.json`；42 adapters | 除 11 旁路外无直连下单；23 输出覆盖全标的 | P4 | ☐ |
| **R-11-02** | live 旁路不经 13 | 11 下单前调 13 `pre_trade_check`；**默认 fail-closed**；豁免限标的/时限/人工审批（DEC-13） | `polling_trader` 建仓入口 | live 订单 100% 经 13；拒单/豁免可审计 | P3/P4 | ☐ |
| **R-11-03** | 多乘数叠加 | 23 独占 `position_mult`；11 只做风控钳位；公式见 §4.2 | `polling_trader`；`engine_router` | 同一仓位只缩放一次；审计可复算 | P2 | ☐ |
| **R-42-01** | bus_state 整文件覆盖 | 单 SignalBus 实例；按 `signal_id` 合并 + TTL + 原子写 | `signal_bus.py`；adapters | 6 源共存；重启不丢；过期剪枝 | P1 | ☐ |
| **R-42-02** | params 通道零消费者 | ParamGovernor 发布 + 订阅分发器；至少 2 个消费者（23/43） | `param_governor.py`；registry；23/43 | 参数非默认可下发；消费可观测 | P1/P2 | ☐ |
| **R-42-03** | registry 缺 horizon | registry 增加 `horizon` 必填并 CI 校验 | `registry.yaml`；validator | 所有插件声明 horizon | P1 | ☐ |
| **R-42-04** | 路径硬编码 | 统一 `DREAMBUDDY_ROOT`/环境变量；42/23/43/40 全量替换 | 42/23/43/40 | grep `/home/luke` = 0 | P1 | ☐ |
| **R-43-01** | 43 不读 strategy_mapping；shadow 未晋升 | 43 合并 40 `strategy_mapping` 仓位带/risk_guards；按 shadow→live 门禁晋升 | 43 `cycle_state_adapter`；42 约束 | 合并约束可查询；晋升有 paper 证据 | P2 | ☐ |
| **R-L0-01** | L0 允许 42 原始信号执行 | `ingest_signal` 仅接受 `23-evolution`；`read_signals` 默认 `["23"]`；42 只读 | `l0_trade_exec/server.py`；注册表 | source=42 执行被拒；审计可查 | P2/P4 | ☐ |
| **R-L0-02** | 13 已接线；16/22 仅在注释/自包含实现，未真正 import | 13 保持 RiskBridge 前置；**16 `capital_allocator` → sizing**；**22 `tee_core` → OrderPort**；L0 MCP 作为统一编排面（DEC-17） | `l0_trade_exec/server.py`；16/22 adapters | paper 管道 13→16→22 完整；订单可对账；无直连旁路 | P3 | ☐ |
| **R-EXEC-01** | 12 Aster 直连 DEX | 迁移 12 到 L0 paper 或 11 旁路；移除独立凭证路径 | `12-三屏趋势系统/live/aster_executor.py` | 无独立 DEX 直连；execution_rights 覆盖 | P3 | ☐ |
| **R-EXEC-02** | 14/16 执行器旁路 | 14 声明 paper 隔离；16 `exit_executor` 收口到 11/L0 | 14/16 | 平仓路径统一；无双出口 | P3/P4 | ☐ |
| **R-STATE-01** | `event_driven_state.json` 双身份 | 23 写 `23_signal_state.json`；11/42/L0 只读；迁移期旧文件镜像 | `event_receiver.py`；11/42/L0 | 单写者；source=23-evolution；旧文件只读 | P2 | ☐ |
| **R-DATA-01** | 双 war_state / 双 regime | 43 为宏观 war_state 唯一源；11 五域为局部；40/43 为 regime 唯一源 | `subsystem_bridge`；43/11 | 每周期单一 canonical 值；审计可追溯 | P2 | ☐ |
| **R-DOC-01** | 文档落后（CUSUM/30%/3 组件） | 修正 docstring/SPEC：Welch t-test、HJB 70%、6 组件、final_loss 0.0119、4/32 默认 | 23 docs；SPEC | 文档与 §10 一致 | P0 | ☐ |
| **R-23-09** | 23 不可用时无降级协议 | **仅 11 子池离场/平仓模块接管，禁止新开仓**；按标的白名单；降级事件审计（DEC-06） | `polling_trader` 离场模块；23 健康检查 | 23 模拟不可用时无新开仓；平仓可用；审计可查 | P2 | ☐ |
| **R-23-10** | 23 既是策略参与者又是仲裁者 | **自票上限 + 独立矛盾证据复核 + 审计**；自身候选不得单独决定主导者（DEC-10） | `evolution_pipeline` 仲裁；`primary_contradiction` 审计 | 自票占比可观测；独立证据可追溯 | P2 | ☐ |
| **R-23-11** | 23 全标的覆盖的调度/算力未定 | **全标的 1h；高风险标的 300s**；分批/限流；记录各标的 age（DEC-07） | 23 调度；11 调用 | 全标的覆盖；高风险 300s；无积压 | P2 | ☐ |
| **R-23-12** | L1 MCP 诊断暴露边界未定 | **只暴露摘要 + 置信度；原始权重/张量不下发**（DEC-15） | `l1.trading.mcp` `get_decision_diagnostics` | L2 仅见摘要；审计字段脱敏 | P3 | ☐ |
| **R-42-05** | 11→42 无跨进程落地方式 | **11 写状态文件；42 只读适配器消费**（DEC-08） | 11 子池状态；42 adapters | 42 可读 11 状态；无内存耦合 | P1 | ☐ |
| **R-L0-03** | 6-TRADING 两条直连路径 | `dream_trade_exec.py` 直连 OKX、`trade_exec_api.py` OKXCLI 需收口到 L0/11，或明确只读/调试用途 | `6-TRADING/scripts`、`6-TRADING/bridge/api` | 无生产直连旁路；用途标注清晰 | P3 | ☐ |

> **评审门禁**：已决议 DEC-01～DEC-17 见 §12.5；§12.1 的“评审”列仍需逐项回填（29 项）。**未回填前不得进入 P1**（DEC-04）。

### 12.2 重点提案卡（评审重点）

#### R-23-01 主矛盾对抗选择器

- **问题**：`_select_optimal_path` 最终 `sort + scored[0]`；外生度量可整体替换主矛盾。
- **根因**：路径评分只有“单路径分数”，没有“候选之间按矛盾维度的对抗矩阵”；主导者没有被显式求解。
- **建议**：
  1. 新增 `DominanceResolver`：输入候选路径的矛盾维度向量、方向、strength、confidence；输出两两 dominance 矩阵与主导者。
  2. 路径最终分 = `base_score × dominance_weight`；argmax 仅作为 `shadow` 回退。
  3. 外生度量只作为 `primary_contradiction` 的先验（`weight_factor`），不得整体替换。
- **验收**：主导者判定可追溯到维度对；与 argmax 的 paper 对比不劣化；shadow 至少 2 周。
- **风险/回滚**：主导者可能过拟合；通过开关回退 argmax。

#### R-23-02 C→D 维度重建

- **建议**：新增 `C_TO_D_MAP`（C1→D2、C2→D4、C3→D3、C4→D1、C6→C6、C7→C7、C8→C8、news→NEWS）；identifier 内部按 D 计算，输出同时保留 C 别名；D2 使用 `dimension_force_evaluator` 的 z-score。
- **验收**：D 标签出现在 identify 输出；C 别名兼容旧消费方；主矛盾分布与旧版对比无异常漂移。
- **风险**：D2 数据不足导致 neutral 增多；先 shadow 观察。

#### R-23-06 AttentionAggregator 接线

- **建议**：从 `NeuralSDE` 取 `last_attn_weights` → `AttentionAggregator` → A_dim；与现有 `primary_contradiction.dimension` 双跑，输出 `a_dim_attention` 与 `a_dim_identifier`；CV gate 用开关选择。
- **验收**：两套 A_dim 的一致率、分歧分布、对 confidence_mult 的影响可观测；默认仍用 identifier，避免行为突变。

#### R-11-01 11 子池收口

- **建议**：bcrm/bdsm/strategy/event_arbitrage/washout 只产出候选信号（经 42 或 SubSystemBridge 进 23），不再直接 `okx_client.place_order`；evolution 池仍由 23 输出驱动。
- **过渡**：`execution_rights.json` 增加 `signal_only` 状态；按标的灰度；双轨期记录 `execution_path` 审计字段。
- **验收**：除 11 bypass 外，无子池直接下单；23 输出覆盖所有实盘订单。
- **风险**：收口期信号延迟；保留 11 内部风控钳位。

#### R-11-02 live 接入 13

- **建议**：11 建仓前调用 13 `pre_trade_check`；13 返回 rejected 则拒绝；13 不可用时默认 fail-closed（可配置过渡豁免，但必须显式标注）。
- **验收**：live 订单审计包含 `risk_check_id`；13 拒单率可观测。
- **风险**：13 不可用导致停单；先 paper/小标的灰度。

#### R-L0-01 23 唯一出口闸门

- **建议**：`ingest_signal` 拒绝 `source != 23-evolution`；`read_signals` 默认 `["23"]`；42 只读分析。为兼容 inline 调试，增加 `debug_inline=true` 且仅 paper、需 Mandate。
- **验收**：source=42 执行被拒；审计记录 `rejected_source`；23 出口覆盖率 100%。

### 12.3 依赖与建议顺序

```text
P0 契约冻结（本 SPEC）
  → R-42-03/04（horizon + 环境变量）
  → R-42-01 + R-42-05（bus 合并/TTL + 11→42 状态文件）
  → R-42-02（params 分发）
  → R-23-08 + R-DATA-01 + R-STATE-01（UpperLayerContext / 单一 war_state / 状态收口）
  → R-23-01 + R-23-02 + R-23-06 + R-23-07 + R-23-09/10/11（23 核心能力、降级、中立性、调度）
  → R-L0-01 + R-11-03（出口闸门 + 乘数链）
  → R-11-02 + R-L0-02 + R-L0-03（live 13 + 16/22 + 6-TRADING 收口）
  → R-11-01 + R-EXEC-01/02（子池与遗留执行器）
  → R-23-03/04 + R-43-01（数据与训练闭环）
```

### 12.4 评审清单（供 Agent）

对每项提案，请评审并标记 `通过 / 需修改 / 拒绝`，并回答：

1. **根因是否成立**：是否引用了具体代码/行为，而非仅文档？
2. **是否新增旁路**：是否绕过 23 唯一出口、42 输入总线、13 风控或 execution_rights？
3. **是否重复计数**：是否与现有乘数/约束/交叉验证重复应用？
4. **shadow/live 隔离**：是否有开关、默认 shadow、可回滚？
5. **验收可测**：是否有量化指标（覆盖率、拒单率、一致率、回撤）？
6. **影响面**：是否改动共享契约（SignalSchema/FinalDecisionSignal/UpperLayerContext）？是否需要版本号？
7. **数据依赖**：19-DAL/42/13/16 的字段是否真实可得？缺失时降级是否保守？
8. **文档同步**：是否同步 §6/§10/§11 与相关 SPEC，避免再次“文档落后”？

### 12.5 评审决议与待决策清单

**已决议（2026-11-06）**：

| ID | 决议 | 影响 |
|---|---|---|
| **DEC-01** | 11 的五个子池（bcrm / bdsm / strategy / event_arbitrage / washout）**降为信号源**；信号作为“矛盾源”经 **42 协调层**透传给 **23**，不再直接下单 | R-11-01 / R-42-01 目标明确 |
| **DEC-02** | 23 的“唯一决策权威”**覆盖全标的**（不仅是 evolution 池） | A-03 / R-11-01 语义成立 |
| **DEC-03** | v0.6 为**冻结前最后一版**；merge 后 `SignalSchema v1` / `FinalDecisionSignal v1` / `MacroElasticConstraint v1` / `UpperLayerContext v1` 进入**禁改期**；变更须版本号 + ADR | P0“字段冻结”成立 |
| **DEC-04** | **§12.1 评审列未回填前，禁止任何 P1 动工**；merge 只代表“可评审”，不代表“可实施” | 评审门禁 |
| **DEC-05** | R-23-01 验收加入 **shadow ≥2 周** 硬性时间窗；不得仅以“不劣于 argmax”通过 | 总表验收补强 |
| **DEC-06** | 23 不可用：**仅 11 子池的离场/平仓模块接管，禁止新开仓** | R-23-09 / 单点故障策略 |
| **DEC-07** | 23 覆盖：**全标的 1h；高风险标的 300s** | R-23-11 / 调度与算力 |
| **DEC-08** | 11→42：**状态文件 + 42 只读适配器** | R-42-05 / 避免跨进程内存耦合 |
| **DEC-09** | **A0-A9 保留为信号源；执行只认 23**；`EXECUTION_AUTHORITY` 对 `23-evolution` 全标的放行 | R-11-01 / R-11-02 |
| **DEC-10** | 23 双重角色中立性：**自票上限 + 独立矛盾证据复核 + 审计** | R-23-10 / 防止自评偏置 |
| **DEC-11** | C→D 映射**先冻结**，shadow 对比旧口径；通过后再切 D 裁决 | R-23-02 |
| **DEC-12** | `DominanceResolver`：**成对支配 + 可解释矩阵**；shadow 回退 argmax | R-23-01 |
| **DEC-13** | live 13：**默认 fail-closed**；豁免限标的/时限/人工审批 | R-11-02 |
| **DEC-14** | 契约所有权：**49 拥有交易域四契约；47 拥有 MCP 注册表；23 拥有实现** | 治理 |
| **DEC-15** | L1 MCP 诊断：**只暴露摘要 + 置信度；原始权重/张量不下发** | R-23-12 / 安全 |
| **DEC-16** | D2 数据**统一接 19-DAL**（OI/清算）；覆盖率 ≥90% 才进 live | R-23-03 |
| **DEC-17** | 13/16/22 统一为 **L0 trade-exec MCP 能力**（13 风控 / 16 定容 / 22 执行）；12/14/16 迁移需谨慎，按远端代码与文档逐项核验 | R-L0-02 / R-L0-03 |

**待决策（按阻塞级别）**：

| # | 级别 | 决策点 | 建议 |
|---|---|---|---|
| 1 | P1 | 42 是否允许发布 23 输出只读镜像？还是完全 input-only？ | input-only；23 输出经独立只读镜像供 L2 |
| 2 | P1/P2 | 单一 war_state/regime 源：43 为宏观唯一源、11 五域为局部，是否确认？ | 确认；43 唯一，11 兜底 |
| 3 | P2 | 乘数所有权：23 独占 `position_mult`、11 只钳位，是否确认？ | 确认；见 §4.2 唯一公式 |
| 4 | P2 | 23 输出文件：`23_signal_state.json` 的写者/读者/切换时点？ | 23 唯一写者；11/42/L0 只读；P2 切换 |
| 5 | P2 | UpperLayerContext 传输：文件 vs 进程内对象？ | 文件 + 适配器（可审计）；高频字段进程内缓存 |
| 6 | P2 | 23 不可用降级的具体范围：哪些“离场/平仓模块”可接管？按标的白名单？ | 仅平仓/减仓；禁止开仓；按标的白名单 |
| 7 | P2 | 13/16/22 在 L0 MCP 内的实现边界与验收：16 定容、22 执行的具体接口 | 先 13 现状，再 16 `capital_allocator`，再 22 `tee_core` |
| 8 | P3 | 6-TRADING 两条直连路径（`dream_trade_exec.py` 直连 OKX、`trade_exec_api.py` OKXCLI）的处置 | 收口到 L0/11，或明确只读/调试用途 |
| 9 | P3 | `execution_rights` 治理：谁有权改标的级 paper/live/disabled？ | 47 域维护，变更需双人审批 |
| 10 | P3 | 符号宇宙与数据保留：全标的范围、W6/语义上下文保留期 | 先按 11 当前标的池；样本保留 2000 条/语义 48h |
| 11 | P3 | 五个子池的 canonical source 最终命名与迁移期双写 | `11-bcrm` / `bdsm`(→`11-bdsm`) / `11-strategy` / `11-event-arbitrage` / `11-washout` |
| 12 | P4 | 40 P5/P6 解锁标准与时间窗？ | 维持门禁；X1 达标后再议 |
| 13 | 流程 | 评审责任人/截止时间；§12 何时拆成 tracking issues？ | 建议 P1 后拆 issue；本 SPEC 保留索引 |

### 12.6 L0 trade-exec MCP 与 13/16/22 的调用关系（远端核验）

> 核验基线：`origin/main` `b4e661b4`（2026-11-05 16:01Z）；核心文件 `mcp_shells/l0_trade_exec/server.py`。

**现状（代码事实）**

| 模块 | 现状 | 证据 |
|---|---|---|
| **13 通用风控** | ✅ 已接线：`RiskBridge` 加载 `13-通用风控模块/core.engine.RiskEngine`；`pre_trade_check` fail-closed；`suggest_size` 调 `calculate_position` | server.py `RiskBridge` 518-660 |
| **16 调控/定容** | ❌ 未 import；仅注释“定容（16 capital_allocator / 13 PositionSizer）”；实际定容走 13 `calculate_position` | server.py 944-999 |
| **22 执行引擎** | ❌ 未 import；OrderPort 为自包含 `OKXPaperLedger`（paper） | server.py 134-430、1003 |
| **6-TRADING `dream_trade_exec.py`** | ⚠️ 直连 OKX `/api/v5/trade/order`，自带 API key/secret/passphrase 签名 | 文件头 1-40 |
| **6-TRADING `trade_exec_api.py`** | ⚠️ 独立 paper/live API，`OKXCLI(profile='paper')` | 文件头 1-35、`/order` |

**目标调用关系（DEC-17）**

```text
23 FinalDecisionSignal
  → L0 trade-exec MCP
      → RiskCheckPort(13 RiskEngine, fail-closed)
      → SizingPort(16 capital_allocator)
      → OrderPort(22 tee_core adapters/algorithms)
      → PositionPort(reconcile)
      → paper 账本/执行信封

live: 11 bypass gateway → 13 pre_trade_check → okx_client（不经 MCP）
```

**结论**：13 已统一；16/22 是“接口已收口、实现未接线”，不能描述成已上线能力。P3 的 R-L0-02 是 16/22 的实际接线工作；6-TRADING 两条路径是新增旁路，需 R-L0-03 收口。

---

## 附：v0.3 相对 v0.2 的关键变化

1. **23 从“输出层”升级为“矛盾裁决与最终决策层”**：明确 23 不是信号聚合器，而是“矛盾系统 + 矛盾 Transformer + 最小阻力路径”的最优控制求解器。
2. **新增 23 架构专章**（§2.6）：双链路、C1-C8/D1-D4 维度、矛盾 Transformer、量变→质变四条件、最小阻力路径、四层闭环。
3. **新增 FinalDecisionSignal v1 契约**（§3.3）：在 SignalSchema 之上纳入 `primary_contradiction` / `contradiction_shift` / `elastic_result` / `cross_validation` / `path`。
4. **新增“三条作用通道”**（§4.2）：路径评分 / 弹性仓位 / 交叉验证阈值；宏观约束应通过这三条通道生效。
5. **修正开关现状**：`enable_elastic_constraint` / `enable_cross_validation_gate` / `enable_granger_pipeline` 等均为 True（源码核实）；`enable_dimension_force_v2` 为 True，且 v0.4 核验确认其经 T5 参与主矛盾裁决（原“仅记录日志”注释已过时）。
6. **现状差距表更新为 31 条**（v0.4 代码核验后），新增主矛盾识别 30%、C→D 维度重建、W6 样本链路、结构性断裂参数、双 war_state、子系统桥接绕过 42、Bellman reward 口径等问题。
7. **迁移路线改为“42 总线→约束合并→23 高阶仲裁→子系统接入→出口/执行→训练反馈”**。

---

## 附：v0.4 代码核验后的关键修正

1. **双链路表述修正**：现状是 Granger vs 矛盾论识别器；`AttentionAggregator` 未接线，Granger vs Attention 是目标。
2. **维度力量 v2**：已通过 T5 参与裁决，删除“只记录日志”的旧口径。
3. **事件驱动主矛盾检测器**：标注为“已实现、未接线、开关未注册”。
4. **Transformer 配置**：默认 4 head/32 dim；8/64 为目标；`final_loss=0.0119`；impact_multiplier 9 阶段。
5. **质变阈值**：shift accumulator=0.4；CV gate pipeline=1.0、persistence=5；断裂检测实际 Welch t-test。
6. **路径选择**：`_select_optimal_path` 纯 argmax；外生度量可替换主矛盾。
7. **弹性通道**：作用于 `ri`，最终 `position_mult` 仍无宏观乘数。
8. **Bellman reward**：两条链路均为 `quality_score−0.5`；真实 PnL 仅 ShadowRL。
9. **执行管道**：13 已接线；16/22 未接线；paper ledger 自包含。
10. **字段/路径口径**：`clock_degradation`、`light_defense`、`strategic_extension`；硬编码路径 42=6/23=2/43=3/40=22。
11. **交付状态**：L1 MCP 为设计态；L0 trade-exec 文件来自 origin/main，本地未同步。

---

## 附：v0.5 架构一致性审计后的关键修正

1. 新增 §0.5 阅读口径（现状 vs 目标）。
2. 新增 §3.9 UpperLayerContext v1（10 字段 + 9 注入点 + 优先级）。
3. 新增 §11 架构一致性与冲突审计（A/B/C/D/E/F 六类；v0.5 为 28 条，v0.8 增至 35 条）。
4. SignalSchema 增加 `mode`；`tier` 拆为 `strategic_tier` / `position_tier`；新增 Canonical source registry。
5. L0 出口闸门：`ingest_signal` 仅接受 `23-evolution`；`read_signals` 默认 `["23"]`。
6. 统一乘数合成顺序、约束应用所有权、TTL 现状/目标表、目标调度顺序。
7. §6 差距表增至 40 条（v0.8 增至 46 条）；§7 增加 P1.5 L1 MCP 实现，拆分 P3/P4 执行收口。
8. 明确 11 子池、L0 source=42、live 13、12 Aster、14/16 等执行旁路为 P3/P4 收口项。

---

## 附：v0.6 修复建议

1. 新增 §12 修复建议（v0.6 为 23 项提案；v0.8 增至 29 项：R-23×12 / R-11×3 / R-42×5 / R-43×1 / R-L0×3 / R-EXEC×2 / R-STATE×1 / R-DATA×1 / R-DOC×1）。
2. 每项含问题、根因、改动面、验收、阶段、评审列；重点提案卡 6 项（R-23-01/02/06、R-11-01/02、R-L0-01）。
3. 新增修复依赖顺序（§12.3）与 8 条评审清单（§12.4）。
4. 新增 6 个开放问题（§12.5），需评审拍板后回填 §12.1 的“评审”列。
5. 本轮仍只改 SPEC，不实现任何修复。

---

## 附：v0.7 评审决议

1. **DEC-01**：11 五个子池（bcrm/bdsm/strategy/event_arbitrage/washout）降为信号源，经 42 协调层透传给 23；11 只保留 live 执行网关。
2. **DEC-02**：23 的唯一决策权威覆盖全标的。
3. **DEC-03**：v0.6 为冻结前最后一版；merge 后 `SignalSchema v1` / `FinalDecisionSignal v1` / `MacroElasticConstraint v1` / `UpperLayerContext v1` 进入禁改期，变更需版本号 + ADR。
4. **DEC-04**：§12.1 评审列 23 项未全部回填前，禁止任何 P1 动工（v0.8 已增至 29 项）。
5. **DEC-05**：R-23-01 验收加入 shadow ≥2 周硬性时间窗。
6. §12.5 改为“评审决议与待决策清单”，新增 14 项待决策（#1-#14）及补充 8 项（#15-#22）。

---

## 附：v0.8 评审决议落地

1. 记录 **DEC-06～DEC-17**：23 降级/调度/中立性、11→42 状态文件、A0-A9 信号源、C→D 冻结、DominanceResolver、live 13、契约所有权、L1 脱敏、D2 19-DAL、13/16/22 L0 统一。
2. §12.1 修复建议扩至 **29 项**（新增 R-23-09/10/11/12、R-42-05、R-L0-03）。
3. 新增 **§12.6 L0 trade-exec 与 13/16/22 调用关系**（远端 `b4e661b4` 核验）：13 已接线；16/22 未 import；6-TRADING 两条直连旁路。
4. §6 差距增至 **46 条**；§11 冲突增至 **35 条**。
5. §7 P1-P4 调整：11→42 状态文件、23 降级/中立性/调度、16/22 实际接线、6-TRADING 收口。
6. 仍只改 SPEC，不实现。