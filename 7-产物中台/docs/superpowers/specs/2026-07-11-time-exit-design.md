# 马丁策略超时触发经典离场系统 — 设计文档 v2

## 概述

在 V15 马丁策略中新增"最佳持仓时间"机制。当持仓超过贝叶斯优化出的最佳时间后，触发经典离场系统（ClassicExitSystem）进行智能评估，避免扛单亏损。

核心理念：
- **事出反常必有妖** — 长时间未止盈说明市场偏离入场假设
- **黑天鹅后反弹黄金窗口** — 加仓后的一段时期是反弹概率最高的黄金期，不应过早触发超时评估
- **强反弹应提高止盈** — 如果经典系统评估发现反弹力度强，不应只 HOLD，而应提高止盈目标

## 架构

```
马丁策略每轮轮询 (1H):
  ├─ 检查止盈 → 命中则平仓
  ├─ 检查MA200止损 → 命中则平仓
  ├─ 【新增】检查持仓时间（分层计时）:
  │     if 无加仓:
  │         计时基准 = open_time
  │         超时阈值 = max_base_holding_hours (如48h)
  │     else:
  │         计时基准 = last_addon_time (最后一次加仓时间)
  │         超时阈值 = max_post_addon_hours (如24h)
  │         └─ 黄金窗口期内(golden_window_hours, 如12h)不触发评估
  │
  │     if 超时:
  │         → 调用 ClassicExitSystem.evaluate_full()
  │         → CLOSE   → 平仓
  │         → REDUCE  → 减仓(reduce_frac比例)
  │         → RAISE_TP → 提高止盈价(new_tp_price)
  │         → HOLD    → 继续持有(下次轮询再评估)
  └─ 检查加仓条件
```

## 改动清单

### 1. classic_exit_system.py — ExitAction 增加 RAISE_TP

```python
class ExitAction(str, Enum):
    """离场动作"""
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"    # 新增：提高止盈价
```

ExitDecision 增加字段：
```python
@dataclass
class ExitDecision:
    ...
    new_tp_price: float = 0.0   # 新增：建议的新止盈价
    new_tp_pct: float = 0.0     # 新增：建议的新止盈百分比
```

TSTP 评估逻辑改进（`_check_tstp` 方法）：

```
现有逻辑:
  if pnl >= 衰减后tp目标:
    if hold_value 低 → CLOSE_WEAK (弱反弹, 趁有利润快走)
    if hold_value 高 → REDUCE (有一定价值, 减仓锁利)
  else:
    → HOLD

改进后:
  if pnl >= 衰减后tp目标:
    if hold_value 低 → CLOSE_WEAK (弱反弹, 趁有利润快走)
    if hold_value 高 → REDUCE (有一定价值, 减仓锁利)
  else:
    if hold_value 很高(>raise_tp_thr) → RAISE_TP (强反弹, 提高止盈目标)
    else → HOLD
```

新增配置项：
```python
# ExitConfig 新增
tstp_raise_tp_enabled: bool = True
tstp_raise_tp_value_thr: float = 0.65    # hold_value > 0.65 时触发 RAISE_TP
tstp_raise_tp_atr_mult: float = 4.0     # 新止盈 = ATR × 4.0 (高于默认的3.0)
```

L1/L2 评估也增加 RAISE_TP 路径：
- 当 hold_value > raise_tp_value_thr 且 hold_risk < 0.3 时 → RAISE_TP
- 表示"价值高 + 风险低 → 应该提高止盈目标让利润奔跑"

### 2. v15_trader.py — 新增分层超时 + RAISE_TP 处理

**改动点 2a：加仓时记录 `last_addon_time`**

```python
# execute_addon() 中加仓成功后 (L262-267)
if r.get("ok"):
    pos["addons"] = addons + 1
    pos["last_addon_time"] = datetime.now(timezone.utc).isoformat()  # 新增
    ...
```

**改动点 2b：新增 `check_time_exit()` 函数**

```python
def check_time_exit(client, coin, pos, state):
    """分层超时触发经典离场系统评估"""
    
    # 分层计时
    if pos.get("addons", 0) > 0 and pos.get("last_addon_time"):
        # 有加仓 → 从最后一次加仓开始计时
        base_time = datetime.fromisoformat(pos["last_addon_time"])
        max_hours = get_config_float("V15_MAX_POST_ADDON_HOURS", 24)
        golden_window = get_config_float("V15_GOLDEN_WINDOW_HOURS", 12)
        
        hold_hours = (datetime.now(timezone.utc) - base_time).total_seconds() / 3600
        
        # 黄金窗口内不触发（让黑天鹅反弹充分发展）
        if hold_hours < golden_window:
            return False
        
        # 黄金窗口后但未超时 → 也不触发
        if hold_hours < max_hours:
            return False
    else:
        # 无加仓 → 从开仓开始计时
        base_time = datetime.fromisoformat(pos["open_time"])
        max_hours = get_config_float("V15_MAX_BASE_HOLDING_HOURS", 48)
        
        hold_hours = (datetime.now(timezone.utc) - base_time).total_seconds() / 3600
        if hold_hours < max_hours:
            return False
    
    # 超时 → 调用经典离场系统
    from classic_exit_system import ClassicExitSystem, PositionState
    system = ClassicExitSystem()
    
    pos_state = PositionState(
        coin=coin,
        side="long",
        entry_price=pos["entry_price"],
        current_price=current_price,
        position_age_sec=hold_hours * 3600,
        unrealized_pnl_pct=(current_price - pos["entry_price"]) / pos["entry_price"],
        leverage=LEVERAGE,
    )
    
    decision = system.evaluate_full(pos_state, candles_1h=None, regime="trend")
    
    if decision.action == "close":
        # 执行平仓
        ...
    elif decision.action == "reduce":
        # 执行减仓(reduce_frac比例)
        ...
    elif decision.action == "raise_tp":
        # 提高止盈价
        new_tp_pct = decision.new_tp_pct
        pos["take_profit_pct"] = new_tp_pct
        _log(f"[{coin}] 超时{hold_hours:.1f}h, 经典系统评估: RAISE_TP "
             f"({decision.reason}) 新止盈={new_tp_pct:.2%}")
    else:
        _log(f"[{coin}] 超时{hold_hours:.1f}h, 经典系统评估: HOLD ({decision.reason})")
    
    return False
```

**改动点 2c：在 `run_poll_cycle()` 中插入调用**

```python
if coin in state["positions"]:
    pos = state["positions"][coin]
    if not check_take_profit(client, coin, pos, state):
        check_time_exit(client, coin, pos, state)  # 新增
        execute_addon(client, coin, pos, state)
```

### 3. v15_backtest.py — 回测主循环新增分层超时 + RAISE_TP

```python
# position 字典新增字段
position = {
    ...
    "entry_idx": i,
    "last_addon_idx": i,    # 新增：最后一次加仓的K线索引
}

# 加仓时更新
position["last_addon_idx"] = i

# 主循环新增时间止盈检查
if not hit_tp and not hit_sl:
    if position.get("addons", 0) > 0:
        # 有加仓：从最后加仓计时
        bars_since_addon = i - position["last_addon_idx"]
        hold_hours = bars_since_addon * 4
        golden_window_bars = golden_window_hours / 4
        max_bars = max_post_addon_hours / 4
        
        if hold_hours >= golden_window_hours and hold_hours >= max_post_addon_hours:
            # 触发经典离场评估
            decision = system.evaluate_full(pos_state, ...)
            if decision.action == "close":
                hit_time_exit = True
                exit_price = current_price
            elif decision.action == "raise_tp":
                position["tp_pct"] = decision.new_tp_pct  # 提高止盈目标
    else:
        # 无加仓：从开仓计时
        bars_held = i - position["entry_idx"]
        hold_hours = bars_held * 4
        if hold_hours >= max_base_holding_hours:
            decision = system.evaluate_full(pos_state, ...)
            ...
```

### 4. bayesian_optimizer.py — 参数空间新增3个时间参数

```python
self.params_space = {
    ...  # 现有6个参数
    'max_base_holding_hours': (24, 96),     # 底仓最大持仓时间
    'max_post_addon_hours': (12, 48),       # 加仓后最大持仓时间
    'golden_window_hours': (4, 24),         # 黑天鹅反弹黄金窗口
}
```

三轮迭代收敛：
- 第1轮：宽范围探索（24-96h / 12-48h / 4-24h）
- 第2轮：±30% 收敛
- 第3轮：±15% 精调

### 5. .env.v15ct — 新增配置项

```
V15_MAX_BASE_HOLDING_HOURS=48
V15_MAX_POST_ADDON_HOURS=24
V15_GOLDEN_WINDOW_HOURS=12
```

## 时间分层设计

```
时间线:
  开仓 ────────────────────────────────────> 平仓
  │                                         │
  │  底仓阶段（无加仓）                       │
  │  超时: max_base_holding_hours (48h)      │
  │                                         │
  │     ┌── 加仓#1                           │
  │     │  ↓                                 │
  │     │  黄金窗口 (golden_window_hours=12h) │
  │     │  ↓  不触发评估，让反弹发展            │
  │     │  ↓                                 │
  │     │  超时窗口 (max_post_addon_hours=24h)│
  │     │  ↓  触发经典离场评估                  │
  │     │                                   │
  │     ├── 加仓#2 (重置计时器)                │
  │     │  ↓                                 │
  │     │  黄金窗口 → 超时窗口 → 触发评估       │
  │     │                                   │
  │     └── 加仓#3 (重置计时器)                │
  │        ↓                                 │
  │        黄金窗口 → 超时窗口 → 触发评估       │
```

**设计原理**：
- 每次加仓重置计时器，因为加仓改变了成本基础和市场环境
- 黄金窗口期内不评估：黑天鹅后反弹最可能发生在这段时间，过早评估可能误判
- 黄金窗口后触发经典系统评估：如果反弹已结束但还没到止盈，需要专业判断
- 底仓（无加仓）的超时更长：因为还没有黑天鹅事件，只是普通持仓

## RAISE_TP 决策逻辑

```
经典离场系统评估:

  持仓超时 → evaluate_full(pos_state)
     │
     ├─ P0 L0 硬退出检查
     │   ├─ 最大亏损 → CLOSE
     │   ├─ 强平缓冲 → CLOSE
     │   └─ 周线反转 → CLOSE
     │
     ├─ P2 Triple Barrier
     │   ├─ 止损屏障 → CLOSE
     │   ├─ 止盈屏障 → CLOSE/REDUCE
     │   └─ 时间屏障 → CLOSE
     │
     ├─ P3 TSTP 时间止盈
     │   ├─ pnl >= 衰减后tp + hold_value低 → CLOSE_WEAK
     │   ├─ pnl >= 衰减后tp + hold_value高 → REDUCE
     │   ├─ pnl < 衰减后tp + hold_value很高 → RAISE_TP  ← 新增
     │   └─ pnl < 衰减后tp + hold_value低 → HOLD
     │
     └─ P1 L1/L2 价值-风险评估
         ├─ hold_risk高 → CLOSE/REDUCE
         ├─ hold_value高 + hold_risk低 → RAISE_TP  ← 新增
         └─ 其他 → HOLD
```

**RAISE_TP 的含义**：
- 黑天鹅后反弹力度强（hold_value > 0.65）
- 当前价格还没到止盈目标
- 但趋势/动能/量能都指向继续上涨
- → 应该提高止盈目标，让利润奔跑，而不是按原计划4%就出

**RAISE_TP 的止盈价计算**：
```python
# 新止盈 = 当前价 × (1 + ATR × raise_tp_atr_mult)
# raise_tp_atr_mult 默认 4.0（高于默认止盈的 3.0）
# 但不超过原始止盈的 2 倍（防止过度贪婪）
new_tp_pct = min(atr_pct * 4.0, original_tp_pct * 2.0)
```

## 数据流

```
实盘:
  pos["open_time"] (已有) + pos["last_addon_time"] (新增)
    → 分层计算 hold_hours
    → if 有加仓: 从 last_addon_time 计时, 先过 golden_window 再过 max_post_addon
    → if 无加仓: 从 open_time 计时, 过 max_base_holding
    → 超时后调用 ClassicExitSystem.evaluate_full()
    → CLOSE/REDUCE/RAISE_TP/HOLD

回测:
  position["entry_idx"] (已有) + position["last_addon_idx"] (新增)
    → 同上分层计算
    → 超时后调用 ClassicExitSystem
    → 同上四种动作

贝叶斯优化:
  3个新参数: max_base_holding_hours, max_post_addon_hours, golden_window_hours
  → 三轮迭代找到最优组合
  → 回测验证 + 诊断分析
```

## 降级策略

```python
try:
    from classic_exit_system import ClassicExitSystem, PositionState
    system = ClassicExitSystem()
    decision = system.evaluate_full(pos_state, ...)
except Exception:
    # 降级：超时直接平仓
    _log(f"[{coin}] 超时{hold_hours:.1f}h，经典系统不可用，执行保本平仓")
    execute_close(client, coin, pos, state)
```

## 贝叶斯优化的反馈循环

```
第1轮: 宽范围探索
  max_base_holding_hours ∈ [24, 96]
  max_post_addon_hours ∈ [12, 48]
  golden_window_hours ∈ [4, 24]
  → 回测验证 → 诊断分析

第2轮: ±30% 收敛
  → 回测验证 → 对比提升

第3轮: ±15% 精调
  → 最终确认最优组合

输出示例:
  底仓超时: 52h
  加仓后超时: 28h
  黄金窗口: 16h
  → 超时后触发经典离场评估
  → 强反弹时 RAISE_TP 让利润奔跑
  → 弱反弹时 CLOSE_WEAK 止损离场
```
