# 三屏趋势交易系统技术文档

> 版本: v2.0 (独立模块重构版)
> 模块路径: `12-三屏趋势系统/`
> 主入口: [`compute_full_trading_signal()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L389-L448) / [`compute_trend_signal_from_dataframes()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L298-L386)

---

## 1. 系统定位与边界

### 1.1 核心理念

**趋势一致性确定方向，置信度评估确定仓位。**

三屏趋势系统是一个**趋势判定 + 置信度评估 + 仓位计算**系统。通过技术指标和基本面两个维度，分别在周线和日线上判定趋势方向与置信度，最终撮合形成统一的趋势方向和置信度，以此驱动交易决策。

### 1.2 系统边界

| 职责 | 归属 | 说明 |
|------|------|------|
| 趋势方向判定 | **12-三屏趋势系统** | 周线+日线趋势一致性 |
| 置信度评估 | **12-三屏趋势系统** | 贝叶斯置信度 + 基本面撮合 |
| 仓位计算 | **12-三屏趋势系统** | 置信度→仓位映射 (5%~60%) |
| 入场信号精选 | **10-经典指标系统** | Freqtrade 多策略投票 |
| 离场决策 | **10-经典指标系统** | ClassicExitSystem 四层优先级 |
| 基本面数据 | **A系列研报** | 周报(MD) + A1日报(JSON) |

### 1.3 与旧三屏马丁系统的区别

| 维度 | 旧三屏马丁 (ab-trading) | 新三屏趋势 (本模块) |
|------|------------------------|-------------------|
| 核心逻辑 | 六维评分 + V9马丁网格 | 五大算法 + 趋势捕捉 |
| 加仓策略 | 最多3次(4层)马丁摊平 | 不含马丁加仓逻辑 |
| 止损方式 | 动态均线止损(MA200/EMA200) | 委托经典系统离场 |
| 入场信号 | 六维加权评分 | 贝叶斯置信度 + Freqtrade投票 |
| 仓位计算 | 固定首仓比例 | 置信度动态映射(5%~60%) |
| 基本面 | 无 | 技术面60% + 基本面40%撮合 |

---

## 2. 系统三层结构

| 层级 | 名称 | 周期 | 核心职责 |
|------|------|------|---------|
| 第一屏 | 战略层 | 周线 | 趋势方向判定（周线权重60%，准确度更高） |
| 第二屏 | 战术层 | 日线 | 趋势一致性检测 + 置信度计算 |
| 第三屏 | 执行层 | 4h/1h | 入场信号(经典系统) + 离场决策(经典系统) |

---

## 3. 模块工程结构

```
12-三屏趋势系统/
├── engine.py                   # 主引擎（算法编排 + 公开接口）
├── signals.py                  # Freqtrade信号服务（调用经典系统）
├── exit_integration.py         # 离场集成（调用经典系统ClassicExitSystem）
├── classic_bridge.py           # 经典系统HTTP桥接
├── core/                       # 核心算法层
│   ├── config.py               # 配置常量（指标组、权重、仓位档位）
│   ├── indicators.py           # 指标计算（三维动态 + 静态方向）
│   ├── trend_consistency.py    # 趋势一致性检测（静态+动态融合）
│   ├── dynamic_weights.py      # 动态权重 + 贝叶斯置信度
│   └── fusion.py               # 技术面+基本面撮合
├── data/                       # 数据获取层
│   ├── market_data.py          # K线数据获取（OKX API）
│   └── fundamental_data.py     # 基本面数据获取（A系列研报）
├── tests/
│   └── test_core.py            # 核心测试
└── docs/
    └── trend-screen-system-design.md  # 本文档
```

---

## 4. 五大算法

### 4.1 算法总览

| # | 算法 | 角色 | 代码位置 |
|---|------|------|---------|
| 1 | 静态指标投票 | 趋势方向**基础判定** | [`calc_trend_direction_static()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py#L189-L198) |
| 2 | 三维动态融合 | 趋势方向**核心创新**（动态优先） | [`calc_trend_direction_dynamic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py#L42-L122) |
| 3 | 动态权重调整 | 指标权重**回测排名** | [`calc_dynamic_weights()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py#L78-L138) |
| 4 | 贝叶斯参数寻优 | 置信度**参数寻优** | [`calc_bayesian_confidence()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py#L140-L200) |
| 5 | 技术面+基本面撮合 | 最终方向与置信度**融合** | [`fuse_technical_fundamental()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fusion.py#L33-L95) |

### 4.2 静态指标投票

对周线/日线各自的5个指标进行投票，多数决定方向（BULL/BEAR/NEUTRAL）。

**周线指标组**（权重更高）:

| 指标 | 类型 |
|------|------|
| RSI_50 | 动量 |
| SuperTrend | 趋势 |
| StochRSI_Cross | 动量 |
| OBV_Trend | 量能 |
| Keltner_Channel | 波动率 |

**日线指标组**:

| 指标 | 类型 |
|------|------|
| GoldenCross_50_200 | 趋势 |
| MACD_Cross | 动量 |
| Vortex | 趋势 |
| TEMA | 趋势 |
| EMA_Align_20_50_200 | 趋势 |

配置位置: [`SCREEN1_INDICATORS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L17-L19) / [`SCREEN2_INDICATORS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L21-L23)

### 4.3 三维动态融合（核心创新）

每个指标计算三个维度:

| 维度 | 范围 | 含义 |
|------|------|------|
| direction | BULL/BEAR | 当前趋势方向 |
| speed | 0-100 | 方向变化快慢（动量强度） |
| acceleration | 0-100 | 速度变化快慢（加速/减速） |

**逆转检测**: `speed < 30 且 acceleration > 20` → 潜在逆转信号

**动态优先原则**（核心创新）:

```
逆转信号 > 60% → 以动态方向为准（覆盖静态）
动态方向 = NEUTRAL → 以静态方向为准（回退）
其他情况 → 以动态方向为准
```

可能出现"静态牛市但动态熊市 → 最终判定熊市"的情况，捕捉趋势逆转的早期信号。

配置: [`REVERSAL_THRESHOLD`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L28) / [`REVERSAL_SPEED_LOW`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L29) / [`REVERSAL_ACCEL_HIGH`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L30)

### 4.4 动态权重调整

- **定期回测**: 指标与日线MA200买入持有基线对比
- **优于基线**才能保留在指标组中
- **权重排名**: 根据超额收益、夏普比率、胜率综合排名
- **周线权重 60%，日线权重 40**（周线准确度更高）

配置: [`WEEKLY_WEIGHT`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L25) / [`DAILY_WEIGHT`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L26)

### 4.5 贝叶斯参数寻优

```
P(趋势|信号) ∝ Σ[权重 × (0.5 + speed/200 + acceleration/200)]
```

- **似然概率** = 动态权重 × 动态因子
- **先验** 隐含在历史权重排名中
- **周线 60%，日线 40**

### 4.6 技术面+基本面撮合

| 场景 | 融合规则 | 置信度计算 |
|------|---------|-----------|
| 方向一致 | 以技术面为主 | 加权平均（技术60% + 基本面40%） |
| 基本面中性 | 以技术面为主 | 直接用技术面置信度 |
| 方向矛盾 | 以技术面为主 | 取较低值，按矛盾程度最大扣减30% |

> **核心原则**: 趋势方向以技术面为主，基本面影响置信度调整。

配置: [`TECHNICAL_WEIGHT`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L32) / [`FUNDAMENTAL_WEIGHT`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L33) / [`MAX_CONFLICT_DEDUCTION`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L34)

---

## 5. 基本面数据接入

### 5.1 数据源

| 研报 | 路径 | 对应周期 | 格式 |
|------|------|----------|------|
| **周报** | `experiments/ab-trading/A系列研报/周报/` | 周线 | Markdown |
| **A1日报** | `experiments/ab-trading/A系列研报/A1研报/` | 日线 | JSON |

### 5.2 解析逻辑

**A1日报 (JSON)** — [`_parse_a1_daily()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L82-L180):

支持三种 JSON 格式:
1. `market_regime.regime/confidence/composite_score`
2. `regime.name/confidence + si_index`
3. `regime + confidence + three_screen.daily`

提取字段: `date`, `direction`, `confidence`, `regime`, `score`

**周报 (Markdown)** — [`_parse_weekly_report()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L211-L291):

- 从 frontmatter 提取日期
- 从表格提取方向关键词（弱多头/弱空头/观望）
- 从 `评分 XX/100` 提取评分
- 从 `Regime: BEAR_TRANSITION` 提取 regime

### 5.3 合并规则

[`_merge_fundamental()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L308-L392):

| 场景 | 方向 | 置信度 |
|------|------|--------|
| 周报=日报且非中性 | 取一致方向 | 周报×60% + 日报×40% |
| 周报非中性，日报中性 | 取周报方向 | 周报×70% |
| 日报非中性，周报中性 | 取日报方向 | 日报×50% |
| 方向矛盾 | 取周报方向 | max(周报,日报)×30% |

### 5.4 公开接口

| 函数 | 用途 |
|------|------|
| [`fetch_fundamental_data()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L394-L433) | 获取合并后的基本面方向+置信度 |
| [`fetch_fundamental_by_timeframe()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L435-L448) | 按周期分别返回周线/日线基本面 |

---

## 6. 经典指标系统集成

### 6.1 入场信号（Freqtrade 多策略）

三屏趋势系统负责大方向判断，具体入场时机由经典系统的 Freqtrade 策略负责。

| 组件 | 文件 | 说明 |
|------|------|------|
| 信号获取 | [`signals.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py) | `fetch_freqtrade_signals()` 获取1h/4h多策略信号 |
| 信号对齐 | [`signals.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L158-L190) | `align_freqtrade_with_trend()` 信号校准 |
| HTTP桥接 | [`classic_bridge.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/classic_bridge.py) | 统一封装对经典系统的API调用 |

**信号校准规则**:

| 情况 | 置信度调整 |
|------|-----------|
| 同向 | +信号置信度×权重（1h×10%, 4h×15%） |
| 反向 | -10% |
| 1h或4h任一同向 | `freqtrade_consistent = true` |

### 6.2 离场决策（ClassicExitSystem）

三屏趋势系统不直接实现离场逻辑，全部委托给经典系统。

| 组件 | 文件 | 说明 |
|------|------|------|
| 离场集成 | [`exit_integration.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py) | `evaluate_exit()` 调用经典系统 |
| 引擎接口 | [`engine.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L196-L246) | `evaluate_exit_from_classic()` |

经典系统四层优先级离场架构:

| 优先级 | 层级 | 说明 |
|--------|------|------|
| P0 | L0 安全硬退出 | 紧急止损、黑天鹅保护 |
| P1 | L1/L2 价值-风险评估 | 基本面恶化、估值偏离 |
| P2 | Triple Barrier | 三重屏障动态止盈止损 |
| P3 | 执行层行为约束 | 冷却期、分批减仓 |

### 6.3 调用方式

支持两种调用方式（自动降级）:
1. **HTTP API** — 通过 `classic_bridge.py` 调用经典系统 REST API
2. **直接导入** — 当 API 不可用时，直接 import 经典系统 Python 模块

---

## 7. 置信度驱动的仓位模型

### 7.1 置信度 → 仓位映射

| 置信度 ≥ | 入场仓位 | 档位 |
|---------|---------|------|
| 85% | 60% | heavy |
| 75% | 45% | medium |
| 65% | 30% | light |
| 55% | 15% | trial |
| 45% | 5% | minimal |
| <45% | 0% | none |

配置: [`POSITION_TIERS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L39-L45)

### 7.2 执行决策（五大算法模式）

```
1. 趋势不一致 → WAIT
2. 方向 = BULL/BEAR 且 置信度 ≥ 60% → OPEN (正常仓位入场)
3. 方向 = BULL/BEAR 且 置信度 ≥ 45% → TRIAL (轻仓试探)
4. 其他 → WAIT
```

函数: [`five_algo_decision()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L248-L295)

配置: [`OPEN_CONFIDENCE_THRESHOLD`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L36) / [`TRIAL_CONFIDENCE_THRESHOLD`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L37)

---

## 8. 主数据流

```
                    ┌─────────────────────────────────────────────┐
                    │           技术指标维度                        │
                    │                                             │
                    │  周线TOP5指标 ──▶ 定期回测(vs 日线MA200基线)  │
                    │     │              优于基线 → 分配权重         │
                    │     │              形成置信度评估               │
                    │     ▼                                        │
                    │  静态方向 + 三维动态(方向/速度/加速度)         │
                    │     │                                        │
                    │     ▼  动态优先原则(权重更高)                  │
                    │  周线最终方向 + 置信度                         │
                    │                                             │
                    │  日线TOP5指标 ──▶ 同理(周线权重 > 日线权重)    │
                    │     │                                        │
                    │     ▼                                        │
                    │  日线最终方向 + 置信度                         │
                    │     │                                        │
                    │     ▼                                        │
                    │  周线 vs 日线 → 趋势一致性检测                 │
                    │  + 贝叶斯参数寻优 → 置信度                     │
                    └────────────────┬────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────────────────┐
                    │                ▼                             │
                    │           基本面维度                          │
                    │                                             │
                    │  A系列研报: 周报(MD) + A1日报(JSON)           │
                    │     │                                        │
                    │     ▼                                        │
                    │  基本面趋势一致性 + 置信度                    │
                    └────────────────┬────────────────────────────┘
                                     │
                                     ▼
                    技术面 + 基本面撮合
                    → 最终趋势方向 + 最终置信度
                                     │
                                     ▼
                    Freqtrade信号校准 (来自经典系统)
                    → 1h/4h 多策略投票
                    → 同向增益 / 反向扣减
                                     │
                                     ▼
                    置信度 → 仓位映射 (5%~60%)
                    + 离场决策 → 经典系统 ClassicExitSystem
```

---

## 9. 公开 API

### 9.1 完整信号计算（含数据获取）

```python
from engine import compute_full_trading_signal

result = compute_full_trading_signal(spot_inst="BTC-USDT", is_btc=True)
```

函数: [`compute_full_trading_signal()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L389-L448)

### 9.2 纯计算入口（数据由调用方提供）

```python
from engine import compute_trend_signal_from_dataframes

result = compute_trend_signal_from_dataframes(
    weekly_df=weekly_df,
    daily_df=daily_df,
    symbol="BTC",
    fundamental_data={"direction": "BULL", "confidence": 65},
    freqtrade_signals={"1h": {"signal": "BUY", "confidence": 70}},
)
```

函数: [`compute_trend_signal_from_dataframes()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L298-L386)

### 9.3 入场信号获取

```python
from engine import fetch_entry_signals_from_classic

signals = fetch_entry_signals_from_classic("BTC", ["1h", "4h"])
```

函数: [`fetch_entry_signals_from_classic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L169-L194)

### 9.4 离场决策

```python
from engine import evaluate_exit_from_classic

result = evaluate_exit_from_classic(
    position_info={"symbol": "BTC", "side": "long", "entry_price": 60000, "current_price": 62000, "quantity": 0.1},
    regime="trend",
)
```

函数: [`evaluate_exit_from_classic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L196-L246)

### 9.5 基本面数据

```python
from data.fundamental_data import fetch_fundamental_data, fetch_fundamental_by_timeframe

# 合并基本面
fund = fetch_fundamental_data("BTC")
# {"direction": "BEAR", "confidence": 7.0, "weekly": {...}, "daily": {...}}

# 分层基本面
tf = fetch_fundamental_by_timeframe("BTC")
# {"weekly": {...}, "daily": {...}}
```

---

## 10. 返回信号结构

`compute_trend_signal_from_dataframes()` 返回:

```python
{
    "symbol": "BTC",
    "price": 64433.7,
    "generated_at": "2026-07-10T12:00:00Z",
    "timeframes": {"weekly": 210, "daily": 250},
    "indicators": {
        "screen1_weekly": ["RSI_50", "SuperTrend", ...],
        "screen2_daily": ["GoldenCross_50_200", "MACD_Cross", ...],
    },
    "trend_consistency": {
        "weekly": {"static_direction": "BULL", "dynamic_direction": "BULL", ...},
        "daily": {...},
        "consistent": true,
        "overall_direction": "BULL",
    },
    "bayesian_confidence": {
        "direction": "BULL",
        "confidence": 73.2,
        "bull_probability": 0.732,
        "bear_probability": 0.268,
    },
    "classic_indicator_confidence": {...},
    "fundamental_data": {
        "direction": "BEAR",
        "confidence": 7.0,
        "weekly": {"date": "2026-07-06", "direction": "BEAR", "regime": "BEAR_TRANSITION", "score": 55},
        "daily": {"date": "2026-07-10", "direction": "NEUTRAL", "regime": "BEAR_RECOVERY", ...},
    },
    "freqtrade_signals": {
        "1h": {"signal": "BUY", "confidence": 75},
        "4h": {"signal": "BUY", "confidence": 80},
    },
    "technical_fundamental_fusion": {
        "technical": {"direction": "BULL", "confidence": 73.2},
        "fundamental": {"direction": "BEAR", "confidence": 7.0},
        "consistent": false,
        "final_direction": "BULL",
        "final_confidence": 51.2,
        "conflict_level": 30,
    },
    "final_signal": {
        "direction": "BULL",
        "confidence": 63.5,
        "trend_consistent": true,
        "fusion_consistent": false,
        "freqtrade_consistent": true,
        "action": "TRIAL",
        "position": {"position_pct": 0.15, "tier": "trial"},
        "decision_reason": "趋势一致但基本面矛盾，轻仓试探",
    },
}
```

---

## 11. 关键参数汇总

| 参数 | 值 | 配置位置 |
|------|----|---------|
| 周线指标数 | 5个 (RSI_50等) | `config.py` L17 |
| 日线指标数 | 5个 (GoldenCross等) | `config.py` L21 |
| 周线权重 | 60% | `config.py` L25 |
| 日线权重 | 40% | `config.py` L26 |
| 逆转覆盖阈值 | 60% | `config.py` L28 |
| 技术面权重 | 60% | `config.py` L32 |
| 基本面权重 | 40% | `config.py` L33 |
| 矛盾最大扣减 | 30% | `config.py` L34 |
| 正常入场阈值 | 60% | `config.py` L36 |
| 试探入场阈值 | 45% | `config.py` L37 |
| 仓位最高档 | 60% (置信度≥85%) | `config.py` L40 |
| 仓位最低档 | 5% (置信度≥45%) | `config.py` L44 |

候选币种池: [`CANDIDATE_COINS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L5-L15) (BTC, ETH, SOL, BNB, DOGE, XRP, UNI, HYPE, OKB)

---

## 12. 测试

运行测试:

```bash
cd 12-三屏趋势系统
python3 tests/test_core.py
```

测试覆盖:

| 测试函数 | 说明 |
|---------|------|
| `test_confidence_to_position()` | 置信度→仓位映射 |
| `test_five_algo_decision()` | 五大算法决策逻辑 |
| `test_trend_consistency()` | 趋势一致性检测 |
| `test_bayesian_confidence()` | 贝叶斯置信度计算 |
| `test_fusion()` | 技术面+基本面撮合 |
| `test_full_signal()` | 完整信号计算 + Freqtrade信号校准 |
| `test_fundamental_data()` | 基本面数据读取（A系列研报） |

测试文件: [`test_core.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/tests/test_core.py)
