# 事件驱动策略系统 — API 规格

> **版本**：v1.0 | **更新日期**：2026-10-04

## 1. EventDrivenStrategy

### 1.1 evaluate(kline_data) -> EventSignal

**输入**：`kline_data: dict[str, Any]`

**返回**：`EventSignal`

**核心逻辑**：
1. 从 `kline_data["event_context"]` 读取事件上下文
2. 计算 5 维评分（surprise / priced_in / real_rate / resilience / cross_asset）
3. 加权平均得到 composite score
4. 阶段动态阈值判断方向（long/short/neutral）
5. 计算弹性系数（事件方向 × 趋势方向）

**FAIL-OPEN**：数据缺失时返回 `neutral_event_signal()`。

---

## 2. EventDrivenTrader

### 2.1 __init__(strategy, config=None)

| 参数 | 类型 | 说明 |
|------|------|------|
| strategy | EventDrivenStrategy | 策略实例 |
| config | dict \| None | 配置（base_position 等） |

### 2.2 on_kline_close(kline_data) -> EventSignal

**主入口**：每 K 线调用。返回 EventSignal 并执行交易决策。

**流程**：
1. `strategy.evaluate(kline_data)` 获取信号
2. 写入 shadow
3. 离场检查优先（若有持仓）
4. 开仓检查（若无持仓）

### 2.3 _should_open(signal) -> bool

开仓条件：
- `signal.signal != "neutral"`
- 无持仓
- strength ≥ 阶段阈值
- confidence ≥ 0.5

### 2.4 _compute_position_size(signal) -> float

```
仓位 = base × strength × phase_mult × (1 + elasticity × 0.3)
```

base 默认 250 USDT。

### 2.5 _compute_sl_tp(signal, kline_data) -> tuple[float, float]

- SL = max(0.04, min(0.15, 5.0 × ATR / close))
- TP = min(0.30, SL × 3.0)
- FAIL-OPEN：ATR=0 时返回 (0.04, 0.12)

### 2.6 _should_exit(signal, kline_data) -> bool

离场条件（满足任一）：
- 脉冲衰减：`days_since > 3 × τ`
- 信号反转：`signal.signal != 持仓方向`
- SL/TP（由执行层处理）

---

## 3. EventSignal (frozen dataclass)

| 字段 | 类型 | 说明 |
|------|------|------|
| signal | str | "long" / "short" / "neutral" |
| confidence | float | [0, 1] 置信度 |
| strength | float | [0, 1] 信号强度 |
| elasticity | float | [-1, 1] 弹性系数 |
| event_type | str | "fomc" / "nfp" / "cpi" / "ppi" / "none" |
| event_phase | str | 事件阶段 |
| scores | dict | 5 维评分明细 |
| reason | str | 决策理由 |
| composite | float | 综合得分 |

**方法**：
- `to_dict() -> dict`
- `from_dict(d: dict) -> EventSignal`（classmethod）

---

## 4. compute_impulse(event_type, days_since, strength) -> float

单点脉冲指数衰减函数：

```
impulse = strength × exp(-days_since / τ)
```

τ 来自 `EVENT_HALF_LIFE`。FAIL-OPEN：τ≤0 或 days_since<0 返回 0.0。

---

## 5. ConvictionScorer

### 5.1 score(kline_data, macro_signal) -> ConvictionResult

6 因子加权置信度评分。

**ConvictionResult 字段**：
| 字段 | 类型 | 说明 |
|------|------|------|
| conviction | float | [0, 1] |
| factors | dict[str, float] | 各因子得分 |
| filter_level | str | "hard" / "soft" / "none" |
| direction | str | "long" / "short" / "neutral" |
| position_params | dict \| None | 仓位映射参数 |

---

## 6. EventDominanceController

### 6.1 is_enabled() -> bool (classmethod)

双层门控检查：`enable_contradiction_driven_layer` && `enable_event_dominance`。
FAIL-OPEN：异常返回 False。

### 6.2 evaluate(conviction, macro_direction) -> DominanceDecision

| conviction | filter_level | modifier |
|-----------|-------------|----------|
| ≥ 0.85 | hard | 覆盖子系统 |
| 0.70-0.85 | soft | ±0.10-0.15 加权 |
| < 0.70 | none | 不过滤 |

### 6.3 安全机制

- `record_loss()`：连续 3 笔亏损降档
- `check_drift(current_conviction)`：1h 漂移 >0.15 降档
- `reset_downgrade()`：人工重置

---

## 7. EventCaseLibrary

### 7.1 load() / save()

案例库持久化（JSON）。

### 7.2 add_case(case: EventCase)

新增案例。

### 7.3 get_pattern_winrate(cycle_phase, decision) -> dict

按阶段+决策检索案例胜率统计。

### 7.4 EventCase 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| event_date | str | ISO8601 |
| cycle_phase | str | 事件阶段 |
| decision | str | hike/cut/hold |
| hike_prob_before | float | 事件前加息概率 |
| market_reaction | dict | 各资产反应 |
| relief_or_reversal | str | "relief"/"reversal"/"" |
| pnl_30d | float \| None | 事件后 30 天盈亏 |
