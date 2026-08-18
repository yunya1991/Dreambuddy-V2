# 接口规格文档 — V4 减半周期 + 艾略特波浪互斥融合趋势策略

> **版本**: v1.0 | **更新日期**: 2026-07-31
> **定位**: 子系统对外接口规格，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3
> **关联文档**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) · [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) · [CHANGELOG.md](./CHANGELOG.md) · [README.md](../README.md)

---

## 目录

- [1. 接口概览](#1-接口概览)
- [2. 认证方式](#2-认证方式)
- [3. 接口详情](#3-接口详情)
- [4. 错误码](#4-错误码)
- [5. 版本管理](#5-版本管理)

---

## 1. 接口概览

### 1.1 接口类型

| 类型 | 数量 | 说明 |
|------|------|------|
| Python API | 11 | SDK 式调用，核心策略与执行器公开方法 |
| CLI 命令 | 2 | 回测入口与实盘入口 |
| HTTP API | 0 | 无独立 HTTP 服务（实盘通过 Aster 执行器对接交易所） |

### 1.2 接口列表

| 接口 | 方法 | 路径/签名 | 说明 |
|------|------|-----------|------|
| V4+波浪信号计算 | Python | `compute_v4_wave_signal(spot_inst, is_btc) -> dict` | 一键获取融合信号 |
| 引擎信号计算 | Python | `V4WaveEngine.compute_from_dataframes(daily_df, symbol, is_btc) -> Dict` | 从 DataFrame 计算信号 |
| V4 仓位生成 | Python | `HalvingTopExitStrategy.generate_signals(prices) -> pd.Series` | V4 减半周期仓位序列 |
| V4 统计信息 | Python | `HalvingTopExitStrategy.get_stats() -> dict` | V4 策略统计 |
| 波浪识别 | Python | `ElliottWaveRecognizer.identify_waves(prices) -> WaveStructure` | 识别波浪结构 |
| 波浪信号序列 | Python | `ElliottWaveRecognizer.generate_signal_series(prices) -> pd.DataFrame` | 滚动识别（回测用） |
| 波浪策略评估 | Python | `EWaveStrategyAdapter.evaluate(daily_df, v4_action, v4_direction, v4_position_pct, symbol) -> Dict` | 互斥融合评估 |
| K 线获取 | Python | `fetch_candles(inst_id, bar, limit) -> List[Dict]` | 单次 K 线获取 |
| 历史 K 线获取 | Python | `fetch_historical_candles(inst_id, bar, days, max_limit_per_page) -> List[Dict]` | 分页历史 K 线 |
| 跨周期重采样 | Python | `resample_candles(candles, target_tf) -> List[Dict]` | K 线聚合 |
| K 线转 DataFrame | Python | `candles_to_dataframe(candles) -> pd.DataFrame` | 数据格式转换 |
| 回测入口 | CLI | `python backtest_v4_wave.py --symbol BTC` | 9 年回测 |
| 实盘入口 | CLI | `python live/v4_wave_trader.py` | 实盘交易器启动 |

---

## 2. 认证方式

| 方式 | 说明 |
|------|------|
| 无需认证 | Python API 直接调用，SDK 集成 |
| OKX API Key | 通过 `dreamllm/services/registry.py` 注册的 OKX 适配器（实盘行情+下单） |
| Aster 执行器凭证 | 通过 `12-三屏趋势系统/live/aster_executor.py` 加载（实盘下单） |
| `.env` 文件 | `17-v4-wave-strategy/.env` 提供环境变量（`TREND_SYMBOLS`, `AUTO_EXECUTE` 等） |

---

## 3. 接口详情

### 3.1 `compute_v4_wave_signal` — V4+波浪完整信号计算

**模块**: `v4_wave_engine.py`
**类型**: 模块级函数（含数据获取）

```python
def compute_v4_wave_signal(
    spot_inst: str = "BTC-USDT",
    is_btc: bool = True,
) -> dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `spot_inst` | str | `"BTC-USDT"` | 现货交易对标识 |
| `is_btc` | bool | `True` | 是否为 BTC 币种（影响 V4 策略分支） |

**返回值**：

```python
{
    "symbol": "BTC",
    "price": 67000.00,
    "generated_at": "2026-07-31T00:00:00+00:00",
    "timeframes": {"daily": 300},
    "value_risk_assessment": {
        "risk_level": "low" | "medium" | "high",
        "adjusted_position": float,
        "ath_drawdown_pct": float,
        "ma200_distance_pct": float,
        "reason": str,
    },
    "final_signal": {
        "direction": "BULL" | "BEAR" | "NEUTRAL",
        "confidence": 75.0,                  # 0-95
        "action": "ENTER_LONG" | "ENTER_SHORT" | "WAIT",
        "position": {
            "position_pct": 0.6,             # 最终仓位占比
            "tier": "full" | "partial",
            "original_position_pct": 0.5,    # V4 原始仓位
        },
        "decision_reason": "v4_long_wave_add" | "v4_long_keep" | ...,
        "leverage": 3,
        "margin_mode": "isolated",
        "max_position_pct": 0.25,
        "max_addon_position_pct": 0.1,
        "v4_strategy": {
            "enabled": True,
            "v4_action": "ENTER_LONG" | "ENTER_SHORT" | "WAIT",
            "v4_direction": "BULL" | "BEAR" | "NEUTRAL",
            "v4_position_pct": 0.5,
            "strategy_version": "v4_halving_top_exit",
            "stats": { /* HalvingTopExitStrategy.get_stats() */ },
        },
        "physics_adjustment": {
            "enabled": True,
            "eta": 0.15,
            "phys_conf": 0.7,
            "kinetic_score": 0.6,
            "adjusted_position": 0.45,
            "reason": "weak_trend_physics_adjusted" | "strong_trend_no_adjustment",
        },
        "wave_strategy": {
            "wave_signal": "ENTER_LONG_W3" | "EXIT_LONG_W5" | "WAIT" | ...,
            "wave_label": "IMPULSE_5" | "INCOMPLETE",
            "current_wave": 0-5,
            "wave_confidence": 0.0-1.0,
            "wave_direction": "LONG" | "SHORT" | "EXIT_LONG" | "EXIT_SHORT" | "NEUTRAL",
            "wave_position_pct": 0.18,
            "wave_physics_confidence": 0.7,
            "wave_eta": 0.15,
            "wave_kinetic_score": 0.6,
            "wave_trailing_stop_pct": 0.08,
            "wave_take_profit_pct": 0.25,
            "total_position_pct": 0.68,
            "final_action": "ENTER_LONG",
            "final_direction": "BULL",
            "fusion_rule": "v4_long_wave_add" | "v4_long_keep" | "v4_wait_wave_bottom" | ...,
            "enabled": True,
        },
        "value_risk_assessment": { /* 同上 */ },
    },
}
```

**调用示例**：

```python
from v4_wave_engine import compute_v4_wave_signal

signal = compute_v4_wave_signal("BTC-USDT", is_btc=True)
print(signal["final_signal"]["action"])          # "ENTER_LONG"
print(signal["final_signal"]["position"]["position_pct"])  # 0.68
```

---

### 3.2 `V4WaveEngine.compute_from_dataframes` — 引擎信号计算

**模块**: `v4_wave_engine.py`
**类型**: 实例方法（不含数据获取）

```python
def compute_from_dataframes(
    self,
    daily_df: pd.DataFrame,
    symbol: str = "BTC",
    is_btc: bool = True,
) -> Dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `daily_df` | pd.DataFrame | - | 日线 OHLCV，索引为 DatetimeIndex，列为 open/high/low/close/volume |
| `symbol` | str | `"BTC"` | 币种符号 |
| `is_btc` | bool | `True` | 是否为 BTC |

**返回值**：与 `compute_v4_wave_signal` 返回值结构一致。

**异常**：当日线数据 < 250 天时，返回包含 `error` 字段的降级信号。

---

### 3.3 `HalvingTopExitStrategy.generate_signals` — V4 仓位生成

**模块**: `halving_top_exit_strategy.py`
**类型**: 实例方法

```python
def generate_signals(self, prices: pd.DataFrame) -> pd.Series
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `prices` | pd.DataFrame | OHLCV 数据，索引为 DatetimeIndex |

**返回值**：

```python
pd.Series  # name="position"
# 值含义：
#   正值 = 多头仓位（0~1.0）
#   负值 = 空头仓位（-0.6~-1.0）
#   0    = 空仓
```

**调用示例**：

```python
from halving_top_exit_strategy import HalvingTopExitStrategy

strategy = HalvingTopExitStrategy(symbol="BTC", is_btc=True)
positions = strategy.generate_signals(daily_df)
print(positions.iloc[-1])  # 0.5（当前多头仓位 50%）
print(strategy.get_stats())  # 策略统计
```

---

### 3.4 `HalvingTopExitStrategy.get_stats` — V4 统计信息

**模块**: `halving_top_exit_strategy.py`
**类型**: 实例方法

```python
def get_stats(self) -> dict
```

**返回值**：

```python
{
    "bull_days": int,           # 多头天数
    "bull_exit_days": int,      # 多头减仓天数
    "bear_short_l1_days": int,  # 熊市 L1 做空天数
    "bear_short_l2_days": int,  # 熊市 L2 做空天数
    "bear_flat_days": int,      # 熊市空仓天数
    "sideways_days": int,       # 震荡天数
    "dip_buy_days": int,        # 抄底天数
    "dip_buy_end_days": int,    # 抄底结束天数
    "fib_tp_days": int,         # 斐波那契止盈天数
    "ma128_exit_days": int,     # MA128 破位减仓天数
    "bounce_sell_days": int,    # 反弹卖出天数
    "halving_warn_days": int,   # 减半预警期天数
    "halving_danger_days": int, # 减半高危期天数
    "halving_peak_days": int,   # 减半顶部期天数
    "high_to_sell_days": int,   # 越高越卖天数
    "trend_switches": int,      # 趋势切换次数
}
```

---

### 3.5 `ElliottWaveRecognizer.identify_waves` — 波浪识别

**模块**: `ewave_recognizer.py`
**类型**: 实例方法

```python
def identify_waves(self, prices: pd.DataFrame) -> WaveStructure
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `prices` | pd.DataFrame | OHLCV 数据，需含 high/low/close 列 |

**返回值**（`WaveStructure` dataclass）：

```python
WaveStructure(
    waves: List[WavePoint],     # 转折点列表
    wave_label: str,            # "IMPULSE_5" | "INCOMPLETE"
    current_wave: int,          # 0-5，当前浪位
    signal: str,                # 交易信号（见下表）
    confidence: float,          # 0.0-1.0
)
```

**`signal` 枚举值**：

| 信号 | 含义 |
|------|------|
| `WAIT` | 观望 |
| `ENTER_LONG_W3` | 浪 2 结束入场做多（最强） |
| `ENTER_LONG_W5` | 浪 4 结束入场做多（次强） |
| `HOLD_LONG_W3` | 持有做多（浪 3 进行中） |
| `EXIT_LONG_W5` | 浪 5 结束离场做多 |
| `ENTER_SHORT_W3` | 浪 2 结束入场做空（最强） |
| `ENTER_SHORT_W5` | 浪 4 结束入场做空（次强） |
| `HOLD_SHORT_W3` | 持有做空（浪 3 进行中） |
| `EXIT_SHORT_W5` | 浪 5 结束离场做空 |

**调用示例**：

```python
from ewave_recognizer import ElliottWaveRecognizer

recognizer = ElliottWaveRecognizer(zigzag_threshold=0.05)
wave = recognizer.identify_waves(daily_df)
print(wave.signal, wave.current_wave, wave.confidence)
# "ENTER_LONG_W3" 3 0.85
```

---

### 3.6 `ElliottWaveRecognizer.generate_signal_series` — 滚动波浪信号序列

**模块**: `ewave_recognizer.py`
**类型**: 实例方法（回测专用）

```python
def generate_signal_series(self, prices: pd.DataFrame) -> pd.DataFrame
```

**返回值**：

```python
pd.DataFrame  # 索引同 prices
# 列：
#   wave_signal: str      # 信号
#   wave_label: str       # 浪标签
#   current_wave: int     # 当前浪位
#   wave_confidence: float  # 置信度
```

**说明**：从第 60 根 K 线开始滚动识别（前 60 根为预热），用于回测中生成时间序列信号。

---

### 3.7 `EWaveStrategyAdapter.evaluate` — 波浪策略互斥融合评估

**模块**: `ewave_strategy_adapter.py`
**类型**: 实例方法

```python
def evaluate(
    self,
    daily_df: pd.DataFrame,
    v4_action: str = "WAIT",
    v4_direction: str = "NEUTRAL",
    v4_position_pct: float = 0.0,
    symbol: str = None,
) -> Dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `daily_df` | pd.DataFrame | - | 日线 OHLCV |
| `v4_action` | str | `"WAIT"` | V4 动作（`ENTER_LONG`/`ENTER_SHORT`/`WAIT`） |
| `v4_direction` | str | `"NEUTRAL"` | V4 方向（`BULL`/`BEAR`/`NEUTRAL`） |
| `v4_position_pct` | float | `0.0` | V4 仓位占比（绝对值） |
| `symbol` | str | `None` | 币种符号（用于动态置信度阈值） |

**返回值**：

```python
{
    "wave_signal": "ENTER_LONG_W3",
    "wave_label": "IMPULSE_5",
    "current_wave": 3,
    "wave_confidence": 0.85,
    "wave_direction": "LONG",
    "wave_position_pct": 0.18,
    "wave_physics_confidence": 0.7,
    "wave_eta": 0.15,
    "wave_kinetic_score": 0.6,
    "wave_trailing_stop_pct": 0.08,
    "wave_take_profit_pct": 0.25,
    "total_position_pct": 0.68,        # 融合后总仓位
    "final_action": "ENTER_LONG",      # 融合后动作
    "final_direction": "BULL",         # 融合后方向
    "fusion_rule": "v4_long_wave_add", # 融合规则标签
    "enabled": True,
}
```

**`fusion_rule` 枚举值**：

| 规则 | 含义 |
|------|------|
| `v4_long_wave_add` | V4 多头 + 波浪看多 → 同向叠加 |
| `v4_long_keep` | V4 多头 + 波浪中性/看空 → 保持 V4 仓位 |
| `v4_wait_wave_bottom` | V4 空仓 + 波浪看多 → 轻仓抄底 |
| `v4_wait_keep_dip_buy` | V4 空仓 + V4 抄底仓位 → 保留抄底 |
| `v4_wait_wave_wait` | V4 空仓 + 波浪中性 → 空仓观望 |
| `v4_short_wave_reduce` | V4 空头 + 波浪看多 → 空头减半 |
| `v4_short_keep` | V4 空头 + 波浪中性/看空 → 保持空头 |
| `v4_default` | 默认（兜底） |
| `no_wave_data` | 无波浪数据 |
| `insufficient_data` | 数据不足（< 90 天） |
| `wave_error_keep_v4` | 波浪异常，保持 V4 |

---

### 3.8 `fetch_candles` — K 线获取

**模块**: `data/market_data.py`
**类型**: 模块级函数

```python
def fetch_candles(inst_id: str, bar: str, limit: int) -> List[Dict]
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `inst_id` | str | 交易对 ID，如 `"BTC-USDT"` |
| `bar` | str | 时间周期，如 `"1m"`, `"5m"`, `"1H"`, `"4H"`, `"1D"`, `"1W"` |
| `limit` | int | 获取数量 |

**返回值**：

```python
[
    {"ts": 1690000000000, "o": 30000.0, "h": 30500.0, "l": 29800.0, "c": 30200.0, "vol": 1234.5},
    # ... 时间正序
]
```

**降级策略**：优先使用 OKX 适配器（`dreamllm/services/registry.py`），失败回退到 OKX CLI，再失败返回空列表。

---

### 3.9 `fetch_historical_candles` — 历史 K 线分页获取

**模块**: `data/market_data.py`
**类型**: 模块级函数

```python
def fetch_historical_candles(
    inst_id: str,
    bar: str = "1D",
    days: int = 730,
    max_limit_per_page: int = 300,
) -> List[Dict]
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `inst_id` | str | - | 交易对 ID |
| `bar` | str | `"1D"` | 时间周期 |
| `days` | int | `730` | 获取天数（约 2 年） |
| `max_limit_per_page` | int | `300` | 每页最大数量 |

**返回值**：与 `fetch_candles` 一致，已去重并按时间正序排列。

---

### 3.10 `resample_candles` — 跨周期重采样

**模块**: `data/market_data.py`
**类型**: 模块级函数

```python
def resample_candles(candles: List[Dict], target_tf: str) -> List[Dict]
```

**支持的重采样路径**：

| 源周期 | 目标周期 | 聚合数 |
|--------|----------|--------|
| `5m` | `1h` | 12 |
| `15m` | `1h` | 4 |
| `15m` | `4h` | 16 |
| `30m` | `1h` | 2 |
| `30m` | `4h` | 8 |
| `30m` | `1D` | 48 |
| `1h` | `4h` | 4 |
| `1h` | `1D` | 24 |
| `4h` | `1D` | 6 |

**聚合规则**：Open=首根开盘价，High=周期内最高价，Low=周期内最低价，Close=末根收盘价，Volume=成交量之和。

---

### 3.11 `candles_to_dataframe` — K 线转 DataFrame

**模块**: `data/market_data.py`
**类型**: 模块级函数

```python
def candles_to_dataframe(candles: List[Dict]) -> pd.DataFrame
```

**返回值**：

```python
pd.DataFrame
# 索引：DatetimeIndex（由 ts 转换）
# 列：open, high, low, close, volume
```

---

### 3.12 CLI — 回测入口

**命令**：

```bash
python backtest_v4_wave.py --symbol BTC
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--symbol` | str | `BTC` | 交易对符号 |

**输出**：

- 控制台打印 9 年/4 年回测对比表（含/无成本）
- 写入 `backtest_results/v4_wave_9year_{symbol_lower}.json`

---

### 3.13 CLI — 实盘入口

**命令**：

```bash
python live/v4_wave_trader.py
```

**环境变量**：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TREND_SYMBOLS` | `BTC,ETH,SOL,UNI` | 监控币种 |
| `SCHEDULER_INTERVAL_SECONDS` | `60` | 轮询间隔（秒） |
| `AUTO_EXECUTE` | `true` | 是否实盘下单 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `MAX_POSITION_PCT` | `25` | 单币种最大仓位(%) |
| `INITIAL_CAPITAL` | `200` | 初始资金（回退用） |

**退出信号**：`Ctrl+C` 或 `SIGTERM`，优雅停止。

---

## 4. 错误码

本子系统无独立 HTTP 错误码（无 HTTP 服务）。错误通过返回值字段与日志体现：

| 错误标识 | 来源 | 说明 | 处理 |
|----------|------|------|------|
| `error: "日线数据不足"` | `v4_wave_engine.py` | 日线数据 < 250 天 | 返回 WAIT/NEUTRAL 空信号 |
| `error: "无法获取{spot_inst} K线数据"` | `v4_wave_engine.py` | OKX API 调用失败返回空 | 调用方检查网络/API |
| `fusion_rule: "insufficient_data"` | `ewave_strategy_adapter.py` | 波浪数据 < 90 天 | 保持 V4 仓位 |
| `fusion_rule: "wave_error_keep_v4"` | `v4_wave_engine.py` | 波浪识别异常 | 保持 V4 仓位，记录异常 |
| `physics_error: <str>` | `ewave_strategy_adapter.py` | 物理特征计算失败 | 物理字段置 None，继续主流程 |
| `physics_adjustment.reason: "physics_error: <str>"` | `v4_wave_engine.py` | 物理置信度调节失败 | 跳过物理调节，使用基础仓位 |
| `enabled: False` | `ewave_strategy_adapter.py` | 波浪策略被禁用 | 使用 V4 仓位作为最终仓位 |
| 日志 `❌ 开仓失败` | `live/v4_wave_trader.py` | 实盘下单失败 | 保留元数据，下一轮重试 |
| 日志 `❌ 止损硬单挂单失败` | `live/v4_wave_trader.py` | 交易所 SL 挂单失败 | 程序端继续监控 SL |

---

## 5. 版本管理

### 5.1 版本策略

- Python API 版本通过 `WaveConfig` 与各 `__init__` 参数演进
- 向后兼容：新增字段不破坏旧调用方；废弃字段保留至少 1 个版本
- `final_signal` 结构保持与三屏系统 `compute_full_trading_signal` 兼容
- 实盘执行器通过 `data/v4_position_sltp.json` 元数据版本号管理持仓状态

### 5.2 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-07-31 | 初始版本：11 个 Python API + 2 个 CLI 接口规格建立 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-31
