# 矛盾 Transformer 架构技术文档

> 万物皆数 · 矛盾论 · 阻力最小路径
> 基于真实代码实现的架构归总与未来演进设计

---

## 0. 文档定位

本文档归总自进化交易系统的核心底层架构——**矛盾 Transformer**。它不是语义识别的 Transformer，而是面向**矛盾空间**的变体：用 QKV 注意力机制定位主要矛盾，用多头注意力并行评估多矛盾维度，用最小阻力路径求解器计算最优交易路径。

文档分两部分：
- **Part A：现有实现归总**（基于代码事实）
- **Part B：架构缺口与演进设计**（基于调研分析）

---

## Part A：现有实现归总

### 1. 核心哲学

| 哲学概念 | 数学实现 | 代码位置 |
|---|---|---|
| 万物皆数 | 所有市场状态→数值化向量 | `resistance_vector.py`, `exogenous_strength_evaluator.py` |
| 矛盾论 | 多维度矛盾(C1-C8) → 主要矛盾识别 | `contradiction_identifier.py` |
| 阻力最小路径 | HJB PDE + 路径积分 + 变分法 | `hjb_solver.py`, `path_integral.py` |
| Transformer 注意力 | Q=价格签名, K/V=外生因子 | `cross_attention.py` |

### 2. 矛盾维度体系（C1-C8）

来源：[contradiction_identifier.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_identifier.py#L45-L54)

| 维度 | 含义 | 路径来源 | 市场影响权重 |
|---|---|---|---|
| C1 | 资金面 | bdsm | 0.25 |
| C2 | 情绪面 | trend_following / grid_trading | 0.15 |
| C3 | 技术面 | bcrm | 0.20 |
| C4 | 宏观 | strategic | 0.30 |
| C6 | 时序 | deep_reasoning | 0.10 |
| C7 | 隐性 | synthesized | 0.10 |
| C8 | 宏观交叉 | l2_gene | 0.10 |

### 3. Cross-Attention 组件

来源：[cross_attention.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/cross_attention.py)

#### 3.1 组件结构

```
FactorEncoder(factor_dim=1, d_model=32)
  → Linear(1, 32) + LayerNorm

MultiHeadCrossAttention(d_model=32, n_heads=8, dropout=0.1, factor_head_mask=None)
  → q_proj, k_proj, v_proj, out_proj (all Linear)
  → scores = Q·Kᵀ / √head_dim
  → scores += factor_head_mask  # 维度对齐: 每个 head 只看对应矛盾维度的因子
  → weights = softmax(scores)   # → 该维度下的因子排名
  → context = Σ weights · V
  → self.last_attn_weights = weights  # 暴露 attention weights (Phase 3)
```

**维度对齐 mask（Phase 4）**：
- `factor_head_mask`: shape `(n_heads, n_factors)`，值为 `0`（允许）或 `-inf`（屏蔽）
- 每个 head 只对其所属矛盾维度的因子做 attention，其余因子被屏蔽
- 支持硬 mask（`-inf`，完全屏蔽）和软 mask（大负值如 `-1e9`，允许少量跨维度梯度泄漏）

#### 3.2 QKV 角色映射

| Transformer | 矛盾 Transformer | 含义 |
|---|---|---|
| Q (Query) | `log_sig_t`（价格路径签名） | 当前价格状态在"问"：什么外生力量能解释现在？ |
| K (Key) | 外生因子编码（etf_flow/funding/cpi_surprise/dxy/vix... 共 36 个） | 各矛盾维度的证据地址 |
| V (Value) | 同上（K=V 自编码） | 各矛盾维度的力量值 |
| attention weights | softmax(QKᵀ/√d) | **因子影响排名**（随价格状态动态变化） |
| context vector | 加权求和 | **主要矛盾的综合力量** |

#### 3.3 在 NeuralSDE 中的集成

来源：[neural_sde_model.py#L301-L318](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/neural_sde_model.py#L301-L318)

```
Q = q_proj(log_sig_t)              # (B, 1, cross_attn_dim)
K,V = factor_encoder(exogenous)    # (B, N, cross_attn_dim)
ctx = cross_attn(Q, K, V)          # (B, cross_attn_dim)
drift = net([S_t, time, ctx, regime, transition])  # ctx 注入漂移项
```

**当前配置**（已训练模型）：
- `use_cross_attention = True`
- `cross_attn_dim = 32`（从 16 提升，支持 n_heads=8 时 head_dim=4）
- `cross_attn_heads = 8`（从 2 提升，对齐 C1/C2/C3/C4/C6/C7/C8/news 共 8 组）
- `exogenous_factor_dim = 36`（覆盖全部 10 模块）
- `factor_head_mask`: 8×36 维度对齐矩阵，每个 head 只看所属维度因子

> **消融建议（2026-10-06）**：消融实验显示 `cross_attn_dim=64` (head_dim=8) 比 `cross_attn_dim=32` (head_dim=4) MAE 改善 69.8%。新训练模型建议使用 `cross_attn_dim=64`。详见 §12 Phase 3+4 消融验证。

### 4. 矛盾识别引擎

来源：[contradiction_identifier.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_identifier.py)

#### 4.1 三步法

```
输入: 6 条路径（bdsm/bcrm/strategic/deep_reasoning/l2_gene/synthesized）
  │
  ├─ Step 1: 共振检测
  │   long_weight vs short_weight
  │   → score, direction, strength(=对立度), consensus_penalty
  │
  ├─ Step 2: 冲突裁决（仅当 resonance < 0.6）
  │   4 维评分法: 力量对比(0.40) + 时间紧迫性(0.15)
  │               + 证据一致性(0.25) + 市场影响权重(0.20)
  │
  └─ Step 3: 主导性评估
      Wyckoff Cause & Effect + Effort vs Result
      Minervini 趋势模板(8条件) + VCP 收缩比
      → enhanced_strength = base × (1 + 0.2·cause + 0.2·effort + 0.3·continuation)
```

输出：`{dimension(C1-C8), direction, strength, confidence, cause_score, effort_result, continuation_score}`

#### 4.2 硬约束

- HC-AGI-18：异常 FAIL-OPEN 返回 neutral
- HC-AGI-23：至少 2 条路径才分析，单路径返回 neutral

### 5. 阻力向量与最小阻力路径

#### 5.1 五维阻力场

来源：[resistance_vector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/resistance_vector.py)

| 维度 | 含义 | 计算方法 |
|---|---|---|
| R_up / R_down | 涨跌阻力 | 筹码(0.5) + 清算(0.3) + 趋势(0.2) |
| R_smooth | 趋势纯度 | 1 - R²(线性拟合)（Livermore） |
| R_flow | 量价效率 | Wyckoff effort/result |
| R_reflexivity | 反射性 | Soros 4:3:3（corr/liq/sent） |

**矛盾调制**（[resistance_vector.py#L438-L452](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/resistance_vector.py#L438-L452)）：
```
if primary_direction == "long":
    R_up   *= (1 - 0.3 × strength)    # 上涨阻力减小
    R_down *= (1 + 0.5 × strength)    # 下跌阻力增大
```

#### 5.2 最小阻力路径求解

三级降级链（[hjb_solver.py#L18-L23](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/hjb_solver.py#L18-L23)）：

```
HJBPathSolver (PDE 逆向动态规划)
  → VariationalPathOptimizer (欧拉-拉格朗日梯度下降)
    → PathIntegralEngine.find_least_resistance_path (蒙特卡洛 argmin)
```

作用量定义：`S = α·成本 + β·风险(最大回撤) + γ·不确定性`

### 6. 周期阶段分类（已有但未充分利用）

#### 6.1 FOMC 事件窗口

来源：[event_window_tracker.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/event_window_tracker.py)

```
6 阶段:
  ① expectation_build   (前 4-6 周, 概率 <40%)
  ② expectation_rise    (前 2-4 周, 概率 40-70%)
  ③ expectation_jump    (前 1-2 周, 概率 >70%)
  ④ expectation_digest  (前 1 周内)
  ⑤ event               (FOMC 当天)
  ⑥ repricing           (后 1-3 周)
    ├─ Phase A relief       (0-5 天)
    ├─ Phase B verification (5-15 天)
    └─ Phase C trend        (15+ 天)
```

**重要发现**：`event_context` 在实盘 `evolution_pipeline.py` 中**未被消费**，仅在回测脚本 `backtest_macro_event.py` 中使用。

#### 6.2 债务周期

来源：[debt_cycle_phase.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/debt_cycle_phase.py)

- 信贷增速 > GDP 增速 → expansion
- 信贷增速 < GDP 增速 + 利率上行 → contraction
- 否则 → neutral

#### 6.3 矛盾漂移检测

来源：[contradiction_shift_accumulator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_shift_accumulator.py)

- 量变：力量数值变化，排序不变
- 质变：排序变化 + 结构性断裂（波动率制度转换/相关性断裂/形态转换）

### 7. 外生因子体系

#### 7.1 基本面 10 模块 → C1-C8 矛盾维度映射

来源：`9-基本面分析/dal_snapshot_provider.py` + `19-数据访问层` 数据库（`mm_metrics` 表）

| 前端模块 | 矛盾维度 | 已有因子(实盘) | 可扩展因子数 | 数据新鲜度 |
|---|---|---|---|---|
| flow 资金流 | C1 资金面 | etf_total_flow, funding_rate | 7 | 今日 |
| sentiment 情绪 | C2 情绪面 | — | 7 | 今日 |
| onchain 链上 | C3 技术面 | active_addresses, tx_count, exchange_balance_chg | 8 | 今日 |
| macro 宏观 | C4 宏观 | cpi_actual, rate_hike_prob, fomc_rate_change | 9 | 周/月 |
| calendar 经济日历 | C4 宏观(事件) | — | 3 | 周/月 |
| valuation 估值 | C6 时序/估值 | — | 6 | 周 |
| breadth 市场广度 | C7 隐性/叙事 | stablecoin_tvl | 5 | 今日 |
| news 新闻 | C2/C7 信息面 | — | 4 | 今日 |
| narrative 叙事 | C7 隐性 | — | 4 | 今日 |
| intermarket 跨市场 | C8 宏观交叉 | dxy | 7 | 周/日 |

**当前状态**：Phase 1 已完成，实盘使用 36 个因子（覆盖 10 模块）。数据库有 50+ sub_category，仍可扩展至 40+ 因子。

#### 7.2 扩展因子清单（按矛盾维度分组，40+ 候选）

##### C1 资金面（9 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| etf_total_flow | etf_flow.total_flow | +675.2M | ✅已有 |
| funding_rate | funding_rate.funding_rate_pct | -0.0015% | ✅已有 |
| long_short_ratio | long_short_ratio.long_short_ratio | 1.1213 | 🆕 |
| liq_total_24h | derivatives_spot.fut_liq_total_24h_usd | 4.62亿 | 🆕 |
| liq_long_24h | derivatives_spot.fut_liq_long_24h_usd | 2.77亿 | 🆕 |
| liq_short_24h | derivatives_spot.fut_liq_short_24h_usd | 1.85亿 | 🆕 |
| open_interest | derivatives_spot.fut_open_interest_usd | 1251亿 | 🆕 |
| exchange_inflow_24h | exchanges_whales.ex_summary_inflowUsd24h | -11.7亿 | 🆕 |
| whale_netflow | exchanges_whales.whale_netflow_to_ex_usd | — | 🆕 |

##### C2 情绪面（7 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| fear_greed | crypto_fear_greed.value | 73 | 🆕 |
| fg_volatility | fear_greed_enhanced.volatility | 86 | 🆕 |
| fg_momentum | fear_greed_enhanced.momentum | 99 | 🆕 |
| fg_funding | fear_greed_enhanced.funding | 50 | 🆕 |
| fg_capital_flow | fear_greed_enhanced.capital_flow | 63 | 🆕 |
| news_count_24h | social_volume.news_count_24h | 27 | 🆕 |
| social_volume | social_volume.social_volume | 2700 | 🆕 |

##### C3 技术面（链上，8 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| active_addresses | btc_basics.active_addresses | 426,300 | ✅已有 |
| tx_count_24h | btc_basics.tx_count_24h | 714,491 | ✅已有 |
| exchange_balance_chg | exchanges_whales.ex_bal_BTC_chg30d_pct | -0.94% | ✅已有 |
| hashrate | btc_basics.hashrate | 1.10 EH/s | 🆕 |
| difficulty | btc_basics.difficulty | 1.33e14 | 🆕 |
| sth_supply_pct | utxo_age_distribution.short_term_holder_supply_pct | 35.5% | 🆕 |
| lth_supply_pct | utxo_age_distribution.long_term_holder_supply_pct | 39.5% | 🆕 |
| profit_supply_pct | utxo_age_distribution.profit_supply_pct | 64.6% | 🆕 |

##### C4 宏观面（9 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| cpi_actual | cpi.actual | 3.4% | ✅已有 |
| fomc_rate_change | fomc_decision.rate_change | +0.25 | ✅已有 |
| rate_hike_prob | fedwatch.hike_prob | 0% | ✅已有 |
| cpi_surprise | cpi.surprise | -0.1 | 🆕 |
| ppi_surprise | ppi.surprise | -0.6 | 🆕 |
| nfp_surprise | nfp.surprise | +35K | 🆕 |
| cut_prob | fedwatch.cut_prob | 44.9% | 🆕 |
| fed_funds | FEDFUNDS.value | 3.75% | 🆕 |
| m2_yoy | M2SL.yoy_pct | +5.41% | 🆕 |

##### C6 估值/时序（6 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| mvrv | cycle_signals.bottom_mvrv_value | 1.44 | 🆕 |
| nupl | cycle_signals.bottom_nupl_value | 0.31 | 🆕 |
| puell_multiple | cycle_signals.bottom_puell-multiple_value | 1.01 | 🆕 |
| reserve_risk | cycle_signals.bottom_reserve-risk_value | 0.0013 | 🆕 |
| two_year_ma | cycle_signals.bottom_two-year-ma_value | 0.886 | 🆕 |
| ahr999 | cycle_signals.bottom_ahr999_value | 0.499 | 🆕 |

##### C7 广度/叙事（5 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| btc_dominance | overview_market.btc_dominance_pct | 58.9% | 🆕 |
| global_change_24h | overview_market.global_change24_pct | -2.18% | 🆕 |
| defi_tvl | chains_summary.total_tvl_bln | 86.9B | 🆕 |
| stablecoin_total | stablecoins_top_10.total_circulating_usd_bln | 313.9B | 🆕 |
| usdt_change_7d | tether_current.change_7d_pct | +0.21% | 🆕 |

##### C8 宏观交叉（7 个）

| 因子名 | sub_category.metric_name | 当前值 | 状态 |
|---|---|---|---|
| dxy | DX-Y.NYB.value | 100.39 | ✅已有 |
| spx | SPY.value | 766.0 | 🆕 |
| gold | GC=F.value | 4388.7 | 🆕 |
| vix | ^VIX.value | 15.52 | 🆕 |
| us10y | ^TNX.value | 4.963% | 🆕 |
| nvda_pe | stock_info_NVDA.forwardPE | 15.05 | 🆕 |
| nvda_rev_growth | stock_info_NVDA.revenueGrowth | +105.9% | 🆕 |

#### 7.3 现有外生因子强度评估器

来源：[exogenous_strength_evaluator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/exogenous_strength_evaluator.py)

3 维度 × 3 周期 = 9 个力量值：

| 维度 | 短期 | 中期 | 长期 |
|---|---|---|---|
| 技术面 | RI 信号强度 | UTXO 换手率 | 月线趋势斜率 |
| 基本面 | ETF 日净流入 | 链上活跃地址 | NVT Z-Score |
| 宏观面 | CPI surprise | 利率决议概率 | 加息/降息方向 |

**当前局限**：`monetary_cycle` 用静态 3 态映射（tightening=1.0 / easing=-1.0 / neutral=0.0），无周期位置感知。因子数量远少于数据库可用数据。

---

## Part B：架构缺口与演进设计

### 8. 缺口一：因子影响力的时间衰减（P0）

#### 8.1 问题

系统能分类"现在处于周期哪个阶段"，但**不调整该阶段下因子影响力的大小**。

典型案例：
- **加息周期**：初期敏感（+25bp 大跌）→ 中期顿感（+25bp 横盘）→ 末期衰减（+25bp 不跌反涨）→ 边际转向（微弱降息预期大涨）
- **赛道过热**：启动期业绩好→大涨 → 过热期业绩好→小涨（priced-in）→ 过热期不及预期→大跌（非对称）

当前 `exogenous_strength_evaluator` 的静态映射无法捕捉这种**因子影响力随周期位置的非线性变化**。

#### 8.2 设计：impact_multiplier(t)

```
factor_effective = factor_raw × impact_multiplier(cycle_phase, factor_type)
```

以加息因子为例的衰减曲线（示意）：

| 阶段 | 加息敏感度 | 降息预期敏感度 |
|---|---|---|
| expectation_build | 0.3 | 0.0 |
| expectation_rise | 0.8 | 0.0 |
| expectation_jump | 1.5 | 0.0 |
| expectation_digest | 0.6 | 0.2 |
| event | 1.2 | 0.5 |
| repricing/relief | 0.3 | 1.5 |
| repricing/verification | 0.2 | 1.2 |
| repricing/trend | 0.1 | 1.0 |

#### 8.3 数据驱动校准

利用已有 `CausalEngine.estimate_ate`（平均处理效应）按周期阶段分桶：

```
impact_multiplier(phase, factor) = ATE(factor → return | phase=phase) / ATE(factor → return | all)
```

这样衰减系数不是硬编码，而是从历史数据因果推断得出。

### 9. 缺口二：多头注意力对齐多维矛盾（P1）

#### 9.1 问题

- `cross_attn_heads = 2`，但矛盾维度有 C1/C2/C3/C4/C6/C7/C8/news 共 8 组，head 数不足以一一对应
- 外生因子已扩展到 36 个（Phase 1 完成），但 2 个 head 无法按维度分组关注
- attention weights 未暴露，无法作为"因子影响排名"输出

#### 9.2 设计：每个 head = 一个矛盾维度的注意力透镜（masked attention）

通过 `factor_head_mask`（shape `n_heads × n_factors`）实现维度对齐：

```
factor_head_mask[h, f] = 0       若因子 f 属于 head h 的矛盾维度
                      = -inf    否则（硬 mask）或 -1e9（软 mask）

scores[h, :, f] = Q[h]·K[f]ᵀ / √head_dim + factor_head_mask[h, f]
weights[h, :, f] = softmax(scores[h, :, f])  # 仅在该维度因子上归一化
```

8 个 head 与矛盾维度一一对应：

| Head | 矛盾维度 | 因子数 | 因子索引范围 |
|---|---|---|---|
| 0 | C1 资金面 | 7 | 0–6 |
| 1 | C2 情绪面 | 5 | 7–11 |
| 2 | C3 技术面 | 6 | 12–17 |
| 3 | C4 宏观面 | 6 | 18–23 |
| 4 | C6 估值 | 4 | 24–27 |
| 5 | C7 广度 | 3 | 28–30 |
| 6 | C8 跨市场 | 3 | 31–33 |
| 7 | news 信息 | 2 | 34–35 |

每个 head 的 `softmax(QKᵀ/√d)` = **该矛盾维度下的因子排名**；
所有 head concat = **多维度矛盾并行评估**；
最终 context = **各矛盾维度力量的加权综合**。

#### 9.3 调研决策：自由学习 vs 结构先验

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 自由学习 | n_heads=8，无约束 | 灵活，可发现未知模式 | 不可解释，head 可能塌缩 |
| B. 硬约束分组 | 每个 head 只看对应维度因子（mask=-inf） | 强可解释，attention 直接=维度内排名 | 抑制跨维度学习，少因子维度（news=2）softmax 噪声大 |
| C. 软先验引导 | 初始化偏向某维度，允许偏离（mask 为大负值） | 兼顾可解释与跨维度学习 | 初始化设计复杂 |

**已选方案：B（硬 mask）为默认，C（软 mask）可配置**。
- 通过 `factor_head_mask` 的值控制：`-inf` = 硬 mask，`-1e9` = 软 mask
- 默认硬 mask 保证 attention weights 严格等于"该维度因子排名"，满足可解释性目标
- 后续若发现跨维度信号重要，可切换软 mask 保留少量梯度泄漏

**待消融验证（Minor）**：
- m1. `head_dim = cross_attn_dim / n_heads = 32/8 = 4` 偏小，建议评估 `cross_attn_dim=64`（head_dim=8）做消融对比
- m2. 硬 mask 默认可能损失跨维度信号（如 funding_rate 同时影响 C1/C2），训练时应同时跑硬 mask vs 软 mask（-1e9）对比 MAE
- m3. 缺少可解释性验证指标，建议增加 attention 熵、维度间 JS 散度，验证"维度内排名"的合理性
- m4. 少因子维度边界：news（2 因子）、C7（3 因子）的 attention 仅作为二元/三元权重参考，排名信息量有限

**mask 构建绑定机制（M3）**：
- `build_factor_head_mask()` 从 `CROSS_ATTENTION_FACTOR_METRICS` 每个 tuple 的第 4 个元素 `dimension` 读取维度分组，**不硬编码索引范围**
- 若因子列表顺序或维度变化，mask 自动重建，不会错位

### 10. 缺口三：时序衰减与多头注意力的耦合

将缺口一和缺口二结合：

```
每个 head 的有效影响力 = head 原始 attention 权重
                      × impact_multiplier(cycle_phase, dimension_of_head)
```

实现"主要矛盾随时间转移"——不是事后检测 shift，而是**每个矛盾维度（head）的影响力随周期位置动态变化**。

例如加息末期：
- Head 宏观面（C4）的 impact_multiplier 从 1.5 → 0.1
- Head 资金面（C1）的 impact_multiplier 从 0.5 → 1.2（转向期资金面主导）

### 11. 完整架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  L0: 原始因子层                                                   │
│  CPI, DXY, funding, ETF_flow, TVL, OI, sentiment, ...           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  L1: 因子强度 + 时间衰减层  ⬅ 缺口一(P0)                          │
│  factor_raw × impact_multiplier(cycle_phase, factor)             │
│  数据来源: CausalEngine ATE 分桶 + EventWindowTracker 6 阶段      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  L2: 矛盾 Transformer 层  ⬅ 缺口二(P1)                           │
│  MultiHeadCrossAttention (n_heads=8, masked attention)           │
│  Q = 价格签名(log_sig)                                           │
│  K,V = 衰减后的因子向量                                           │
│  factor_head_mask: 每个 head 只看所属维度因子                      │
│  → 每个 head 的 attention weights = 该维度因子排名                 │
│  → context = 主要矛盾综合力量                                      │
│  → 注入 NeuralSDE drift                                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ context + 6 路径信号
┌──────────────────────────▼──────────────────────────────────────┐
│  L3: 矛盾识别 + 阻力最小路径                                       │
│  PrimaryContradictionIdentifier (共振→冲突裁决→主导性评估)         │
│  → ResistanceVector (5 维阻力场, 矛盾方向调制)                    │
│  → HJBPathSolver → Variational → PathIntegral (三级降级)          │
│  → 最优交易路径                                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 12. 落地路径

#### Phase 1：扩展外生因子（5 → 36）— ✅ 已完成

**目标**：将 cross-attention 输入从 5 个因子扩展到 36 个，覆盖全部 10 个基本面模块和 7 个矛盾维度。

**Phase 1 因子清单（36 个，覆盖 10 模块）**：

| 矛盾维度 | 因子数 | 对应模块 | 因子列表 |
|---|---|---|---|
| C1 资金面 | 7 | flow | etf_total_flow, funding_rate, long_short_ratio, open_interest, exchange_inflow_24h, liq_long_24h, liq_short_24h |
| C2 情绪面 | 5 | sentiment+narrative | fear_greed, fg_momentum, fg_volatility, fg_capital_flow, fg_funding |
| C3 技术面 | 6 | onchain | active_addresses, tx_count_24h, exchange_balance_chg, profit_supply_pct, hashrate, sth_supply_pct |
| C4 宏观面 | 6 | macro+calendar | cpi_surprise, ppi_surprise, nfp_surprise, cut_prob, fed_funds, fomc_rate_change |
| C6 估值 | 4 | valuation | mvrv, nupl, puell_multiple, reserve_risk |
| C7 广度 | 3 | breadth | btc_dominance, stablecoin_total, global_change_24h |
| C8 跨市场 | 3 | intermarket | dxy, vix, spx |
| news | 2 | news | news_count_24h, total_news_records |

**改动点**：
1. `exogenous_data_bridge.py` 的 `CROSS_ATTENTION_FACTOR_METRICS` 扩展为 36 项
2. `build_exogenous_factors_for_cross_attention` 查询起始时间改为 2010-01-01，确保 forward-fill 能捕获停更因子
3. `ExogenousDataBridge.get_repo()` 自动设置 `DAL_DB_PATH` 指向 `19-数据访问层/data/dreambuddy_core.db`
4. 重训 NeuralSDE 模型（`exogenous_factor_dim` 5→36），final_loss=0.0136

**依赖**：DAL `mm_metrics` 表已有全部数据，无外部依赖。

#### Phase 2：因子影响力时间衰减 impact_multiplier(t) — P0 ✅ 已完成

将 `event_context`（EventWindowTracker 6 阶段）接入 Cross-Attention 因子构建管线，对每个因子按其所属矛盾维度乘以周期位置相关的衰减系数。详见 §8。

**实现**（`exogenous_data_bridge.py`）：
1. `ImpactMultiplier` 类：维护 8 维度 × 7 阶段（含 3 repricing 子阶段）的衰减系数表
2. `get_multipliers(cycle_phase, factor_names, repricing_sub_phase)` → shape (F,) 衰减向量
3. `apply_impact_multiplier(factors, multipliers)` → 衰减后的因子矩阵
4. `build_exogenous_factors_for_cross_attention` 增加可选 `impact_multipliers` 参数，应用衰减
5. `evolution_pipeline._get_latest_exogenous_factors` 获取 event_context 并注入

**设计决策**：
- 维度级 decay（非因子级）：与 Phase 4 的 `factor_head_mask` 维度分组一致，更干净
- 硬编码先验表（基于 §8.2 加息周期）：Phase 6 用 `CausalEngine.estimate_ate` 数据驱动校准替换
- FAIL-OPEN：`cycle_phase=None/neutral` 或 `impact_multipliers=None` → 不衰减（原样返回）
- 不影响已训练 NeuralSDE：衰减在因子输入层应用，模型本身不变

> **顺序说明**：Phase 3+4（维度对齐）在 Phase 2 之前落地，因为 Phase 5 的 head 级别 impact_multiplier 依赖 Phase 4 的维度绑定。Phase 2 以维度级 decay 形式实现，更干净。

#### Phase 3+4：暴露 attention weights + n_heads 对齐矛盾维度（masked attention）— ✅ 已完成

合并 Phase 3（暴露 weights）和 Phase 4（维度对齐 mask）：

**目标**：
1. `MultiHeadCrossAttention` 暴露 `last_attn_weights`（shape `B × n_heads × 1 × N`），作为因子影响排名
2. 引入 `factor_head_mask`（`n_heads × n_factors`），每个 head 只看所属矛盾维度的因子
3. n_heads 2→8，cross_attn_dim 16→32（head_dim=4），对齐 C1/C2/C3/C4/C6/C7/C8/news 共 8 组

**改动点**：
1. `cross_attention.py`: `MultiHeadCrossAttention` 新增 `factor_head_mask` 参数（构造时注册为 buffer，forward 时 `scores += mask`），保存 `self.last_attn_weights`（dropout 前的纯 softmax 概率）
2. `exogenous_data_bridge.py`: `CROSS_ATTENTION_FACTOR_METRICS` 每个 tuple 增加第 4 元素 `dimension`；新增 `build_factor_head_mask()` 从 dimension 元数据构建 mask（M3 修复：不硬编码索引）
3. `neural_sde_model.py`:
   - `_PathSignatureDriftNet`/`_MoEDriftNet` 接收并向每个 expert 传递 `factor_head_mask`（M2 修复：MoE 透传）
   - `NeuralSDEModel.save()/load()` 保存/加载 `factor_head_mask`（M1 修复：checkpoint 序列化）
   - `cross_attn_dim` 默认 32
4. 重训 NeuralSDE 模型（n_heads=8, cross_attn_dim=32, masked attention）

**Major 修复验证**：
- M1 checkpoint: `save()` 将 `factor_head_mask` 写入 checkpoint dict，`load()` 读取并传给 drift_net；旧 checkpoint 无 mask 时 FAIL-OPEN（mask=None，无屏蔽）
- M2 MoE: `_MoEDriftNet.__init__` 接收 `factor_head_mask`，创建每个 expert 时传入；MoE 推理时 masked attention 生效
- M3 绑定: `build_factor_head_mask()` 从 tuple[3] 的 dimension 字段构建，因子顺序变化时 mask 自动适配

**mask 构建规则**（基于 `CROSS_ATTENTION_FACTOR_METRICS` 的分组顺序）：
- Head 0 (C1): 因子 0–6
- Head 1 (C2): 因子 7–11
- Head 2 (C3): 因子 12–17
- Head 3 (C4): 因子 18–23
- Head 4 (C6): 因子 24–27
- Head 5 (C7): 因子 28–30
- Head 6 (C8): 因子 31–33
- Head 7 (news): 因子 34–35

**消融验证已完成**（2026-10-06, 报告: `dreambuddy_evolution/data/ablation_mask_head_dim.json`, 脚本: `dreambuddy_evolution/tests/ablation_mask_head_dim.py`）：

| 实验 | mask | head_dim | cross_attn_dim | MAE | entropy | leakage |
|---|---|---|---|---|---|---|
| A-hard-hd4 | hard | 4 | 32 | 33718.23 | 1.20 | 0.0 |
| B-soft-hd4 | soft | 4 | 32 | 33718.23 | 1.20 | 0.0 |
| C-none-hd4 | none | 4 | 32 | 31432.90 | 3.55 | — |
| D-hard-hd8 | hard | 8 | 64 | 10185.36 | 1.11 | 0.0 |
| E-soft-hd8 | soft | 8 | 64 | 10185.36 | 1.11 | 0.0 |

**关键结论**：
- **P1-a (hard vs soft)**: 完全等价（float32 下 exp(-1e9)=exp(-inf)=0，MAE/entropy/leakage 三项指标完全相同）。默认硬 mask（-inf），软 mask（-1e9）作为可配置项保留但无实际差异。
- **P1-b (head_dim 4 vs 8)**: head_dim=8 (cross_attn_dim=64) MAE 改善 **69.8%**（10185 vs 33718）。**新训练模型应使用 cross_attn_dim=64**。
- **P2 (可解释性)**: mask 模式 entropy≈1.1-1.2（高度聚焦），无 mask entropy=3.55（分散 3x）；mask 牺牲少量精度（MAE +6.8%）换取可解释性，值得。
- **mask leakage = 0.0**：维度隔离完美，硬 mask 实现正确。

**配置建议**：
- 新训练：`cross_attn_dim=64, cross_attn_heads=8, head_dim=8, factor_head_mask=hard`
- 已训练模型（cross_attn_dim=32）：保持不变，避免重训；如需升级，重训后替换 checkpoint

#### Phase 5：head 级别 impact_multiplier 耦合 — P2

将时间衰减与多头注意力结合：每个 head（矛盾维度）的影响力随周期位置动态变化。详见 §10。

#### Phase 6：CausalEngine ATE 分桶动态校准 — P2

用因果推断的平均处理效应（ATE）按周期阶段分桶，数据驱动校准衰减系数。

---

## 附录：核心代码索引

| 模块 | 文件 |
|---|---|
| Cross-Attention | `dreambuddy_evolution/core/cross_attention.py` |
| NeuralSDE (含 CA 注入) | `dreambuddy_evolution/core/neural_sde_model.py` |
| 外生因子桥接 | `dreambuddy_evolution/core/exogenous_data_bridge.py` |
| 主要矛盾识别 | `dreambuddy_evolution/core/contradiction_identifier.py` |
| 阻力向量 | `dreambuddy_evolution/core/resistance_vector.py` |
| HJB 求解器 | `dreambuddy_evolution/core/hjb_solver.py` |
| 路径积分 | `dreambuddy_evolution/core/path_integral.py` |
| 事件窗口 | `dreambuddy_evolution/core/event_window_tracker.py` |
| 债务周期 | `dreambuddy_evolution/engines/debt_cycle_phase.py` |
| 矛盾漂移 | `dreambuddy_evolution/core/contradiction_shift_accumulator.py` |
| 外生强度 | `dreambuddy_evolution/core/exogenous_strength_evaluator.py` |
| 因果引擎 | `dreambuddy_evolution/core/causal_engine.py` |
| 基本面 DAL Provider | `9-基本面分析/dal_snapshot_provider.py` |
| 宏观数据仓库协议 | `19-数据访问层/dreambuddy_dal/protocols/market_macro_repo.py` |
| 数据库 | `19-数据访问层/data/dreambuddy_core.db` (mm_metrics 表) |
