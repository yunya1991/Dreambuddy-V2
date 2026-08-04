# 技术设计文档 — V4 减半周期 + 艾略特波浪互斥融合趋势策略

> **版本**: v1.0 | **更新日期**: 2026-07-31
> **定位**: 子系统技术架构设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2
> **关联文档**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) · [API_SPEC.md](./API_SPEC.md) · [CHANGELOG.md](./CHANGELOG.md) · [README.md](../README.md)

---

## 目录

- [1. 概述](#1-概述)
- [2. 架构设计](#2-架构设计)
- [3. 核心算法](#3-核心算法)
- [4. 数据流](#4-数据流)
- [5. 接口设计](#5-接口设计)
- [6. 状态管理](#6-状态管理)
- [7. 配置管理](#7-配置管理)
- [8. 错误处理](#8-错误处理)
- [9. 扩展性设计](#9-扩展性设计)
- [变更记录](#变更记录)

---

## 1. 概述

### 1.1 系统定位

17-v4-wave-strategy 是 DreamBuddy-V2 中**完全独立于三屏趋势系统**的 V4+波浪融合趋势策略子系统。它通过 **V4 减半周期逃顶策略** 定方向、**艾略特波浪识别器** 择时加仓，并以 **互斥融合规则** 输出与三屏系统兼容的 `final_signal` 结构。

### 1.2 设计目标

- **方向 + 择时解耦**：V4 解决"多/空/空仓"的方向问题，波浪解决"何时加仓"的择时问题，互斥融合统一输出
- **减半周期顶部逃顶**：基于比特币 4 次减半历史（2012/2016/2020/2024），在减半后 12-18 个月窗口逐步减仓
- **物理增强可选**：弱趋势（η < 0.10）时通过动能力度仓位 + 宽追踪止损 + 动能止盈动态调节
- **回测可复现**：9 年 BTC 数据多策略对比，含交易成本与样本外验证
- **实盘可执行**：60 秒轮询，Aster 执行器集成，含动态 SL/TP 与移动止盈

### 1.3 业务边界

| 职责 | 归属 |
|------|------|
| V4 减半周期方向决策 | 本模块（`halving_top_exit_strategy.py`） |
| 艾略特波浪识别 | 本模块（`ewave_recognizer.py`） |
| 互斥融合规则 | 本模块（`ewave_strategy_adapter.py`） |
| 信号编排与 final_signal 组装 | 本模块（`v4_wave_engine.py`） |
| 回测验证 | 本模块（`backtest_v4_wave.py`） |
| 实盘交易执行 | 本模块（`live/v4_wave_trader.py`） |
| 物理特征计算（η、phys_conf、kinetic_score） | 上游 `12-三屏趋势系统/ml/` |
| 交易所下单（市价/止损/止盈） | 上游 `12-三屏趋势系统/live/aster_executor.py` |
| K 线数据源 | OKX API + 本地缓存 |

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     入口层（Entry）                          │
│  compute_v4_wave_signal()  │  V4WaveTrader.run_forever()    │
│  v4_wave_engine.py         │  live/v4_wave_trader.py        │
└──────────────┬─────────────┴────────────────────────────────┘
               ↓
┌─────────────────────────────────────────────────────────────┐
│                   核心层（Core Strategy）                    │
│  V4WaveEngine.compute_from_dataframes()                     │
│  ├─ HalvingTopExitStrategy.generate_signals()  (V4 定方向)  │
│  ├─ _compute_value_risk()                       (风险约束)  │
│  ├─ PhysicsEnhancer.compute_features()          (物理调节)  │
│  └─ EWaveStrategyAdapter.evaluate()             (互斥融合)  │
│      ├─ ElliottWaveRecognizer.identify_waves()              │
│      └─ _fuse_positions()                                   │
└──────────────┬──────────────────────────────────────────────┘
               ↓
┌─────────────────────────────────────────────────────────────┐
│                    工具层（Utility）                         │
│  data/market_data.py (K线获取/重采样/DataFrame)             │
│  backtest_v4_wave.py (回测引擎+指标计算)                    │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 模块关系

```
                ┌──────────────────────┐
                │  OKX API / 本地JSON  │
                └──────────┬───────────┘
                           ↓
                ┌──────────────────────┐
                │  data/market_data.py │
                │  fetch_candles()     │
                └──────────┬───────────┘
                           ↓
         ┌─────────────────────────────────────────┐
         │      v4_wave_engine.py (核心编排)        │
         │      V4WaveEngine.compute_from_dataframes│
         └─┬───────────┬──────────────┬───────────┘
           ↓           ↓              ↓
  ┌────────────────┐ ┌────────────────────┐ ┌──────────────────────┐
  │ halving_top_   │ │ 12-三屏/ml/        │ │ ewave_strategy_      │
  │ exit_strategy  │ │ physics_enhancer   │ │ adapter.py           │
  │ .py (V4)       │ │ (物理特征)          │ │  ├─ ewave_recognizer │
  │ → 多空空仓     │ │ → η/phys_conf/ks   │ │  │   .py (波浪识别)   │
  └────────────────┘ └────────────────────┘ │  └─ _fuse_positions  │
                                          │     (互斥融合)        │
                                          └──────────┬───────────┘
                                                     ↓
                                          ┌──────────────────────┐
                                          │ final_signal (统一)  │
                                          └──────────┬───────────┘
                                                     ↓
                                    ┌────────────────────────────┐
                                    │ live/v4_wave_trader.py     │
                                    │ AsterExecutor 下单         │
                                    └────────────────────────────┘
```

### 2.3 设计原则

- **互斥优先**：V4 与波浪方向冲突时，V4 拥有方向决定权，波浪仅在同向时叠加、反向时减半
- **物理可选**：物理引擎通过 `enable_physics` 开关，导入失败自动降级，不阻塞主流程
- **回测-实盘一致**：`backtest_v4_wave.compute_v4_wave_fusion` 规则与 `EWaveStrategyAdapter._fuse_positions` 完全对齐
- **final_signal 兼容**：输出结构与三屏系统 `compute_full_trading_signal` 兼容，便于复用下游执行器

---

## 3. 核心算法

### 3.1 V4 减半周期逃顶策略

**核心思路**：MA200 趋势过滤 + 减半周期顶部预警 + MA128 破位分批减仓 + 周线 MA200 抄底。

#### 3.1.1 减半周期相位判定

比特币减半历史时间点：

```python
BTC_HALVING_DATES = [
    pd.Timestamp("2012-11-28"),  # 第1次减半
    pd.Timestamp("2016-07-09"),  # 第2次减半
    pd.Timestamp("2020-05-11"),  # 第3次减半
    pd.Timestamp("2024-04-20"),  # 第4次减半
]
```

**相位判定公式**：

```
months_after = (current_date.year - last_halving.year) * 12
             + (current_date.month - last_halving.month)

if months_after < 12:        phase = "normal"
elif months_after < 15:      phase = "warn"     # 预警期
elif months_after < 18:      phase = "danger"   # 高危期
elif months_after < 24:      phase = "peak"     # 顶部期
else:                        phase = "normal"
```

**仓位约束**：

```
target_pos = base_long × halving_min_position[phase]

# halving_min_position 默认值
warn:    0.7   # 减仓 30%
danger:  0.3   # 减仓 70%
peak:    0.0   # 清仓
```

#### 3.1.2 越高越卖（high_to_sell）

```
若 current_price > ath_price:
    gain_pct = (current_price - ath_price) / ath_price × 100
    steps = int(gain_pct / high_to_sell_step_pct)      # 默认 5%
    sell_ratio = min(steps × 0.15, 0.8)                # 每步卖 15%，上限 80%
    target_pos = base_long × (1 - sell_ratio)
```

#### 3.1.3 MA128 破位分批减仓

```
below_pct = (ma128 - current_price) / ma128 × 100
levels_filled = min(int(below_pct / 5.0), 4)           # 每 5% 一级，最多 4 级
sell_ratio = levels_filled / 4
target_pos = current_long_pos × (1 - sell_ratio)
```

#### 3.1.4 周线 MA200 抄底

```
weekly_below_pct = (weekly_ma200 - close) / weekly_ma200 × 100
levels_filled = min(int(weekly_below_pct / 3.0), 6)    # 每 3% 一级，最多 6 级
dip_buy_pos = dip_buy_initial_pct × max_position       # 首级
            + (levels_filled - 1) × add_per_level      # 后续级别
```

### 3.2 艾略特波浪识别

#### 3.2.1 ZigZag 转折点识别

```
初始化 trend=0，遍历 highs/lows：
    up_move   = (highs[i] - last_extreme) / last_extreme
    down_move = (last_extreme - lows[i]) / last_extreme

    若 up_move ≥ zigzag_threshold(0.05)：趋势转 1（上升），记录 LOW 点
    若 down_move ≥ zigzag_threshold(0.05)：趋势转 -1（下降），记录 HIGH 点

后续遍历中，反向回撤 ≥ threshold 时记录转折点并切换趋势。
```

#### 3.2.2 分形确认

```
对每个转折点 p（窗口 w=5）：
    若 p 为 HIGH：检查 [i-w, i+w] 范围内是否所有 highs[j] < highs[i]
    若 p 为 LOW ：检查 [i-w, i+w] 范围内是否所有 lows[j]  > lows[i]
未通过分形确认的点被过滤；若过滤后点数过少，回退到原始点集。
```

#### 3.2.3 艾略特三大硬规则

```
规则 1（浪 2 不完全回撤浪 1）：
    wave2_retrace < wave1_height × wave2_retrace_max(1.0)

规则 2（浪 3 不最短）：
    wave3_height ≥ wave1_height × wave3_min_ratio(0.382)
    且 wave3_height ≥ max(wave1_height, wave5_height)  # 最长判定

规则 3（浪 4 不与浪 1 重叠）：
    多头：wave4_low > wave1_high × (1 - wave4_overlap_max)
    空头：wave4_low < wave1_high × (1 + wave4_overlap_max)
```

#### 3.2.4 实时浪位判定（`_classify_realtime_wave`）

伪代码：

```python
def classify_realtime_wave(points, current_price, is_bull):
    # 取最近 6 个转折点匹配 5 浪模式
    bull_pattern = ['LOW','HIGH','LOW','HIGH','LOW','HIGH']
    bear_pattern = ['HIGH','LOW','HIGH','LOW','HIGH','LOW']

    # 在 points 末尾滑动查找 6 点模式匹配
    for offset in reversed(range(len(actual) - 5)):
        if actual[offset:offset+6] == target_pattern:
            p0..p5 = recent[offset:offset+6]
            # 计算各浪高度
            wave1_height = p1.price - p0.price  # 多头
            wave2_retrace = p1.price - p2.price
            wave3_height = p3.price - p2.price
            wave4_retrace = p3.price - p4.price
            wave5_height = p5.price - p4.price

            # 检查规则 1、规则 3
            rule1_ok = wave2_retrace < wave1_height × 1.0
            rule3_ok = p4.price > p1.price × (1 - 0.0)

            # 判定当前位置
            if current_price < p5.price and last_high.idx >= p5.idx:
                # 浪 5 已结束，进入调整
                return ('IMPULSE_5', 5, conf)
            if current_price > p4.price and last_high.idx < p5.idx + 5:
                # 浪 5 进行中
                return ('IMPULSE_5', 5, 0.6)
            return ('IMPULSE_5', 5, 0.5)
    return classify_partial_wave(points, current_price, is_bull)
```

#### 3.2.5 信号生成

```
基于 (label, current_wave, confidence, is_bull) 生成信号：

is_bull 且 current_wave=2, conf≥0.5 → ENTER_LONG_W3   (浪2结束入场做多，最强)
is_bull 且 current_wave=4, conf≥0.5 → ENTER_LONG_W5   (浪4结束入场做多，次强)
is_bull 且 current_wave=5, conf≥0.6 → EXIT_LONG_W5    (浪5结束离场)
is_bull 且 current_wave=3            → HOLD_LONG_W3    (浪3持有)

空头对称：ENTER_SHORT_W3 / ENTER_SHORT_W5 / EXIT_SHORT_W5 / HOLD_SHORT_W3
其他                                   → WAIT
```

### 3.3 互斥融合规则

**核心规则矩阵**（`EWaveStrategyAdapter._fuse_positions`）：

```
输入：v4_action, v4_direction, v4_position_pct, wave_signal, wave_direction, wave_position_pct

参数：cap=1.0, wave_weight=0.6, confirm_threshold=0.6, bottom_cap=0.5

estimated_wave_conf = min(wave_pos / base_position, 1.0)
wave_confirmed = estimated_wave_conf ≥ confirm_threshold

# 规则 1：V4 多头
if v4_action == ENTER_LONG:
    if wave_dir == LONG and wave_confirmed:
        add = wave_weight × max(estimated_wave_conf, 0.5)
        total = min(v4_pos + add, cap)
        return total, ENTER_LONG, BULL, "v4_long_wave_add"
    else:
        return v4_pos, ENTER_LONG, BULL, "v4_long_keep"

# 规则 2：V4 空仓
if v4_action == WAIT:
    if wave_dir == LONG and wave_confirmed:
        bottom = min(wave_weight × max(estimated_wave_conf, 0.5), bottom_cap)
        return bottom, ENTER_LONG, BULL, "v4_wait_wave_bottom"
    elif keep_v4_dip_buy and v4_pos > 0.001:
        return v4_pos, ENTER_LONG, BULL, "v4_wait_keep_dip_buy"
    else:
        return 0.0, WAIT, NEUTRAL, "v4_wait_wave_wait"

# 规则 3：V4 空头
if v4_action == ENTER_SHORT:
    if wave_dir == LONG and wave_confirmed:
        return v4_pos × 0.5, ENTER_SHORT, BEAR, "v4_short_wave_reduce"
    else:
        return v4_pos, ENTER_SHORT, BEAR, "v4_short_keep"
```

**互斥性体现**：

- V4 多头 + 波浪中性/看空 → 保持 V4 仓位（不反向）
- V4 空头 + 波浪看多 → V4 空头减半（不完全反向，仅减仓）
- V4 空仓 + 波浪看多 → 轻仓抄底（上限 50%）

### 3.4 物理增强算法

#### 3.4.1 动能力度仓位

```
if enable_dynamic_sizing and sizing_mode == "kinetic":
    kinetic_factor = 0.5 + 1.5 × kinetic_score
    base_pos = base_pos × kinetic_factor

multiplier = 0.6 + 1.0 × phys_conf
base_pos = base_pos × multiplier
```

#### 3.4.2 弱趋势仓位调节

```
if eta < eta_weak(0.10):
    phys_multiplier = position_lower(0.6) + position_scale(1.0) × phys_conf
    adjusted_position = base_position × phys_multiplier
```

#### 3.4.3 追踪止损与动能止盈

```
# 追踪止损（trailing_mode=combo）
trail_pct ∈ [trail_min=0.06, trail_max=0.15]
基于 jerk 反转信号动态选择

# 动能止盈（take_profit_mode=kinetic）
tp_pct ∈ [tp_min=0.13, tp_max=0.50]
基于 kinetic_score 动态选择
```

### 3.5 价值风险评估

```
ath_drawdown_pct = (ath - current_price) / ath × 100
ma200_distance_pct = (current_price - ma200) / ma200 × 100

# 多头风险评估
if ath_drawdown_pct < 10 and ma200_distance_pct > 50:
    risk_level = "high";   adjusted = position × 0.7   # 接近 ATH 极端高位
elif ath_drawdown_pct < 20 and ma200_distance_pct > 30:
    risk_level = "medium"; adjusted = position × 0.85  # 接近 ATH 中等高位

# 空头风险评估
if ath_drawdown_pct > 70:
    risk_level = "high";   adjusted = position × 0.7   # 深熊做空风险
elif ath_drawdown_pct > 50:
    risk_level = "medium"; adjusted = position × 0.85  # 中度熊市做空风险
```

---

## 4. 数据流

### 4.1 主数据流（信号生成）

```
[OKX API]
    ↓ fetch_candles(spot_inst, "1D", 300)
[K 线列表 List[Dict]]  {ts, o, h, l, c, vol}
    ↓ candles_to_dataframe()
[pd.DataFrame]  索引=DatetimeIndex, 列=open/high/low/close/volume
    ↓ V4WaveEngine.compute_from_dataframes(daily_df, symbol, is_btc)
    ├─ HalvingTopExitStrategy.generate_signals(daily_df)
    │  → pd.Series[position]  (正=多头, 负=空头, 0=空仓)
    │  → v4_position_pct, v4_action, v4_direction
    ├─ _compute_value_risk(daily_df, base_position, base_direction)
    │  → {risk_level, adjusted_position, ath_drawdown_pct, ma200_distance_pct}
    ├─ PhysicsEnhancer.compute_features(daily_df) [可选]
    │  → {eta, phys_conf, kinetic_score}
    │  → adjusted_position (弱趋势调节)
    └─ EWaveStrategyAdapter.evaluate(daily_df, v4_action, v4_direction, v4_pos)
       ├─ ElliottWaveRecognizer.identify_waves(daily_df)
       │  → WaveStructure{waves, wave_label, current_wave, signal, confidence}
       ├─ _compute_wave_position(daily_df, wave_struct, v4_action, v4_direction)
       │  → wave_position_pct (含物理增强)
       └─ _fuse_positions(...)
          → (total_position_pct, final_action, final_direction, fusion_rule)
    ↓
[final_signal Dict]
{
    "symbol", "price", "generated_at", "timeframes",
    "value_risk_assessment",
    "final_signal": {
        "direction", "confidence", "action",
        "position": {position_pct, tier, original_position_pct},
        "decision_reason", "leverage", "margin_mode",
        "max_position_pct", "max_addon_position_pct",
        "v4_strategy": {enabled, v4_action, v4_direction, v4_position_pct, stats},
        "physics_adjustment": {enabled, eta, phys_conf, kinetic_score, adjusted_position},
        "wave_strategy": {wave_signal, wave_label, current_wave, wave_confidence,
                          wave_direction, wave_position_pct, total_position_pct,
                          final_action, final_direction, fusion_rule},
        "value_risk_assessment"
    }
}
```

### 4.2 回测数据流

```
[data/BTC_1D_9year.json]
    ↓ load_coin_data("BTC")
[pd.DataFrame OHLCV]
    ↓ compute_v4_positions(prices)              → v4_positions: np.array
    ↓ generate_wave_signals(prices, 0.05)       → wave_signals, wave_confs: np.array
    ↓ compute_v4_wave_fusion(prices, v4_pos, wave_sig, wave_conf, ...)
[ fused_positions: np.array ]
    ↓ calc_metrics(prices, fused_positions, valid_start=730, cost_pct=0.001)
[ metrics Dict ]
    ↓ json.dump
[ backtest_results/v4_wave_9year_btc.json ]
```

### 4.3 实盘数据流

```
[60s 轮询触发]
    ↓ V4WaveTrader.run_once()
    ├─ get_positions()  → 当前持仓 {coin: pos_data}
    ├─ _check_sltp(positions)  → 检查止损/止盈/移动止盈触发
    ├─ for symbol in TREND_SYMBOLS:
    │    compute_v4_wave_signal(f"{symbol}-USDT", is_btc=(symbol=="BTC"))
    │    → full_signal
    │    ↓ _compute_sltp(full_signal, current_price)
    │    → {stop_loss_pct, take_profit_pct, trailing_enabled, sltp_mode}
    │    ↓ action 分发
    │    ├─ ENTER_LONG/SHORT → _handle_entry()  → AsterExecutor.place_market_order()
    │    ├─ EXIT_LONG/SHORT  → _handle_exit()   → AsterExecutor.close_position()
    │    └─ WAIT              → 继续持有
    └─ _dynamic_adjust_sltp(positions, full_signal_map)
       → 风险升高时收紧 SL/TP；趋势增强时放松 SL/TP
       → _sync_sltp_orders()  → AsterExecutor.cancel_order() + place_stop_loss_order() + place_take_profit_order()
```

### 4.4 数据结构

| 结构 | 字段 | 说明 |
|------|------|------|
| `WavePoint` | `idx, price, point_type, timestamp` | 波浪转折点（HIGH/LOW） |
| `WaveStructure` | `waves, wave_label, current_wave, signal, confidence` | 识别出的波浪结构 |
| `WaveConfig` | 28 个字段 | 互斥融合+物理增强完整配置（dataclass） |
| `final_signal` | 见 §4.1 | 完整交易决策结构 |
| 持仓元数据 | `entry_px, side, qty, sl_pct, tp_pct, trailing_enabled, peak_px, ...` | 实盘 SL/TP 状态（`data/v4_position_sltp.json`） |

---

## 5. 接口设计

### 5.1 内部接口

| 函数 | 签名 | 说明 |
|------|------|------|
| `V4WaveEngine.compute_from_dataframes` | `(daily_df, symbol="BTC", is_btc=True) -> Dict` | 从 DataFrame 计算 final_signal |
| `HalvingTopExitStrategy.generate_signals` | `(prices: pd.DataFrame) -> pd.Series` | 生成仓位序列 |
| `ElliottWaveRecognizer.identify_waves` | `(prices: pd.DataFrame) -> WaveStructure` | 识别波浪结构 |
| `EWaveStrategyAdapter.evaluate` | `(daily_df, v4_action, v4_direction, v4_position_pct, symbol) -> Dict` | 评估波浪信号+互斥融合 |
| `EWaveStrategyAdapter._fuse_positions` | `(v4_action, v4_direction, v4_position_pct, wave_signal, wave_direction, wave_position_pct) -> tuple` | 互斥融合核心 |
| `_compute_value_risk` | `(daily_df, position_pct, direction) -> Dict` | 价值风险评估 |
| `_compute_sltp` | `(full_signal, current_price) -> Dict` | 实盘 SL/TP 计算 |

### 5.2 对外接口

详见 [API_SPEC.md](./API_SPEC.md)。

---

## 6. 状态管理

### 6.1 状态文件

| 文件 | 作用 | 格式 |
|------|------|------|
| `data/v4_position_sltp.json` | 实盘持仓 SL/TP 元数据（开仓价、方向、数量、SL/TP 百分比、移动止盈峰值价等） | JSON |
| `backtest_results/v4_wave_9year_btc.json` | 9 年回测产物 | JSON |
| `backtest_results/v4_wave_independent_btc.json` | 独立模块对比回测产物 | JSON |
| `logs/v4_wave_trader.log` | 实盘运行日志（运行时生成） | 文本 |

### 6.2 状态机

#### 6.2.1 V4 趋势状态机

```
init → bull → bull_exit → bear_short_l2 → bear_flat → sideways → dip_buy → dip_buy_end
                       ↑                                                              ↓
                       └──────────────────────────────────────────────────────────────┘
                                     （MA200 重新站上 + 斜率转正）
```

#### 6.2.2 减半周期相位状态机

```
normal → warn (减半后12月) → danger (15月) → peak (18月) → normal (24月后)
```

#### 6.2.3 实盘 SL/TP 调整状态机

```
开仓 → 监控 SL/TP → 风险升高? ─ 是 → 收紧 SL/TP (只收不松)
                  │
                  └ 否 → 趋势增强? ─ 是 → 放松 SL/TP (TP 上调/移动止盈开)
                       │
                       └ 否 → 保持

利润保护：
  pnl ≥ 5% → SL 锁成本价 (sl_pct=0)
  pnl ≥ 8% → SL 锁 3% 利润 (sl_pct=-0.03)
```

---

## 7. 配置管理

### 7.1 配置层级

| 层级 | 文件/来源 | 说明 |
|------|-----------|------|
| L1 | 环境变量（`TREND_SYMBOLS`, `AUTO_EXECUTE` 等） | 实盘运行时参数 |
| L2 | `17-v4-wave-strategy/.env` | 实盘环境变量文件 |
| L3 | `WaveConfig` dataclass 默认值 | 互斥融合+物理增强参数（代码内） |
| L4 | `HalvingTopExitStrategy.__init__` 默认参数 | V4 减半周期参数（代码内） |
| L5 | `ElliottWaveRecognizer.__init__` 默认参数 | 波浪识别参数（代码内） |

### 7.2 关键配置项

详见 [ENGINEERING_INDEX.md §5 配置参数索引](./ENGINEERING_INDEX.md)。

### 7.3 配置加载优先级

```
环境变量
    ↓ 覆盖
.env 文件
    ↓ 覆盖
WaveConfig / HalvingTopExitStrategy / ElliottWaveRecognizer 代码默认值
```

`WaveConfig` 当前不支持 .env 加载，参数调整需修改代码；后续可扩展 `config_loader`。

---

## 8. 错误处理

### 8.1 异常场景与处理策略

| 场景 | 处理策略 | 代码位置 |
|------|----------|----------|
| 日线数据不足（< 250 天） | 返回 WAIT/NEUTRAL 空信号 | `v4_wave_engine.py:173` |
| 物理引擎导入失败 | 降级为纯 V4+波浪融合，`physics_adjustment.enabled=False` | `ewave_strategy_adapter.py:136-167` |
| 物理特征计算异常 | `physics_error` 字段记录错误，继续主流程 | `v4_wave_engine.py:255-256` |
| 波浪识别异常 | `fusion_rule="wave_error_keep_v4"`，保持 V4 仓位 | `v4_wave_engine.py:286-294` |
| 波浪识别数据不足（< 90 天） | `enabled=False, fusion_rule="insufficient_data"` | `ewave_strategy_adapter.py:206-209` |
| OKX API 调用失败 | 回退到 CLI 方案，再失败返回空列表 | `data/market_data.py:62-95` |
| 实盘下单失败 | 日志记录错误，保留持仓元数据，下一轮重试 | `live/v4_wave_trader.py:599-600` |
| 持仓元数据加载失败 | 警告日志，初始化为空字典 | `live/v4_wave_trader.py:153-155` |
| 实盘 SL/TP 挂单失败 | 错误日志，保留程序端 SL/TP 监控 | `live/v4_wave_trader.py:516-517` |
| 回测中物理特征计算失败 | 回退到无物理增强模式（eta=1.0, phys_conf=0.5） | `backtest_v4_wave.py:288-293` |

### 8.2 降级机制

```
主流程（V4+波浪+物理） 
    ↓ 物理引擎不可用
降级 1：V4+波浪互斥融合（无物理增强）
    ↓ 波浪识别失败
降级 2：纯 V4 减半周期策略
    ↓ V4 数据不足
降级 3：WAIT/NEUTRAL 空信号
```

---

## 9. 扩展性设计

### 9.1 如何添加新币种

1. 准备该币种 9 年日线数据文件 `data/{SYMBOL}_1D_9year.json`（格式：`[{ts, o, h, l, c, vol}, ...]`）
2. 修改 `TREND_SYMBOLS` 环境变量添加币种
3. 若该币种非 BTC，调用时传 `is_btc=False`，系统自动启用 `alt_bear_no_trade` 模式（仅在 BTC 牛市时做多）
4. 可选：通过 `ml/market_cap_provider.get_confirm_threshold_by_symbol(symbol)` 提供该币种的动态置信度阈值

### 9.2 如何调整互斥融合参数

1. 修改 `ewave_strategy_adapter.py` 中 `WaveConfig` dataclass 默认值，或
2. 实例化时传入自定义 `WaveConfig`：`EWaveStrategyAdapter(WaveConfig(wave_weight=0.7))`
3. 通过 `backtest_v4_wave.py` 验证新参数的回测表现
4. 推荐使用 Optuna TPE 进行贝叶斯优化（历史最优参数：`wave_weight=0.6, confirm_threshold=0.6, bottom_position_cap=0.5`）

### 9.3 如何扩展新的波浪识别算法

1. 在 `ewave_recognizer.py` 中实现新的识别器类（保持 `identify_waves(prices) -> WaveStructure` 接口）
2. 在 `EWaveStrategyAdapter.__init__` 中替换 `self.recognizer` 实例
3. 若新算法需要额外参数，扩展 `WaveConfig` dataclass

### 9.4 如何切换物理增强模式

1. 修改 `WaveConfig`：
   - `enable_physics=False` 完全关闭物理增强
   - `sizing_mode="fixed"` 关闭动能力度仓位
   - `trailing_mode="jerk"` 切换追踪止损算法
   - `take_profit_mode="fixed"` 切换固定止盈
2. 物理引擎模块本身在 `12-三屏趋势系统/ml/`，扩展物理特征需修改上游模块

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-07-31 | 初始版本：完整技术设计文档建立，覆盖架构/算法/数据流/接口/状态/配置/错误处理/扩展性 9 大章节 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-31
