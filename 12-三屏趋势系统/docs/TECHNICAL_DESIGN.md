# 技术设计文档 — 三屏趋势系统

> **版本**: v2.2 | **更新日期**: 2026-07-17
> **定位**: 模块级技术设计文档，描述架构、数据流、算法细节
> **阶段**: Phase 4.2 完成 — 基本面特征增强（screen1六维 + 9-基本面信号 + 对比回测）

---

## 目录

- [1. 系统架构](#1-系统架构)
- [2. 数据流与决策链路](#2-数据流与决策链路)
- [3. 核心算法](#3-核心算法)
- [4. 接口设计](#4-接口设计)
- [5. 配置管理](#5-配置管理)
- [6. 测试体系](#6-测试体系)
- [7. 版本演进](#7-版本演进)

---

## 1. 系统架构

### 1.1 模块定位

| 属性 | 说明 |
|------|------|
| 模块名称 | 12-三屏趋势系统 |
| 英文代号 | screen-trend |
| 核心职责 | 周线+日线+BTC风向标三重滤网趋势分析，含置信度评估、价值风险评估、仓位计算、加仓决策 |
| 设计模式 | 策略模式 + 责任链模式 + 观察者模式 |
| 决策优先级链 | BTC风向标闸门 → 趋势一致性 → 置信度评估 → Freqtrade入场信号 → 价值风险仓位调整 |

### 1.2 六层架构

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
├── ml/                      # 机器学习策略
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
- [ ] 构建策略评估看板（实时可视化）
