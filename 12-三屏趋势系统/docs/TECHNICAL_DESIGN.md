# 技术设计文档 — 三屏趋势系统

> **版本**: v4.0 | **更新日期**: 2026-07-19
> **定位**: 模块级技术设计文档，描述架构、数据流、算法细节
> **阶段**: Phase 6 — 双线策略架构（V4+波浪互斥融合 主线 + V5.5 ML 副线）
> **主线策略**: V4 + 波浪互斥融合 — BTC 年化 56.43%，夏普 1.41，回撤 -43.31%
> **副线策略**: V5.5 ML 基线 — 实验状态，需重新设计特征工程
> **策略线管理**: [STRATEGY_LINES.md](STRATEGY_LINES.md) — 主副线隔离规则
> **版本演进**: v2（牛熊经验法则）→ v3（做空优化）→ v4（减半周期逃顶）→ v4+波浪互斥融合（当前主线）

---

## 目录

- [1. 系统架构](#1-系统架构)
- [2. 数据流与决策链路](#2-数据流与决策链路)
- [3. 核心算法](#3-核心算法)
- [4. 接口设计](#4-接口设计)
- [5. 配置管理](#5-配置管理)
- [6. 测试体系](#6-测试体系)
- [7. 版本演进](#7-版本演进)
- [8. 双线策略架构](#8-双线策略架构)
- [9. V4基线策略与优化原则](#9-v4基线策略与优化原则)
- [10. PITD物理数学趋势推理算法](#10-pitd物理数学趋势推理算法)

---

## 1. 系统架构

### 1.1 模块定位

| 属性 | 说明 |
|------|------|
| 模块名称 | 12-三屏趋势系统 |
| 英文代号 | screen-trend |
| 核心职责 | V4定方向 + 波浪择时加仓 + 物理置信度评估 + 仓位计算 |
| 设计模式 | 策略模式 + 责任链模式 + 观察者模式 |
| 主线策略 | V4 + 波浪互斥融合（实盘部署） |
| 副线策略 | V5.5 ML 基线（实验状态） |
| 决策优先级链 | BTC风向标闸门 → 趋势一致性 → 置信度评估 → 五大算法 → **V4定方向** → **波浪择时加仓** → 物理调节 → 价值风险 |

### 1.2 双线策略架构

三屏趋势系统维护两条可持续演进的策略线，详见 [STRATEGY_LINES.md](STRATEGY_LINES.md)：

```
┌─────────────────────────────────────────────────────────────┐
│                    主策略线 [MAIN]                            │
│              V4 + 波浪互斥融合（实盘部署）                    │
│  V4减半周期策略 ──→ 波浪择时加仓 ──→ 物理置信度调节           │
│  回测：年化 56.43% | 夏普 1.41 | 回撤 -43.31%                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  机器学习基线 [ML_BASELINE]                   │
│              V5.5 LightGBM（实验状态）                       │
│  28维哲学特征 ──→ LightGBM ──→ Walk-Forward 验证             │
│  回测：年化 4.31% | 夏普 0.30 | 状态：严重过拟合              │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 七层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                       入口层 (engine.py)                             │
│   compute_full_trading_signal() / five_algo_decision()               │
│   BTC风向标闸门评估 / 价值风险评估 / 加仓决策                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────────────┐
│                        核心算法层 (core/)                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────┐  │
│  │ indicators  │ │ trend_      │ │ fusion      │ │ risk_reward  │  │
│  │ 技术指标计算│ │ consistency │ │ 多周期融合  │ │ 价值风险评估│  │
│  │             │ │ 趋势一致性  │ │             │ │ 仓位+加仓    │  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘ └──────┬───────┘  │
│         │               │               │               │          │
│         └────────┬──────┴────────┬──────┴────────┬──────┘          │
│                  │               │               │                  │
│         ┌────────▼────────┐ ┌────▼─────┐ ┌──────▼──────┐           │
│         │ dynamic_weights │ │  config  │ │ risk_control│           │
│         │ 动态权重调整    │ │ 配置管理  │ │ 极端风控    │           │
│         └─────────────────┘ └──────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────────────┐
│                        数据层 (data/)                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ market_data  │  │ fundamental_ │  │ signal_pool/ │               │
│  │ 市场数据获取 │  │ data         │  │ 信号池扫描器 │               │
│  │ (多周期K线)  │  │ 基本面数据   │  │ pool.json    │               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────────────┐
│                      桥接集成层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │
│  │ signals.py   │  │ classic_     │  │ exit_        │               │
│  │ Freqtrade信号│  │ bridge.py    │  │ integration  │               │
│  │ 读取与对齐   │  │ 经典系统桥接 │  │ 离场系统集成│               │
│  └──────────────┘  └──────────────┘  └──────────────┘               │
└─────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────────────┐
│                      回测与ML层                                      │
│  ┌──────────────┐  ┌──────────────┐                                 │
│  │ backtest/    │  │ ml/          │                                 │
│  │ 策略回测引擎 │  │ 机器学习策略│                                 │
│  └──────────────┘  └──────────────┘                                 │
└─────────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────────────┐
│                      执行层 (experiments/ab-trading/)                │
│  screen_executor.py — 逐仓下单、止盈止损、加仓执行                    │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.3 目录结构

```
12-三屏趋势系统/
├── core/                    # 核心算法模块
│   ├── __init__.py
│   ├── config.py            # 配置管理（含逐仓/价值风险/风向标配置）
│   ├── composite_predictor.py # 综合预测引擎（技术基线+基本面三维度调节）
│   ├── dynamic_weights.py   # 动态权重调整
│   ├── fundamental_screen1.py # Path B 核心模块：7维基本面分析（Tavily+算法）
│   ├── fusion.py            # 多时间周期融合（技术面+基本面）
│   ├── indicators.py        # 技术指标计算（静态+三维动态）
│   ├── risk_control.py      # 极端行情风控守卫
│   ├── risk_reward.py       # 价值风险评估 + 仓位计算 + 加仓决策
│   └── trend_consistency.py # 趋势一致性判断（静态+三维动态融合）
├── data/                    # 数据层
│   ├── __init__.py
│   ├── fundamental_data.py  # 基本面数据（研报回退到经典指标）
│   └── market_data.py       # 市场数据获取
├── signal_pool/             # Freqtrade信号池
│   ├── pool.json            # 信号池缓存
│   └── scanner.py           # 信号池扫描器
├── backtest/                # 回测引擎
│   ├── engine.py            # 回测核心引擎
│   ├── strategy.py          # 策略定义
│   ├── metrics.py           # 绩效指标
│   ├── walk_forward.py      # 滚动验证
│   └── run_backtest.py      # 回测入口
├── ml/                      # 机器学习策略 + 基线策略
│   ├── halving_top_exit_strategy.py  # ⭐ V4基线策略（减半周期逃顶）
│   ├── enhanced_ma200_v3_strategy.py # V3策略框架（抄底+逃顶）
│   ├── philosophy_feature_engineer.py # 哲学贡献特征工程（22个特征）
│   ├── four_objective_feature_mapper.py # 四类目的特征映射器
│   ├── scenario_backtest_engine.py  # 分场景回测引擎
│   ├── closed_loop_manager.py       # 闭环迭代管理器
│   ├── v2_baseline_optimization_principles.md # V4基线优化原则
│   ├── four_objective_framework_design.md # 四类目的+动态实践闭环设计
│   ├── ml_strategy.py       # ML策略核心
│   ├── models.py            # 模型定义
│   ├── tuner.py             # 超参调优
│   └── version_manager.py   # 模型版本管理
├── tests/                   # 测试模块
│   ├── __init__.py
│   └── test_core.py         # 核心算法单元测试
├── docs/                    # 技术文档
│   ├── TECHNICAL_DESIGN.md  # 技术设计文档（本文件）
│   ├── ENGINEERING_INDEX.md # 工程索引
│   └── trend-screen-system-design.md
├── classic_bridge.py        # 经典指标系统桥接
├── exit_integration.py      # 离场系统集成
├── signals.py               # Freqtrade信号读取与对齐
├── engine.py                # 主引擎（风向标+五大算法+价值风险+加仓）
├── start_services.sh        # 服务启动脚本
└── README.md
```

---

## 2. 数据流与决策链路

### 2.1 完整决策优先级链

```
优先级 0: BTC风向标闸门（宏观方向过滤，最高优先级）
    │
    ├── 强制做多（站上周线MA200）：拦截所有BEAR信号
    ├── 做空闸门开（跌破日线MA128）：拦截所有BULL信号
    └── 中间状态：双向开放
    ↓
优先级 1: 趋势一致性检测（Screen 1）
    │
    ├── 周线NEUTRAL不阻断日线（弱一致）
    ├── 周线与日线同向 → 一致
    └── 周线与日线反向 → 不一致（WAIT）
    ↓
优先级 2: 置信度评估（Screen 2）
    │
    ├── 贝叶斯置信度 + 经典指标置信度融合
    ├── Freqtrade信号同向加权（1h×10%, 4h×15%）
    └── 置信度映射仓位档位（micro→heavy）
    ↓
优先级 3: Freqtrade入场信号触发（Screen 3）
    │
    ├── 1h/4h 多策略投票
    ├── 同向信号触发入场
    └── 无信号时高置信度降级入场（≥70%）
    ↓
优先级 4: 价值风险评估（仓位调整）
    │
    ├── Elder-ray趋势强度 + 背离检测
    ├── 30日波动率 vs BTC波动率放大
    ├── 风险回报比（RR）计算
    └── 价值<风险时仓位限制在5%以内
    ↓
执行: 逐仓模式下单
    ├── isolated margin, 5x杠杆上限
    ├── 50%初始仓位上限, 70%加仓上限
    ├── 自动止盈止损（波动率放大）
    └── 加仓系统（逆势背离+顺势趋势强度）
```

### 2.2 主入口数据流

```python
compute_full_trading_signal(spot_inst, is_btc):
  │
  ├─ fetch_candles(spot_inst, "1D"/"1W"/"1H")  ← 获取币种K线
  ├─ fetch_candles("BTC-USDT", "1D"/"1W")       ← 获取BTC数据（非BTC币种时）
  │
  ├─ fetch_fundamental_data(symbol)             ← 基本面数据
  │     └─ 缺失时回退: calc_classic_indicator_confidence()
  │
  ├─ fetch_entry_signals_from_classic(symbol)   ← Freqtrade入场信号
  │
  └─ compute_trend_signal_from_dataframes(...)
        │
        ├─ calc_trend_consistency()             ← 趋势一致性
        ├─ calc_bayesian_confidence()           ← 贝叶斯置信度
        ├─ calc_classic_indicator_confidence()  ← 经典指标置信度
        ├─ fuse_technical_fundamental()         ← 技术面+基本面融合
        ├─ _integrate_freqtrade_signals()       ← Freqtrade信号校准
        ├─ evaluate_btc_wind_vane()             ← BTC风向标闸门
        ├─ five_algo_decision()                 ← 五大算法综合决策
        │     └─ 风向标闸门 → 趋势一致 → 置信度 → Freqtrade触发
        └─ compute_value_risk_assessment()      ← 价值风险评估
              └─ 价值<风险时仓位限制在5%
```

### 2.3 最终信号输出结构

```python
{
    "symbol": "BTC",
    "price": 65000.0,
    "btc_wind_vane": {                    # BTC风向标状态
        "enabled": true,
        "long_gate_open": true,          # 做多闸门
        "short_gate_open": false,        # 做空闸门
        "force_long": true,              # 强制做多
        "prohibit_short": true,          # 禁止做空
        "btc_daily_ma128": 62000.0,
        "btc_weekly_ma200": 58000.0,
        "consecutive_below_ma128": 0,
        "weekly_above_ma200": true,
        "reason": "BTC周收盘站上MA200，强制做多，禁止做空"
    },
    "final_signal": {
        "direction": "BULL",             # BULL/BEAR/NEUTRAL
        "confidence": 72.5,              # 0-100
        "trend_consistent": true,
        "action": "ENTER_LONG",          # ENTER_LONG/ENTER_SHORT/WAIT
        "position": {
            "position_pct": 0.30,        # 仓位比例
            "tier": "moderate",
            "original_position_pct": 0.30
        },
        "decision_reason": "趋势一致+Freqtrade 4h看多+置信72.5%",
        "wind_vane_blocked": false,      # 是否被风向标拦截
        "leverage": 5.0,
        "margin_mode": "isolated",
        "max_position_pct": 0.50,
        "max_addon_position_pct": 0.70
    },
    "value_risk_assessment": {            # 价值风险评估
        "elder_ray": {...},
        "volatility": {...},
        "take_profit_stop_loss": {
            "take_profit_price": 67600.0,
            "stop_loss_price": 58500.0,
            "risk_reward": {...}
        },
        "value_gt_risk": true
    },
    "trend_consistency": {...},
    "bayesian_confidence": {...},
    "freqtrade_signals": {...},
    "generated_at": "2026-07-15T08:00:00Z"
}
```

---

## 3. 核心算法

### 3.1 BTC风向标闸门（Phase 3.1）

**宏观方向过滤器，全系统最高优先级。**

#### 三条大原则

| 规则 | 条件 | 效果 | 优先级 |
|------|------|------|--------|
| 规则3 | BTC周收盘价 **有效站上周线MA200** | 强制做多，禁止做空 | 最高 |
| 规则1 | BTC连续3日收盘价 **低于日线MA128** | 做空闸门打开，做多关闭 | 次之 |
| 中间 | 未跌破MA128且未站上MA200 | 双向开放 | 默认 |

#### 有效跌破/站上定义

- **有效跌破日线MA128**：连续 `BTC_WIND_VANE_BREAK_DAYS`（默认3）日收盘价 < MA128，避免单日假跌破
- **有效站上周线MA200**：周收盘价 > MA200（单周确认，周线本身低频）

#### 核心函数

```python
def evaluate_btc_wind_vane(btc_daily_df=None, btc_weekly_df=None) -> Dict:
    """
    返回:
    {
        "enabled": bool,
        "long_gate_open": bool,
        "short_gate_open": bool,
        "force_long": bool,
        "prohibit_short": bool,
        "prohibit_long": bool,
        "btc_daily_ma128": float,
        "btc_weekly_ma200": float,
        "consecutive_below_ma128": int,
        "weekly_above_ma200": bool,
        "daily_below_ma128_confirmed": bool,
        "reason": str,
    }
    """
```

#### 闸门集成点

`five_algo_decision()` 中优先级0检查：

```python
if btc_wind_vane and btc_wind_vane.get("enabled"):
    # 强制做多：拦截BEAR
    if btc_wind_vane.get("force_long") and direction == "BEAR":
        return {"action": "WAIT", "wind_vane_blocked": True, ...}
    # 做空闸门关闭：拦截BEAR
    if not btc_wind_vane.get("short_gate_open", True) and direction == "BEAR":
        return {"action": "WAIT", "wind_vane_blocked": True, ...}
    # 做多闸门关闭：拦截BULL
    if not btc_wind_vane.get("long_gate_open", True) and direction == "BULL":
        return {"action": "WAIT", "wind_vane_blocked": True, ...}
```

### 3.2 趋势一致性检测（Screen 1）

#### 三维动态融合 + 动态优先

- **静态投票**：传统MA/EMA/MACD等指标方向投票
- **三维动态**：方向 + 速度 + 加速度，捕捉趋势逆转
- **动态优先原则**：
  - 逆转信号 > 60% → 动态方向覆盖静态
  - 动态方向 = NEUTRAL → 回退到静态
  - 其他 → 动态方向为准

#### 一致性判断规则

| 周线 | 日线 | 一致性 | 说明 |
|------|------|--------|------|
| BULL | BULL | ✅ 一致 | 强一致 |
| BEAR | BEAR | ✅ 一致 | 强一致 |
| NEUTRAL | BULL/BEAR | ✅ 弱一致 | 周线无意见，日线主导 |
| BULL | BEAR | ❌ 不一致 | 趋势冲突，观望 |
| BEAR | BULL | ❌ 不一致 | 趋势冲突，观望 |

#### 置信度计算

- 强一致：`weekly_conf × WEEKLY_WEIGHT + daily_conf × DAILY_WEIGHT`
- 弱一致（周线NEUTRAL）：`daily_conf × DAILY_WEIGHT + weekly_conf × WEEKLY_WEIGHT × 0.3`
- 不一致：`min(weekly_conf, daily_conf) × 0.5`

### 3.3 置信度评估（Screen 2）

#### 五层置信度融合

```
贝叶斯置信度（bayesian）
  + 经典指标置信度（classic_indicator）
  + 技术面+基本面融合（fusion）
    + Freqtrade信号校准（+1h×10%, +4h×15%, 反向-10%）
    = 最终置信度（0-100）
```

#### 仓位档位映射

| 置信度阈值 | 仓位档位 | 仓位比例 |
|-----------|---------|---------|
| ≥85 | heavy | 60% |
| ≥75 | medium | 45% |
| ≥65 | moderate | 30% |
| ≥55 | light | 15% |
| ≥45 | trial | 5% |
| ≥0 | micro | 2% |

### 3.4 价值与风险评估（Phase 3）

#### Elder-ray 趋势强度检测

```python
def calc_elder_ray(klines, period=13) -> Dict:
    """
    返回: {
        "direction": "BULL"/"BEAR"/"NEUTRAL",
        "strength": 0-100,          # 趋势强度
        "bull_power": float,        # 多头力量
        "bear_power": float,        # 空头力量
        "ema_slope": float,         # EMA斜率
        "divergence": bool,         # 是否存在背离
        "divergence_type": "bull"/"bear"/None,
        "divergence_strength": 0-100,
    }
    """
```

#### 波动率放大机制

```python
vol_ratio = coin_volatility / btc_volatility
# 限制在 0.5x ~ 2.5x 范围
vol_ratio = max(0.5, min(2.5, vol_ratio))

tp_pct = BASE_TAKE_PROFIT_PCT * vol_ratio  # 默认4% × 波动率比
sl_pct = BASE_STOP_LOSS_PCT * vol_ratio    # 默认10% × 波动率比
```

#### 风险回报比（RR）

```python
risk = abs(entry_price - stop_loss_price)
reward = abs(take_profit_price - entry_price)
rr_ratio = reward / risk
value_gt_risk = rr_ratio >= RISK_REWARD_THRESHOLD  # 默认1.5
```

**价值<风险时的仓位限制**：初始仓位不超过5%。

### 3.5 加仓系统（Phase 3）

#### 两类加仓机制

| 加仓类型 | 触发条件 | 仓位上限 |
|---------|---------|---------|
| **逆势背离加仓** | 亏损≥阈值 + 背离 + 价值>风险 | 70%（含初始） |
| **顺势趋势强度加仓** | 盈利50% + 趋势强度≥65 | 70%（含初始） |

#### 逆势背离加仓（BTC vs 其他币种）

- **BTC**：亏损 ≥ 8% + 看涨/看跌背离
- **其他币种**：亏损 ≥ (8% × 波动率比) + 背离
- 最多加仓 2 次（`MAX_ADDON_COUNT`）
- 加仓间距随波动率放大

#### 顺势趋势强度加仓

- 未实现盈利 ≥ 50%（以初始止损距离为基准）
- Elder-ray 趋势强度 ≥ `TREND_STRENGTH_ADDON_THRESHOLD`（默认65）
- 加仓仓位 = 趋势强度 / 100 × 剩余可用仓位

### 3.6 逐仓模式（Phase 3）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MARGIN_MODE` | isolated | 逐仓模式，风险隔离 |
| `MAX_LEVERAGE` | 5.0 | 最大杠杆倍数 |
| `MAX_POSITION_PCT` | 0.50 | 初始最大仓位（50%） |
| `MAX_ADDON_POSITION_PCT` | 0.70 | 加仓后最大仓位（70%） |

### 3.7 最小阻力方向引擎 — 三屏趋势算法内核（Phase 3.5）

> **第一性原理**：市场总是沿着阻力最小方向运动。

#### 3.7.1 算法总览

```
时间三维 × 五维阻力算法 → 最小阻力三维模型(D/V/A) → 双向驱动判定 → 最小阻力方向
```

**核心等式**：

```
最小阻力方向 = f(时间三维, 五维阻力, 双向驱动模式)

其中：
  时间三维 = (长周期周线, 中周期日线, 小周期4H/小时)
  五维阻力 = (价格阻力, 量能阻力, 动量阻力, 趋势阻力, 基本面阻力)
  双向驱动 = 趋势延续(大→小) ∪ 量变催生(小→大)
```

#### 3.7.2 时间三维映射

| 时间维度 | 周期 | D/V/A角色 | 功能 |
|---------|------|----------|------|
| **长周期** | 周线 | Direction | 定方向（大趋势） |
| **中周期** | 日线 | Velocity | 定入场时机 |
| **小周期** | 4H/小时线 | Acceleration | 精细入场 + 量变检测 |

**入场规则**：
- 日线方向与周线一致 → **MUST_ENTER**（理论上必须入）
- 日线方向中性 → WAIT
- 日线方向与周线反向 → WAIT
- 质变确认 → 提前切换方向，MUST_ENTER

#### 3.7.3 五维阻力计算

| 阻力维度 | 权重 | 计算逻辑 | 多方阻力小意味着 |
|---------|------|---------|---------------|
| **价格阻力** | 30% | 上方压力位距离 vs 下方支撑位距离 | 上方无压力，上涨容易 |
| **量能阻力** | 20% | 上涨/下跌放量程度 + OBV资金流向 | 放量上涨，资金流入 |
| **动量阻力** | 20% | RSI超买超卖 + MACD动能 + 背离 | 未超买，动能充足 |
| **趋势阻力** | 20% | 均线斜率 + Elder-ray多空力量 + 加速度 | 趋势向上，均线多头 |
| **基本面阻力** | 10% | 矿工抛压 + 链上活跃度 + 宏观环境 | 基本面利多 |

**阻力差公式**：

```python
resistance_diff = bear_resistance - bull_resistance
# > 0.10 → BULL（空方阻力大，多方阻力小）
# < -0.10 → BEAR（多方阻力大，空方阻力小）
# 其他 → NEUTRAL
```

#### 3.7.4 三维模型（Direction / Velocity / Acceleration）

| 维度 | 来源 | 计算方法 | 值域 |
|------|------|---------|------|
| **Direction** | 周线五维阻力差 | `sign(resistance_diff)` | BULL / BEAR / NEUTRAL |
| **Velocity** | 日线阻力差变化率 | `tanh((current - hist_mean) / hist_std)` | (-1, 1) |
| **Acceleration** | 小周期阻力差变化率 | `tanh((small - recent_mean) * 5)` | (-1, 1) |

#### 3.7.5 量变积累 → 质变突破

**核心原理**：短周期的量积累会引发中周期的质变，中周期的量积累会引发长周期的质变。

**四阶段检测**：

| 阶段 | 触发条件 | 意义 |
|------|---------|------|
| **ACCUMULATION** | D不变 + A持续反向（≥2周期） | 量变积累中，磨底/筑顶 |
| **BREAKTHROUGH_IMMINENT** | 短周期D改变 + A持续反向 | 质变临近，拐点即将出现 |
| **BREAKTHROUGH_CONFIRMED** | 中周期D改变 | 质变确认，长周期方向即将反转 |
| **NONE** | 无显著积累信号 | 趋势平稳 |

**置信度加成**：
- 量变积累期：+5% ~ +15%（随积累周期递增）
- 质变临近：+15%
- 质变确认：+25%

#### 3.7.6 双向驱动模型

> **大周期决定小周期（强趋势强度阶段）**
> **小周期催生大周期（弱趋势强度 + 趋势延续减弱阶段）**

**趋势强度计算**（0-100分）：

```python
trend_strength = (
    abs(resistance_diff) * 250       # 阻力差贡献（0-50）
    + max(0, velocity_aligned) * 30  # 速度同向贡献（0-30）
    + max(-20, accel_aligned * 20)   # 加速度贡献（-20~20）
)
```

**四种驱动模式**：

| 模式 | 驱动方向 | 触发条件 | 行为 |
|------|---------|---------|------|
| **CONTINUATION** | 大→小 | 强度≥60 + 延续<10期，或强度≥40 + 敏感度<0.5 | 大周期主导，量变信号降权(×0.3)，置信度提升(×1.1) |
| **LATE_CONTINUATION** | 大→小 | 强度≥40 + 敏感度≥0.5 | 大周期仍主导但减弱，量变信号半权(×0.6) |
| **ACCUMULATION** | 小→大 | 强度<40 + 加速度反向 | 小周期主导，量变信号全权重，提前捕捉反转 |
| **WEAKENING** | 小→大 | 强度<40 + 趋势衰竭 | 等待方向选择，置信度降低(×0.8) |

**反转敏感度**：

```python
reversal_sensitivity = (
    max(0, 1 - strength/70) * 0.4   # 强度越低越敏感
    + min(1, duration/15) * 0.3     # 延续越久越敏感
    + max(0, -accel_aligned) * 2 * 0.3  # 加速度反向越强烈越敏感
)
```

#### 3.7.7 置信度合成

```
基础置信度 = 周线置信 × 0.6 + 日线置信 × 0.4
  + 同向加成(+10)    ← 周线日线同向
  × 0.5              ← 周线日线反向
  × 0.7              ← 日线中性
  + 量变质变加成     ← 0~25%（受双向驱动模式调节）
  × 1.1              ← CONTINUATION模式
  × 0.8              ← WEAKENING模式
  = 最终置信度（0-100）
```

#### 3.7.8 核心函数

```python
def compute_least_resistance_3d(
    weekly_df, daily_df, small_df=None,
    fundamental_data=None, weights=None,
    daily_history_diffs=None, history_3d=None,
) -> Dict[str, Any]:
    """
    返回:
    {
        "direction": "BULL"/"BEAR"/"NEUTRAL",
        "confidence": 0-100,
        "velocity": float,
        "acceleration": float,
        "entry_signal": "MUST_ENTER"/"TIMING"/"WAIT",
        "trend_strength": float,        # 趋势强度 0-100
        "trend_duration": int,          # 趋势延续周期数
        "drive_mode": {                 # 双向驱动模式
            "mode": "CONTINUATION"/"LATE_CONTINUATION"/"ACCUMULATION"/"WEAKENING",
            "drive_direction": "LARGE_TO_SMALL"/"SMALL_TO_LARGE",
            "reversal_sensitivity": float,
            "description": str,
        },
        "accumulation": {...},          # 量变质变检测
        "early_inference": {...},       # 早期方向推理
        "weekly": {...}, "daily": {...}, "small": {...},
    }
    """
```

**支撑函数**：

| 函数 | 功能 |
|------|------|
| `calc_trend_strength()` | 计算趋势强度（0-100） |
| `calc_trend_duration()` | 计算趋势延续周期数 |
| `determine_drive_mode()` | 判定双向驱动模式 |
| `detect_accumulation_breakthrough()` | 量变积累→质变突破检测 |
| `compute_least_resistance()` | 单周期五维阻力计算 |

---

## 4. 接口设计

### 4.1 主引擎接口

#### compute_full_trading_signal

```python
def compute_full_trading_signal(
    spot_inst: str = DEFAULT_INST_SPOT,
    is_btc: bool = True,
) -> dict:
    """
    完整三屏交易信号计算（含数据获取）

    参数:
        spot_inst: 现货交易对，如 "BTC-USDT"
        is_btc: 是否为BTC币种（影响风向标数据来源）

    返回: 完整信号结构，含btc_wind_vane、final_signal、value_risk_assessment等
    """
```

#### compute_trend_signal_from_dataframes

```python
def compute_trend_signal_from_dataframes(
    weekly_df,
    daily_df,
    symbol: str = "BTC",
    price: Optional[float] = None,
    fundamental_data: Optional[Dict] = None,
    freqtrade_signals: Optional[Dict] = None,
    is_btc: bool = False,
    btc_daily_df=None,      # BTC日线（波动率基准 + 风向标）
    btc_weekly_df=None,     # BTC周线（风向标MA200检测）
) -> dict:
    """纯计算入口，不依赖外部数据获取"""
```

### 4.2 风向标接口

```python
def evaluate_btc_wind_vane(btc_daily_df=None, btc_weekly_df=None) -> Dict
```

### 4.3 价值风险评估接口

```python
def compute_value_risk_assessment(
    symbol: str,
    direction: str,            # BULL/BEAR
    current_price: float,
    daily_df,
    is_btc: bool = False,
    btc_daily_df=None,
) -> Dict

def evaluate_addon_decision(
    symbol: str,
    direction: str,
    current_price: float,
    entry_price: float,
    is_btc: bool,
    daily_df,
    btc_daily_df=None,
    unrealized_pnl_pct: float = 0.0,
    current_position_pct: float = 0.0,
    max_position_cap: float = None,
) -> Dict
```

### 4.4 五大算法决策接口

```python
def five_algo_decision(
    trend_consistent: bool,
    direction: str,            # BULL/BEAR/NEUTRAL
    confidence: float,         # 0-100
    freqtrade_signals: Optional[Dict] = None,
    freqtrade_consistent: bool = False,
    btc_wind_vane: Optional[Dict] = None,
) -> dict:
    """
    返回: {
        "action": "ENTER_LONG"/"ENTER_SHORT"/"WAIT",
        "confidence": float,
        "position": {"position_pct", "tier"},
        "reason": str,
        "wind_vane_blocked": bool,
    }
    """
```

---

## 5. 配置管理

### 5.1 配置项总览

所有配置定义在 `core/config.py`。

#### 基础配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CANDIDATE_COINS` | ["BTC", "ETH", ...] | 候选币种列表 |
| `SCREEN1_INDICATORS` | [EMA, MACD, ...] | Screen1周线指标 |
| `SCREEN2_INDICATORS` | [RSI, KDJ, ...] | Screen2日线指标 |
| `WEEKLY_WEIGHT` | 0.4 | 周线权重 |
| `DAILY_WEIGHT` | 0.6 | 日线权重 |
| `REVERSAL_THRESHOLD` | 60 | 逆转检测阈值 |
| `OPEN_CONFIDENCE_THRESHOLD` | 60 | 开仓置信度阈值 |
| `TRIAL_CONFIDENCE_THRESHOLD` | 45 | 试探仓阈值 |
| `CONFIDENCE_JUMP_THRESHOLD` | 15 | 置信度跳升阈值 |

#### Phase 3: 逐仓 + 价值风险 + 加仓

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MARGIN_MODE` | "isolated" | 逐仓模式 |
| `MAX_LEVERAGE` | 5.0 | 最大杠杆 |
| `MAX_POSITION_PCT` | 0.50 | 初始最大仓位 |
| `MAX_ADDON_POSITION_PCT` | 0.70 | 加仓后最大仓位 |
| `BTC_DIVERGENCE_ADDON_PCT` | 0.08 | BTC背离加仓亏损阈值 |
| `BASE_TAKE_PROFIT_PCT` | 0.04 | 基准止盈比例（BTC） |
| `BASE_STOP_LOSS_PCT` | 0.10 | 基准止损比例（BTC） |
| `RISK_REWARD_THRESHOLD` | 1.5 | 风险回报比阈值 |
| `TREND_STRENGTH_ADDON_THRESHOLD` | 65.0 | 顺势加仓趋势强度阈值 |
| `MAX_ADDON_COUNT` | 2 | 最大加仓次数 |

#### Phase 3.1: BTC风向标

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `BTC_WIND_VANE_DAILY_MA` | 128 | 日线MA周期 |
| `BTC_WIND_VANE_WEEKLY_MA` | 200 | 周线MA周期 |
| `BTC_WIND_VANE_BREAK_DAYS` | 3 | 连续跌破确认天数 |
| `BTC_WIND_VANE_ENABLED` | True | 风向标总开关 |

### 5.2 配置加载顺序

1. `core/config.py` 默认值
2. 环境变量覆盖（如有）
3. 运行时传入配置

---

## 6. 测试体系

### 6.1 测试文件

| 文件 | 测试内容 | 覆盖范围 |
|------|----------|----------|
| `tests/test_core.py` | 核心算法单元测试 | 指标计算、趋势一致性、信号融合、置信度映射 |

### 6.2 验证场景

BTC风向标闸门验证（合成数据，无外部依赖）：

| 场景 | 验证点 | 结果 |
|------|--------|------|
| 做空闸门打开 | 连续3日<MA128, 周线<MA200 → short_gate=True, BULL被拦截 | ✅ |
| 强制做多 | 周收盘>MA200 → force_long=True, BEAR被拦截 | ✅ |
| 优先级验证 | 同时跌破MA128+站上MA200 → force_long优先 | ✅ |
| 中间状态 | 双向开放，无拦截 | ✅ |
| 端到端集成 | BTC自身风向标注入结果 | ✅ |
| 跨币种过滤 | SOL使用BTC风向标数据正确过滤 | ✅ |

### 6.3 测试命令

```bash
cd 12-三屏趋势系统 && python -m pytest tests/ -v
```

---

## 7. 版本演进

### Phase 1: 核心框架 ✅
- [x] 三层趋势分析引擎（周线/日线/4H）
- [x] 静态指标投票 + 三维动态融合
- [x] 动态优先原则
- [x] 趋势一致性判断
- [x] 动态权重调整
- [x] 基础测试

### Phase 2: 深化与扩展 ✅
- [x] 五大算法模式综合决策
- [x] 贝叶斯置信度 + 经典指标置信度融合
- [x] 技术面+基本面撮合
- [x] Freqtrade入场信号集成（Screen 3）
- [x] 基本面缺失回退到经典指标
- [x] 信号池架构（pool.json + scanner）
- [x] 回测引擎（backtest/）
- [x] ML策略模块（ml/）

### Phase 3: 逐仓 + 价值风险 + 加仓系统 ✅
- [x] 逐仓模式（isolated margin, 5x杠杆）
- [x] 50%初始仓位 / 70%加仓上限
- [x] Elder-ray趋势强度 + 背离检测
- [x] 30日波动率放大（vs BTC基准）
- [x] 风险回报比计算（RR阈值1.5）
- [x] 价值<风险时仓位限制5%
- [x] 逆势背离加仓（BTC 8% + 其他按波动率）
- [x] 顺势趋势强度加仓（强度≥65）
- [x] 最多2次加仓
- [x] 自动止盈止损（波动率放大）

### Phase 3.1: BTC风向标闸门 ✅
- [x] BTC日线MA128连续跌破检测（3日确认）
- [x] BTC周线MA200站上检测
- [x] 三种闸门状态（强制做多/做空闸门开/双向开放）
- [x] 优先级：周线MA200 > 日线MA128 > 中间状态
- [x] 集成到 five_algo_decision 最高优先级
- [x] 非BTC币种使用BTC风向标数据过滤
- [x] 6场景全量验证通过

### Phase 3.2: 币种池优化 + 置信度校准 ✅
- [x] 币种池精简：聚焦高流动性大币种（BTC/ETH/SOL/BNB）
- [x] 扩展币种：HYPE/UNI/ARB/ZEC/DOGE（高流动性标的）
- [x] 剔除低流动性小币种（XRP/ADA/AVAX/LINK/DOT/TRX/MATIC等）
- [x] Platt Scaling 置信度校准（sigmoid函数拟合校准曲线）
- [x] 校准训练方法：`TrendScreenStrategy.train_calibration()`
- [x] 便捷工厂方法：`TrendScreenStrategy.with_calibration()`
- [x] 交叉验证校准：5折CV避免过拟合
- [x] 校准效果：训练集ECE从22.6%降至1.3%（改善94%）
- [x] 参数敏感性分析修复：支持位置参数/关键字参数两种factory调用方式
- [x] BTC回测验证：参数敏感性评分21.0/100（稳健，过拟合风险低）
- [x] BTC回测收益：min_confidence=30时夏普0.59，收益+10.0%

### Phase 3.3: 双路径基本面架构（Path A + Path B）✅
- [x] **Path A（AI驱动）**：通过研报系统获取基本面方向（SKILL调用，未来探索路径）
  - 数据源：A系列研报（周报MD + A1日报JSON）
  - 融合入口：`engine.py` → `fetch_fundamental_data()` → `fusion.py`
  - 回退机制：无研报时用经典指标系统兜底
  - 定位：优先路径，Token费贵时暂不划算，未来SKILL成本下降后启用
- [x] **Path B（算法驱动）**：纯代码 + Tavily API，不依赖AI（核心打磨路径）
  - 数据源：Tavily API 实时搜索（矿工/链上/宏观/跨市场 4维）
  - 采集模块：`data/tavily_data.py`（30分钟缓存，年份过滤，SDK+HTTP双模式）
  - 评分算法：关键词解析 + 阈值评分（Puell/MVRV/SOPR/DXY/10Y等）
  - 融合入口：`core/fundamental_screen1.py` → `calc_fundamental_screen1()`
  - 数据源优先级：Tavily API > 6-TRADING annotation > 纯代码（减半周期）
  - 定位：独特底层算法能力，深度打磨
- [x] Tavily API 集成测试通过（4维数据采集 + 7维分析 + 文本解析）

### Phase 3.4: 综合预测引擎（技术基线 + 基本面三维度调节）✅
- [x] **设计理念**：技术面为基线，基本面为主要调节因子，动态算法优先于静态指标
- [x] **核心公式**：`final_confidence = tech_confidence × (1 + fundamental_adjustment)`
- [x] **三维度模型**（来自9-基本面分析的LeastResistance引擎）：
  - Direction（方向）：基于raw_score判断 up/down/neutral
  - Velocity（速度）：相对于历史的速率变化，tanh归一化
  - Acceleration（加速度）：基于速度变化趋势，tanh归一化
- [x] **四维调节因子**：
  - 方向匹配因子（30%）：技术面与基本面方向一致时增强，冲突时减弱
  - 速度因子（30%）：基本面速度正向时增强，负向时减弱
  - 加速度因子（20%）：基本面加速度正向时增强，负向时减弱
  - 情绪因子（20%）：基于9-基本面分析的SentimentEngine
- [x] **引擎集成**（`core/composite_predictor.py`）：
  - `CompositePredictor.predict()`：综合预测主入口
  - `compute_fundamental_3d()`：计算基本面三维度
  - `analyze_sentiment()`：情绪分析（SentimentEngine）
  - `generate_signals()`：生成交易信号（SignalEngine）
  - `compute_fundamental_adjustment()`：计算基本面调节因子
- [x] **权重配置**：
  - `technical_base`: 0.6（技术面基线权重）
  - `fundamental_adjust`: 0.4（基本面调节权重）
  - `direction_factor`: 0.3（方向匹配因子）
  - `velocity_factor`: 0.3（速度因子）
  - `acceleration_factor`: 0.2（加速度因子）
  - `sentiment_factor`: 0.2（情绪因子）
- [x] **接入9-基本面分析模块**：SignalEngine、SentimentEngine、LeastResistance三维度计算
- [x] **集成到engine.py**：在`compute_trend_signal_from_dataframes()`中调用综合预测引擎，应用调节因子到最终置信度

### Phase 3.5: 最小阻力方向引擎 — 三屏趋势算法内核 ✅
- [x] **核心原理**：市场总是沿着阻力最小方向运动（第一性原理）
- [x] **5大阻力维度**（纯阻力视角，非指标投票）：
  - **价格阻力（30%）**：上方压力位距离 vs 下方支撑位距离
  - **量能阻力（20%）**：上涨/下跌放量程度 + OBV资金流向
  - **动量阻力（20%）**：RSI超买超卖 + MACD动能 + 背离
  - **趋势阻力（20%）**：均线斜率 + Elder-ray多空力量 + 加速度
  - **基本面阻力（10%）**：矿工抛压 + 链上活跃度 + 宏观环境
- [x] **时间三维 × 五维阻力 → 最小阻力三维模型（D/V/A）**：
  - 长周期（周线）→ Direction：定方向
  - 中周期（日线）→ Velocity：定入场时机
  - 小周期（4H/小时）→ Acceleration：精细入场 + 量变检测
- [x] **量变积累 → 质变突破检测**：
  - ACCUMULATION（量变积累）→ BREAKTHROUGH_IMMINENT（质变临近）→ BREAKTHROUGH_CONFIRMED（质变确认）
  - 短周期A持续反向 → 中周期V穿越 → 长周期D改变
  - 置信度加成：+5%~+15%（量变）→ +15%（临近）→ +25%（确认）
- [x] **双向驱动模型**（三屏趋势内核）：
  - **CONTINUATION（大→小）**：强趋势延续，大周期决定小周期
    - 触发：趋势强度≥60 + 延续<10期，或 强度≥40 + 反转敏感度<0.5
    - 行为：量变信号降权(×0.3)，置信度提升(×1.1)
  - **LATE_CONTINUATION（大→小，后期）**：延续后期，开始关注小周期
    - 触发：强度≥40 + 反转敏感度≥0.5
    - 行为：量变信号半权(×0.6)
  - **ACCUMULATION（小→大）**：趋势衰竭+加速度反向，小周期催生大周期
    - 触发：强度<40 + 加速度反向
    - 行为：量变信号全权重，提前捕捉反转
  - **WEAKENING（小→大，减弱）**：趋势衰竭，等待方向选择
    - 触发：强度<40 + 无显著加速度反向
    - 行为：置信度降低(×0.8)
- [x] **纯算法驱动**：静态指标投票已移除，最小阻力引擎为唯一方向来源
- [x] **趋势强度计算**（0-100分）：阻力差(50分) + 速度同向(30分) + 加速度(±20分)
- [x] **反转敏感度**：强度越低、延续越久、加速度越反向 → 敏感度越高
- [x] **核心函数**（`core/least_resistance.py`）：
  - `compute_least_resistance_3d()`：主入口，时间三维×五维阻力→方向+双向驱动
  - `compute_least_resistance()`：单周期五维阻力计算
  - `calc_trend_strength()`：趋势强度计算
  - `calc_trend_duration()`：趋势延续周期统计
  - `determine_drive_mode()`：双向驱动模式判定
  - `detect_accumulation_breakthrough()`：量变积累→质变突破检测
- [x] **回测策略**（`backtest/strategy.py` → `LeastResistanceStrategy`）：
  - 纯最小阻力三维模型驱动，绕过完整推理链
  - 支持双向驱动模式统计、量变质变统计
- [x] **配置项**（`core/config.py`）：
  - `LEAST_RESISTANCE_ENABLED`: True（总开关，纯算法驱动）
  - `LEAST_RESISTANCE_PRICE_LOOKBACK`: 60
  - `LEAST_RESISTANCE_WEIGHTS`: 5维度权重配置

### Phase 4: AI 模型集成

**核心思路**：不是让 AI 替代规则引擎，而是让 AI 优化规则引擎的参数和阈值。
AI 预测未来N日最小阻力方向的概率分布，规则引擎提供交易逻辑骨架，二者融合得到最终决策。

#### Phase 4.1: 特征工程 + LightGBM 基线 ✅

**文件**: [ml/lr_feature_engineer.py](../ml/lr_feature_engineer.py),
        [ml/lr_ml_strategy.py](../ml/lr_ml_strategy.py)

**特征架构（52个特征）**:

```
┌──────────────────────────────────────────────────────────┐
│             最小阻力三维特征工程                          │
├──────────────────────────────────────────────────────────┤
│  1. 五维阻力特征（日线×5 + 周线×5）  = 10 个              │
│     price / volume / momentum / trend / fundamental      │
│     + 阻力差 / 置信度                                     │
├──────────────────────────────────────────────────────────┤
│  2. 三维动态特征（日+周）            = 6 个               │
│     velocity / acceleration / conf_velocity              │
├──────────────────────────────────────────────────────────┤
│  3. 跨周期一致性特征                 = 8 个               │
│     方向一致性 / 方向差 / 置信度比 / 五维阻力差            │
├──────────────────────────────────────────────────────────┤
│  4. 多窗口统计特征（日 5 窗口 + 周 4 窗口）= 28 个        │
│     mean / std / slope @ [1,3,5,10,20]                   │
├──────────────────────────────────────────────────────────┤
│  5. 趋势强度 + 主导维度              = 2 个               │
└──────────────────────────────────────────────────────────┘
```

**模型**: LightGBM 二分类（未来7日上涨/下跌）
- 微软开源，量化领域标配
- 表格数据最强基线
- 训练快、解释性好（特征重要性）

**Walk-Forward 滚动训练**:
- 训练窗口: 365 天（可调）
- 重训练间隔: 30 天（可调）
- 无未来函数，模拟实盘

**AI + 规则引擎融合策略**:

```
规则引擎方向 × AI预测方向 → 决策:
  同向 → 置信度增强 → 仓位放大
  反向 → 置信度削弱 → 仓位减小或空仓
  规则中性 + AI有方向 → 轻仓跟随（打折）
  AI中性 + 规则有方向 → 按规则执行
```

**关键参数**:
- `ml_weight`: AI 在最终决策中的权重（默认 0.4）
- `min_ml_confidence`: AI 最低置信度阈值（默认 0.55）
- `weekly_lr_weight`: 周线规则引擎权重（默认 0.5）

#### Phase 4.2: 基本面特征增强 ✅

**文件**: [ml/fundamental_adapter.py](../ml/fundamental_adapter.py),
        [ml/ai_backtest_comparison.py](../ml/ai_backtest_comparison.py)

**特征总数：94 个**（52 技术面 + 42 基本面）

```
基本面特征架构（42 个）:

┌─────────────────────────────────────────────────────┐
│  数据源 1：6-TRADING screen1（周线六维评分）          │
│  24 个特征                                           │
├─────────────────────────────────────────────────────┤
│  总览层 (3)：                                        │
│    - screen1_total_score (归一化 -1~1)               │
│    - screen1_direction (BULL=1/BEAR=-1/NEUTRAL=0)   │
│    - screen1_confidence (0~1)                        │
│                                                      │
│  六维评分 (6×3=18)：                                  │
│    - s1_{dim}_score   (归一化 -1~1)                  │
│    - s1_{dim}_weight  (0~1)                          │
│    - s1_{dim}_anchor  (方向 1/-1/0)                  │
│    维度: technical/cycle/miner/onchain/macro/        │
│          cross_market                                │
│                                                      │
│  ACH 三假设 (3)：                                     │
│    - s1_ach_h1/h2/h3_prob (0~1)                      │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  数据源 2：9-基本面分析（日频信号+情绪）              │
│  18 个特征                                           │
├─────────────────────────────────────────────────────┤
│  三维阻力 (4)：                                      │
│    - f9_res_direction   (-1~1)                       │
│    - f9_res_velocity    (-1~1)                       │
│    - f9_res_acceleration (-1~1)                      │
│    - f9_res_confidence  (0~1)                        │
│                                                      │
│  模块分数 (10)：                                     │
│    - f9_mod_{mod}  (归一化 -1~1)                     │
│    模块: flow/valuation/onchain/macro/news/          │
│          sentiment/breadth/intermarket/              │
│          narrative/calendar                          │
│                                                      │
│  信号统计 (3)：                                      │
│    - f9_sig_count       (0~1)                        │
│    - f9_sig_strength    (0~1)                        │
│    - f9_sig_net_direction (-1~1)                     │
│                                                      │
│  情绪分数 (1)：                                      │
│    - f9_sentiment      (-1~1)                        │
└─────────────────────────────────────────────────────┘
```

**适配器能力**:
- 支持单点数据（广播到所有时间步）
- 支持历史序列数据（前向填充对齐到日线）
- 自动归一化（-1~1 或 0~1）
- 缺失特征自动填 0

**对比回测结果（模拟数据，400天）**:

| 指标 | 纯规则引擎 | AI增强(技术面) | AI增强(技术+基本面) |
|------|-----------|--------------|-------------------|
| 总收益率 | 0.00% | 3.75% | **10.96%** |
| 夏普比率 | 0.000 | 0.610 | **1.260** |
| 胜率 | 0.00% | 50.00% | **70.00%** |
| 交易次数 | 0 | 9 | 11 |

**特征重要性**:
- 基本面特征在 LightGBM 中显著贡献预测能力
- 技术面特征捕捉短期波动，基本面特征提供中长期方向约束
- 二者融合后夏普比率提升 ~2x

#### Phase 4.3: 模型升级（多任务学习 + 动态融合权重）✅

**核心目标**：从单任务分类升级为多任务学习，引入动态融合权重机制，
根据市场环境自适应调整 AI 与规则引擎的权重比例。

**关键组件**：

##### 1. 多任务学习模型 (MultiTaskLightGBM)

```
┌─────────────────────────────────────────────────────────┐
│                    输入特征向量 (X)                      │
│  技术面特征(52维) + 基本面特征(42维) = 94维              │
└──────────────────────────┬──────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    ┌───────────┐   ┌───────────┐  ┌───────────┐
    │ 方向分类   │   │ 置信度回归 │  │驱动模式分 │
    │ (二分类)  │   │ (回归)    │  │类(多分类) │
    └─────┬─────┘   └─────┬─────┘  └─────┬─────┘
          │                │               │
          │    ┌───────────┴───────────┐   │
          └────▶   综合得分融合层       ◀───┘
               └───────────┬───────────┘
                           ▼
                  ┌─────────────────┐
                  │ final_score     │
                  │ (方向 × 置信度   │
                  │  × 驱动加成)     │
                  └─────────────────┘
```

**三个任务**：
- **方向分类**：预测未来 N 天涨跌方向（二分类）
- **置信度回归**：预测未来收益率大小（回归）→ tanh 归一化为置信度
- **驱动模式分类**：预测当前市场驱动模式（4 分类：CONTINUATION / LATE_CONTINUATION / ACCUMULATION / WEAKENING）

**综合得分公式**：
```
final_score = dir_strength × conf_level × (1 + dm_bonus)

其中：
- dir_strength = (direction_prob - 0.5) × 2   # -1~1
- conf_level = tanh(|return_pred| × scale)    # 0~1
- dm_bonus:
    CONTINUATION:    +0.2  (趋势延续，增强)
    LATE_CONTINUATION: 0.0 (后期，谨慎)
    ACCUMULATION:    -0.1 (积累期，反向关注)
    WEAKENING:       -0.2 (减弱期，降低)
```

**文件**：`ml/multitask_model.py`

##### 2. 动态融合权重引擎 (DynamicWeightFusion)

根据市场环境自适应调整 AI 与规则引擎的权重：

| 市场环境 | 规则权重 | AI 权重 | 说明 |
|---------|---------|---------|------|
| trending (强趋势) | 0.35 | 0.65 | 趋势明确，AI 更有优势 |
| volatile (高波动) | 0.7 | 0.3 | 波动大，规则更稳健 |
| range (震荡) | 0.8 | 0.2 | 震荡市，规则为主 |
| normal (正常) | 0.5 | 0.5 | 均衡 |

**环境因子**（0~1 归一化）：
- `trend_strength`：趋势强度（阻力差 + 速度 + 加速度）
- `volatility`：波动率（20 日收益率标准差）
- `volume_spike`：成交量异动度
- `trend_duration`：趋势延续时间

**动态权重公式**：
```
rule_weight = base_weight
    + volatility × 0.3
    - trend_strength × 0.25
    + (1 - volume_spike) × 0.1
    + trend_duration × 0.1

ai_weight = 1 - rule_weight
```

**融合逻辑**：
1. AI 与规则同向 → 置信度加权融合，增强
2. AI 与规则反向 → 按权重抵消，低置信度中性
3. 一方中性 → 另一方打折生效

**文件**：`ml/multitask_model.py`

##### 3. 特征重要性分析与筛选

- 多任务模型输出 3 个任务的特征重要性
- 平均融合得到全局特征重要性排序
- 支持 Top K 特征自动筛选，降低维度，减少过拟合

```python
# 获取特征重要性
importance = model.feature_importance(task='all')  # 'direction'|'confidence'|'drive_mode'|'all'

# 特征筛选
selected_features = model.select_features(X, top_k=50, task='all')
```

##### 4. 升级 AI 策略 (LeastResistanceAIStrategyV2)

在 v1 基础上集成：
- ✅ 多任务学习模型
- ✅ 动态融合权重引擎
- ✅ 特征自动筛选
- ✅ Walk-Forward 滚动训练（无未来函数）
- ✅ 基本面特征支持

**文件**：`ml/lr_ml_strategy_v2.py`

##### 5. 回测对比结果（500 天模拟数据）

| 策略 | 总收益率 | 夏普比率 | 最大回撤 | 胜率 | 交易次数 |
|-----|---------|---------|---------|------|---------|
| 纯规则引擎 | 0.00% | 0.000 | 0.00% | 0.00% | 0 |
| AI增强(技术面) | -18.94% | -1.560 | 21.43% | 50.00% | 27 |
| AI增强(技术+基本面) | 133.69% | 6.560 | 4.91% | 71.43% | 15 |
| AI v2(多任务+动态权重) | 65.88% | 3.890 | 14.23% | 63.64% | 12 |
| AI v2(全功能+特征筛选) | 65.88% | 3.890 | 14.23% | 63.64% | 12 |

> **说明**：v2 策略在模拟数据上表现低于 v1，主要因为动态权重偏保守（模拟数据趋势强，应降低规则权重）。
> 实盘需根据标的特性调整 `base_rule_weight` 和动态权重参数。

#### Phase 4.4: 实盘验证（纸交易）✅

**核心目标**：通过纸交易（模拟交易）验证不同策略的实盘表现，
对比 AI 策略与规则引擎的绩效差异，为实盘部署提供数据支撑。

**关键组件**：

##### 1. 纸交易引擎 (PaperTradingEngine)

```
┌─────────────────────────────────────────────────────────────┐
│                    纸交易引擎架构                            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ 策略 A      │    │ 策略 B      │    │ 策略 C      │     │
│  │ (AI v1)     │    │ (AI v2)     │    │ (规则引擎)   │     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘     │
│         │                  │                  │            │
│         ▼                  ▼                  ▼            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              多策略组合管理器                         │   │
│  │  - 独立的持仓账户                                    │   │
│  │  - 独立的订单历史                                    │   │
│  │  - 独立的盈亏计算                                    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  核心功能:                                                  │
│  - 模拟市价单成交（滑点可选）                               │
│  - 手续费扣除                                              │
│  - 多空双向持仓管理                                         │
│  - 未实现/已实现盈亏计算                                    │
│  - 交易日志持久化                                          │
└─────────────────────────────────────────────────────────────┘
```

**核心类**：
- `Order`：订单（order_id, strategy_name, inst_id, side, sz, px, fee, timestamp）
- `Position`：持仓（inst_id, side, sz, avg_px, unrealized_pnl, realized_pnl）
- `Portfolio`：策略组合（strategy_name, cash, positions, orders, total_fee）
- `PaperTradingEngine`：纸交易引擎

**文件**：`live/paper_trading.py`

##### 2. 策略运行器 (StrategyRunner)

定时运行策略，获取实时数据，生成信号，执行纸交易：

```
启动 → 获取实时K线 → 运行各策略 → 生成信号 → 执行纸交易 → 保存日志 → 等待
  ↑                                                          │
  └──────────────────────────────────────────────────────────┘
```

**运行模式**：
- **单次运行**（`--once`）：运行一次后退出，适合测试
- **持续运行**（默认）：按间隔循环运行，适合长期验证

**预定义策略**：
- `rule`：纯规则引擎策略（基于最小阻力方向）
- `ai_v1`：AI 增强策略 v1（LightGBM 单任务）
- `ai_v2`：AI 增强策略 v2（多任务 + 动态权重）

**使用示例**：
```bash
# 单次运行 BTC、ETH，对比规则和 AI v1 策略
python live/strategy_runner.py --symbols BTC,ETH --strategies rule,ai_v1 --once

# 持续运行，每 5 分钟执行一次
python live/strategy_runner.py --symbols BTC,ETH --strategies rule,ai_v1,ai_v2 --interval 300
```

**文件**：`live/strategy_runner.py`

##### 3. 验证报告生成器 (ValidationReport)

汇总交易日志，生成策略对比报告：

```
交易日志 (trading_log_*.json)
        │
        ▼
┌─────────────────────┐
│ ValidationReport    │
│ - 加载所有日志       │
│ - 汇总各策略表现     │
│ - 计算统计指标       │
│ - 生成排名对比       │
└─────────────────────┘
        │
        ▼
验证报告 (validation_report_*.json)
```

**报告内容**：
- 验证期间（起止时间）
- 各策略表现：收益率、最大收益、最大亏损、交易次数
- 策略排名对比
- 最优策略推荐

**使用示例**：
```bash
# 打印报告
python live/validation_report.py

# 保存报告
python live/validation_report.py --save
```

**文件**：`live/validation_report.py`

##### 4. 数据流架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据流                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  OKX API                                                        │
│     │                                                           │
│     ▼                                                           │
│  fetch_candles(inst_id, bar, limit)                            │
│     │                                                           │
│     ▼                                                           │
│  ┌─────────────────────────────────────────┐                   │
│  │ 多周期数据                              │                   │
│  │ - 周线 (1W): 趋势方向                   │                   │
│  │ - 日线 (1D): 入场时机                   │                   │
│  │ - 4H: 精细入场                         │                   │
│  └─────────────────────────────────────────┘                   │
│     │                                                           │
│     ▼                                                           │
│  ┌─────────────────────────────────────────┐                   │
│  │ 特征工程                                │                   │
│  │ - LeastResistanceFeatureEngineer        │                   │
│  │ - 52 维技术面特征                       │                   │
│  │ - 42 维基本面特征（可选）               │                   │
│  └─────────────────────────────────────────┘                   │
│     │                                                           │
│     ▼                                                           │
│  ┌─────────────────────────────────────────┐                   │
│  │ 策略推理                                │                   │
│  │ - 规则引擎: compute_least_resistance()  │                   │
│  │ - AI v1: LightGBM 单任务分类            │                   │
│  │ - AI v2: 多任务 + 动态融合              │                   │
│  └─────────────────────────────────────────┘                   │
│     │                                                           │
│     ▼                                                           │
│  信号 (-1 ~ 1)                                                  │
│     │                                                           │
│     ▼                                                           │
│  ┌─────────────────────────────────────────┐                   │
│  │ 纸交易引擎                              │                   │
│  │ - 信号 → 仓位计算                       │                   │
│  │ - 模拟成交（滑点 + 手续费）             │                   │
│  │ - 持仓更新 + 盈亏计算                   │                   │
│  └─────────────────────────────────────────┘                   │
│     │                                                           │
│     ▼                                                           │
│  交易日志 (JSON)                                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

##### 5. 目录结构

```
12-三屏趋势系统/
├── live/
│   ├── __init__.py
│   ├── paper_trading.py       # 纸交易引擎
│   ├── strategy_runner.py     # 策略运行器
│   ├── validation_report.py   # 验证报告生成器
│   └── data/                  # 运行时数据
│       ├── trading_log_*.json # 交易日志
│       └── validation_report_*.json # 验证报告
├── data/
│   └── market_data.py         # OKX 数据获取
├── core/
│   ├── config.py              # 配置（交易对列表）
│   └── least_resistance.py    # 最小阻力计算
└── ml/
    ├── lr_ml_strategy.py      # AI v1 策略
    └── lr_ml_strategy_v2.py   # AI v2 策略
```

##### 6. 使用流程

1. **启动策略运行器**：
   ```bash
   # 单次测试
   python live/strategy_runner.py --once

   # 持续运行（推荐后台运行）
   nohup python live/strategy_runner.py --interval 300 > logs/runner.log 2>&1 &
   ```

2. **查看实时日志**：
   ```bash
   tail -f logs/runner.log
   ```

3. **生成验证报告**：
   ```bash
   python live/validation_report.py --save
   ```

4. **分析策略表现**：
   - 对比各策略收益率
   - 分析交易频率差异
   - 评估风险控制效果

##### 7. 后续迭代方向

- [ ] 接入更多数据源（币安、火币等）
- [ ] 实现更精细的风控模块（止损、止盈、仓位管理）
- [ ] 接入真实交易接口（OKX 交易 API）
- [ ] 实现策略参数自动调优（贝叶斯优化）

### Phase 4.5: V3做空优化基线 ✅

**核心改进**：移除L1做空（价格在日线MA200下方但5日斜率为正时做空），
保留L2做空（斜率明确为负时做空，仓位0.6）。

**回测发现**：L1做空阶段未来收益为正，做空属于逆势操作，是V2的主要亏损来源。

**V3基线指标**（BTC 9年回测）：

| 指标 | V2基线 | V3做空优化 | 改进 |
|-----|--------|-----------|------|
| 总收益率 | 632.47% | 833.72% | +31.8% |
| 夏普比率 | 0.600 | 0.670 | +11.7% |
| 最大回撤 | 77.85% | 76.25% | -2.1% |
| 综合评分 | 1.000 | 1.098 | +9.8% |
| 交易次数 | 92 | 66 | -28.3% |

**文件**：
- [ml/enhanced_ma200_v3_strategy.py](../ml/enhanced_ma200_v3_strategy.py) — V3策略框架
- [ml/short_optimization_test.py](../ml/short_optimization_test.py) — 做空优化测试
- [ml/v2_vs_v3_comparison.py](../ml/v2_vs_v3_comparison.py) — V2 vs V3对比回测

### Phase 5: V4减半周期逃顶基线 ✅

**核心创新**：在V3基础上引入**比特币减半周期时间维度**，实现四阶段仓位管理 +
四重逃顶机制（减半周期 + 越高越卖 + MA128破位 + 反弹卖出）。

**四阶段仓位管理**（基于减半后月数）：

| 阶段 | 减半后时间 | 仓位上限 | 说明 |
|------|-----------|---------|------|
| Normal | 0-12个月 | 100% | 正常牛市，满仓持有 |
| Warn | 12-15个月 | 70% | 预警区，开始减仓 |
| Danger | 15-18个月 | 30% | 高危区，加速减仓 |
| Peak | 18-24个月 | 0% | 见顶区，清仓等待 |
| Normal | 24个月后 | 100% | 恢复正常，MA200策略接管 |

**比特币减半历史时间点**：

| 减半次数 | 日期 | 预测见顶（18月后） | 实际见顶 |
|---------|------|-------------------|---------|
| 第2次 | 2016-07-09 | 2018-01-09 | 2017-12 (~17月) |
| 第3次 | 2020-05-11 | 2021-11-11 | 2021-11 (~18月) |
| 第4次 | 2024-04-20 | 2025-10-20 | 待验证 |

**V4基线指标**（BTC 9年回测）：

| 指标 | V2基线 | V3做空优化 | V4减半逃顶 | V4 vs V2 |
|-----|--------|-----------|-----------|----------|
| 总收益率 | 632.47% | 833.72% | **1440.30%** | +127.8% |
| 夏普比率 | 0.600 | 0.670 | **0.900** | +50.0% |
| 最大回撤 | 77.85% | 76.25% | **53.46%** | -31.3% |
| 卡玛比率 | 0.330 | 0.380 | **0.680** | +106.1% |
| 综合评分 | 1.000 | 1.098 | **1.592** | +59.2% |
| 交易次数 | 92 | 66 | **57** | -38.0% |

**V4新增三大哲学贡献**：

| # | 哲学贡献 | 核心思想 | ML特征数 |
|---|---------|---------|---------|
| 5 | **减半周期时间锚定** | 比特币减半后18个月见顶，时间维度比价格维度更确定 | 3个（新增） |
| 6 | **四阶段仓位递减** | 顶部不是一瞬间，而是区域；分阶段减仓比一次性清仓更优 | 2个（新增） |
| 7 | **越高越卖** | 顶部区域每创新高都是卖出机会，不是买入机会 | 2个（新增） |

**特征总数**：V2原有15个 + V4新增7个 = **22个哲学特征**

**文件**：
- [ml/halving_top_exit_strategy.py](../ml/halving_top_exit_strategy.py) — V4基线策略实现
- [ml/v2_baseline_optimization_principles.md](../ml/v2_baseline_optimization_principles.md) — V4基线优化原则（完整版）
- [ml/four_objective_framework_design.md](../ml/four_objective_framework_design.md) — 四类目的+动态实践闭环设计

---

## 8. 双线策略架构

### 8.1 架构总览

三屏趋势系统维护两条可持续演进的策略线，互不干扰、独立优化、统一对比。
完整管理规则见 [STRATEGY_LINES.md](STRATEGY_LINES.md)。

| 策略线 | 代号 | 定位 | 状态 | 9年回测年化 |
|--------|------|------|------|------------|
| **主策略线** | `MAIN` | V4 + 波浪互斥融合 | ✅ 实盘部署 | **56.43%** |
| **机器学习基线** | `ML_BASELINE` | V5.5 LightGBM | 🔬 实验 | 4.31% |

### 8.2 主策略线 [MAIN]

**核心算法**：V4 减半周期策略 + 波浪互斥融合 + 物理置信度调节

**决策链路**：
```
五大算法（信号源层）
    ↓
V4 减半周期策略（定方向，覆盖三屏决策）
    ↓
波浪策略择时加仓（互斥融合）
    ↓
物理置信度调节（弱趋势仓位微调）
    ↓
最终决策（方向 + 仓位）
```

**互斥融合规则**（9年回测验证，BTC年化 56.43%，夏普 1.4112）：

| V4方向 | 波浪信号 | 融合动作 | 规则名 |
|--------|----------|----------|--------|
| 多头 | 看多 | V4仓位 + 波浪加仓 | v4_long_wave_add |
| 多头 | 中性/看空 | 保持V4仓位 | v4_long_keep |
| 空仓 | 看多 | 波浪轻仓抄底（上限30%） | v4_wait_wave_bottom |
| 空仓 | 中性/看空 | 空仓观望 | v4_wait_wave_wait |
| 空头 | 看空 | 保持V4空头 | v4_short_keep |
| 空头 | 看多 | V4空头减半 | v4_short_wave_reduce |

**主线基线指标**（9年回测，2017-10-10 ~ 2026-07-16）：

| 指标 | 纯V4 | V4+波浪互斥融合 | 买入持有 |
|------|------|-----------------|----------|
| 年化收益 | 53.34% | **56.43%** | 34.80% |
| 夏普比率 | 1.3744 | **1.4112** | 0.8024 |
| 最大回撤 | -44.37% | **-43.31%** | -76.40% |
| Calmar | 1.2022 | **1.3031** | 0.4555 |

### 8.3 机器学习基线 [ML_BASELINE]

**核心算法**：LightGBM + Walk-Forward + 28维哲学特征

**当前状态**：🔬 实验性，严重过拟合
- 9年回测年化仅 4.31%，远低于主线 56.43%
- 需重新设计特征工程解决长期过拟合问题

**优化方向**：
1. 重新设计特征工程（减少维度，增加稳定性）
2. 探索更长的训练窗口（>730天）
3. 改进标签生成策略
4. 探索时序模型（LSTM/Transformer）

**副线工作区**：[ml/v55_baseline/](../ml/v55_baseline/)

### 8.4 代码隔离纪律

**文件归属标签**：
- `[MAIN]` — 主线代码（V4+波浪+物理）
- `[ML_BASELINE]` — 副线代码（V5.5 ML 探索）
- `[SHARED]` — 共享基础设施（被两条线共同依赖）

**主线代码 [MAIN] 禁止**：
- ❌ 引入 LightGBM/XGBoost 等 ML 模型依赖
- ❌ 引入 `philosophy_feature_engineer.py` 等 V5.5 特征工程
- ❌ 在 `engine.py` 主路径中调用 V5.5 ML 推理

**副线代码 [ML_BASELINE] 禁止**：
- ❌ 修改 `engine.py` 的主决策路径
- ❌ 修改 `halving_top_exit_strategy.py` V4 主策略
- ❌ 修改 `ewave_strategy_adapter.py` 波浪互斥融合规则
- ❌ 直接接入实盘交易系统

### 8.5 晋升与回退机制

**副线晋升为主线**（需同时满足）：
1. 9年回测年化 ≥ 56.43%（主线基线）
2. 夏普 ≥ 1.41
3. 最大回撤 ≤ -43.31%
4. Walk-Forward 样本外 AUC ≥ 0.60
5. 多币种验证（BTC + ETH + SOL）均优于主线

**主线回退**（任一触发）：
1. 实盘连续 3 个月跑输纯 V4 基线
2. 最大回撤超过 V4 基线的 120%（即 > 53.24%）
3. 减半周期预测失败（2025年10月后 BTC 未见顶）

---

## 9. V4基线策略与优化原则

### 9.1 基线策略定位

**V4减半周期逃顶策略（HalvingTopExitStrategy v4）** 是三屏趋势系统中通过
**技术分析 + 比特币减半周期时间维度**达成的最佳版本，具有最高优先级。
所有后续的ML特征工程优化和算法推理优化都必须在V4基线上进行，
且优化版本的综合评分必须优于V4基线（score > 1.0），否则**必须回退**到V4版本。

```
┌───────────────────────────────────────────────────────┐
│  三屏趋势策略迭代铁律：                                  │
│                                                         │
│  新策略综合评分 > 1.0（相对V4）→ 采纳，更新基线          │
│  新策略综合评分 ≤ 1.0（相对V4）→ 回退到V4，保留探索记录  │
│                                                         │
│  任何优化不得以"理论上更优"为理由绕过基线对比验证。       │
│  V4的综合评分1.592是新锚点（V2=1.000为原始锚点）。       │
└───────────────────────────────────────────────────────┘
```

### 9.2 基线策略核心规则

**文件**: [ml/halving_top_exit_strategy.py](../ml/halving_top_exit_strategy.py) → `HalvingTopExitStrategy`
**基础**: V3做空优化（EnhancedMA200Strategy v3）+ 减半周期逃顶

#### 9.2.1 多头规则（BTC：左侧抄底 + 减半逃顶）

**抄底阶段**（沿用V2/V3）：

| 层级 | 触发条件 | 仓位 | 说明 |
|------|---------|------|------|
| 第1层 | 价格跌破周线MA200（>0%） | 20% | 轻仓试探 |
| 第2层 | 跌破MA200达5% | 40% | 下跌确认 |
| 第3层 | 跌破MA200达10% | 60% | 继续加仓 |
| 第4层 | 跌破MA200达15% | 80% | 极端恐慌区满仓抄底 |

**减半周期逃顶阶段**（V4新增）：

| 阶段 | 减半后时间 | 仓位上限 | 说明 |
|------|-----------|---------|------|
| Normal | 0-12个月 | 100% | 正常牛市，满仓持有 |
| Warn | 12-15个月 | 70% | 预警区，开始减仓 |
| Danger | 15-18个月 | 30% | 高危区，加速减仓 |
| Peak | 18-24个月 | 0% | 见顶区，清仓等待 |
| Normal | 24个月后 | 100% | 恢复正常，MA200策略接管 |

#### 9.2.2 四重逃顶机制（V4核心创新）

```
┌─────────────────────────────────────────────────────────┐
│                  V4 四重逃顶机制                          │
│                                                           │
│  1️⃣ 减半周期时间锚定（核心）                              │
│     减半后12-18个月进入顶部区域，强制减仓                  │
│     仓位：100% → 70% → 30% → 0%                         │
│                       │                                   │
│  2️⃣ 越高越卖                                            │
│     价格每创新高5%卖出一档（15%仓位），最高卖出80%        │
│                       │                                   │
│  3️⃣ MA128破位卖出                                       │
│     跌破MA128后每跌5%卖出一档（4档清仓）                  │
│                       │                                   │
│  4️⃣ 反弹卖出                                            │
│     每次反弹3%卖出25%剩余仓位，最高累计卖出80%            │
└─────────────────────────────────────────────────────────┘
```

#### 9.2.3 空头规则（V3优化版，仅BTC）

| 条件组合 | 初始仓位 | 说明 |
|---------|---------|------|
| 跌破MA200 + 5日斜率为负 | 60% | 确认下跌趋势才做空 |
| 跌破MA200 + 5日斜率非负 | 0% | **V3改进：不做空**（V2是30%） |

**关键改进**：V2在"价格跌破MA200但斜率为正"阶段做空（L1=30%），回测发现此阶段未来收益为正，
做空是逆势操作。V3/V4移除L1做空，只在斜率明确为负时做空。

**斐波那契止盈**（沿用V2）：

| 止盈位 | 盈利比例 | 剩余仓位 |
|-------|---------|---------|
| 第1止盈 | 23.6% | 75% |
| 第2止盈 | 38.2% | 50% |
| 第3止盈 | 50.0% | 25% |
| 第4止盈 | 61.8% | 0%（清仓） |

#### 9.2.4 小币多头（双牛过滤，沿用V2）

```
小币做多条件 = BTC处于牛市 AND 小币自身处于牛市
```

#### 9.2.5 小币熊市规则（沿用V2）

- **禁止做多**：BTC处于熊市时，小币不开多仓
- **禁止做空**：小币永不做空（反弹剧烈、趋势不可控、流动性差）
- **完全空仓**：熊市中小币保持空仓观望

### 9.3 基线策略回测基准

**回测区间**: 2017-10-10 至 2026-07-16（9年+）
**数据来源**: 本地BTC日线数据（3202天）
**基准对比**: V2基线（综合评分=1.000）

**BTC回测指标对比**:

| 策略 | 总收益率 | 夏普比率 | 最大回撤 | 卡玛比率 | 交易次数 | 综合评分 |
|-----|---------|---------|---------|---------|---------|---------|
| V2基线 | 632.47% | 0.600 | 77.85% | 0.330 | 92 | 1.000 |
| V3做空优化 | 833.72% | 0.670 | 76.25% | 0.380 | 66 | 1.098 |
| **V4减半逃顶** | **1440.30%** | **0.900** | **53.46%** | **0.680** | **57** | **1.592** |

**关键结论**：
- V4相对V2：总收益+127.8%，夏普+50%，回撤-31.3%
- V4相对V3：总收益+72.7%，夏普+34.3%，回撤-29.9%
- V4交易次数最少（57次），不过度交易
- V4最大回撤控制最优（53.46%），风险大幅降低

**V4参数敏感性验证**:

| 配置 | 总收益 | 夏普 | 回撤 | 评分 |
|------|--------|------|------|------|
| V4默认（12-15-18月，70%-30%-0%） | 1440.3% | 0.900 | 53.5% | 1.592 |
| V4保守（10-13-16月，80%-50%-20%） | 1249.1% | 0.860 | 54.0% | 1.512 |
| V4激进（14-17-20月，60%-20%-0%） | 1086.1% | 0.790 | 61.5% | 1.339 |
| V4只用减半时间（无MA128/反弹） | 1293.3% | 0.860 | 54.1% | 1.535 |

**结论**：减半周期时间窗口是核心收益来源，MA128和反弹卖出是锦上添花。

### 9.4 七大哲学贡献与ML特征映射

V4策略的成功不仅在于参数，更在于其背后的**交易哲学**。V2贡献4项 + V4新增3项 = 7项哲学贡献，
被转化为ML特征工程的重要输入。

#### 9.4.1 V2原有哲学贡献（4项，15个特征）

| # | 哲学贡献 | 核心思想 | ML特征数 |
|---|---------|---------|---------|
| 1 | **分化对待BTC和小币** | BTC可做空，小币禁止做空 | 4个 |
| 2 | **左侧抄底 > 右侧做空** | 周线MA200抄底收益远大于做空 | 4个 |
| 3 | **分层仓位管理** | 试探仓→确认仓→止盈减仓 | 4个 |
| 4 | **双牛过滤** | 小币需BTC+自身双牛才做多 | 3个 |

#### 9.4.2 V4新增哲学贡献（3项，7个特征）

| # | 哲学贡献 | 核心思想 | 回测验证 | ML特征数 |
|---|---------|---------|---------|---------|
| 5 | **减半周期时间锚定** | 比特币减半后18个月见顶，时间维度比价格维度更确定 | ✅ 验证通过 | 3个 |
| 6 | **四阶段仓位递减** | 顶部不是一瞬间，而是区域；分阶段减仓比一次性清仓更优 | ✅ 验证通过 | 2个 |
| 7 | **越高越卖** | 顶部区域每创新高都是卖出机会，不是买入机会 | ✅ 验证通过 | 2个 |

#### 9.4.3 V4新增特征清单

| 特征名 | 类型 | 说明 |
|--------|------|------|
| `halving_months_after` | 时间 | 距上次减半的月数 |
| `halving_phase` | 分类 | 当前减半阶段（normal/warn/danger/peak） |
| `halving_position_cap` | 数值 | 减半周期仓位上限（0.0-1.0） |
| `ma128_distance_pct` | 价格 | 价格距MA128的百分比 |
| `ma128_below_days` | 时间 | 价格连续低于MA128的天数 |
| `ath_drawdown_pct` | 价格 | 距历史高点的回撤百分比 |
| `bounce_from_low_pct` | 价格 | 从近期低点的反弹幅度 |

**特征总数**：V2原有15个 + V4新增7个 = **22个哲学特征**，全部带有 `practice_validated` 元数据标记。

**特征消费分类**（LightGBM）:
- **价格特征管线**：MA200/MA128位置、距离、斜率等 → 输入层
- **时间特征管线**：减半周期、阶段、仓位上限 → 决策层（V4新增）
- **阻力特征管线**：支撑/压力位、斐波那契档位等 → 中间层
- **集成推理管线**：双牛过滤、分层管理、减半逃顶等哲学特征 → 决策层

详细分类见 [ml/LIGHTGBM_FEATURE_CATALOG.md](../ml/LIGHTGBM_FEATURE_CATALOG.md)。

### 9.5 优化迭代原则

#### 9.5.1 优化方向优先级（V4更新）

```
P0（最高优先级）: 基于V4减半周期的ML特征工程优化
    └─ 减半周期特征 → LightGBM验证
    └─ MA128破位特征 → 逃顶时机优化
    └─ 目标：让ML学习V4的时间维度决策

P1: 四类目的框架深化
    ├─ DIP_BUY：抄底时机优化（布林带+头肩底）
    ├─ TOP_EXIT：逃顶时机优化（减半周期+波浪理论）
    ├─ BEAR_SHORT：做空优化（V3已优化，待ML验证）
    └─ BEAR_EXIT：空平时机优化（底背离+量能萎缩）

P2: 算法推理优化
    ├─ 多任务学习架构调优
    ├─ 动态融合权重机制调优
    └─ Walk-Forward参数调优

P3: 新数据源接入
    ├─ 链上数据增强（减半周期相关）
    ├─ 情绪数据增强（顶部区域恐慌/贪婪）
    └─ 基本面数据增强
```

#### 9.5.2 评估指标体系

任何新策略版本必须通过**多维度综合评估**，全部优于V4基线方可采纳。

| 指标 | 权重 | 说明 | 优于基线的判定 |
|-----|------|------|--------------|
| **夏普比率** | 40% | 风险调整收益（最核心指标） | 新夏普 > V4夏普(0.900) |
| **卡玛比率** | 30% | 收益/最大回撤 | 新卡玛 > V4卡玛(0.680) |
| **最大回撤** | 15% | 绝对风险控制 | 新回撤 < V4回撤(53.46%) |
| **胜率** | 10% | 交易质量 | 新胜率 > V4胜率(51.79%) |
| **交易频率** | 5% | 合理性（不过度交易） | 在合理区间内 |

#### 9.5.3 综合评分公式

```
score = 0.4 × (sharpe / V4_sharpe)
      + 0.3 × (calmar / V4_calmar)
      + 0.15 × (V4_maxdd / maxdd)
      + 0.1 × (win_rate / V4_winrate)
      + 0.05 × f_trade_freq(trade_count)

其中 V4 基线值：
  V4_sharpe = 0.900
  V4_calmar = 0.680
  V4_maxdd = 0.5346
  V4_winrate = 0.5179
  V4_trades = 57

判定规则：
  score > 1.0 → 采纳（优于V4基线）
  score ≤ 1.0 → 回退（不优于V4基线）
```

#### 9.5.4 回测验证规范

1. **统一数据**：所有策略使用同一数据集回测（BTC_1D_730d.json）
2. **统一区间**：2017-10-10 至 2026-07-16（9年+完整周期）
3. **样本内外**：
   - 样本内训练/验证：2017-10-10 至 2023-12-31
   - 样本外验证：2024-01-01 至 2026-07-16
4. **多币种验证**：至少在BTC和ETH上均优于V4基线
5. **滚动验证**：Walk-Forward验证，避免过拟合
6. **减半周期覆盖**：至少2个减半周期（2020年+2024年减半）

#### 9.5.5 版本管理与回退机制

```
版本命名规则：
    v2              原始基线（牛熊经验法则）
      ↓
    v3              做空优化（L1=0, L2=0.6）
      ↓
    v4              减半周期逃顶（当前基线）
      ↓
    v4.1, v4.2 ...  小版本迭代（参数/特征微调）
      ↓
    v5              大版本架构升级（需充分验证）

回退触发条件：
    1. 综合评分 ≤ 1.0（相对V4）
    2. 样本外表现显著劣于样本内（过拟合）
    3. 最大回撤超过V4的120%（即>64.15%）
    4. 实盘/纸交易连续3个月跑输V4
    5. 核心逻辑变更导致可解释性丧失
    6. 减半周期预测失败（2025年10月后BTC未见顶）

回退操作：
    1. 标记该版本为"探索失败"，保留记录用于分析
    2. 策略配置回退到V4基线版本（HalvingTopExitStrategy 默认参数）
    3. 分析失败原因（特征？模型？参数？减半周期失效？），形成经验教训
```

### 9.6 相关文件索引

| 文件 | 说明 |
|-----|------|
| [`ml/halving_top_exit_strategy.py`](../ml/halving_top_exit_strategy.py) | V4基线策略实现（HalvingTopExitStrategy） |
| [`backtest/strategy.py`](../backtest/strategy.py) | V2/V3策略实现（EnhancedMA200Strategy） |
| [`ml/enhanced_ma200_v3_strategy.py`](../ml/enhanced_ma200_v3_strategy.py) | V3策略框架（抄底+逃顶） |
| [`ml/short_optimization_test.py`](../ml/short_optimization_test.py) | V3做空优化测试脚本 |
| [`ml/v2_vs_v3_comparison.py`](../ml/v2_vs_v3_comparison.py) | V2 vs V3对比回测 |
| [`ml/philosophy_feature_engineer.py`](../ml/philosophy_feature_engineer.py) | 哲学贡献 → ML特征工程（22个特征） |
| [`ml/LIGHTGBM_FEATURE_CATALOG.md`](../ml/LIGHTGBM_FEATURE_CATALOG.md) | LightGBM特征消费分类目录 |
| [`ml/v2_baseline_optimization_principles.md`](../ml/v2_baseline_optimization_principles.md) | V4基线优化原则（独立完整文档） |
| [`ml/four_objective_framework_design.md`](../ml/four_objective_framework_design.md) | 四类目的+动态实践闭环设计 |
| [`docs/TECHNICAL_DESIGN.md`](../docs/TECHNICAL_DESIGN.md) | 本文档 · 技术设计 |
| [`ENGINEERING_INDEX.md`](../ENGINEERING_INDEX.md) | 工程索引（完整版） |

---

## 10. PITD物理数学趋势推理算法

> **定位**: 系统的底层推理算法框架，将五条核心趋势理论转化为基于物理学定律的数学模型
> **目标**: 从经验驱动（V2-V5特征工程）走向理论驱动（物理-数学算法）
> **详细设计**: [docs/PITD_PHYSICS_ALGORITHM_DESIGN.md](PITD_PHYSICS_ALGORITHM_DESIGN.md)
> **当前阶段**: Phase 1 运动学层实现中

### 10.1 五条核心理论 → 物理学映射

| # | 核心理论 | 物理学对应 | 数学工具 |
|---|---------|-----------|---------|
| 1 | 趋势强时大周期驱动小周期（趋势惯性） | 牛顿第一定律 + 动量传递 | 动量 P=mv，动量守恒 |
| 2 | 趋势减弱，小周期累积，量变到质变 | 能量累积 + 相变（临界突变） | 势能 E=½kx²，相变判据 |
| 3 | 阈值临界通过方向/速度/加速度计算 | 运动学（位移/速度/加速度） | 微积分 dⁿs/dtⁿ |
| 4 | 市场沿阻力最小方向运动 | 最小作用量原理 + 势能场 | 变分法 δS=0，梯度场 |
| 5 | 利用力学定律构建精密算法 | 牛顿第二定律 F=ma + 能量守恒 | 微分方程，积分变换 |

### 10.2 五层算法架构

```
┌─────────────────────────────────────────────────────────────┐
│              PITD 物理数学趋势推理引擎                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Layer 1: 运动学层 (Kinematics) — 基础观测量                 │
│    v(t)=ds/dt, a(t)=dv/dt, j(t)=da/dt                      │
│    多周期嵌套：周线(W) + 日线(D)                             │
│                                                             │
│  Layer 2: 动力学层 (Dynamics) — 力与能量                     │
│    m(t)=StableCoin_MCap标准化, F=ma, P=mv, E_k=½mv²         │
│    动量传递效率 η = corr(v_W, v_D) × |v_W|/(|v_W|+|v_D|)    │
│                                                             │
│  Layer 3: 势能场层 (Potential Field) — 阻力最小原理          │
│    V(s) = Σ w_i × φ(s - s_i)                                │
│    关键价位：均线密集区 + 成交密集区 + 前高前低 + 斐波那契     │
│    阻力最小方向 = -∇V(s)                                     │
│                                                             │
│  Layer 4: 相变层 (Phase Transition) — 量变到质变             │
│    E_pot(t) = ∫|a_small|dt, 临界判据 E_pot ≥ E_critical     │
│    PhaseTransition_Score = 多指标融合                        │
│                                                             │
│  Layer 5: 最小作用量统一框架 (Least Action)                  │
│    S = ∫L dt, L = E_k - V_total, δS = 0                    │
│    轨迹预测 + 方向预测 + 临界点预测                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 10.3 关键物理量定义（修正后方案）

| 物理量 | 符号 | 数学定义 | 物理含义 |
|--------|------|---------|---------|
| 位移 | s(t) | ln(P(t)/P(t₀)) | 对数收益（无量纲） |
| 速度 | v(t) | ds/dt | 价格变化速率 |
| 加速度 | a(t) | dv/dt = d²s/dt² | 趋势加强/减弱 |
| 加加速度 | j(t) | da/dt = d³s/dt³ | 突变预警（jerk） |
| 质量 | m(t) | StableCoin_MCap / MCap_MA | 市场流动性环境（外生变量） |
| 动量 | P(t) | m(t) × v(t) | 价格动量 |
| 动能 | E_k(t) | ½ × m(t) × v(t)² | 趋势动能 |
| 合力 | F(t) | m(t) × a(t) - μ×m(t)×σ(t) | 驱动力 - 摩擦力 |
| 波动幅度 | σ(t) | ATR(t)/P(t) | "温度"（摩擦力来源） |
| 势能场 | V(s) | Σ w_i × φ(s-s_i) | 阻力支撑场 |
| 势能梯度 | -∇V | -dV/ds | 阻力最小方向 |
| 累积势能 | E_pot | ∫\|a_small\|dt | 小周期能量累积 |
| 作用量 | S | ∫L dt, L=E_k-V | 路径优化目标 |

### 10.4 实现路线图

| Phase | 内容 | 状态 | 物理验证 | ML集成 |
|-------|------|------|---------|--------|
| Phase 1 | 运动学层（v/a/j 双周期） | ✅ 完成 | ✅ 物理意义合理 | ❌ 回退 |
| Phase 2 | 动力学层（F/P/E_k/η） | ✅ 完成 | ✅ **理论1完美验证** | ❌ 回退 |
| Phase 3 | 势能场层（V/∇V 4类价位） | ✅ 完成 | 🟡 理论4接近验证 | ❌ 回退 |
| Phase 3.5 | 物理-哲学交互特征 | ✅ 完成 | — | ❌ 回退 |
| Phase 4 | 相变层（E_pot/临界判据） | ⏳ 待评估 | — | — |
| Phase 5 | 最小作用量统一框架 | ⏳ 待评估 | — | — |

**关键结论**：物理模型验证成功（特别是理论1 η 2.86x单调递增），但V5.5基线（80维）已触及LightGBM信息容量上限，物理特征直接作为ML输入均导致过拟合加剧。详见 [PITD_PHYSICS_ALGORITHM_DESIGN.md](PITD_PHYSICS_ALGORITHM_DESIGN.md) 第6章。

### 10.5 验证原则

每个Phase必须通过Walk-Forward验证（730天训练+180天测试+180天步长，12折）：
- **TOP_EXIT场景**: 未来20日跌幅>20%
- **DIP_BUY场景**: 未来20日涨幅>15%
- **采纳标准**: 双场景AUC均提升，且过拟合不增加
- **回退标准**: 任一场景AUC下降超过0.005

---

**文档维护**: 每次基线变更或优化原则更新时，同步更新本文档。
**最后更新**: 2026-07-19
**当前基线**: V5.5（28维哲学特征，TOP_EXIT 0.7433, DIP_BUY 0.6935）
