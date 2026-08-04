# 接口规格文档 — 三屏趋势系统

> **定位：** 全部公开 API 的签名、参数、返回值、调用示例
> **版本：** v4.0.0 | **更新：** 2026-07-25
> **主线策略：** V4 + 波浪互斥融合 — BTC 年化 56.43%，夏普 1.41，回撤 -43.31%
> **系统边界：** 本系统无自有 HTTP 服务，对外以 Python API 为主；HTTP 调用作为客户端访问 10-经典指标系统

---

## 目录

- [1. 接口概览](#1-接口概览)
- [2. 认证方式](#2-认证方式)
- [3. 主引擎 API (engine.py)](#3-主引擎-api-enginepy)
- [4. 经典系统 HTTP 桥接 API (classic_bridge.py)](#4-经典系统-http-桥接-api-classic_bridgepy)
- [5. 入场信号 API (signals.py)](#5-入场信号-api-signalspy)
- [6. 离场集成 API (exit_integration.py)](#6-离场集成-api-exit_integrationpy)
- [7. 实盘执行器 API (live/v4_wave_trader.py)](#7-实盘执行器-api-livev4_wave_traderpy)
- [8. 回测引擎 API (backtest/engine.py)](#8-回测引擎-api-backtestenginepy)
- [9. 集成推理层 API (ml/)](#9-集成推理层-api-ml)
- [10. CLI 命令](#10-cli-命令)
- [11. 错误码](#11-错误码)
- [12. 版本管理](#12-版本管理)

---

## 1. 接口概览

### 1.1 接口列表

| 模块 | 函数/类 | 用途 |
|------|---------|------|
| **engine.py** | `compute_full_trading_signal()` | 完整入口：自动取数+计算信号（含风向标+价值风险） |
| **engine.py** | `compute_trend_signal_from_dataframes()` | 纯计算入口：数据由调用方提供（适合回测） |
| **engine.py** | `five_algo_decision()` | 五大算法决策 + 风向标闸门 |
| **engine.py** | `evaluate_btc_wind_vane()` | BTC风向标闸门评估（宏观方向过滤） |
| **engine.py** | `compute_value_risk_assessment()` | 价值风险评估（Elder-ray + 波动率 + RR） |
| **engine.py** | `evaluate_addon_decision()` | 加仓决策评估（逆势背离 + 顺势趋势强度） |
| **engine.py** | `confidence_to_position()` | 置信度 → 仓位映射 |
| **engine.py** | `fetch_entry_signals_from_classic()` | 从经典系统获取入场信号 |
| **engine.py** | `evaluate_exit_from_classic()` | 从经典系统获取离场决策 |
| **classic_bridge.py** | `get_classic_base_url()` | 获取经典系统 Base URL |
| **classic_bridge.py** | `is_classic_system_available()` | 经典系统健康检查 |
| **classic_bridge.py** | `_make_request()` | 统一 HTTP 请求封装 |
| **signals.py** | `fetch_freqtrade_signals()` | 从信号池读取 Freqtrade 多策略信号 |
| **signals.py** | `align_freqtrade_with_trend()` | Freqtrade 信号与趋势对齐校准 |
| **exit_integration.py** | `evaluate_exit()` | 离场决策主入口（API 优先，导入降级） |
| **exit_integration.py** | `evaluate_exit_via_api()` | HTTP API 调用经典系统离场 |
| **exit_integration.py** | `get_exit_system_classic()` | 直接导入 ClassicExitSystem |
| **live/v4_wave_trader.py** | `V4WaveTrader` | V4+波浪策略实盘执行器 |
| **live/v4_wave_trader.py** | `_compute_sltp()` | 止盈止损融合计算 |
| **backtest/engine.py** | `BacktestEngine` | 向量化回测引擎 |
| **ml/algo_ensemble.py** | `predict_ensemble()` | LightGBM 集成推理预测 |
| **ml/algo_ensemble.py** | `collect_sample()` | 收集训练样本 |
| **ml/algo_ensemble.py** | `train_ensemble()` | 训练集成模型 |
| **ml/algo_ensemble.py** | `extract_ensemble_features()` | 提取 46 维特征 |
| **ml/llm_reasoning.py** | `reason_if_needed()` | LLM 辩证推理（按需触发） |
| **ml/llm_reasoning.py** | `should_trigger_llm()` | 判断是否需要 LLM 介入 |
| **ml/label_samples.py** | `label_collected_samples()` | 样本自动标注 |
| **ml/label_samples.py** | `train_from_collected()` | 一键训练 |

### 1.2 HTTP 路由清单（本系统作为客户端）

本系统**不提供 HTTP 服务**，所有 HTTP 调用均为客户端访问 10-经典指标系统：

| 方法 | 路径 | 用途 | 调用方 |
|------|------|------|-------|
| GET | `/api/health` | 健康检查 | `classic_bridge.py` |
| GET | `/api/freqtrade/signals` | 获取 Freqtrade 多策略入场信号 | `signals.py` |
| POST | `/api/exit/evaluate` | 获取离场决策 | `exit_integration.py` |

**Base URL：** 环境变量 `CLASSIC_SYSTEM_BASE_URL`，默认 `http://127.0.0.1:8092`

---

## 2. 认证方式

### 2.1 经典系统 HTTP 调用

本系统对 10-经典指标系统的 HTTP 调用**不需要认证**，走本地内网（默认 `127.0.0.1:8092`），通过环境变量 `CLASSIC_SYSTEM_BASE_URL` 配置目标地址。

### 2.2 OKX API 认证

OKX K线数据获取通过 `data/market_data.py` 完成，使用 OKX REST API：
- **API Key / Secret / Passphrase**：通过环境变量或 `.env` 文件配置
- **模拟盘标志**：通过 `OKX_SIMULATED` 环境变量控制
- **降级策略**：API 不可用时通过 OKX CLI 获取

### 2.3 LLM 服务认证

`ml/llm_reasoning.py` 调用 DeepSeek API：
- **API Key**：进程环境变量 > `experiments/ab-trading/config/.env` > `12-三屏趋势系统/.env`
- **触发模式**：按需触发（节省 token），仅在置信度 <40 或 40-60 + 矛盾时触发

### 2.4 Tavily API（Path B 基本面数据）

`data/tavily_data.py` 调用 Tavily Search API：
- **API Key**：环境变量 `TAVILY_API_KEY`
- **缓存**：30 分钟本地缓存
- **降级**：API 不可用时回退到经典指标 / 6-TRADING annotation

---

## 3. 主引擎 API (engine.py)

### 3.1 compute_full_trading_signal

**完整三屏交易信号计算（含数据获取）**

```python
def compute_full_trading_signal(
    spot_inst: str = DEFAULT_INST_SPOT,   # 默认 "BTC-USDT"
    is_btc: bool = True,
) -> dict
```

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| spot_inst | str | "BTC-USDT" | 现货交易对 |
| is_btc | bool | True | 是否为BTC币种（影响风向标数据来源） |

**返回值：** 完整信号结构（含 `btc_wind_vane`、`final_signal`、`value_risk_assessment` 等字段，详见 §3.8）

**错误返回：** K线获取失败时返回 `{"error": "无法获取{spot_inst} K线数据"}`

**调用示例：**

```python
from engine import compute_full_trading_signal

# BTC 完整信号
result = compute_full_trading_signal("BTC-USDT", is_btc=True)

# ETH 完整信号（自动获取 BTC 风向标数据）
result = compute_full_trading_signal("ETH-USDT", is_btc=False)
```

**调用链路：**

```
compute_full_trading_signal
  ├─ fetch_candles(spot_inst, "1D"/"1W"/"1H")        ← OKX K线
  ├─ fetch_fundamental_data(symbol)                  ← A系列研报 / 经典指标回退
  ├─ fetch_entry_signals_from_classic(symbol)        ← Freqtrade 信号
  ├─ fetch_candles("BTC-USDT", "1D"/"1W")            ← BTC 风向标（非BTC时）
  └─ compute_trend_signal_from_dataframes(...)       ← 核心计算
```

---

### 3.2 compute_trend_signal_from_dataframes

**纯计算入口：数据由调用方提供，适合回测/单元测试**

```python
def compute_trend_signal_from_dataframes(
    weekly_df,                                  # 周线 DataFrame（OHLCV）
    daily_df,                                   # 日线 DataFrame（OHLCV）
    symbol: str = "BTC",
    price: Optional[float] = None,
    fundamental_data: Optional[Dict] = None,
    freqtrade_signals: Optional[Dict] = None,
    is_btc: bool = False,
    btc_daily_df=None,                          # BTC日线（波动率基准+风向标）
    btc_weekly_df=None,                         # BTC周线（风向标MA200）
    btc_trend_direction: Optional[str] = None,  # BTC趋势方向（小币过滤）
    use_fundamental: Optional[bool] = None,     # 是否启用基本面融合
) -> dict
```

**参数说明：**

| 参数 | 类型 | 说明 |
|------|------|------|
| weekly_df | DataFrame | 周线K线（open/high/low/close/volume） |
| daily_df | DataFrame | 日线K线（至少 250 根用于 V4 主策略） |
| symbol | str | 币种符号（如 "BTC"） |
| price | float | 当前价格（None 则从 daily_df 推断） |
| fundamental_data | dict | 基本面数据 `{"direction", "confidence"}` |
| freqtrade_signals | dict | Freqtrade 信号 `{"1h": {...}, "4h": {...}}` |
| is_btc | bool | 是否为BTC币种 |
| btc_daily_df | DataFrame | BTC 日线（非 BTC 时必传，用于风向标和波动率） |
| btc_weekly_df | DataFrame | BTC 周线（非 BTC 时必传，用于风向标 MA200） |
| btc_trend_direction | str | BTC 趋势方向（"BULL"/"BEAR"/"NEUTRAL"），非 BTC 币种趋势跟随过滤 |
| use_fundamental | bool | 是否启用基本面融合（None=从 config 读取） |

**决策链路：**

```
1. calc_trend_consistency()                    ← 趋势一致性（静态+三维动态）
2. calc_bayesian_confidence()                  ← 贝叶斯置信度
3. calc_classic_indicator_confidence()         ← 经典指标置信度
4. fuse_technical_fundamental()                ← 技术+基本面融合
5. CompositePredictor.predict()                ← P3.4 综合预测引擎调节
6. _integrate_freqtrade_signals()              ← Freqtrade 信号校准
7. evaluate_btc_wind_vane()                    ← BTC风向标闸门
8. five_algo_decision()                        ← 五大算法决策
9. V4 主策略（HalvingTopExitStrategy/AltcoinTrendStrategy）  ← 定方向
10. compute_value_risk_assessment()            ← 价值风险评估
11. PITD 物理置信度调节（η<0.10 时）           ← 弱趋势仓位微调
12. EWaveStrategyAdapter.evaluate()            ← 波浪择时加仓（互斥融合）
```

---

### 3.3 five_algo_decision

**五大算法决策 + 风向标闸门**

```python
def five_algo_decision(
    trend_consistent: bool,
    direction: str,                              # BULL/BEAR/NEUTRAL
    confidence: float,                           # 0-100
    freqtrade_signals: Optional[Dict] = None,
    freqtrade_consistent: bool = False,
    btc_wind_vane: Optional[Dict] = None,
    consistency_level: str = "STRONG_CONSISTENT",
    reversal_confidence: float = 0.0,
    daily_dynamics: Optional[Dict] = None,
    trend_phase: str = "UNKNOWN",
    trend_phase_confidence: float = 0.0,
    elder_ray: Optional[Dict] = None,
) -> dict
```

**参数说明：**

| 参数 | 类型 | 说明 |
|------|------|------|
| trend_consistent | bool | 趋势是否一致（Screen1） |
| direction | str | 最终方向 "BULL"/"BEAR"/"NEUTRAL" |
| confidence | float | 综合置信度（0-100） |
| freqtrade_signals | dict | Freqtrade 信号 `{"1h": {...}, "4h": {...}}` |
| freqtrade_consistent | bool | Freqtrade 信号是否与趋势同向 |
| btc_wind_vane | dict | `evaluate_btc_wind_vane()` 返回值 |
| consistency_level | str | 一致性级别：STRONG/REVERSAL/NEUTRAL/INCONSISTENT |
| reversal_confidence | float | 逆转置信度（0-100） |
| daily_dynamics | dict | 日线动态指标 `{"avg_speed", "avg_acceleration"}` |
| trend_phase | str | 趋势生命周期阶段：EARLY/ACCELERATING/MATURING/REVERSING/UNKNOWN |
| trend_phase_confidence | float | 阶段判定置信度（0-100） |
| elder_ray | dict | Elder-ray 高级分析结果（含背离信号） |

**返回值：**

```python
{
    "action": "ENTER_LONG",             # "ENTER_LONG"/"ENTER_SHORT"/"WAIT"
    "confidence": 72.5,                  # float: 0-100
    "position": {"position_pct": 0.30, "tier": "moderate"},
    "reason": "趋势一致+Freqtrade 4h看多+置信72.5%，正常仓位入场",
    "wind_vane_blocked": False,          # bool: 是否被风向标硬拦截
    "wind_vane_soft_blocked": False,     # bool: 是否被风向标软拦截
    "reversal_trial": False,             # bool: 是否为逆转轻仓试探
    "dynamic_timing_entry": False,       # bool: 是否为动态时机入场
    "trend_phase": "ACCELERATING",       # str: 趋势阶段
    "phase_adjusted": False,             # bool: 是否经过阶段调整
    "elder_ray_divergence_entry": False, # bool: 是否为Elder-ray背离入场
}
```

**决策优先级：**

```
0. BTC风向标闸门（hard_block → WAIT；soft_block → 轻仓试探）
1. 趋势一致性分级（INCONSISTENT → WAIT；REVERSAL → trial 仓位上限）
2. 趋势生命周期阶段调整（EARLY/MATURING/REVERSING 调整仓位）
3. Screen3 入场时机：
   - Freqtrade 同向 → 直接入场
   - Elder-ray 背离 + 趋势一致 → 降级入场（阈值 -15~25）
   - 动态时机评分（speed/accel）→ 降级入场（阈值 -5~10）
   - 纯置信度降级入场（阈值默认 70，逆转 60）
```

---

### 3.4 evaluate_btc_wind_vane

**BTC风向标闸门评估 — 全系统做多/做空闸门**

```python
def evaluate_btc_wind_vane(
    btc_daily_df=None,                           # BTC日线（含close列）
    btc_weekly_df=None,                          # BTC周线（含close列）
    reversal_context: Optional[Dict] = None,     # 动态逆转上下文
) -> Dict
```

**reversal_context 结构：**

```python
{
    "consistency_level": str,       # STRONG/REVERSAL/NEUTRAL/INCONSISTENT
    "reversal_alignment": str,      # NONE/WEEKLY_REVERSAL/DAILY_REVERSAL/BOTH_REVERSAL
    "reversal_confidence": float,   # 0-100
    "overall_direction": str,       # BULL/BEAR/NEUTRAL
}
```

**返回值：**

```python
{
    "enabled": True,                            # bool: 风向标总开关
    "long_gate_open": True,                     # bool: 做多闸门
    "short_gate_open": False,                   # bool: 做空闸门
    "force_long": True,                         # bool: 强制做多（站上MA200）
    "prohibit_short": True,                     # bool: 禁止做空（硬拦截）
    "prohibit_long": False,                     # bool: 禁止做多
    "btc_daily_ma128": 62000.0,                 # float: BTC日线MA128
    "btc_weekly_ma200": 58000.0,                # float: BTC周线MA200
    "btc_last_daily_close": 65000.0,            # float: BTC最近日线收盘
    "btc_last_weekly_close": 63000.0,           # float: BTC最近周线收盘
    "consecutive_below_ma128": 0,               # int: 连续低于MA128的日数
    "weekly_above_ma200": True,                 # bool: 周收盘是否站上MA200
    "daily_below_ma128_confirmed": False,       # bool: 是否有效跌破MA128
    "reason": "BTC周收盘站上MA200，强制做多，禁止做空（硬拦截）",
    "hard_block": True,                         # bool: 硬拦截（严格禁止反向）
    "soft_block": False,                        # bool: 软拦截（允许轻仓试探反向）
    "reversal_downgrade": False,                # bool: 是否触发了动态降级
    "reversal_direction": "NEUTRAL",            # str: 逆转方向（软拦截时有效）
}
```

**三条大原则：**

| 规则 | 条件 | 效果 | 优先级 |
|------|------|------|--------|
| 规则3 | BTC周收盘价 > 周线MA200 | 强制做多，禁止做空 | 最高 |
| 规则1 | BTC连续3日收盘 < 日线MA128 | 做空闸门打开，做多关闭 | 次之 |
| 中间 | 未跌破MA128且未站上MA200 | 双向开放 | 默认 |

---

### 3.5 compute_value_risk_assessment

**价值风险评估（Elder-ray + 波动率 + RR）**

```python
def compute_value_risk_assessment(
    symbol: str,
    direction: str,                              # BULL/BEAR
    current_price: float,
    daily_df,                                    # 至少31根日线
    is_btc: bool = False,
    btc_daily_df=None,                           # BTC日线（非BTC时必传）
) -> Dict
```

**返回值：**

```python
{
    "symbol": "BTC",
    "is_btc": True,
    "direction": "BULL",
    "current_price": 65000.0,
    "elder_ray": {                               # Elder-ray 趋势强度
        "direction": "BULL", "strength": 75.0,
        "bull_power": 500.0, "bear_power": -200.0,
        "ema_slope": 0.025, "divergence": False, ...
    },
    "volatility": {                              # 波动率放大参数
        "vol_ratio": 1.17,                       # 限制在 0.5-2.5
        "coin_vol": 0.035, "btc_vol": 0.030, ...
    },
    "take_profit_stop_loss": {                   # 止盈止损
        "take_profit_price": 67600.0,
        "stop_loss_price": 58500.0,
        "take_profit_pct": 4.0,                  # 4% × vol_ratio
        "stop_loss_pct": 10.0,                   # 10% × vol_ratio
        "vol_ratio": 1.17,
        "risk_reward": {"rr_ratio": 1.5, "value_gt_risk": True, ...},
    },
    "value_gt_risk": True,                       # bool: 价值>风险
}
```

**错误返回：** 日线数据不足时返回 `{"error": "日线数据不足"}`

---

### 3.6 evaluate_addon_decision

**加仓决策评估（逆势背离 + 顺势趋势强度）**

```python
def evaluate_addon_decision(
    symbol: str,
    direction: str,                              # BULL/BEAR
    current_price: float,
    entry_price: float,
    is_btc: bool,
    daily_df,                                    # 至少31根日线
    btc_daily_df=None,
    unrealized_pnl_pct: float = 0.0,             # 未实现盈亏百分比
    current_position_pct: float = 0.0,           # 当前仓位
    max_position_cap: float = None,              # 仓位上限（默认 MAX_ADDON_POSITION_PCT=0.70）
) -> Dict
```

**返回值：**

```python
{
    "can_add": True,                             # bool: 是否允许加仓
    "addon_type": "divergence",                  # str: "divergence"/"trend_strength"/None
    "addon_pct": 0.15,                           # float: 加仓比例
    "reason": "BTC亏损8%+看涨背离，逆势加仓",
    "elder_ray": {...},                          # Elder-ray 结果
    "volatility": {...},                         # 波动率参数
}
```

**两类加仓机制：**

| 加仓类型 | 触发条件 | 仓位上限 |
|---------|---------|---------|
| 逆势背离加仓 | 亏损≥8%（BTC）或 8%×波动率比（其他币）+ 背离 + 价值>风险 | 70% |
| 顺势趋势强度加仓 | 盈利≥50% + Elder-ray强度≥65 | 70% |

---

### 3.7 confidence_to_position

**置信度 → 仓位映射**

```python
def confidence_to_position(confidence: float) -> dict
```

**参数：** `confidence` (float) — 0-100 的置信度

**返回值：**

```python
{"position_pct": 0.30, "tier": "moderate"}
```

**仓位档位映射表：**

| 置信度阈值 | 仓位档位 (tier) | 仓位比例 (position_pct) |
|-----------|----------------|----------------------|
| ≥85 | heavy | 0.60 |
| ≥75 | medium | 0.45 |
| ≥65 | moderate | 0.30 |
| ≥55 | light | 0.15 |
| ≥45 | trial | 0.05 |
| ≥0 | micro | 0.02 |
| 不满足 | none | 0.0 |

---

### 3.8 fetch_entry_signals_from_classic

**从经典指标系统获取入场信号**

```python
def fetch_entry_signals_from_classic(
    symbol: str,
    timeframes: Optional[list] = None,           # 默认 ["1h", "4h"]
) -> Dict
```

**返回值：** `{timeframe: MultiStrategySignal}`，详见 §5

---

### 3.9 evaluate_exit_from_classic

**从经典指标系统获取离场决策**

```python
def evaluate_exit_from_classic(
    position_info: Dict,                         # 持仓信息
    candles_1h: Optional[list] = None,           # 1小时K线
    regime: str = "trend",                       # 市场 regime
) -> Dict
```

**position_info 结构：**

```python
{"symbol", "side", "entry_price", "current_price", "quantity", "entry_time", "notional_usd"}
```

**返回值：**

```python
{
    "action": "close",                           # "close"/"reduce"/"hold"/"raise_tp"
    "confidence": 0.85,
    "reason": "止损线触发",
    "priority": "P0",                            # P0/P1/P2/P3/error
    "reduce_fraction": 0.5,                      # 减仓比例（reduce 动作）
    "suggested_price": 60000.0,
    "new_tp_price": 70000.0,                     # raise_tp 动作的新止盈价
    "new_tp_pct": 0.06,
}
```

---

## 4. 经典系统 HTTP 桥接 API (classic_bridge.py)

### 4.1 get_classic_base_url

```python
def get_classic_base_url() -> str
```

获取经典系统基础 URL。优先读取环境变量 `CLASSIC_SYSTEM_BASE_URL`，默认 `http://127.0.0.1:8092`。

---

### 4.2 _make_request

**统一的经典系统 API 请求封装**

```python
def _make_request(
    endpoint: str,                               # 如 "/api/freqtrade/signals"
    method: str = "GET",                         # "GET" / "POST"
    params: Optional[Dict] = None,               # URL query 参数
    json_data: Optional[Dict] = None,            # POST body
    timeout: float = 5.0,                        # 超时（秒）
) -> Dict[str, Any]
```

**返回值：**

```python
{"ok": True, "data": {...}, "error": None}       # 成功
{"ok": False, "data": None, "error": "http_500"} # 失败
```

**错误类型：**

| error 值 | 说明 |
|---------|------|
| `requests_not_installed` | requests 库未安装 |
| `http_{status_code}` | HTTP 状态码错误（如 `http_500`） |
| `request_error:{detail}` | 网络异常（如超时、连接拒绝） |
| `unsupported_method:{method}` | 不支持的 HTTP 方法 |

---

### 4.3 is_classic_system_available

```python
def is_classic_system_available() -> bool
```

检查经典系统是否可用（调用 `/health`，超时 2 秒）。

---

### 4.4 HTTP 路由详情

#### GET /api/freqtrade/signals

获取 Freqtrade 多策略入场信号。

**Query 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| symbol | str | 币种符号（如 "BTC"） |
| timeframes | str | 时间周期列表（如 "1h,4h"） |

**响应（200）：**

```python
{
    "signals": {
        "BTC": {
            "1h": {"signal": "BUY", "confidence": 80.0, "strategy": "RegimeHybridStrategy", "details": [...]},
            "4h": {"signal": "BUY", "confidence": 75.0, "strategy": "MultiGroupStrategy", "details": [...]}
        }
    }
}
```

#### POST /api/exit/evaluate

获取离场决策。

**请求体：**

```python
{
    "symbol": "BTC", "side": "long",
    "entry_price": 60000.0, "current_price": 65000.0,
    "quantity": 0.5, "entry_time": 1700000000,
    "notional_usd": 32500.0, "regime": "trend"
}
```

**响应（200）：**

```python
{
    "action": "reduce", "confidence": 0.7,
    "reason": "移动止盈触发", "priority": "P2",
    "reduce_fraction": 0.5, "suggested_price": 65000.0,
    "new_tp_price": 0, "new_tp_pct": 0
}
```

#### GET /api/health

健康检查。响应（200）：`{"status": "ok"}`

---

## 5. 入场信号 API (signals.py)

### 5.1 数据类

```python
class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    HOLD = "hold"

@dataclass
class StrategySignal:
    strategy_name: str
    signal: SignalDirection
    confidence: float = 0.0
    entry_price: Optional[float] = None

@dataclass
class MultiStrategySignal:
    symbol: str
    timeframe: str
    direction: SignalDirection
    confidence: float
    strategy_count: int
    long_votes: int
    short_votes: int
    strategies: List[StrategySignal]

    @property
    def is_long(self) -> bool    # direction == LONG
    @property
    def is_short(self) -> bool   # direction == SHORT
    @property
    def is_hold(self) -> bool    # direction == HOLD
```

---

### 5.2 fetch_freqtrade_signals

**从信号池读取 Freqtrade 多策略信号**

```python
def fetch_freqtrade_signals(
    symbol: str,
    timeframes: Optional[List[str]] = None,      # 默认 ["1h", "4h"]
) -> Dict[str, MultiStrategySignal]
```

**返回值：** `{timeframe: MultiStrategySignal}`

**降级策略：** 信号池不存在或币种未在池中时，返回中性信号（HOLD，confidence=0）。

---

### 5.3 align_freqtrade_with_trend

**将 Freqtrade 信号与趋势方向对齐，校准置信度**

```python
def align_freqtrade_with_trend(
    trend_direction: str,                        # "BULL"/"BEAR"/"NEUTRAL"
    freqtrade_signal: MultiStrategySignal,
) -> Dict[str, float]
```

**返回值：**

```python
{"confidence_adjustment": 8.0, "consistent": True}
```

**校准规则：**

| 场景 | 调整 |
|------|------|
| 同向（BULL+LONG / BEAR+SHORT） | +confidence × weight（1h: 10%, 4h: 15%） |
| 反向 | -10% |
| 中性 | 0 |

---

## 6. 离场集成 API (exit_integration.py)

### 6.1 数据类

```python
class ExitAction(str, Enum):
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"    # 提高止盈价（强反弹时让利润奔跑）

@dataclass
class PositionInfo:
    symbol: str
    side: str = "long"
    entry_price: float = 0.0
    current_price: float = 0.0
    quantity: float = 0.0
    entry_time: float = 0.0
    notional_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    unrealized_pnl_pct: float = 0.0
    leverage: float = 1.0
    atr_pct: float = 0.02
    mfe_pnl_pct: float = 0.0
    max_dd_pct: float = 0.0
    trailing_armed: bool = False
    trailing_stop_price: float = 0.0
    liq_price: float = 0.0

@dataclass
class ExitDecisionResult:
    action: ExitAction
    confidence: float = 0.0
    reason: str = ""
    priority: str = ""
    reduce_fraction: float = 0.0
    suggested_price: float = 0.0
    new_tp_price: float = 0.0
    new_tp_pct: float = 0.0
    raw_data: Dict[str, Any] = field(default_factory=dict)
```

---

### 6.2 evaluate_exit

**离场决策主入口（API 优先，导入降级）**

```python
def evaluate_exit(
    position: PositionInfo,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",                       # trend/choppy/neutral
    use_api: bool = True,
) -> ExitDecisionResult
```

**调用顺序：**
1. 优先调用 `evaluate_exit_via_api()`（HTTP API）
2. API 不可用时降级到 `get_exit_system_classic()`（直接导入）
3. 两者均不可用返回 `ExitDecisionResult(action=HOLD, priority="unavailable")`

---

### 6.3 evaluate_exit_via_api

```python
def evaluate_exit_via_api(
    position: PositionInfo,
    candles_1h: Optional[List[Dict]] = None,
    regime: str = "trend",
) -> ExitDecisionResult
```

通过 HTTP POST `/api/exit/evaluate` 调用经典系统离场决策。

---

### 6.4 get_exit_system_classic

```python
def get_exit_system_classic() -> Optional[Any]
```

尝试直接导入经典系统的 `ClassicExitSystem`（同机部署时使用）。

---

## 7. 实盘执行器 API (live/v4_wave_trader.py)

### 7.1 V4WaveTrader 类

```python
class V4WaveTrader:
    def __init__(self)
    def initialize(self) -> bool                # 初始化 AsterExecutor
    def get_positions(self) -> dict             # 获取当前持仓
    def run_once(self) -> None                  # 单轮轮询
    def run_forever(self) -> None               # 持续轮询（Ctrl+C 停止）
```

**关键私有方法：**

| 方法 | 功能 |
|------|------|
| `_load_position_meta()` | 从 `data/v4_position_sltp.json` 加载持仓 SL/TP 元数据 |
| `_save_position_meta()` | 持久化持仓 SL/TP 元数据 |
| `_check_sltp(positions)` | 检查所有持仓的止盈止损 + 移动止盈 |
| `_dynamic_adjust_sltp(positions, full_signal_map)` | 动态调整 SL/TP（每轮基于最新信号） |
| `_sync_sltp_orders(symbol, meta)` | 同步交易所 SL/TP 硬单（取消旧单 → 挂新单） |
| `_handle_entry(symbol, action, direction, confidence, full_signal)` | 执行开仓 |
| `_handle_exit(symbol, action, direction, reason=None)` | 执行平仓 |
| `_calc_notional(symbol, position_pct)` | 计算名义价值 |

---

### 7.2 _compute_sltp

**根据 V4+波浪融合信号计算止盈止损**

```python
def _compute_sltp(
    full_signal: dict,
    current_price: float,
) -> dict
```

**返回值：**

```python
{
    "stop_loss_pct": 0.06,                  # float: 止损百分比（0.06=6%）
    "take_profit_pct": 0.15,                # float: 止盈百分比（0.15=15%）
    "trailing_enabled": True,               # bool: 是否启用移动止盈
    "trailing_activate_pct": 0.05,          # float: 移动止盈激活阈值 5%
    "trailing_callback_pct": 0.025,         # float: 移动止盈回撤 2.5%
    "sltp_mode": "trend_continuation",      # str: 模式标签
    "reason": "趋势延续型(W1)：宽止损6%+移动止盈(激活5%/回撤2.5%)",
}
```

**SL/TP 策略融合参数：**

| 模式 | 止损 | 止盈 | 移动止盈 |
|------|------|------|---------|
| 趋势延续型（W1/W3/W5/IMPULSE） | 6% | 15% | 启用（激活5%/回撤2.5%） |
| 趋势反转型（W2/W4/ABC/CORRECTIVE） | 2.5% | 6% | 关闭 |
| 默认模式 | 4% | 9% | 关闭 |
| 低置信度（wave_conf<0.5） | SL × 0.7 | 不变 | 不变 |

**SL 百分比语义：**
- `sl_pct = 0.06` → pnl ≤ -6% 止损（常规）
- `sl_pct = 0.0` → pnl ≤ 0 止损（保本）
- `sl_pct = -0.03` → pnl ≤ +3% 止损（锁定 3% 利润）

---

### 7.3 配置项（环境变量）

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `TREND_SYMBOLS` | "BTC,ETH,SOL,UNI" | 交易币种列表 |
| `SCHEDULER_INTERVAL_SECONDS` | 60 | 轮询间隔（秒） |
| `LOG_LEVEL` | "INFO" | 日志级别 |
| `AUTO_EXECUTE` | "true" | 是否自动执行真实交易 |
| `MAX_POSITION_PCT` | 25 | 单仓位最大百分比 |
| `INITIAL_CAPITAL` | 200 | 默认初始资金（USDT） |

---

## 8. 回测引擎 API (backtest/engine.py)

### 8.1 BacktestEngine 类

```python
class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 10000.0,        # 初始资金（USDT）
        commission: float = 0.0005,              # 手续费率（单边 0.05%）
        slippage: float = 0.0005,                # 滑点率（单边 0.05%）
        leverage: float = 1.0,                   # 杠杆倍数
        physics_config=None,                     # PhysicsEnhancerConfig（None=不启用）
    )

    def run(
        self,
        prices: pd.Series,                       # 收盘价序列
        position_sizes: pd.Series,               # 目标仓位比例（-1~1）
        symbol: str = "BTC",
        ohlcv: Optional[pd.DataFrame] = None,    # OHLCV（物理增强时需要）
        wave_signals: Optional[Union[np.ndarray, pd.Series]] = None,
        wave_confs: Optional[Union[np.ndarray, pd.Series]] = None,
        base_positions: Optional[Union[np.ndarray, pd.Series]] = None,
    ) -> Dict
```

**返回值：**

```python
{
    "symbol": "BTC",
    "initial_capital": 10000.0,
    "final_equity": 18500.0,
    "total_return": 85.0,                        # 百分比
    "equity_curve": pd.Series,                   # 净值曲线
    "returns": pd.Series,                        # 日收益率
    "trades": pd.DataFrame,                      # 交易记录
    "position": pd.Series,                       # 实际仓位
    "metrics": dict,                             # 绩效指标
    "prices": pd.Series,
    "physics_stats": dict,                       # 物理增强统计（若启用）
}
```

**trades DataFrame 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| entry_time | datetime | 入场时间 |
| exit_time | datetime | 离场时间 |
| side | str | "long"/"short" |
| entry_price | float | 入场价 |
| exit_price | float | 离场价 |
| size | float | 仓位大小 |
| pnl_pct | float | 盈亏百分比 |
| holding_bars | int | 持仓K线数 |
| open | bool | 是否未平仓（仅最后一条） |

**调用示例：**

```python
from backtest import BacktestEngine, BuyAndHoldStrategy, generate_sample_data

df = generate_sample_data(n_days=1000, start_price=100.0, volatility=0.02)
engine = BacktestEngine(initial_capital=10000.0, commission=0.0005, slippage=0.0005)
strategy = BuyAndHoldStrategy()
signals = strategy.generate_signals(df)
result = engine.run(df["close"], signals, symbol="BTC")
print(f"总收益: {result['total_return']:.2f}%")
```

---

## 9. 集成推理层 API (ml/)

### 9.1 predict_ensemble (algo_ensemble.py)

**LightGBM 集成推理预测**

```python
def predict_ensemble(full_signal: dict) -> dict
```

**返回值：**

```python
{
    "direction": "BULL",                # "BULL"/"BEAR"/"NEUTRAL"
    "confidence": 72.5,                  # float: 0-100
    "prob_up": 0.78,                     # float: 0-1
    "prob_down": 0.22,                   # float: 0-1
    "source": "ensemble",                # "ensemble"/"fallback"
    "features": {...}                    # 46维特征 dict
}
```

**46维特征分组：**

| 分组 | 维度 | 来源 |
|------|------|------|
| 趋势一致性 | 16维 | `trend_consistency`（周线+日线） |
| 贝叶斯置信度 | 3维 | `bayesian_confidence` |
| 经典指标置信度 | 10维 | `classic_indicator_confidence` |
| 技术基本面融合 | 4维 | `technical_fundamental_fusion` |
| 价值风险评估 | 4维 | `value_risk_assessment` |
| Freqtrade信号 | 4维 | `freqtrade_signals`（1h+4h） |
| 最终信号 | 5维 | `final_signal` |

---

### 9.2 collect_sample / train_ensemble / extract_ensemble_features

```python
def collect_sample(full_signal: dict, symbol: str, future_return: float) -> None
# 收集训练样本到 ml/models/ensemble/collected/samples_YYYY-MM-DD.jsonl

def train_ensemble(label_lookahead: int = 7, test_ratio: float = 0.2) -> dict
# 从 collected/ 样本训练模型，返回训练结果

def extract_ensemble_features(full_signal: dict) -> dict
# 从 full_signal 提取 46 维特征
```

---

### 9.3 reason_if_needed (llm_reasoning.py)

**LLM 辩证推理（按需触发）**

```python
def reason_if_needed(full_signal: dict, ensemble_pred: dict) -> dict
```

**返回值：**

```python
{
    "direction": "BULL",                       # "BULL"/"BEAR"/"NEUTRAL"
    "confidence": 65,                           # int: 0-100
    "source": "llm_reasoning",                  # "llm_reasoning"/"ensemble_direct"/"ensemble_fallback"
    "contradiction_analysis": "周线BULL与日线BEAR矛盾...",
    "reasoning": "辩证分析：...",
    "risk_note": "趋势矛盾，建议轻仓",
    "trust_weight": {"trend": 0.8, "bayes": 0.6, "classic": 0.5, "fundamental": 0.4},
    "contradictions": ["周线与日线方向不一致"],
    "trigger_reason": "uncertain_with_contradictions",
}
```

**触发规则：**

| 场景 | 是否触发 | trigger_reason |
|------|---------|---------------|
| 集成置信 ≥ 60 | 否 | `high_confidence` |
| 集成置信 < 40 | 是 | `low_confidence` |
| 置信 40-60 + 有矛盾 | 是 | `uncertain_with_contradictions` |
| 置信 40-60 + 无矛盾 | 否 | `uncertain_no_contradictions` |
| 模型未训练 | 否 | `ensemble_model_not_available` |

**矛盾检测维度（5类）：**
1. 趋势不一致（周线 vs 日线方向不同）
2. 贝叶斯方向与最终信号方向不一致
3. 经典指标趋势不一致
4. 技术面与基本面不一致
5. 逆转信号偏高（>50）

---

### 9.4 label_samples.py

```python
def label_collected_samples(lookahead_days: int = 7) -> dict
# 从 OKX 拉K线，计算未来收益，回填 _future_return 字段

def train_from_collected(lookahead_days: int = 7, test_ratio: float = 0.2) -> dict
# 先标注再训练，一条龙
```

---

## 10. CLI 命令

### 10.1 服务启动

```bash
# 启动信号池扫描器（守护进程）+ 执行器循环（每60秒）
bash start_services.sh
```

**内部启动的两个进程：**
1. 信号池扫描器：`python3 signal_pool/scanner.py --daemon --interval 300`（每5分钟扫描）
2. 交易执行器：`screen_executor.py run scheduled`（每60秒循环）

**停止服务：**
```bash
pkill -f 'scanner.py --daemon'
pkill -f 'screen_executor.py.*run.*scheduled'
```

---

### 10.2 信号池扫描器

```bash
# 单次扫描
python3 signal_pool/scanner.py --once

# 守护模式（默认每5分钟）
python3 signal_pool/scanner.py --daemon

# 自定义间隔（秒）
python3 signal_pool/scanner.py --daemon --interval 300
```

---

### 10.3 回测

```bash
# 运行回测演示（合成数据 + 真实数据 + 样本内外分割）
python3 backtest/run_backtest.py
```

---

### 10.4 集成推理训练

```bash
# 查看样本统计
python3 ml/label_samples.py --list

# 标注样本（未来7日收益）
python3 ml/label_samples.py --lookahead 7

# 标注并训练
python3 ml/label_samples.py --train --lookahead 7
```

---

### 10.5 V4+波浪实盘执行器

```bash
# 启动实盘执行器（每60秒轮询）
python3 live/v4_wave_trader.py
```

---

### 10.6 测试

```bash
cd 12-三屏趋势系统
python3 tests/test_core.py
# 或
python -m pytest tests/ -v
```

**测试用例清单：**

| 测试函数 | 覆盖模块 | 测试点 |
|---------|---------|--------|
| `test_confidence_to_position()` | engine.py | 5档仓位映射正确性 |
| `test_five_algo_decision()` | engine.py | 五大算法决策：OPEN/TRIAL/WAIT |
| `test_trend_consistency()` | core/trend_consistency.py | 趋势一致性：一致/不一致场景 |
| `test_bayesian_confidence()` | core/dynamic_weights.py | 贝叶斯置信度计算 |
| `test_fusion()` | core/fusion.py | 技术面+基本面撮合：一致/中性/矛盾 |
| `test_full_signal()` | engine.py | 完整信号计算 + Freqtrade信号校准 |
| `test_fundamental_data()` | data/fundamental_data.py | A系列研报读取 + 周报/A1日报解析 + 合并 |

---

## 11. 错误码

### 11.1 HTTP 错误（classic_bridge.py）

| 错误码 | 说明 | 处理建议 |
|--------|------|---------|
| `requests_not_installed` | requests 库未安装 | `pip install requests` |
| `http_4xx` | 客户端错误（如参数错误） | 检查请求参数 |
| `http_5xx` | 服务端错误 | 检查经典系统日志 |
| `request_error:timeout` | 请求超时 | 检查经典系统可用性 / 增大 timeout |
| `request_error:ConnectionError` | 连接失败 | 检查 `CLASSIC_SYSTEM_BASE_URL` |
| `unsupported_method:{method}` | 不支持的 HTTP 方法 | 仅支持 GET / POST |

### 11.2 业务错误（engine.py）

| 错误场景 | 返回值 | 处理建议 |
|---------|--------|---------|
| K线获取失败 | `{"error": "无法获取{spot_inst} K线数据"}` | 检查 OKX API / 网络 |
| 日线数据不足 | `{"error": "日线数据不足"}` | 至少 31 根日线 |
| 风向标未启用 | 默认双向开放 | 设置 `BTC_WIND_VANE_ENABLED=True` |
| V4 主策略异常 | `v4_strategy_info.enabled=False` 回退到三屏决策 | 检查 `halving_top_exit_strategy.py` |
| 波浪策略异常 | `wave_strategy.enabled=False` 保持 V4 原始仓位 | 检查 `ewave_strategy_adapter.py` |
| 物理置信度异常 | `physics_adjustment.enabled=False` 保持原始仓位 | 检查 `pitd_confidence_scorer.py` |
| 离场系统不可用 | `priority="unavailable"`，action="hold" | 检查经典系统 / 切换直接导入模式 |

### 11.3 风向标拦截状态

| 字段组合 | 含义 | 决策影响 |
|---------|------|---------|
| `hard_block=True` | 硬拦截（站上MA200或有效跌破MA128） | 严格禁止反向信号 → WAIT |
| `soft_block=True` | 软拦截（动态强逆转 ≥50%） | 允许 trial 5% 反向轻仓试探 |
| `wind_vane_blocked=True` | 已被风向标硬拦截 | action=WAIT |
| `wind_vane_soft_blocked=True` | 已被风向标软拦截 | 允许 trial 仓位反向入场 |

---

## 12. 版本管理

### 12.1 版本策略

- **当前版本**：v4.0.0（Phase 6 双线策略架构）
- **版本号规范**：`vMAJOR.MINOR.PATCH`
  - MAJOR：策略架构变更（如 v4 → v5）
  - MINOR：功能迭代（如双线架构、集成推理层）
  - PATCH：bug 修复 / 参数微调
- **`__init__.py` 的 `__version__`**：`"1.4.0"`（Python 包版本，与策略版本独立）
- **文档版本同步**：每次代码变更需同步更新 `TECHNICAL_DESIGN.md` 和 `ENGINEERING_INDEX.md`

### 12.2 双线版本管理

| 策略线 | 当前基线 | 9年回测年化 | 状态 |
|--------|---------|-----------|------|
| 主策略线 [MAIN] | V4+波浪互斥融合 | 56.43% | ✅ 实盘部署 |
| 机器学习基线 [ML_BASELINE] | V5.5 LightGBM | 4.31% | 🔬 实验状态 |

**晋升与回退规则详见 [STRATEGY_LINES.md](STRATEGY_LINES.md)。**

### 12.3 接口兼容性

- **公开 API（§3）**：保持向后兼容，参数新增使用默认值
- **私有 API（`_` 前缀）**：可能随版本变更
- **返回值字段**：仅追加新字段，不删除已有字段
- **HTTP 路由**：本系统作为客户端，路由变更由 10-经典指标系统负责

### 12.4 相关文档

| 文档 | 说明 |
|------|------|
| [TECHNICAL_DESIGN.md](TECHNICAL_DESIGN.md) | 技术设计文档（完整版） |
| [ENGINEERING_INDEX.md](../ENGINEERING_INDEX.md) | 工程索引 |
| [STRATEGY_LINES.md](STRATEGY_LINES.md) | 策略线管理总纲 |
| [CHANGELOG.md](CHANGELOG.md) | 变更日志 |
| [PITD_PHYSICS_ALGORITHM_DESIGN.md](PITD_PHYSICS_ALGORITHM_DESIGN.md) | PITD 物理算法设计 |

---

_最后更新：2026-07-25 | 来源：12-三屏趋势系统（v4.0.0 双线策略架构）_
