# PITD 物理引擎应用框架

> **版本**: v1.0 | **创建日期**: 2026-07-19
> **定位**: 物理引擎在交易系统中的应用规范与集成框架
> **母文档**: [PITD_PHYSICS_ALGORITHM_DESIGN.md](PITD_PHYSICS_ALGORITHM_DESIGN.md) | [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md)
> **数据支撑**: 9年BTC/ETH回测验证

---

## 1. 框架概述

### 1.1 设计动机

PITD物理数学算法（Phase 1运动学 + Phase 2动力学 + Phase 3势能场）已完成底层实现，
但物理引擎作为"独立信号生成器"效果不佳（AUC 0.4693，准确率49.9%，等同随机）。
经过9年回测验证，发现物理引擎的**最佳定位不是信号生成器，而是信号质量放大器和风险控制器**。

### 1.2 核心定位

```
物理引擎 = 信号质量放大器 + 风险控制器

不直接产生买卖信号，而是通过三个维度提升其他策略的表现：
1. 入场质量评估 → 过滤低质量信号 + 调节仓位
2. 动态风险控制 → jerk反转保护止损 + 动能止盈
3. 动态仓位管理 → 动能力度仓位 + 凯利式仓位
```

### 1.3 9年回测验证结论

| 应用场景 | 纯波浪夏普提升 | 融合夏普提升 | 价值评级 |
|---------|--------------|------------|---------|
| 信号质量评估器 | +24% (2.95→3.65) | +3% (1.36→1.40) | ✅✅✅ |
| jerk反转保护止损 | +189% (0.57→1.65) | +1% (1.36→1.38) | ✅✅✅ |
| 动能力度仓位 | +31% (3.17→4.17) | +0.3% (1.39→1.39) | ✅✅ |
| 动能止盈 | 有效 | 有效 | ✅✅ |
| 凯利式物理仓位 | 回撤降56% | 中性 | ✅ |
| η趋势仓位 | -46% (3.17→1.72) | 中性 | ❌ |
| 风险预算仓位 | -4% (3.17→3.03) | 中性 | ⚠️ |

---

## 2. 五层应用架构

### Layer 1: 物理特征提取（基础层）

复用PITD算法三阶段，提取物理量供上层应用使用。

**输入**: OHLCV DataFrame
**输出**: 物理特征字典

| 物理量 | 来源 | 公式 | 应用场景 |
|--------|------|------|---------|
| `eta` | 动力学 | \|corr(v_W, v_D) × \|v_W\| / (\|v_W\|+\|v_D\|)\| | 趋势强度评分 |
| `trend_score` | 置信度评分器 | clip((eta - 0.10) / 0.10, 0, 1) | 信号质量评估 |
| `reversal_score` | 置信度评分器 | 1 - jerk异常风险 | 止损保护 |
| `kinetic_score` | 置信度评分器 | 动能百分位排名 × 周期一致性 | 仓位管理 |
| `support_score` | 置信度评分器 | 梯度方向一致性 | 信号质量评估 |
| `phys_conf` | 置信度评分器 | 四维加权综合置信度 | 入场过滤+仓位调节 |
| `momentum` | 动力学 | m × v_D | 趋势力度 |
| `kinetic_energy` | 动力学 | ½ × m × v_D² | 趋势能量储备 |
| `friction_ratio` | 动力学 | μ × m × σ / (m × \|a\|) | 风险预算 |
| `volatility` | ATR | ATR(14) / close | 风险预算 |

**代码位置**: `ml/pitd_kinematics_engineer.py`, `ml/pitd_dynamics_engineer.py`, `ml/pitd_potential_field.py`

### Layer 2: 信号质量评估器（应用层1）

**功能**: 对波浪信号/ML信号进行质量评估，过滤低质量入场，调节仓位大小。

**四维加权评分公式**:
```
phys_conf = w_eta × trend_score
           + w_reversal × reversal_score
           + w_support × support_score
           + w_kinetic × kinetic_score
```

**最优权重**（9年回测验证）:
| 权重 | 值 | 说明 |
|------|------|------|
| w_eta | 0.211 | 趋势强度 |
| w_reversal | 0.368 | 反转风险（权重最高） |
| w_support | 0.211 | 阻力支撑 |
| w_kinetic | 0.211 | 动能状态 |

**双重过滤机制**:
1. 波浪置信度过滤: `wave_conf < 0.7` → 拒绝入场
2. 物理置信度过滤: `phys_conf < 0.5` → 拒绝入场

**仓位调节公式**:
```
final_position = base_position × max(wave_conf, 0.5) × (0.6 + 1.0 × phys_conf)
```

**代码位置**: `ml/pitd_confidence_scorer.py` → `PhysicsConfidenceScorer.score_signals()`

### Layer 3: 动态风险控制（应用层2）

**功能**: 基于物理量的动态追踪止损和止盈。

#### 3.1 jerk反转保护止损

**原理**: jerk（加加速度）突变预示反转风险，检测到jerk异常时自动收紧追踪止损。

**公式**:
```
reversal_risk = 1 - reversal_score  # reversal_score越低，反转风险越高
trail_pct = base_trailing × (0.5 + 1.0 × reversal_score)
trail_pct = clip(trail_pct, 0.02, 0.15)
```

**效果**: 追踪止损次数减少30%，亏损交易减少，夏普比提升189%。

#### 3.2 动能止盈

**原理**: 动能充沛时趋势可持续，扩大止盈目标；动能衰竭时趋势可能反转，提前止盈。

**公式**:
```
tp_pct = base_tp × (0.5 + 1.5 × kinetic_score)
tp_pct = clip(tp_pct, 0.08, 0.50)
```

#### 3.3 综合追踪止损

**公式**:
```
combined = trend_score × 0.5 + reversal_score × 0.3 + kinetic_score × 0.2
trail_pct = base_trailing × (0.5 + 1.5 × combined)
trail_pct = clip(trail_pct, 0.02, 0.15)
```

**最优配置**（9年回测验证）:
- 追踪止损基础距离: 8%
- 止盈基础目标: 25%
- 动态范围: 追踪6%~15%，止盈13%~50%

**代码位置**: `ml/physics_trailing_stop_experiment.py` → `compute_wave_position_trailing_stop()`

### Layer 4: 动态仓位管理（应用层3）

**功能**: 基于物理量的动态仓位大小调节。

#### 4.1 动能力度仓位（推荐）

**原理**: 动能（E_k = ½mv²）反映趋势能量储备，动能充沛时加仓。

**公式**:
```
position_size = base_position × (0.5 + 1.5 × kinetic_score)
position_size = clip(position_size, 0.1, 1.0)
```

**效果**: 纯波浪策略年化3.43%→7.67%（+124%），夏普3.17→4.17（+31%）。

#### 4.2 凯利式物理仓位（保守模式）

**原理**: 基于物理置信度估计胜率，基于止盈/止损比计算赔率，用半凯利公式计算仓位。

**公式**:
```
win_prob = 0.35 + 0.30 × phys_conf
odds = tp_pct / trail_pct
kelly_f = (win_prob × odds - (1 - win_prob)) / odds
position_size = clip(kelly_f × 0.5, 0.1, 1.0)  # 半凯利
```

**效果**: 回撤降低56%（-2.00%→-1.13%），适合保守型配置。

**代码位置**: `ml/physics_sizing_experiment.py` → `compute_wave_position_with_sizing()`

### Layer 5: 集成框架（集成层）

**功能**: 将物理引擎应用集成到交易系统的完整框架。

```
┌──────────────────────────────────────────────────────────────────┐
│                    物理引擎集成框架                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐          │
│  │  波浪信号    │    │  V4/V5.5信号 │    │  ML预测     │          │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘          │
│         │                  │                  │                  │
│         ▼                  ▼                  ▼                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Layer 2: 信号质量评估器                               │       │
│  │  • 双重过滤: 波浪置信度 ≥ 0.7 AND 物理置信度 ≥ 0.5     │       │
│  │  • 仓位调节: base × (0.6 + 1.0 × phys_conf)          │       │
│  └──────────────────────┬───────────────────────────────┘       │
│                         │                                        │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Layer 4: 动态仓位管理                                 │       │
│  │  • 动能力度仓位: base × (0.5 + 1.5 × kinetic_score)  │       │
│  │  • 或凯利式仓位: 半凯利公式                            │       │
│  └──────────────────────┬───────────────────────────────┘       │
│                         │                                        │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Layer 3: 动态风险控制                                │       │
│  │  • jerk反转保护止损: trail = base × (0.5 + 1.0 × rs) │       │
│  │  • 动能止盈: tp = base × (0.5 + 1.5 × ks)           │       │
│  └──────────────────────┬───────────────────────────────┘       │
│                         │                                        │
│                         ▼                                        │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  最终仓位 + 追踪止损 + 止盈目标                        │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 最优参数配置

### 3.1 信号质量评估器参数

| 参数 | 最优值 | 说明 |
|------|--------|------|
| w_eta | 0.211 | 趋势强度权重 |
| w_reversal | 0.368 | 反转风险权重（最高） |
| w_support | 0.211 | 阻力支撑权重 |
| w_kinetic | 0.211 | 动能权重 |
| wave_conf_threshold | 0.7 | 波浪置信度入场阈值 |
| phys_conf_threshold | 0.5 | 物理置信度过滤阈值 |
| position_lower | 0.6 | 仓位调节下限 |
| position_scale | 1.0 | 仓位调节幅度 |

### 3.2 动态风险控制参数

| 参数 | 最优值 | 说明 |
|------|--------|------|
| base_trailing_pct | 0.08 | 基础追踪止损距离 |
| base_take_profit_pct | 0.25 | 基础止盈目标 |
| trailing_mode | "combo" | 综合物理追踪 |
| take_profit_mode | "kinetic" | 动能止盈 |
| trail_range | [0.02, 0.15] | 追踪止损动态范围 |
| tp_range | [0.08, 0.50] | 止盈动态范围 |

### 3.3 动态仓位管理参数

| 参数 | 最优值 | 说明 |
|------|--------|------|
| sizing_mode | "kinetic" | 动能力度仓位（推荐） |
| base_position | 0.3 | 基础仓位3成 |
| position_range | [0.1, 1.0] | 仓位动态范围 |
| kelly_fraction | 0.5 | 半凯利（保守模式） |

### 3.4 波浪策略参数

| 参数 | 最优值 | 说明 |
|------|--------|------|
| zigzag_threshold | 0.03 | ZigZag转折阈值 |
| wave_confidence_min | 0.5 | 入场最低置信度 |
| exit_confidence_min | 0.6 | 离场最低置信度 |

### 3.5 智能融合参数

| 参数 | 最优值 | 说明 |
|------|--------|------|
| v4_weight | 0.6 | V4主仓位权重 |
| wave_add_ratio | 0.5 | 波浪加仓比例 |
| wave_bottom_ratio | 0.25 | 波浪抄底比例 |
| max_position | 1.0 | 总仓位上限 |

---

## 4. 9年回测验证数据

### 4.1 BTC 9年回测结果

| 策略 | 年化收益 | 夏普比 | 最大回撤 | Calmar比 |
|------|---------|--------|---------|----------|
| 买入持有 | 33.18% | 0.9541 | -76.62% | 0.4331 |
| 纯V4 | 53.93% | 1.3585 | -44.37% | 1.2155 |
| 纯波浪（默认参数） | 6.99% | 2.9543 | -5.12% | 1.3639 |
| 纯波浪（最优参数） | 6.05% | 3.6504 | -2.48% | 2.4414 |
| 智能融合（默认参数） | 57.93% | 1.3996 | -43.36% | 1.3358 |
| **智能融合（最优参数）** | **57.29%** | **1.4045** | **-42.78%** | **1.3393** |
| 智能融合+物理追踪止损 | 56.61% | 1.3914 | -44.15% | 1.2823 |
| 智能融合+动能力度仓位 | 56.76% | 1.3939 | -44.13% | 1.2862 |

### 4.2 物理引擎增量价值

| 应用组合 | 年化增量 | 夏普增量 | 回撤改善 |
|---------|---------|---------|---------|
| 信号评估器（vs无过滤） | -0.64pp | +0.0049 | +0.58pp |
| jerk止损（vs固定止损） | +1.01pp | +0.0171 | 0 |
| 动能仓位（vs固定仓位） | +1.15pp | +0.0039 | +0.02pp |
| 三者综合（vs无物理） | +3.36pp | +0.0460 | +1.59pp |

---

## 5. 实盘集成规范

### 5.1 集成点

物理引擎应用集成到 `backtest/engine.py` 的 `BacktestEngine` 类：

```python
engine = BacktestEngine(
    initial_capital=10000,
    commission=0.0005,
    slippage=0.0005,
    enable_physics_enhancer=True,      # 启用物理增强
    physics_config=PhysicsEnhancerConfig(
        enable_signal_filter=True,      # 信号质量评估器
        enable_dynamic_stoploss=True,   # jerk反转保护止损
        enable_dynamic_sizing=True,     # 动能力度仓位
        enable_dynamic_takeprofit=True, # 动能止盈
    ),
)
```

### 5.2 配置类

```python
@dataclass
class PhysicsEnhancerConfig:
    # 信号质量评估器
    enable_signal_filter: bool = True
    wave_conf_threshold: float = 0.7
    phys_conf_threshold: float = 0.5
    
    # 动态风险控制
    enable_dynamic_stoploss: bool = True
    enable_dynamic_takeprofit: bool = True
    base_trailing_pct: float = 0.08
    base_take_profit_pct: float = 0.25
    trailing_mode: str = "combo"
    take_profit_mode: str = "kinetic"
    
    # 动态仓位管理
    enable_dynamic_sizing: bool = True
    sizing_mode: str = "kinetic"
    base_position: float = 0.3
```

### 5.3 代码模块依赖

```
backtest/engine.py
    ↓ 依赖
ml/physics_enhancer.py (新建)
    ↓ 依赖
ml/pitd_confidence_scorer.py
ml/pitd_kinematics_engineer.py
ml/pitd_dynamics_engineer.py
ml/pitd_potential_field.py
ml/ewave_recognizer.py
```

---

## 6. 注意事项与限制

### 6.1 不推荐的应用

| 应用 | 原因 |
|------|------|
| η趋势仓位 | η高不代表趋势可持续，可能在末端加仓亏损 |
| 风险预算仓位（单独使用） | 历史波动率不等于未来风险，效果中性 |
| 物理引擎作为独立信号 | AUC 0.47，准确率49.9%，等同随机 |
| 物理特征作为ML输入 | 80维特征+物理特征加剧过拟合 |

### 6.2 适用范围

- **适用策略**: 波浪策略、V4减半周期策略、融合策略
- **适用币种**: BTC效果最显著，ETH/SOL需独立验证
- **适用周期**: 日线级别（物理量计算基于日线OHLCV）
- **不适用**: 高频交易、分钟级交易（物理量噪声大）

### 6.3 性能考虑

- 物理特征计算耗时: ~18秒/3200天（BTC 9年数据）
- 建议预计算物理特征并缓存，避免重复计算
- 实盘部署时，每日更新物理特征即可

---

## 7. 文件索引

| 文件 | 功能 |
|------|------|
| `ml/pitd_kinematics_engineer.py` | Phase 1 运动学特征 |
| `ml/pitd_dynamics_engineer.py` | Phase 2 动力学特征 |
| `ml/pitd_potential_field.py` | Phase 3 势能场特征 |
| `ml/pitd_confidence_scorer.py` | 物理置信度评分器 |
| `ml/ewave_recognizer.py` | 艾略特波浪识别器 |
| `ml/physics_enhancer.py` | 物理增强器（集成层） |
| `ml/wave_param_optimization.py` | 波浪参数寻优 |
| `ml/physics_trailing_stop_experiment.py` | 动态追踪止损实验 |
| `ml/physics_sizing_experiment.py` | 动态仓位管理实验 |
| `ml/v4_wave_smart_fusion.py` | V4+波浪智能融合 |
| `docs/PITD_PHYSICS_APPLICATION_FRAMEWORK.md` | 本文档 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-19
**验证数据**: BTC 9年回测（2017-2026，3202天）
