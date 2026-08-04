# 技术设计文档 — V15 经典马丁策略

> **定位：** 模块级技术设计文档，描述架构、数据流、算法细节
> **版本：** v5.2 | **更新：** 2026-08-01
> **系统：** V15 经典马丁策略（入场信号+反弹增强+参数设置+趋势计算+资金管理+动态止损+离场系统+贝叶斯优化+多空方向控制v2+OCO止盈止损挂单+币种风控过滤+智能系统增强+双基线版本管理+贝叶斯自动调度+实盘移动止盈）

---

## 目录

- [1. 系统架构](#1-系统架构)
  - [1.1 八大核心模块](#11-八大核心模块)
  - [1.2 三层架构](#12-三层架构)
  - [1.3 设计原则](#13-设计原则)
- [2. 数据流](#2-数据流)
- [3. 入场信号系统（16层决策）](#3-入场信号系统)
- [4. 反弹检测器（第二层信号增强）](#4-反弹检测器)
- [5. 参数设置模块（BTC基准+波动率放大）](#5-参数设置模块)
- [6. 趋势强度计算器（Elder-ray）](#6-趋势强度计算器)
- [7. 资金管理器（智能资金分配）](#7-资金管理器)
- [8. 动态止损系统（MA200族）](#8-动态止损系统)
- [9. 持仓超时与离场系统](#9-持仓超时与离场系统)
- [10. 贝叶斯参数优化系统](#10-贝叶斯参数优化系统)
- [11. 回测引擎](#11-回测引擎)
- [12. 风控体系](#12-风控体系)
- [13. OCO止盈止损挂单系统](#13-oco止盈止损挂单系统)
- [14. 币种风控过滤系统](#14-币种风控过滤系统)
- [15. 智能系统增强（ATR动态止盈+移动止盈+ELDER-RAY资金调度+凯利公式）](#15-智能系统增强)
- [16. BTC风向标智能模式选择](#16-btc风向标智能模式选择)
- [17. 贝叶斯优化自动调度与双基线版本管理](#17-贝叶斯优化自动调度与双基线版本管理)

---

## 1. 系统架构

### 1.1 八大核心模块

V15 经典马丁策略由 8 大核心模块构成，形成完整的交易决策闭环：

```
┌───────────────────────────────────────────────────────────────────┐
│                        入场信号系统（第一层）                       │
│  16层入场决策 + 16项技术指标 + 4H均线位置判定                      │
└─────────────┬─────────────────────────────────────────────────────┘
              │
┌─────────────▼─────────────┐
│   反弹检测器（第二层增强）   │  ← 可选，非必须
│  Fib支撑+RSI超卖+量能恐慌    │
│  置信度加持：+10×n_triggered │
└─────────────┬─────────────┘
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

> **三屏趋势过滤器（已禁用）**：代码保留但 `TREND_FILTER_MODE=none`，实盘不执行任何过滤。风险由动态止损系统（MA200族）承担。

| 模块 | 核心职责 | 关键输出 | 所在文件 |
|------|----------|----------|----------|
| 入场信号系统 | 16层入场决策，16项技术指标计算，4H均线位置判定 | OPEN_BULL / OPEN_BEAR / WAIT + 置信度 | `core/v15_signal.py` |
| 多空方向控制 | 基于MA128+BTC风向标三状态模型动态控制多空方向 | regime + short_enabled + long_enabled | `lib/direction_gate.py` |
| 反弹检测器 | 第二层信号增强，Fib支撑+RSI超卖+量能恐慌检测 | n_triggered + 置信度加持 | `lib/bounce_potential_evaluator.py` |
| 参数设置 | BTC固定参数基准，其他币种按30日波动率放大 | 止盈比例、加仓间距、止损参数 | `lib/strategy_params.py` |
| 趋势强度计算器 | Elder-ray三重滤网系统，日线级别趋势强度评估 | direction + strength(0-100) + 多空信号 | `lib/strategy_params.py` |
| 资金管理器 | 基于趋势强度+置信度+波动率的智能资金分配 | per_coin_budget + 3次加仓分配 | `lib/capital_manager.py` |
| 动态止损 | 日线/周线 MA200+EMA200 四条均线止损（支持多空方向） | 止损线价格 + 是否触发 | `lib/strategy_params.py` |
| 持仓超时与离场 | 分层计时，超时后切换经典离场系统 | CLOSE/REDUCE/RAISE_TP/HOLD | `core/v15_trader.py` |
| 贝叶斯参数优化 | 8参数寻优，每月自动优化配置 | 最优参数组合 + 回测绩效 | `lib/bayesian_optimizer.py` |

#### 反弹检测器（第二层信号增强）

反弹检测器是**可选的第二层信号增强机制**，非硬性过滤条件：

| 场景 | 行为 | 结果 |
|------|------|------|
| 第一层信号通过 + 有反弹信号 | 置信度加持：`conf + n_triggered × 10` | 优先选择 |
| 第一层信号通过 + 无反弹信号 | 保持原始置信度 | 按置信度排序选择 |
| 第一层信号不通过 | 不进入第二层检测 | 等待 |

**触发条件（满足任意≥1项即有效）**：

| 序号 | 检测项 | 判断标准 | 权重 |
|------|--------|----------|------|
| 1 | Fib支撑位 | 价格在0.382-0.618黄金区 | +10 |
| 2 | RSI超卖 | RSI < 40 | +10 |
| 3 | 成交量恐慌 | 量能 > 20周期均量 × 1.5 | +10 |
| 4 | 价格下沿突破 | 价格 < 布林下轨 | +10 |
| 5 | KDJ超卖 | K < 20 或 D < 20 | +10 |

**配置项**：

```ini
# config/.env.v15
BOUNCE_FILTER_ENABLED=true    # 启用反弹检测
BOUNCE_MIN_SIGNALS=1          # 最少触发项数
```

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

### 1.3 设计原则

1. **信号与执行分离** — `v15_signal.py` 只负责计算信号，`v15_trader.py` 负责执行交易，职责清晰
2. **波动率自适应** — 所有关键参数（止盈、加仓间距、止损）根据币种波动率动态调整
3. **多空方向控制** — DirectionGate 基于 MA128+BTC风向标 三状态模型动态控制多空方向（默认只做多，`V15_ALLOW_SHORT=true` 时启用做空）。详见 §11.2.2
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
  │                     ├─ 反弹检测增强置信度（可选）
  │                     ├─ 止损触发 → 禁止开多
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

## 3. 入场信号系统（16层决策）

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

## 4. 反弹检测器（第二层信号增强）

### 4.1 设计理念

反弹检测器是**可选的第二层信号增强机制**，位于入场信号系统之后：

```
┌─────────────────────────────────────────────────────────────────┐
│                  第一层：入场信号系统                             │
│  16层决策 → 置信度≥60 → OPEN_BULL                                │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│               第二层：反弹检测器（可选增强）                       │
│  ├─ 有反弹信号 → 置信度加持：conf + n_triggered × 10             │
│  └─ 无反弹信号 → 保持原始置信度                                   │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
          按增强后置信度排序选择开仓币种
```

**关键特性**：
- **非硬性过滤**：没有反弹信号不会阻止开仓，只是保持原始置信度
- **优先选择**：有反弹信号加持的币种置信度更高，优先开仓
- **资金分配**：使用增强后的置信度计算资金分配倍数

### 4.2 检测项与权重

| 序号 | 检测项 | 判断标准 | 置信度加持 |
|------|--------|----------|------------|
| 1 | Fib黄金支撑 | 价格在0.382-0.618黄金区 | +10 |
| 2 | RSI超卖 | RSI < 40 | +10 |
| 3 | 成交量恐慌 | 量能 > 20周期均量 × 1.5 | +10 |
| 4 | 布林下轨突破 | 价格 < 布林下轨 | +10 |
| 5 | KDJ超卖 | K < 20 或 D < 20 | +10 |

**触发规则**：
- `n_triggered ≥ BOUNCE_MIN_SIGNALS`（默认1）时有效
- 置信度加持 = `n_triggered × 10`

### 4.3 代码实现

```python
# core/v15_trader.py - execute_open_position()

effective_conf = conf  # 原始置信度

if BOUNCE_FILTER_ENABLED and BOUNCE_MONITOR_ENABLED:
    klines_4h = params.get("klines_4h")
    if klines_4h:
        bounce_signal = evaluate_signals(coin, klines_4h, lookback=60)
        if bounce_signal["valid"] and bounce_signal["n_triggered"] >= BOUNCE_MIN_SIGNALS:
            # 有反弹信号 → 置信度加持
            effective_conf = conf + bounce_signal["n_triggered"] * 10
            _log(f"[{coin}] 反弹信号加持: n_triggered={n_triggered}, 置信度从{conf}%增强至{effective_conf}%")
        else:
            # 无反弹信号 → 保持原始置信度
            _log(f"[{coin}] 无反弹信号，保持原始置信度{conf}%")
```

### 4.4 资金分配影响

增强后的置信度影响资金分配：

```python
# lib/capital_manager.py - calculate_per_coin_allocation()

# 置信度调整因子 (0.5x - 1.5x)
# conf=60 → 0.8x, conf=70 → 1.0x, conf=80 → 1.2x, conf=90 → 1.4x
conf_mult = 0.5 + (confidence / 100) * 1.0

# 反弹加持后 conf=80 → 1.2x，比原始 conf=65 → 0.925x 更高资金分配
per_coin_budget = base_budget × combined_mult
```

**示例**：
- 原始置信度 65%：`conf_mult = 0.5 + 0.65 = 1.15` → 资金倍数 ~1.0x
- 反弹加持后 85%：`conf_mult = 0.5 + 0.85 = 1.35` → 资金倍数 ~1.2x

### 4.5 配置项

```ini
# config/.env.v15
BOUNCE_FILTER_ENABLED=true    # 启用反弹检测
BOUNCE_MIN_SIGNALS=1          # 最少触发项数（满足1项即有效）
```

---

## 5. 参数设置模块（BTC基准+波动率放大）

### 5.1 开仓流程

```
execute_open_position(client, coin, decision, state):
  1. 置信度检查: conf < 60 → 拒绝
  2. 反弹检测: effective_conf = conf + n_triggered × 10（可选）
  3. 资金计算: base_margin = capital_manager.single_position_cost.base_usd
  4. 动态参数: _get_dynamic_params(client, coin, "LONG")
     - 止损触发? → 禁止开多
  5. 下单规模: order_margin = base_margin × vol_mult
              order_notional = order_margin × LEVERAGE
  6. 合约精度: get_contract_info(client, inst_id) → lot_sz, ct_val
  7. 下单数量: sz = calc_lot_sz(notional, price, lot_sz, ct_val)
     - sz < lot_sz → 拒绝（最小单位不足）
  8. 执行下单: side="buy", pos_side="long", td_mode="isolated"
  9. 状态记录: entry_price, open_price, sz, addons=0, confidence,
              take_profit_pct, addon_pct, stop_loss_price, vol_mult
```

### 5.2 加仓流程

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

### 5.3 止盈止损流程

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

## 6. 趋势强度计算器（Elder-ray）

### 6.1 四均线止损系统

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

### 6.2 止损参数接口

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

### 6.3 三屏趋势过滤器（已禁用）

> **状态：已禁用（`TREND_FILTER_MODE=none`）**
>
> 代码保留在 `lib/strategy_params.py` 的 `check_trend_filter()` 中，但配置为 `none` 模式，实盘不执行任何过滤。
> 风险控制由动态止损系统（MA200族）承担，通过收盘价确认触发止损。

---

## 7. 资金管理器（智能资金分配）

### 7.1 智能资金分配（Elder-ray + 置信度 + 波动率）

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

### 7.2 Elder-ray 趋势强度检测

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
- 趋势强度是资金分配的第一维调整因子
- 实盘资金管理器（`capital_manager.py`）：0.3x - 1.5x（宽范围，STRONG_BEAR 可降至 0.3x）
- 回测/贝叶斯优化基线（`v15_backtest.py`）：0.9x - 1.5x（窄范围，可被优化器动态调整）
- 贝叶斯优化参数空间：`elder_ray_floor` (0.5-0.9), `elder_ray_ceil` (1.2-1.5)
- 看涨背离 + EMA上升 → ×1.2 加成（强做多信号）
- 多空双弱（both_weakening）→ ×0.7 降仓（变盘风险）

> **范围差异说明：** 实盘 `capital_manager.py` 使用更宽的 0.3-1.5x 范围，允许在强熊市时更大幅度降仓以控制风险；回测引擎 `v15_backtest.py` 使用 0.9-1.5x 作为贝叶斯优化基线，优化器可在此空间内寻优。两者通过 `calc_elder_ray_size_mult()` 统一计算，差异仅在边界约束。

**调用位置：** `get_coin_strategy_params()` → `calc_elder_ray(coin_daily_raw)`；回测中 `calc_elder_ray_size_mult()` 使用模块级变量 `_elder_ray_floor` / `_elder_ray_ceil`

### 7.3 持仓超时与离场系统切换

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
| **RAISE_TP** | 提高止盈价 | 强势反弹、趋势延续 | 提高止盈价（上限2×原始止盈），同步更新OCO挂单，继续持有 |
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

### 7.4 贝叶斯参数优化

> **详细内容见 [§10. 贝叶斯参数优化系统](#10-贝叶斯参数优化系统)**

**当前优化空间（8个智能系统参数）：**

| 参数 | 范围 | 说明 | 类别 |
|------|------|------|------|
| `trailing_atr_mult` | 1.0-2.5 | 移动止盈ATR倍数 | 智能系统 |
| `trailing_start_ratio` | 0.3-0.8 | 移动止盈启动阈值（占止盈比例） | 智能系统 |
| `elder_ray_floor` | 0.5-0.9 | ELDER-RAY仓位下限 | 智能系统 |
| `elder_ray_ceil` | 1.2-1.5 | ELDER-RAY仓位上限 | 智能系统 |
| `btc_windvane_confirm_days` | 1-5 | BTC风向标确认天数 | 智能系统 |
| `max_base_holding_hours` | 24-96h | 底仓最大持仓时间 | 持仓时间 |
| `max_post_addon_hours` | 12-48h | 加仓后最大持仓时间 | 持仓时间 |
| `golden_window_hours` | 4-24h | 黑天鹅反弹黄金窗口 | 持仓时间 |

**固定参数（不参与优化）：** 底仓22%、杠杆5x、BTC止盈4%（其他币种按波动率放大）、加仓间距8%基准

### 7.5 资金管理引擎（整体模块）

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

### 7.6 开仓许可规则（旧版，保留参考）

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

## 8. 动态止损系统（MA200族）

### 8.1 四均线止损系统

> **重要区分：** 均线系统在 V15 中有两条独立用途：
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

### 8.2 止损参数接口

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

---

## 9. 持仓超时与离场系统

### 9.1 核心设计思想

马丁策略的本质是通过加仓摊低成本，但持仓不能无限期持有。通过分层计时机制，在持仓超时时切换到经典指标离场系统，由专业的离场评估模块决定最优离场策略，避免"死扛"导致的深度套牢。

### 9.2 分层计时机制

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

### 9.3 切换到经典离场系统的流程

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

### 9.4 四种离场动作

| 动作 | 说明 | 触发条件示例 | 后续行为 |
|------|------|-------------|----------|
| **CLOSE** | 全部平仓 | 趋势反转、严重破位、顶背离 | 平仓离场，删除持仓 |
| **REDUCE** | 部分减仓 | 短期超买、有回调风险 | 减仓 reduce_frac 比例，继续持有 |
| **RAISE_TP** | 提高止盈价 | 强势反弹、趋势延续 | 提高止盈价（上限2×原始止盈），同步更新OCO挂单，继续持有 |
| **HOLD** | 继续持有 | 趋势健康、无明显离场信号 | 什么都不做，下一轮继续评估 |

### 9.5 参数来源（贝叶斯优化）

- `max_base_holding_hours`: 底仓最大持仓时间（24-96h）
- `max_post_addon_hours`: 加仓后最大持仓时间（12-48h）
- `golden_window_hours`: 黑天鹅反弹黄金窗口（4-24h）
- 由资金管理引擎每月自动优化并写入 `.env.v15` 配置文件

---

## 10. 贝叶斯参数优化系统

### 10.1 优化空间（8个智能系统参数）

> **v5.0 更新：** 优化参数从旧的资金分配参数（addon1/2/3_pct等）切换为智能系统核心参数（ATR/移动止盈/ELDER-RAY/风向标），聚焦于智能系统参数寻优而非资金分配。

| 参数 | 范围 | 说明 | 类别 | 配置来源 |
|------|------|------|------|----------|
| `trailing_atr_mult` | 1.0-2.5 | 移动止盈ATR倍数（浮盈回撤N×ATR止盈） | 智能系统 | 贝叶斯优化 |
| `trailing_start_ratio` | 0.3-0.8 | 移动止盈启动阈值（占止盈比例，如0.8=80%） | 智能系统 | 贝叶斯优化 |
| `elder_ray_floor` | 0.5-0.9 | ELDER-RAY仓位下限（弱趋势时最小仓位倍数） | 智能系统 | 贝叶斯优化 |
| `elder_ray_ceil` | 1.2-1.5 | ELDER-RAY仓位上限（强趋势时最大仓位倍数） | 智能系统 | 贝叶斯优化 |
| `btc_windvane_confirm_days` | 1-5 | BTC风向标跌破确认天数（3日=稳健，1日=灵敏） | 智能系统 | 贝叶斯优化 |
| `max_base_holding_hours` | 24-96h | 底仓最大持仓时间 | 持仓时间 | 贝叶斯优化 |
| `max_post_addon_hours` | 12-48h | 加仓后最大持仓时间 | 持仓时间 | 贝叶斯优化 |
| `golden_window_hours` | 4-24h | 黑天鹅反弹黄金窗口 | 持仓时间 | 贝叶斯优化 |

**固定参数（不参与优化）：**
- 底仓比例22%（`base_position_pct`，用户经验值）
- 杠杆5x（`leverage`，用户经验值）
- BTC止盈4%（`tp_pct_btc`，其他币种按波动率放大）
- 加仓间距8%基准（`addon_pct`，按波动率放大）
- 最大加仓3次（`max_addons`）

### 10.2 优化流程

基于回测数据的智能系统参数寻优（回测→优化→回测验证），目标：最大化卡尔马比率

**目标函数权重：**
- 卡尔马比率（收益/回撤）：40%（最高权重，控制回撤）
- 夏普比率：20%
- 胜率：15%
- 资金效率：25%

**硬约束：**
- 最大回撤 ≤ 60%
- 最小胜率 ≥ 40%
- 最小交易数 ≥ 10

### 10.3 三轮反馈优化机制

```
第1轮：基线探索，宽范围搜索 → 回测验证 → 分析瓶颈
第2轮：收敛到±30%范围 → 回测验证 → 对比提升
第3轮：收敛到±15%范围 → 回测验证 → 最终确认
```

每轮都有完整的回测验证和指标对比，确保优化方向正确。

### 10.4 自动回退验证（`--with-rollback`）

贝叶斯优化完成后，自动与智能参数基线（210.4%）对比，决定采用或回退：

```
[1/4] 智能参数基线回测（SMART_BASELINE_PARAMS, 210.4%）
[2/4] 贝叶斯参数优化（8参数寻优）
[3/4] 优化参数回测验证
[4/4] 对比决定:
      improvement = 优化收益 - 基线收益
      if improvement >= 2.0%:  → 采用优化参数，保存到 active_params.json
      else:                    → 回退到智能参数基线（210.4%）
```

**采用阈值：** `min_improve_pct = 2.0%`（优化收益需比基线高2%才采用）

### 10.5 双基线版本管理

| 版本 | 名称 | 收益 | 特性 | 用途 |
|------|------|------|------|------|
| v1.0 | 固定参数基线 | 138% | 纯马丁策略（止盈4%/底仓22%/加仓3次/间隔8%），无智能增强 | 智能系统整体失效时的终极回退 |
| v2.0 | 智能参数基线 | 210.4% | 智能系统全开（ATR+移动止盈+ELDER-RAY+风向标）+ 贝叶斯优化最优参数 | 贝叶斯优化无效时的回退目标 |

**三级回退策略：**
1. 贝叶斯优化参数（自定义）→ 正常运行
2. 智能参数基线（210.4%）→ 优化收益差 < 2% 时回退
3. 固定参数基线（138%）→ 智能系统整体失效时终极回退

**CLI 版本管理命令：**
```bash
python lib/bayesian_optimizer.py --version-info      # 查看版本管理信息
python lib/bayesian_optimizer.py --reset-to-smart    # 重置为智能参数基线（210.4%）
python lib/bayesian_optimizer.py --reset-to-fixed    # 终极回退到固定参数基线（138%）
python lib/bayesian_optimizer.py --check-trigger     # 检查是否应该触发优化
python lib/bayesian_optimizer.py --with-rollback     # 优化+自动回退验证（调度推荐）
```

---

## 11. 回测引擎

### 11.1 回测流程

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

### 11.2 BELOW_ALL 做空信号与 DirectionGate 方向控制

#### 11.2.1 16层做空镜像逻辑

当 `V15_ALLOW_SHORT=true` 时，BELOW_ALL 位置会走16层做空镜像逻辑（做多看支撑/超卖，做空看压力/超买）：

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

#### 11.2.2 DirectionGate 三状态方向控制（MA128 + BTC风向标）

基于风险-价值二元评估理论，DirectionGate 采用 **BTC风向标机制** + **MA128有效跌破** 动态控制多空方向：

**BTC风向标机制：**
- 当BTC有效跌破日线MA128（连续3日收盘价低于MA128），全系统做空闸门打开
- BTC作为市场风向标，其走势决定整个加密市场的做空时机

**有效跌破定义：**
- 连续3日收盘价低于日线MA128（避免单日假跌破）
- 使用已完成的日线收盘价确认，而非实时价格

**三状态模型：**

| 市场状态 | 触发条件 | 允许方向 | 理论依据 |
|----------|----------|----------|----------|
| LONG_PREFERRED | BTC未有效跌破MA128 | 只做多 | 震荡+多头行情，做多占多数(80%) |
| SHORT_ALLOWED | BTC有效跌破MA128 + 价格在周MA200上方 | 多空均可 | 暴跌阶段(20%)，做空价值较高 |
| LONG_ONLY_FORCE | 跌至周线MA200附近 | 强制做多 | 下跌末端，继续做空风险高 |

**核心设计：**
- **MA128替代MA200**：更灵敏的跌破信号，提前捕捉做空机会
- **BTC风向标**：BTC有效跌破MA128是全系统做空的必要条件
- **收盘价确认**：使用连续3日收盘价确认有效跌破，避免频繁切换
- **MA附近1%缓冲带**（`buffer_pct=0.01`）：避免临界点频繁状态切换

**状态转移：**
```
LONG_PREFERRED ──BTC有效跌破MA128──→ SHORT_ALLOWED
SHORT_ALLOWED  ──BTC涨回MA128上──→ LONG_PREFERRED
SHORT_ALLOWED  ──跌至周MA200──→ LONG_ONLY_FORCE
LONG_ONLY_FORCE ──涨回日MA128上──→ LONG_PREFERRED
```
- `V15_ALLOW_SHORT=false` 时永远只做多（向后兼容）

**做空执行参数：**
| 操作 | 做多（LONG） | 做空（SHORT） |
|------|-------------|-------------|
| 开仓 | side=buy, pos_side=long | side=sell, pos_side=short |
| 加仓触发 | 价格下跌到加仓间距 | 价格上涨到加仓间距（反向马丁） |
| 止盈 | 价格上涨到止盈线 | 价格下跌到止盈线 |
| 止损线 | 价格下方最近均线 | 价格上方最近均线 |
| 止损触发 | 收盘价 <= 止损线 | 收盘价 >= 止损线 |
| 平仓 | side=sell, pos_side=long | side=buy, pos_side=short |

#### 11.2.3 回测验证

回测引擎支持 `--direction-gate` 参数和 `--compare` 三模式对比：

```bash
# 三模式对比回测
python core/v15_backtest.py --compare

# 单币种 DirectionGate 模式
python core/v15_backtest.py --coin BTC --allow-short --direction-gate
```

##### 11.2.3.1 15币种回测结果（1000根4H K线）

| 币种 | 模式 | 总收益 | 交易数 | 胜率 | 盈亏比 | 最大回撤 | 夏普 | 做空数 |
|------|------|--------|--------|------|--------|----------|------|--------|
| BTC | 只做多 | -1.49% | 15 | 53.33% | 1.12 | 2.95% | 0.3411 | 0 |
| BTC | 无限制做空 | -0.44% | 15 | 73.33% | 0.74 | 2.81% | 1.1358 | 6 |
| BTC | Gate控制做空(新) | -0.30% | 18 | 66.67% | 1.20 | 2.81% | 1.3390 | 4 |
| ETH | 只做多 | +0.54% | 53 | 52.83% | 1.38 | 0.32% | 1.0921 | 0 |
| ETH | 无限制做空 | +3.34% | 22 | 45.45% | 3.43 | 0.24% | 1.3345 | 5 |
| ETH | Gate控制做空 | +0.54% | 53 | 52.83% | 1.38 | 0.32% | 1.0921 | 0 |
| SOL | 只做多 | -0.25% | 67 | 49.25% | 0.88 | 0.54% | -0.4747 | 0 |
| SOL | 无限制做空 | +1.25% | 20 | 45.00% | 2.11 | 0.50% | 0.7991 | 4 |
| SOL | Gate控制做空 | -0.25% | 67 | 49.25% | 0.88 | 0.54% | -0.4747 | 0 |
| BNB | 只做多 | +0.72% | 4 | 50.00% | 1.52 | 1.12% | 0.3541 | 0 |
| BNB | 无限制做空 | +0.97% | 4 | 75.00% | 0.79 | 1.12% | 0.7355 | 0 |
| BNB | Gate控制做空 | +0.97% | 4 | 75.00% | 0.79 | 1.12% | 0.7355 | 0 |
| XRP | 只做多 | -0.39% | 14 | 42.86% | 1.74 | 1.74% | 0.3628 | 0 |
| XRP | 无限制做空 | +3.30% | 7 | 71.43% | 1.36 | 0.54% | 1.5783 | 7 |
| XRP | Gate控制做空 | +2.52% | 10 | 40.00% | 7.77 | 0.22% | 1.4842 | 3 |
| ADA | 只做多 | -0.40% | 39 | 48.72% | 0.68 | 0.62% | -1.0929 | 0 |
| ADA | 无限制做空 | +4.19% | 5 | 100.00% | 0.00 | 0.00% | 7.7230 | 5 |
| ADA | Gate控制做空 | -0.40% | 39 | 48.72% | 0.68 | 0.62% | -1.0929 | 0 |
| DOGE | 只做多 | -0.34% | 36 | 41.67% | 0.91 | 0.62% | -1.0121 | 0 |
| DOGE | 无限制做空 | +4.47% | 11 | 81.82% | 1.99 | 0.20% | 2.4030 | 7 |
| DOGE | Gate控制做空 | -0.34% | 36 | 41.67% | 0.91 | 0.62% | -1.0121 | 0 |
| AVAX | 只做多 | -0.42% | 51 | 49.02% | 0.75 | 0.67% | -0.8329 | 0 |
| AVAX | 无限制做空 | +1.88% | 20 | 50.00% | 2.51 | 0.46% | 1.2742 | 5 |
| AVAX | Gate控制做空 | -0.42% | 51 | 49.02% | 0.75 | 0.67% | -0.8329 | 0 |
| LINK | 只做多 | -0.11% | 53 | 56.60% | 0.70 | 0.64% | -0.2120 | 0 |
| LINK | 无限制做空 | +3.23% | 4 | 75.00% | 2.80 | 0.16% | 2.0645 | 4 |
| LINK | Gate控制做空 | -0.11% | 53 | 56.60% | 0.70 | 0.64% | -0.2120 | 0 |
| ATOM | 只做多 | +0.41% | 54 | 50.00% | 1.43 | 0.23% | 0.9201 | 0 |
| ATOM | 无限制做空 | -2.30% | 18 | 50.00% | 0.97 | 3.85% | -0.0408 | 7 |
| ATOM | Gate控制做空 | +0.41% | 54 | 50.00% | 1.43 | 0.23% | 0.9201 | 0 |
| FIL | 只做多 | -0.03% | 52 | 42.31% | 1.33 | 0.27% | -0.0595 | 0 |
| FIL | 无限制做空 | -4.25% | 31 | 58.06% | 0.97 | 7.42% | 0.4248 | 14 |
| FIL | Gate控制做空 | -0.03% | 52 | 42.31% | 1.33 | 0.27% | -0.0595 | 0 |
| NEAR | 只做多 | +4.15% | 55 | 54.55% | 2.55 | 0.26% | 1.9234 | 0 |
| NEAR | 无限制做空 | +1.87% | 33 | 57.58% | 1.58 | 2.29% | 1.1370 | 1 |
| NEAR | Gate控制做空 | +4.14% | 54 | 53.70% | 2.67 | 0.26% | 1.9232 | 0 |
| AAVE | 只做多 | -0.12% | 32 | 46.88% | 1.04 | 0.86% | -0.1831 | 0 |
| AAVE | 无限制做空 | +4.50% | 9 | 88.89% | 0.99 | 0.41% | 3.1653 | 9 |
| AAVE | Gate控制做空 | -0.12% | 32 | 46.88% | 1.04 | 0.86% | -0.1831 | 0 |
| LTC | 只做多 | -0.03% | 47 | 55.32% | 0.78 | 0.35% | -0.1029 | 0 |
| LTC | 无限制做空 | +2.64% | 16 | 56.25% | 3.74 | 0.24% | 2.0898 | 7 |
| LTC | Gate控制做空 | -0.03% | 47 | 55.32% | 0.78 | 0.35% | -0.1029 | 0 |

##### 11.2.3.2 汇总对比（14币种平均，MA128 + BTC风向标 v2）

| 模式 | 平均收益 | 平均夏普 | 总做空数 | 亏损币种数 |
|------|----------|----------|----------|-----------|
| 只做多 | +0.16% | 0.0731 | 0 | 10/14 |
| 无限制做空 | +1.76% | 1.8446 | 81 | 3/14 |
| **Gate控制做空(v2)** | **+0.48%** | **0.2692** | **8** | **9/14** |

##### 11.2.3.3 BTC风向标机制验证（v2版本）

**BTC风向标核心逻辑**：BTC有效跌破日线MA128（连续3日收盘价低于MA128）→ 全系统做空闸门打开。

**Gate控制做空(v2)优质表现币种：**

| 币种 | 只做多 | 无限制做空 | Gate控制(v2) | 关键改善 |
|------|--------|-----------|-------------|----------|
| BTC | -1.49% | -0.44% | **-0.30%** | 盈亏比0.74→1.20，夏普1.14→1.34 |
| XRP | -0.39% | +3.30% | **+2.70%** | 盈亏比1.36→7.07，回撤0.54%→0.22% |
| BNB | +0.72% | +0.97% | +0.97% | 一致，无做空信号 |
| NEAR | +4.15% | +1.87% | **+4.14%** | 成功避开1笔低质量做空 |

**Gate成功避免的亏损币种：**

| 币种 | 无限制做空 | Gate控制 | 避免亏损 | 原因 |
|------|-----------|---------|---------|------|
| FIL | **-4.25%** | -0.03% | +4.22% | 14笔做空失控，回撤7.42% |
| ATOM | **-2.30%** | +0.41% | +2.71% | 7笔做空，回撤3.85% |

**过滤效率**：81笔 → 8笔（90%过滤率），仅保留高质量做空机会。

##### 11.2.3.4 回测结论（v2版本：MA128 + BTC风向标）

1. **BTC风向标机制有效**：
   - Gate将81笔做空过滤到8笔（90%过滤率），正确识别真正适合做空的时机
   - 仅BTC、XRP、BNB、NEAR 4个币种触发做空，其余10个币种因BTC风向标关闭而保持只做多
   - 成功避免了FIL（-4.25%）、ATOM（-2.30%）等高风险亏损

2. **风险控制价值显著**：
   - XRP盈亏比从1.36提升至7.07（5倍提升），回撤从0.54%降至0.22%
   - BTC盈亏比从0.74提升至1.20，夏普从1.14提升至1.34
   - 14币种中仅9个亏损（vs 无限制做空3个），但亏损幅度远小于极端风险

3. **收益与风险的平衡**：
   - 无限制做空平均收益+1.76%最高，但包含尾部风险（FIL -4.25%）
   - Gate控制做空平均收益+0.48%适中，但风险更可控
   - 符合"稳健优先、收益其次"的马丁策略定位

4. **理论验证**：
   - 3/14（21%）币种有较高做空价值，验证了"暴涨暴跌占20%"理论
   - 大部分时间（79%）处于只做多状态，符合"做多占多数"的策略定位
   - BTC作为市场风向标的角色得到数据支撑

### 11.3 MA200 止损在回测中的实现

回测引擎内置了 `prepare_ma200_for_4h()` 函数，将日线/周线 MA200 对齐到4H K线：

```python
prepare_ma200_for_4h(klines_4h, klines_1d, klines_1w):
    # 日线 MA200 对齐到4H：每个4H K线使用前一个已收盘的日线MA200
    # 周线 MA200 对齐到4H：每个4H K线使用前一个已收盘的周线MA200
    → 返回 (daily_ma200_series, weekly_ma200_series)
```

---

## 12. 风控体系

### 12.1 六层风控架构

```
┌─ 第零层：币种风控 ──────────────────────────────────────┐
│  • 市值等级过滤：剔除SMALL小市值/meme币，仅保留LARGE+MID │
│  • 上线时间检测：要求至少365天历史数据，剔除新币          │
│  • 运行时双重过滤：配置层 + is_martin_safe()校验          │
│  • 启动时输出剔除日志，透明可审计                         │
└──────────────────────────────────────────────────────────┘

┌─ 第一层：入场风控 ──────────────────────────────────────┐
│  • 置信度 ≥ 60 才入场                                    │
│  • DirectionGate方向控制（MA128+BTC风向标三状态模型）          │
│  • 止损未触发（不在 BELOW_ALL_MA_CONFIRMED 状态）         │
│  • 下单数量 ≥ 最小合约单位                                │
└──────────────────────────────────────────────────────────┘

┌─ 第二层：持仓风控 ──────────────────────────────────────┐
│  • 最大加仓3次（共4层仓位）                               │
│  • 做多：下跌触发加仓；做空：上涨触发加仓（反向马丁）      │
│  • 加仓递增门槛：8% × vol × (N+1)                        │
│  • MA200动态止损（做空止损线在价格上方）                   │
└──────────────────────────────────────────────────────────┘

┌─ 第三层：资金风控 ──────────────────────────────────────┐
│  • 最大并发6仓                                           │
│  • 开新仓需可用 ≥ 单仓位总成本 × 2                       │
│  • 加仓需可用 ≥ 单仓位总成本                              │
│  • 保证金占比 > 80% → 高风险                              │
└──────────────────────────────────────────────────────────┘

┌─ 第四层：系统风控 ──────────────────────────────────────┐
│  • 日亏损限制：-50 USDT → 暂停                            │
│  • 连续亏损3次 → 暂停，触发资金管理引擎重新优化           │
│  • 状态持久化：JSON文件，进程重启不丢失                    │
│  • 日志轮转：按日期存储                                    │
└──────────────────────────────────────────────────────────┘

┌─ 第五层：交易所挂单风控（OCO） ─────────────────────────┐
│  • 开仓同步挂OCO止盈止损单（程序离线也生效）              │
│  • 加仓后自动更新挂单（撤销旧单→下新单）                  │
│  • 轮询动态调整（止损线移动>0.5%时同步更新）              │
│  • 平仓前自动取消所有条件单                                │
│  • 止损价方向一致性校验（做多SL<Entry，做空SL>Entry）      │
└──────────────────────────────────────────────────────────┘

注：三屏趋势过滤器已禁用（TREND_FILTER_MODE=none），不参与风控链路。
```

### 12.2 风控参数表

| 参数 | 默认值 | 配置键 | 作用 |
|------|--------|--------|------|
| 最低市值等级 | mid | `V15_MARTIN_MIN_TIER` | 马丁策略最低市值等级（large/mid/small） |
| 最小上线天数 | 365 | `V15_MARTIN_MIN_HISTORY_DAYS` | 新币暴涨暴跌风险，要求至少1年历史数据 |
| 最小置信度 | 60 | 代码硬编码 | 低于60分不入场 |
| 最大加仓次数 | 3 | `MAX_ADDONS_PER_POSITION` | 每仓最多加仓3次 |
| 最大并发仓 | 6 | `MAX_CONCURRENT_POSITIONS` | 同时最多6个币种持仓 |
| 固定止损 | — | — | 已移除，仅使用MA200动态止损 |
| 趋势过滤模式 | none | `TREND_FILTER_MODE` | 已禁用，不参与开仓过滤 |
| 允许做空 | true | `V15_ALLOW_SHORT` | 多空方向控制开关，true=启用MA128+BTC风向标做空机制 |
| 方向缓冲带 | 1% | `DirectionGate(buffer_pct)` | MA附近缓冲（日MA128+周MA200），避免频繁切换 |
| 日亏损限制 | -50 USDT | `V15_DAILY_LOSS_LIMIT` | 单日亏损上限 |
| 连续亏损 | 3次 | `V15_MAX_CONSECUTIVE_LOSSES` | 连续亏损暂停阈值，触发资金管理引擎重新优化 |
| 保证金高危线 | 80% | 代码硬编码 | 保证金占比超80%高风险 |
| 轮询间隔 | 3600s | `V15_POLL_INTERVAL` | 策略轮询周期 |

### 12.3 多空方向验证链

```
方向控制层:
  direction_gate.py (DirectionGate)
    ├─ V15_ALLOW_SHORT=false → 永远 LONG_PREFERRED (只做多)
    ├─ BTC做空闸门关闭(btc_short_enabled=false) → LONG_PREFERRED (只做多)
    ├─ BTC做空闸门打开 + 价格在周MA200上方 → SHORT_ALLOWED (允许做空)
    ├─ 跌至周MA200附近(含1%缓冲带) → LONG_ONLY_FORCE (强制做多)
    └─ 有效跌破判断：连续3日收盘价低于日MA128 + 收盘价确认，避免频繁切换

信号层:
  v15_signal.py
    ├─ direction_ctx=None (V15_ALLOW_SHORT=false) → 只产生 OPEN_BULL/WAIT
    ├─ direction_ctx.short_enabled=True → BELOW_ALL走16层做空镜像 → OPEN_BEAR
    └─ 输出 action: "OPEN_BULL" / "OPEN_BEAR" / "WAIT"

执行层:
  v15_trader.py (根据 pos["direction"] 判断)
    ├─ 做多开仓: side="buy",  pos_side="long"
    ├─ 做空开仓: side="sell", pos_side="short"
    ├─ 做多加仓: side="buy",  pos_side="long"  (下跌加仓)
    ├─ 做空加仓: side="sell", pos_side="short" (上涨加仓，反向马丁)
    ├─ 做多平仓: side="sell", pos_side="long"
    └─ 做空平仓: side="buy",  pos_side="short"

止损层:
  strategy_params.py get_dynamic_stop_loss()
    ├─ LONG: 止损线 = 价格下方最近均线, 触发 = 收盘价 <= 止损线
    └─ SHORT: 止损线 = 价格上方最近均线, 触发 = 收盘价 >= 止损线

测试:
  tests/test_short_selling.py (26项测试全通过)
    ├─ DirectionGate三状态模型 (4项)
    ├─ 边界情况与缓冲带 (6项)
    ├─ GateResult序列化 (2项)
    ├─ 做空执行逻辑Mock验证 (5项)
    ├─ 做多向后兼容 (2项)
    ├─ SHORT止损逻辑 (4项)
    └─ 状态转移完整性 (3项)
```

---

## 13. OCO止盈止损挂单系统

### 13.1 核心设计思想

传统马丁策略的止盈止损完全依赖软件轮询监控，存在程序宕机/网络中断时无法执行的风险。OCO（One-Cancels-the-Other）止盈止损挂单系统通过在交易所层面同步设置条件单，实现"程序离线也生效"的硬性保护，与软件监控形成双重保障。

### 13.2 双重保障架构

```
┌─────────────────────────────────────────────────────────────┐
│  L1: 交易所 OCO 挂单（硬性保护）                              │
│  • 开仓后立即在交易所挂 OCO 条件单                           │
│  • 止盈/止损互斥：触发任一个自动撤销另一个                   │
│  • 程序离线/网络中断时仍能触发                               │
│  • 市价触发（slOrdPx=-1, tpOrdPx=-1）                       │
└─────────────────────────────────────────────────────────────┘
                          ↓ 互补
┌─────────────────────────────────────────────────────────────┐
│  L2: 软件轮询监控（动态增强）                                │
│  • check_take_profit() 每轮检查止盈条件                     │
│  • 动态止损线（MA200/EMA200）实时跟踪                       │
│  • 多因子判断（收盘价确认、缓冲带等）                        │
│  • 止损线移动 > 0.5% 时自动同步更新挂单                      │
└─────────────────────────────────────────────────────────────┘
```

### 13.3 核心函数

#### `_sync_tp_sl_orders()` — 止盈止损挂单同步

```python
def _sync_tp_sl_orders(client, coin, pos, entry_price, tp_pct, sl_price):
    """
    同步设置/更新 OCO 止盈止损条件单
    - 先取消旧条件单（cancel_algo_orders）
    - 止损价方向一致性校验（做多SL<Entry，做空SL>Entry）
    - 止损价有效时下OCO单，无效时降级为仅止盈单
    """
```

#### `_update_tp_sl_dynamic()` — 轮询动态更新

```python
def _update_tp_sl_dynamic(client, coin, pos):
    """
    每次轮询检查止盈/止损价格变化
    - 变化 > 0.5% 才更新（防抖，避免频繁撤单）
    - 动态止损线（MA200等）移动时自动同步
    """
```

### 13.4 挂单生命周期

```
开仓 (execute_open_position)
  │
  ├── 1. 下开仓市价单
  ├── 2. 记录持仓状态（entry_price, tp_pct, sl_price等）
  └── 3. _sync_tp_sl_orders() → 挂OCO单
         │
         ├── cancel_algo_orders(inst_id)  ← 取消旧单
         └── place_stop_loss_take_profit() ← 下新OCO单
             ├── 止盈价 = entry × (1 + tp_pct)   [做多]
             ├── 止损价 = sl_price               [来自策略参数]
             └── 数量 = pos.sz                   [全部持仓]

加仓 (execute_addon)
  │
  ├── 1. 下加仓市价单
  ├── 2. 更新均价和数量
  └── 3. _sync_tp_sl_orders() → 撤旧单+挂新单
         └── 止盈价基于新均价重算，数量更新为总仓位

轮询 (run_poll_cycle)
  │
  ├── check_take_profit() → 止盈/止损触发？
  │   ├── 是 → cancel_algo_orders() → 市价平仓
  │   └── 否 → check_time_exit() → 超时？
  │       ├── 是 → _execute_close_position() → cancel + 平仓
  │       └── 否 → execute_addon() → 加仓？
  │           ├── 是 → _sync_tp_sl_orders()
  │           └── 否 → _update_tp_sl_dynamic() → 价格变化>0.5%？
  │               └── 是 → _sync_tp_sl_orders()

平仓 (_execute_close_position)
  │
  ├── 1. cancel_algo_orders(inst_id)  ← 取消所有条件单
  └── 2. 市价平仓
```

### 13.5 多空方向止盈止损价格计算

| 方向 | 止盈价 | 止损价 | 平仓方向 |
|------|--------|--------|----------|
| 做多 (LONG) | entry × (1 + tp_pct) | sl_price < entry | side=sell, pos_side=long |
| 做空 (SHORT) | entry × (1 - tp_pct) | sl_price > entry | side=buy, pos_side=short |

### 13.6 止损价无固定价格时的安全网机制

当策略止损类型为 `BELOW_ALL_MA_INTRADAY`（无固定价格，依赖实时均线判断）时，在强平价上方设置安全网止损价，防止极端行情下被交易所强平：

| 场景 | 处理方式 | 示例 |
|------|---------|------|
| 止损价有效（MA200/EMA200） | OCO 单（止盈+止损） | INJ: SL=$4.613 (日EMA200) |
| 止损价为 null（BELOW_ALL_MA） | OCO 单 + 安全网止损 | BTC: SL=$57,000 (强平价$56,608上方) |

### 13.7 OKX API 参数

#### OCO 单（止盈+止损同时设置）

```python
body = {
    "instId": "BTC-USDT-SWAP",
    "tdMode": "isolated",
    "side": "sell",            # 做多平仓=sell, 做空平仓=buy
    "ordType": "oco",
    "sz": "0.03",
    "posSide": "long",         # 持仓方向
    "slTriggerPx": "57000",    # 止损触发价
    "slOrdPx": "-1",           # 市价触发
    "tpTriggerPx": "65119",    # 止盈触发价
    "tpOrdPx": "-1",           # 市价触发
}
```

#### 仅止盈/仅止损单（conditional 类型）

当只需要止盈或止损其中一个时，使用 `conditional` 类型配合 `tpTriggerPx`/`slTriggerPx` 参数。

### 13.8 实盘持仓挂单记录（2026-07-14）

| 币种 | 方向 | 均价 | 止盈价 | 止盈% | 止损价 | 止损类型 | OCO algo_id |
|------|------|------|--------|-------|--------|----------|-------------|
| BTC | long | $62,614 | $65,119 | 4.0% | $57,000 | 安全网(强平价上方) | 3742732068829507584 |
| INJ | long | $4.986 | $5.434 | 9.0% | $4.613 | 日EMA200 | 3742728693589192704 |
| TIA | long | $0.4054 | $0.4442 | 9.6% | $0.3844 | 日MA200 | 3742728719728095232 |
| WLD | long | $0.4022 | $0.4424 | 10.0% | $0.3927 | 日MA200 | 3742728737847488512 |
| ZEC | long | $504.36 | $554.80 | 10.0% | $424.32 | 日EMA200 | 3742728764389044224 |

---

## 14. 币种风控过滤系统

### 14.1 核心设计思想

马丁策略的本质是"逆势加仓摊平成本"，在单边行情中通过加仓降低均价，等待反弹获利。然而两类币种会给马丁策略带来致命风险：

1. **小市值/meme币**：流动性差，易被操控，单日暴涨暴跌100%+司空见惯，马丁加仓会被瞬间击穿
2. **新币**：上线时间短，历史数据不足，价格发现不充分，上线初期常伴随极端波动

币种风控过滤系统通过"市值等级 + 上线时间"双重维度，在币种池加载阶段即剔除高风险币种，从源头杜绝黑天鹅风险。

### 14.2 双重过滤架构

```
┌─────────────────────────────────────────────────────────────┐
│  L1: 配置层过滤（.env.v15）                                  │
│  • V15_COINS 配置直接排除小市值和新币                        │
│  • 34个原始币种精简至30个                                    │
│  • 剔除: PEPE, SHIB, SUSHI, WLD, APE                        │
└─────────────────────────────────────────────────────────────┘
                          ↓ 互补
┌─────────────────────────────────────────────────────────────┐
│  L2: 运行时过滤（is_martin_safe）                            │
│  • 即使配置误加小市值/新币，运行时也会自动拦截               │
│  • 市值等级校验：LARGE > MID > SMALL                        │
│  • 上线时间校验：days(today - listing_date) ≥ 365          │
│  • 启动时输出剔除日志，透明可审计                            │
└─────────────────────────────────────────────────────────────┘
```

### 14.3 市值等级分类

| 等级 | 定义 | 马丁策略 | 币种示例 |
|------|------|----------|----------|
| LARGE | 大市值（Top 20），流动性深，黑天鹅风险低 | ✅ 通过 | BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LTC, LINK, AVAX, DOT, TRX, MATIC, ATOM, UNI, NEAR, APT, FIL, ARB, OP, OKB, XAUT, PAXG |
| MID | 中等市值（Top 20-60），流动性尚可 | ✅ 通过 | INJ, SUI, SEI, TIA, RUNE, AAVE, ALGO, AXS, CHZ, COMP, CRV, DYDX, GALA, GRT, IMX, LDO, MKR, RNDR, SAND, STX, ZEC, HYPE |
| SMALL | 小市值/高波动meme币，黑天鹅风险高 | ❌ 剔除 | APE, PEPE, SHIB, SUSHI, WLD |

### 14.4 核心数据结构

#### MarketCapTier 枚举

```python
class MarketCapTier(str, Enum):
    """市值等级（用于马丁策略风控过滤）"""
    LARGE = "large"   # 大市值：Top 20，流动性深，黑天鹅风险低
    MID = "mid"       # 中等市值：Top 20-60，流动性尚可
    SMALL = "small"   # 小市值：排名靠后或高波动meme币，黑天鹅风险高
```

#### AssetInfo 扩展字段

```python
@dataclass
class AssetInfo:
    # ... 原有字段 ...
    # ── 马丁风控字段 ──
    market_cap_tier: MarketCapTier = MarketCapTier.MID  # 市值等级
    listing_date: Optional[str] = None       # 上线日期 ISO 格式 "YYYY-MM-DD"
```

### 14.5 核心函数

#### `is_martin_safe()` — 单币种风控检查

```python
def is_martin_safe(
    coin: str,
    min_tier: MarketCapTier = MarketCapTier.MID,
    min_history_days: int = 365,
) -> bool:
    """
    马丁策略风控检查：市值等级 + 上线时间双重过滤

    Args:
        coin: 币种符号
        min_tier: 最低市值等级（LARGE > MID > SMALL），默认 MID
        min_history_days: 最小上线天数，默认 365 天（1年）

    Returns:
        True = 通过风控检查，可纳入马丁策略
        False = 不通过（小市值 或 上线时间不足 或 未知币种）
    """
```

#### `filter_martin_safe()` — 批量过滤

```python
def filter_martin_safe(
    coins: List[str],
    min_tier: MarketCapTier = MarketCapTier.MID,
    min_history_days: int = 365,
) -> List[str]:
    """批量过滤出通过马丁风控检查的币种"""
```

### 14.6 币种加载流程

```
v15_trader.py 启动
  │
  ├─→ 1. 加载 V15_COINS 配置（_RAW_COINS）
  │
  ├─→ 2. OKX支持过滤（_OKX_SUPPORTED）
  │      └─→ _coin_supported(coin, "okx")
  │
  ├─→ 3. 马丁风控过滤（COINS）
  │      └─→ _coin_martin_safe(coin, min_tier, min_history_days)
  │           ├─ 市值等级检查：coin_level ≥ min_level
  │           └─ 上线时间检查：days_listed ≥ min_history_days
  │
  └─→ 4. 启动日志输出
       ├─ "马丁策略币种池: 原始=N个, OKX支持=M个, 风控通过=K个"
       ├─ "马丁风控剔除币种: PEPE,SHIB,... - 原因: 小市值或上线时间不足"
       └─ "最终马丁币种池: BTC,ETH,SOL,..."
```

### 14.7 配置参数

```ini
# config/.env.v15

# 最低市值等级: large(仅大市值) / mid(大+中市值，推荐) / small(全部)
V15_MARTIN_MIN_TIER=mid

# 最小上线天数: 新币暴涨暴跌风险大，要求至少1年历史数据
V15_MARTIN_MIN_HISTORY_DAYS=365
```

### 14.8 风控过滤效果

| 阶段 | 币种数 | 说明 |
|------|--------|------|
| 原始配置 | 34 | V15_COINS 全量 |
| 配置层精简 | 30 | 剔除 PEPE/SHIB/SUSHI/WLD/APE |
| 运行时风控 | 30 | 全部通过 is_martin_safe 校验 |
| 注册表总量 | 50 | SymbolMapper 注册的全部币种 |
| 风控安全 | 44 | 50 个中 44 个通过风控（含未在配置中的币种） |

### 14.9 HYPE 特殊处理

HYPE（Hyperliquid）作为 Hyperliquid 平台代币，上线于 2024-11-29。尽管上线时间较短（约1年），但因其平台潜力和用户明确要求，从 SMALL 提升至 MID 等级：

| 调整项 | 调整前 | 调整后 |
|--------|--------|--------|
| market_cap_tier | SMALL | MID |
| martin_enabled | False | True |
| is_martin_safe | False | True |

### 14.10 测试验证

`tests/test_symbol_mapper.py` 新增 `TestMartinSafeFilter` 测试类（16项测试）：

| 测试项 | 验证内容 |
|--------|----------|
| test_market_cap_tier_large | BTC/ETH/OKB 为 LARGE |
| test_market_cap_tier_mid | INJ/AAVE/ZEC/HYPE 为 MID |
| test_market_cap_tier_small | PEPE/SHIB/APE 为 SMALL |
| test_market_cap_tier_unknown | 未知币种返回 None |
| test_listing_date | 上线日期查询 |
| test_is_martin_safe_large_passes | 大市值通过 |
| test_is_martin_safe_mid_passes | 中市值通过（含HYPE） |
| test_is_martin_safe_small_rejected | 小市值被剔除 |
| test_is_martin_safe_unknown_rejected | 未知币种被剔除 |
| test_is_martin_safe_large_only_tier | min_tier=large 时 MID 被剔除 |
| test_is_martin_safe_small_tier_allows_all | min_tier=small 时全部通过 |
| test_is_martin_safe_min_history_days | 上线时间阈值过滤 |
| test_filter_martin_safe_batch | 批量过滤 |
| test_small_cap_martin_disabled | 小市值 martin_enabled=False |
| test_hype_martin_enabled | HYPE 已提升至 MID |
| test_module_level_* | 模块级便捷函数 |

---

## 15. 智能系统增强（ATR动态止盈+移动止盈+ELDER-RAY资金调度+凯利公式）

### 15.1 核心设计思想

V15 智能系统在经典马丁策略基础上增加四项增强机制，通过动态参数自适应提升收益和风险控制能力。智能系统全开时回测收益从 138%（固定参数基线）提升至 210.4%（智能参数基线）。

```
┌─────────────────────────────────────────────────────────────┐
│  智能系统增强层（v5.0）                                       │
│  ├─ ATR动态止盈：BTC 4%基准，按ATR百分比动态调整             │
│  ├─ 移动止盈：浮盈达80%启动，从峰值回撤N×ATR止盈             │
│  ├─ ELDER-RAY资金调度：趋势强度调整仓位（0.9-1.5x基线）      │
│  └─ 凯利公式底仓优化：半凯利+收缩估计（默认关闭，可选启用）   │
└─────────────────────────────────────────────────────────────┘
```

### 15.2 ATR动态止盈

**设计理念：** BTC 止盈固定 4%，其他币种按 30 日波动率放大。ATR 动态止盈在此基础上引入 ATR（平均真实波幅）因子，根据近期波动率微调止盈比例。

**实现位置：** `lib/strategy_params.py` → `calc_atr()` + `get_vol_adjusted_params()`

```python
# ATR计算（4H K线，14周期）
calc_atr(klines, period=14):
    TR = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR = SMA(TR, period)

# ATR百分比 = ATR / 当前价格
atr_pct = calc_atr_pct(klines_4h)

# 动态止盈：BTC 4%基准，其他币种 = 4% × vol_ratio × atr_factor
# vol_ratio = coin_volatility / btc_volatility（限制0.5-2.0）
```

**关键参数：**
- BTC：固定 4%（`tp_pct_btc=0.04`），不按波动率放大
- 其他币种：4% × 波动率倍数 × ATR因子

### 15.3 移动止盈（Trailing Take-Profit）

**设计理念：** 传统马丁策略达到固定止盈比例即平仓，可能错过趋势延续的利润。移动止盈在浮盈达到启动阈值后，从最高盈利点回撤 N×ATR 时才止盈，让利润奔跑。

**实现位置：**
- `core/v15_backtest.py` → `use_trailing_tp=True` 参数（回测引擎）
- `core/v15_trader.py` → `check_take_profit()` 中集成（实盘交易器，v5.1 新增）

**实盘集成（v5.1）：**
- 参数从 `active_params.json` 加载（`trailing_atr_mult`, `trailing_start_ratio`）
- 配置开关：`V15_USE_TRAILING_TP=true`（默认启用）
- 持仓状态新增字段：`trailing_active`, `trailing_price`, `peak_price`
- 移动止盈在固定止盈之前检查，优先级更高
- ATR 从 4H K线实时计算（`calc_atr_pct()`）

**触发流程：**
```
check_take_profit() 每轮轮询:
  ├─ 移动止盈检查（启用且 profit > 0 时）
  │    ├─ 计算 ATR%（4H K线，14周期）
  │    ├─ 更新峰值价格 peak_price
  │    ├─ 浮盈 >= start_ratio × tp_pct → 激活移动止盈
  │    │    └─ 计算 trailing_price = peak ∓ atr_mult × ATR_price
  │    │       （做多: peak - N×ATR，做空: peak + N×ATR）
  │    │       （只向有利方向移动，不回退）
  │    └─ 移动止盈激活后:
  │         价格回撤至 trailing_price → 止盈平仓
  │
  ├─ 固定止盈检查（移动止盈未触发时）
  │    └─ profit_pct >= tp_pct（使用 pos 中 RAISE_TP 提高后的值）
  │
  └─ 动态止损检查
```

**参数说明：**
| 参数 | 说明 | 默认值 | 优化范围 |
|------|------|--------|----------|
| `trailing_atr_mult` | 回撤ATR倍数（1.0=1倍ATR回撤止盈） | 1.0 | 1.0-2.5 |
| `trailing_start_ratio` | 启动阈值（占止盈比例，0.8=浮盈达80%启动） | 0.8 | 0.3-0.8 |

**示例：** tp_pct=4%, trailing_start_ratio=0.8, trailing_atr_mult=1.0
- 浮盈达 3.2%（4%×0.8）启动移动止盈
- 峰值盈利 5%，ATR=1.5% → 回撤 1.5% 止盈（即盈利降至 3.5% 时平仓）

### 15.4 ELDER-RAY 资金调度

**设计理念：** 经典马丁策略对所有信号一视同仁分配资金。ELDER-RAY 资金调度根据日线趋势强度动态调整仓位大小——强趋势时加大仓位，弱趋势时减小仓位。

**实现位置：**
- `core/v15_backtest.py` → `calc_elder_ray_size_mult()` + 模块级变量 `_elder_ray_floor` / `_elder_ray_ceil`
- `lib/capital_manager.py` → `calculate_per_coin_allocation()`（实盘，0.3-1.5x 宽范围）

**仓位调整逻辑：**
```python
calc_elder_ray_size_mult(elder_ray_result):
    strength = elder_ray_result['strength']  # 0-100
    direction = elder_ray_result['direction']

    # 基础倍数：强度越高，仓位越大
    strength_mult = 0.5 + (strength / 100) * 1.0  # 0.5-1.5

    # 趋势方向加成
    if direction in ['STRONG_BULL', 'BULL_TREND']:
        strength_mult *= 1.1  # 上升趋势加成
    elif direction in ['STRONG_BEAR', 'BEAR_TREND']:
        strength_mult *= 0.7  # 下降趋势降仓

    # 边界约束（可被贝叶斯优化器动态调整）
    return max(_elder_ray_floor, min(_elder_ray_ceil, strength_mult))
```

**两套范围说明：**
| 场景 | 范围 | 文件 | 说明 |
|------|------|------|------|
| 实盘交易 | 0.3-1.5x | `capital_manager.py` | 宽范围，强熊市可降至0.3x控风险 |
| 回测/优化基线 | 0.9-1.5x | `v15_backtest.py` | 窄范围，优化器参数空间(0.5-0.9, 1.2-1.5) |

### 15.5 凯利公式底仓优化

**设计理念：** 经典马丁策略底仓固定 22%。凯利公式根据历史胜率和盈亏比计算最优底仓比例，半凯利+收缩估计提供更科学的资金管理。

**实现位置：** `lib/kelly_optimizer.py`

**状态：** 默认关闭（`use_kelly=False`），可选启用

**算法：**
```python
# 凯利比例：f = (bp - q) / b
# b = 盈亏比, p = 胜率, q = 1 - p
# 半凯利：f_kelly / 2（降低风险）
# 收缩估计：向0.5收缩，避免小样本过拟合
```

**参数：**
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `use_kelly` | 是否启用凯利公式 | False（关闭） |
| `kelly_shrinkage` | 收缩估计系数 | 0.3 |
| `kelly_max_pct` | 凯利底仓上限 | 0.30（30%） |
| `kelly_min_pct` | 凯利底仓下限 | 0.15（15%） |

---

## 16. BTC风向标智能模式选择

### 16.1 核心设计思想

不同币种对 BTC 风向标的响应不同。BTC 作为市值最大的加密货币，其走势具有独立性；而其他山寨币（altcoins）高度跟随 BTC 走势。因此系统对不同币种采用不同的方向控制策略。

### 16.2 智能模式自动选择

```python
# core/v15_backtest.py - run_backtest()
if not use_btc_windvane and not use_direction_gate:
    # 智能模式自动选择
    if coin.upper() == "BTC":
        use_direction_gate = True           # BTC用自身MA200+DirectionGate
    else:
        use_btc_windvane = True             # 其他币用BTC风向标
        btc_windvane_confirm_days = 3       # 3日确认
        btc_windvane_short_only = True      # SHORT_ALLOWED只允许做空
```

### 16.3 两套方向控制策略

| 币种 | 策略 | 止损机制 | 方向控制 | 理由 |
|------|------|----------|----------|------|
| BTC | DirectionGate + 自身MA200 | 各币种MA200动态止损 | MA128三状态模型 | BTC走势独立，用自身指标更准确 |
| 其他币 | BTC风向标3日确认 | 移除各币种MA200，用BTC MA200全局控方向 | BTC跌破MA200→做空，触及周MA200→做多 | 山寨币跟随BTC，用BTC风向标更稳定 |

### 16.4 BTC风向标三状态

| 状态 | 触发条件 | 允许方向 | 说明 |
|------|----------|----------|------|
| LONG_ONLY | BTC在日MA200上方 | 只做多 | 默认状态，震荡+多头行情 |
| SHORT_ALLOWED | BTC连续3日收盘价低于日MA200 | 只做空（`short_only=True`） | 暴跌阶段，做空价值较高 |
| LONG_ONLY_FORCE | BTC触及周线MA200 | 强制做多 | 下跌末端，做空风险高 |

### 16.5 回测验证结果

BTC风向标3日确认 + SHORT_ALLOWED只做空模式，对山寨币回测效果显著：

| 币种 | 只做多 | 风向标3日+short_only | 改善 |
|------|--------|---------------------|------|
| ETH | 负收益 | 正收益 | 收益转正 |
| SOL | 负收益 | +5.83% | 大幅改善 |
| OP | 负收益 | +6.77% | 大幅改善 |
| UNI | 负收益 | +4.11% | 收益转正 |

**总收益提升：** 从 +124.50%（固定参数）→ +134.28%（风向标模式）→ +210.4%（智能基线+贝叶斯优化）

---

## 17. 贝叶斯优化自动调度与双基线版本管理

### 17.1 自动调度架构

贝叶斯优化通过 `orchestrator.py` 集成到系统调度中，独立于交易运行，后台执行不阻塞交易。

```
┌─────────────────────────────────────────────────────────────┐
│  orchestrator.py（每15分钟被cron调用）                        │
│  ├─ check_bayesian_optimization_trigger()                    │
│  │    ├─ 读取 .env.v15 调度配置                               │
│  │    ├─ 读取 v15_state.json 连亏笔数                         │
│  │    └─ 调用 should_trigger_optimization() 判断              │
│  │                                                            │
│  ├─ should_trigger_optimization()                            │
│  │    ├─ 条件1: 连亏 ≥ 3笔（事件驱动，最高优先级）            │
│  │    ├─ 条件2: 跨月触发（周期驱动）                          │
│  │    └─ 冷却期检查: 距上次优化 < 24h → 跳过                  │
│  │                                                            │
│  └─ run_bayesian_optimization()                              │
│       ├─ PID锁检查（防重复运行）                              │
│       └─ 后台启动: python3 bayesian_optimizer.py --with-rollback │
│            └─ 独立进程组，不阻塞交易                           │
└─────────────────────────────────────────────────────────────┘
```

### 17.2 调度配置

```ini
# config/.env.v15

# ── 贝叶斯优化自动调度（连亏触发+每月轮询+冷却期+自动回退）──
BAYESIAN_OPT_LOSS_STREAK_TRIGGER=3      # 连续亏损3笔触发
BAYESIAN_OPT_WEEKLY=false               # 每周触发（已关闭，避免过拟合）
BAYESIAN_OPT_MONTHLY=true               # 每月触发（跨月检查）
BAYESIAN_OPT_MIN_IMPROVE_PCT=2.0        # 优化收益需比基线高2%才采用
BAYESIAN_OPT_COOLDOWN_HOURS=24          # 冷却期：距上次优化24h内不重复触发
```

### 17.3 触发条件优先级

| 优先级 | 条件 | 说明 | 冷却期约束 |
|--------|------|------|------------|
| 1（最高） | 连亏 ≥ 3笔 | 事件驱动，市场状态已变化 | 冷却期内仍检查（避免短时间连续触发） |
| 2 | 跨月 | 周期驱动，每月轮询 | 冷却期内不触发 |
| 3 | 首次运行 | 无历史记录 | 无冷却期约束 |

**冷却期设计：**
- 连亏触发有最高优先级，但冷却期内（24h）仍受约束
- 设计目的：避免市场剧烈波动时1-2天内连续触发优化
- 连亏冷却期内会记录原因："连亏N笔但冷却期内（Xh < 24h）"

### 17.4 触发频率评估

> **回测窗口分析：** 1500根4H K线 ≈ 250天数据，每周新增7天仅占2.8%，频繁优化收益递减且过拟合风险高。

| 触发方式 | 频率 | 评估 | 是否启用 |
|----------|------|------|----------|
| 连亏3笔 | 事件驱动 | 市场状态变化时才触发，合理 | ✅ 启用 |
| 每周 | 7天一次 | 数据增量仅2.8%，过拟合风险高 | ❌ 关闭 |
| 每月 | 30天一次 | 数据增量约12%，平衡点 | ✅ 启用 |
| 冷却期24h | 限制 | 避免短时间连续触发 | ✅ 启用 |

### 17.5 双基线版本管理

**版本元数据（`VERSION_INFO`）：**

| 版本 | 名称 | 收益 | 创建日期 | 特性 |
|------|------|------|----------|------|
| v1.0 | 固定参数基线 | 138.0% | 2026-07-15 | 固定止盈4%/固定加仓间隔8%/无ATR/无移动止盈/无ELDER-RAY/仅做多 |
| v2.0 | 智能参数基线 | 210.4% | 2026-07-16 | ATR动态止盈/移动止盈/ELDER-RAY资金调度(0.9-1.5x)/BTC风向标3日确认/多空方向门控 |

**智能参数基线最优参数（`SMART_BASELINE_PARAMS`）：**
```python
{
    'trailing_atr_mult': 1.0,
    'trailing_start_ratio': 0.8,
    'elder_ray_floor': 0.9,
    'elder_ray_ceil': 1.5,
    'btc_windvane_confirm_days': 3,
    'max_base_holding_hours': 29.9,
    'max_post_addon_hours': 37.7,
    'golden_window_hours': 11.1,
}
# 来源: bayesian_optimization, 优化ID: v15_optimization_20260715_192704, 最优评分: 4112.87
```

### 17.6 活跃参数管理

**活跃参数文件：** `data/bayesian_opt/active_params.json`

```json
{
  "params": { ... },           // 当前生效的参数
  "source": "manual_reset_to_smart",  // 来源（optimization/rollback/manual）
  "score": 4112.87,            // 优化评分
  "timestamp": "2026-07-16T..."  // 更新时间
}
```

**参数来源类型：**
| source | 说明 |
|--------|------|
| `bayesian_optimization` | 贝叶斯优化采用（improvement ≥ 2%） |
| `smart_baseline_rollback` | 优化无效回退到智能基线 |
| `fixed_baseline_rollback` | 终极回退到固定基线 |
| `manual_reset_to_smart` | 手动重置为智能基线 |
| `manual_reset_to_fixed` | 手动终极回退 |

### 17.7 调度状态管理

**调度状态文件：** `data/bayesian_opt/schedule_state.json`

```json
{
  "last_optimize_ts": "2026-07-16T...",  // 上次优化时间（ISO格式）
  "last_action": "adopted",               // 上次动作（adopted/rolled_back）
  "last_improvement": 5.23                // 上次收益改善（%）
}
```

**首次运行：** `schedule_state.json` 不存在时，`should_trigger_optimization()` 返回 `True`（首次运行优化），优化完成后由 `_save_schedule_state()` 创建。

---

_最后更新：2026-07-16 | 来源：14-V15经典马丁策略（独立V15系统）_
