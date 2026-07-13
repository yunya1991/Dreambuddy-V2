# 技术设计文档 — V15 经典马丁策略

> **定位：** 模块级技术设计文档，描述架构、数据流、算法细节
> **版本：** v4.0 | **更新：** 2026-07-12
> **系统：** V15 经典马丁策略（8大核心模块 + 16项指标 + 智能资金管理）

---

## 目录

- [1. 系统架构](#1-系统架构)
  - [1.1 八大核心模块](#11-八大核心模块)
  - [1.2 三层架构](#12-三层架构)
  - [1.3 设计原则](#13-设计原则)
- [2. 数据流](#2-数据流)
- [3. 信号引擎算法](#3-信号引擎算法)
- [4. 交易执行引擎](#4-交易执行引擎)
- [5. 止损系统设计](#5-止损系统设计)
- [6. 资金管理引擎](#6-资金管理引擎)
  - [6.1 智能资金分配](#61-智能资金分配elder-ray--置信度--波动率)
  - [6.2 Elder-ray 趋势强度检测](#62-elder-ray-趋势强度检测)
  - [6.3 持仓超时与离场系统切换](#63-持仓超时与离场系统切换)
  - [6.4 贝叶斯参数优化](#64-贝叶斯参数优化)
  - [6.5 资金管理引擎（整体模块）](#65-资金管理引擎整体模块)
- [7. 回测引擎](#7-回测引擎)
- [8. 风控体系](#8-风控体系)

---

## 1. 系统架构

### 1.1 八大核心模块

V15 经典马丁策略由 8 大核心模块构成，形成完整的交易决策闭环：

```
┌───────────────────────────────────────────────────────────────────┐
│                        入场信号系统                                │
│  16层入场决策 + 16项技术指标 + 4H均线位置判定                      │
└─────────────┬─────────────────────────────────────────────────────┘
              │
┌─────────────▼─────────────┐  ┌──────────────────────────────────┐
│       参数设置模块         │  │       趋势强度计算器              │
│  BTC固定参数 + 波动率放大   │  │  Elder-ray三重滤网（日线）        │
│  止盈/加仓间距/止损自适应   │  │  EMA斜率 + Bull/Bear + 背离      │
└─────────────┬─────────────┘  └──────────────┬───────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              │
                    ┌─────────▼─────────┐
                    │    资金管理器      │
                    │ 智能资金分配引擎   │
                    │ Elder×置信×波动   │
                    │ 3次加仓预算分配    │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │    动态止损系统    │
                    │ 日/周线 MA200 族   │
                    │ 收盘价确认触发     │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  三屏趋势过滤器    │
                    │ 周线+日线MA104     │
                    │ both_bear禁止开多  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │ 持仓超时与离场系统 │
                    │  分层计时（底仓/加仓）│
                    │  → 经典离场系统切换 │
                    │  CLOSE/REDUCE/RAISE_TP/HOLD │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │ 贝叶斯参数优化系统 │
                    │  8参数寻优          │
                    │  最大化卡尔马比率   │
                    └───────────────────┘
```

| 模块 | 核心职责 | 关键输出 | 所在文件 |
|------|----------|----------|----------|
| 入场信号系统 | 16层入场决策，16项技术指标计算，4H均线位置判定 | OPEN_BULL / WAIT + 置信度 | `core/v15_signal.py` |
| 参数设置 | BTC固定参数基准，其他币种按30日波动率放大 | 止盈比例、加仓间距、止损参数 | `lib/strategy_params.py` |
| 趋势强度计算器 | Elder-ray三重滤网系统，日线级别趋势强度评估 | direction + strength(0-100) + 多空信号 | `lib/strategy_params.py` |
| 资金管理器 | 基于趋势强度+置信度+波动率的智能资金分配 | per_coin_budget + 3次加仓分配 | `lib/capital_manager.py` |
| 动态止损 | 日线/周线 MA200+EMA200 四条均线止损 | 止损线价格 + 是否触发 | `lib/strategy_params.py` |
| 三屏趋势过滤器 | 周线+日线MA104趋势一致性检查，both_bear时禁止开多 | trend_filter状态 | `lib/strategy_params.py` |
| 持仓超时与离场 | 分层计时，超时后切换经典离场系统 | CLOSE/REDUCE/RAISE_TP/HOLD | `core/v15_trader.py` |
| 贝叶斯参数优化 | 8参数寻优，每月自动优化配置 | 最优参数组合 + 回测绩效 | `lib/bayesian_optimizer.py` |

### 1.2 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    入口层 (run.py)                           │
│   signal │ backtest │ trader │ capital │ test │ config      │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                   核心层 (core/)                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ v15_signal   │  │ v15_trader   │  │ v15_backtest │       │
│  │ 信号引擎     │  │ 交易执行器   │  │ 回测引擎     │       │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘       │
└─────────┼─────────────────┼─────────────────────────────────┘
          │                 │
┌─────────┴─────────────────┴─────────────────────────────────┐
│                   工具层 (lib/)                              │
│  ┌────────────┐ ┌───────────┐ ┌────────────┐ ┌───────────┐  │
│  │market_data │ │okx_client │ │strategy_   │ │capital_   │  │
│  │K线+指标    │ │交易客户端 │ │params      │ │manager    │  │
│  │            │ │           │ │止损+波动率 │ │资金+风控  │  │
│  └─────┬──────┘ └───────────┘ └────────────┘ └───────────┘  │
│        │                                                     │
│  ┌─────┴──────┐                                              │
│  │config_loader│                                             │
│  │配置加载器   │                                              │
│  └────────────┘                                              │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 设计原则

1. **信号与执行分离** — `v15_signal.py` 只负责计算信号，`v15_trader.py` 负责执行交易，职责清晰
2. **波动率自适应** — 所有关键参数（止盈、加仓间距、止损）根据币种波动率动态调整
3. **只做多** — 信号引擎不产生做空信号，交易器不执行做空操作
4. **状态持久化** — 持仓状态写入 JSON 文件，进程重启不丢失
5. **多层风控** — 入场风控 + 持仓风控 + 资金风控 + 止损风控 四层防护

---

## 2. 数据流

### 2.1 信号决策流

```
v15_decision("BTC-USDT")
  │
  ├─→ fetch_candles("BTC-USDT", "4H", 200)   ← OKX API / CLI 降级
  │     返回: [{ts, o, h, l, c, v}, ...]
  │
  ├─→ prices = [float(c["c"]) for c in candles]
  │     highs  = [float(c["h"]) for c in candles]
  │     lows   = [float(c["l"]) for c in candles]
  │     volumes = [float(c["v"]) for c in candles]
  │
  ├─→ 计算指标（并行无依赖）—— 共16项
  │     ├─ calc_sma(prices, 30/65/128/200)  → 4条均线
  │     ├─ calc_rsi(prices, 14)             → RSI值
  │     ├─ calc_fibonacci(prices, 30)       → Fib回调位
  │     ├─ calc_bollinger_bands(prices, 20) → 布林带
  │     ├─ calc_macd(prices)                → MACD
  │     ├─ calc_adx(prices, 14)             → ADX/DI
  │     ├─ calc_pivot_points(highs, lows, closes, period=1)  → 枢纽点指标
  │     ├─ calc_obv(prices, volumes)                         → OBV量能指标
  │     ├─ calc_supertrend(prices, period=10, multiplier=3.0) → SuperTrend趋势指标
  │     ├─ calc_keltner_channel(prices, period=20, multiplier=2.0) → Keltner Channel波动率指标
  │     ├─ calc_stochrsi(prices, period=14, fastk=3, fastd=3) → StochRSI动量指标
  │     ├─ calc_vortex(highs, lows, prices, period=14)       → Vortex趋势反转指标
  │     ├─ calc_tema(prices, period=30)                      → TEMA三重指数移动平均
  │     ├─ calc_golden_cross(prices, fast_period=50, slow_period=200) → GoldenCross金叉/死叉
  │     └─ calc_ema_align(prices, periods=[20, 50, 200])     → EMA排列指标
  │
  ├─→ determine_position(price, smas)        → ABOVE_ALL / IN_ZONE / BELOW_ALL
  │
  ├─→ 按位置进入决策分支
  │     ├─ ABOVE_ALL → 16层入场决策（Tier 1-16）
  │     ├─ IN_ZONE   → 均值回归（含新指标入场条件）
  │     └─ BELOW_ALL → 等待（只做多）
  │
  ├─→ 计算 vol_mult（波动率倍数）
  │
  └─→ 返回决策结果 dict
        {action, confidence, reasons, mode, vol_mult, position,
         fib_zone, trend_signal, boll_signal, rsi, smas, fib,
         boll, macd, adx, pivot, obv, supertrend, keltner,
         stochrsi, vortex, tema, golden_cross, ema_align}
```

### 2.2 交易执行流

```
run_poll_cycle()  ← 每 POLL_INTERVAL 秒触发一次
  │
  ├─→ load_state()  ← 从 data/v15_state.json 加载持仓状态
  ├─→ _get_okx_client()  ← 初始化 OKX 客户端
  │
  ══ 阶段1：处理已有持仓 ══
  │
  FOR each coin in COINS (已有持仓):
  │
  ├─→ check_take_profit(client, coin, pos, state)
  │     ├─ 盈利 ≥ tp_pct → 止盈平仓（sell/long）
  │     ├─ 止损触发     → 止损平仓（sell/long）
  │     └─ 均未触发     → execute_addon(client, coin, pos, state)
  │                       ├─ 跌幅 ≥ 门槛 → 加仓（buy/long）
  │                       └─ 跌幅不足     → 跳过
  │
  ══ 阶段2：信号收集排序开仓 ══
  │
  ├─→ 收集所有无持仓币种的信号
  │     FOR each coin in COINS (无持仓):
  │       decision = get_v15_decision(coin)
  │       if action == OPEN_BULL 且 conf >= 60:
  │         candidates.append((coin, decision, confidence))
  │
  ├─→ 按 confidence 降序排序
  │
  ├─→ 逐个开仓（资金允许范围内）
  │     FOR each (coin, decision, conf) in sorted_candidates:
  │       check_capital()
  │       ├─ 资金不足 → 跳过
  │       └─ 资金充足 → execute_open_position(client, coin, decision, state)
  │                     ├─ 止损触发 → 禁止开多
  │                     ├─ 趋势过滤触发（both_bear）→ 禁止开多
  │                     ├─ 下单量 < 最小单位 → 跳过
  │                     └─ 执行下单（buy/long）
  │
  └─→ save_state(state)  ← 持久化到 data/v15_state.json
```

### 2.3 状态机

```
                    ┌──────────┐
          ┌────────→│  WAIT    │←────────┐
          │         └────┬─────┘         │
          │              │               │
          │   signal=OPEN_BULL          止盈/止损
          │   conf≥60                   平仓
          │              │               │
          │         ┌────▼─────┐         │
          │         │ OPEN(LONG)│─────────┘
          │         └────┬─────┘
          │              │
          │     跌幅≥8%×vol×(N+1)
          │              │
          │         ┌────▼─────┐
          │         | ADDON #1  │
          │         └────┬─────┘
          │              │
          │     跌幅≥16%×vol
          │              │
          │         ┌────▼─────┐
          │         | ADDON #2  │
          │         └────┬─────┘
          │              │
          │     跌幅≥24%×vol
          │              │
          │         ┌────▼─────┐
          │         | ADDON #3  │
          │         └────┬─────┘
          │              │
          │     止盈或止损触发
          │              │
          └──────────────┘
```

---

## 3. 信号引擎算法

### 3.1 技术指标计算

#### SMA（简单移动平均）

```python
calc_sma(values, period):
    return sum(values[-period:]) / period
```
- 输入：收盘价列表 + 周期
- 输出：最近 N 周期的均值，数据不足返回 None

#### RSI（相对强弱指数）

```python
calc_rsi(prices, period=14):
    deltas = 价格差分序列
    gains = max(d, 0)  最近14个
    losses = max(-d, 0) 最近14个
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)
```
- 输入不足时返回 50.0（中性）
- avg_loss=0 时返回 100.0（超强）

#### Fibonacci 回调位

```python
calc_fibonacci(prices, lookback=30):
    swing_high = max(prices[-30:])
    swing_low = min(prices[-30:])
    range = swing_high - swing_low
    f382 = swing_high - 0.382 * range   # 浅回调
    f500 = swing_high - 0.500 * range   # 中回调
    f618 = swing_high - 0.618 * range   # 深回调
```

#### 布林带

```python
calc_bollinger_bands(prices, period=20, num_std=2):
    sma = SMA(prices, 20)
    std = 标准差(prices[-20:])
    upper = sma + 2 * std
    lower = sma - 2 * std
    bandwidth = 4 * std / sma * 100
    pct_b = (price - lower) / (upper - lower)
```

#### MACD

```python
calc_macd(prices, fast=12, slow=26, signal=9):
    macd_line = EMA(12) - EMA(26)
    signal_line = EMA(macd_line, 9)
    hist = macd_line - signal_line
    expanding = |hist[-1]| > |hist[-2]|  # 柱状图扩张
    cross = hist穿越零轴               # 金叉/死叉
```

#### ADX（Wilder 平滑法）

```python
calc_adx(prices, period=14):
    +DM = 高点上穿
    -DM = 低点下穿
    TR = 真实波幅
    Wilder平滑(+DM, -DM, TR)
    +DI = 100 * 平滑+DM / 平滑TR
    -DI = 100 * 平滑-DM / 平滑TR
    DX = 100 * |+DI - -DI| / (+DI + -DI)
    ADX = SMA(DX, 14)
    strong = ADX > 25
    very_strong = ADX > 40
```

#### Pivot Points（枢纽点指标）

```python
calc_pivot_points(highs, lows, closes, period=1):
    # 使用最近 period 根K线的最高/最低/收盘价
    H = max(highs[-period:])
    L = min(lows[-period:])
    C = closes[-1]
    pivot = (H + L + C) / 3
    s1 = 2 * pivot - H        # 第一支撑位
    s2 = pivot - (H - L)      # 第二支撑位
    r1 = 2 * pivot - L        # 第一阻力位
    r2 = pivot + (H - L)      # 第二阻力位
```
- 输入：最高价/最低价/收盘价列表 + 周期
- 输出：pivot中心位、S1/S2支撑位、R1/R2阻力位

#### OBV（On-Balance Volume 量能指标）

```python
calc_obv(prices, volumes):
    obv = [0]
    for i in range(1, len(prices)):
        if prices[i] > prices[i-1]:
            obv.append(obv[-1] + volumes[i])     # 价涨加量
        elif prices[i] < prices[i-1]:
            obv.append(obv[-1] - volumes[i])     # 价跌减量
        else:
            obv.append(obv[-1])                   # 平盘不动
    obv_sma = SMA(obv, 20)                        # OBV均线用于趋势判断
    bullish = obv[-1] > obv_sma                   # 多头趋势
    accelerating = obv[-1] - obv[-5] > obv[-5] - obv[-10]  # 量能加速
```
- 输入：收盘价 + 成交量列表
- 输出：OBV序列、多头趋势标志、量能加速标志

#### SuperTrend（趋势指标）

```python
calc_supertrend(prices, period=10, multiplier=3.0):
    atr = calc_atr(prices, period)               # 平均真实波幅
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr           # 上轨
    lower_band = hl2 - multiplier * atr           # 下轨
    # 趋势跟踪：价格突破上轨→多头，跌破下轨→空头
    bullish = price > super_trend_line
```
- 输入：收盘价列表 + ATR周期 + 乘数
- 输出：SuperTrend线、多头/空头标志

#### Keltner Channel（波动率指标）

```python
calc_keltner_channel(prices, period=20, multiplier=2.0):
    ema = EMA(prices, period)                     # 中轨EMA
    atr = calc_atr(prices, period)                # ATR
    upper = ema + multiplier * atr                # 上轨
    lower = ema - multiplier * atr                # 下轨
    near_lower = price <= lower                   # 触及下沿
    near_mid = |price - ema| / ema < 0.01         # 接近中线
```
- 输入：收盘价列表 + EMA周期 + ATR乘数
- 输出：上轨/中轨/下轨、触及下沿/中线标志

#### StochRSI（动量指标）

```python
calc_stochrsi(prices, period=14, fastk=3, fastd=3):
    rsi = calc_rsi(prices, period)                # 先算RSI
    stoch_rsi = (rsi - min(rsi)) / (max(rsi) - min(rsi))  # RSI的随机化
    k = SMA(stoch_rsi, fastk)                     # K线
    d = SMA(k, fastd)                             # D线
    golden_cross = k[-1] > d[-1] and k[-2] <= d[-2]  # 金叉
    oversold = k[-1] < 20                         # 超卖区
```
- 输入：收盘价列表 + RSI周期 + K/D平滑周期
- 输出：K值/D值、金叉标志、超卖标志

#### Vortex（趋势反转指标）

```python
calc_vortex(highs, lows, prices, period=14):
    vm_plus = |high[-i] - low[-i-1]|             # 正向运动
    vm_minus = |low[-i] - high[-i-1]|            # 负向运动
    tr = true_range                               # 真实波幅
    vi_plus = SMA(vm_plus, period) / SMA(tr, period)   # +VI
    vi_minus = SMA(vm_minus, period) / SMA(tr, period)  # -VI
    bullish_reversal = vi_plus[-1] > vi_minus[-1] and vi_plus[-2] <= vi_minus[-2]  # 多头反转
```
- 输入：最高价/最低价/收盘价列表 + 周期
- 输出：+VI/-VI、多头反转标志

#### TEMA（三重指数移动平均）

```python
calc_tema(prices, period=30):
    ema1 = EMA(prices, period)                    # 一阶EMA
    ema2 = EMA(ema1, period)                      # 二阶EMA
    ema3 = EMA(ema2, period)                      # 三阶EMA
    tema = 3 * ema1 - 3 * ema2 + ema3            # TEMA公式
    slope = (tema[-1] - tema[-5]) / 5             # 斜率
    bullish = slope > 0                           # 多头趋势
```
- 输入：收盘价列表 + 周期
- 输出：TEMA值、斜率、多头趋势标志

#### GoldenCross（金叉/死叉指标）

```python
calc_golden_cross(prices, fast_period=50, slow_period=200):
    ema_fast = EMA(prices, fast_period)           # 快线EMA50
    ema_slow = EMA(prices, slow_period)           # 慢线EMA200
    golden_cross = ema_fast[-1] > ema_slow[-1] and ema_fast[-2] <= ema_slow[-2]  # 金叉
    death_cross = ema_fast[-1] < ema_slow[-1] and ema_fast[-2] >= ema_slow[-2]  # 死叉
    bullish_align = ema_fast[-1] > ema_slow[-1]   # 快线在慢线上方
```
- 输入：收盘价列表 + 快线/慢线周期
- 输出：金叉/死叉标志、多头排列标志

#### EMA Align（EMA排列指标）

```python
calc_ema_align(prices, periods=[20, 50, 200]):
    emas = {p: EMA(prices, p) for p in periods}  # 计算多条EMA
    bullish_align = emas[20][-1] > emas[50][-1] > emas[200][-1]  # 完美多头排列
    bearish_align = emas[20][-1] < emas[50][-1] < emas[200][-1]  # 完美空头排列
```
- 输入：收盘价列表 + EMA周期列表
- 输出：多头/空头排列标志

### 3.2 位置判定

```python
determine_position(price, smas):
    valid = {k: v for k, v in smas.items() if v is not None}
    if all(price > v for v in valid.values()):
        return 'ABOVE_ALL'    # 价格在所有均线之上
    if all(price < v for v in valid.values()):
        return 'BELOW_ALL'    # 价格在所有均线之下
    return 'IN_ZONE'          # 价格在均线之间
```

### 3.3 ABOVE_ALL 十六层入场决策

按 elif 链式优先级判断，命中即停：

```
前置计算：
  in_fib_zone = f618 ≤ price ≤ f382
  in_golden = price ≤ f500（黄金区）
  boll_near_mid = |price - boll_sma| / boll_sma < 0.02
  boll_at_lower = price ≤ boll_lower

── Tier 1-7：原始6指标入场 ──

Tier 1: in_golden + RSI<55 + (boll_near_mid 或 boll_at_lower)
        → confidence=80, size_mult=1.0, 双重确认

Tier 2: in_golden + RSI<55
        → confidence=75, size_mult=1.0, Fib黄金区

Tier 3: in_fib_zone（非黄金区）+ RSI<55
        → confidence=60, size_mult=0.5, Fib浅区

Tier 4: Fib区外 + boll_near_mid + RSI<50
        → confidence=65, size_mult=0.5, 趋势中继

Tier 5: Fib区外 + RSI<45
        → confidence=60, size_mult=0.5, 多头动能

Tier 6: MACD多头柱扩张 + RSI<55
        → confidence=68, size_mult=0.6, MACD信号

Tier 7: ADX>25 + +DI>-DI + RSI<55
        → confidence=70, size_mult=0.7, ADX强趋势

── Tier 8-16：新增9指标扩展入场 ──

Tier 8: Pivot Points支撑区（price ≤ S1）+ RSI<55（中性）
        → confidence=62, size_mult=0.5, Pivot支撑

Tier 9: OBV多头趋势+量能加速 + RSI<60
        → confidence=66, size_mult=0.6, OBV量能

Tier 10: SuperTrend多头 + RSI<60
         → confidence=64, size_mult=0.5, SuperTrend趋势

Tier 11: Keltner Channel下沿/中线 + RSI<60
         → confidence=61, size_mult=0.5, Keltner波动率

Tier 12: StochRSI金叉/超卖 + RSI<60
         → confidence=63, size_mult=0.5, StochRSI动量

Tier 13: Vortex多头反转 + RSI<65
         → confidence=65, size_mult=0.5, Vortex反转

Tier 14: TEMA多头趋势 + slope>0 + RSI<65
         → confidence=64, size_mult=0.5, TEMA趋势

Tier 15: GoldenCross金叉（EMA50>EMA200）+ RSI<65
         → confidence=72, size_mult=0.7, 金叉信号

Tier 16: EMA排列多头（20>50>200）+ RSI<65
         → confidence=75, size_mult=0.8, EMA完美排列
```

### 3.4 IN_ZONE 均值回归

```
── 原始布林带入场 ──

布林下轨 + RSI<45 → confidence=70, OPEN_BULL
RSI<35             → confidence=65, OPEN_BULL
RSI>65             → 等待（只做多不反手）
布林上轨 + RSI>55  → 等待（不做空）

── 新指标扩展入场 ──

Pivot支撑区（price ≤ S1）+ RSI<50
        → confidence=63, OPEN_BULL, Pivot支撑

OBV多头趋势+量能加速 + RSI<55
        → confidence=65, OPEN_BULL, OBV量能

SuperTrend多头 + RSI<55
        → confidence=62, OPEN_BULL, SuperTrend趋势

Keltner Channel下沿 + RSI<55
        → confidence=60, OPEN_BULL, Keltner波动率

StochRSI金叉/超卖 + RSI<55
        → confidence=63, OPEN_BULL, StochRSI动量

Vortex多头反转 + RSI<60
        → confidence=64, OPEN_BULL, Vortex反转

TEMA多头趋势 + slope>0 + RSI<60
        → confidence=63, OPEN_BULL, TEMA趋势

GoldenCross金叉 + RSI<60
        → confidence=68, OPEN_BULL, 金叉信号

EMA排列多头（20>50>200）+ RSI<60
        → confidence=70, OPEN_BULL, EMA排列

其他               → 等待
```

### 3.5 波动率倍数矩阵

```
Fib黄金区 + 布林触轨  → vol_mult = 1.3  （最强信号）
Fib黄金区（单独）     → vol_mult = 1.2
Fib浅区              → vol_mult = 0.8
ADX强趋势            → vol_mult = 0.9
MACD信号             → vol_mult = 0.8
布林触轨（无Fib）     → vol_mult = 1.0
RSI极端              → vol_mult = 0.7
```

---

## 4. 交易执行引擎

### 4.1 开仓流程

```
execute_open_position(client, coin, decision, state):
  1. 置信度检查: conf < 60 → 拒绝
  2. 资金计算: base_margin = capital_manager.single_position_cost.base_usd
  3. 动态参数: _get_dynamic_params(client, coin, "LONG")
     - 止损触发? → 禁止开多
  4. 下单规模: order_margin = base_margin × vol_mult
              order_notional = order_margin × LEVERAGE
  5. 合约精度: get_contract_info(client, inst_id) → lot_sz, ct_val
  6. 下单数量: sz = calc_lot_sz(notional, price, lot_sz, ct_val)
     - sz < lot_sz → 拒绝（最小单位不足）
  7. 执行下单: side="buy", pos_side="long", td_mode="cross"
  8. 状态记录: entry_price, open_price, sz, addons=0, confidence,
              take_profit_pct, addon_pct, stop_loss_price, vol_mult
```

### 4.2 加仓流程

```
execute_addon(client, coin, pos, state):
  1. 加仓次数: addons >= MAX_ADDONS(3) → 拒绝
  2. 资金检查: alloc.recommendations.allow_addon == False → 拒绝
  3. 跌幅计算:
     open_price = pos.open_price
     target_drop_pct = addon_pct × (addons + 1)
     drop_pct = (open_price - current_price) / open_price
     drop_pct < target_drop_pct → 拒绝（跌幅不足）
  4. 加仓规模: addon_margin = base_margin × vol_mult × addon_pct × (addons + 1)
  5. 执行下单: side="buy", pos_side="long"
  6. 均价更新: entry_price = (旧仓×旧价 + 新仓×新价) / 总仓
  7. 仓位更新: sz += new_sz, addons += 1
```

**加仓门槛递增表（BTC, vol_ratio=1.0）：**

| 加仓次序 | 目标跌幅 | 累计跌幅 | 保证金倍数 |
|----------|----------|----------|------------|
| 第1次 | 8% | 8% | base × vol_mult × 8% |
| 第2次 | 16% | 16% | base × vol_mult × 16% |
| 第3次 | 24% | 24% | base × vol_mult × 24% |

### 4.3 止盈止损流程

```
check_take_profit(client, coin, pos, state):
  1. 计算盈亏: profit_pct = (current_price - entry_price) / entry_price
  2. 止盈判断: profit_pct >= tp_pct
     → 平仓（sell/long）, total_wins += 1, 删除持仓
  3. 止损判断: sl_triggered == True
     → 平仓（sell/long）, 删除持仓
  4. 均未触发: return False（继续持有）
```

---

## 5. 止损系统设计

### 5.1 四均线止损系统

> **重要区分：** 均线系统在 V15-CT 中有两条独立用途：
> - **价格位置判定**：使用4H周期均线（SMA30/65/128/200），由 `determine_position()` 判断 ABOVE_ALL / IN_ZONE / BELOW_ALL
> - **动态止损**：使用日线/周线均线（MA200/EMA200），作为持仓止损参考线

使用日线/周线的 MA200 + EMA200 四条均线作为止损参考：

```
均线系统:
  ├─ 日线 MA200    (calc_daily_ma200)
  ├─ 日线 EMA200   (calc_daily_ema200)
  ├─ 周线 MA200    (calc_weekly_ma200)
  └─ 周线 EMA200   (calc_weekly_ema200)

止损线选择:
  1. 收集所有在价格【下方】的均线
  2. 按距离排序，取【最近】的一条作为止损线
  3. 止损类型 = 该均线的名称（如"日MA200"）

触发条件（关键设计）:
  日线止损 → 看昨收盘价（不是实时价）
  周线止损 → 看上周收盘价（不是实时价）
  → 未收盘的实时价跌破不算触发

特殊情况:
  BELOW_ALL_MA_INTRADAY:
    所有均线实时价全破，但某条均线收盘价仍在上方
    → is_triggered = False（不触发，等收盘确认）

  BELOW_ALL_MA_CONFIRMED:
    所有均线收盘价全破
    → is_triggered = True（无条件止损）
```

### 5.2 止损参数接口

```python
get_dynamic_stop_loss(
    direction="LONG",
    current_price=67000,
    daily_ma200=60000,
    daily_ema200=61000,
    weekly_ma200=55000,
    weekly_ema200=56000,
    last_daily_close=65000,   # 昨收
    last_weekly_close=63000   # 上周收
) → {
    stop_loss_price: 60000,       # 止损线
    stop_loss_pct: 10.45,         # 距当前价百分比
    stop_type: "日MA200",         # 止损类型
    is_triggered: False,          # 是否触发
    above_daily_ma200_close: True, # 昨收在日MA200上方
    above_weekly_ma200_close: True # 上周收在周MA200上方
}
```

### 5.3 三屏趋势过滤器

> **设计思想：** 借用三屏趋势交易系统的周线和日线趋势一致性概念，在马丁策略开仓前进行趋势过滤。
> 当周线和日线趋势同时看空时（both_bear），禁止做多马丁策略，避免在确定性熊市中建仓。

**算法：** 周线MA104 + 日线MA104 双周期趋势一致性检查

```python
check_trend_filter(symbol):
    # 获取周线和日线K线
    weekly_klines = fetch_weekly_klines(symbol, limit=200)
    daily_klines = fetch_daily_klines(symbol, limit=250)
    
    # 计算MA104（约5个月均线）
    weekly_ma104 = SMA(weekly_closes, 104)
    daily_ma104 = SMA(daily_closes, 104)
    
    # 趋势判断
    weekly_bear = current_price < weekly_ma104  # 周线看空
    daily_bear = current_price < daily_ma104    # 日线看空
    
    # both_bear模式：双周期都看空才禁止
    if weekly_bear and daily_bear:
        return {"blocked": True, "mode": "both_bear", 
                 "weekly_ma104": weekly_ma104, "daily_ma104": daily_ma104}
    else:
        return {"blocked": False, "mode": "both_bear",
                 "weekly_ma104": weekly_ma104, "daily_ma104": daily_ma104}
```

**在开仓流程中的作用：**
- 作为开仓许可的第三道检查（置信度 → MA200止损 → 趋势过滤 → 资金管理）
- both_bear 模式下，只有周线+日线同时看空才禁止开多
- MA104周期（约5个月均线）既能过滤大熊市，又不会过度过滤

**与MA200动态止损的区别：**
- MA200动态止损：保护已有持仓，收盘价跌破触发止损
- 三屏趋势过滤器：控制新开仓，实时价格判断趋势方向

---

## 6. 资金管理引擎

### 6.1 智能资金分配（Elder-ray + 置信度 + 波动率）

```
calculate_per_coin_allocation(symbol, confidence, elder_ray):
    1. 最大持仓控制：MAX_CONCURRENT_POSITIONS (默认4)
       remaining_slots = MAX - current_positions
       if remaining_slots <= 0: return allowed=False

    2. 基础预算：per_coin_base = available_budget / remaining_slots

    3. 三维调整因子（combined_mult = 趋势 × 置信 × 波动）：
       a. Elder-ray 趋势强度 (0.3x - 1.5x)
          - EMA上升 + STRONG_BULL:  1.2x-1.5x
          - EMA上升 + BULL_TREND:   1.0x-1.3x
          - EMA下降 + STRONG_BEAR:  0.3x-0.5x
          - 看涨背离 + EMA上升:      ×1.2 加成
          - 多空双弱(both_weakening): ×0.7 降仓

       b. 信号置信度 (0.5x - 1.5x)
          - conf=60% → 0.8x
          - conf=80% → 1.2x
          - conf=100% → 1.5x

       c. 波动率反向调整 (0.5x - 1.5x)
          - BTC (vol_ratio=1.0):  1.0x
          - 高波动 (vol_ratio=2.0):  0.67x
          - 低波动 (vol_ratio=0.5):  1.33x

    4. 边界约束：
       - 上限: 不超过 available_budget × 60% (MAX_POSITION_PCT)
       - 下限: 不低于 MIN_MARGIN_USD / BASE_POSITION_PCT

    5. 资金分配（固定比例，贝叶斯优化可调）：
       - 底仓: 22% (BASE_POSITION_PCT, 用户经验值)
       - 加仓1: 20% (ADDON1_PCT, 黑天鹅第一档)
       - 加仓2: 5% (ADDON2_PCT)
       - 加仓3: 10% (ADDON3_PCT)

    6. 下跌保证金缓冲：drawdown_margin = base_usd × 0.4
       total_with_drawdown = total_needed + drawdown_margin
       若超过可用资金的85%，按比例缩减
```

### 6.2 Elder-ray 趋势强度检测

**算法：** Alexander Elder 三重滤网系统第一重 — 趋势判断

**计算周期：** 日线（1D），使用 250+ 根日线K线计算

> **设计依据：** Elder-ray 指标是三重滤网交易系统的第一重滤网，用于判断大周期趋势方向，
> 日线级别能有效过滤4H及以下周期的噪音，确保马丁策略在趋势正确的方向上建仓。

```python
calc_elder_ray(klines_1d, period=13):
    # 核心计算
    EMA(13) = 市场共识价值（指数移动平均）
    Bull Power = High - EMA(13)   # 买方将价格推升至共识价值之上的能力
    Bear Power = Low - EMA(13)    # 卖方将价格打压至共识价值之下的能力

    # 1. 趋势方向（EMA斜率）— 三重滤网第一重核心
    ema_slope = (EMA[-1] - EMA[-4]) / EMA[-4] × 100
    if ema_slope > 0.01%:  → 上升趋势（只寻找做多机会）
    if ema_slope < -0.01%: → 下降趋势（只寻找做空机会）
    否则 → 震荡趋势

    # 2. 背离检测（20日窗口）— 趋势衰竭信号
    看涨背离（做多信号）:
      价格创最近20日新低 + Bear Power 未创新低 → 做空动能衰竭
    看跌背离（做空信号）:
      价格创最近20日新高 + Bull Power 未创新高 → 做多动能衰竭

    # 3. 力量趋势（柱状图变化）
    Bull_rising:  最近3根Bull Power持续上升 → 买方力量增强
    Bull_falling: 最近3根Bull Power持续下降 → 买方力量减弱
    Bear_rising:  最近3根Bear Power持续上升 → 卖方力量减弱（Bear负值变小）
    Bear_falling: 最近3根Bear Power持续下降 → 卖方力量增强（Bear负值变大）

    # 4. 趋势力度衰竭与逆转判断
    多头失控: Bull Power < 0 → 空头完全凌驾多头之上，上升趋势可能逆转
    空头失控: Bear Power > 0 → 多头完全主控局面，下降趋势可能逆转
    双弱变盘: Bull>0且上升 + Bear<0且上升 → 多空力量均减弱，市场可能变盘

    # 5. 趋势方向分类（8类）
    ┌──────────────┬─────────────────────────────────┬────────┐
    │ 分类          │ 条件                             │ 强度基准 │
    ├──────────────┼─────────────────────────────────┼────────┤
    │ STRONG_BULL  │ EMA上升 + Bull>0 + Bear>0       │   80   │
    │ BULL_TREND   │ EMA上升 + Bull>0 + Bear≤0       │   65   │
    │ BULL_REVERSAL│ EMA上升 + Bull≤0（多头转负）     │   35   │
    │ STRONG_BEAR  │ EMA下降 + Bull<0 + Bear<0       │   20   │
    │ BEAR_TREND   │ EMA下降 + Bull≥0 + Bear<0       │   35   │
    │ BEAR_REVERSAL│ EMA下降 + Bear≥0（空头转正）     │   60   │
    │ SIDEWAYS_BULL│ 震荡 + Bull>0 + Bear>0          │   55   │
    │ SIDEWAYS_BEAR│ 震荡 + Bull<0 + Bear<0          │   45   │
    │ SIDEWAYS     │ 震荡 + 其他                      │   50   │
    └──────────────┴─────────────────────────────────┴────────┘

    # 6. 强度评分（0-100）
    strength = strength_base + slope_bonus + divergence_bonus
    - 斜率加成: 上升趋势加，下降趋势减
    - 背离加成: 看涨背离+上升趋势=+10，看跌背离+下降趋势=-10
    - 双弱变盘: 重置为50（中性）

    # 7. 综合交易信号
    做多信号（强）: EMA上升 + Bear<0 + Bear回升 + 看涨背离
    做多信号（弱）: EMA上升 + Bear<0 + Bear回升
    做空信号（强）: EMA下降 + Bull>0 + Bull下降 + 看跌背离
    做空信号（弱）: EMA下降 + Bull>0 + Bull下降
```

**在资金分配中的作用：**
- 趋势强度是资金分配的第一维调整因子（0.3x - 1.5x）
- STRONG_BULL 给 1.2x-1.5x 高权重，STRONG_BEAR 给 0.3x-0.5x 低权重
- 看涨背离 + EMA上升 → ×1.2 加成（强做多信号）
- 多空双弱（both_weakening）→ ×0.7 降仓（变盘风险）

**调用位置：** `get_coin_strategy_params()` → `calc_elder_ray(coin_daily_raw)`

### 6.3 持仓超时与离场系统切换

**核心设计思想：** 马丁策略的本质是通过加仓摊低成本，
但持仓不能无限期持有。通过分层计时机制，在持仓超时时
切换到经典指标离场系统，由专业的离场评估模块决定
最优离场策略，避免"死扛"导致的深度套牢。

**分层计时机制：**

```
┌───────────────────────────────────────────────────────────────┐
│  底仓阶段（无加仓）                                            │
│  计时起点：open_time（开仓时间）                               │
│  超时阈值：max_base_holding_hours（默认48h）                  │
│  黄金窗口：无（底仓阶段直接判断超时）                          │
│  超时后 → 触发经典离场系统评估                                 │
└──────────────────────────────┬────────────────────────────────┘
                               │
                    触发第1次加仓 ↓
┌───────────────────────────────────────────────────────────────┐
│  加仓后阶段（有加仓）                                          │
│  计时起点：last_addon_time（最后一次加仓时间）                 │
│  黄金窗口：golden_window_hours（默认12h）                      │
│    → 黄金窗口内不触发离场（让黑天鹅反弹充分发展）              │
│  超时阈值：max_post_addon_hours（默认24h）                     │
│    → 黄金窗口结束后，再计算是否超时                            │
│  超时后 → 触发经典离场系统评估                                 │
└───────────────────────────────────────────────────────────────┘
```

**切换到经典离场系统的流程：**

```
check_time_exit(coin, pos):
  │
  ├─ 1. 计算持仓时间（分层计时）
  │     无加仓 → hold_hours = now - open_time
  │     有加仓 → hold_hours = now - last_addon_time
  │
  ├─ 2. 黄金窗口判断（仅加仓后）
  │     hold_hours < golden_window → 不触发（继续持有等待反弹）
  │
  ├─ 3. 超时判断
  │     hold_hours < max_hours → 不触发
  │     hold_hours >= max_hours → 超时，触发离场评估
  │
  └─ 4. 调用经典离场系统（ClassicExitSystem）
        ├─ 输入：PositionState（价格、盈亏、持仓时间、ATR等）
        ├─ 输入：candles_1h（1H K线，100根，用于技术指标）
        ├─ 输入：regime="trend"（趋势市模式）
        └─ 输出：ExitDecision（action + reason + 参数）
```

**四种离场动作：**

| 动作 | 说明 | 触发条件示例 | 后续行为 |
|------|------|-------------|----------|
| **CLOSE** | 全部平仓 | 趋势反转、严重破位、顶背离 | 平仓离场，删除持仓 |
| **REDUCE** | 部分减仓 | 短期超买、有回调风险 | 减仓 reduce_frac 比例，继续持有 |
| **RAISE_TP** | 提高止盈价 | 强势反弹、趋势延续 | 提高止盈价（上限2×原始止盈），继续持有 |
| **HOLD** | 继续持有 | 趋势健康、无明显离场信号 | 什么都不做，下一轮继续评估 |

**降级策略：**
- 若经典离场系统不可用（导入失败、计算异常等）
- → 直接执行保本平仓（timeout_fallback）
- → 确保不会因为离场系统故障而无限期持有

**参数来源（贝叶斯优化）：**
- `max_base_holding_hours`: 底仓最大持仓时间（24-96h）
- `max_post_addon_hours`: 加仓后最大持仓时间（12-48h）
- `golden_window_hours`: 黑天鹅反弹黄金窗口（4-24h）
- 由资金管理引擎每月自动优化并写入 `.env.v15` 配置文件

### 6.4 贝叶斯参数优化

**优化空间（8个参数）：**

| 参数 | 范围 | 说明 |
|------|------|------|
| `base_position_pct` | 0.15-0.30 | 底仓资金比例 |
| `addon1_pct` | 0.10-0.30 | 加仓1资金比例 |
| `addon2_pct` | 0.03-0.10 | 加仓2资金比例 |
| `addon3_pct` | 0.05-0.20 | 加仓3资金比例 |
| `max_concurrent_positions` | 2-8 | 最大持仓数 |
| `max_base_holding_hours` | 24-96h | 底仓最大持仓时间 |
| `max_post_addon_hours` | 12-48h | 加仓后最大持仓时间 |
| `golden_window_hours` | 4-24h | 黑天鹅反弹黄金窗口 |

**优化流程：** 基于回测数据的资金效率评分（回测→优化→回测验证），目标：最大化卡尔马比率

**资金效率评分算法：**
- 各层效率 = 触发频率 × (1 + 平均收益) × 胜率
- 资金分配与效率评分匹配度作为优化目标之一
- 底仓22%和杠杆5x为用户经验值，固定不参与优化
- BTC止盈4%固定，其他币种按波动率放大
- 趋势过滤参数（both_bear + MA104）参与优化

### 6.5 资金管理引擎（整体模块）

**模块定位：** 整合回测引擎 + 趋势过滤器 + 贝叶斯优化器 + 资金管理，作为整体模块运行。

**触发机制：**
1. **月度定期运行：** master_daemon 每天检查，每月1号运行完整优化流程
2. **连续亏损3次触发：** v15ct_trader.py 止损平仓时 consecutive_losses += 1，达到3次异步触发

**运行流程：**
```
CapitalManagerEngine.run_monthly()
  ├─ run_backtest()          ← 回测引擎（统计各层触发频率和收益特征）
  │    └─ 计算资金效率评分 = 触发频率 × (1 + 平均收益) × 胜率
  ├─ check_trend_filter()    ← 三屏趋势过滤
  ├─ run_optimization()      ← 贝叶斯优化器
  │    ├─ 基于回测数据的资金效率评分
  │    ├─ 趋势过滤参数寻优
  │    └─ 最大化卡尔马比率
  └─ _update_config_file()   ← 写入配置
```

**HTTP API 接口（端口8770）：**
| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /status | 资金管理整体状态 |
| GET | /params | 当前最优参数 |
| GET | /trend/<coin> | 某币种趋势过滤状态 |
| GET | /check/<coin> | 综合开仓许可检查 |
| GET | /history | 优化历史记录 |
| POST | /optimize | 触发手动优化 |

**CLI 接口：**
```bash
python capital_manager_engine.py status      # 资金状态
python capital_manager_engine.py trend --coin BTC  # 趋势过滤
python capital_manager_engine.py check --coin BTC  # 综合检查
python capital_manager_engine.py monthly     # 手动月度优化
python capital_manager_engine.py api --port 8770   # 启动API
```

### 6.6 开仓许可规则（旧版，保留参考）

```python
calculate_capital_allocation():
    available = TOTAL_BUDGET - used_margin
    position_count = 当前持仓数
    total_cost_per_position = 单仓位总成本

    # 风险评级
    margin_pct = used_margin / TOTAL_BUDGET
    if margin_pct > 0.8 or position_count >= MAX_CONCURRENT: risk_level = "high"
    elif margin_pct > 0.5: risk_level = "medium"
    else: risk_level = "low"

    # 开仓许可
    allow_open_new = (available >= total_cost_per_position × 2
                      and position_count < MAX_CONCURRENT)
    allow_addon = available >= total_cost_per_position
```

---

## 7. 回测引擎

### 7.1 回测流程

```
run_backtest(coin, limit=500):
  1. 获取历史K线: fetch_klines(coin, "4h", limit)
  2. 逐根K线回测:
     FOR i in range(200, len(klines)):
       - 截取 klines[:i] 作为当前数据
       - 计算所有指标
       - 判断位置 → 入场决策
       - 持仓管理: 止盈/止损/加仓
       - 记录交易
  3. 统计绩效:
     - 总交易数、胜场、胜率
     - 总收益、最大回撤
     - 夏普比率、盈亏比
     - 平均持仓时长
```

### 7.2 回测中的 BELOW_ALL 做空

回测引擎支持 `--allow-short` 参数，开启后 BELOW_ALL 位置会走16层做空镜像逻辑：

| Tier | 做多条件（ABOVE_ALL） | 做空条件（BELOW_ALL） |
|------|----------------------|----------------------|
| 1 | Fib黄金区+布林支撑+RSI<55 | Fib黄金区+布林压力+RSI>45 |
| 2 | Fib黄金区+RSI<55 | Fib黄金区+RSI>45 |
| 3 | Fib浅区+RSI<55 | Fib浅区+RSI>45 |
| 4 | 布林中轨+RSI<50 | 布林中轨+RSI>50 |
| 5 | RSI<45 | RSI>55 |
| 6 | MACD多头扩张+RSI<55 | MACD空头扩张+RSI>45 |
| 7 | ADX>25+DI多+RSI<55 | ADX>25+DI空+RSI>45 |
| 8 | Pivot支撑区+RSI<55 | Pivot压力区+RSI>45 |
| 9 | OBV多头+量能加速+RSI<60 | OBV空头+量能加速+RSI>40 |
| 10 | SuperTrend多头+RSI<60 | SuperTrend空头+RSI>40 |
| 11 | Keltner下沿/中线+RSI<60 | Keltner上沿/中线+RSI>40 |
| 12 | StochRSI金叉/超卖+RSI<60 | StochRSI死叉/超买+RSI>40 |
| 13 | Vortex多头反转+RSI<65 | Vortex空头反转+RSI>35 |
| 14 | TEMA多头+slope>0+RSI<65 | TEMA空头+slope<0+RSI>35 |
| 15 | GoldenCross金叉+RSI<65 | GoldenCross死叉+RSI>35 |
| 16 | EMA多头排列+RSI<65 | EMA空头排列+RSI>35 |

> 注意：实盘 `v15_signal.py` 只做多，不产生做空信号。

### 7.3 MA200 止损在回测中的实现

回测引擎内置了 `prepare_ma200_for_4h()` 函数，将日线/周线 MA200 对齐到4H K线：

```python
prepare_ma200_for_4h(klines_4h, klines_1d, klines_1w):
    # 日线 MA200 对齐到4H：每个4H K线使用前一个已收盘的日线MA200
    # 周线 MA200 对齐到4H：每个4H K线使用前一个已收盘的周线MA200
    → 返回 (daily_ma200_series, weekly_ma200_series)
```

---

## 8. 风控体系

### 8.1 五层风控架构

```
┌─ 第一层：入场风控 ──────────────────────────────────────┐
│  • 置信度 ≥ 60 才入场                                    │
│  • 只做多（ABOVE_ALL/IN_ZONE），BELOW_ALL 等待            │
│  • 止损未触发（不在 BELOW_ALL_MA_CONFIRMED 状态）         │
│  • 下单数量 ≥ 最小合约单位                                │
└──────────────────────────────────────────────────────────┘

┌─ 第二层：持仓风控 ──────────────────────────────────────┐
│  • 最大加仓3次（共4层仓位）                               │
│  • 加仓只在下跌时触发（drop_pct > 0）                     │
│  • 加仓递增门槛：8% × vol × (N+1)                        │
│  • MA200动态止损                                          │
└──────────────────────────────────────────────────────────┘

┌─ 第三层：趋势风控 ──────────────────────────────────────┐
│  • 三屏趋势过滤（both_bear + MA104）                     │
│  • 周线+日线MA104都看空 → 禁止开多                       │
│  • 实时价格判断（非收盘价确认）                          │
└──────────────────────────────────────────────────────────┘

┌─ 第四层：资金风控 ──────────────────────────────────────┐
│  • 最大并发6仓                                           │
│  • 开新仓需可用 ≥ 单仓位总成本 × 2                       │
│  • 加仓需可用 ≥ 单仓位总成本                              │
│  • 保证金占比 > 80% → 高风险                              │
└──────────────────────────────────────────────────────────┘

┌─ 第五层：系统风控 ──────────────────────────────────────┐
│  • 日亏损限制：-50 USDT → 暂停                            │
│  • 连续亏损3次 → 暂停，触发资金管理引擎重新优化           │
│  • 状态持久化：JSON文件，进程重启不丢失                    │
│  • 日志轮转：按日期存储                                    │
└──────────────────────────────────────────────────────────┘
```

### 8.2 风控参数表

| 参数 | 默认值 | 配置键 | 作用 |
|------|--------|--------|------|
| 最小置信度 | 60 | 代码硬编码 | 低于60分不入场 |
| 最大加仓次数 | 3 | `MAX_ADDONS_PER_POSITION` | 每仓最多加仓3次 |
| 最大并发仓 | 6 | `MAX_CONCURRENT_POSITIONS` | 同时最多6个币种持仓 |
| 固定止损 | — | — | 已移除，仅使用MA200动态止损 |
| 趋势过滤模式 | both_bear | `V15_TREND_FILTER_MODE` | none/both_bear |
| 趋势过滤MA周期 | 104 | `V15_TREND_FILTER_PERIOD` | 约5个月均线 |
| 日亏损限制 | -50 USDT | `V15_DAILY_LOSS_LIMIT` | 单日亏损上限 |
| 连续亏损 | 3次 | `V15_MAX_CONSECUTIVE_LOSSES` | 连续亏损暂停阈值，触发资金管理引擎重新优化 |
| 保证金高危线 | 80% | 代码硬编码 | 保证金占比超80%高风险 |
| 轮询间隔 | 3600s | `V15_POLL_INTERVAL` | 策略轮询周期 |

### 8.3 只做多验证链

```
信号层:
  v15_signal.py
    ├─ BELOW_ALL → "等待（不做空）"     ← L185
    ├─ IN_ZONE RSI>65 → "只做多不反手"  ← L322
    ├─ IN_ZONE RSI>55+布林上轨 → 等待    ← L315
    └─ 输出 action 仅可能为 "OPEN_BULL" 或 "WAIT"

执行层:
  v15_trader.py
    ├─ 开仓: side="buy", pos_side="long"  ← L162-167
    ├─ 加仓: side="buy", pos_side="long"  ← L243-248
    ├─ 止盈: side="sell", pos_side="long" ← L322-327
    └─ 止损: side="sell", pos_side="long" ← L348-353
    （全部 pos_side="long"，无任何 "short"）

加仓方向:
  execute_addon() 中 side="buy"  ← 下跌加仓也是做多方向
```

---
_最后更新：2026-07-13 | 来源：14-V15经典马丁策略（独立V15系统）_
