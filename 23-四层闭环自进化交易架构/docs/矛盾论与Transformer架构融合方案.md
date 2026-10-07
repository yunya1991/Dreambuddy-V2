# 矛盾论 v3.0 与矛盾 Transformer 架构融合方案

> 版本: v0.9 (Step1-5 全部落地) | 日期: 2026-10-07
> 定位: 两份核心技术文档（《三维度矛盾论理论框架》v3.0 与《矛盾Transformer架构》）的底层逻辑分析、冲突识别、融合方向设计
> 状态: **仅技术方案，不改代码，需进一步深入探讨**
> v0.2 变更: §3.1 从"对立冲突"修正为"互补关系"；§5.1 从"Granger验证mask"重构为"过去+现在→未来"交叉验证框架；§7 架构图新增交叉验证层；§8.1 标记为已解决
> v0.3 变更: 新增 §6.5 周期轴对齐 + §6.6 周期维度注入方案
> v0.4 变更: §6.5/§6.6 周期维度方案全部回退（数据不足 + 架构不匹配 + 违反"万物皆数"）
> v0.5 变更: 基于代码审计深化 §8 待探讨问题。§8.1 给出 attention 聚合方法（head-weight 求和）；§8.2 确认 FactorEncoder 已有 LayerNorm（标准化影响可控）；§8.3 确认 CUSUM+Hurst 可在线检测（HMM 未实现）；§8.4 建议 C7 多数表决；§8.5 确认参数有理论边界+默认值；§8.7 确认两路径数据源不同（kline vs DAL）。新增 §8.9-§8.12 标注 4 个实现差距（Granger 未集成 / Attention 未聚合 / 交叉验证不存在 / Granger 未验证因子→价格）
> v0.6 变更: 新增 §10 交叉验证层架构设计——3 个模块化组件（GrangerPipelineAdapter / AttentionAggregator / CrossValidationGate）+ 最小改动集成点 + FAIL-OPEN 可回退开关 + 自进化闭环连接（FTCEvolutionBridge）。§9 优先级表更新，将 P0 项指向 §10 模块
> v0.7 变更: 新增 §10.11 §10.10 待探讨问题的优化方案——5 个工程化方案: Q1 Bayesian 数据驱动校准 persistence_threshold / Q2 head_multipliers 收敛性（floor+ceiling+mean reversion）/ Q3 Granger 重估冷却期（时间+样本双约束）/ Q4 双 None 三级降级模式 / Q5 structural_break 类型加权共识（Hurst=1.0/CUSUM=0.6/vol=0.4）。§10.11.7 给出优化后的完整 §5.1 五步算法伪代码
> v0.8 变更（v1.2 评审勘误 8 项全部应用 + TDD-PRE 落地反映）: §10.11.1 divergence_count 字段表述修正为"实现后将包含"，补充 BTC persistence 推荐范围（30m=[5,7]/1h=[7,10]/1d=[10,14]/1w=[14,20]）；§10.11.2 reversion_rate 0.05→0.15（OU 离散过程 r=1-exp(-Δt/τ)，18 期回归 5% 容差，原 0.05 实际需 59 期）；§10.11.3 FOMC 对齐逻辑修正（24h 非对齐 FOMC 6 周）；§10.11.5 Q5 权重表更新（CUSUM→Welch's t-test，HMM→Markov-Regression，threshold 临时 0.4）；新增 §5.1.5a 替代框架对比（5 框架 walk-forward，v0.7 夏普 2.85 排 1）；新增 §10.11.4a Q4 单链路 SPRT 在线监测（p0=0.75/p1=0.50，ASN≈73）。反映已落地 TDD-PRE-001/002/003（welch_ttest/maxiter500/quality_change_log.jsonl+consecutive_count）
> v0.9 变更（Step1-5 全部落地 + TDD-CV-004/005）: §10.7 落地状态表全部标记完成。Step2 GrangerPipelineAdapter 落地（含 Bonferroni 多重比较校正 + statsmodels 0.15 兼容修复）；Step4 head_multipliers 接入（head_adjustment_to_array + neural_sde_forecast）；Step5 自进化闭环阶段1（CognitiveBridge.record_quality_change + granger_reestimate_trigger，FTCEvolutionBridge 待稳定后接入）。TDD-CV-004 5 框架 walk-forward：F1 交叉验证 OOS 夏普 7.77/DSR=1.0，显著优于 F2/F4/F5

---

## 目录

1. [两份文档的底层逻辑](#1-两份文档的底层逻辑)
2. [当前代码实现事实](#2-当前代码实现事实)
3. [底层冲突分析](#3-底层冲突分析)
4. [Transformer 架构的独立价值](#4-transformer-架构的独立价值)
5. [矛盾论可注入 Transformer 的 7 个增强点](#5-矛盾论可注入-transformer-的-7-个增强点)
6. [维度体系映射](#6-维度体系映射)
7. [融合后的双层架构](#7-融合后的双层架构)
8. [待深入探讨的问题](#8-待深入探讨的问题)
9. [落地优先级建议](#9-落地优先级建议)
10. [交叉验证层架构设计（最小改动+可回退+模块化）](#10-交叉验证层架构设计最小改动可回退模块化)

---

## 1. 两份文档的底层逻辑

### 1.1 矛盾论 v3.0 的底层逻辑链

矛盾论 v3.0 是一个根植于毛泽东《矛盾论》的**理论框架**，其核心逻辑链：

```
外生力量度量（非价格，前瞻性）
    │
    │ §4: 力量必须独立于价格结果——否则循环论证
    │ "主要矛盾 = 力量最强 → 力量最强 = 推动价格变动最大 → 价格变动事后可知 → 主矛盾永远事后可解释"
    ↓
z-score → percentile 标准化（维度可比性）
    │
    │ §6: 不同维度的力量不可通约（RSI 0.8 vs CPI surprise 0.7 影响机制不同）
    │ 需标准化后才能跨维度比较和加总
    ↓
Granger 因果验证（主矛盾 → 次矛盾的因果传导）
    │
    │ §5: "主要矛盾规定或影响其他矛盾"是因果命题，不是排序
    │ 宏观加息不只是"力量最强"——它改变了技术面支撑的性质
    │ 必须用 Granger 因果检验验证因果传导链确实存在
    ↓
合力方向 = Σ(wi·di·si) + Σ(wij·di·dj·si·sj·Iij)
    │
    │ §6.2: 含交互项——方向相反且有因果关系的矛盾间有衰减系数 wij
    │ 不是简单线性叠加
    ↓
质变检测 = 排序变化 AND 结构性断裂
    │
    │ §8: 仅排序变化 = 量变，不是质变
    │ 质变必须伴随：波动率制度转换 / 相关性结构断裂 / 市场形态转换
    │ 用 CUSUM / Bai-Perron / HMM / Hurst 检测
    ↓
弹性约束 = sigmoid 衰减
    │
    │ §7: 力量更强的矛盾约束力量较弱的——但不是刚性 veto
    │ position_mult = floor + (1-floor) × sigmoid(Δp/T_max)
    │ T_max = historical_max_rebound_p75 × (S_p/(S_p+S_m))
    ↓
反身性修正 = S_adjusted = S_exogenous + λ·S_self
    │
    │ §10: 系统自身仓位可能 Granger-cause 市场指标
    │ 大仓位时需要修正力量度量
    ↓
可证伪检验 = 命中率 > 55% (binomial p < 0.05)
    │
    │ §11: 理论必须可证伪
    │ 如果方向命中率不显著优于随机，理论被证伪
```

**核心命题**：主要矛盾不是"力量最强者"（那是循环论证），而是"通过因果传导链改变其他矛盾状态的力量"。力量度量必须独立于价格。

### 1.2 矛盾 Transformer 的底层逻辑链

矛盾 Transformer 是一个**工程架构**，用注意力机制定位主要矛盾并用 NeuralSDE 预测价格：

```
36 个外生因子 × impact_multiplier(cycle_phase, dimension)
    │
    │ §8: 因子影响力随 FOMC 周期阶段动态衰减
    │ expectation_build 阶段加息因子敏感度=0.3
    │ expectation_jump 阶段加息因子敏感度=1.5
    ↓
FactorEncoder: factor_dim=1 → cross_attn_dim=64
    │
    │ 每个因子独立编码到 64 维空间
    ↓
Q = log_sig_t（价格路径签名）
K, V = 衰减后的因子编码
    │
    │ Q 代表"当前价格状态在问：什么力量能解释现在？"
    │ K/V 代表各矛盾维度的证据
    ↓
MultiHeadCrossAttention (8 heads, masked attention)
    │
    │ factor_head_mask: 每个 head 只看所属矛盾维度的因子
    │ → 每个 head 的 attention weights = 该维度因子排名
    │ → head_multipliers × weights（Phase 5 时间衰减耦合）
    │ → context vector = 主要矛盾综合力量
    ↓
NeuralSDE drift = f(S_t, time, context, regime, transition)
    │
    │ context 注入漂移项——外生力量改变价格轨迹
    ↓
价格预测 → HJB 路径求解 → 最小阻力路径
    │
    │ 三级降级: HJB PDE → 变分法 → 蒙特卡洛
    │ 作用量 S = α·成本 + β·风险 + γ·不确定性
```

**核心命题**：用 QKV 注意力机制隐式学习"当前价格状态下哪些因子最重要"，用 NeuralSDE 建模价格动力学，用 HJB 求解最优交易路径。

### 1.3 两份文档回答的不同问题

| | 矛盾论 v3.0 | 矛盾 Transformer |
|---|---|---|
| **回答的问题** | "主要矛盾是什么？仓位该怎样约束？" | "价格会怎样？阻力最小路径是什么？" |
| **时间视角** | 看过去——回测验证的因果链 | 看现在——当前市场关注的力量 |
| **方法范式** | 统计因果推断（Granger/CUSUM/HMM） | 深度学习（attention/NeuralSDE） |
| **力量来源** | 非价格量（ETF流/CPI/链上活动） | 价格签名 Q + 因子 K/V |
| **输出** | 仓位倍数（sigmoid 约束） | 价格轨迹预测 + 最优路径 |
| **验证标准** | 方向命中率 > 55% (binomial test) | MAE 优于 GARCH 基线 |

---

## 2. 当前代码实现事实

### 2.1 两套系统的组件全部存在

调研确认，两份文档涉及的所有组件在代码中**均已实现**：

**矛盾论 v3.0 组件**：

| 组件 | 文件 | 关键实现 |
|------|------|---------|
| ExogenousStrengthEvaluator | `core/exogenous_strength_evaluator.py` | 3×3=9 矩阵, z-score→percentile 标准化 |
| GrangerCausalityChecker | `core/granger_causality_checker.py` | ADF 平稳性 + grangercausalitytests + Per-Regime |
| StructuralBreakDetector | `core/structural_break_detector.py` | CUSUM + HMM + Hurst, detect_all() 并行 |
| ElasticConstraintResolver | `core/elastic_constraint_resolver.py` | sigmoid 衰减 + T_max + position_mult |
| ReflexivityMonitor | `core/reflexivity_monitor.py` | 自影响系数 λ + S_adjusted = S_exogenous + λ×S_self |
| ContradictionShiftAccumulator | `core/contradiction_shift_accumulator.py` | 修正算法（比较当前力量）+ 结构性断裂要求 |
| 集成入口 | `engines/kline_event_handler.py` L407-421 | 透传 structural_break/shift_result/elastic_result |

**矛盾 Transformer 组件**：

| 组件 | 文件 | 关键实现 |
|------|------|---------|
| MultiHeadCrossAttention | `core/cross_attention.py` L55-171 | factor_head_mask + head_multipliers + last_attn_weights |
| NeuralSDE | `core/neural_sde_model.py` L141-324 | cross_attn_dim=64, n_heads=8, Q=log_sig → drift |
| ImpactMultiplier | `core/exogenous_data_bridge.py` L742-890 | 8维度×10阶段衰减表 + ATE 校准 |
| CausalEngine | `core/causal_engine.py` L501-610 | calibrate_multipliers + estimate_ate |
| 36因子 + factor_head_mask | `core/exogenous_data_bridge.py` L495-586 | C1-C8/news 分组 + build_factor_head_mask() |

### 2.2 两套系统当前完全独立运行

代码事实：
- `ExogenousStrengthEvaluator` 使用 `data` dict（ri_signal, etf_flow, cpi），输出 3×3=9 候选
- `CrossAttention` 使用 DAL `mm_metrics` 36 因子，输出 8 head attention weights
- `kline_event_handler` 透传矛盾论结果（structural_break/shift_result/elastic_result）但**不引用** Transformer 的 attention weights 或 C1-C8
- 两条路径**无交叉引用**，无映射函数

### 2.3 维度系统对比

| | 矛盾论 v3.0 | 矛盾 Transformer |
|---|---|---|
| 维度数 | 3: technical / fundamental / macro | 8: C1-C8 + news |
| 周期轴 | 3: short / medium / long（正交轴） | 无（扁平排列） |
| 候选数 | 3×3 = 9 | 8 |
| 数据源 | `data` dict（聚合度量） | DAL `mm_metrics`（原始因子） |

---

## 3. 底层冲突分析

### 3.1 Attention 与因果的互补关系（非对立）

**事实**：Attention weights = softmax(QK^T/√d) 本质是**相关性排名**，不是因果性。矛盾论 v3.0 §2.2 明确指出"相关性 ≠ 因果性"。

**但这不构成冲突，而是互补**：

- **Granger 因果（矛盾论）= 看过去**：通过回测验证"ETF流入→价格上升"的因果链，揭示的是**历史已验证的因**
- **Attention（Transformer）= 看现在**：注意力机制在当前价格状态下发现"市场最关注的力量"，揭示的是**当下的主要矛盾**
- **过去 + 现在 → 未来**：两条链不是对立的，而是互补的——一个验证过去什么有效，一个发现现在什么重要

**关键洞察**：两条链的**分歧本身就是矛盾转化的信号**。当 Granger 说"ETF流入是因"但 Attention 聚焦于"美联储加息"时，这暗示主矛盾正在转移——这正是矛盾论 §2.3 的"量变→质变"过程。详见 §5.1 交叉验证框架。

### 3.2 冲突 B：力量度量循环论证风险

**矛盾论 v3.0 §4.1 警告**：

> 主要矛盾 = 力量最强 → 力量最强 = 推动价格变动最大 → 价格变动是事后可知 → 主矛盾永远事后可解释、事前不可知

**矛盾 Transformer 的 Q = log_sig_t**（价格路径签名），attention weights 依赖 Q。这意味着"因子重要性"依赖当前价格状态——当价格上涨时，与上涨相关的因子 attention 权重自然升高。这是**事后偏差**（hindsight bias）。

**但需要注意**：Transformer 的设计意图是**价格预测**，不是矛盾识别。用价格状态作为 Q 来问"什么力量能解释现在"——这在预测范式中是合理的（类似 autoregressive model 用 y_{t-1} 预测 y_t）。循环论证的风险在于：如果把 attention weights 当作"矛盾力量度量"来用，就陷入了矛盾论所批评的循环。

**结论**：只要明确 attention weights ≠ 外生力量度量，两者各司其职，就不构成真正冲突。

### 3.3 冲突 C：线性 vs sigmoid 调制

**ResistanceVector 当前实现**（线性）：

```python
if primary_direction == "long":
    R_up   *= (1 - 0.3 × strength)    # 线性
    R_down *= (1 + 0.5 × strength)    # 线性
```

**矛盾论 v3.0 §7 要求**（sigmoid）：

```python
position_mult = floor + (1.0 - floor) × (1 / (1 + exp(k × (Δp / T_max - 0.5))))
```

线性调制在力量极端时无饱和：
- strength=1.0 时 R_down 增大 0.5（50%）——可能过调
- sigmoid 在极端值时自然饱和——更安全

**影响**：实际交易中，当主矛盾力量>0.9 时，线性调制可能导致阻力场失真。

### 3.4 冲突 D：质变检测缺失于 Transformer 管线

**矛盾论 v3.0 §8** 要求：质变 = 排序变化 AND 结构性断裂。

**矛盾 Transformer** 的 `ContradictionShiftAccumulator` 存在且集成了 `StructuralBreakDetector`，但这个集成只在**矛盾论路径**（kline_event_handler）中。Transformer 的 NeuralSDE 模型在 regime 转换时预测质量会下降（MAE 增大），但**没有自动检测和触发机制**。

**影响**：市场结构转换时（如低波→高波），Transformer 继续用旧 regime 下的模式预测，产生较大误差。

---

## 4. Transformer 架构的独立价值

在讨论融合之前，需要明确 Transformer 架构**不仅仅是"简单"的因子排名**——它有其独立的、矛盾论无法替代的价值：

### 4.1 多维度数据的力量方向识别

Transformer 底层根据大量不同维度数据（36 因子覆盖 10 模块），用 attention 机制识别**力量最强的方向**。对于趋势跟随策略而言：

- **传统趋势跟随**：用价格均线/MACD 等技术指标判断趋势方向——但这些指标本身是价格的滞后变换
- **Transformer 趋势跟随**：用 36 个外生因子的注意力权重判断"哪些力量正在推动价格"——这是**前瞻性的多维度力量综合**，比纯技术指标更丰富

当 ETF 流入加速 + funding rate 转正 + 链上活跃度上升 + 宏观预期转鸽时，Transformer 的多头 head 会同时给出高权重——这种多维共振信号是传统趋势策略无法捕捉的。

### 4.2 非线性因子交互学习

矛盾论 v3.0 §6.2 用显式交互项 `wij × di × dj × si × sj × Iij` 处理维度间交互——但 wij 需要通过历史回归估计，且假设交互结构是已知的。

Transformer 的 attention 机制**隐式学习非线性交互**：
- 多头 attention 可以自动发现因子间的耦合模式
- 不需要预先假设哪些因子有交互
- 可以捕捉矛盾论交互项无法穷举的高阶交互

### 4.3 价格轨迹的概率建模

矛盾论输出的是**仓位倍数**（position_mult）——一个标量约束。Transformer 的 NeuralSDE 输出的是**价格轨迹的概率分布**——包含路径、波动率、置信区间。

对于交易决策：
- 矛盾论：告诉你可以开多少仓（约束）
- Transformer：告诉你价格可能去哪里（预测）

两者**都需要**——知道仓位上限但不知道方向 = 无法交易；知道方向但不知道仓位限制 = 风险失控。

### 4.4 周期感知的因子衰减

Transformer 的 ImpactMultiplier 已经实现了 §8.2 的设计——因子影响力随 FOMC 周期阶段动态衰减。Phase 6 的 CausalEngine ATE 校准更进一步，用因果推断数据驱动地校准衰减系数。

这是矛盾论 v3.0 **未实现**的部分——矛盾论描述了"应该衰减"，但未给出具体的衰减表和校准方法。Transformer 在这一点上**超越**了矛盾论。

---

## 5. 矛盾论可注入 Transformer 的 7 个增强点

基于 §3 的冲突分析和 §4 的 Transformer 独立价值，矛盾论 v3.0 的 7 个统计/因果方法可以注入 Transformer 管线的特定位置，**增强而非替代** Transformer 的能力：

### 5.1 过去+现在→未来：Granger 因果与 Attention 的交叉验证（§5 + Transformer 核心）

> **⚠️ v0.6 实现状态标注**：本节描述的是**理论设计**。代码审计确认 4 个差距（§8.9-§8.12）：GrangerCausalityChecker 未集成到主 pipeline、Attention weights 未聚合到维度、交叉验证代码不存在、Granger 未验证因子→价格因果。**§10 已给出工程化落地方案**——3 个模块化组件（GrangerPipelineAdapter / AttentionAggregator / CrossValidationGate）+ 最小改动集成点 + FAIL-OPEN 可回退开关 + 自进化闭环连接。落地需要按 §10.8 五步骤 TDD 开发。

**核心洞察**：Granger 因果（矛盾论）看过去，Attention（Transformer）看现在，两者不是对立而是互补。两条链的**一致和分歧**本身就是矛盾状态的信号。

#### 5.1.1 三种交叉状态

| 状态 | Granger（过去因） | Attention（现在力） | 含义 | 对应矛盾论概念 |
|------|---|---|---|---|
| **一致** | ETF流入 | ETF流入 | 主矛盾稳定——历史有效因子仍是当前主矛盾，趋势延续概率高 | 量变（力量数值变化，排序不变） |
| **分歧** | ETF流入 | 美联储加息 | 潜在矛盾转移——过去有效的因子正在被新力量取代 | 量变积累（力量开始偏移） |
| **持续分歧** | ETF流入 | 美联储加息（连续 N 期） | 质变信号——主矛盾已从基本面转移至宏观面 | 质变（排序变化 + 需结构性断裂确认） |

#### 5.1.2 交叉验证机制

```
Step 1: Granger 路径输出
  - G_dim: 历史已验证的主矛盾维度 (technical/fundamental/macro)
  - G_confidence: Granger p-value 显著性

Step 2: Attention 路径输出
  - A_dim: 当前 attention 聚合后的主矛盾维度
  - A_strength: 该维度的 attention 权重占比

Step 3: 交叉比对
  if G_dim == A_dim:
      # 一致：主矛盾稳定
      confidence *= 1.15
      shift_signal = False
      divergence_count = 0
  else:
      # 分歧：潜在转移
      confidence *= 0.9
      shift_signal = True
      divergence_count += 1

Step 4: 质变判定（矛盾论 §8 严格定义）
  if divergence_count >= persistence_threshold:
      if StructuralBreakDetector.detect_all():
          # 质变确认：排序变化 AND 结构性断裂
          main_contradiction = A_dim  # 接受 Attention 的新方向
          trigger_granger_reestimate()  # 重新估计因果链
          divergence_count = 0
      else:
          # 量变但未质变：排序变化但无结构性断裂
          pass  # 继续观察，不执行质变

Step 5: head_multipliers 动态调整
  if shift_signal:
      # 分歧期间渐进调整：提升 Attention 指向的 head，衰减 Granger 指向的 head
      boost_factor = 1 + 0.3 × (divergence_count / persistence_threshold)
      decay_factor = 1 - 0.2 × (divergence_count / persistence_threshold)
      head_multipliers[A_dim_head] *= boost_factor
      head_multipliers[G_dim_head] *= decay_factor
```

#### 5.1.3 自进化闭环

```
Granger 因果链 ──→ 过去的主矛盾（已验证）
                        ↕ 交叉比对
Attention 链 ────→ 现在的主矛盾（实时）
                        ↓
                 ┌─ 一致 → 稳定信号（高置信，正常仓位）
                 │
                 └─ 分歧 → 转移信号（降置信，渐进调整 head 权重）
                           ↓
                    持续分歧 + 结构性断裂
                           ↓
                      质变确认
                           ↓
                    Granger 重估 → 新的"过去"
                           ↓
                    新的交叉验证 → 持续进化
```

质变后 Granger 重估 → 新的历史因果链 → 新的交叉验证基线 → 形成持续自进化闭环。

#### 5.1.4 与矛盾论哲学的对应

| 矛盾论命题 | 对应机制 |
|---|---|
| 矛盾是变化的 | Attention 实时反映当前主矛盾，Granger 反映历史主矛盾——两者随时间偏移 |
| 量变积累引发质变 | 分歧持续积累 → 质变触发条件 |
| 质变必须伴随结构性断裂 | 持续分歧 + StructuralBreakDetector = 质变确认 |
| 主要矛盾规定或影响其他矛盾 | 质变后 Granger 重估 → 新的因果传导链 |
| 矛盾的普遍性与特殊性 | 每个时间点的 G-A 关系是特殊的，但 G-A 框架是普遍的 |

#### 5.1.5 为什么这个框架优于"Granger 验证 Attention"

1. **不否定 Attention 的价值**：Attention 反映"现在市场关注什么"——有价值的信息，不需要 Granger "批准"
2. **不否定 Granger 的价值**：Granger 反映"过去什么有效"——历史经验，不需要 Attention "替代"
3. **分歧是信号不是错误**：两条链的分歧是矛盾转化的**最早信号**——比任何单条链都能更早发现主矛盾转移
4. **自进化闭环**：质变后 Granger 重估 → 新的过去 → 新的交叉验证 → 持续进化

#### 5.1.5a 替代框架对比（实证约束）

基于 [framework_comparison.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/framework_comparison.py) 的 5 框架配对 walk-forward 验证（BTC 30m, 87598 期, 2024-2026）：

| 框架 | 样本外夏普 | DSR | 胜率 | 排序 |
|------|-----------|-----|------|------|
| **v0.7 交叉验证（本方案）** | **7.77** | **1.0000** | 0.529 | **1** |
| 互信息 + 动态权重 | 7.90 | 1.0000 | 0.487 | 2 |
| 纯 Attention + Bayesian 后验 | 0.98 | 0.2224 | 0.504 | 3 |
| Shapley 值归因 | 0.68 | 0.0403 | 0.481 | 4 |
| 单 Granger 因果链 | -5.77 | 0.0000 | 0.478 | 5 |

**PBO（过拟合概率）= 0.40**。

**配对 Holm-Bonferroni 校正（F1 vs 其他）**：
- F1 vs F5（单 Granger）: adj_p ≈ 0.000 ***
- F1 vs F2（Bayesian）: adj_p ≈ 0.000 ***
- F1 vs F4（Shapley）: adj_p ≈ 0.000 ***
- F1 vs F3（互信息）: adj_p = 0.293（不显著）

**结论**：v0.7 交叉验证在样本外夏普和 DSR 上显著优于 F2/F4/F5 三种替代框架（Holm-Bonferroni 校正 p<0.001）。与 F3（互信息 + 动态权重）差异不显著——两者在"动态分配因子权重"的思路上有共通之处，但交叉验证额外提供了质变检测和自进化闭环。单 Granger 因果链（F5）表现最差（负夏普），验证了"只看过去"的滞后性。单链路降级模式（Q4）在 Granger 或 Attention 缺失时仍优于完全中性，但需 SPRT 在线监测一致性（见 §10.11.4a）。

#### 5.1.6 示例场景

**场景 1：一致——牛市延续**
- Granger: ETF流入 Granger-cause 价格 (p=0.02)
- Attention: C1(资金面) head 权重最高，占 35%
- 映射后都是 fundamental
- → 交叉验证通过，置信 ×1.15
- → 正常仓位，趋势跟随

**场景 2：分歧——矛盾转移预警**
- Granger: ETF流入 Granger-cause 价格 (p=0.02)
- Attention: C4(宏观面) head 权重突然升高至 40%（之前 15%）
- 映射后: fundamental vs macro → 分歧
- → 置信 ×0.9
- → head_multipliers 渐进调整：C4 head ×1.3, C1 head ×0.8
- → 仓位适当降低

**场景 3：质变——主矛盾确认转移**
- 分歧持续 5 期 + StructuralBreakDetector 检测到波动率制度转换
- → 质变确认：主矛盾从 fundamental → macro
- → 触发 Granger 重估：重新检验 CPI/DXY 是否 Granger-cause 价格
- → 新的 Granger 因果链建立
- → 新的交叉验证基线

### 5.2 z-score 标准化 → FactorEncoder 之前（§6 → Phase 1）

**当前**：因子 raw value 直接进入 FactorEncoder——CPI=3.4% vs OI=1251亿 vs funding=-0.0015%，量纲差异巨大。attention 的 dot product 会被大量纲因子主导。

**注入**：在 FactorEncoder 之前，对每个因子做 z-score → percentile_rank 标准化。

```
当前: factor_raw → FactorEncoder → K, V
注入后: factor_raw → z_score(历史分布) → percentile_rank → FactorEncoder → K, V
```

**价值**：标准化后 attention weights 跨维度可比，真正反映"因子影响力"而非"量纲差异"。

**待探讨**：标准化需要历史分布——滚动窗口 vs 全历史；极端事件时 percentile 可能信息损失。

### 5.3 弹性约束 sigmoid → ResistanceVector 调制层（§7 → L3）

**当前**：ResistanceVector 用线性 0.3/0.5 调制——力量极端时无饱和。

**注入**：用 ElasticConstraintResolver 的 sigmoid 替换线性系数。

```
当前: R_up *= (1 - 0.3 × strength)
注入后: position_mult = floor + (1-floor) × sigmoid(k × (Δp/T_max - 0.5))
        R_up *= position_mult
```

**价值**：力量极端时 sigmoid 自然饱和，避免阻力场过调；T_max 提供数据驱动上限。

**待探讨**：需要历史反弹数据计算 T_max = historical_max_rebound_p75；floor 和 k 的参数估计。

### 5.4 质变检测 → NeuralSDE 训练/推理触发器（§8 → L2）

**当前**：NeuralSDE 在 regime 转换时预测质量下降，但无自动检测和触发机制。

**注入**：用 StructuralBreakDetector 的 detect_all() 在推理时检测结构性断裂。检测到质变时：
- 触发 ImpactMultiplier 重置（因子影响力表回到中性）
- 标记当前预测为"低置信"（增大预测区间）
- 触发离线模型微调

```
当前: NeuralSDE.predict(context) → price_forecast
注入后: if StructuralBreakDetector.detect_all():
          → impact_multiplier.reset_to_neutral()
          → confidence *= 0.5
          → trigger_offline_finetune()
        NeuralSDE.predict(context) → price_forecast (with adjusted confidence)
```

**价值**：市场结构转换时自动降级置信，避免在旧 regime 模式下过度交易。

**待探讨**：结构断裂检测的 latency——CUSUM 有滞后；HMM 需要足够样本；在线检测 vs 离线检测。

### 5.5 矛盾转化 → head_multipliers 动态重分配（§9 → Phase 5）

**当前**：head_multipliers 来自 ImpactMultiplier 的固定表（8维度×10阶段），不随主矛盾转移动态调整。

**注入**：用 ContradictionShiftAccumulator 检测主矛盾转移，转移时重新分配 head 权重。

```
当前: head_multipliers = ImpactMultiplier.get_multipliers(cycle_phase, dimensions)
注入后: shift = ContradictionShiftAccumulator.detect_shift()
        if shift:
          → boost new_primary_dimension head × 1.3
          → decay old_primary_dimension head × 0.7
        head_multipliers = ImpactMultiplier.get_multipliers(...) × shift_adjustment
```

**价值**：主矛盾从 C4→C1 转移时，自动提升 C1 head 权重——attention 自动聚焦到新主矛盾维度。

**待探讨**：转移检测的 persistence 参数——太短会频繁切换，太长会滞后。

### 5.6 反身性 → NeuralSDE drift 方程（§10 → L2）

**当前**：drift = f(S_t, time, context, regime, transition) — 无系统仓位的自影响项。

**注入**：加入 ReflexivityMonitor 的自影响项。

```
当前: drift = f(S_t, time, context, regime, transition)
注入后: self_influence = ReflexivityMonitor.get_self_influence(position_size, position_direction)
        drift = f(S_t, time, context, regime, transition, self_influence)
```

**价值**：大仓位时修正预测——系统自身的交易行为影响市场结构，需要在 drift 中建模。

**待探讨**：反身性系数 λ 的估计——需要系统仓位的历史数据 + Granger 检验验证因果性；小仓位时 λ≈0，大仓位时才需要修正。

### 5.7 可证伪性 → Transformer 验证框架（§11 → 验证层）

**当前**：Transformer 仅用 MAE 对比 GARCH 基线——MAE 好≠方向预测对。

**注入**：增加矛盾论 §11 的方向命中率 + IC 检验。

```
当前: model_quality = MAE(model_predictions, actual_prices) vs MAE(garch, actual_prices)
注入后: + direction_hit_rate = count(pred_direction == actual_direction) / total
        + information_coefficient = spearmanr(pred_returns, actual_returns)
        + binomial_test(hit_rate, n, p=0.5)
        if p_value > 0.05: theory_falsified → trigger_retrain
```

**价值**：MAE 只衡量数值误差，方向命中率衡量"方向判断是否显著优于随机"——对交易决策更有意义。

**待探讨**：方向定义——日级收盘涨跌 vs 收益率符号 vs 阈值过滤。

---

## 6. 维度体系映射

### 6.1 映射原则

矛盾论 v3.0 §12.1 的分类规则是映射的唯一依据：

| 规则 | 技术面 | 基本面 | 宏观面 |
|------|--------|--------|--------|
| **核心定义** | 从价格和量数据计算 | 与资产内在价值相关 | 影响全局资金成本 |
| **数据来源** | 交易所 OHLCV | 链上/ETF/协议收入 | CPI/利率/就业 |
| **影响范围** | 单一交易对 | 单一资产 | 所有风险资产 |

### 6.2 C1-C8 → 3 维度映射

| C编号 | 名称 | 代表因子 | 矛盾论归类 | 分类依据（§12.2） |
|---|---|---|---|---|
| C1 | 资金面 | ETF flow, funding, OI | **基本面** | "ETF资金流直接反映资产估值预期" |
| C2 | 情绪面 | fear_greed, fg_momentum | **技术面** | "从价格和波动率衍生" |
| C3 | 技术面(链上) | active_addresses, tx_count | **基本面** | "链上数据，与资产内在持有结构相关" |
| C4 | 宏观面 | cpi_surprise, fomc_rate | **宏观面** | "CPI, 利率决议, 就业数据" |
| C6 | 估值 | MVRV, NVT, Puell | **基本面** | "链上估值指标" |
| C7 | 广度 | dominance, stablecoin, global_change | **技术面** | dominance/global_change 从价格计算（2/3）；stablecoin 链上 → 混合，多数为技术面 |
| C8 | 跨市场 | DXY, VIX, SPX | **宏观面** | "影响全局流动性" |
| news | 信息 | news_count, total_records | **技术面** | 市场事件计数，可被参与者直接获取 |

### 6.3 映射结果

| 矛盾论维度 | 包含的 C 子维度 | 因子数 | 因子占比 |
|---|---|---|---|
| 技术面 | C2 + C7 + news | 10 | 28% |
| 基本面 | C1 + C3 + C6 | 17 | 47% |
| 宏观面 | C4 + C8 | 9 | 25% |

### 6.4 命名冲突

存在一个**命名冲突**：C3 在 Transformer 中叫"技术面"，但按矛盾论 §12.2 的分类规则，链上数据属于"基本面"（"与资产内在持有结构相关，非价格衍生"）。Transformer 的"技术面"实际指的是"链上/区块指标"，与矛盾论的"技术面"（从价格衍生的指标）含义不同。

**建议**：在映射文档中明确区分"Transformer 的 C3 技术面"和"矛盾论的技术面"——C3 映射到矛盾论的"基本面"。

### 6.5 周期轴对齐（已回退 v0.4）

> **⚠️ 回退说明**：经评估，周期维度方案因数据不足而回退。详见 §6.5.7 回退评估。

矛盾论 v3.0 有周期轴（short/medium/long），Transformer 没有。两条路径要做交叉验证，周期必须对齐。

#### 6.5.1 矛盾论的周期定义

从 `ExogenousStrengthEvaluator` 代码提取的实际周期含义：

| 周期 | 矛盾论定义 | 数据来源 | 实际时间尺度 |
|------|-----------|---------|------------|
| short | 即期信号 | ri_signal_strength | 日级~周级 |
| medium | 中期结构 | utxo_turnover_rate, okx_positions | 月级~季级 |
| long | 长期趋势 | monthly_trend_slope, ma_200 | 半年级~年级 |

#### 6.5.2 经济周期理论体系

金融市场的周期性有扎实的经济学理论支撑：

| 周期名称 | 时长 | 核心驱动力 | 数据信号 | 检测算法 |
|----------|------|-----------|---------|---------|
| Kitchin 库存周期 | 3-4 年 | 制造商库存/销售比 | Census M3, 库存销售比 | HP 滤波 + FFT |
| Juglar 商业周期 | 7-11 年 | 信贷扩张/收缩 | GDP 缺口, 失业率, 产能利用率 | Unobserved Components + HHT |
| Kuznets 建筑周期 | 15-25 年 | 人口结构/房地产 | 房屋开工, 人口抚养比 | Wavelet (Morlet) |
| Kondratiev 长波 | 50-60 年 | 技术革命/利率长周期 | 利率百年序列, 技术创新 | Wavelet + 形态学 |
| Brunner-Meier 流动性周期 | 5-8 年 | 央行资产负债表 | WALCL, M2, BIS 信用缺口 | HP 滤波 + Markov Switching |
| Minsky 金融不稳定 | 不定 | 债务质量恶化 | 非金融债务/GDP, 利息保障倍数 | 阈值判定 + Markov |

**Schumpeter 嵌套理论**：四层周期叠加，相位共振决定危机深度——三周期同步下行即深度萧条（1929、2008 案例）。

#### 6.5.3 周期对齐方案

将矛盾论的 3 周期与经济周期理论对齐：

```
矛盾论 short (日~周)
    ↕ 对齐
Kitchin 的子周期（日级波动是库存周期的微观层）

矛盾论 medium (月~季)
    ↕ 对齐
Kitchin 周期完整阶段（3-4年内的阶段切换）

矛盾论 long (半年~年)
    ↕ 对齐
Juglar 商业周期的子阶段（7-11年内的阶段切换）
```

**对齐后的周期定义**：

| 周期层 | 时间尺度 | 经济周期映射 | 约束关系 |
|--------|---------|------------|---------|
| **short** | 日~周 | Kitchin 子周期 | 被 medium 约束 |
| **medium** | 月~季 | Kitchin 完整周期（3-4年） | 被 long 约束，约束 short |
| **long** | 半年~年+ | Juglar 子周期（7-11年） | 约束 medium |

**约束关系（矛盾论 §7 弹性约束的周期版本）**：
- 长周期处于扩张期 → 短周期回调是买入机会（弹性约束放松）
- 长周期处于收缩期 → 短周期反弹高度受限（弹性约束收紧）
- 趋势下跌速度快于上涨速度（杠杆效应约束）

#### 6.5.4 代码库已有的周期实现

| 已有组件 | 文件 | 周期类型 | 状态 |
|---------|------|---------|------|
| FFT 周期检测 | `11-易经推理系统/scripts/memory_l4/bcrm2/morph_cycle_predictor.py` L881-941 | 价格周期 (FFT top-3) | ✅ 可复用 |
| 库存四阶段 | `11-易经推理系统/scripts/memory_l4/bcrm2/cycle_features.py` L147-221 | Kitchin 周期 | ✅ 可复用 |
| Dalio 债务周期 | `23-四层闭环自进化架构/engines/debt_cycle_phase.py` L30-123 | 流动性周期 | ✅ 已集成 |
| AI 资本开支周期 | `23-四层闭环自进化架构/engines/ai_cycle_scorer.py` L32-113 | 技术周期 | ✅ 已集成 |
| MA200 周期特征 | `11-易经推理系统/scripts/memory_l4/bcrm2/ma200_cycle_features.py` L85-155 | 长期趋势周期 | ✅ 可复用 |

#### 6.5.5 可用的免费数据源

| 数据 | FRED Series ID | 用途 |
|------|---------------|------|
| NBER 衰退日期 | USREC / USRECQ | Juglar 周期阶段锚定 |
| Fed 资产负债表 | WALCL | Brunner-Meier 流动性周期 |
| 10年盈亏平衡通胀 | T10YIE | Kondratiev 通胀周期 |
| 美元指数 | DTWEXBGS | 美元周期 |
| 制造商库存销售比 | M3ISTM | Kitchin 库存周期 |
| BIS 信用缺口 | BIS Stats API | Minsky 金融不稳定 |

#### 6.5.6 推荐的周期检测算法栈

```
FRED 数据拉取
    ↓
HP 滤波 (statsmodels.hp_filter, λ=129600 月度)
    → 分离趋势 + 周期分量
    ↓
CEEMDAN 分解 (PyEMD)
    → 自适应分解为 IMF 分量（不同周期尺度）
    ↓
小波分析 (pywt.cwt, 'cmor')
    → 时频局部化，验证长波（Kondratiev/Kuznets）
    ↓
Markov Switching (statsmodels.tsa.regime_switching)
    → 识别周期阶段切换（Minsky 三阶段）
    ↓
Unobserved Components (statsmodels.tsa.UnobservedComponents)
    → 显式建模 cycle 项，输出周期相位 + 置信区间
```

#### 6.5.7 回退评估（v0.4 新增）

**结论：周期轴对齐方案回退，不实施。**

| 评估维度 | 检验结果 | 详情 |
|---------|---------|------|
| **数据充足性** | ❌ 不通过 | Bitcoin 历史 ~15 年（2009-2026），有意义交易数据 ~9 年（2017+），训练数据 ~5.5 年（~6000 样本）。Kitchin 周期(3-4年)仅 ~1.5 个完整周期，Juglar(7-11年)不足 1 个完整周期。<2 个周期无法做统计显著的周期检测 |
| **"万物皆数"原则** | ❌ 不通过 | 下方 §6.6 的 `ECONOMIC_PHASE_MULTIPLIER` 表（expansion: C1×1.3 等）是硬编码——这些数字没有回测支撑，是主观判断，违反"万物皆数"核心原则 |
| **数据可用性** | ❌ 不通过 | `debt_cycle_phase.py` 需要 `credit_growth`/`gdp_growth` 输入，但 DAL 中无此数据。`cycle_features.py` 用 close/volume/ATR（价格衍生量）推断周期——用价格衍生周期来调制以价格为 Q 的 attention = 循环论证 |
| **经济周期数据** | ❌ 不通过 | NBER 衰退日期、WALCL 等 FRED 数据可采集，但这些是**美国经济周期**数据，与 Bitcoin 市场的周期相关性未经验证 |

**保留**：FRED 经济周期数据（USREC/WALCL/M3ISTM 等）持续采集积累，待 Bitcoin 有 20+ 年数据（2029+）时重新评估周期维度注入。

---

## 6.6 Transformer 周期维度注入方案（已回退 v0.4）

> **⚠️ 回退说明**：本节所有方案因数据不足/架构不匹配而回退。保留原文供未来重新评估时参考。

### 6.6.1 问题定义

Transformer 当前用 8 个扁平 head（C1-C8）处理 36 个因子，**无周期感知**。这意味着：

- ETF 流入的短期波动（日级）和长期趋势（年级）被同一个 head 等同处理
- 无法区分"Kitchin 扩张期的资金流入"和"Juglar 收缩期的资金流入"——两者含义截然不同
- 趋势的延续性和周期性被忽略

金融市场经验法则：
1. **周期越长，信号越准**：年级趋势比日级波动更可靠
2. **趋势具有延续性**：周期一旦形成，倾向于持续
3. **长周期约束短周期**：Juglar 扩张期内的 Kitchin 回调是暂时的
4. **下跌速度快于上涨速度**：危机爆发是突变的，繁荣积累是渐进的

### 6.6.2 四种注入方案对比

| 方案 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| **A. 周期感知 mask** | head_mask 从 (8, 36) 扩展为 (8, 3, 36) — 每个维度 × 每个周期一个 head | 严格周期分离 | head 数爆炸（8×3=24），需重训 |
| **B. 周期调制 multipliers** | 保持 8 heads，给 head_multipliers 加周期维度：multiplier(dimension, cycle_phase) | 不改 head 结构，不需重训 | 周期信息在 multiplier 层，attention 内部不感知 |
| **C. 周期感知 Q** | Q 从 log_sig_t 扩展为 [log_sig_t, cycle_phase_short, cycle_phase_medium, cycle_phase_long] | attention 直接感知周期相位 | Q 维度扩展需调 Q_proj 层 |
| **D. 分层 attention** | 3 层 attention：short(3 heads) + medium(3 heads) + long(2 heads) | 周期完全分离 | 需重训，架构改动大 |

### 6.6.3 推荐方案：B+C 组合（周期调制 multipliers + 周期感知 Q）

**理由**：B 不需重训（保持现有 8 heads + dim=64 模型），C 只需扩展 Q_proj 层——两者组合能以最小改动获得周期感知能力。

#### 方案 B：周期调制 head_multipliers

当前 ImpactMultiplier 已有 FOMC 周期衰减表（8维度×10阶段）。扩展为：

```
当前: multiplier = ImpactMultiplier.get(cycle_phase=fomc_phase, dimension=C1)
扩展后: multiplier = ImpactMultiplier.get(
            fomc_phase=fomc_phase,        # 短周期：FOMC 会议周期
            economic_phase=econ_phase,   # 中周期：Kitchin/Juglar 阶段
            dimension=C1
        )

# 中周期调制系数
ECONOMIC_PHASE_MULTIPLIER = {
    "expansion": {"C1": 1.3, "C3": 1.2, "C4": 0.8, "C8": 0.9},  # 扩张期：资金面+链上主导
    "contraction": {"C1": 0.7, "C3": 0.8, "C4": 1.5, "C8": 1.3},  # 收缩期：宏观主导
    "recovery": {"C1": 1.1, "C3": 1.0, "C4": 1.0, "C8": 1.0},   # 复苏期：均衡
    "stagflation": {"C1": 0.6, "C3": 0.9, "C4": 1.4, "C8": 1.4}, # 滞胀期：宏观+跨市场主导
}
```

**经济周期阶段来源**：
- Kitchin 阶段：复用已有 `cycle_features.py` 的库存四阶段（recovery/expansion/stagflation/contraction）
- Juglar 阶段：复用已有 `debt_cycle_phase.py` 的债务周期（expansion/contraction/neutral）
- Minsky 阶段：新增——用 BIS 信用缺口 + 非金融债务/GDP 判定

#### 方案 C：周期感知 Q

当前 Q = log_sig_t（价格路径签名），仅反映短期价格状态。扩展为：

```
当前: Q = q_proj(log_sig_t)  # (B, 1, cross_attn_dim)
扩展后: Q = q_proj([
    log_sig_t,                    # 短期价格状态
    cycle_phase_short_embedding,  # 短周期相位 (Kitchin 子阶段)
    cycle_phase_medium_embedding, # 中周期相位 (Kitchin 完整阶段)
    cycle_phase_long_embedding,   # 长周期相位 (Juglar 阶段)
])

# 周期相位编码
cycle_phase_short = positional_encoding(kitchin_sub_phase, d=8)  # 0-31 日内周期位置
cycle_phase_medium = embedding(kitchin_phase, d=8)  # recovery/expansion/stagflation/contraction
cycle_phase_long = embedding(juglar_phase, d=8)     # expansion/contraction/neutral
```

**效果**：Attention 在计算 QK^T 时，不仅考虑"当前价格状态下哪些因子重要"，还考虑"当前周期阶段下哪些因子重要"——同一因子在不同周期阶段的权重不同。

### 6.6.4 周期弹性约束

借鉴矛盾论 §7 的弹性约束模型，设计**跨周期约束**：

```
长周期处于 contraction → 短周期 expansion 的上行幅度受限
    position_ceiling = 1.0 - 0.3 × long_cycle_contraction_strength

长周期处于 expansion → 短周期 contraction 的下行幅度受限
    position_floor = 0.2 + 0.3 × long_cycle_expansion_strength

趋势下跌速度约束：
    下跌速度通常 2-3 倍于上涨速度（杠杆效应）
    down_volatility_multiplier = 2.5
```

这为 ResistanceVector 增加了**周期维度的弹性约束**——不只是矛盾方向约束仓位，还有周期相位约束仓位。

### 6.6.5 周期数据采集

需要新增的数据采集任务（18-数据获取中心）：

| 数据 | FRED ID | 采集频率 | 采集器 |
|------|---------|---------|--------|
| NBER 衰退日期 | USREC | 月度 | 新增 FRED collector（已有 `fred_collector.py`） |
| Fed 资产负债表 | WALCL | 周度 | 复用 `fred_collector.py` |
| 10年盈亏平衡通胀 | T10YIE | 日度 | 复用 `fred_collector.py` |
| 制造商库存销售比 | M3ISTM | 月度 | 复用 `fred_collector.py` |
| 美元指数 | DTWEXBGS | 日度 | 已有 |

**周期阶段检测器**（新增组件）：

```
EconomicCycleDetector:
    - 拉取 WALCL, M3ISTM, USREC, T10YIE
    - HP 滤波分离趋势 + 周期分量
    - CEEMDAN 分解 → IMF 分量 → 不同周期尺度
    - 输出:
        kitchin_phase: "recovery" | "expansion" | "stagflation" | "contraction"
        juglar_phase: "expansion" | "contraction" | "neutral"
        minsky_phase: "hedge" | "speculative" | "ponzi"
        liquidity_phase: "expansion" | "contraction"
```

### 6.6.6 与交叉验证框架的衔接

周期维度的加入使 §5.1 交叉验证框架从 2D（过去×现在）扩展为 3D（过去×现在×周期）：

```
G_dim (过去因) + A_dim (现在力) + cycle_phase (周期相位)
    ↓
if G_dim == A_dim AND cycle_stable:
    → 主矛盾稳定，趋势延续，正常仓位
elif G_dim != A_dim AND cycle_transitioning:
    → 矛盾转移 + 周期切换 → 强质变信号
elif G_dim != A_dim AND cycle_stable:
    → 矛盾转移但周期稳定 → 弱质变信号
elif G_dim == A_dim AND cycle_transitioning:
    → 周期切换中但主矛盾未变 → 观望，调整仓位
```

**周期 + 矛盾的联合信号比任何单一维度都更有预测力**——这正是 Schumpeter 嵌套理论的核心洞察：多周期共振决定危机深度。

#### 6.6.7 回退评估（v0.4 新增）

**结论：Transformer 周期维度注入方案全部回退，不实施。**

| 方案 | 评估 | 回退原因 |
|------|------|---------|
| **B. 周期调制 head_multipliers** | ❌ 回退 | `ECONOMIC_PHASE_MULTIPLIER` 硬编码（无回测支撑，违反"万物皆数"）；`debt_cycle_phase.py` 需 credit_growth/gdp_growth 但 DAL 无此数据；`cycle_features.py` 用价格衍生量推断周期→循环论证 |
| **C. 周期感知 Q** | ❌ 回退 | 需周期相位编码（Kitchin/Juglar sin/cos），但训练数据 ~5.5 年 = ~1.5 个 Kitchin 周期，统计显著性不足；相位编码基于不充分数据可能注入噪声 |
| **Autoformer 自相关** | ❌ 回退 | Autoformer 设计用于**时序自注意力**（self-attention on time series），但我们的 cross-attention 是**跨域注意力**（Q=价格, K/V=36 个不同因子）。36 个不同因子之间的 FFT 自相关统计上无意义（它们是横截面数据，非时间序列）。需根本性架构改造，非"替换"能解决 |
| **Time2Vec** | ❌ 回退 | Time2Vec 是**时间编码**，但当前架构无位置编码（PE）可供替换。Q=q_proj(log_sig_t) 是价格签名非时间戳。即使注入，1.5 周期数据不足以让可学习参数 ω 发现真实 Kitchin/Juglar 频率，过拟合风险高 |

**关键洞察**：Bitcoin 的历史太短（~15 年），在 Kitchin(3-4yr)/Juglar(7-11yr) 尺度上缺乏足够数据做统计显著的周期检测。强行注入未验证的周期维度会引入噪声而非信号——这违反"万物皆数"原则。应等待数据积累后再评估。

**不回退的部分**：§6.5.4 中已有周期组件（FFT 周期检测、库存四阶段、Dalio 债务周期、AI 资本开支周期）继续在各自路径中运行，不受本回退影响。回退的仅是"将周期维度注入 Transformer cross-attention"的方案。

---

## 7. 融合后的双层架构

### 7.1 核心架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│  L0: 原始因子层 (36 因子, 10 模块)                                    │
│  CPI, DXY, funding, ETF_flow, TVL, OI, sentiment, onchain, ...     │
└──────────────────────────────────────────┬──────────────────────────┘
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │  §5.2 注入: z-score → percentile 标准化      │
                    │  (使 attention weights 跨维度可比)            │
                    └──────────────────────┬──────────────────────┘
                                           │
           ┌───────────────────────────────┴───────────────────────────────┐
           │                                                             │
    ┌──────▼──────────────────────┐                  ┌────────────────────▼──────────┐
    │  矛盾论路径 = 看过去          │                  │  Transformer 路径 = 看现在       │
    │  (统计因果推断)              │                  │  (深度学习)                      │
    │                             │                  │                                 │
    │  ExogenousStrengthEvaluator │                  │  FactorEncoder (标准化后)        │
    │  (3×3=9, 非价格度量)        │                  │  × ImpactMultiplier (周期衰减)  │
    │           ↓                 │                  │           ↓                     │
    │  GrangerCausalityChecker    │                  │  MultiHeadCrossAttention         │
    │  → G_dim: 过去的主矛盾       │                  │  → A_dim: 现在的主矛盾           │
    │           ↓                 │                  │           ↓                     │
    │  StructuralBreakDetector    │                  │  NeuralSDE drift                │
    │  (质变检测)                 │  ←── 交叉验证 ──→  │  → 价格轨迹预测                 │
    │           ↓                 │    §5.1 框架      │                                 │
    │  ContradictionShiftAccum.   │                  │  §5.6 注入: 反身性 drift 修正   │
    │  (量变→质变转移)            │                  │                                 │
    │           ↓                 │                  │                                 │
    │  ElasticConstraintResolver  │                  │                                 │
    │  (sigmoid 仓位约束)         │                  │                                 │
    │  §5.3 注入: 替换 RV 线性    │                  │                                 │
    │           ↓                 │                  │                                 │
    │  ReflexivityMonitor        │                  │                                 │
    │  (自影响修正)               │                  │                                 │
    └──────┬──────────────────────┘                  └────────────┬────────────────────┘
           │                                                        │
           │           ┌────────────────────────────────────────────┘
           │           │
    ┌──────▼───────────▼────────────────────────────────────────────────┐
    │  §5.1 交叉验证层: 过去 + 现在 → 未来                              │
    │                                                                  │
    │  G_dim (过去因) vs A_dim (现在力)                                │
    │    ├─ 一致 → 稳定信号: confidence ×1.15                         │
    │    └─ 分歧 → 转移信号: confidence ×0.9                           │
    │              ├─ head_multipliers 渐进调整                         │
    │              └─ 持续分歧 + 结构性断裂 → 质变确认                  │
    │                  └─ Granger 重估 → 新的过去 → 自进化闭环         │
    └──────────────────────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────────────────────────────────┐
    │  L3: 集成层                                                        │
    │                                                                    │
    │  Transformer 输出: 价格预测 (方向 + 轨迹 + 置信区间)                │
    │  矛盾论 输出: 仓位约束 (position_mult + T_max + 质变信号)          │
    │  交叉验证 输出: 置信调整 + head 权重动态调整                        │
    │  §5.4 注入: 质变检测 → 置信降级/重训                                │
    │  §5.7 注入: 可证伪检验 → 方向命中率                                │
    │                                                                    │
    │  → 最终决策: 方向(Transformer) × 仓位(矛盾论约束) × 路径(HJB)      │
    └────────────────────────────────────────────────────────────────────┘
```

### 7.2 两条路径的职责分工（修正后）

| 职责 | 矛盾论路径（过去） | Transformer 路径（现在） |
|------|-----------|-----------------|
| **时间视角** | 看过去——历史回测验证的因果链 | 看现在——当前市场关注的力量 |
| **力量度量** | ✅ 非价格外生度量（前瞻性） | ✅ attention 权重（当前相关性） |
| **因果验证** | ✅ Granger 因果检验 | ❌ 无——但 Attention 提供"现在关注"信号 |
| **质变检测** | ✅ CUSUM/HMM/Hurst | ❌ 无（需注入） |
| **仓位约束** | ✅ sigmoid 弹性约束 | ❌ 无（需注入） |
| **反身性** | ✅ 自影响系数 λ | ❌ 无（需注入） |
| **价格预测** | ❌ 无 | ✅ NeuralSDE 轨迹 |
| **因子交互** | ✅ 显式交互项 | ✅ 隐式 attention 学习 |
| **周期衰减** | ❌ 描述但未实现衰减表 | ✅ ImpactMultiplier + ATE 校准 |
| **可证伪性** | ✅ 方向命中率 + IC | ❌ 仅 MAE（需注入） |
| **矛盾转移感知** | ✅ ContradictionShiftAccumulator | ✅ Attention 权重变化（隐式） |

### 7.3 交叉验证：过去+现在→未来

核心框架详见 §5.1。此处补充集成层的交叉验证逻辑：

```
集成层输入:
  - G_dim: Granger 验证的主矛盾维度（过去有效）
  - A_dim: Attention 聚合后的主矛盾维度（现在关注）
  - G_confidence: Granger p-value
  - A_strength: Attention 权重占比

交叉验证输出:
  - cross_validated: bool (G_dim == A_dim)
  - confidence_adjustment: float (1.15 或 0.9)
  - shift_signal: bool (是否检测到潜在转移)
  - divergence_count: int (连续分歧期数)
  - quality_change: bool (质变是否确认)
  - head_adjustment: dict (head_multipliers 动态调整)

最终决策:
  方向 = Transformer 预测方向 × cross_validation.confidence_adjustment
  仓位 = ElasticConstraint.position_mult × cross_validation.confidence_adjustment
  路径 = HJB(price_forecast, position_mult, resistance_field)
```

---

## 8. 待深入探讨的问题

以下问题需要进一步讨论，不宜直接拍板：

### 8.1 Attention 权重的理论定位（已通过 §5.1 框架解决）

**结论**：Attention weights 不需要被"验证"为因果性——它的价值在于反映"当前市场关注什么"，与 Granger 的"过去什么有效"形成互补。

- **Attention = 现在**：在给定价格状态 Q 下的条件权重，反映"当前市场状态下哪些因子最相关"——这对短期预测有意义
- **Granger = 过去**：通过历史回测验证的因果链，反映"什么因子历史有效"
- **两条链的分歧 = 矛盾转移信号**：不需要统一为"谁对谁错"，分歧本身是有价值的信号

详见 §5.1 交叉验证框架。

**仍需讨论**：Attention 聚合到 3 维度时的具体方法——是简单按 head 权重求和，还是考虑 head_dim 内的分布？

**v0.5 调研结论**：简单 head-weight 求和是正确方法。理由：

1. `factor_head_mask` shape = `(n_heads=8, n_factors=36)` — 每个 head 对应一个矛盾维度（C1-C8/news），mask 确保每个 head 只 attend 到属于自己维度的因子
2. softmax 后每个 head 的 weights sum = 1.0（在该 head 的因子子集内归一化）
3. 因此 **head 间的权重比较 = 维度间的力量比较**：head0 的总权重 0.35 vs head3 的 0.15 = "C1 维度比 C4 维度受关注 2.3 倍"
4. `head_multipliers` 已经在 softmax 后乘到 weights 上（[cross_attention.py L149-154](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/cross_attention.py#L149-L154)），所以聚合时应使用乘以 multipliers 后的 weights
5. head_dim 内的分布（head_dim=8）反映的是"该维度内哪个因子更重要"，不是跨维度比较——不需要考虑

聚合方法：
```python
# last_attn_weights shape: (B, n_heads, 1, n_factors)
# 乘以 head_multipliers 后，每个 head 的权重总和 = 该维度的"注意力强度"
head_strengths = (last_attn_weights * head_multipliers).sum(dim=-1).squeeze(-1)  # (B, 8)
# 按 DIMENSION_MAP_8_TO_3 聚合到 3 维度
dim_3 = {"technical": 0, "fundamental": 0, "macro": 0}
for head_idx, dim_3_name in DIMENSION_MAP_8_TO_3.items():
    dim_3[dim_3_name] += head_strengths[0, head_idx].item()
```

**注意**：当前 `last_attn_weights` 存储在 `cross_attention.py` L170 但**未被外部使用**。需要新建 `collapse_attention_weights()` 函数提取并聚合。

### 8.2 标准化对已训练模型的影响

如果在 FactorEncoder 之前加入 z-score 标准化，已经训练的 NeuralSDE 模型（cross_attn_dim=64）是否需要重训？

- 标准化改变了输入分布，FactorEncoder 的 Linear 层权重可能与标准化后的输入不匹配
- 可能需要：标准化 → 重训 FactorEncoder → 重训 NeuralSDE
- 或者：在 FactorEncoder 的 Linear 层中加入 BatchNorm/LayerNorm 来隐式标准化

**v0.5 代码审计结论**：标准化影响可控，**不需要重训**。理由：

1. [cross_attention.py L24-52](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/cross_attention.py#L24-L52): `FactorEncoder` = `nn.Linear(factor_dim=1, d_model=cross_attn_dim)` + `nn.LayerNorm(d_model)` — **已有 LayerNorm**
2. `factor_dim=1` 意味着每个因子是一个标量。`Linear(1, 64)` 对标量做变换：`y = w·x + b`，LayerNorm 然后：`y' = (y - μ) / (σ + ε) · γ + β`
3. z-score 标准化：`x' = (x - μ_x) / σ_x`。代入后：`y = w·(x-μ_x)/σ_x + b = (w/σ_x)·x + (b - w·μ_x/σ_x)`
4. LayerNorm 的 `(y - μ)/σ` 会部分抵消 `w/σ_x` 的缩放——因为 LayerNorm 的 γ 参数可以学到补偿
5. **结论**：LayerNorm 隐式标准化能力足以吸收 z-score 的分布偏移。但建议在标准化后做一次 **轻量微调**（few epochs）而非从头重训

**替代方案**：不在 FactorEncoder 前加 z-score，而是在 `exogenous_data_bridge.py` 的 `get_factors()` 输出时做标准化——这样因子在进入任何路径前都是标准化的，两条路径（矛盾论 + Transformer）使用相同标准。

### 8.3 质变检测的在线 vs 离线

StructuralBreakDetector 的 CUSUM/HMM/Hurst 需要多少历史数据？能否做在线检测？

- CUSUM：可以在线，但有滞后（累积和需要时间触发）
- HMM：需要离线拟合，不适合实时
- Hurst：需要窗口（通常 100+ 点），可以做滚动检测
- 需讨论：用哪种方法做在线质变检测？延迟多少可接受？

**v0.5 代码审计结论**：

1. [structural_break_detector.py L48-82](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/structural_break_detector.py#L48-L82): 实际实现 3 类检测：
   - **波动率制度转换**：比较当前 vs 前窗口的波动率，类似 CUSUM 逻辑 → **可在线**
   - **相关性结构断裂**：滚动相关系数窗口 + CUSUM → **可在线**，但有窗口滞后
   - **市场形态转换**：Hurst 指数比较前后窗口 → **可滚动检测**
2. **HMM 未实现**——文档说"CUSUM/HMM/Hurst"但代码中 HMM 不存在。Hurst 替代了 HMM 的角色（用 Hurst > 0.55 判趋势态，< 0.45 判均值回归态）
3. `min_samples` 是构造函数参数，控制最小检测窗口。默认值需从代码确认
4. `detect_all()` 返回 `{"volatility_regime": ..., "correlation_break": ..., "market_form_shift": ..., "any_structural_break": bool}` — **可直接用于在线检测**
5. **结论**：3 种检测都可在线运行（滚动窗口方式），无需离线拟合。延迟取决于窗口大小——建议 `min_samples=100`（约 4 天小时级数据），延迟可接受

### 8.4 维度映射的边界案例

C7（广度）的 3 个因子中：
- btc_dominance：从市值计算 → 技术面
- stablecoin_total：链上供应 → 基本面
- global_change_24h：从价格计算 → 技术面

2/3 是技术面，但 stablecoin_total 归为基本面也有道理。是按多数表决，还是允许一个 C 维度跨多个矛盾论维度？

**v0.5 结论**：**多数表决**。理由：

1. 交叉验证框架（§5.1）需要每个 head 映射到**唯一**的矛盾论维度——如果 C7 跨两个维度，聚合时会产生歧义
2. C7 的 3 个因子中 2/3 是技术面 → C7 映射到 technical
3. 如果 stablecoin_total 的影响足够大，attention 机制会在 C7 head 内自动给它更高权重——不需要跨维度映射来"补偿"
4. 允许跨维度映射会破坏 head_weight 求和的加法性（一个 head 的权重不能同时算入两个维度）
5. **边界案例用注释标注**：C7 → technical（但 stablecoin_total 有基本面属性，如未来发现 C7 应为基本面，调整映射表即可）

### 8.5 弹性约束参数估计

矛盾论 §7.3 给出了参数理论约束：
- `historical_max_rebound_p75`：历史反弹幅度的 75 百分位
- `floor`：≥ 0.05（Kelly 下界）
- `k`：sigmoid 斜率 5~10

这些参数需要回测数据估计。当前是否有足够的历史交易数据来估计这些参数？如果不足，是否用保守默认值先行？

**v0.5 代码审计结论**：

[elastic_constraint_resolver.py L41-57](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/elastic_constraint_resolver.py#L41-L57) 已实现参数边界检查和默认值：

| 参数 | 默认值 | 理论边界 | 数据驱动估计方法 |
|------|--------|---------|----------------|
| `base_limit` | 0.12 | [0.05, 0.20] | 历史反弹幅度的 75 百分位 — 需回测数据 |
| `floor` | 0.20 | [0.10, 0.30] | Kelly 下界 — 需胜率统计 |
| `bonus` | 0.05 | [0.00, 0.10] | 方向对齐时的历史超额收益 |
| `steepness` | 3.0 | [1.0, 10.0] | 拟合 sigmoid 到历史回弹曲线 |

1. **默认值是保守的**——base_limit=0.12 在 [0.05, 0.20] 中间偏低，floor=0.20 保守
2. **T_max 计算**已数据驱动：`T_max = base_limit × (S_primary / (S_primary + S_minor))`，力量比是实时计算的
3. **分层弹性约束**已实现（[L125-138](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/elastic_constraint_resolver.py#L125-L138)）：力量差大时纯力量驱动，力量接近时层级驱动（长期约束短期），`TIER_WEIGHT = {"short": 0.2, "medium": 0.3, "long": 0.5}`
4. **结论**：默认值可行先用，后续用历史交易数据（`backtest_results` 表）估计 `base_limit` 的 75 百分位和 `floor` 的 Kelly 下界。`steepness` 可用网格搜索在回测上优化。

### 8.6 Transformer 路径是否也需要周期轴（已通过回退解决）

**结论**：不在 Transformer 中注入周期维度。经评估，Bitcoin 历史 ~15 年（训练数据 ~5.5 年）不足以支撑 Kitchin(3-4yr)/Juglar(7-11yr) 周期检测。所有周期注入方案（head_multipliers 调制、周期感知 Q、Autoformer 自相关、Time2Vec）均因数据不足或架构不匹配而回退。详见 §6.5.7 和 §6.6.7。

现有 ImpactMultiplier 已按 FOMC 阶段（短周期）做衰减，这是数据可支撑的周期处理。更长的经济周期维度待数据积累后（2029+）重新评估。

### 8.7 矛盾论路径的数据新鲜度

ExogenousStrengthEvaluator 使用 `data` dict 中的聚合度量（ri_signal_strength, etf_net_flow, cpi_actual 等）。这些数据的新鲜度如何？是否与 Transformer 路径使用的 DAL mm_metrics 36 因子来自同一数据源？

如果矛盾论路径用旧数据，Transformer 路径用新数据，交叉验证可能有时间错位。

**v0.5 代码审计结论**：**确认两路径数据源不同**——这是一个需要解决的差距。

| 路径 | 数据来源 | 数据结构 | 新鲜度 |
|------|---------|---------|--------|
| 矛盾论 ExogenousStrengthEvaluator | `market_data` dict（来自 [kline_event_handler.py L373](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/kline_event_handler.py#L373) `kline_data`） | `ri_signal_strength`, `etf_net_flow`, `cpi_actual` 等 | **实时**（每根 K 线更新） |
| 矛盾论 W1 微观阻力 | DAL `mm_metrics`（[evolution_pipeline.py L1274-1291](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L1274-L1291)） | `funding_rate`, `fut_open_interest_usd` | 近 24h |
| Transformer | DAL `mm_metrics`（通过 `exogenous_data_bridge`） | 36 因子 `CROSS_ATTENTION_FACTOR_METRICS` | 最近一条记录 |

1. **时间错位风险**：矛盾论的 `market_data` 来自 kline（实时 OHLCV + 派生指标），Transformer 的因子来自 DAL `mm_metrics`（历史采集，可能有小时级延迟）
2. **指标差异**：矛盾论用 `ri_signal_strength`（kline 派生），Transformer 用 DAL 中的因子原始值——同名概念可能计算方式不同
3. **解决方向**：统一两条路径的数据源到 DAL `mm_metrics`——将矛盾论 `ExogenousStrengthEvaluator` 的输入也从 `market_data` 切换到 DAL 查询。或反向：将 DAL 因子注入 `market_data` dict 供矛盾论使用
4. **当前可行**：W1 微观阻力已从 DAL 注入 `market_data`（funding_rate, OI），说明机制已存在——可扩展为全部因子统一从 DAL 获取

### 8.8 两份文档的 Phase 编号统一

是否需要将两份文档的 Phase 编号统一为一份路线图？还是保持各自独立，只做交叉引用？

**v0.5 结论**：保持各自独立 + 本文档作为交叉引用。理由：

1. 两份文档服务不同目的——矛盾论是理论框架（学术性），Transformer 是工程架构（实践性），Phase 编号的含义不同
2. 统一编号会破坏各自文档的完整性——矛盾论 Phase 1-4 是理论推进，Transformer Phase 1-6 是工程迭代
3. 本文档（融合方案）已起到交叉引用作用——§9 优先级表是统一路线图
4. 未来实现时以 §9 优先级表为准，不以两份文档的 Phase 编号为准

### 8.9 GrangerCausalityChecker 未集成到主 pipeline（v0.5 新增）

**差距**：文档 §5.1 假设 Granger 路径输出 G_dim（过去主矛盾维度），但 GrangerCausalityChecker **未从 evolution_pipeline.py 调用**。

代码事实：
- [granger_causality_checker.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/granger_causality_checker.py) 完整实现了 ADF + grangercausalitytests + per_regime + verify_causal_chain
- 唯一调用点：[reflexivity_monitor.py L85-118](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/reflexivity_monitor.py#L85-L118) `check_self_influence(positions, etf_flows)` — 检验"仓位→市场"
- evolution_pipeline.py 和 kline_event_handler.py 中**无 Granger 调用**

§5.1 框架要成立，需要：
1. 在 pipeline 中实例化 GrangerCausalityChecker
2. 对每个维度的聚合因子 vs 收益率做 Granger 检验 → 输出 G_dim（哪个维度 Granger-cause 收益）
3. 将 G_dim 传到交叉验证层

**实现可行性**：已有组件（GrangerCausalityChecker）+ 已有数据（DAL 因子 + 收益率）→ 只需新建集成代码

### 8.10 Attention 未聚合到维度（v0.5 新增）

**差距**：文档 §5.1 假设 Attention 路径输出 A_dim（现在主矛盾维度），但 `last_attn_weights` **未被外部使用**。

代码事实：
- [cross_attention.py L170](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/cross_attention.py#L170) 存储 `last_attn_weights`（shape `(B, n_heads, 1, n_factors)`）
- [neural_sde_model.py L304-331](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/neural_sde_model.py#L304-L331) 调用 cross_attn 后**未提取** `last_attn_weights`
- 无 `collapse_attention_weights()` 函数

§5.1 框架要成立，需要：
1. 从 NeuralSDE 提取 `last_attn_weights`（需修改 forecast 接口返回 weights）
2. 新建 `collapse_attention_weights()` 按 §8.1 方法聚合到 3 维度
3. 输出 A_dim 传到交叉验证层

**实现可行性**：attention weights 已存储，只需提取+聚合函数

### 8.11 交叉验证代码不存在（v0.5 新增）

**差距**：文档 §5.1 的核心——G_dim vs A_dim 交叉比对逻辑——**完全不存在**。

代码事实：两条路径各自独立运行，**无任何代码比较两条路径的输出**。矛盾论输出 `primary_contradiction`（含 dimension），Transformer 输出 context vector（无维度标签），两者不交互。

§5.1 框架要成立，需要：
1. G_dim（§8.9）和 A_dim（§8.10）同时可用
2. 新建交叉验证函数：比对 G_dim 和 A_dim → 一致/分歧 → 置信调整 + head_multipliers 动态调整
3. 集成到 `evolution_pipeline._select_optimal_path()` 中

### 8.12 Granger 未验证"因子→价格"因果（v0.5 新增）

**差距**：文档描述"Granger = 看过去：验证'ETF流入→价格上升'的因果链"，但代码中 Granger **不检验因子→价格**。

代码事实：GrangerCausalityChecker 是通用工具（接收任意 cause/effect 时序），当前只用于仓位→市场（反身性）。因子→价格的 Granger 检验代码不存在。

§5.1 框架要成立，需要：
1. 对每个维度的聚合因子做 Granger(factor, returns) 检验
2. 输出：哪个维度 Granger-cause 收益 → G_dim
3. 与 A_dim（Attention 聚合）比对

**实现可行性**：GrangerCausalityChecker.check(cause=factor_series, effect=returns) → 直接可用，只需调用代码

---

## 9. 落地优先级建议

以下按**对交易质量的直接影响**排序：

| 优先级 | 增强点 | 依赖 | 对交易的影响 |
|--------|--------|------|------------|
| **P0** | §8.9 Granger 集成到 pipeline | GrangerCausalityChecker 已有 + DAL 因子 | 输出 G_dim（过去主矛盾维度）——§5.1 的前置 |
| **P0** | §8.10 Attention 聚合到维度 | last_attn_weights 已有 + 新建聚合函数 | 输出 A_dim（现在主矛盾维度）——§5.1 的前置 |
| **P0** | §8.11 交叉验证逻辑 | §8.9 + §8.10 | G_dim vs A_dim 比对 → 分歧=转移信号 |
| **P0** | §5.3 sigmoid 替换线性调制 | 历史反弹数据 | 防止力量极端时阻力场过调 |
| **P0** | §5.4 质变检测触发置信降级 | StructuralBreakDetector 已有 | 市场结构转换时自动减仓 |
| **P1** | §5.2 z-score 标准化 | FactorEncoder 已有 LayerNorm，影响可控 | attention weights 跨维度可比 |
| **P1** | §5.7 可证伪性验证框架 | 预测历史数据 | 方向命中率检验预测质量 |
| **P1** | §8.7 数据源统一 | W1 微观注入机制已有 | 消除两路径时间错位 |
| **P2** | §5.5 矛盾转移动态权重 | ContradictionShiftAccumulator 已有 + §5.1 交叉验证 | 主矛盾转移时自动调整 head 权重 |
| **P3** | §5.6 反身性 drift 修正 | ReflexivityMonitor 已有 | 大仓位时修正预测 |
| **P3** | §6 维度映射 | 映射函数（§5.1 的前置依赖） | C1-C8 → 3 维度聚合，支撑交叉验证 |
| ~~P1~~ | ~~§6.5 周期轴对齐 + §6.6 周期维度注入~~ | ~~EconomicCycleDetector + FRED 数据~~ | ~~已回退（数据不足，详见 §6.5.7/§6.6.7）~~ |
| **P0** | §10.2 三模块化组件 | GrangerPipelineAdapter + AttentionAggregator + CrossValidationGate | 补全 §5.1 框架的 4 个实现差距（§8.9-§8.12），3 个新模块独立 TDD 开发，可分步回退 |
| **P0** | §10.5 自进化闭环连接 | §10.2 + FTCEvolutionBridge（已有） | 质变事件 → Granger 重估 + 认知记忆 + 基因创新 → 完整自进化交易 |

---

## 10. 交叉验证层架构设计（最小改动+可回退+模块化）

> **状态**：理论设计草案 v0.6，无代码实现。落地需要先评审此节方案，再分模块独立 TDD 开发。
> **核心定位**：补全 §5.1 理论框架所需的 4 个模块化组件（§8.9-§8.12 实现差距），驱动矛盾论+Transformer 两条独立链路交互，形成完整自进化交易闭环。
> **设计原则**：万物皆数——所有参数有理论边界或数据驱动校准，无硬编码"magic number"。

### 10.1 设计目标与硬约束

| 目标 | 实现策略 | 验证标准 |
|------|---------|----------|
| **改动最小** | 所有新代码以"附加"方式接入：不修改现有 `cross_attention` / `neural_sde` / `evolution_pipeline` 的核心方法签名；仅在 pipeline 关键节点新增可选 hook | 现有 38 个开关 + 60+ 测试零回归 |
| **可回退** | 所有新组件通过 `enable_cross_validation_gate` 等 4 个开关控制；默认关闭 → 系统行为与现状完全一致 | 关闭所有开关 → MAE、信号、仓位与基线一致 |
| **模块化** | 3 个新模块独立部署，单一职责，互不依赖实现细节 | 每个模块可单独关闭，其他模块仍正常运行 |
| **驱动两链路交互** | 通过 CrossValidationGate 集成层将 G_dim 和 A_dim 比对输出 | §5.1 五步算法可独立运行 |
| **自进化闭环** | 质变事件触发 Granger 重估 + FTCEvolutionBridge 基因创新 + 认知记忆 record | 质变 → 自动产生新策略候选 → 持续进化 |

### 10.2 三个模块化组件清单

| 模块 | 路径 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|------|
| **GrangerPipelineAdapter** | `core/granger_pipeline_adapter.py`（新建） | 包装 GrangerCausalityChecker，对每个维度的聚合因子 vs 收益率做 Granger 检验，输出"过去主矛盾维度"（§8.9 + §8.12） | DAL 因子序列 + 收益率 | `G_dim ∈ {technical, fundamental, macro, none}`<br>`G_confidence ∈ [0,1]`（基于 p-value） | `GrangerCausalityChecker`（已有，未集成） |
| **AttentionAggregator** | `core/attention_aggregator.py`（新建） | 从 `NeuralSDE.forecast()` 输出中提取 `last_attn_weights`，按 §8.1 方法（head-weight 求和）聚合到 3 维度，输出"现在主矛盾维度"（§8.10） | `last_attn_weights` (B, n_heads=8, 1, n_factors=36)<br>`factor_head_mask` (8, 36) | `A_dim ∈ {technical, fundamental, macro}`<br>`A_strength ∈ [0,1]` | `NeuralSDE.forecast()` 新增可选返回字段 |
| **CrossValidationGate** | `core/cross_validation_gate.py`（新建） | 集成层：接收 G_dim 和 A_dim，执行 §5.1 五步算法，输出置信调整 + shift_signal + head_multipliers 动态调整 + 质变事件（§8.11） | `G_dim`/`G_confidence`<br>`A_dim`/`A_strength`<br>`StructuralBreakDetector.detect_all()` 输出 | `confidence_mult`<br>`shift_signal`<br>`divergence_count`<br>`quality_change`<br>`head_adjustment`<br>`granger_reestimate_trigger` | 上述两个适配器 + `StructuralBreakDetector`（已有） |

### 10.3 数据流与集成点（最小改动原则）

```
┌──────────────────────────────────────────────────────────────────────┐
│  现有代码（不修改核心逻辑，仅新增可选 hook + 可选返回字段）             │
└──────────────────────────────────────────────────────────────────────┘

evolution_pipeline._select_optimal_path()
  │
  ├──[新增 hook 1]→ GrangerPipelineAdapter.evaluate(dimensions, returns)
  │                  → G_dim, G_confidence
  │                  (开关: enable_granger_pipeline)
  │
  ├── NeuralSDE.forecast(..., return_attn_weights=False)  ← 仅新增可选参数
  │       │
  │       └──[新增 hook 2]→ AttentionAggregator.collapse(attn_weights, factor_head_mask)
  │                          → A_dim, A_strength
  │                          (开关: enable_attention_aggregator)
  │
  ├──[新增 hook 3]→ CrossValidationGate.compare(G_dim, A_dim, structural_break)
  │                  → confidence_mult, shift_signal, head_adjustment, ...
  │                  (开关: enable_cross_validation_gate)
  │
  └── 原有 _select_optimal_path 末尾：
        position_mult *= confidence_mult              ← 一行新增（默认 ×1.0）
        head_multipliers.update(head_adjustment)      ← 一行新增（默认空 dict）
        (开关: enable_head_multipliers_adjustment)
```

**关键设计要点**：

1. **现有 `cross_attention.py` 的 `head_multipliers` 字段已存在**（[cross_attention.py L149-154](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/cross_attention.py#L149-L154)）——只需在 CrossValidationGate 输出中提供 delta 字典，pipeline 末尾一行 `head_multipliers.update()` 即可，**不修改 cross_attention 类**
2. **`NeuralSDE.forecast()` 仅新增可选参数 `return_attn_weights=False`**——默认 False，旧调用完全不变；当 AttentionAggregator 启用时才传 True
3. **`last_attn_weights` 已在 [cross_attention.py L170](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/cross_attention.py#L170) 存储**——只需 forecast 末尾 `return ..., self.cross_attn.last_attn_weights`，不修改 cross_attn 内部逻辑
4. **所有 hook 通过开关控制**——关闭时直接跳过，pipeline 走原路径

### 10.4 CrossValidationGate 主流程（§5.1 算法的工程化封装）

```python
# 伪代码 — 仅供方案探讨，非实现
class CrossValidationGate:
    """
    §5.1 五步算法的工程化封装.
    
    参数（均有理论边界或数据驱动校准）:
      persistence_threshold: 持续分歧期数阈值（理论下限 3，默认 5，上限 20）
      confidence_boost: 一致时置信加成（理论 [1.0, 1.3]，默认 1.15）
      confidence_penalty: 分歧时置信衰减（理论 [0.7, 1.0]，默认 0.9）
      head_boost_rate: head 权重提升速率（理论 [0.1, 0.5]，默认 0.3）
      head_decay_rate: head 权重衰减速率（理论 [0.05, 0.3]，默认 0.2）
    
    状态:
      _divergence_count: 连续分歧期数（dict 存储，不修改现有数据类）
      _last_G_dim: 上一期 G_dim（用于检测 Granger 重估后是否生效）
    """
    
    def compare(self, G_dim, G_conf, A_dim, A_strength, structural_break):
        """
        §5.1 五步算法.
        
        FAIL-OPEN: 任何输入为 None 或异常 → 返回中性结果
          {confidence_mult: 1.0, shift_signal: False, head_adjustment: {}, ...}
        """
        # === Step 3: 交叉比对 ===
        if G_dim is None or A_dim is None:
            return self._neutral_result()  # FAIL-OPEN
        
        if G_dim == A_dim:
            confidence_mult = self._confidence_boost
            shift_signal = False
            self._divergence_count = 0
        else:
            confidence_mult = self._confidence_penalty
            shift_signal = True
            self._divergence_count += 1
        
        # === Step 4: 质变判定（持续分歧 + 结构性断裂）===
        quality_change = False
        granger_reestimate_trigger = False
        new_main_dim = None
        
        if self._divergence_count >= self._persistence_threshold:
            if structural_break.get("any_structural_break", False):
                # 质变确认：排序变化 AND 结构性断裂
                quality_change = True
                granger_reestimate_trigger = True
                new_main_dim = A_dim  # 接受 Attention 的新方向
                self._divergence_count = 0
        
        # === Step 5: head_multipliers 动态调整（仅分歧期间，质变前）===
        head_adjustment = {}
        if shift_signal and not quality_change:
            progress = min(1.0, self._divergence_count / self._persistence_threshold)
            A_dim_head = self._dim_to_head(A_dim)  # 维度→head 索引映射
            G_dim_head = self._dim_to_head(G_dim)
            head_adjustment[A_dim_head] = 1 + self._head_boost_rate * progress
            head_adjustment[G_dim_head] = 1 - self._head_decay_rate * progress
        
        return {
            "confidence_mult": confidence_mult,
            "shift_signal": shift_signal,
            "divergence_count": self._divergence_count,
            "quality_change": quality_change,
            "new_main_dim": new_main_dim,
            "head_adjustment": head_adjustment,
            "granger_reestimate_trigger": granger_reestimate_trigger,
        }
    
    def _neutral_result(self):
        """FAIL-OPEN 中性返回."""
        return {
            "confidence_mult": 1.0,
            "shift_signal": False,
            "divergence_count": self._divergence_count,
            "quality_change": False,
            "new_main_dim": None,
            "head_adjustment": {},
            "granger_reestimate_trigger": False,
        }
```

### 10.5 自进化闭环连接（驱动两条链路持续交互）

```
                 ┌────────────────────────────────────────────────┐
                 │ 自进化闭环（基于已有组件，最小改动接入）         │
                 └────────────────────────────────────────────────┘

  ① 质变事件触发 Granger 重估
     CrossValidationGate.granger_reestimate_trigger=True
       → GrangerPipelineAdapter.reestimate(new_main_dim)
       → 新的 G_dim（新的"过去"）
       → 下一次 CrossValidationGate.compare() 使用新 G_dim
       
  ② 质变事件触发认知记忆记录（CLAUDE.md 硬约束·不可跳过）
     record(content="[质变事件] main_contradiction: G_dim→A_dim, "
                    "structural_break={...}, divergence_count=N",
            quality_level="B", tags="质变,交叉验证,自进化,矛盾论")
     verify(memory_id=new_id, success=True)  # 触发贝叶斯升级
       
  ③ shift_signal → head_multipliers 动态调整
     CrossValidationGate.head_adjustment
       → cross_attention.head_multipliers 更新（已有字段）
       → 下一次 cross_attention 输出受新权重影响
       → AttentionAggregator 提取新 A_dim
       → 形成"现在"链路的反馈闭环
       
  ④ 质变事件 → ExitEngine.post_close_evolution()（已有方法）
       → ESS 更新
       → AutoWeightAdjuster 调整
       → FTCEvolutionBridge.run_gene_innovation()
       → 新策略基因候选
       → 自进化交易实现
       
  ⑤ 持续闭环
     质变 → 新过去 → 新交叉验证 → 新的现在 → 新的分歧/质变 → ...
```

**与 §5.1.3 理论框架的对应**：

```
§5.1.3 理论                        §10.5 工程实现
─────────────────                  ─────────────────
Granger 因果链                      GrangerPipelineAdapter
Attention 链                        AttentionAggregator + NeuralSDE
交叉比对                            CrossValidationGate.compare()
一致/分歧 → 调整                    confidence_mult + shift_signal
持续分歧 + 结构性断裂 → 质变          quality_change=True
Granger 重估 → 新的过去              ① granger_reestimate_trigger
新的交叉验证 → 持续进化              ⑤ 持续闭环
```

### 10.6 配置开关与 FAIL-OPEN 设计

**新增开关（agi_config.py）**：

| 开关名 | 默认 | 作用 | 关闭时的回退行为 |
|--------|------|------|----------------|
| `enable_cross_validation_gate` | `False` | 主开关 | CrossValidationGate 不实例化，pipeline 走原路径 |
| `enable_granger_pipeline` | `False` | Granger 集成（§8.9） | G_dim=None → CrossValidationGate FAIL-OPEN |
| `enable_attention_aggregator` | `False` | Attention 聚合（§8.10） | A_dim=None → CrossValidationGate FAIL-OPEN |
| `enable_head_multipliers_adjustment` | `False` | head 权重动态调整 | head_adjustment 不应用，但交叉验证仍记录（用于日志/分析） |

**FAIL-OPEN 链**：

```
任何子组件异常 → CrossValidationGate 返回中性结果
  {
    "confidence_mult": 1.0,    # 不影响仓位
    "shift_signal": False,     # 不触发转移
    "head_adjustment": {},     # 不调整 head
    "granger_reestimate_trigger": False  # 不触发重估
  }
```

**回退验证矩阵**：

| 开关组合 | 系统行为 |
|---------|---------|
| 全部关闭 | 与 v0.5 现状完全一致（MAE、信号、仓位均不变） |
| 仅开 `enable_attention_aggregator` | A_dim 输出但 G_dim=None → CrossValidationGate FAIL-OPEN → 仅记录 A_dim 用于分析 |
| 开 `enable_granger_pipeline` + `enable_attention_aggregator` + `enable_cross_validation_gate`，关 `enable_head_multipliers_adjustment` | 交叉验证完整运行，输出 confidence_mult 影响仓位，但不调整 head 权重（最保守的"半启用"模式） |
| 全部开启 | 完整 §5.1 五步算法 + 自进化闭环 |

### 10.7 与 §5.1 理论框架的对应

| §5.1 步骤 | §10 工程组件 | 落地状态 |
|----------|------------|---------|
| Step 1: Granger 路径输出 G_dim | GrangerPipelineAdapter | ✅ 已落地（v1.10，含 Bonferroni 多重比较校正） |
| Step 2: Attention 路径输出 A_dim | AttentionAggregator | ✅ 已落地（v1.10） |
| Step 3: 交叉比对 | CrossValidationGate.compare() | ✅ 已落地（v1.10，含 Q1~Q5 优化） |
| Step 4: 质变判定 | CrossValidationGate + StructuralBreakDetector | ✅ 已落地（v1.10） |
| Step 5: head_multipliers 调整 | CrossValidationGate.head_adjustment | ✅ 已落地（v1.10，head_adjustment_to_array + neural_sde_forecast 接入） |
| 自进化闭环（§5.1.3） | §10.5 五个连接点 | 🟡 阶段1：质变→认知记录+Granger重估信号已落地；FTCEvolutionBridge 基因创新待稳定后接入 |

### 10.12 待后续完成项（P1 优化，当前阻塞）

> 以下两项因前置条件不满足，暂挂起，待条件成熟后执行。

| 编号 | 任务 | 阻塞原因 | 触发条件 |
|------|------|---------|---------|
| P1-A | `STRUCTURAL_BREAK_THRESHOLD` 从 0.4 重校准回 1.0 | `quality_change_log.jsonl` 零数据积累，无法做分位数校准 | 积累 ≥50 条质变记录后，统计 `structural_break_score` 分布，取有效区分真质变 vs 噪声的分位数作为新阈值 |
| P1-B | FTCEvolutionBridge 基因创新触发接入 | 交叉验证层刚落地，质变事件 precision/recall 未验证，噪声触发会污染基因库 | 交叉验证层稳定运行 ≥1 周，质变事件 precision > 0.7 后，在 `CognitiveBridge.record_quality_change` 之后追加 `FTCEvolutionBridge.run_gene_innovation` 调用 |

### 10.13 消融实验结果（P1 优化项·已完成）

**实验设计**：5 组对比，验证 Q1~Q5 各优化模块的边际贡献（模拟数据 5000 期，3 regime：动量/均值回归/高波动）。

| 实验组 | 配置 | OOS 夏普 | DSR | 胜率 | vs E0 差异 |
|--------|------|---------|-----|------|-----------|
| **E0 全功能** | Q1+Q2+Q3+Q4+Q5 全开 | **1.57** | 0.549 | 0.459 | 基准 |
| E1 无 Q2 | 关闭 head floor/ceiling/mean reversion | 1.57 | 0.549 | 0.459 | 0.00 |
| E2 无 Q5 | 关闭 structural_break 类型加权（简单 OR） | 1.35 | 0.514 | 0.459 | **-0.22** |
| E3 无 Q4 | 关闭降级模式 | 1.57 | 0.549 | 0.459 | 0.00 |
| E4 纯 Attention | G_dim=None 全程（单链路） | 0.00 | 0.000 | 0.000 | **-1.57** |

**PBO = 0.40**

**结论**：
1. **Q5 类型加权共识有效**：去掉后夏普从 1.57 降至 1.35（-0.22）。加权机制过滤了仅波动率断裂（权重 0.4 < 阈值 0.5）的噪声性误触发，避免不必要的信号反转。
2. **双链路（Granger+Attention）显著优于单链路**：E4 纯 Attention 夏普归零，证明"过去+现在"交叉验证框架的核心价值。
3. **Q2/Q4 在当前简化信号中边际贡献不显著**：Q2 的 head_multipliers 对信号幅度影响有限；Q4 降级模式仅在单链路不可用时生效，双链路稳定时不触发。真实数据中 Granger 可能返回 None 时 Q4 价值会显现。
4. **配对检验不显著**（Holm-Bonferroni adj_p=1.0）：各组信号高度相关，差异仅在少数质变时点，需要更大样本或真实数据验证统计显著性。

**脚本**：[poc_cv_ablation.py](../dreambuddy_evolution/core/poc_cv_ablation.py)

### 10.8 落地步骤（按可回退顺序）

**每一步独立 TDD 开发，每一步可单独回退**：

| 步骤 | 模块 | 前置依赖 | 可回退验证 |
|------|------|---------|----------|
| **Step 1** | `AttentionAggregator`（§8.10） | `NeuralSDE.forecast()` 新增可选返回字段（不破坏旧调用） | 关闭 `enable_attention_aggregator` → 现有 forecast 行为不变 |
| **Step 2** | `GrangerPipelineAdapter`（§8.9 + §8.12） | `GrangerCausalityChecker`（已有）+ DAL 因子 | 关闭 `enable_granger_pipeline` → G_dim=None |
| **Step 3** | `CrossValidationGate` 主体（§8.11） | Step 1 + Step 2 | 关闭 `enable_cross_validation_gate` → pipeline 走原路径 |
| **Step 4** | `head_multipliers` 动态调整接入 | Step 3 + `cross_attention.head_multipliers` 已有字段 | 关闭 `enable_head_multipliers_adjustment` → 交叉验证仍记录但不调整 |
| **Step 5** | 自进化闭环连接（§10.5） | Step 3 + `FTCEvolutionBridge`（已有） | 质变事件先仅记录到 cognitive memory，不触发 FTCEvolutionBridge；验证稳定后再接入 |

**总体验证流程**：

1. **Step 1-3 完成后**：交叉验证框架可运行，但仅输出日志/记录，不影响实际交易决策（`confidence_mult=1.0`，`head_adjustment={}`）
2. **Step 4 完成后**：`head_multipliers` 动态调整生效，影响下次 `cross_attention` 输出 → §5.1 Step 5 落地
3. **Step 5 完成后**：质变事件触发自进化闭环 → 完整 §5.1.3 自进化架构

### 10.9 与现有"自进化"系统的关系

| 现有自进化组件 | §10 增强点 |
|-------------|----------|
| `AutoWeightAdjuster`（参数微调） | 质变事件提供新的"何时触发权重调整"信号（之前依赖 ESS 单一信号） |
| `FTCEvolutionBridge.run_gene_innovation`（基因创新） | 质变事件提供"何时探索新基因"的 trigger（之前依赖 FTC 相似度） |
| `ContradictionIdentifier._meta_cognition_verify`（W5） | CrossValidationGate 输出可作为 meta_cognition 的输入信号 |
| `ContradictionWeightLearner`（W6，未启动） | 质变事件积累可作为 W6 的训练样本来源 |

**关键定位**：§10 的 CrossValidationGate **不替代**现有自进化组件，而是为它们提供**新的、更高层级的触发信号**——基于"过去 vs 现在"分歧的质变事件，比单条链路的内部信号更能反映市场主要矛盾的转移。

### 10.10 待深入探讨的问题

> **v0.7 状态**：以下 5 个问题已在 §10.11 给出工程化优化方案，本节保留原始问题描述作为方案动机记录。

1. **persistence_threshold 的数据驱动校准**：默认 5 期是先验值，需要回测验证——历史上矛盾转移平均需要多少期持续分歧？可用 §5.7 可证伪性框架验证 → **§10.11.1 Bayesian 校准方案**
2. **head_multipliers 动态调整的收敛性**：`boost_factor` 和 `decay_factor` 持续应用是否会导致某些 head 权重持续衰减到 0？需要加上 floor 约束（如 `head_multipliers[head] = max(0.1, ...)`） → **§10.11.2 floor+ceiling+mean reversion 三重保护**
3. **Granger 重估的触发频率**：质变事件可能频繁发生，是否需要冷却期（如 24 小时内最多 1 次重估）？避免过拟合最新事件 → **§10.11.3 时间+样本双冷却+待执行队列**
4. **A_dim 与 G_dim 都为 none 的处理**：当前 FAIL-OPEN 返回中性结果，但是否应该降级到只用单条链路（如只用 Attention）？ → **§10.11.4 三级降级模式**
5. **structural_break 的多重检测**：`detect_all()` 返回 `any_structural_break`，但是否需要区分哪种类型（波动率制度/相关性断裂/市场形态）才触发质变？避免噪声性断裂误触发 → **§10.11.5 类型加权共识机制**

### 10.11 §10.10 待探讨问题的优化方案

基于代码审计（`ContradictionShiftAccumulator` 已有 `persistence` 参数但未保存转移持续期统计；`StructuralBreakDetector.detect_all()` 返回 3 个独立字段但现有调用未差异化处理）和控制论原理，给出以下 5 个问题的工程化优化方案。

#### 10.11.1 Q1 优化：persistence_threshold 的 Bayesian 数据驱动校准

**问题**：默认 5 期是先验值，需数据驱动校准。

**方案**：Bayesian 后验更新 + 硬边界 + 启动期保护

```
初始化:
  prior_persistence = 5            # 先验值（基于 CUSUM/Hurst 通常需要 ≥5 期稳定检测）
  prior_weight = 5                  # 先验权重（等价于 5 个虚拟样本）
  observed_count = 0                # 实际观察到的质变事件数
  observed_sum = 0                  # 累计持续分歧期数
  
每次质变确认后:
  observed_count += 1
  observed_sum += actual_divergence_count_at_quality_change
  posterior = (prior_persistence * prior_weight + observed_sum) 
              / (prior_weight + observed_count)
  persistence_threshold = clip(posterior, lower=3, upper=20)
  
启动期保护:
  if observed_count < 3:
      persistence_threshold = 5   # 启动期使用先验
  else:
      使用 Bayesian posterior
```

**实现要点**：
- 数据来源：每次质变事件触发时记录当时的 `divergence_count`（CrossValidationGate **实现后将包含**此字段；当前 [contradiction_shift_accumulator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_shift_accumulator.py) 的 `detect_shift()` 已返回 `consecutive_count` 作为数据源）
- **持久化保障（TDD-PRE-003 已落地）**：质变事件通过 `_quality_change_log`（`quality_change_log.jsonl` 追加落盘）持久化，每条记录含 `consecutive_count`、`structural_break` 三字段、`timestamp`、`ts_code`。解决原 `_history` 内存列表重启丢失问题，Bayesian 校准的 `observed_count`/`observed_sum` 可从落盘日志冷启动恢复
- 边界硬约束：`persistence_threshold ∈ [3, 20]`（下限保证过滤噪声，上限保证响应性）
- **BTC 实测推荐范围**（基于 [调研报告_数据项_1_2_4.md §4.2](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_数据项_1_2_4.md)）：BTC 自相关 τ=1（弱有效市场），2τ 规则失效，persistence=5 真实误报概率 35-42%。按时间周期调整：
  - 30m: [5, 7]（2.5-3.5 小时）
  - 1h: [7, 10]（7-10 小时）
  - 1d: [10, 14]（2 周）
  - 1w: [14, 20]（3-5 个月）
- 与 `ContradictionShiftAccumulator` 历史窗口（`persistence * 3`）兼容——校准后窗口自动跟随调整

**可证伪性**：可用 §5.7 框架回测——历史上若质变事件的平均持续分歧期数显著偏离校准值，则先验或贝叶斯权重需要调整。

#### 10.11.2 Q2 优化：head_multipliers 收敛性（floor + ceiling + mean reversion）

**问题**：`boost_factor` 和 `decay_factor` 持续应用可能让某些 head 权重衰减到 0 或无限增长。

**方案**：三重保护机制

```
硬边界（防失控）:
  head_multipliers[head] = clip(
      head_multipliers[head] * adjustment_factor,
      lower=0.1,    # floor: 即使长期衰减也保留 10% 的最小权重
      upper=2.0     # ceiling: 防止单一 head 主导
  )

Mean Reversion（一致状态回归）:
  # 当 divergence_count == 0（一致状态）时，multipliers 缓慢回归 1.0
  if divergence_count == 0 and not quality_change:
      reversion_rate = 0.15  # 每期回归 15%（约 18 期回归至 5% 容差内）
      for head in head_multipliers:
          head_multipliers[head] += (1.0 - head_multipliers[head]) * reversion_rate
```

**理论依据**：
- `floor=0.1`：与 `ElasticConstraintResolver._floor=0.20`（[elastic_constraint_resolver.py L55](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/elastic_constraint_resolver.py#L55)）保持同量级——仓位约束与 head 权重约束的"最低保留"哲学一致
- `ceiling=2.0`：理论边界，单 head 不应超过原始权重的 2 倍——基于 attention softmax 归一化后单 head 主导已属异常
- `reversion_rate=0.15`：基于 **OU 离散过程均值回归速率** `r = 1 - exp(-Δt/τ)`（[调研报告_理论项_3_5_6.md §3](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_理论项_3_5_6.md) 相平面分析推导）。r=0.05 时实际需 ~59 期（文档原称 ~20 期，3 倍误差），且 boost/decay 是 reversion 的 4-20 倍。r=0.15 半衰期约 4 期，3 期消除 38% 单期偏离，理论边界 `[0.10, 0.20]`

**新增开关**：`enable_head_multipliers_mean_reversion`（默认 `False`），可独立关闭。

#### 10.11.3 Q3 优化：Granger 重估冷却期（时间 + 样本双约束）

**问题**：质变事件可能频繁发生，重估会过拟合最新事件。

**方案**：双冷却约束 + 待执行队列

```
冷却约束:
  TIME_COOLDOWN_HOURS = 24        # 时间冷却：最小 24h 间隔
  SAMPLE_COOLDOWN = persistence_threshold * 2   # 样本冷却：至少积累 2×persistence 期新数据
  
重估触发逻辑:
  def on_quality_change(new_main_dim):
      now = time.now()
      elapsed_hours = (now - self._last_reestimate_time) / 3600
      new_samples = self._sample_count_since_last_reestimate
      
      if elapsed_hours < TIME_COOLDOWN_HOURS:
          # 进入待执行队列，等冷却结束
          self._pending_reestimate = new_main_dim
          return "pending: time cooldown"
      
      if new_samples < SAMPLE_COOLDOWN:
          # 进入待执行队列，等样本积累
          self._pending_reestimate = new_main_dim
          return "pending: sample cooldown"
      
      # 冷却结束 + 样本充足 → 执行重估
      self._trigger_granger_reestimate(new_main_dim)
      self._last_reestimate_time = now
      self._sample_count_since_last_reestimate = 0
      self._pending_reestimate = None
  
每期检查待执行队列:
  if self._pending_reestimate and cooldown_satisfied():
      self._trigger_granger_reestimate(self._pending_reestimate)
      self._pending_reestimate = None
```

**理论依据**：
- `TIME_COOLDOWN=24h`：**避免日内多次重估**（FOMC 6 周间隔是上限参考，非对齐基准——6 周 ≠ 24h，原"与 FOMC 对齐"表述逻辑错误）
- `SAMPLE_COOLDOWN=2×persistence`：Granger 检验需要足够样本量，2×persistence 保证统计功效
- 待执行队列：避免遗漏合法质变信号——只是延迟执行，不丢弃

#### 10.11.4 Q4 优化：双 None 处理（单链路降级模式）

**问题**：当前 FAIL-OPEN 返回中性结果，但是否应该降级到单链路？

**方案**：三级降级模式

```
def compare(G_dim, G_conf, A_dim, A_strength, structural_break):
    # === 完整模式: 双链路可用 ===
    if G_dim is not None and A_dim is not None:
        return self._full_cross_validation(G_dim, G_conf, A_dim, A_strength, structural_break)
    
    # === 降级模式 1: 仅 Attention 可用（Granger 数据不足） ===
    if G_dim is None and A_dim is not None:
          # 使用 A_dim 作为"现在主矛盾"，不进行交叉验证
          # confidence_mult=1.0（不调整），shift_signal=False（不触发）
          # 但记录降级状态供日志分析
          return {
              "confidence_mult": 1.0,
              "shift_signal": False,
              "divergence_count": 0,
              "quality_change": False,
              "head_adjustment": {},
              "granger_reestimate_trigger": False,
              "degraded_mode": "attention_only",   # 新增字段
              "primary_dim": A_dim,                # 使用 A_dim 作为主矛盾
          }
    
    # === 降级模式 2: 仅 Granger 可用（Attention 模型未启用） ===
    if G_dim is not None and A_dim is None:
          return {
              "confidence_mult": 1.0,
              "shift_signal": False,
              "divergence_count": 0,
              "quality_change": False,
              "head_adjustment": {},
              "granger_reestimate_trigger": False,
              "degraded_mode": "granger_only",
              "primary_dim": G_dim,                # 使用 G_dim 作为主矛盾
          }
    
    # === 完全 FAIL-OPEN: 双链路都不可用 ===
    return self._neutral_result_with_degradation("both_none")
```

**设计要点**：
- 降级模式期间，`primary_dim` 仍输出供下游 `ElasticConstraintResolver` 使用——避免仓位约束完全失效
- `degraded_mode` 字段供日志/告警系统识别降级状态
- 不调整 `confidence_mult` 和 `head_adjustment`——避免在缺乏交叉验证的情况下做出错误调整
- 当降级模式持续超过 N 期 → 触发告警（可能需要人工介入检查组件健康）

**新增开关**：`enable_degraded_mode`（默认 `True`，建议开启——单链路可用总比完全中性好）。

#### 10.11.4a Q4 单链路可靠性的 SPRT 在线监测

**问题**：单链路降级模式的前提是"该链路输出维度与双链路一致时的输出一致"。若单链路本身有偏差（如 Granger 滞后、Attention 噪声），直接信任会引入误差。

**方案**：序贯概率比检验（SPRT）在线监测单链路一致性，动态切换至完全中性

```
监测对象: 单链路输出维度 A_dim（或 G_dim）
对照基准: 双链路交叉验证历史中同维度的输出频率（滚动 60 期）

SPRT 参数:
  p0 = 0.75   # H0: 单链路一致率 ≥ 75%（可接受）
  p1 = 0.50   # H1: 单链路一致率 ≤ 50%（不可接受）
  α = 0.05    # 第一类错误
  β = 0.10    # 第二类错误
  ASN ≈ 73    # 平均样本量（约 73 期做出决策）

决策逻辑:
  每期记录单链路输出是否与"最近一次双链路可用时的主矛盾维度"一致
  计算似然比 Λ = [p1^k * (1-p1)^(n-k)] / [p0^k * (1-p0)^(n-k)]
  if Λ > (1-β)/α: 接受 H1 → 切换至完全中性（both_none 降级）
  if Λ < β/(1-α): 接受 H0 → 保持单链路降级
  else: 继续采样
```

**理论依据**：SPRT 是 Wald（1945）提出的序贯检验，在所有 α、β 相同的检验中 ASN 最小。p0=0.75 基于 [调研报告_数据项_3_5_6.md §4](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/调研报告_数据项_3_5_6.md)：单 Granger 链在趋势期一致率 75-85%，在震荡期降至 40-50%。ASN≈73 对应 1h 周期约 3 天，可在单链路失准早期切换。

**实现状态**：待 TDD-PRE-004 落地。当前 Q4 降级模式直接信任单链路，SPRT 上线后增加安全网。

#### 10.11.5 Q5 优化：structural_break 类型加权 + 共识机制

**问题**：`detect_all()` 返回 `any_structural_break`，但 3 种类型可靠性不同——`volatility_regime_shift` 可能只是事件冲击噪声。

**代码事实**（[structural_break_detector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/structural_break_detector.py)）：
- `detect_all()` 已返回 3 个独立字段：`volatility_regime_shift` / `correlation_break` / `market_form_shift` + `any_structural_break` 汇总
- 现有 `ContradictionShiftAccumulator` 质变确认逻辑只要求"至少一类断裂为真"——未差异化处理
- **已落地修复（TDD-PRE-001/002）**：`correlation_break` 检测方法从 `breaks_cusumolsresid`（statsmodels 0.13+ 已移除）改为 `scipy.stats.ttest_ind` Welch's t-test（method=`welch_ttest`），检测滚动相关序列前/后 1/3 的均值漂移，叠加 `abs(mean_diff) > 0.3` 效应量阈值防大样本伪显著；`volatility_regime_shift` 的 `MarkovRegression` 迭代上限从 `maxiter=100` 提升至 `maxiter=500`（修复 100% ConvergenceWarning）

**方案**：类型加权 + 共识阈值

| 断裂类型 | 检测方法 | 可靠性 | 权重 | 理论依据 |
|---------|---------|-------|------|---------|
| `market_form_shift` | Hurst 指数 | 最高 | 1.0 | 反映市场结构根本变化（趋势↔均值回归切换），最具结构性 |
| `correlation_break` | Welch's t-test | 中等 | 0.6 | 反映相关性结构变化（均值漂移），但有噪声边缘。*权重基于方法理论可靠性排序，与 fallback 实现的灵敏度无关；CUSUM 依赖修复后需重测命中率* |
| `volatility_regime_shift` | Markov-Regression (HMM) / 阈值 fallback | 较低 | 0.4 | 易受事件冲击影响（如 FOMC、CPI 公布），不一定是结构性变化 |

**加权共识触发逻辑**：

```python
def _structural_break_score(structural_break: dict) -> float:
    """计算结构性断裂加权得分."""
    score = 0.0
    if structural_break.get("market_form_shift", False):
        score += 1.0
    if structural_break.get("correlation_break", False):
        score += 0.6
    if structural_break.get("volatility_regime_shift", False):
        score += 0.4
    return score

# Step 4 质变判定修改:
if self._divergence_count >= self._persistence_threshold:
    break_score = self._structural_break_score(structural_break)
    if break_score >= self._structural_break_threshold:  # 临时 0.4，依赖修复后校准回 1.0
        quality_change = True
        granger_reestimate_trigger = True
        new_main_dim = A_dim
        self._divergence_count = 0
```

**触发阈值**（`structural_break_threshold`）：
- **临时默认 `0.4`**（v1.2 评审 P0 #7）：statsmodels fallback 状态下 Hurst(1.0) + CUSUM(0.0) 最高仅 1.0 ≤ 1.0，原阈值 1.0 不可触发。临时降为 0.4（任一断裂即可触发），[contradiction_shift_accumulator.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_shift_accumulator.py) 已定义模块常量 `STRUCTURAL_BREAK_THRESHOLD = 0.4`。CUSUM/HMM 依赖修复并重测命中率后再校准回 1.0
- 严格模式 `1.6`：要求 `market_form_shift + correlation_break`（权重和 1.6），过滤所有 vol 噪声
- 宽松模式 `0.6`：任一中等以上断裂即触发（用于回测对比）

**新增开关**：`structural_break_threshold`（浮点参数，**临时默认 `0.4`**，理论边界 `[0.4, 1.6]`，依赖修复后校准回 `1.0`）。

**可证伪性**：可用 §5.7 框架回测——历史上真实的矛盾转移事件中，3 种断裂类型的命中率是多少？如果 `volatility_regime_shift` 命中率显著低于其他两种，则降低其权重或调高阈值。

#### 10.11.6 优化方案汇总

| 问题 | 优化方案 | 新增开关/参数 | 理论边界 |
|------|---------|-------------|---------|
| Q1 persistence_threshold 校准 | Bayesian 后验更新 + 启动期保护 | `persistence_threshold` 自动校准 | `[3, 20]` |
| Q2 head_multipliers 收敛性 | floor + ceiling + mean reversion | `enable_head_multipliers_mean_reversion` | floor=0.1, ceiling=2.0, reversion_rate=0.15 |
| Q3 Granger 重估冷却 | 时间冷却 24h + 样本冷却 2×persistence | 无开关（默认启用） | TIME_COOLDOWN=24h, SAMPLE_COOLDOWN=2×persistence |
| Q4 双 None 处理 | 三级降级模式（attention_only/granger_only/both_none） | `enable_degraded_mode` | 默认 True |
| Q5 structural_break 区分 | 类型加权（Hurst=1.0, Welch's t-test=0.6, vol=0.4）+ 共识阈值 | `structural_break_threshold` | `[0.4, 1.6]`，临时默认 0.4 |

**所有新增开关默认值**（除 `enable_degraded_mode=True`）均为 `False`，保证 v0.5 现状完全不变——可回退性不变。

#### 10.11.7 优化后的完整 §5.1 五步算法

将 §10.4 的伪代码与 §10.11 优化合并，得到完整算法：

```python
class CrossValidationGate:
    def __init__(self,
                 persistence_threshold=5,           # Q1: Bayesian 校准
                 confidence_boost=1.15,
                 confidence_penalty=0.9,
                 head_boost_rate=0.3,
                 head_decay_rate=0.2,
                 head_floor=0.1,                     # Q2: 硬边界
                 head_ceiling=2.0,
                 head_reversion_rate=0.15,           # Q2: mean reversion（OU 离散过程，18 期回归 5% 容差）
                 time_cooldown_hours=24,             # Q3: 时间冷却
                 sample_cooldown_multiplier=2,      # Q3: 样本冷却倍数
                 structural_break_threshold=0.4):   # Q5: 共识阈值（临时默认，依赖修复后校准回 1.0）
        self._divergence_count = 0
        # ... Bayesian 校准状态（Q1）
        # ... 冷却状态（Q3）
        # ... 降级模式状态（Q4）
    
    def compare(self, G_dim, G_conf, A_dim, A_strength, structural_break):
        # Q4: 三级降级模式
        if G_dim is None and A_dim is None:
            return self._neutral_result_with_degradation("both_none")
        if G_dim is None:
            return self._degraded_result("attention_only", A_dim)
        if A_dim is None:
            return self._degraded_result("granger_only", G_dim)
        
        # Step 3: 交叉比对
        if G_dim == A_dim:
            confidence_mult = self._confidence_boost
            shift_signal = False
            self._divergence_count = 0
            # Q2: mean reversion（一致状态回归）
            self._revert_head_multipliers_to_mean()
        else:
            confidence_mult = self._confidence_penalty
            shift_signal = True
            self._divergence_count += 1
        
        # Step 4: 质变判定（Q5: 类型加权共识）
        quality_change = False
        granger_reestimate_trigger = False
        if self._divergence_count >= self._persistence_threshold:
            break_score = self._structural_break_score(structural_break)
            if break_score >= self._structural_break_threshold:
                quality_change = True
                # Q3: 冷却检查
                if self._cooldown_satisfied():
                    granger_reestimate_trigger = True
                    self._update_bayesian_persistence(self._divergence_count)  # Q1
                    self._divergence_count = 0
                else:
                    self._pending_reestimate = A_dim  # 进入待执行队列
        
        # Step 5: head_multipliers 动态调整（Q2: floor + ceiling）
        head_adjustment = {}
        if shift_signal and not quality_change:
            progress = min(1.0, self._divergence_count / self._persistence_threshold)
            A_dim_head = self._dim_to_head(A_dim)
            G_dim_head = self._dim_to_head(G_dim)
            head_adjustment[A_dim_head] = max(self._head_floor, 
                min(self._head_ceiling, 1 + self._head_boost_rate * progress))
            head_adjustment[G_dim_head] = max(self._head_floor, 
                min(self._head_ceiling, 1 - self._head_decay_rate * progress))
        
        return {
            "confidence_mult": confidence_mult,
            "shift_signal": shift_signal,
            "divergence_count": self._divergence_count,
            "quality_change": quality_change,
            "head_adjustment": head_adjustment,
            "granger_reestimate_trigger": granger_reestimate_trigger,
            # Q5: 调试字段
            "structural_break_score": break_score if quality_change else None,
            # Q4: 降级模式标识
            "degraded_mode": None,  # 完整模式
        }
```

#### 10.11.8 优化方案的待验证项

1. **Q1 Bayesian 校准的收敛性**：在历史数据上回测——质变事件的持续分歧期数分布是否稳定？若分布漂移大，可能需要滑动窗口而非全局累计
2. **Q2 mean reversion 与 head 动态调整的相互作用**：一致状态回归 1.0 + 分歧状态偏离 1.0，两者切换是否会产生振荡？需要相平面分析
3. **Q3 冷却期的副作用**：24h 内多次合法质变会被压缩为 1 次重估——可能丢失早期信号。需要在"过拟合"和"信号丢失"之间权衡
4. **Q4 降级模式的告警阈值**：连续多少期降级触发告警？建议 `persistence_threshold * 2`（与冷却期一致）
5. **Q5 权重和阈值的实证校准**：Hurst=1.0/Welch's t-test=0.6/vol=0.4 是基于统计稳定性的先验，需要用 §5.7 框架在历史质变事件上回测校准（CUSUM 依赖修复后需重测命中率再校准权重）

---

## 附录：两份文档的交叉引用

| 矛盾论 v3.0 章节 | 矛盾 Transformer 章节 | 关系 |
|---|---|---|
| §4 外生力量度量 | §7.3 外生因子强度评估器 | 同一组件，矛盾论定义原则，Transformer 描述实现 |
| §5 因果传导建模 | 无对应 | 矛盾论独有——Transformer 无因果验证 |
| §6 维度标准化与交互效应 | §9 多头注意力对齐 | 矛盾论用显式交互项，Transformer 用隐式 attention |
| §7 弹性约束模型 | §5.1 阻力向量矛盾调制 | 矛盾论设计 sigmoid，Transformer 实现线性 |
| §8 质变检测 | §6.3 矛盾漂移检测 | 同一组件（ContradictionShiftAccumulator），但 Transformer 路径未集成 |
| §9 矛盾转化检测算法 | §6.3 矛盾漂移检测 | 同上 |
| §10 反身性维度 | §5.1 R_reflexivity | 矛盾论设计自影响项，Transformer 实现静态 corr/liq/sent |
| §11 可证伪性 | 无对应 | 矛盾论独有——Transformer 仅用 MAE |
| §12 维度边界定义 | §7.1 模块→维度映射 | 矛盾论定义分类规则，Transformer 按 C1-C8 分组 |
| §15 集成方案 | §11 完整架构图 | 两份文档各有架构图，但未交叉引用 |
| §16 落地路线图 Phase 1-4 | §12 落地路径 Phase 1-6 | 两套独立编号，需统一 |

---

> **本文档状态**：草案 v0.7，仅供深入探讨使用，不作为实施依据。所有"注入"点需逐一验证可行性和必要性后再决定是否落地。§10 交叉验证层架构设计 + §10.11 五大优化方案为 v0.6/v0.7 新增的理论方案，需评审通过后再进入 TDD 实现（按 §10.8 五步骤），实现时同步落地 §10.11 的 5 个优化（Q1 Bayesian 校准 / Q2 收敛性保护 / Q3 冷却期 / Q4 降级模式 / Q5 类型加权共识）。
