# Market Morphology Evolution Engine — 市场形态演化引擎设计

> 设计日期: 2026-08-19
> 状态: **待审批 (Draft)**
> 所有者: DreamBuddy v2 易经推理系统工作组
> 版本: v1.0
> 关联 Spec: [2026-08-18-regime-predictor-design.md](./2026-08-18-regime-predictor-design.md)（旧硬分类范式升级为连续曲线范式）

---

## 一、动机与背景（Why）

### 1.1 旧范式痛点（"硬分类预测 regime"）

| 痛点 | 现象（真实训练结果） |
|---|---|
| **瞬间跳变不可信** | 分类器必须输出单一标签，相邻 K 线 regime 跳变无连续性 |
| **Fold 2/3 严重退化** | 2022 熊市 / 2022-2023 恢复期 avg Macro F1 仅 0.120 / 0.185 |
| **过拟合周期特征** | Halving 日期特征跨周期泛化失败（F1 0.247→0.199） |
| **容错机制缺失** | 单一分类标签错误即全错，无"允许吃一点亏"机制 |
| **前端不可解释** | 输出标签无数据支撑，无法展示"为什么是这个形态" |

### 1.2 新范式目标（"数据驱动形态演化曲线"）

借鉴美联储 FOMC 点阵图方法论：
- Fed **不用预测利率**，而是用 19 个委员的数据投票（点阵图）**描述当前对经济数据的共识度**
- 我们 **不用预测形态**，而是用 12 个数据指标的连续评分 **描述当前市场在周期中的位置 + 方向 + 演化轨迹**

核心信仰：
> 市场形态不是骤然改变的。形态由**连续数据累积的量变引起质变**，可以通过数据驱动修正逐步识别拐点，允许容错（滞后确认、吃一点亏），不求某一刻精准，但求动态曲线的长期准确描述。

### 1.3 成功度量（KPI）

| 指标 | 基线（旧范式） | 目标（新范式 v1） | 理想态（v2+） |
|---|---|---|---|
| **Top-3 命中率**（8 态中真实标签在 top3 的概率） | 0.35（LGBM argmax） | ≥ 0.70 | ≥ 0.85 |
| **坐标连续性**（相邻 K 线 Level/Trend 均方跳变） | N/A（离散标签） | ≤ 0.20 格/天 | ≤ 0.10 格/天 |
| **拐点识别滞后**（道氏 123 全满足 vs 真实反转底/顶） | N/A | ≤ 10 根日线 | ≤ 5 根日线 |
| **共识度 vs 后续收益解释度**（R²） | N/A | ≥ 0.30 | ≥ 0.50 |
| WalkForward 5 折 Macro F1（保留标签验证） | 0.299 | ≥ 0.45 | ≥ 0.55 |

---

## 二、核心理论框架（What: Level-Trend 双维坐标体系）

### 2.1 双维坐标定义

所有形态均由两个**连续值**表示，而非离散标签：

| 维度 | 范围 | 含义 | 金融直觉 |
|---|---|---|---|
| **Level Score** (L) | [-4, +4]，9 档整数刻度 | 市场在长周期中的位置 | Stan Weinstein 四阶段的量化（底 Accumulation → 顶 Distribution） |
| **Trend Score** (T) | [-4, +4]，9 档整数刻度 | 市场当前的动量与方向 | 道氏理论 HH/HL + Sperandeo 1-2-3 法则的量化 |

**刻度语义**：

| Level | 典型语义 | Trend | 典型语义 |
|---|---|---|---|
| -4 | 深熊 / 积累末期 | -4 | 强势下跌 / LL+LH 确认 |
| -3 | 熊市中后段 | -3 | 明显下行 / 回撤延续 |
| -2 | 弱势 / 熊市初段 | -2 | 温和下行 |
| -1 | 略弱 / 震荡偏弱 | -1 | 小幅下行 |
| **0** | **中性 / 震荡中枢** | **0** | **无明确方向 / 平盘** |
| +1 | 略强 / 震荡偏强 | +1 | 小幅上行 |
| +2 | 强势 / 牛市初段 | +2 | 温和上行 |
| +3 | 牛市中后段 | +3 | 明显上行 / 反弹延续 |
| +4 | 疯牛 / 派发末期 | +4 | 强势上涨 / HH+HL 确认 |

### 2.2 Level Score 合成算法

Level = 6 个数据指标的**线性加权求和 + clamp(-4, +4)**。初始权重（后续在线学习迭代）：

| # | 指标 | 数据来源 | 单位贡献 (±) | 初始权重 |
|---|---|---|---|---|
| L1 | MA200 三日确认上方/下方 | `ma200_above` 三日 rolling AND | ±1.0 | **2.0** |
| L2 | MA50 上方/下方 | close > MA50 | ±0.5 | 1.0 |
| L3 | MA20 vs MA50 排列 | MA20>MA50=+ / MA20<MA50=- | ±0.5 | 1.0 |
| L4 | 365d range 位置 | `cycle_position_in_range` ≥0.75=+ / ≤0.25=- | ±0.5 | 1.2 |
| L5 | MA 堆叠对齐评分 | `ma_alignment_score` ≥0.50=+ / ≤-0.50=- | ±0.75 | **1.5** |
| L6 | MA200 斜率方向 | `ma200_slope_20d` ≥0.01=+ / ≤-0.01=- | ±0.5 | 1.0 |

**合成公式**：
```
Level_raw = Σ ( wi * ci ) / Σ wi  * 4    # 归一化到 [-4, +4]
```
其中 `ci` 为每个指标的 ± 单位贡献。

### 2.3 Trend Score 合成算法

Trend = 5 个数据指标的**线性加权求和 + clamp(-4, +4)**：

| # | 指标 | 数据来源 | 单位贡献 (±) | 初始权重 |
|---|---|---|---|---|
| T1 | 道氏 HH/HL 序列判定 | Swing 点（5日窗口）：HH+HL=+2, LL+LH=-2, 混合=0 | ±2.0 | **2.0** |
| T2 | 90d 对数收益 | `log_ret_90d` ≥0.15=+1 / ≤-0.15=-1 | ±1.0 | 1.5 |
| T3 | 30d 对数收益 | `log_ret_30d` ≥0.08=+0.5 / ≤-0.08=-0.5 | ±0.5 | 1.0 |
| T4 | MA20/50/200 斜率加权和 | slope(MA20)×2 + slope(MA50)×1 + slope(MA200)×0.5 | ±0.75 | 1.2 |
| T5 | 量能加权趋势确认 | 放量阳线(+0.5) / 放量阴线(-0.5)，缩量相反减弱 | ±0.5 | 1.0 |

**合成公式**：
```
Trend_raw = Σ ( wi * ci ) / Σ wi  * 4
```

### 2.4 四条连续化 / 容错规则（核心灵魂）

#### 规则 1：日变化钳制（连续性保证）

```python
MAX_DAILY_DELTA = 0.5      # 正常情况每根 K 线最大 ±0.5 格
EXTREME_DELTA = 1.0        # 极端事件（日涨跌幅 > 5% + 量确认）允许 ±1.0 格

def clamp_delta(prev: float, raw_now: float, price_change_pct: float, vol_ratio: float) -> float:
    delta = raw_now - prev
    cap = EXTREME_DELTA if (abs(price_change_pct) > 5.0 and vol_ratio > 1.5) else MAX_DAILY_DELTA
    return prev + max(-cap, min(cap, delta))
```

目的：**连续性硬约束**。形态不会一天从 Level=-2 跳跃到 Level=+3。

#### 规则 2：量变 → 质变（Sperandeo 1-2-3 渐进）

道氏 123 法则的**渐进式评分**（不一次性切换）：

| 条件 | 语义 | Trend Score 调整 |
|---|---|---|
| ① 突破（跌破）趋势线 | 下降趋势线被向上突破（或上升趋势线向下突破） | +0.33（或 -0.33） |
| ② 回撤不破前低（高） | 回撤不创新低（或反弹不创新高） | +0.33（或 -0.33） |
| ③ 突破前高（跌破前低） | 收盘价突破前高（或跌破前低） | +0.34（或 -0.34） |

三条合计 ±1.0。不满足任何一条时坐标**不变**，允许"暂时不明朗"。

#### 规则 3：HMM 平滑器（消噪）

- 用 Level/Trend 的 5 日滑动均值作为观测值
- 训练 3 状态 HMM（Bull / Neutral / Bear，Gaussian emission）
- Viterbi 解码得到平滑后的 level_smooth / trend_smooth
- **HMM 不决定形态**，只消除短期噪声毛刺（对应 3-3 EMA 兜底平滑）

复用现有资产：`market_regime.py` → `HMMRegime`。

#### 规则 4：BOCPD 变点加权（拐点检测）

- BOCPD 检测到变点概率 P > 0.70 时
- 记录变点日的价格方向 sign（后续 5 日收益方向）
- Trend Score 在接下来 5 个交易日**每天渐进调整** sign × 0.06
- 合计 ±0.30，避免单日冲击式跳变

复用现有资产：Spec Phase 2 BOCPD 模块。

### 2.5 (L, T) → 8 态软概率映射

保留原有 8 态顺序不变。映射不是硬阈值，而是**高斯软分配**：

**Step 1：标定 8 态在 Level-Trend 平面的中心坐标**

| 8 态 | L_center | T_center | 金融直觉 |
|---|---|---|---|
| TREND_UP_STRONG | +2.5 | +3.5 | 高位强涨 |
| TREND_UP_MILD | +1.0 | +2.0 | 中高位置温和上涨 |
| RANGE_BOUND | 0.0 | 0.0 | 震荡中心 |
| CONSOLIDATION | -1.0 | -0.5 | 低位压缩（含波动率） |
| REVERSAL | -2.5 | +1.5 | 底部反转（低价位+涨势启动） |
| VOLATILE_DROP | +1.5 | -3.0 | 高位暴跌 |
| FOMO_RALLY | +3.5 | +2.5 | 顶部情绪化加速 |
| DISTRIBUTION | +3.0 | -1.5 | 顶部派发（高价位+转跌） |

**Step 2：高斯软分配**

对于每一时点的 `(L, T)`：

```python
import math

def regime_soft_probs(L: float, T: float) -> Dict[str, float]:
    distances = {}
    for name, (Lc, Tc) in REGIME_CENTERS.items():
        d2 = ((L - Lc) / 2.0) ** 2 + ((T - Tc) / 2.0) ** 2   # 归一化距离
        distances[name] = -0.5 * d2                           # 高斯核（sigma=2）
    logits = np.array(list(distances.values()))
    probs = softmax(logits)
    return dict(zip(distances.keys(), probs))
```

**不 argmax**。输出保留完整 8 维概率分布。Top-1 仅用于前端高亮，后端 API 不产出单一标签。

---

## 三、引擎架构（How: 六层流水线）

### 3.1 总体架构图

```
┌────────────────────────────────────────────────────────────┐
│ Layer 0: 数据层 (Data Provider)                             │
│  Input: BTC 1D OHLCV → Breadth 8 币 → VIX/F&G/FRED 外部    │
│  产出: unified DataFrame (timestamp 索引, 标准列名)          │
└──────────────────┬─────────────────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────────────────┐
│ Layer 1: 指标银行 (Indicator Bank) → 12 原子指标            │
│  MA组: ma200_above, ma200_slope_20d, ma_alignment_score,   │
│        ma_cross_50_200_signal                               │
│  道氏组: dow_hhhl_score (±2), dow_123_progress (0~1)       │
│  动量组: log_ret_30d, log_ret_90d, ma_slope_wavg            │
│  量能组: volume_ma20_ratio, volume_trend_conf               │
│  周期组: cycle_position_in_range                            │
│  波动率组: vol_60d_percentile_252d                          │
│  产出: Dict[str -> float Series]                            │
└──────────────────┬─────────────────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────────────────┐
│ Layer 2: 双维评分层 (Score Composer)                        │
│  Level_raw = 6 指标加权 clamp(-4, +4)                       │
│  Trend_raw = 5 指标加权 clamp(-4, +4)                       │
│  规则1: clamp_delta (日变化钳制 ±0.5 / ±1.0 extreme)        │
│  规则2: dow_123 渐进调整 ±0.33 / 条件                       │
│  产出: (level_raw, trend_raw) 一对 float                    │
└──────────────────┬─────────────────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────────────────┐
│ Layer 3: 时序平滑层 (Temporal Smoother) — 复用现有资产       │
│  3-1: HMM 3-state Viterbi → 5 日均线平滑                   │
│  3-2: BOCPD 变点 P>0.7 → 5 日渐进调整 ±0.30                │
│  3-3: EMA(α=0.25) 兜底平滑                                  │
│  产出: (level_smooth, trend_smooth) + hmm_state + cp_prob  │
└──────────────────┬─────────────────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────────────────┐
│ Layer 4: 概率映射层 (Regime Mapper)                         │
│  4-1: 软分配 8 维概率 regime_probs                          │
│  4-2: 点阵图矩阵 (12 × 8) = 指标对形态的支持度              │
│  4-3: 共识度 = 1 - entropy_norm(probs)                      │
│  补充: 与 LGBM 分类器的 8 概率 0.7:0.3 加权（独立验证）     │
│  产出: regime_probs + dotplot_matrix + consensus           │
└──────────────────┬─────────────────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────────────────┐
│ Layer 5: 存储 & 服务层 (Storage & API)                      │
│  5-1: regime_state_daily 表持久化                           │
│  5-2: 4 种 REST API（trajectory / dotplot / snapshot /     │
│       indicators evolution）                                │
│  5-3: 周度在线学习（BayesOpt/网格：权重微调 + 中心坐标校准）│
└────────────────────────────────────────────────────────────┘
```

### 3.2 核心数据结构

```python
@dataclass
class RegimeStateFrame:
    """每根 K 线的完整形态状态帧"""
    timestamp: pd.Timestamp
    price: float

    # 双维坐标
    level_raw: float
    trend_raw: float
    level_smooth: float
    trend_smooth: float

    # 8 态概率（不 argmax）
    regime_probs: Dict[str, float]
    regime_top3: List[Tuple[str, float]]

    # 共识度
    consensus: float                          # 1 - H(p)/ln(8) ∈ [0,1]

    # 时序平滑产物
    hmm_state: int                             # 0 Bear / 1 Neutral / 2 Bull
    bocpd_change_point_prob: float             # BOCPD 变点概率

    # 12 个原始指标值（前端点阵图 & 诊断）
    indicators: Dict[str, float]

    # 元信息
    data_version: int = 1
```

### 3.3 现有资产复用映射

| 模块 | 当前角色 | 新引擎角色 | 调整点 |
|---|---|---|---|
| `ma200_cycle_features.py` | BTC 训练特征 | Layer 1 指标 | 直接调用 `compute()`，抽 3 个字段 |
| `multi_timeframe_features.py` | BTC 训练特征 | Layer 1 指标 | 直接调用，抽 6 个字段 |
| `classic_experience_features.py` | BTC 训练特征 | Layer 1 补充 | ADX/Hurst/BB 供诊断面板 |
| `cross_asset_features.py` | BTC 训练特征（广度） | Layer 0 广度数据 | 广度指标值做点阵图额外行 |
| `market_regime.py` HMMRegime | LGBM×0.7+HMM×0.3 | Layer 3-1 HMM Viterbi | 输入改为 Level+Trend 5 日均线 |
| BOCPD 模块（Spec P2） | LGBM 集成 | Layer 3-2 变点加权 | 触发条件 P>0.7 → 渐进调整 |
| `regime_labeler.py` | 8 态标签（训练 ground truth）| 标定 8 态中心坐标 & 回测验证 | 历史标签统计得出初始 `REGIME_CENTERS` |
| `RegimePredictor` LGBM | 唯一分类输出 | Layer 4-1 独立验证（0.3 权重） | 保留 `predict_proba()`，与软分配加权合并 |

### 3.4 在线学习机制（每周迭代）

**触发**：每周日 00:00 UTC，离线 batch。

**调参空间**（约束小，可直接网格 + BayesOpt 并行）：

| 参数量 | 维度 | 初始值 | 单次迭代边界 |
|---|---|---|---|
| Level 指标 6 权重 | 6 | [2.0,1.0,1.0,1.2,1.5,1.0] | ±10% |
| Trend 指标 5 权重 | 5 | [2.0,1.5,1.0,1.2,1.0] | ±10% |
| 8 态中心坐标 (L,T) | 16 | §2.5 表 | ±0.3 格 |
| 日钳制系数 MAX_DAILY_DELTA | 1 | 0.5 | [0.3, 0.8] |

**目标函数**（加权，最高优先级 → 最低）：
1. **Top-3 命中率**（20 日远期标签在预测 top-3 的比例）→ 权重 0.40
2. **坐标连续性**（相邻 |ΔL|+|ΔT| 均值）→ 权重 0.25（负向）
3. **WalkForward Macro F1**（保留 argmax 基准）→ 权重 0.20
4. **共识度 vs 后续 20 日收益 R²** → 权重 0.15

**约束**：所有参数变化必须满足上表的迭代边界；若目标函数下降 ≥ 2%，**拒绝更新**，保留上一周权重。

---

## 四、数据模型与持久化

### 4.1 核心表 `regime_state_daily`

每行 = 一个 symbol × 一个 timestamp（日线）。

SQL DDL（PostgreSQL 兼容，SQLite 可退化为 TEXT）：

```sql
CREATE TABLE IF NOT EXISTS regime_state_daily (
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(16) NOT NULL DEFAULT 'BTCUSDT',
    price_close     DOUBLE PRECISION NOT NULL,
    level_raw       DOUBLE PRECISION NOT NULL,
    trend_raw       DOUBLE PRECISION NOT NULL,
    level_smooth    DOUBLE PRECISION NOT NULL,
    trend_smooth    DOUBLE PRECISION NOT NULL,
    regime_probs    JSONB NOT NULL,           -- 8 个 key-value
    consensus       DOUBLE PRECISION NOT NULL,
    hmm_state       SMALLINT NOT NULL,
    bocpd_cp_prob   DOUBLE PRECISION NOT NULL,
    indicators      JSONB NOT NULL,           -- 12 个指标原始值
    data_version    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (timestamp, symbol)
);

CREATE INDEX idx_regime_state_daily_ts ON regime_state_daily (timestamp);
```

### 4.2 快捷快照表 `regime_trajectory_90d`

用于前端首屏秒开。每次写入 `regime_state_daily` 新行时同步覆盖更新（只有 1 行）：

```sql
CREATE TABLE IF NOT EXISTS regime_trajectory_90d (
    symbol          VARCHAR(16) PRIMARY KEY,
    updated_at      TIMESTAMPTZ NOT NULL,
    trajectory      JSONB NOT NULL            -- 最近 90 条 RegimeStateFrame 精简版数组
);
```

### 4.3 权重表 `regime_model_weights`

供在线学习迭代使用：

```sql
CREATE TABLE IF NOT EXISTS regime_model_weights (
    week_start      DATE PRIMARY KEY,
    level_weights   JSONB NOT NULL,            -- 6 个 float
    trend_weights   JSONB NOT NULL,            -- 5 个 float
    regime_centers  JSONB NOT NULL,            -- 8 × [Lc, Tc]
    max_daily_delta DOUBLE PRECISION NOT NULL,
    objective       DOUBLE PRECISION NOT NULL, -- 当周目标函数值
    comment         TEXT
);
```

---

## 五、前端可视化设计（四面板仪表盘）

### 5.1 总体布局

2×2 栅格（大屏）/ 1×4 纵向（小屏）。

```
┌───────────────────────────────────┬───────────────────────────────────┐
│ Panel 1: 形态演化轨迹图            │ Panel 2: 共识点阵图 (FOMC Style)  │
│ Level-Trend Scatter + Trajectory  │ 12 指标 × 8 态 Dot Matrix        │
│ (动画播放 + Hover Tooltip)        │ + 列底概率聚合条                  │
├───────────────────────────────────┼───────────────────────────────────┤
│ Panel 3: 8 态概率堆叠面积图        │ Panel 4: 指标演变诊断条            │
│ 90 日 × 8 态 (Stacked Area)       │ 12 指标 × 90 日 Sparkline/热力行  │
│ + 共识度反向黑实线                 │ (绿=看多 / 黄=中性 / 红=看空)      │
└───────────────────────────────────┴───────────────────────────────────┘
```

### 5.2 Panel 1：形态演化轨迹图

**借鉴**：美联储点阵图的散点 + 路径动画
- x 轴 = Level Score，y 轴 = Trend Score
- 背景 = 8 象限半透明色（按 8 态配色，Ridge 平滑过渡）
- 白色细线 = 过去 90 日轨迹（最后 7 日加粗 3px）
- 圆点 = 每日位置：
  - 大小 ∝ 共识度（半径 3~12 px）
  - 颜色 = Top-1 主导态颜色
  - 价格变化热 → 叠加色阶（高=红，低=蓝）
- **交互**：
  - 播放按钮：从 Day 1 → Day 90 动画演进（10fps）
  - Hover：tooltip 显示 `日期 / 价格 / (L,T) / Top3 概率`
  - 点选某一天 → 所有面板同步聚焦该日

### 5.3 Panel 2：共识点阵图（FOMC Dot Plot Style）

**借鉴**：FOMC 点阵图的"多委员投票 → 分布密度"
- 12 行 × 8 列矩阵
- 每格一个圆点：size = 指标对该态的支持强度（映射 1-6 px），color = 指标色系
- 指标→形态支持度计算：对每个指标值，求其在「该形态训练样本中该指标分布」上的 CDF 值
- 每列底部一条聚合条形：height = 最终 8 态概率（即 Panel 3 当日 top 截面）
- 行右侧加"指标当前值"的色阶指示条（快速了解指标实际读数）

### 5.4 Panel 3：8 态概率堆叠面积图

- x = 90 天时间轴
- y = 0~1 概率轴
- 8 条半透明堆叠面积，颜色 = 8 态规范色
- 顶部黑色实线 = 1 - consensus（**分歧度**曲线）→ 越高越分歧
- 垂直参考线：BOCPD 变点日高亮竖线
- **交互**：拖动选择区间 → Panel 1 只显示区间轨迹；Panel 2 切换显示区间平均支持度

### 5.5 Panel 4：指标演变诊断条

- 每行 = 1 个指标（12 行）
- 横向 = 90 天
- 渲染模式：**双模式切换**（单选按钮）
  - Sparkline 模式：指标值走势小折线 + ±1σ 带
  - 热力模式：指标归一化 → 色阶（绿看多→黄中性→红看空）
- 每行列尾 = 当前值（大字号 + 色阶标签）
- 含义 = 让用户一眼理解 Level/Trend 是怎么来的

### 5.6 API 接口契约

```
GET /api/regime/evolution/latest?symbol=BTCUSDT&window=90
→ {
     trajectory: [{t,level_raw,trend_raw,level_smooth,trend_smooth,regime_probs,consensus,price}]   // 90
     dotplot:    {rows: [12指标], cols: [8态名], matrix: float[12][8], marginal_probs: float[8]}  // 最新1日
     indicators: {[ind_name]: [float × 90]}                                                     // 12×90
     snapshot:   {...RegimeStateFrame latest}
  }

GET /api/regime/evolution/trajectory?start=&end=&symbol=
GET /api/regime/evolution/dotplot_average?start=&end=&symbol=
```

### 5.7 前端实现路径

- **新页面**：`10-经典指标系统/frontend/src/pages/RegimeEvolutionPage.tsx`（挂在现有 router 下）
- **图表库**：沿用 `dream-data-analysis` 中的 Plotly（Trajectory 用 Scatter、堆叠面积用 `go.Scatter stackgroup`、热力行用 `go.Heatmap`；点阵图用 SVG 组件画（Plotly 不原生支持 dot matrix））
- **UI**：Tailwind CSS + 2×2 grid，响应式
- **状态管理**：React Context（`EvolutionContext`），四个面板共享选中的时间区间 & focus 日期

---

## 六、实施路线与里程碑（Roadmap）

### 6.1 Phase 0：骨架与最小可运行版（~3 天）

目标：跑通六层流水线，能在真实 BTC 数据上产出 Level-Trend 曲线。

- [ ] L1 指标银行：基于 `ma200_cycle_features.py` + `multi_timeframe_features.py`，产出 12 指标
- [ ] L2 Score Composer：实现 Level/Trend 加权合成 + 规则1 钳制
- [ ] L3 平滑：HMM Viterbi（GaussianHMM hmmlearn）
- [ ] L4 映射：§2.5 软分配 8 概率
- [ ] L5 存储：JSON file backend（先不用 DB，快速原型）
- [ ] **验证**：在 2423 条 BTC 数据上跑通，输出 `trajectory.json`

### 6.2 Phase 1：完善机制 + 后端 API（~4 天）

- [ ] 规则2 Sperandeo 1-2-3 渐进调整（含 Swing 检测）
- [ ] 规则4 BOCPD 变点加权
- [ ] L4-2 点阵图矩阵（12×8 支持度）
- [ ] L4-3 共识度
- [ ] L4-4 与 LGBM 0.7:0.3 概率加权（独立验证信号）
- [ ] SQLite 持久化 + 4 种 REST API（Express 路由）
- [ ] **验证**：Top-3 命中率 ≥ 0.60

### 6.3 Phase 2：前端四面板仪表盘（~4 天）

- [ ] 路由 + 页面骨架
- [ ] Panel 1 轨迹图（含动画播放）
- [ ] Panel 2 点阵图（SVG dot matrix）
- [ ] Panel 3 8 态堆叠面积
- [ ] Panel 4 指标诊断条（Sparkline/Heatmap 双模式）
- [ ] 全局联动（Hover / 区间选择 / 日期焦点同步）
- [ ] **验证**：前端交互 OK，动画流畅

### 6.4 Phase 3：在线学习 + 回测验证（~3 天）

- [ ] 周度 batch 脚本（BayesOpt + 网格）
- [ ] 权重持久化 regime_model_weights
- [ ] 参数迭代边界 + 回退机制
- [ ] WalkForward 5 折完整回溯（对比旧范式 F1）
- [ ] **验收**：Top-3 命中率 ≥ 0.70；Macro F1 ≥ 0.45；连续性 ≤ 0.20 / 天

### 6.5 Phase 4（可选）：实盘部署

- [ ] 与 `a6_regime_monitor.py` 对接（输出 regime_probs + consensus，替代原分类器）
- [ ] 易经推理系统 `_regime_pred_multipliers` 改用新引擎 consensus 加权
- [ ] Grafana 额外面板（可选）

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Level/Trend 权重设定不当，输出曲线失真 | 中 | 高 | 初始权重由 8 态历史标签的 mean(L,T) 反推校准；Phase 0 产出曲线后人工审阅 BTC 2021 牛市顶 / 2022 熊市底 / 2023-2024 减半牛 三个关键区间 |
| 8 态中心坐标偏移导致概率分布失真 | 中 | 中 | 先由 2423 条历史标签的 (Level,Trend) 样本均值做冷启动中心；在线学习周度微调 |
| HMM 训练不稳定（观测样本偏少）| 低 | 中 | EMA 兜底平滑独立可用；HMM 失败自动降级 EMA |
| BOCPD 变点误判过多 → Trend 抖动 | 低 | 中 | P>0.7 才触发；5 日渐进；同时满足「变点日量能 ≥ 1.5× 均量」双重门槛 |
| 前端 Plotly / SVG 性能（90 天×多维）| 低 | 低 | 数据量极小（KB级），无需优化 |
| 在线学习过拟合（周度权重振荡）| 中 | 中 | 权重变化 ±10% 硬限；目标函数下降 ≥2% 拒绝更新 |

---

## 八、验收标准（Go/No-Go）

**v1 Go 条件（全部满足进入实盘挂钩）：**

1. WalkForward 5 折 **Top-3 命中率 ≥ 0.70**
2. WalkForward 5 折 **Macro F1 ≥ 0.45**（比旧范式 0.299 提升 ≥50%）
3. 全样本 **坐标连续性** = 日均 |ΔL| + |ΔT| ≤ 0.20 格
4. 拐点识别滞后（Sperandeo 123 完成时点 vs 真实反转极值点）≤ 10 根日线
5. 人工检视 2021Q4 顶部 / 2022Q4 底部 / 2024Q2 减半启动 / 2025 本轮 四个关键区间的轨迹曲线合理
6. 四面板前端视觉验收通过

## 九、参考与灵感来源

1. **Regime Dashboard 2.0** (GitHub MiggoyGHP/Regime-Dashboard-2.0) — Level/Trend 二维评分法的灵感源
2. **Stan Weinstein 《Secrets for Profiting in Bull and Bear Markets》** — 四阶段生命周期
3. **Victor Sperandeo 《专业投机原理》** — 1-2-3 法则 & 道氏 HH/HL 应用
4. **Dow Theory Navi (dow-theory-navi.com)** — 道氏 4 原則量化判定 + 7 阶段公开算法
5. **pythonfintech.com: Market Stage Detection** — Weinstein Stage + MA 斜率 + slope 实现
6. **GitHub bennycode/trading-signals #841** — Zero-Lag Dow Theory 实时 HH/HL 检测器
7. **美联储 FOMC 点阵图方法论**（datascienceplus.com / rubenhm.org 复现文章）— 不预测只描述的共识表达哲学
8. **GitHub ksanjay/stage-analysis-stocks** — Weinstein Stage 4 分类简化实现
9. **GitHub elninos/stock-dashboard `backtest_stage_aware.py`** — Dow Theory × Weinstein × Chandelier 组合交易决策
10. **Minervini SEPA Trend Template** — Weinstein Stage 2 的 8 条件量化扩展
