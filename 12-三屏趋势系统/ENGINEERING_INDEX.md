# 12-三屏趋势系统 · 工程索引

> 模块路径: `12-三屏趋势系统/`
> 版本: v1.0.0
> 语言: Python 3.x
> 依赖: numpy, pandas, talib（可选，从10-经典指标系统导入）

---

## 目录

1. [模块总览](#1-模块总览)
2. [完整目录结构](#2-完整目录结构)
3. [文件详情索引](#3-文件详情索引)
4. [模块依赖关系](#4-模块依赖关系)
5. [公开 API 清单](#5-公开-api-清单)
6. [配置参数清单](#6-配置参数清单)
7. [数据结构清单](#7-数据结构清单)
8. [外部接口清单](#8-外部接口清单)
9. [测试覆盖](#9-测试覆盖)

---

## 1. 模块总览

### 1.1 系统定位

**趋势一致性确定方向，置信度评估确定仓位。**

三屏趋势系统 = 「趋势方向判定 + 置信度评估 + 仓位计算」

| 职责 | 归属 | 说明 |
|------|------|------|
| 趋势方向判定 | 本模块 | 周线 + 日线，静态 + 三维动态 |
| 置信度评估 | 本模块 | 贝叶斯置信度 + 基本面撮合 + Freqtrade校准 |
| 仓位计算 | 本模块 | 5档置信度映射 5%~60% |
| 入场信号 | **10-经典指标系统** | Freqtrade 多策略投票 |
| 离场决策 | **10-经典指标系统** | ClassicExitSystem 四层优先级 |
| 基本面数据 | **A系列研报** | 周报(MD) + A1日报(JSON) |
| K线数据 | **OKX API** | 周线 / 日线 / 小时线 |

### 1.2 三层架构

| 层级 | 名称 | 周期 | 核心模块 |
|------|------|------|---------|
| 第一屏 | 战略层 | 周线 | `core/trend_consistency.py` |
| 第二屏 | 战术层 | 日线 | `core/dynamic_weights.py`, `core/fusion.py` |
| 第三屏 | 执行层 | 4h/1h | `signals.py`, `exit_integration.py`（委托经典系统） |

---

## 2. 完整目录结构

```
12-三屏趋势系统/
│
├── __init__.py                         # 包入口，版本号 + 核心导出
├── README.md                           # 快速开始 + 简要索引
├── ENGINEERING_INDEX.md                # 本文档 · 完整工程索引
│
├── engine.py                           # ⭐ 主引擎（算法编排 + 公开接口）
│
├── signals.py                          # 入场信号服务（Freqtrade 多策略）
├── exit_integration.py                 # 离场决策集成（ClassicExitSystem）
├── classic_bridge.py                   # 经典系统 HTTP 桥接
│
├── core/                               # 🔧 核心算法层
│   ├── __init__.py                     #    核心包导出
│   ├── config.py                       #    配置常量
│   ├── indicators.py                   #    指标计算（三维动态 + 静态）
│   ├── trend_consistency.py            #    趋势一致性检测
│   ├── dynamic_weights.py              #    动态权重 + 贝叶斯置信度
│   └── fusion.py                       #    技术面+基本面撮合
│
├── data/                               # 📦 数据获取层
│   ├── __init__.py                     #    数据包导出
│   ├── market_data.py                  #    K线数据获取 + 重采样
│   └── fundamental_data.py             #    基本面数据获取（A系列研报）
│
├── tests/                              # ✅ 测试套件
│   ├── __init__.py                     #    测试包
│   └── test_core.py                    #    核心功能测试
│
└── docs/                               # 📚 文档
    └── trend-screen-system-design.md   #    技术设计文档
```

---

## 3. 文件详情索引

### 3.1 根目录文件

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`__init__.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/__init__.py) | 22 | — | 包入口，版本号 v1.0.0 |
| [`engine.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py) | ~450 | `compute_full_trading_signal()`<br>`compute_trend_signal_from_dataframes()`<br>`five_algo_decision()`<br>`confidence_to_position()`<br>`fetch_entry_signals_from_classic()`<br>`evaluate_exit_from_classic()` | **主引擎**。整合五大算法，编排数据流，提供完整信号计算接口 |
| [`signals.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py) | ~190 | `SignalDirection`<br>`StrategySignal`<br>`MultiStrategySignal`<br>`fetch_freqtrade_signals()`<br>`align_freqtrade_with_trend()` | **入场信号服务**。调用经典系统 Freqtrade 多策略，与趋势方向对齐校准 |
| [`exit_integration.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py) | ~230 | `ExitAction`<br>`PositionInfo`<br>`ExitDecisionResult`<br>`evaluate_exit()`<br>`get_exit_system_classic()` | **离场集成**。调用经典系统 ClassicExitSystem，支持 API/直接导入两种方式 |
| [`classic_bridge.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/classic_bridge.py) | ~90 | `get_classic_base_url()`<br>`_make_request()`<br>`is_classic_system_available()` | **HTTP桥接**。统一封装对经典指标系统的 REST API 调用 |

### 3.2 core/ 核心算法层

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`core/__init__.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/__init__.py) | 72 | — | 核心包导出，统一相对/绝对导入兼容 |
| [`core/config.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) | 52 | `CANDIDATE_COINS`<br>`SCREEN1_INDICATORS`<br>`SCREEN2_INDICATORS`<br>`POSITION_TIERS` | **配置常量**。指标组、权重、仓位档位、阈值等所有配置参数 |
| [`core/indicators.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py) | ~200 | `calc_indicator_dynamics()`<br>`calc_indicator_signal()`<br>`calc_trend_direction_static()`<br>`calc_classic_indicator_confidence()` | **指标计算引擎**。单指标三维动态(direction/speed/acceleration)、静态投票、经典指标综合置信度 |
| [`core/trend_consistency.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py) | ~150 | `calc_trend_direction_dynamic()`<br>`calc_trend_consistency()` | **趋势一致性检测**。静态+动态融合（动态优先原则），周线日线一致性判定 |
| [`core/dynamic_weights.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py) | ~200 | `calc_indicator_performance()`<br>`calc_dynamic_weights()`<br>`calc_bayesian_confidence()` | **动态权重 + 贝叶斯**。指标回测表现评估、动态权重分配、贝叶斯置信度计算 |
| [`core/fusion.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fusion.py) | ~100 | `fuse_technical_fundamental()` | **撮合层**。技术面与基本面方向和置信度的融合计算 |

### 3.3 data/ 数据获取层

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`data/__init__.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/__init__.py) | 1 | — | 数据包导出 |
| [`data/market_data.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py) | ~120 | `fetch_candles()`<br>`resample_candles()`<br>`_get_okx_client()` | **K线数据**。从 OKX API 获取K线，支持跨周期重采样(5m→1h→4h→1D) |
| [`data/fundamental_data.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py) | ~450 | `fetch_fundamental_data()`<br>`fetch_fundamental_by_timeframe()`<br>`_parse_a1_daily()`<br>`_parse_weekly_report()`<br>`_merge_fundamental()` | **基本面数据**。解析A系列研报(周报MD + A1日报JSON)，输出方向+置信度 |

### 3.4 tests/ 测试

| 文件 | 行数 | 测试函数数 | 覆盖范围 |
|------|------|-----------|---------|
| [`tests/test_core.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/tests/test_core.py) | ~280 | 7个 | 置信度映射、五大算法决策、趋势一致性、贝叶斯、撮合、完整信号、基本面数据 |

### 3.5 docs/ 文档

| 文件 | 说明 |
|------|------|
| [`docs/trend-screen-system-design.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/trend-screen-system-design.md) | 技术设计文档，v2.0，含五大算法、数据流、API、参数汇总 |

---

## 4. 模块依赖关系

### 4.1 内部依赖图

```
                    ┌─────────────────────────┐
                    │       engine.py         │  主引擎编排
                    │  (compute_full_*)       │
                    └────┬───────┬──────┬────┘
                         │       │      │
              ┌──────────┘       │      └──────────────┐
              │                  │                     │
    ┌─────────▼────────┐ ┌──────▼─────────┐ ┌────────▼──────────┐
    │  core/           │ │  signals.py    │ │ exit_integration.py│
    │  五大算法        │ │  Freqtrade信号 │ │ ClassicExitSystem  │
    └────────┬─────────┘ └──────┬─────────┘ └────────┬──────────┘
             │                  │                     │
             │           ┌──────▼─────────┐           │
             │           │ classic_bridge │           │
             │           │   (HTTP)       │           │
             │           └────────────────┘           │
             │                                        │
    ┌────────▼─────────┐                     ┌────────▼──────────┐
    │  data/           │                     │ 10-经典指标系统    │
    │  market_data.py  │                     │ (外部依赖)         │
    │  fundamental.py  │                     └───────────────────┘
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ OKX API / A系列研报│
    │ (外部数据源)      │
    └───────────────────┘
```

### 4.2 内部依赖方向

| 模块 | 依赖 | 被谁依赖 |
|------|------|---------|
| `core/config.py` | 无 | indicators, trend_consistency, dynamic_weights, engine |
| `core/indicators.py` | core/config | trend_consistency, engine |
| `core/trend_consistency.py` | core/config, core/indicators | engine |
| `core/dynamic_weights.py` | core/config, core/indicators | engine |
| `core/fusion.py` | 无 | engine |
| `data/market_data.py` | 无 | engine |
| `data/fundamental_data.py` | 无 | engine |
| `signals.py` | classic_bridge | engine |
| `exit_integration.py` | classic_bridge | engine |
| `classic_bridge.py` | 无 | signals, exit_integration |
| `engine.py` | core/\*, data/\*, signals, exit_integration | 外部调用 |

### 4.3 导入兼容机制

所有支持模块导入的文件均实现了 **相对导入 / 绝对导入 双兼容**（try-except 模式），确保：
- 作为包导入时（`from core import ...`）正常工作
- 直接运行脚本时（`python engine.py`）也正常工作

---

## 5. 公开 API 清单

### 5.1 主引擎 API

| 函数 | 输入 | 输出 | 用途 |
|------|------|------|------|
| [`compute_full_trading_signal()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L389-L448) | `spot_inst`, `is_btc` | 完整信号 dict | **完整入口**：自动获取K线+基本面，计算完整信号 |
| [`compute_trend_signal_from_dataframes()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L298-L386) | `weekly_df`, `daily_df`, `symbol`, `price`, `fundamental_data`, `freqtrade_signals` | 完整信号 dict | **纯计算入口**：数据由调用方提供，适合回测/单元测试 |
| [`five_algo_decision()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L248-L295) | `trend_consistent`, `direction`, `confidence` | `{action, confidence, position, reason}` | 五大算法决策（OPEN/TRIAL/WAIT） |
| [`confidence_to_position()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L57-L75) | `confidence` (0-100) | `{position_pct, tier, counter_trend_addon_budget}` | 置信度 → 仓位映射 |

### 5.2 经典系统集成 API

| 函数 | 输入 | 输出 | 用途 |
|------|------|------|------|
| [`fetch_entry_signals_from_classic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L169-L194) | `symbol`, `timeframes` | `{tf: MultiStrategySignal}` | 获取经典系统入场信号 |
| [`evaluate_exit_from_classic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L196-L246) | `position_info`, `candles_1h`, `regime` | `{action, confidence, reason, ...}` | 获取经典系统离场决策 |

### 5.3 核心算法 API (core/)

| 函数 | 所在文件 | 输入 | 输出 |
|------|---------|------|------|
| `calc_trend_consistency()` | [trend_consistency.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py#L130) | weekly_df, daily_df | `{weekly, daily, consistent, overall_direction, ...}` |
| `calc_bayesian_confidence()` | [dynamic_weights.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py#L140) | weekly_df, daily_df | `{direction, confidence, bull_probability, bear_probability, ...}` |
| `fuse_technical_fundamental()` | [fusion.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fusion.py#L33) | technical_result, fundamental_result | `{final_direction, final_confidence, consistent, conflict_level, ...}` |
| `calc_trend_direction_static()` | [indicators.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py#L189) | df, indicators | `"BULL"/"BEAR"/"NEUTRAL"` |
| `calc_trend_direction_dynamic()` | [trend_consistency.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py#L42) | df, indicators | `{direction, confidence, reversal_score, avg_speed, ...}` |
| `calc_dynamic_weights()` | [dynamic_weights.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py#L78) | df, indicators | `{weights, performance, total_score}` |
| `calc_indicator_dynamics()` | [indicators.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py#L36) | df, indicator_name | `{direction, speed, acceleration, value, ...}` |

### 5.4 数据层 API (data/)

| 函数 | 所在文件 | 输入 | 输出 |
|------|---------|------|------|
| `fetch_candles()` | [market_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py#L22) | inst_id, bar, limit | `[{o,h,l,c,vol,...}]` |
| `resample_candles()` | [market_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py#L80) | candles, target_tf | `[{o,h,l,c,vol,...}]` |
| `fetch_fundamental_data()` | [fundamental_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L394) | symbol | `{direction, confidence, weekly, daily, reports, ...}` |
| `fetch_fundamental_by_timeframe()` | [fundamental_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L435) | symbol | `{weekly: {...}, daily: {...}}` |

---

## 6. 配置参数清单

### 6.1 指标组配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `SCREEN1_INDICATORS` | 5个 | 周线指标组: RSI_50, SuperTrend, StochRSI_Cross, OBV_Trend, Keltner_Channel | [config.py L17](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L17) |
| `SCREEN2_INDICATORS` | 6个 | 日线指标组: GoldenCross_50_200, MACD_Cross, Vortex, TEMA, EMA_Align_20_50_200, Elder_ray | [config.py L21](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L21) |

### 6.2 权重配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `WEEKLY_WEIGHT` | 0.6 | 周线权重（准确度更高） | [config.py L25](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L25) |
| `DAILY_WEIGHT` | 0.4 | 日线权重 | [config.py L26](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L26) |
| `TECHNICAL_WEIGHT` | 0.6 | 技术面权重（撮合时） | [config.py L32](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L32) |
| `FUNDAMENTAL_WEIGHT` | 0.4 | 基本面权重（撮合时） | [config.py L33](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L33) |

### 6.3 逆转检测配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `REVERSAL_THRESHOLD` | 60.0 | 逆转覆盖阈值(%)，超过则动态方向覆盖静态 | [config.py L28](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L28) |
| `REVERSAL_SPEED_LOW` | 30.0 | 逆转速度下限：speed 低于此值可能逆转 | [config.py L29](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L29) |
| `REVERSAL_ACCEL_HIGH` | 20.0 | 逆转加速度上限：accel 高于此值可能逆转 | [config.py L30](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L30) |

### 6.4 撮合配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `MAX_CONFLICT_DEDUCTION` | 0.3 | 方向矛盾时最大扣减比例 | [config.py L34](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L34) |

### 6.5 决策阈值配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `OPEN_CONFIDENCE_THRESHOLD` | 60.0 | 正常入场置信度阈值(%) | [config.py L36](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L36) |
| `TRIAL_CONFIDENCE_THRESHOLD` | 45.0 | 轻仓试探置信度阈值(%) | [config.py L37](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L37) |

### 6.6 仓位配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `POSITION_TIERS` | 5档 | 置信度→仓位映射: 85→60%, 75→45%, 65→30%, 55→15%, 45→5% | [config.py L39](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L39) |
| `CONFIDENCE_JUMP_THRESHOLD` | 15.0 | 顺势加仓置信度跃迁阈值(%) | [config.py L47](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L47) |
| `COUNTER_TREND_ADDON_BUDGET` | 0.4 | 逆势加仓预算比例 | [config.py L48](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L48) |
| `TOTAL_POSITION_BUDGET_CAP` | 0.8 | 总仓位硬上限 | [config.py L49](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L49) |

### 6.7 币种池配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `CANDIDATE_COINS` | 9个 | BTC, ETH, SOL, BNB, DOGE, XRP, UNI, HYPE, OKB | [config.py L5](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L5) |
| `DEFAULT_INST_SPOT` | "BTC-USDT" | 默认现货交易对 | [config.py L51](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L51) |
| `DEFAULT_INST_SWAP` | "BTC-USDT-SWAP" | 默认合约交易对 | [config.py L52](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L52) |

---

## 7. 数据结构清单

### 7.1 核心数据类

| 类名 | 所在文件 | 字段 | 用途 |
|------|---------|------|------|
| `SignalDirection` | [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L19) | LONG, SHORT, HOLD | Freqtrade信号方向枚举 |
| `StrategySignal` | [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L26) | strategy_name, signal, confidence, reason | 单策略信号 |
| `MultiStrategySignal` | [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L35) | symbol, timeframe, direction, confidence, strategy_count, long_votes, short_votes, strategies | 多策略投票信号 |
| `ExitAction` | [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py#L23) | CLOSE, REDUCE, HOLD | 离场动作枚举 |
| `PositionInfo` | [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py#L30) | symbol, side, entry_price, current_price, quantity, entry_time, notional_usd | 持仓信息 |
| `ExitDecisionResult` | [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py#L44) | action, confidence, reason, priority, reduce_fraction, suggested_price, triggered_by | 离场决策结果 |

### 7.2 完整信号返回结构

`compute_trend_signal_from_dataframes()` 返回的 dict 结构：

```
{
  symbol: str,
  price: float,
  generated_at: str (ISO),
  timeframes: { weekly: int, daily: int },
  indicators: { screen1_weekly: [...], screen2_daily: [...] },
  trend_consistency: {
    weekly: { static_direction, dynamic_direction, final_direction, confidence, reversal_score, ... },
    daily: { ... },
    consistent: bool,
    overall_direction: str,
    consistency_confidence: float,
  },
  bayesian_confidence: {
    direction: str,
    confidence: float,
    bull_probability: float,
    bear_probability: float,
    weekly_weights: { ... },
    daily_weights: { ... },
  },
  classic_indicator_confidence: { ... },
  fundamental_data: {
    direction: str,
    confidence: float,
    weekly: { date, direction, confidence, regime, score, source_file },
    daily: { date, direction, confidence, regime, score, source_file },
    reports: [...],
    bull_count: int,
    bear_count: int,
    total_reports: int,
  },
  freqtrade_signals: {
    "1h": { signal, confidence, ... },
    "4h": { ... },
  },
  technical_fundamental_fusion: {
    technical: { direction, confidence },
    fundamental: { direction, confidence },
    consistent: bool,
    final_direction: str,
    final_confidence: float,
    conflict_level: float,
    ...
  },
  final_signal: {
    direction: str,
    confidence: float,
    trend_consistent: bool,
    fusion_consistent: bool,
    freqtrade_consistent: bool,
    action: str (OPEN/TRIAL/WAIT),
    position: { position_pct, tier, counter_trend_addon_budget },
    decision_reason: str,
  },
}
```

---

## 8. 外部接口清单

### 8.1 外部依赖系统

| 外部系统 | 接口方式 | 用途 | 调用模块 |
|---------|---------|------|---------|
| **10-经典指标系统** | HTTP API / 直接导入 | Freqtrade 入场信号 | `signals.py` → `classic_bridge.py` |
| **10-经典指标系统** | HTTP API / 直接导入 | ClassicExitSystem 离场决策 | `exit_integration.py` → `classic_bridge.py` |
| **OKX API** | REST API | K线数据获取 | `data/market_data.py` |
| **A系列研报** | 文件读取 | 基本面数据 | `data/fundamental_data.py` |
| **talib** | Python import | 指标计算（从10-经典系统导入） | `core/indicators.py` |

### 8.2 A系列研报路径

| 研报类型 | 路径 | 格式 | 对应周期 |
|---------|------|------|---------|
| 周报 | `experiments/ab-trading/A系列研报/周报/screen1_YYYYMMDD.md` | Markdown + frontmatter | 周线 |
| A1日报 | `experiments/ab-trading/A系列研报/A1研报/a1_regime_YYYYMMDD.json` | JSON | 日线 |

### 8.3 经典系统 HTTP 接口

| 端点 | 方法 | 用途 | 调用方 |
|------|------|------|-------|
| `/api/freqtrade/signals` | GET | 获取 Freqtrade 多策略信号 | `signals.py` |
| `/api/exit/evaluate` | POST | 获取离场决策 | `exit_integration.py` |
| `/api/health` | GET | 健康检查 | `classic_bridge.py` |

Base URL 配置：环境变量 `CLASSIC_SYSTEM_BASE_URL`，默认 `http://localhost:8092`

---

## 9. 测试覆盖

### 9.1 测试运行

```bash
cd 12-三屏趋势系统
python3 tests/test_core.py
```

### 9.2 测试用例清单

| 测试函数 | 覆盖模块 | 测试点 |
|---------|---------|--------|
| `test_confidence_to_position()` | engine.py | 5档仓位映射正确性 |
| `test_five_algo_decision()` | engine.py | 五大算法决策：OPEN/TRIAL/WAIT |
| `test_trend_consistency()` | core/trend_consistency.py | 趋势一致性：一致/不一致场景 |
| `test_bayesian_confidence()` | core/dynamic_weights.py | 贝叶斯置信度计算 |
| `test_fusion()` | core/fusion.py | 技术面+基本面撮合：一致/中性/矛盾 |
| `test_full_signal()` | engine.py | 完整信号计算 + Freqtrade信号校准 |
| `test_fundamental_data()` | data/fundamental_data.py | A系列研报读取 + 周报/A1日报解析 + 合并 |

### 9.3 合成数据生成

测试使用 `_generate_synthetic_data()` 函数生成合成K线数据，支持 `bull` / `bear` / `sideways` 三种趋势模式，不依赖真实市场数据。

---

**文档版本**: ENGINEERING_INDEX v1.0
**最后更新**: 2026-07-10
