# V15 经典马丁策略

> 基于斐波那契回调 + 布林带均值回归 + RSI/MACD/ADX 的纯技术分析马丁格尔交易策略

## 目录

- [1. 策略概述](#1-策略概述)
- [2. 目录结构](#2-目录结构)
- [3. 快速开始](#3-快速开始)
- [4. 策略原理](#4-策略原理)
- [5. 入场决策体系](#5-入场决策体系)
- [6. 马丁加仓体系](#6-马丁加仓体系)
- [7. 止损止盈体系](#7-止损止盈体系)
- [8. 资金管理](#8-资金管理)
- [9. 技术指标](#9-技术指标)
- [10. 配置说明](#10-配置说明)
- [11. API 接口](#11-api-接口)
- [12. 测试](#12-测试)
- [13. 风控规则](#13-风控规则)

---

## 1. 策略概述

V15 经典马丁策略是一个**只做多**的马丁格尔交易策略，核心思想：

- **方向判断优先**：通过4条均线系统判断价格位置，只在多头排列时入场
- **斐波那契回调入场**：在趋势中等待回调至黄金区间（38.2%-61.8%）再进场
- **布林带均值回归**：震荡区利用布林带上下轨做均值回归
- **马丁加仓**：入场后若继续下跌，按递增间距分批加仓（最多3次）
- **波动率自适应**：所有参数根据30天波动率动态调整

**交易周期**：4H
**最大加仓**：3次（共4层仓位）
**交易方向**：只做多
**入场决策**：16层入场体系（满足任一指标条件即可开仓）
**技术指标**：16项
**监控币种**：34个 — BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LTC, LINK, AVAX, DOT, UNI, NEAR, APT, ARB, OP, INJ, SUI, SEI, TIA, AAVE, COMP, CRV, DYDX, LDO, PEPE, SAND, SHIB, STX, SUSHI, WLD, ZEC, OKB, HYPE

---

## 2. 目录结构

```
14-V15经典马丁策略/
├── run.py                    # 统一入口脚本
├── README.md                 # 本文档
├── config/                   # 配置文件
│   ├── .env.common           # 公共配置（OKX密钥、资金参数）
│   └── .env.v15              # V15策略专属配置
├── core/                     # 核心策略层
│   ├── v15_signal.py         # 信号引擎（16层入场决策 + 16项技术指标）
│   ├── v15_trader.py         # 自动交易器（轮询、开仓、加仓、止盈止损）
│   └── v15_backtest.py       # 回测引擎
├── lib/                      # 基础工具层
│   ├── config_loader.py      # 配置加载器（支持 include 语法）
│   ├── okx_client.py         # OKX 交易客户端
│   ├── market_data.py        # K线数据获取 + 基础指标
│   ├── strategy_params.py    # 动态参数计算（止损/止盈/波动率/Elder-ray趋势强度）
│   ├── capital_manager.py    # 资金管理计算器
│   ├── capital_manager_engine.py  # 资金管理引擎（回测+趋势过滤+贝叶斯优化+HTTP API）
│   ├── bayesian_optimizer.py # 贝叶斯参数优化器（8参数，最大化卡尔马比率）
│   └── symbol_mapper.py      # 币种映射工具
├── tests/                    # 测试套件
│   ├── test_v15_system.py    # 系统测试（19项，1000次随机场景）
│   ├── test_v15_stress.py    # 多场景压力测试（25项，含500次随机）
│   ├── test_multi_scenario.py # 多场景模拟测试（89项，7大模块40+场景）
│   ├── test_symbol_mapper.py # 币种映射测试
│   └── v15_stress_test.py    # 资金管理压力测试
├── data/                     # 运行数据
│   ├── v15_state.json        # 交易状态持久化
│   ├── backtest_cache/       # 回测K线缓存
│   └── okx_client/           # OKX客户端数据
└── docs/                     # 技术文档
    ├── ENGINEERING_INDEX.md  # 工程索引（v4.1）
    ├── TECHNICAL_DESIGN.md   # 技术设计文档（v4.0）
    ├── API_SPEC.md           # 接口规格文档（v3.1）
    └── CHANGELOG.md          # 变更日志（v1.0）

> **当前运行版本：** master_daemon 每小时调用 `run.py poll_once`（独立V15系统）
>
> **V15-CT 实验版**（`experiments/ab-trading/`）已废弃，代码保留作为AB对照参考，不再维护。
```

---

## 3. 快速开始

### 3.1 环境要求

- Python 3.8+
- 依赖：`requests`（OKX API 调用）

### 3.2 配置

编辑 `config/.env.common`，填入 OKX API 密钥：

```bash
OKX_API_KEY=your_api_key
OKX_SECRET_KEY=your_secret_key
OKX_PASSPHRASE=your_passphrase
```

编辑 `config/.env.v15`，调整策略参数（详见[配置说明](#10-配置说明)）。

### 3.3 使用

**V15 独立系统（当前运行版本）：**

```bash
cd 14-V15经典马丁策略

# 查看全部币种信号
python3 run.py signal

# 查看指定币种信号
python3 run.py signal BTC,ETH

# BTC 回测（1000根K线）
python3 run.py backtest BTC 1000

# 查看资金管理状态
python3 run.py capital

# 查看当前配置
python3 run.py config

# 启动自动交易器
python3 run.py trader

# 单次轮询（master_daemon 每小时调用）
python3 run.py poll_once

# 资金管理引擎 — 月度优化
python3 run.py capital_engine monthly

# 资金管理引擎 — 查看状态
python3 run.py capital_engine status

# 资金管理引擎 — 趋势过滤检查
python3 run.py capital_engine trend --coin BTC

# 资金管理引擎 — 综合开仓许可检查
python3 run.py capital_engine check --coin BTC

# 资金管理引擎 — 启动HTTP API服务（端口8770）
python3 run.py capital_engine api --port 8770

# 运行全部测试
python3 run.py test
```

> **当前运行方式：** master_daemon 每小时调用 `run.py poll_once`，无需手动启动。

---

## 4. 策略原理

### 4.1 整体流程

```
K线数据获取（4H）
    │
    ▼
均线系统计算 ──→ 位置判断（ABOVE_ALL / IN_ZONE / BELOW_ALL）
    │
    ├── ABOVE_ALL → 16层入场决策（Fib回调 + 布林 + MACD + ADX + 9项新增指标）
    ├── IN_ZONE   → 均值回归 + 多指标入场（布林下轨 + 9项新增指标）
    └── BELOW_ALL → 等待（只做多，不做空）
    │
    ▼
信号触发 → 资金管理检查 → 开仓/加仓/止盈/止损
    │
    ▼
状态持久化 + 日志记录
```

### 4.2 位置判断

使用 4 条简单移动平均线判断价格位置：

| 均线 | 周期 | 用途 |
|------|------|------|
| SMA30 | 30根4H (~5天) | 短期趋势 |
| SMA65 | 65根4H (~11天) | 中期趋势 |
| SMA128 | 128根4H (~21天) | 中长期趋势 |
| SMA200 | 200根4H (~33天) | 长期趋势 |

位置判定规则：
- `ABOVE_ALL`：价格 > 全部4条均线 → 最强做多区
- `BELOW_ALL`：价格 < 全部4条均线 → 熊市等待区
- `IN_ZONE`：价格在均线之间 → 震荡区

---

## 5. 入场决策体系

### 5.1 ABOVE_ALL — 16层入场决策（只做多）

这是核心做多区，按优先级链式判断（elif 命中即停）。设计理念：**满足任一指标条件即可开仓**，通过多指标覆盖更多入场场景。

Fib回调区计算（做多时从高点向下回调）：
```
range = swing_high - swing_low
f382 = swing_high - 0.382 × range   （浅回调位）
f500 = swing_high - 0.500 × range   （中回调位）
f618 = swing_high - 0.618 × range   （深回调位）
in_zone = f618 ≤ price ≤ f382       （价格在回调区内）
golden_zone = price ≤ f500           （黄金区：更深回调）
```

| Tier | 条件 | 置信度 | 仓位倍数 | 场景 |
|------|------|--------|----------|------|
| 1 | Fib黄金区 + RSI<55 + 布林中轨/下轨 | 80 | 1.0 | 双重确认（最高优先级） |
| 2 | Fib黄金区 + RSI<55 | 75 | 1.0 | Fib黄金区入场（主入场信号） |
| 3 | Fib浅区 + RSI<55 | 60 | 0.5 | Fib浅区回调，轻仓试探 |
| 4 | Fib区外 + 布林中轨(±2%) + RSI<50 | 65 | 0.5 | 趋势中继：回调至布林中轨 |
| 5 | RSI<45 + Fib区外 | 60 | 0.5 | 多头动能持续，RSI偏低 |
| 6 | MACD多头柱扩张 + RSI<55 | 68 | 0.6 | MACD hist>0 且 |hist|扩张 |
| 7 | ADX>25 + +DI>-DI + RSI<55 | 70 | 0.7 | ADX强趋势+多头DI确认 |
| 8 | Pivot Points支撑区(S1~Pivot) + RSI中性(40~65) | 62 | 0.5 | 支撑位做多 |
| 9 | OBV多头趋势+量能加速 + RSI<60 | 66 | 0.6 | 资金流入确认 |
| 10 | SuperTrend多头 + RSI<60 | 64 | 0.5 | 趋势启动信号 |
| 11 | Keltner Channel下沿/中线 + RSI<60 | 61 | 0.5 | 均值回归机会 |
| 12 | StochRSI金叉/超卖 + RSI<60 | 63 | 0.5 | 动量反转信号 |
| 13 | Vortex多头反转 + RSI<65 | 65 | 0.5 | 趋势反转确认 ¹ |
| 14 | TEMA多头趋势(slope>0) + RSI<65 | 64 | 0.5 | 三重EMA确认 ¹ |
| 15 | GoldenCross金叉(EMA50>EMA200) + RSI<65 | 72 | 0.7 | 长期趋势启动 ¹ |
| 16 | EMA排列多头(20>50>200) + RSI<65 | 75 | 0.8 | 完美多头排列 ¹ |

> ¹ Tier 13-16 的指标来自**三屏趋势系统回测验证**，具有更高的趋势确认可靠性

关键设计：
- Tier 1-3 是 Fib 回调区内的入场，按回调深度分级
- Tier 4-5 是 Fib 区外的辅助入场，依赖布林带和 RSI
- Tier 6-7 是趋势信号入场，MACD 和 ADX 独立确认
- Tier 8-12 是新增技术指标入场，覆盖支撑位、量能、趋势、通道、动量等维度
- Tier 13-16 是三屏趋势系统回测验证指标，具有更高的趋势确认可靠性
- **设计理念：满足任一指标条件即可开仓**，不要求多个指标同时满足
- 布林中轨判定：`|price - boll_sma| / boll_sma < 0.02`（2%以内）
- 布林下轨判定：`price ≤ boll_lower`

### 5.2 IN_ZONE — 均值回归 + 多指标入场（只做多）

| 条件 | 置信度 | 信号 | 场景 |
|------|--------|------|------|
| 布林下轨 + RSI<45 | 70 | OPEN_BULL | 触及下轨+超卖，均值回归 |
| RSI<35 | 65 | OPEN_BULL | 超卖，单层LONG |
| Pivot Points支撑区 + RSI中性(40~65) | 62 | OPEN_BULL | 支撑位做多 |
| OBV多头趋势+量能加速 + RSI<60 | 64 | OPEN_BULL | 资金流入确认 |
| SuperTrend多头 + RSI<60 | 62 | OPEN_BULL | 趋势确认做多 |
| Keltner Channel下沿 + RSI<60 | 60 | OPEN_BULL | 通道下沿均值回归 |
| StochRSI金叉/超卖 + RSI<60 | 61 | OPEN_BULL | 动量反转信号 |
| Vortex多头反转 + RSI<65 | 63 | OPEN_BULL | 趋势反转确认 ¹ |
| TEMA多头趋势(slope>0) + RSI<65 | 62 | OPEN_BULL | 三重EMA确认 ¹ |
| GoldenCross金叉 + RSI<65 | 70 | OPEN_BULL | 长期趋势启动 ¹ |
| EMA排列多头(20>50>200) + RSI<65 | 72 | OPEN_BULL | 完美多头排列 ¹ |
| 布林上轨 + RSI>55 | — | 等待 | 只做多，不做空 |
| RSI>65 | — | 等待 | 超买，只做多不反手 |
| 其他 | — | 等待 | 所有指标均未触发 |

> ¹ Vortex/TEMA/GoldenCross/EMA_Align 来自三屏趋势系统回测验证

### 5.3 BELOW_ALL — 熊市等待区

实盘信号模块：**纯等待，不产生任何信号**。

回测引擎中支持 BELOW_ALL 做空（16层镜像逻辑），通过 `--allow-short` 参数开启。

### 5.4 波动率倍数矩阵

入场后根据信号类型调整仓位：

| 信号组合 | vol_mult | 含义 |
|----------|----------|------|
| Fib黄金区 + 布林触轨 | 1.3 | 最强信号，加仓30% |
| Fib黄金区（单独） | 1.2 | 强信号，加仓20% |
| Fib浅区 | 0.8 | 弱信号，减仓20% |
| ADX强趋势 | 0.9 | 趋势信号，略减 |
| MACD信号 | 0.8 | 动能信号，减仓 |
| 布林触轨（无Fib） | 1.0 | 标准仓位 |
| RSI极端 | 0.7 | 超卖反弹，轻仓 |

实际下单保证金 = 基础保证金 × vol_mult × size_mult

---

## 6. 马丁加仓体系

### 6.1 加仓触发条件

```
第N次加仓触发条件:
  ├─ 当前加仓次数 < MAX_ADDONS（3次）
  ├─ 资金管理允许加仓
  ├─ 跌幅 ≥ addon_pct × vol_ratio × (addons + 1)  ← 递增门槛
  │   第1次: 跌幅 ≥ 8% × vol_ratio
  │   第2次: 跌幅 ≥ 16% × vol_ratio
  │   第3次: 跌幅 ≥ 24% × vol_ratio
  └─ 下单数量 ≥ 最小合约单位
```

### 6.2 加仓保证金计算

```
加仓保证金 = base_margin × vol_mult × addon_pct × (addons + 1)
```

### 6.3 均价更新

```
均价 = (旧仓位 × 旧价 + 新仓位 × 新价) / 总仓位
```

### 6.4 波动率自适应

```
ratio = coin_volatility / btc_volatility  （限制在 0.5~2.5）
tp_pct = BASE_TP_PCT(4%) × ratio
addon_pct = BASE_ADDON_PCT(8%) × ratio
```

不同币种的波动率倍数示例：
- BTC: 1.0（基准）
- ETH: ~1.2
- SOL: ~1.5
- ARB/OP: ~2.0
- HYPE: ~3.0

---

## 7. 止损止盈体系

### 7.1 动态止盈

```
tp_pct = BASE_TP_PCT(4%) × vol_ratio × vol_mult
止盈价 = 入场均价 × (1 + tp_pct)
```

### 7.2 MA200 动态止损（4均线系统）

> **重要区分**：价格位置判定使用4H均线（SMA30/65/128/200），动态止损使用日线/周线均线（MA200/EMA200）。

使用日线/周线 MA200 + EMA200 四均线系统：

```
止损线 = 价格下方最近的一条均线
         ├─ 日线 MA200
         ├─ 日线 EMA200
         ├─ 周线 MA200
         └─ 周线 EMA200

触发条件 = 对应周期的【已收盘价】跌破止损线
         ├─ 日线止损 → 看昨收
         └─ 周线止损 → 看上周收盘
         （未收盘的实时价跌破不算触发）
```

均线用途区分：
- **4H均线（SMA30/65/128/200）**：用于价格位置判定（ABOVE_ALL / IN_ZONE / BELOW_ALL），决定是否进入入场决策
- **日线/周线均线（MA200/EMA200）**：用于动态止损，决定何时平仓退出

特殊情况处理：
- `BELOW_ALL_MA_INTRADAY` — 收盘价在某条均线上但实时价全破 → 不触发
- `BELOW_ALL_MA_CONFIRMED` — 所有均线收盘价全破 → **无条件止损**

### 7.3 三屏趋势过滤器（both_bear + MA104）

借用三屏趋势交易系统的周线和日线趋势一致性概念，在开仓前进行趋势过滤：

```
周线MA104 + 日线MA104 双周期趋势检查
  ├─ 周线看空（价格 < 周线MA104）
  ├─ 日线看空（价格 < 日线MA104）
  └─ both_bear模式：两者都看空 → 禁止做多马丁
```

**与MA200动态止损的区别：**
- MA200动态止损：保护已有持仓，收盘价跌破触发止损
- 三屏趋势过滤器：控制新开仓，实时价格判断趋势方向
- MA104周期（约5个月均线）既能过滤大熊市，又不会过度过滤

---

## 8. 资金管理

### 8.1 单仓位资金需求

**V15 独立系统（当前运行版本）：**

贝叶斯优化后的资金分配 — 底仓现货思维 + 黑天鹅加仓：

```
底仓  = BASE_POSITION_PCT(22%) × TOTAL_BUDGET(100) = $22
加仓1 = ADDON1_PCT(5%)  × TOTAL_BUDGET = $5   ← 黑天鹅第一档
加仓2 = ADDON2_PCT(25%) × TOTAL_BUDGET = $25  ← 黑天鹅第二档
加仓3 = ADDON3_PCT(10%) × TOTAL_BUDGET = $10  ← 黑天鹅第三档

单仓位总需求 = 底仓 + 加仓1 + 加仓2 + 加仓3 = $62
```

> 设计理念：底仓22% + 5x杠杆 ≈ 110%现货敞口，平时略占优且有止盈机制；加仓资金按黑天鹅层级分配，第二档最重（25%）用于深跌抄底。

**V15 独立版（历史配置，已被贝叶斯优化版本替代）：**

```
底仓 = BASE_POSITION_PCT(5%) × TOTAL_BUDGET(260) = $13
加仓 = ADDON_PCT(8%) × 底仓 × (addons + 1)

单仓位总需求 = 底仓 × (1 + 6 × ADDON_PCT) = $13 × 1.48 = $19.24
```

### 8.2 开仓许可规则

```
可用资金 ≥ 单仓位总需求 × 2  → 允许开新仓
单仓位总需求 ≤ 可用资金 < 总需求 × 2  → 仅允许加仓，禁止开新仓
可用资金 < 单仓位总需求  → 禁止一切新操作
```

### 8.3 并发持仓限制

```
V15-CT 实战版（已废弃）：MAX_CONCURRENT_POSITIONS = 6
V15 独立版：  MAX_CONCURRENT_POSITIONS = 4
```

V15独立系统最多同时持有 4 个币种的仓位（贝叶斯优化可调整，范围2-8）。

---

## 9. 技术指标

### 9.1 指标清单

| 指标 | 参数 | 用途 | 来源 | 代码位置 |
|------|------|------|------|----------|
| SMA | 30/65/128/200 | 趋势判断 | 原始 | `v15_signal.py:calc_sma()` |
| RSI | 14 | 超买超卖 | 原始 | `v15_signal.py:calc_rsi()` |
| Fibonacci | 30根K线 | 回调位 | 原始 | `v15_signal.py:calc_fibonacci()` |
| Bollinger Bands | 20, 2σ | 均值回归 | 原始 | `v15_signal.py:calc_bollinger_bands()` |
| MACD | 12/26/9 | 趋势动能 | 原始 | `v15_signal.py:calc_macd()` |
| ADX | 14 (Wilder) | 趋势强度 | 原始 | `v15_signal.py:calc_adx()` |
| Pivot Points | 1周期 | 支撑/阻力位 | 扩展指标 | `v15_signal.py:calc_pivot_points()` |
| OBV | 10期MA | 量能趋势 | 扩展指标 | `v15_signal.py:calc_obv()` |
| SuperTrend | 10, 3×ATR | 趋势方向 | 扩展指标 | `v15_signal.py:calc_supertrend()` |
| Keltner Channel | 20, 2×ATR | 通道突破/回归 | 扩展指标 | `v15_signal.py:calc_keltner_channel()` |
| StochRSI | 14/3/3 | 动量反转 | 扩展指标 | `v15_signal.py:calc_stochrsi()` |
| Vortex | 14 | 趋势反转 | 三屏回测验证 ¹ | `v15_signal.py:calc_vortex()` |
| TEMA | 30 | 三重EMA趋势 | 三屏回测验证 ¹ | `v15_signal.py:calc_tema()` |
| GoldenCross | EMA50/EMA200 | 长期趋势启动 | 三屏回测验证 ¹ | `v15_signal.py:calc_golden_cross()` |
| EMA_Align | 20/50/200 | 均线排列对齐 | 三屏回测验证 ¹ | `v15_signal.py:calc_ema_align()` |

> ¹ Vortex/TEMA/GoldenCross/EMA_Align 来自三屏趋势系统回测验证的指标

### 9.2 指标计算说明

**RSI**：使用 14 周期，计算最近 14 根K线的涨跌幅比率。

**Fibonacci**：取最近 30 根K线的最高点和最低点，计算 38.2%/50%/61.8% 回调位。

**布林带**：20 周期 SMA ± 2 倍标准差。额外计算：
- `bandwidth`：带宽百分比 = 2 × 2σ / SMA × 100
- `pct_b`：价格在带内的位置 = (price - lower) / (upper - lower)

**MACD**：
- MACD 线 = EMA(12) - EMA(26)
- 信号线 = EMA(MACD, 9)
- 柱状图 = MACD - 信号
- 判定 `expanding`：|hist[-1]| > |hist[-2]|（柱状图扩张）
- 判定 `cross`：hist 穿越零轴（金叉/死叉）

**ADX**：
- 使用 Wilder 平滑法
- +DI / -DI 方向指标
- ADX > 25 = 强趋势，> 40 = 极强趋势

**Pivot Points（枢纽点）**：
- 经典枢纽点计算：Pivot = (H + L + C) / 3
- 支撑位 S1/S2/S3，阻力位 R1/R2/R3
- `support_zone`：价格在 S1~Pivot 区间
- `near_s1`：价格距S1在1%以内

**OBV（能量潮指标）**：
- 价格上涨时累加成交量，下跌时累减
- 10期MA判断趋势方向（BULL/BEAR）
- `accelerating`：量能加速（连续两期OBV增量递增）

**SuperTrend（超级趋势线）**：
- 基于ATR的中轨 ± 3×ATR通道
- 价格在下轨上方 = BULL趋势
- `reversal`：趋势方向发生反转

**Keltner Channel（肯特纳通道）**：
- EMA中轨 ± 2×ATR通道
- `near_lower`：位置<0.2（接近下沿）
- `near_middle`：位置0.4~0.6（接近中线）
- `position`：价格在通道内的相对位置(0~1)

**StochRSI（随机RSI）**：
- 对RSI值再取随机指标：FastK(3) / FastD(3)
- K<20 = 超卖，K>80 = 超买
- `cross=golden`：K线上穿D线（金叉）

**Vortex（涡旋指标）** ¹：
- VI+/VI- 两条方向线，VI+>VI- 为多头方向
- `reversal`：方向从BEAR翻转为BULL（趋势反转信号）
- 需要 high/low 数据

**TEMA（三重指数移动平均）** ¹：
- TEMA = 3×EMA1 - 3×EMA2 + EMA3
- `bullish`：TEMA > 当前价（均线在价格下方，支撑趋势）
- `slope`：TEMA斜率百分比，>0 为上升趋势

**GoldenCross（金叉）** ¹：
- EMA50 与 EMA200 的交叉
- `cross=golden`：EMA50 上穿 EMA200（长期趋势启动信号）
- `distance_pct`：两线间距百分比

**EMA_Align（EMA排列对齐）** ¹：
- EMA20 > EMA50 > EMA200 = 完美多头排列
- `alignment_score`：排列对齐度评分（0~1）
- 三线完全对齐时信号最强

---

## 10. 配置说明

### 10.1 公共配置（.env.common）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| OKX_API_KEY | — | OKX API Key |
| OKX_SECRET_KEY | — | OKX Secret Key |
| OKX_PASSPHRASE | — | OKX Passphrase |
| OKX_BASE_URL | https://www.okx.com | OKX API 基础URL |
| OKX_SIMULATED | false | 是否模拟盘 |
| OKX_DRY_RUN | false | 是否模拟下单（不真实成交） |
| TOTAL_BUDGET | 260 | 总资金（USDT），V15-CT覆盖为100 |
| LEVERAGE | 5.0 | 杠杆倍数（固定5x，不参与优化） |
| MIN_MARGIN_USD | 10 | 最小保证金（美元），V15-CT覆盖为20 |
| MAX_ADDONS_PER_POSITION | 3 | 每仓最大加仓次数 |
| ADDON_PCT | 0.08 | 加仓比例基准（8%） |
| BASE_POSITION_PCT | 0.05 | 底仓比例（5%），V15-CT覆盖为0.22 |
| MAX_POSITION_PCT | 0.25 | 单仓最大占比（25%），V15-CT覆盖为0.60 |
| BASE_TP_PCT | 0.04 | 基础止盈（4%，固定不优化） |

### 10.2 策略专属配置（.env.v15）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| STRATEGY_ID | v15 | 策略标识 |
| V15_MODE | auto | 运行模式 |
| V15_AUTO_EXECUTE | true | 是否自动执行交易 |
| V15_COINS | BTC,ETH,SOL,... | 监控币种列表（34个） |
| MAX_CONCURRENT_POSITIONS | 4 | 最大并发持仓数（V15-CT覆盖为6） |
| V15_TAKE_PROFIT_PCT | 0.04 | 基础止盈比例（4%） |
| V15_POLL_INTERVAL | 3600 | 轮询间隔（秒） |
| V15_DAILY_LOSS_LIMIT | -50 | 日亏损限制（USDT） |
| V15_MAX_CONSECUTIVE_LOSSES | 5 | 最大连续亏损次数（代码在3次时触发资金管理引擎） |
| V15_LOG_LEVEL | INFO | 日志级别 |
| V15_VOL_MULT | 1.875 | 波动率倍数 |
| V15_MIN_VOL_MULT | 0.3 | 最小波动率倍数 |
| V15_MAX_VOL_MULT | 4.0 | 最大波动率倍数 |
| V15_RSI_LOW | 30 | RSI低位阈值 |
| V15_RSI_HIGH | 70 | RSI高位阈值 |
| V15_FIB_ZONE | IN_ZONE | Fib区域配置 |
| V15_TREND_CONFIDENCE | 0.5 | 趋势置信度阈值 |
| TREND_FILTER_MODE | none | 三屏趋势过滤模式（V15-CT覆盖为both_bear） |
| TREND_FILTER_PERIOD | 200 | 趋势过滤均线周期（V15-CT覆盖为107） |
| V15_MAX_BASE_HOLDING_HOURS | 48 | 底仓最大持仓时间（小时） |
| V15_MAX_POST_ADDON_HOURS | 24 | 加仓后最大持仓时间（小时） |
| V15_GOLDEN_WINDOW_HOURS | 12 | 加仓黄金窗口时间（小时） |

### 10.3 V15-CT 专属配置（.env.v15ct）

V15-CT 版本在 `experiments/ab-trading/` 目录下运行，配置前缀为 `V15CT_`。以下为当前实盘配置：

| 配置项 | 实盘值 | 说明 |
|--------|--------|------|
| STRATEGY_ID | v15-ct | 策略标识 |
| V15CT_MODE | auto | 运行模式 |
| V15CT_AUTO_EXECUTE | true | 是否自动执行交易 |
| TOTAL_BUDGET | 100 | 总资金（USDT，覆盖公共配置260） |
| BASE_POSITION_PCT | 0.22 | 底仓比例（22%，贝叶斯优化固定值） |
| LEVERAGE | 5.0 | 杠杆倍数（固定5x，不参与优化） |
| MAX_CONCURRENT_POSITIONS | 6 | 最大并发持仓数 |
| MAX_ADDONS_PER_POSITION | 3 | 每仓最大加仓次数 |
| ADDON1_PCT | 0.05 | 加仓1比例（5%，黑天鹅第一档） |
| ADDON2_PCT | 0.25 | 加仓2比例（25%，黑天鹅第二档） |
| ADDON3_PCT | 0.10 | 加仓3比例（10%，黑天鹅第三档） |
| MAX_POSITION_PCT | 0.60 | 单仓最大占比（60%） |
| MIN_MARGIN_USD | 20 | 最小保证金（美元） |
| TREND_FILTER_MODE | both_bear | 三屏趋势过滤（周线+日线都看空时禁止做多） |
| TREND_FILTER_PERIOD | 107 | 趋势过滤均线周期（约5个月均线） |
| V15CT_COINS | BTC,ETH,SOL,... | 监控币种列表（34个） |
| V15CT_VOL_MULT | 1.875 | 波动率倍数 |
| V15CT_MIN_VOL_MULT | 0.3 | 最小波动率倍数 |
| V15CT_MAX_VOL_MULT | 4.0 | 最大波动率倍数 |
| V15CT_RSI_LOW | 30 | RSI低位阈值 |
| V15CT_RSI_HIGH | 70 | RSI高位阈值 |
| V15CT_FIB_ZONE | IN_ZONE | Fib区域配置 |
| V15CT_TREND_CONFIDENCE | 0.5 | 趋势置信度阈值 |
| V15CT_CONFIDENCE_THRESHOLD | 30 | 入场置信度阈值（测试模式较低） |
| V15CT_TEST_MODE | true | 测试模式（降低入场标准用于系统验证） |
| BASE_TP_PCT | 0.04 | 基础止盈比例（4%，BTC基准，其他币种按波动率放大） |
| BASE_ADDON_PCT | 0.08 | 基础加仓间距（8%，按波动率放大） |
| V15CT_POLL_INTERVAL | 3600 | 轮询间隔（秒） |
| V15CT_DAILY_LOSS_LIMIT | -50 | 日亏损限制（USDT） |
| V15CT_MAX_CONSECUTIVE_LOSSES | 5 | 最大连续亏损次数（代码在3次时触发资金管理引擎） |
| V15CT_LOG_LEVEL | INFO | 日志级别 |

> **连续亏损触发机制：** 虽然配置中 `V15CT_MAX_CONSECUTIVE_LOSSES=5`，但代码实际在连续亏损 **3次** 时即异步触发资金管理引擎（`capital_manager_engine.py monthly`）重新优化参数。止盈时重置计数器。

### 10.4 配置加载机制

配置文件支持 `include` 语法，加载顺序：

```
config_loader.load_config("v15")
  ├─ 读取 .env.common
  └─ 读取 .env.v15（覆盖同名配置）
```

---

## 11. API 接口

### 11.1 信号决策

```python
from v15_signal import v15_decision

# 获取BTC信号
result = v15_decision("BTC-USDT")

# 指定当前价格和时间周期
result = v15_decision("BTC-USDT", price=67000, timeframe="4H", limit=200)

# 返回值结构（V15独立版，7层入场 + 6项指标）
{
    "action": "OPEN_BULL",      # OPEN_BULL / WAIT
    "confidence": 75,           # 置信度 0-100
    "reasons": ["..."],         # 决策理由列表
    "mode": "v15",             # 策略标识
    "vol_mult": 1.2,           # 波动率倍数
    "position": "ABOVE_ALL",   # 价格位置
    "fib_zone": "golden",      # Fib区域: golden / shallow / None
    "trend_signal": None,      # 趋势信号: macd_bull / adx_bull / None
    "boll_signal": "near_mid", # 布林信号: touch_lower / near_mid / rsi_extreme / None
    "rsi": 42.5,               # RSI值
    "smas": {30: ..., 65: ..., 128: ..., 200: ...},
    "fib": {swing_high, swing_low, f382, f500, f618},
    "boll": {sma, upper, lower, std, bandwidth, pct_b},
    "macd": {macd, signal, hist, hist_prev, cross, expanding, bullish, bearish},
    "adx": {adx, strong, very_strong, di_plus, di_minus},
}

# V15-CT 完整版返回值（16层入场 + 16项指标，mode="v15_ct"）
# 额外包含以下字段：
{
    ...  # 同上字段
    "mode": "v15_ct",
    "trend_signal": "goldencross_bull",  # 新增: pivot_support/obv_bull/supertrend_bull/
                                          #      keltner_bull/stochrsi_bull/vortex_bull/
                                          #      tema_bull/goldencross_bull/ema_align_bull
    "pivot": {pivot, r1, r2, r3, s1, s2, s3, support_zone, resistance_zone, near_s1, near_pivot, near_r1},
    "obv": {obv, obv_ma, trend, bullish, accelerating, divergence},
    "supertrend": {upper_band, lower_band, trend, bullish, reversal, atr, distance_pct},
    "keltner": {upper, middle, lower, position, near_lower, near_middle, near_upper, bandwidth},
    "stochrsi": {k, d, cross, oversold, overbought, bullish},
    "vortex": {vi_plus, vi_minus, direction, bullish, reversal, strength},
    "tema": {tema, direction, bullish, slope, distance_pct},
    "golden_cross": {ema_fast, ema_slow, cross, direction, bullish, distance_pct},
    "ema_align": {emas, direction, bullish, aligned, alignment_score},
}
```

### 11.2 资金管理（V15 独立版）

```python
from capital_manager import (
    calculate_capital_allocation,  # 资金分配
    get_signal_trigger_status,     # 信号触发状态
    calculate_single_position_cost # 单仓位成本
)
```

### 11.3 资金管理引擎（V15 独立系统）

```python
from capital_manager_engine import CapitalManagerEngine

# 初始化引擎
engine = CapitalManagerEngine()

# 运行月度优化（回测+趋势过滤+贝叶斯优化+资金分配）
engine.run_monthly()

# 运行回测
backtest_result = engine.run_backtest()

# 检查单个币种趋势过滤
trend_status = engine.check_trend("BTC")
# 返回: {blocked: bool, mode: "both_bear", weekly_ma104: float, daily_ma104: float}

# 批量检查趋势过滤
trend_batch = engine.check_trend_batch()

# 运行贝叶斯优化
opt_result = engine.run_optimization()

# 检查开仓许可（资金+趋势双重检查）
permission = engine.check_open_permission("BTC")

# 获取引擎状态
status = engine.get_status()
```

**HTTP API（端口8770）：**

```
GET  /api/status             # 引擎状态
GET  /api/trend/:coin        # 查询币种趋势过滤状态
POST /api/optimize           # 触发优化
```

### 11.4 策略参数

```python
from strategy_params import (
    calc_daily_ma200,           # 日线MA200
    calc_30d_volatility,        # 30天波动率
    get_vol_adjusted_params,    # 波动率调整后的参数
    get_all_coins_params,       # 全币种参数
    check_trend_filter,         # 三屏趋势过滤（V15-CT新增）
)
```

> Elder-ray 趋势强度计算器位于 `screen_engine.py`（三屏趋势系统共享模块）。

**趋势过滤示例：**

```python
from strategy_params import check_trend_filter
from market_data import fetch_candles

# 获取K线数据
daily_klines = fetch_candles("BTC-USDT", bar="1D", limit=200)
weekly_klines = fetch_candles("BTC-USDT", bar="1W", limit=200)
current_price = 67000.0

# 检查BTC趋势过滤状态
result = check_trend_filter(current_price, daily_klines, weekly_klines)
# 返回:
# {
#     "blocked": False,          # 是否禁止开多
#     "mode": "both_bear",       # 过滤模式
#     "period": 107,             # 均线周期
#     "weekly_ma": 87830.0,      # 周线MA值
#     "daily_ma": 70658.0,       # 日线MA值
#     "weekly_bear": False,      # 周线是否看空
#     "daily_bear": False,       # 日线是否看空
#     "reason": "趋势正常",      # 原因说明
# }
```

### 11.5 市场数据

```python
from market_data import (
    fetch_candles,  # K线获取
    calc_sma,       # SMA
    calc_ema,       # EMA
    calc_rsi,       # RSI
)
```

---

## 12. 测试

### 12.1 测试套件

**V15 独立系统（14-V15经典马丁策略/tests/）：**

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| test_v15_system.py | 19项 | SMA/位置判定/布林带/MACD/ADX/RSI/16层信号/vol_mult一致性/空数据/零价保护/极端波动/1000次随机 |
| test_v15_stress.py | 25项 | BELOW_ALL/ABOVE_ALL/IN_ZONE全分支/边界条件/异常数据/布林带/500次随机 |
| test_multi_scenario.py | 89项 | 7大模块40+场景：Elder-ray/资金管理/入场信号/动态止损/持仓超时/贝叶斯优化/边界异常 |
| test_symbol_mapper.py | — | 币种映射测试 |
| v15_stress_test.py | 8项 | 全币种信号/100U-200U-500U资金规模/多持仓/信号触发/加仓预留/API响应 |

### 12.2 运行测试

```bash
# V15 独立系统 — 运行全部测试
cd 14-V15经典马丁策略
python3 run.py test

# V15 独立系统 — 单独运行某个测试
python3 tests/test_v15_system.py
python3 tests/test_v15_stress.py
python3 tests/test_multi_scenario.py
python3 tests/test_symbol_mapper.py
python3 tests/v15_stress_test.py
```

### 12.3 测试中的 Mock

测试使用合成K线数据，不依赖网络请求：

```python
# Mock fetch_candles 返回合成数据
def mock_candles(candles):
    import market_data
    import v15_signal
    original_md = market_data.fetch_candles
    original_vs = v15_signal.fetch_candles
    def _fake(inst_id, bar="4H", limit=200):
        return candles
    market_data.fetch_candles = _fake
    v15_signal.fetch_candles = _fake
    return (original_md, original_vs)
```

---

## 13. 风控规则

V15 经典马丁策略采用 **五层风控架构**：入场风控 → 持仓风控 → 趋势风控 → 资金风控 → 系统风控。

### 13.1 入场风控

| 规则 | 说明 |
|------|------|
| 置信度 ≥ 60 | 低于60分的信号不入场 |
| 资金充足检查 | 可用资金 ≥ 单仓位总需求 × 2 才允许开新仓 |
| 止损未触发 | 不在 BELOW_ALL_MA_CONFIRMED 状态 |
| 最小下单量 | 下单数量 ≥ 最小合约单位 |
| 三屏趋势过滤 | both_bear模式下，周线+日线MA104都看空时禁止开多 |

### 13.2 持仓风控

| 规则 | 说明 |
|------|------|
| 最大加仓3次 | 每仓最多加仓3次（共4层） |
| 最大并发6仓 | 贝叶斯优化可调整（默认4，范围2-8） |
| MA200动态止损 | 收盘价跌破日线/周线MA200/EMA200触发止损（仅使用日线/周线均线，不使用4H均线） |
| 持仓超时离场 | 底仓超48H、加仓后超24H触发经典离场系统评估（CLOSE/REDUCE/RAISE_TP/HOLD） |

### 13.3 趋势风控

| 规则 | 说明 |
|------|------|
| 三屏趋势过滤器 | 周线MA104 + 日线MA104 双周期趋势一致性检查 |
| both_bear禁止开多 | 周线和日线都看空（价格 < MA104）时，禁止新开多仓 |
| 实时价格判断 | 与MA200止损不同，趋势过滤器使用实时价格判断趋势方向 |
| MA104周期选择 | 约5个月均线，既能过滤大熊市，又不会过度过滤 |

> **趋势过滤 vs 动态止损的区别：**
> - MA200动态止损：保护已有持仓，收盘价跌破触发止损
> - 三屏趋势过滤器：控制新开仓，实时价格判断趋势方向

### 13.4 资金风控

| 规则 | 说明 |
|------|------|
| 日亏损限制 | 单日亏损超过 50 USDT 暂停交易 |
| 连续亏损3次触发 | 连续亏损3次异步触发资金管理引擎重新优化参数（`capital_manager_engine.py monthly`） |
| 最小保证金 | 保证金低于 10 USDT 不开新仓 |
| 单仓最大占比 | 25%（代码默认），贝叶斯优化可调整 |

### 13.5 系统风控

```
正常状态（回撤 < 15%）
    │
    ├─ 回撤 15-20% → 警告状态：暂停加仓，仅执行止损
    │
    └─ 回撤 ≥ 20% → 强制止损：全部平仓，等待下次机会
```

**连续亏损触发流程：**

```
止盈平仓 → consecutive_losses = 0（重置）
止损平仓 → consecutive_losses += 1
    │
    └─ consecutive_losses >= 3
        → 异步启动 capital_manager_engine.py monthly
        → 重置 consecutive_losses = 0
        → 记录 last_capital_rebuild 时间戳
```

---

## 设计理念

1. **不轻易出手** — 高确认度才入场，宁可错过不可做错
2. **方向判断优先** — 马丁策略的生命线是方向判断正确
3. **波动率自适应** — 参数随品种波动率动态调整
4. **五层风控** — 入场风控 + 持仓风控 + 趋势风控 + 资金风控 + 系统风控
5. **只做多** — 避免做空马丁的高风险，专注多头回调入场
6. **多指标覆盖** — 16项技术指标提供16层入场决策，满足任一条件即可开仓，提高信号覆盖率
7. **均线用途分离** — 4H均线用于位置判定（决定是否入场），日线/周线均线用于止损（决定何时退出），MA104用于趋势过滤（决定是否允许开仓）
8. **智能资金管理** — 贝叶斯优化参数 + Elder-ray趋势强度 + 连续亏损3次自动触发重新优化
