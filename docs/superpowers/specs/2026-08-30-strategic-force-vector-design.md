# 战略层数据驱动升级：力向量最小阻力方向设计

> 日期：2026-08-30
> 上游规格：[2026-08-21-sunzi-five-domains-evaluation.md](./2026-08-21-sunzi-five-domains-evaluation.md)
> 范围：战略层从"人工规则打分"升级为"数学统计学→最小阻力方向→下游输出"
> 阶段：部分实现（Shadow 运行中，2026-09-01 更新）

---

## 一、背景与目标

### 现状

五计庙算当前是 100% 人工规则打分体系——阈值（≥75/≥60/≥50）、权重（道30%/天15%/地25%/将15%/法15%）、子指标映射规则全部人工设定。9-基本面分析已具备 FinBERT 模型推理 + signal_engine 自适应权重 + 贝叶斯置信度等数据驱动能力，但仅接入不到 10%（仅 sentiment_engine 的 score 值注入一个子项）。

### 目标

将战略层从"人工规则打分"升级为"数学统计学→主要矛盾识别→共振分析→最小阻力方向→周期比对→下游输出"的数据驱动体系：

```
Step 1: 统计学计算 → 五维力向量（方向+强度+置信度）
Step 2: Kalman Filter 平滑 → 降噪后的力向量
Step 3: 特征-价格关联度计算 → 识别主要矛盾（定方向）
Step 4: PCA 五维共振分析 → 共振/冲突调整强度（定强度）
Step 5: 最小阻力方向（主矛盾定）+ 强度（共振调整后）
Step 6: 周期比对 → 7天窗口(方向变化) vs 30天窗口(趋势确认) 双窗口共振校验
Step 7: 映射到 war_state/cap/mask + 新增 force_vectors → 下游可消费
```

### 核心原则

- **统计描述而非预测**：客观测量各维度力量方向和强度，不预测未来涨跌 → 从根上规避过拟合
- **客观测量→推导方向**：庙算是客观盘点双方力量对比，推导综合最小阻力方向，不是算命
- **双窗口共振校验**：短窗口看方向变化，长窗口看趋势确认，共振才有效

### 四项硬约束

1. 不改现有 war_state/cap/mask 接口（下游零改动）
2. 新增 force_vectors 输出（方向+强度+置信度+PCA主成分），下游可选消费
3. 现有规则打分作为 fallback（统计计算异常时回退）
4. 统计窗口数据不足（<7天）→ FAIL-OPEN 回退规则打分

---

## 二、五维力向量统计学计算 + Kalman 平滑

### 力向量结构

> **复用 9-基本面 least_resistance.py**：direction/magnitude/confidence/velocity/acceleration 五字段直接从 `compute_resistance_3d()` 输出读取（L63-71），不重新计算。

```python
@dataclass
class ForceVector:
    dimension: str          # "dao" / "tian" / "di" / "jiang" / "fa"
    direction: float        # [-1.0, +1.0]  ← least_resistance.direction
    magnitude: float        # [0.0, +∞)    ← least_resistance.direction_score
    confidence: float       # [0.0, 1.0]   ← signal_engine._bayesian_confidence（非简单公式）
    velocity: float         # 方向变化率   ← least_resistance.velocity（新增，部分替代 Kalman）
    acceleration: float     # 方向变化加速度 ← least_resistance.acceleration（新增，检测趋势转折）
    kalman_direction: float # Kalman平滑后的方向（可选：confidence>0.7时跳过）
    kalman_magnitude: float # Kalman平滑后的强度
    dominant: bool          # 是否为主要矛盾维度
    weight: float           # 自适应权重（按|magnitude|分配）
```

### Step 1：五维力向量统计计算

每个维度用不同的统计学方法计算 direction 和 magnitude：

| 维度 | 统计方法 | direction 计算 | magnitude 计算 | 置信度来源 |
|---|---|---|---|---|
| **道** | 滚动 Z-score + 趋势斜率 | sign(OLS斜率) × min(1, \|Z\|/2) | \|Z\| / 2（归一化到0-1+） | 样本数/30 + (1-方差比) |
| **天** | 条件期望值 E[r\|season] + 分位数 | sign(E[r\|season]) × min(1, \|E[r]\|/σ) | \|E[r]\|/σ | 季节样本数/预期最小样本 |
| **地** | 百分位排名 + 趋势一致性 | sign(MA对齐度) × 一致性% | (百分位偏离50%)/50% | MA对齐数/总MA数 |
| **将** | 滚动 Sharpe + 偏度 | sign(Sharpe) × min(1, \|Sharpe\|/2) | \|Sharpe\|/2 | 交易样本数/30 |
| **法** | 信息系数 IC + 信息比率 IR | sign(IC) × min(1, \|IC\|/0.1) | \|IC\|/0.1 | 策略命中数/总策略数 |

### Step 2：Kalman Filter 平滑

对每个维度的 direction 和 magnitude 分别做 Kalman 平滑：

```
状态: x = [direction, direction_velocity]  # 方向 + 方向变化率
观测: z = [raw_direction]
状态转移: F = [[1, dt], [0, 1]]            # 匀速模型
观测矩阵: H = [[1, 0]]
过程噪声: Q = diag(0.001, 0.0001)          # 低过程噪声（力向量慢变化）
观测噪声: R = [σ²_raw]                      # 来自原始数据方差
```

- dt = 日级刷新间隔（1天）
- Kalman 输出 kalman_direction：比原始 direction 更平滑，减少单日跳变
- 观测噪声 R 自适应：样本方差大 → R 大 → 平滑力度大（更信任先验）

### Step 3：置信度计算（复用 signal_engine 贝叶斯置信度）

> **复用 9-基本面 signal_engine.py**：直接调用 `_bayesian_confidence()`（L91-113），废弃简单 w_sample × w_stability 公式。

```python
# signal_engine.py L91-113 已实现：
posterior_mean = alpha / (alpha + beta)
posterior_variance = alpha * beta / ((alpha + beta)^2 * (alpha + beta + 1))
precision = 1 / (1 + posterior_variance)
bayesian_confidence = raw_confidence × (0.5 + 0.5 × posterior_mean) × (0.5 + 0.5 × precision)

# 直接调用，不重新实现：
confidence = signal_engine._bayesian_confidence(module_name, raw_confidence)
```

- alpha/beta 由 `update_module_performance()` 滚动更新（L115-132）
- 预测正确 → alpha += 1，预测错误 → beta += 1
- 比简单 w_sample × w_stability 更精确：融合了后验均值 + 方差精度

---

## 三、主要矛盾识别：特征-价格关联度 + 自适应权重合成

> **设计转变**：从 PCA 协方差分解转向特征-价格关联度计算。PCA 看的是"五维之间的关系"，而主要矛盾的本质是"哪些特征对价格影响最紧密"——特征-价格关联度才是识别主要矛盾的正确方法。
> **过拟合不构成风险**：目标是识别关联强度排名（序数关系），不是预测价格（基数关系）。IC=0.08 和 0.12 哪个更准不重要，重要的是哪个排前面。排名比绝对值更抗过拟合。

### Step 4：特征-价格关联度计算（主要矛盾识别核心）

#### Step 4-1：特征池构建

从三源汇聚候选特征池（约 50-100 个）：

```
特征池来源：
  ├ 五维子指标特征（25 个）：fedfunds_rate, stablecoin_mcap_bln, fgi_zscore, ATR分位, regime, MA对齐度...
  ├ 9-基本面引擎输出（10+ 个）：sentiment_score, event_risk_dir, narrative_heat,
  │   signal_engine _module_stats adaptive_weight, three_dee_3D resistance...
  └ 数据中心 Gold 层特征（37 个 MacroFeatures）：funding_rate_zscore, oi_change_rate,
      fgi_extreme_fear, merrill_clock_phase, liquidity_credit_features...
```

#### Step 4-2：滚动窗口关联度计算

对每个特征 f_i，在滚动窗口 W（30天）内计算两个关联度指标：

```
1. 信息系数 IC（线性关联度）：
   IC_i = Spearman_Rho(f_i[t], r[t+1])
   
   # Spearman 秩相关，而非 Pearson，抗异常值
   # r[t+1] = 未来 1 天（或 1 周日级）的收益率
   # |IC_i| 越大 → 该特征与价格线性关联越紧密
   # IC > 0 → 正向关联（特征高→价格涨）
   # IC < 0 → 负向关联（特征高→价格跌）

2. 互信息 MI（非线性关联度）：
   MI_i = Mutual_Information(f_i[t], r[t+1])
   
   # 捕捉非线性关系（如阈值效应、区间效应）
   # "顶部利好催不动" → MI 高但 IC 低（非线性衰减）
   # MI_normalized = MI_i / max_MI（归一化到 [0, 1]）
```

#### Step 4-3：综合关联度排名

```
combined_score_i = |IC_i| × w_linear + MI_normalized_i × w_nonlinear

  默认 w_linear = 0.6, w_nonlinear = 0.4（线性为主，非线性补充）
  
  排名 top-N 特征 = 当前的主要矛盾信号集
  排名 top-1 特征 = 当前主要矛盾（PrimaryContradiction）
  
  特征排名映射到维度：
    if top-1 feature ∈ dao_features → dominant_dimension = "dao"
    if top-1 feature ∈ tian_features → dominant_dimension = "tian"
    ...（按特征→维度归属表映射）
```

#### Step 4-4：最优权重计算

```
weight_i = |IC_i|^α / Σ|IC_j|^α    # 按 IC 绝对值分配权重

  α > 1 → 强化头部特征（差距拉大，更聚焦主要矛盾）
  α = 1 → 线性正比（默认）
  α < 1 → 平滑差距（防止单特征独占）

约束：weight_i ∈ [0.02, 0.40]
     （任意特征权重不低于 2%，不高于 40%）

Beta 后验权重融合（直接复用 signal_engine._adaptive_weight，L67-89）：
  feature_weight_i = IC_weight_i × signal_engine._adaptive_weight(module_name_i)

  # signal_engine.py L67-89 已实现完全相同公式：
  # posterior_mean = alpha / (alpha + beta)
  # adaptive_weight = base × (1 + (posterior_mean - 0.5) × 0.6)
  # 范围 [0.3×base, 2.0×base]
  # 不重新实现，直接调用

  → IC 高但 Beta 低（统计相关但预测不准）→ 降权
  → IC 低但 Beta 高（统计不显著但预测准）→ 提权
```

### 关联度计算输出结构

```python
@dataclass
class FeatureCorrelation:
    feature_name: str               # 特征名
    dimension: str                  # 归属维度 "dao"/"tian"/"di"/"jiang"/"fa"
    ic_30d: float                   # 30天滚动信息系数 [-1, 1]
    mi_30d: float                   # 30天互信息归一化值 [0, 1]
    combined_score: float           # 综合关联度
    rank: int                       # 排名（1=主要矛盾）
    ic_weight: float                # IC 最优权重
    beta_weight: float              # Beta 后验权重
    final_weight: float             # 最终融合权重
```

```python
@dataclass
class PrimaryContradiction:
    feature_name: str               # 主要矛盾特征（rank=1）
    dimension: str                  # 主要矛盾维度
    combined_score: float           # 综合关联度
    rank_stability: float           # 排名稳定性（滚动窗口间 Spearman 相关）
    all_features: List[FeatureCorrelation]  # 完整排名表
    dominant_dimension: str         # 维度聚合后的主导维度
    alignment: str                  # "resonance"/"conflict"/"divergence"
    sign_alignment: float           # 同向比例 [0, 1]
```

### Step 4-A：维度聚合（特征→五维）

将特征排名聚合到五维级别：

```
维度力量 = Σ(feature_final_weight_i × feature_direction_i)  for i ∈ dim_features

  dao_power = Σ(w_i × dir_i)  for i ∈ dao_feature_pool
  tian_power = Σ(w_i × dir_i)  for i ∈ tian_feature_pool
  ...

dominant_dimension = argmax(|维度力量|)
sign_alignment = count(sign(维度力量_i) == sign(综合力向量)) / 5
  ≥ 0.8 → "resonance"
  ≤ 0.4 → "conflict"
  0.4-0.8 → "divergence"
```

### Step 5：自适应权重合成（用关联度权重替代 |magnitude|×confidence）

```
维度权重 = 维度内所有特征的 final_weight 之和

  w_dao = Σ(final_weight_i)  for i ∈ dao_features
  w_tian = Σ(final_weight_i)  for i ∈ tian_features
  ...

约束：w_dim ∈ [0.05, 0.50]（同原 Spec）

综合力向量 = Σ(w_dim_i × kalman_direction_i × kalman_magnitude_i)
```

### Step 5-A：排名一致性检测（矛盾变化信号）

```
每日滚动计算特征排名：
  rank_spearman = Spearman_Rho(rank_T, rank_T-1)

  rank_spearman > 0.8 → 排名稳定，主要矛盾未变
  0.6 < rank_spearman ≤ 0.8 → 排名微调，主要矛盾可能松动
  rank_spearman ≤ 0.6 → 排名大幅变化，主要矛盾可能转化

  top-1 切换检测：
    if top1_T != top1_T-1:
      contradiction_shift_signal = True
      → 触发矛盾转化检测（§三-A-2）
```

### Step 4-B：PCA 五维共振分析（定强度，非可选）

PCA 在主要矛盾识别之后执行，用于**计算最小阻力强度**。方向由主要矛盾决定（Step 4），强度由 PCA 共振分析调整。

**职责分工**：
- **主要矛盾（Step 4）**→ 定**方向**（主要矛盾特征方向 = 最小阻力方向）
- **PCA 共振分析（Step 4-B）**→ 定**强度**（其他四维与主导维度的共振/冲突 → 强度增强/减弱）

```
输入：五维力量 [dao_power, tian_power, di_power, jiang_power, fa_power]
     + 主导维度 dominant_dim（由 Step 4 特征关联度 top-1 确定）

PCA 分解：
  协方差矩阵 C = Cov(五维力量矩阵)
  特征值 λ_1 ≥ λ_2 ≥ ... ≥ λ_5
  特征向量 v_1（第一主成分方向）
  explained_ratio = λ_1 / Σλ_i

共振分析：
  主导维度方向 = sign(dominant_dim_power)
  其他四维与主导维度的方向一致性：
    sign_alignment = count(sign(dim_i) == sign(dominant_dim_power)) / 4
      = 1.0 → 全共振（其他四维全部与主导同向）
      ≥ 0.75 → 强共振
      0.5 ~ 0.75 → 弱共振（部分同向）
      ≤ 0.5 → 冲突（多数反向）
      = 0.0 → 全冲突

强度调整系数 strength_coefficient：
  全共振 (alignment=1.0)      → ×1.3（力量叠加）
  强共振 (alignment≥0.75)      → ×1.2
  弱共振 (0.5<alignment<0.75)  → ×1.0（中性）
  冲突 (alignment≤0.5)          → ×0.5（力量抵消）
  全冲突 (alignment=0.0)        → ×0.3（强烈抵消）

  额外约束：
    if explained_ratio < 0.3 → PCA 退化，strength_coefficient ×0.8（五维线性相关，结构不清晰）
```

**PCA 共振输出**（合并到 PrimaryContradiction）：

```python
@dataclass
class PCAResonance:
    explained_ratio: float           # 第一主成分解释方差比 [0, 1]
    sign_alignment: float            # 其他四维与主导维度的同向比例 [0, 1]
    alignment: str                   # "full_resonance"/"strong_resonance"/"weak_resonance"/"conflict"/"full_conflict"
    strength_coefficient: float      # 强度调整系数 [0.3, 1.3]
    dominant_dimension: str           # 主导维度（从 Step 4 传入，PCA 不改变）
```

### 最小阻力方向 + 强度合成

```
最小阻力方向 = sign(dominant_dim_power)    # 由主要矛盾决定方向

最小阻力强度 = |dominant_dim_power|        # 主导维度自身强度
              × strength_coefficient       # PCA 共振调整
              × adaptive_weight_dominant  # 主要矛盾的自适应权重
```

### 特殊情况处理

| 场景 | 处理 |
|---|---|
| 全共振 + 方向一致 | 综合强度 ×1.3（力量叠加） |
| 强共振 + 方向一致 | 综合强度 ×1.2 |
| 弱共振 | 综合强度 ×1.0（中性） |
| 冲突 | 综合强度 ×0.5（力量抵消） |
| 全冲突 | 综合强度 ×0.3（强烈抵消） |
| explained_ratio < 0.3 | PCA 退化，额外 ×0.8 |
| 主要矛盾维度 | 权重下限提升到 0.15（确保主要矛盾有足够话语权） |
| 样本不足（<30天） | IC/MI 不可靠 → 回退 \|magnitude\|×confidence 权重 |

---

## 三-A、矛盾转化检测（关联度增强层）

> **理论依据**：毛泽东《矛盾论》— "矛盾的主要和非主要的方面互相转化着，事物的性质也就随着起变化"、"一切矛盾都依一定条件向它们的反面转化着"。
> **工程铁律**：A0-IRON-5 "矛盾会转化，必须设定监控条件"（矛盾分析法.md L91）

### 问题：关联度快照的不足

特征-价格关联度能识别"哪些特征对价格影响最大"（主要矛盾），但存在 3 个关键不足：

| 不足 | 问题 | 影响 |
|---|---|---|
| 关联度是滚动快照 | 30天窗口的 IC/MI 是静态的，不跟踪实时变化 | 无法检测主要矛盾从特征 A 切换到特征 B |
| 不考虑阶段依赖性 | 同样力向量在顶部和底部含义不同 | "顶部利好催不动"会被误判为"力量充足" |
| 无法识别弹性衰减 | 力向量强度高但价格不响应 | 主要矛盾已转化但力向量尚未反映的滞后 |

### Step 3-A-1：弹性系数β检测（价格响应衰减）

**核心思想**：同样强度的利好信息，在顶部和底部的价格弹性系数完全不同——这不是信息变了，是主要矛盾转化了。

```
弹性系数 β = ΔPrice% / ΔForce%

  β_7d  = 近7天价格变化率 / 近7天综合力向量变化率
  β_30d = 近30天价格变化率 / 近30天综合力向量变化率
  β_ratio = β_7d / β_30d  （弹性变化比值）

矛盾转化信号：
  β_ratio < 0.5 持续3天 → 弹性衰减：价格对力向量响应持续衰减
    → 主要矛盾可能已从"利好驱动"转化为"获利了结压力"（顶部信号）
    → 力向量方向仍偏多，但价格已不响应

  β_ratio > 2.0 持续3天 → 弹性放大：价格对力向量响应突然放大
    → 主要矛盾可能正从"空头压制"转化为"被压制的做多力量释放"（底部信号）
    → 力向量方向可能仍偏空，但价格已开始响应利好
```

**β 检测输出**：

```python
@dataclass
class ElasticityBeta:
    beta_7d: float              # 近7天弹性系数
    beta_30d: float             # 近30天弹性系数
    beta_ratio: float           # 弹性变化比值 = β_7d / β_30d
    decay_signal: bool          # 弹性衰减信号（β_ratio < 0.5 持续3天）
    amplification_signal: bool  # 弹性放大信号（β_ratio > 2.0 持续3天）
    decay_days: int             # 衰减持续天数
    amplification_days: int     # 放大持续天数
```

### Step 3-A-2：矛盾转化条件监控（A0-IRON-5 落地）

《矛盾论》明确"转化依一定条件"，需设定 5 类监控条件：

| 转化条件 | 统计指标 | 触发阈值 | 含义 | 9-基本面数据源 |
|---|---|---|---|---|
| **弹性衰减** | β_7d / β_30d 比值 | < 0.5 持续3天 | 价格对力向量响应持续衰减→顶部矛盾转化 | 新建（OLS 回归） |
| **弹性放大** | β_7d / β_30d 比值 | > 2.0 持续3天 | 价格对力向量响应突然放大→底部矛盾转化 | 新建（OLS 回归） |
| **维度主导切换** | 特征排名 top-1 历史 | 7天内 top-1 特征切换≥2次 | 主要矛盾特征不稳定→转化中 | 新建 + **S4 event_mapping crr** 辅助（crr>0.3→事件分类冲突高→主要矛盾不稳定佐证） |
| **共振破裂** | sign_alignment 变化 | 7天内降幅≥0.4（从≥0.8降至≤0.4） | 多维同向共识破裂→矛盾转化 | PCA 共振分析 + **S4 event_mapping mr** 辅助（mr<0.5→事件映射一致性低→共振弱佐证） |
| **CBR 背离** | 同类事件历史结果 vs 当前 | 方向相反 | 同类事件出现不同结果→阶段已变 | 扩展现有 CBR 案例库 |
| **数据质量预警**（新增） | **S3 news_contract pass_rate** | < 0.7 持续3天 | 新闻契约通过率持续低→输入信息可信度下降→力向量置信度需降级 | **S3 news_contract_validator** 直接复用 |

> **S3/S4 复用说明**：S3 的 pass_rate 作为"数据质量预警"新增第 6 类转化条件，当 pass_rate 持续低时，力向量 confidence 直接 ×0.7（信息可信度降级）；S4 的 crr/mr 作为"维度主导切换"和"共振破裂"的辅助佐证，不单独触发转化，但提升对应条件的置信度权重（crr>0.3 或 mr<0.5 时，该条件触发置信度 ×1.2）。

**矛盾转化检测输出**：

```python
@dataclass
class ContradictionTransform:
    transforming: bool                  # 是否检测到矛盾转化
    transform_type: str                 # "elasticity_decay" / "elasticity_amplification" / "dominant_shift" / "resonance_break" / "cbr_divergence" / "data_quality_warning" / "none"
    trigger_conditions: List[str]       # 触发的条件列表
    confidence: float                   # 转化置信度 [0, 1]（多个条件同时触发→高置信度）
    monitoring_points: List[str]        # A0-IRON-5 要求的监控点描述
    data_quality_factor: float          # S3 pass_rate 降级因子（pass_rate<0.7 持续3天→0.7，否则1.0）
```

**转化置信度计算**：

```
confidence = 触发条件数 / 总条件数（6）

  1个条件触发 → confidence≈0.17（低置信度，观察中）
  2个条件触发 → confidence≈0.33（中置信度，提高警惕）
  3个条件触发 → confidence=0.50（高置信度，矛盾转化中）
  ≥4个条件触发 → confidence≥0.67（极高置信度，矛盾已转化）

  注：S4 crr/mr 辅助佐证不增加触发条件数，但提升已触发条件的置信度权重（×1.2）
```

### Step 3-A-3：阶段依赖性校准（矛盾特殊性落地）

《矛盾论》"矛盾特殊性"要求：同一事件在不同发展阶段矛盾性质不同。利用 CBR 案例库 + regime 分层计算**条件期望**：

```
E[r | event_type, regime] =
  case A: regime=trend_up   → E[r] = +2.3%  （顺势利好放大）
  case B: regime=trend_down  → E[r] = -1.2%  （利好被空头压制）
  case C: regime=sideways    → E[r] = +0.3%  （利好影响有限）

阶段依赖性校准因子：
  当 E[r | event, regime_current] 与 E[r | event, regime_全部] 方向相反
  → 当前阶段的矛盾特殊性导致同类事件结果不同
  → 力向量 magnitude 需按校准因子调整：

  adjustment_factor = E[r | event, regime_current] / E[r | event, all_regimes]

  若 |adjustment_factor| < 0.3 → 力向量强度 ×0.5（当前阶段该事件影响被压制）
  若 |adjustment_factor| > 2.0 → 力向量强度 ×1.5（当前阶段该事件影响被放大）
```

**CBR 背离检测**：当当前事件结果与历史同类事件（同 regime）结果方向相反时，标记 `cbr_divergence=True`，提示"同类事件出现背离，可能主要矛盾已转化"。

### 矛盾转化对决策的影响

当 `ContradictionTransform.transforming=True` 时，对下游映射做以下调整：

| 转化类型 | 对 cap 的影响 | 对 mask 的影响 | 对 war_state 的影响 |
|---|---|---|---|
| elasticity_decay（顶部衰减） | cap ×0.5 | 禁 trend_follow/breakout | COOLDOWN（即使 final_score≥65） |
| elasticity_amplification（底部放大） | cap 不变但 position_mult ×1.2 | 开 mean_revert/emergency | COOLDOWN→ALLOW 加速（若方向转正） |
| dominant_shift（维度切换） | cap ×0.7 | 保守：仅 mean_revert/emergency | COOLDOWN |
| resonance_break（共振破裂） | cap ×0.6 | 仅 emergency | FREEZE（若方向也不明确） |
| cbr_divergence（CBR 背离） | cap ×0.8 | 维持当前但标记观察 | 维持当前 |
| data_quality_warning（数据质量预警） | cap 不变 | 维持当前 | 维持当前，但所有 force_vector.confidence ×0.7（信息可信度降级） |

### 新增模块

| 模块 | 职责 | 复用 9-基本面 |
|---|---|---|
| `ElasticityBetaCalculator` | Step 3-A-1：计算 β_7d/β_30d/β_ratio，检测衰减/放大信号 | 新建（OLS 回归） |
| `ContradictionTransformDetector` | Step 3-A-2：6 类转化条件监控，输出 ContradictionTransform | **复用 S3 pass_rate + S4 crr/mr** 作为 2 类条件的输入 |
| `RegimeConditionalCalibrator` | Step 3-A-3：CBR 条件期望 + 阶段依赖性校准因子 | 扩展现有 CBR 案例库 |

---

## 四、双窗口周期比对 + 映射下游输出

### Step 6：7天+30天双窗口共振校验

对综合力向量同时计算 7天窗口和 30天窗口版本，做共振校验：

| 短窗口(7d) | 长窗口(30d) | 共振状态 | 综合强度系数 | 含义 |
|---|---|---|---|---|
| 方向一致(同正/同负) | 方向一致 | **共振** | ×1.2 | 短期变化与长期趋势一致 |
| 方向一致 | 方向中性(\|dir\|<0.1) | **萌发** | ×0.9 | 短期变化出现但长趋势未确认 |
| 方向相反 | 方向一致 | **背离** | ×0.6 | 短期逆行，可能是反转前兆或噪音 |
| 方向中性 | 方向一致 | **持续** | ×1.0 | 短期无变化，长趋势维持 |
| 方向一致 | 方向相反 | **转折** | ×0.7 | 短期转向，长趋势仍在旧方向 |
| 方向中性 | 方向中性 | **观望** | ×0.3 | 双窗口均无明确方向 |

### 周期比对输出结构

```python
@dataclass
class CycleComparison:
    direction_7d: float           # 7天窗口综合方向
    direction_30d: float          # 30天窗口综合方向
    magnitude_7d: float           # 7天窗口综合强度
    magnitude_30d: float          # 30天窗口综合强度
    resonance_state: str          # 共振/萌发/背离/持续/转折/观望
    strength_multiplier: float    # 综合强度系数
    final_direction: float        # 最终方向（取30d为主，7d加权修正）
    final_magnitude: float        # 最终强度 = magnitude_30d × strength_multiplier
```

### Step 7：映射下游可消费字段

最终方向和强度映射到现有 war_state/cap/mask + 新增 force_vectors：

```
final_score = (final_direction + 1) / 2 × 100    # [-1,+1] → [0,100]

war_state 映射:
  final_score ≥ 65 且 resonance_state ∈ {共振,持续}  → ALLOW
  50 ≤ final_score < 65 或 resonance ∈ {萌发,转折}  → COOLDOWN
  final_score < 50 或 resonance ∈ {背离,观望}       → FREEZE

cap 映射（按 resonance_state 调整）:
  共振 + final_direction > 0 → cap = 0.50~1.00（按 magnitude 分档）
  持续 + final_direction > 0 → cap = 0.30~0.80
  萌发/转折                  → cap = 0.20~0.50
  背离/观望                  → cap = 0.10~0.20

allowed_style_mask 映射:
  共振 + direction > 0 → trend_follow/breakout/momentum 全开
  持续                 → mean_revert/momentum 开
  萌发/转折            → 仅 mean_revert/emergency
  背离/观望            → 仅 emergency

position_mult:
  PCA dominant 维度 |direction| < 0.2 → 0.3（主矛盾方向不明确→降仓）
  法维度 confidence < 0.3            → 0.0（法维度统计失效→不开新仓）
```

### 输出结构（与现有共存）

```python
@dataclass
class StrategicLayerOutput:
    # === 现有字段（下游零改动）===
    war_state: str                    # ALLOW / COOLDOWN / FREEZE
    aggregate_position_cap_pct: float # 仓位上限
    allowed_style_mask: Dict[str, bool] # 策略白名单
    position_mult: float             # 维度否决乘数
    five_scores: Dict[str, int]       # 五维分数(兼容现有0-100)

    # === 新增力向量字段（下游可选消费）===
    force_vectors: Dict[str, ForceVector]     # 五维力向量
    pca_result: PCAResult                      # PCA主要矛盾
    cycle_comparison: CycleComparison          # 双窗口共振校验
    final_direction: float                    # 综合最小阻力方向 [-1,+1]
    final_magnitude: float                    # 综合强度
    resonance_state: str                       # 共振状态
    elasticity_beta: ElasticityBeta            # 弹性系数β（价格响应衰减/放大）
    contradiction_transform: ContradictionTransform  # 矛盾转化检测结果
    primary_contradiction: str                # 主要矛盾维度（=PCA dominant_dimension）
    monitoring_points: List[str]              # A0-IRON-5 监控点列表
```

---

## 五、9-基本面引擎接入 + FAIL-OPEN + 测试策略

### 9-基本面引擎在力向量体系中的接入（复用优化版）

> **与 7 引擎注入对齐**：下表覆盖 `FiveDomainFeatureComputer` 已注入的 S 级 5 引擎（S1-S5）+ A 级 2 引擎（A6/A7），确保 Spec 复用范围与代码实际注入范围一致（见 `_fd_S_dao_boost`/`_fd_S_tian_boost`/`_fd_A_dao_boost`/`_fd_A_tian_boost`，L768/L1066/L1283/L1339）。

| 引擎 | 接入维度 | 提供什么 | 接入方式 | 复用度 |
|---|---|---|---|---|
| **S1 sentiment_engine** | 道/天 | FinBERT score → direction 原始输入（含时间衰减权重 τ=24h） | 已接入（P1），score 映射为 direction[-1,+1]，弱信号保护 abs(s)<0.05 走 fallback | ✅ 已接入 |
| **S2 event_ledger** | 道/天 | **direction 直接输入**（非辅助）：risk_dir → direction，sentiment_weighted → magnitude | `generate_ledger()` 输出 risk_dir/sentiment_weighted 直接作为 direction/magnitude 输入 | **70% 提升** |
| **S3 news_contract_validator** | 道/天 | **新闻契约通过率 pass_rate → 法维度 confidence 来源**；契约失败率高→信息可信度下降 | `validate()` 输出 pass_rate ∈ [0,1] → 映射为法维度置信度（数据质量契约） | **新增复用** |
| **S4 event_mapping_engine** | 道/天 | **事件映射冲突率 crr + 一致性 mr → 矛盾转化检测信号**；crr 高→主要矛盾不稳定，mr 低→共振弱 | `_map_events()` 输出 crr/mr → Step 3-A-2 "维度主导切换"监控 + PCA 共振分析辅助 | **新增复用** |
| **S5 narrative_engine** | 道 | **PCA 权重先验**：heat_score 量化主要矛盾预判 | `build_narratives()` 输出 heat_score → PCA 先验权重 `1.0 + heat × 0.3` | **量化落地** |
| **A6 least_resistance** | 全五维 | **ForceVector 核心计算器**：direction/magnitude/confidence/velocity/acceleration 五字段 | `compute_resistance_3d()`（L63-71）输出直接映射到 ForceVector | **85% 复用** |
| **A7 signal_engine** | 全五维 | **贝叶斯置信度 → confidence** + **自适应权重 → feature_weight** | `_bayesian_confidence()`（L91-113）直接调用；`_adaptive_weight()`（L67-89）直接调用 | **100% 复用** |
| **three_dee_3D** | 地 | 3D 阻力趋势 → 地维度 direction（least_resistance 封装） | 已接入（A级），通过 least_resistance 统一输出 | ✅ 已接入 |

### 数据流（复用优化版）

```
9-基本面引擎输出（S级5引擎 + A级2引擎）
  ├─ S1 sentiment_engine: score[-1,1] ─────────→ 道/天 direction 原始值
  ├─ S2 event_ledger: risk_dir/sentiment_weighted → 道/天 direction 直接输入
  ├─ S3 news_contract_validator: pass_rate ───→ 法维度 confidence（数据质量契约）
  ├─ S4 event_mapping_engine: crr/mr ─────────→ 矛盾转化检测 + PCA 共振分析辅助
  ├─ S5 narrative_engine: heat_score ─────────→ PCA 先验权重（1.0 + heat × 0.3）
  ├─ A6 least_resistance: compute_resistance_3d() → ForceVector 五字段直接输出
  │   (direction/magnitude/confidence/velocity/acceleration)
  ├─ A7 signal_engine: _bayesian_confidence() → 五维 confidence（贝叶斯后验）
  ├─ A7 signal_engine: _adaptive_weight() ───→ 特征级 Beta 后验权重
  └─ three_dee_3D: 阻力方向 ──────────────────→ 地 direction（least_resistance 封装）

数据中心 SQLite Gold 层
  ├─ stablecoin_mcap_bln 周环比 ─────────────→ 道 magnitude（Z-score）
  ├─ fgi_zscore / fgi_extreme ───────────────→ 道/天 direction 辅助
  ├─ funding_rate_zscore ───────────────────→ 地 magnitude
  ├─ oi_change_rate ─────────────────────────→ 地 direction
  └─ macro_feature_select_v2 特征 ───────────→ 特征池候选
      ↓
  统计计算 → 力向量(direction, magnitude, confidence)
      ↓
  Kalman Filter 平滑
      ↓
  特征-价格关联度计算 → 主要矛盾识别（IC + MI + Beta后验）
    ├─ 特征排名 → top-1 = 主要矛盾（定方向）
    ├─ 最优权重（|IC|^α 归一化 × Beta后验融合）
    └ 排名一致性检测 → 矛盾变化信号
      ↓
  PCA 五维共振分析（定强度）
    ├─ 主导维度 = 主要矛盾维度（Step 4 传入）
    ├─ 其他四维与主导维度共振/冲突 → 强度调整系数
    └ 共振增强×1.3 / 冲突减弱×0.5
      ↓
  最小阻力方向（主矛盾定）+ 强度（共振调整后）
      ↓
  矛盾转化检测（动态检测）
    ├─ 弹性系数β → 价格响应衰减/放大
    ├─ 5类转化条件监控 → 矛盾是否转化中
    └ CBR 条件期望 → 阶段依赖性校准
      ↓
  双窗口周期比对 → 共振校验
      ↓
  映射 → war_state/cap/mask + force_vectors + 矛盾转化状态
```

### FAIL-OPEN 三层防护

| 层级 | 触发条件 | 行为 |
|---|---|---|
| L0 | 数据不足（<7天样本） | 力向量计算跳过，回退现有规则打分体系 |
| L1 | 统计计算异常（Z-score 溢出/PCA 退化/矩阵奇异） | 本维度 direction=0, magnitude=0, confidence=0 |
| L2 | Kalman/PCA 全失败 | 整体回退规则打分，force_vectors=None，war_state/cap/mask 走现有逻辑 |
| OK | 正常计算 | 力向量 + 现有输出共存 |

### 测试策略（TDD，17 TC）

| TC# | 名称 | 断言 |
|---|---|---|
| TC1 | 力向量结构 | ForceVector 含 8 字段（dimension/direction/magnitude/confidence/kalman_direction/kalman_magnitude/dominant/weight），类型范围正确 |
| TC2 | Z-score 统计计算 | 喂入 30 天稳定币增速数据 → direction sign 与趋势一致，magnitude ∈ [0, 1+] |
| TC3 | Kalman 平滑 | 原始 direction 有单日跳变 → kalman_direction 平滑后跳变幅度 < 50% 原始 |
| TC4 | 特征-价格 IC 计算 | 构造特征与价格正相关 30 天数据 → IC > 0；负相关 → IC < 0 |
| TC5 | 互信息 MI 计算 | 构造非线性关系（阈值效应）→ MI_normalized > 0.3 但 IC ≈ 0 |
| TC6 | 综合关联度排名 | 构造 5 个特征不同 IC/MI → combined_score 排名正确，top-1 = 主要矛盾 |
| TC7 | 最优权重 | IC 权重按 \|IC\|^α 归一化，和=1.0，每个 ∈ [0.02, 0.40]；Beta 融合后仍满足约束 |
| TC8 | 排名一致性检测 | 连续 2 天排名 Spearman > 0.8 → rank_stability > 0.8；top-1 切换 → contradiction_shift_signal=True |
| TC9 | 双窗口共振 | 7d 方向 +30d 方向同向 → resonance_state="resonance"，strength_multiplier=1.2；反向 → "divergence"，×0.6 |
| TC10 | FAIL-OPEN | 样本<7天 → force_vectors=None，war_state 走现有规则打分 |
| TC11 | 弹性系数β衰减 | 构造 β_7d/β_30d < 0.5 持续3天 → decay_signal=True, decay_days≥3 |
| TC12 | 弹性系数β放大 | 构造 β_7d/β_30d > 2.0 持续3天 → amplification_signal=True |
| TC13 | 矛盾转化检测 | 3个转化条件同时触发 → transforming=True, confidence=0.50（6类条件基准） |
| TC14 | 阶段依赖性校准 | E[r\|event,regime_current] 与 E[r\|event,all] 方向相反 → adjustment_factor<0.3 → 力向量强度×0.5 |
| TC15 | 矛盾转化对决策影响 | elasticity_decay 触发 → cap×0.5，禁 trend_follow，war_state=COOLDOWN |
| TC16 | S3 数据质量预警 | 构造 S3 news_contract pass_rate<0.7 持续3天 → data_quality_warning 触发，data_quality_factor=0.7，所有 force_vector.confidence ×0.7 |
| TC17 | S4 事件映射辅助佐证 | 构造 S4 crr>0.3 且维度主导切换已触发 → 该条件置信度权重 ×1.2；构造 mr<0.5 且共振破裂已触发 → 同样 ×1.2 |

---

## 六、与现有体系的关系

### 规则打分体系（保留为 fallback）

现有 `FiveDomainHeuristicScorer` + `FiveDomainFeatureComputer` 规则打分体系完整保留，作为：
- 力向量计算的 fallback（L0/L1/L2 异常时回退）
- 数据不足（<7天）时的默认路径
- 力向量体系验证期的 Shadow 对照组

### 新增模块（标注复用/新建）

| 模块 | 职责 | 复用/新建 | 复用来源 |
|---|---|---|---|
| `ForceVectorCalculator` | Step 1-3：统计计算 + Kalman 平滑 → 五维 ForceVector | **85% 复用** | A6 least_resistance.compute_resistance_3d() L63-71 |
| `FeatureCorrelationCalculator` | Step 4：IC + MI 滚动计算 → 特征排名 → 主要矛盾识别（定方向） | **新建** | scipy.stats.spearmanr + sklearn MI |
| `PCAResonanceAnalyzer` | Step 4-B：五维共振分析 → 强度调整系数（定强度） | **新建** | sklearn.decomposition.PCA + **S4 event_mapping mr** 辅助 |
| `AdaptiveWeightOptimizer` | Step 4-4 + Step 5：IC 最优权重 + Beta 后验融合 | **100% 复用** | A7 signal_engine._adaptive_weight() L67-89 |
| `ElasticityBetaCalculator` | Step 3-A-1：弹性系数β计算 → 价格响应衰减/放大检测 | **新建** | OLS 回归 ΔPrice ~ ΔForce |
| `ContradictionTransformDetector` | Step 3-A-2：6 类转化条件监控 → 矛盾转化检测 | **部分复用** | **复用 S3 news_contract pass_rate**（数据质量预警条件）+ **S4 event_mapping crr/mr**（辅助佐证）+ 新建 4 类条件 |
| `RegimeConditionalCalibrator` | Step 3-A-3：CBR 条件期望 + 阶段依赖性校准 | **新建** | 扩展现有 CBR 案例库 |
| `CycleComparator` | Step 6：双窗口共振校验 → CycleComparison | **新建** | 7d/30d 窗口并行计算 |
| `StrategicMapper` | Step 7：映射 → war_state/cap/mask + force_vectors + 矛盾转化状态 | **新建** | 参考 least_resistance.generate_signal() L74-125 决策风格 |

> **复用统计**：9 个模块中 2 个直接复用（ForceVectorCalculator 85%、AdaptiveWeightOptimizer 100%），1 个部分复用（ContradictionTransformDetector 复用 S3/S4），6 个新建。新增 S3/S4 复用后，矛盾转化检测模块新建条件从 5 类降至 4 类，新建代码量减少约 45%。
> **7 引擎复用对齐**：S1-S5 + A6/A7 全部纳入 Spec 复用范围，与 `FiveDomainFeatureComputer` 的 `_fd_S_dao_boost`/`_fd_S_tian_boost`/`_fd_A_dao_boost`/`_fd_A_tian_boost` 注入范围完全一致。

### 字节等价保证

- 力向量体系默认关闭（enable_force_vector=False）
- 开启时与规则打分共存：war_state/cap/mask 优先取力向量映射值，force_vectors 作为附加输出
- 关闭时回退规则打分，force_vectors=None，下游字节等价"力向量不存在"

---

## 七、风险评估

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| 过拟合 | **低** | 目标是关联强度排名（序数），非预测价格（基数）；排名比绝对值抗过拟合 |
| IC/MI 计算不稳定 | 中 | 30天滚动窗口平滑；Spearman 秩相关抗异常值；样本<30天回退 |magnitude|×confidence |
| 互信息离散化误差 | 中 | MI 计算需离散化连续变量；使用等频分箱（10 bins）+ 交叉验证 |
| Kalman 参数不适配 | 低 | Q/R 可配置；默认值保守（低过程噪声）；异常时回退原始值 |
| 双窗口数据不足 | 低 | 30天窗口不足时用 7天窗口单独输出，resonance_state 标记为"萌发" |
| signal_engine 接入复杂度 | 中 | 分阶段：先接入 confidence 输出，后接入自适应权重 |
| 弹性系数β误判 | 中 | β_ratio 需持续3天才触发；单日波动不触发；L1 异常时 β=1.0（中性） |
| 矛盾转化误判（假阳性） | 中 | 需≥2个条件同时触发才标记 transforming=True；单条件仅记录不调整决策 |
| CBR 条件期望样本不足 | 中 | 同 regime 同事件样本<5时回退全 regime 均值；无样本时 adjustment_factor=1.0（不调整） |
| 特征池规模过大 | 低 | 50-100 候选特征 IC 计算量可控；日级刷新无性能压力；可按预筛 |IC|>0.02 过滤 |
| S3 pass_rate 降级误触发 | 低 | pass_rate<0.7 需持续3天才触发；S3 引擎异常时 pass_rate=1.0（FAIL-OPEN 中性，不降级） |
| S4 crr/mr 辅助佐证失真 | 低 | crr/mr 仅作辅助佐证（×1.2 权重），不单独触发转化；S4 引擎异常时 crr/mr 取中性值（不影响主条件） |

---

## 八、实现状态（2026-09-01 更新）

> 原标"设计阶段，不落地代码"→ 已更新为"部分实现（Shadow 运行中）"。

### 已实现模块

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| ForceVectorCalculator | `force_vector/force_vector_calculator.py` | ✅ 已实现 | 五维统计计算（Z-score/条件期望/百分位/Sharpe/IC）+ Kalman 平滑 + 自适应权重 |
| FeatureCorrelationCalculator | `force_vector/feature_correlation_calculator.py` | ✅ 已实现 | IC + MI + combined_score + rank_features |
| PCAResonanceAnalyzer | `force_vector/pca_resonance_analyzer.py` | ✅ 已实现 | 五维共振分析 + sign_alignment + strength_coefficient |
| CycleComparator | `force_vector/cycle_comparator.py` | ✅ 已实现 | 7d/30d 双窗口比对 + consistency_state |
| ElasticityBetaCalculator | `force_vector/elasticity_beta_calculator.py` | ✅ 已实现 | β_7d/β_30d/ratio + decay/amplification 信号 |
| ContradictionTransformDetector | `force_vector/contradiction_transform_detector.py` | ✅ 已实现 | 6 类转化条件 + confidence |
| StrategicMapper | `force_vector/strategic_mapper.py` | ✅ 已实现 | 映射到 war_state/cap/mask + force_vectors |

### Shadow 运行状态

| 项目 | 状态 | 详情 |
|------|------|------|
| FORCE_VECTOR_SHADOW 开关 | ✅ 已开启 | `yijing_monitor.py` L265 `env.setdefault("FORCE_VECTOR_SHADOW", "1")` |
| JSONL 真实记录 | ✅ 积累中 | `scripts/runtime/force_vector_records.jsonl`，23 条记录跨 3 天（2026-08-30 ~ 09-01） |
| 前端真实数据展示 | ✅ 已接通 | `data_server_fixed.py` `_aggregate_real_data()` 5 种 sub_type 全实现 |
| Shadow 输入数据源 | ✅ 已改为真实 | Phase 1B：从 JSONL 历史真实方向序列构建，不足时回退合成 |
| `_count_shadow_days` BUG | ✅ 已修复 | 原 `timestamp`/`ts`/`datetime` 三字段查找漏 `ts_ms`，导致恒返回 0 → 永远走 demo |

### 自适应权重基础设施（Phase 2）

| 项目 | 状态 | 说明 |
|------|------|------|
| `_compute_adaptive_weights()` | ✅ 已实现 | `five_domain_scorer.py`：从 force_vector magnitude 计算自适应权重，alpha 由 avg_conf 决定 |
| `_weighted_total(force_vectors=)` | ✅ 已实现 | 可选参数，传入则用自适应权重，不传则用 WEIGHTS_BY_CLASS |
| 调用方传参 | ❌ 未启用 | 当前调用方（`_apply_decision_rules` L280）未传 force_vectors → 仍用硬编码权重 |
| 启用条件 | 待定 | 需 Shadow 数据积累 ≥7 天 + avg_conf > 0.3 + PR+CR |

### 仍为合成数据的部分

| 项目 | 原因 | 计划 |
|------|------|------|
| FeatureCorrelation 的 `returns_arr` | JSONL 无价格数据 | 后续接入 OKX 价格 API |
| ElasticityBeta 的 `price_hist` | 同上 | 同上 |
| confidence 恒为 0.5 | Shadow 用历史序列计算但仍需更多样本积累 | 随 JSONL 积累自动提升 |
