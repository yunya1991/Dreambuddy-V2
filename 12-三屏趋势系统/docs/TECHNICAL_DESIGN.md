# 技术设计文档 — 三屏趋势系统

> **版本**: v1.3.1 | **更新日期**: 2026-07-15
> **定位**: 模块级技术设计文档，描述架构、数据流、算法细节
> **阶段**: Phase 3.1 完成 — BTC风向标闸门 + 逐仓价值风险评估 + 加仓系统

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
│   ├── dynamic_weights.py   # 动态权重调整
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

### Phase 4: 未来计划
- [ ] 接入通用风控模块（13）
- [ ] 易经推理系统对接
- [ ] 增强回测覆盖（多币种、多周期）
- [ ] ML策略实盘验证
- [ ] 监控告警系统
- [ ] 实盘校准参数自动更新（每周重训练）
