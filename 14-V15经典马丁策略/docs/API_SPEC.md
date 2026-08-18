# 接口规格文档 — V15 经典马丁策略

> **定位：** 全部公开函数的签名、参数、返回值、调用示例
> **版本：** v3.1 | **更新：** 2026-07-13

---

## 目录

- [1. 信号引擎 (core/v15_signal.py)](#1-信号引擎-corev15_signalpy)
- [2. 交易执行器 (core/v15_trader.py)](#2-交易执行器-corev15_traderpy)
- [3. 回测引擎 (core/v15_backtest.py)](#3-回测引擎-corev15_backtestpy)
- [4. 市场数据 (lib/market_data.py)](#4-市场数据-libmarket_datapy)
- [5. 策略参数 (lib/strategy_params.py)](#5-策略参数-libstrategy_paramspy)
- [6. 资金管理 (lib/capital_manager.py)](#6-资金管理-libcapital_managerpy)
- [7. 配置加载 (lib/config_loader.py)](#7-配置加载-libconfig_loaderpy)
- [8. OKX 客户端 (lib/okx_client.py)](#8-okx-客户端-libokx_clientpy)
- [9. 入口脚本 (run.py)](#9-入口脚本-runpy)
- [10. 资金管理引擎 (experiments/ab-trading/capital_manager_engine.py)](#10-资金管理引擎-experimentsab-tradingcapital_manager_enginepy)
- [11. 连续亏损触发机制 (v15ct_trader.py)](#11-连续亏损触发机制-v15ct_traderpy)

---

## 1. 信号引擎 (core/v15_signal.py)

### 1.1 v15_decision

**核心决策函数 — 生成交易信号**

```python
def v15_decision(spot_inst: str = "BTC-USDT",
                 price: float = None,
                 timeframe: str = "4H",
                 limit: int = 200) -> dict
```

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| spot_inst | str | "BTC-USDT" | 现货交易对标识 |
| price | float | None | 指定当前价格（None则用K线最新收盘价） |
| timeframe | str | "4H" | K线周期 |
| limit | int | 200 | K线数量 |

**返回值：**

```python
{
    # 核心决策
    "action": "OPEN_BULL",          # str: "OPEN_BULL" | "WAIT"
    "confidence": 75,               # int: 0-100
    "reasons": ["Fib黄金区入场", "RSI=42.5<55"],  # list[str]: 决策理由
    "mode": "v15",                  # str: 固定 "v15"
    "vol_mult": 1.2,                # float: 波动率倍数 (0.7-1.3)

    # 市场状态
    "position": "ABOVE_ALL",        # str: "ABOVE_ALL" | "IN_ZONE" | "BELOW_ALL"
    "fib_zone": "golden",           # str: "golden" | "shallow" | None
    "trend_signal": None,           # str: "macd_bull" | "adx_bull" | None
    "boll_signal": "near_mid",      # str: "touch_lower" | "near_mid" | "rsi_extreme" | None
    "rsi": 42.5,                    # float: RSI值

    # 指标数据
    "smas": {30: 67123.5, 65: 65432.1, 128: 63000.0, 200: 58000.0},
    "fib": {"swing_high": 70000, "swing_low": 60000, "f382": 66180, "f500": 65000, "f618": 63820},
    "boll": {"sma": 66000, "upper": 68000, "lower": 64000, "std": 1000, "bandwidth": 6.06, "pct_b": 0.5},
    "macd": {"macd": 120.5, "signal": 80.3, "hist": 40.2, "hist_prev": 35.1,
             "cross": False, "expanding": True, "bullish": True, "bearish": False},
    "adx": {"adx": 28.5, "strong": True, "very_strong": False, "di_plus": 25.3, "di_minus": 15.2},

    # 新增指标数据
    "pivot": {"pivot": 67000.0, "r1": 68000.0, "r2": 69000.0, "r3": 70000.0,
              "s1": 66000.0, "s2": 65000.0, "s3": 64000.0,
              "support_zone": True, "resistance_zone": False,
              "near_s1": False, "near_pivot": False, "near_r1": False},
    "obv": {"obv": 123456.0, "obv_ma": 120000.0, "trend": "BULL",
            "bullish": True, "accelerating": True, "divergence": False},
    "supertrend": {"upper_band": 70000.0, "lower_band": 64000.0, "trend": "BULL",
                   "bullish": True, "reversal": False, "atr": 1500.0, "distance_pct": 4.69},
    "keltner": {"upper": 69000.0, "middle": 67000.0, "lower": 65000.0,
                "position": 0.5, "near_lower": False, "near_middle": True,
                "near_upper": False, "bandwidth": 5.97},
    "stochrsi": {"k": 25.5, "d": 30.2, "cross": "golden",
                 "oversold": False, "overbought": False, "bullish": True},
    "vortex": {"vi_plus": 1.15, "vi_minus": 0.87, "direction": "BULL",
               "bullish": True, "reversal": True, "strength": 2.8},
    "tema": {"tema": 67500.0, "direction": "BULL", "bullish": True,
             "slope": 0.15, "distance_pct": 0.75},
    "golden_cross": {"ema_fast": 68000.0, "ema_slow": 65000.0, "cross": "golden",
                     "direction": "BULL", "bullish": True, "distance_pct": 4.62},
    "ema_align": {"emas": {20: 69000.0, 50: 67000.0, 200: 63000.0},
                  "direction": "BULL", "bullish": True, "aligned": True, "alignment_score": 0.85},
}
```

**错误返回（K线获取失败/数据异常）：**

```python
{"action": "WAIT", "confidence": 0, "reasons": ["无法获取K线数据"], "mode": "v15", "vol_mult": 1.0}
```

**调用示例：**

```python
from v15_signal import v15_decision

# 默认调用
result = v15_decision("BTC-USDT")

# 指定价格
result = v15_decision("ETH-USDT", price=3500)

# 全参数
result = v15_decision("SOL-USDT", price=150, timeframe="4H", limit=300)
```

---

### 1.2 calc_sma

```python
def calc_sma(values: list, period: int) -> float | None
```

计算简单移动平均。数据不足返回 None。

---

### 1.3 calc_rsi

```python
def calc_rsi(prices: list, period: int = 14) -> float
```

计算 RSI。数据不足返回 50.0（中性），avg_loss=0 返回 100.0。

---

### 1.4 determine_position

```python
def determine_position(price: float, smas: dict) -> str
```

判断价格与均线位置关系。返回 `"ABOVE_ALL"` / `"BELOW_ALL"` / `"IN_ZONE"`。

---

### 1.5 calc_fibonacci

```python
def calc_fibonacci(prices: list, lookback: int = 30) -> dict
```

计算斐波那契回调位。返回 `{"swing_high", "swing_low", "f382", "f500", "f618"}`。

---

### 1.6 calc_bollinger_bands

```python
def calc_bollinger_bands(prices: list, period: int = 20, num_std: int = 2) -> dict
```

计算布林带。返回 `{"sma", "upper", "lower", "std", "bandwidth", "pct_b"}`。

---

### 1.7 calc_macd

```python
def calc_macd(prices: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict
```

计算 MACD。返回 `{"macd", "signal", "hist", "hist_prev", "cross", "expanding", "bullish", "bearish"}`。

---

### 1.8 calc_adx

```python
def calc_adx(prices: list, period: int = 14) -> dict
```

计算 ADX（Wilder平滑法）。返回 `{"adx", "strong", "very_strong", "di_plus", "di_minus"}`。

---

### 1.9 calc_pivot_points

```python
def calc_pivot_points(highs: list, lows: list, closes: list, period: int = 1) -> dict | None
```

计算枢轴点（Pivot Points）及支撑/阻力位。数据不足返回 None。

**返回值：**

```python
{
    "pivot": 67000.0, "r1": 68000.0, "r2": 69000.0, "r3": 70000.0,
    "s1": 66000.0, "s2": 65000.0, "s3": 64000.0,
    "support_zone": True,     # s1 <= price <= pivot
    "resistance_zone": False, # pivot <= price <= r1
    "near_s1": False,         # price接近s1
    "near_pivot": False,      # price接近pivot
    "near_r1": False,         # price接近r1
}
```

---

### 1.10 calc_obv

```python
def calc_obv(prices: list, volumes: list) -> dict | None
```

计算能量潮指标（OBV）。数据不足返回 None。

**返回值：**

```python
{
    "obv": 123456.0, "obv_ma": 120000.0,
    "trend": "BULL",  # "BULL" | "BEAR"
    "bullish": True, "accelerating": True,
    "divergence": False,
}
```

---

### 1.11 calc_supertrend

```python
def calc_supertrend(prices: list, period: int = 10, multiplier: float = 3.0) -> dict | None
```

计算超级趋势指标（Supertrend）。数据不足返回 None。

**返回值：**

```python
{
    "upper_band": 70000.0, "lower_band": 64000.0,
    "trend": "BULL",  # "BULL" | "BEAR"
    "bullish": True, "reversal": False,
    "atr": 1500.0, "distance_pct": 4.69,
}
```

---

### 1.12 calc_keltner_channel

```python
def calc_keltner_channel(prices: list, period: int = 20, multiplier: float = 2.0) -> dict | None
```

计算肯特纳通道（Keltner Channel）。数据不足返回 None。

**返回值：**

```python
{
    "upper": 69000.0, "middle": 67000.0, "lower": 65000.0,
    "position": 0.5,  # (price - lower) / (upper - lower)
    "near_lower": False,  # position < 0.2
    "near_middle": True,  # 0.4 < position < 0.6
    "near_upper": False,  # position > 0.8
    "bandwidth": 5.97,
}
```

---

### 1.13 calc_stochrsi

```python
def calc_stochrsi(prices: list, period: int = 14, fastk: int = 3, fastd: int = 3) -> dict | None
```

计算随机RSI（StochRSI）。数据不足返回 None。

**返回值：**

```python
{
    "k": 25.5, "d": 30.2,
    "cross": "golden",  # "golden" | "death" | "none"
    "oversold": False,  # k < 20
    "overbought": False,  # k > 80
    "bullish": True,  # cross == "golden" or k < 20
}
```

---

### 1.14 calc_vortex

```python
def calc_vortex(highs: list, lows: list, prices: list, period: int = 14) -> dict | None
```

计算涡旋指标（Vortex Indicator）。数据不足返回 None。

**返回值：**

```python
{
    "vi_plus": 1.15, "vi_minus": 0.87,
    "direction": "BULL",  # "BULL" | "BEAR"
    "bullish": True, "reversal": True,
    "strength": 2.8,
}
```

---

### 1.15 calc_tema

```python
def calc_tema(prices: list, period: int = 30) -> dict | None
```

计算三重指数移动平均（TEMA）。数据不足返回 None。

**返回值：**

```python
{
    "tema": 67500.0,
    "direction": "BULL",  # tema > price → BULL
    "bullish": True,
    "slope": 0.15,  # TEMA变化率%
    "distance_pct": 0.75,
}
```

---

### 1.16 calc_golden_cross

```python
def calc_golden_cross(prices: list, fast_period: int = 50, slow_period: int = 200) -> dict | None
```

计算金叉/死叉信号（EMA快慢线交叉）。数据不足返回 None。

**返回值：**

```python
{
    "ema_fast": 68000.0, "ema_slow": 65000.0,
    "cross": "golden",  # "golden" | "death" | "none"
    "direction": "BULL",  # ema_fast > ema_slow
    "bullish": True,
    "distance_pct": 4.62,
}
```

---

### 1.17 calc_ema_align

```python
def calc_ema_align(prices: list, periods: list = [20, 50, 200]) -> dict | None
```

计算EMA多头/空头排列。数据不足返回 None。

**返回值：**

```python
{
    "emas": {20: 69000.0, 50: 67000.0, 200: 63000.0},
    "direction": "BULL",  # 完美多头排列
    "bullish": True,  # ema20 > ema50 > ema200
    "aligned": True,  # 完美排列（多或空）
    "alignment_score": 0.85,
}
```

---

## 2. 交易执行器 (core/v15_trader.py)

### 2.1 run_poll_cycle

```python
def run_poll_cycle() -> None
```

执行一次完整轮询。遍历所有币种，对持仓检查止盈止损/加仓，对空仓检查信号开仓。

**调用示例：**

```python
from v15_trader import run_poll_cycle
run_poll_cycle()  # 单次轮询
```

---

### 2.2 execute_open_position

```python
def execute_open_position(client, coin: str, decision: dict, state: dict) -> bool
```

执行开仓操作。

| 参数 | 类型 | 说明 |
|------|------|------|
| client | OKXSimulatedClient | OKX 客户端实例 |
| coin | str | 币种名（如 "BTC"） |
| decision | dict | v15_decision() 返回的决策结果 |
| state | dict | 全局状态字典 |

**返回：** True=开仓成功，False=开仓失败/跳过

**前置检查链：**
1. confidence >= 60
2. stop_loss_triggered == False
3. 下单数量 >= 最小合约单位
4. 资金管理允许开新仓

---

### 2.3 execute_addon

```python
def execute_addon(client, coin: str, pos: dict, state: dict) -> bool
```

执行加仓操作（仅在价格下跌时触发）。

**加仓门槛公式：**

```
target_drop_pct = addon_pct × (addons + 1)
drop_pct = (open_price - current_price) / open_price
触发条件: drop_pct >= target_drop_pct
```

**返回：** True=加仓成功，False=跳过

---

### 2.4 check_take_profit

```python
def check_take_profit(client, coin: str, pos: dict, state: dict) -> bool
```

检查止盈和止损。

**止盈条件：** `(current_price - entry_price) / entry_price >= tp_pct`

**止损条件：** `stop_loss_triggered == True`

**返回：** True=已平仓，False=继续持有

---

### 2.5 _get_dynamic_params

```python
def _get_dynamic_params(client, coin: str, direction: str = "LONG") -> dict
```

获取币种的动态策略参数。

**返回值：**

```python
{
    "current_price": 67000.0,
    "take_profit_pct": 0.048,          # 止盈比例（已除以100）
    "addon_pct": 0.096,                # 加仓比例
    "stop_loss_price": 60000.0,        # 止损价
    "stop_loss_type": "日MA200",       # 止损类型
    "stop_loss_triggered": False,      # 是否触发
    "trend_filter": {                  # 新增
        "blocked": False,              # 是否禁止开多
        "mode": "both_bear",           # 过滤模式
        "weekly_ma104": 87830.0,       # 周线MA104
        "daily_ma104": 70658.0,        # 日线MA104
    },
}
```

---

### 2.6 状态管理

```python
def load_state() -> dict          # 从 data/v15_state.json 加载
def save_state(state: dict)       # 保存到 data/v15_state.json
```

**状态结构：**

```python
{
    "positions": {
        "BTC": {
            "inst_id": "BTC-USDT-SWAP",
            "entry_price": 67000.0,      # 均价（加仓后更新）
            "open_price": 67000.0,       # 首次开仓价（不变）
            "sz": 10,                     # 持仓数量（张）
            "addons": 0,                  # 已加仓次数
            "confidence": 75,             # 开仓置信度
            "open_time": "2026-07-10T...",
            "take_profit_pct": 0.048,
            "addon_pct": 0.096,
            "stop_loss_price": 60000.0,
            "stop_loss_type": "日MA200",
            "vol_mult": 1.2,
        }
    },
    "total_trades": 10,
    "total_wins": 7,
    "consecutive_losses": 0,           # 新增：连续亏损次数
    "last_capital_rebuild": None,      # 新增：上次资金管理引擎触发时间
}
```

---

### 2.7 main

```python
def main() -> None
```

启动自动交易器，进入轮询循环。

**启动模式：**
- `python v15ct_trader.py` — 长驻轮询模式（while True + sleep）
- `python v15ct_trader.py --poll-once` — 单次轮询模式（供 master_daemon 调用）

---

## 3. 回测引擎 (core/v15_backtest.py)

### 3.1 run_backtest

```python
def run_backtest(coin: str, limit: int = 500) -> dict
```

运行历史数据回测。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| coin | str | — | 币种名（如 "BTC"） |
| limit | int | 500 | 回测K线数量 |

**返回值：**

```python
{
    "coin": "BTC",
    "period": "4H",
    "total_trades": 15,
    "wins": 10,
    "losses": 5,
    "win_rate": 0.667,
    "total_pnl": 125.50,           # USDT
    "max_drawdown": 0.08,          # 8%
    "sharpe_ratio": 1.85,
    "avg_hold_bars": 12,           # 平均持仓K线数
    "trades": [                    # 交易记录
        {"entry_time": "...", "exit_time": "...",
         "entry_price": 65000, "exit_price": 68000,
         "direction": "LONG", "pnl": 30.0, "addons": 1}
    ]
}
```

---

### 3.2 回测内置函数

回测引擎内置了独立的指标计算函数（不依赖 v15_signal.py），以避免 mock 复杂性：

| 函数 | 说明 |
|------|------|
| `_calc_sma(values, period)` | SMA |
| `_calc_rsi(prices, period=14)` | RSI |
| `_determine_position(price, smas)` | 位置判定 |
| `_calc_fibonacci(prices, lookback=30)` | Fib回调位 |
| `_calc_bollinger_bands(prices, period=20, num_std=2)` | 布林带 |
| `_calc_macd(prices, fast=12, slow=26, signal=9)` | MACD |
| `_calc_adx(prices, period=14)` | ADX |
| `calc_ma200_series(closes)` | MA200 序列 |
| `prepare_ma200_for_4h(klines_4h, klines_1d, klines_1w)` | 日/周 MA200 对齐到4H |
| `get_ma200_stop_loss(direction, close, daily_ma200, weekly_ma200)` | 回测止损 |
| `get_vol_adjusted_params(base_tp, base_addon, coin_vol, btc_vol)` | 波动率参数 |

---

## 4. 市场数据 (lib/market_data.py)

### 4.1 fetch_candles

```python
def fetch_candles(inst_id: str, bar: str = "4H", limit: int = 200) -> list
```

获取K线数据（OKX API 优先，CLI 降级）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| inst_id | str | — | 交易对（如 "BTC-USDT"） |
| bar | str | "4H" | K线周期 |
| limit | int | 200 | K线数量 |

**返回值：** `list[dict]`，每个元素：

```python
{"ts": "1700000000000", "o": "67000", "h": "67500", "l": "66500", "c": "67200", "v": "1234.5"}
```

**降级策略：** API 不可用时通过 `okx` CLI 获取。

---

### 4.2 基础指标

```python
def calc_sma(values: list, period: int) -> float | None
def calc_ema(values: list, period: int) -> float | None
def calc_rsi(prices: list, period: int = 14) -> float
```

---

## 5. 策略参数 (lib/strategy_params.py)

### 5.1 get_dynamic_stop_loss

```python
def get_dynamic_stop_loss(direction: str, current_price: float,
                          daily_ma200: float, daily_ema200: float,
                          weekly_ma200: float = None, weekly_ema200: float = None,
                          last_daily_close: float = None,
                          last_weekly_close: float = None) -> dict
```

计算四均线动态止损。

**返回值：**

```python
{
    "stop_loss_price": 60000.0,         # 止损线价格
    "stop_loss_pct": 10.45,             # 距当前价百分比
    "stop_type": "日MA200",             # 止损均线类型
    "is_triggered": False,              # 是否触发止损
    "daily_ma200": 60000.0,             # 日MA200
    "daily_ema200": 61000.0,            # 日EMA200
    "weekly_ma200": 55000.0,            # 周MA200
    "weekly_ema200": 56000.0,           # 周EMA200
    "last_daily_close": 65000.0,        # 昨收盘价
    "last_weekly_close": 63000.0,       # 上周收盘价
    "above_daily_ma200_close": True,    # 昨收在日MA200上方
    "above_daily_ema200_close": True,
    "above_weekly_ma200_close": True,
    "above_weekly_ema200_close": True,
}
```

**stop_type 特殊值：**
- `"BELOW_ALL_MA_INTRADAY"` — 实时价全破但收盘价未全破，不触发
- `"BELOW_ALL_MA_CONFIRMED"` — 收盘价全破，无条件止损

---

### 5.2 get_vol_adjusted_params

```python
def get_vol_adjusted_params(coin_vol: float, btc_vol: float,
                            base_tp_pct: float = None,
                            base_addon_pct: float = None) -> dict
```

根据币种波动率计算自适应参数。

**返回值：**

```python
{
    "ratio": 1.5,                # 波动率比（限制在0.5-2.5）
    "take_profit_pct": 6.0,      # 止盈百分比（4% × 1.5）
    "addon_pct": 12.0,           # 加仓百分比（8% × 1.5）
}
```

---

### 5.3 get_coin_strategy_params

```python
def get_coin_strategy_params(symbol: str, direction: str = "LONG") -> dict
```

获取币种的完整策略参数（止损+波动率+止盈+加仓）。

**返回值：**

```python
{
    "symbol": "BTC",
    "direction": "LONG",
    "current_price": 67000.0,
    "stop_loss": {...},          # get_dynamic_stop_loss 返回值
    "volatility": {
        "coin_vol": 0.035,
        "btc_vol": 0.030,
        "ratio": 1.17,
    },
    "take_profit_pct": 4.67,     # 百分比
    "addon_pct": 9.33,           # 百分比
    "stop_loss_price": 60000.0,
    "stop_loss_type": "日MA200",
    "stop_loss_triggered": False,
}
```

---

### 5.4 get_all_coins_params

```python
def get_all_coins_params() -> dict
```

获取所有监控币种的策略参数。返回 `{symbol: params_dict}` 字典。

---

### 5.5 辅助计算函数

```python
def calc_daily_ma200(klines_1d: list) -> float | None      # 日线MA200
def calc_daily_ema200(klines_1d: list) -> float | None     # 日线EMA200
def calc_weekly_ma200(klines_1w: list) -> float | None     # 周线MA200
def calc_weekly_ema200(klines_1w: list) -> float | None    # 周线EMA200
def calc_30d_volatility(klines_1d: list) -> float           # 30天波动率
def fetch_daily_klines(client, inst_id, limit=250) -> list  # 日线K线
def fetch_weekly_klines(client, inst_id, limit=200) -> list # 周线K线
```

---

### 5.6 check_trend_filter

```python
def check_trend_filter(symbol: str) -> dict
```

三屏趋势过滤器 — 周线+日线MA104双周期趋势一致性检查。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| symbol | str | 币种名（如 "BTC"） |

**返回值：**

```python
{
    "blocked": False,            # bool: 是否禁止开多
    "mode": "both_bear",         # str: 过滤模式
    "weekly_ma104": 87830.0,     # float: 周线MA104
    "daily_ma104": 70658.0,      # float: 日线MA104
    "current_price": 63871.0,    # float: 当前价格
}
```

**调用示例：**

```python
from strategy_params import check_trend_filter
result = check_trend_filter("BTC")
if result["blocked"]:
    print(f"BTC趋势禁止开多: 周线MA104={result['weekly_ma104']}, 日线MA104={result['daily_ma104']}")
```

---

## 6. 资金管理 (lib/capital_manager.py)

### 6.1 calculate_single_position_cost

```python
def calculate_single_position_cost() -> dict
```

计算单仓位完整资金需求。

**返回值：**

```python
{
    "base_usd": 13.0,            # 底仓成本
    "addon_total_usd": 6.24,     # 加仓总成本
    "total_cost_usd": 19.24,     # 单仓位总成本
    "addon_details": [
        {"addon": 1, "cost_usd": 1.04},
        {"addon": 2, "cost_usd": 2.08},
        {"addon": 3, "cost_usd": 3.12},
    ]
}
```

---

### 6.2 calculate_capital_allocation

```python
def calculate_capital_allocation() -> dict
```

计算当前资金分配和开仓许可。

**返回值：**

```python
{
    "timestamp": "2026-07-10T...",
    "balance": {"total_eq": 260.0, "avail_balance": 200.0, "used_margin": 60.0},
    "positions": [...],
    "coins_monitored": ["BTC", "ETH", ...],
    "single_position_cost": {...},
    "parameters": {
        "total_budget": 260, "max_concurrent_positions": 4,
        "max_addons_per_position": 3, "addon_pct": 0.08,
        "base_position_pct": 0.05, "max_position_pct": 0.25,
        "leverage": 10, "min_margin_usd": 10,
    },
    "positions_can_open": 2,
    "remaining_after_open": 161.52,
    "margin_usage_pct": 23.08,
    "risk_level": "low",              # "low" | "medium" | "high"
    "recommendations": {
        "allow_open_new_position": True,
        "allow_addon": True,
        "advice": "正常运营",
    }
}
```

---

### 6.3 get_signal_trigger_status

```python
def get_signal_trigger_status() -> dict
```

获取所有币种的信号触发状态。

**返回值：**

```python
{
    "BTC": {"triggered": True, "action": "OPEN_BULL", "confidence": 75, "position": "ABOVE_ALL"},
    "ETH": {"triggered": False, "action": "WAIT", "confidence": 0, "position": "IN_ZONE"},
    ...
}
```

---

### 6.4 其他函数

```python
def get_account_balance() -> dict                     # 账户余额
def get_current_positions() -> list                   # 当前持仓列表
def check_can_open_position(symbol: str = None) -> bool  # 是否允许开仓
def check_can_addon() -> bool                         # 是否允许加仓
def get_coin_allocation(symbol: str) -> dict          # 单币种资金分配
def get_coin_strategy_params(symbol, direction="LONG") -> dict  # 币种策略参数
def get_all_coins_strategy_params() -> dict           # 全币种策略参数
def calculate_position_risk(pos: dict) -> dict        # 持仓风险评估
```

---

## 7. 配置加载 (lib/config_loader.py)

### 7.1 load_config

```python
def load_config(strategy_type: str = "v15") -> dict
```

加载配置文件。先读 `.env.common`，再读 `.env.v15`（覆盖同名配置）。

**参数：** `strategy_type` — `"v15"` (默认)

**返回值：** `dict` — 配置键值对

---

### 7.2 类型化获取函数

```python
def get_config(key: str, default: str = None) -> str          # 字符串
def get_config_float(key: str, default: float = 0.0) -> float  # 浮点数
def get_config_int(key: str, default: int = 0) -> int          # 整数
def get_config_bool(key: str, default: bool = False) -> bool   # 布尔值
def get_config_list(key: str, default: list = None) -> list    # 列表（逗号分隔）
```

**调用示例：**

```python
from config_loader import get_config_float, get_config_list

leverage = get_config_float("LEVERAGE", 10.0)
coins = get_config_list("V15_COINS", ["BTC"])
```

---

## 8. OKX 客户端 (lib/okx_client.py)

### 8.1 OKXSimulatedClient

```python
class OKXSimulatedClient:
    def __init__(self, api_key=None, secret_key=None, passphrase=None,
                 simulated=False, base_url=None)
```

OKX REST API 客户端，支持实盘和模拟盘。

**关键方法：**

| 方法 | 说明 |
|------|------|
| `place_order(inst_id, side, sz, td_mode, pos_side, ...)` | 下单 |
| `get_positions(inst_type="SWAP")` | 查询持仓 |
| `get_balance()` | 查询余额 |
| `get_kline(inst_id, bar, limit)` | 获取K线 |
| `get_instruments(inst_type="SWAP")` | 查询合约信息 |
| `close_position(inst_id, pos_side)` | 平仓 |
| `set_leverage(inst_id, lever, pos_side)` | 设置杠杆 |

**下单返回值：**

```python
{"ok": True, "data": {"ordId": "123456789"}}
# 或
{"ok": False, "error": "insufficient balance"}
```

---

## 9. 入口脚本 (run.py)

### 9.1 子命令

```bash
python3 run.py <command> [args]
```

| 命令 | 参数 | 说明 |
|------|------|------|
| `signal` | `[coins]` | 查看信号（逗号分隔币种，默认全部） |
| `backtest` | `[coin] [limit]` | 回测（默认BTC, 500根） |
| `trader` | — | 启动自动交易器 |
| `capital` | — | 查看资金管理状态 |
| `test` | — | 运行全部测试 |
| `config` | — | 查看当前配置 |

### 9.2 使用示例

```bash
# 查看BTC和ETH信号
python3 run.py signal BTC,ETH

# BTC回测1000根K线
python3 run.py backtest BTC 1000

# 运行全部测试
python3 run.py test
```

---

## 10. 资金管理引擎 (lib/capital_manager_engine.py)

### 10.1 CapitalManagerEngine 类

```python
class CapitalManagerEngine:
    def __init__(self, coins: list = None)
```

资金管理引擎 — 整合回测+趋势过滤+贝叶斯优化+资金管理。

### 10.2 run_monthly

```python
def run_monthly(self) -> dict
```

运行月度完整优化流程（回测→趋势分析→贝叶斯优化→更新配置）。

**返回值：**

```python
{
    "timestamp": "2026-07-12T...",
    "backtest_stats": {...},      # 回测统计
    "trend_filter": {...},        # 趋势过滤状态
    "optimization_result": {...}, # 优化结果
    "config_updated": True,       # 配置是否更新
}
```

### 10.3 get_status

```python
def get_status(self) -> dict
```

获取资金管理整体状态。

### 10.4 check_open_permission

```python
def check_open_permission(self, symbol: str) -> dict
```

综合开仓许可检查（资金+趋势+止损）。

**返回值：**

```python
{
    "symbol": "BTC",
    "allowed": False,
    "reasons": ["趋势过滤禁止(both_bear)", "MA200止损触发"],
    "capital": {...},
    "trend_filter": {...},
}
```

### 10.5 HTTP API（端口8770）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/status` | 资金管理整体状态 |
| GET | `/params` | 当前最优参数 |
| GET | `/trend/<coin>` | 某币种趋势过滤状态 |
| GET | `/check/<coin>` | 综合开仓许可检查 |
| GET | `/history` | 优化历史记录 |
| POST | `/optimize` | 触发手动优化 |

### 10.6 CLI 接口

```bash
python capital_manager_engine.py status              # 资金状态
python capital_manager_engine.py trend --coin BTC    # 趋势过滤
python capital_manager_engine.py check --coin BTC    # 综合检查
python capital_manager_engine.py monthly             # 手动月度优化
python capital_manager_engine.py api --port 8770     # 启动API服务
```

---

## 11. 连续亏损触发机制 (core/v15_trader.py)

### 11.1 _trigger_capital_rebuild

```python
def _trigger_capital_rebuild(state: dict) -> None
```

连续亏损3次时异步触发资金管理引擎重新优化。

**触发条件：** `state["consecutive_losses"] >= 3`

**行为：**
1. 异步启动子进程 `capital_manager_engine.py monthly`
2. 重置 `consecutive_losses = 0`
3. 记录 `last_capital_rebuild` 时间戳

**计数规则：**
- 止盈平仓 → `consecutive_losses = 0`（重置）
- 止损平仓 → `consecutive_losses += 1`
- 达到3次 → 触发资金管理引擎，重置计数

---

## 调用关系速查

```
run.py signal
  └─→ v15_signal.v15_decision()
        └─→ market_data.fetch_candles()

run.py backtest
  └─→ v15_backtest.run_backtest()
        └─→ market_data.fetch_candles() (通过 fetch_klines)

run.py trader
  └─→ v15_trader.main()
        └─→ run_poll_cycle() [循环]
              ├─→ v15_signal.v15_decision()
              ├─→ capital_manager.calculate_capital_allocation()
              ├─→ execute_open_position()
              │     └─→ strategy_params.get_coin_strategy_params()
              │     └─→ okx_client.place_order()
              ├─→ execute_addon()
              │     └─→ okx_client.place_order()
              └─→ check_take_profit()
                    └─→ okx_client.place_order()

run.py capital
  └─→ capital_manager.calculate_capital_allocation()
  └─→ capital_manager.get_signal_trigger_status()
  └─→ capital_manager.calculate_single_position_cost()

capital_manager_engine.py monthly
  └─→ CapitalManagerEngine.run_monthly()
        ├─→ v15_backtest.run_backtest()
        ├─→ strategy_params.check_trend_filter()
        ├─→ bayesian_optimizer.iterate_optimize()
        └─→ _update_config_file()

master_daemon (hourly)
  └─→ run.py poll_once
        └─→ run_poll_cycle()
              ├─→ v15_signal.v15_decision()
              ├─→ strategy_params.get_coin_strategy_params()
              │     └─→ check_trend_filter()
              ├─→ capital_manager.calculate_capital_allocation()
              └─→ execute_open_position() / check_take_profit()
```

---

_最后更新：2026-07-13 | 来源：14-V15经典马丁策略（独立V15系统）_
