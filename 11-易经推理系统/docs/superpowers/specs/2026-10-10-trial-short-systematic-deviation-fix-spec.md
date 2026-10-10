# 空单试错仓系统性偏差修复 SPEC

> 版本：v0.2（评审后修订）
> 日期：2026-10-10
> 作者：AI Agent
> 状态：待实施
>
> 评审修订记录（v0.1→v0.2）：
> - Major-1 修复：`_compute_effective_leverage` 调用移到 BDSM 杠杆块之后（L15623 后），避免 BDSM 覆盖 trial 2x cap
> - Major-2 确认：F3 下限设 0.30（用户确认保留 F1 机制，仅拦截极端低值）
> - Minor-1 补充：F4 超时检查受 eval 周期约束，实际超时约 4-4.5h
> - Minor-2 补充：C5 的 trade_snapshot 增加 direction 字段（L9749 已有 `_dr` 变量）
> - Minor-3 补充：F1 动态调节复用 _gate_threshold_state 已有空单样本

---

## 1. 背景与问题

### 1.1 现象

ARB、COIN、CRCL 三币种空单连续亏损，排查确认全部来自 BCRM2.0 试错仓（`is_trial=True`）：

| 币种 | 入场价 | 杠杆 | 持仓时长 | 盈亏 | 退出原因 |
|------|--------|------|---------|------|---------|
| ARB  | -      | 5x   | 9.4h    | -9.76% | trial_trend_reverse |
| ARB(2)| -      | 5x   | -       | -6.03% | FORCE_CLOSE |
| COIN | 175.92 | 5x   | -       | 亏损   | - |
| CRCL | 82.38  | 5x   | -       | 亏损   | - |

### 1.2 偏差链路

```
BCRM2.0推理 → 方向=DOWN, 置信度0.84-0.96
  → P1做空趋势过滤: BTC TREND_BULL → 禁止做空 → BLOCK
  → F1永不BLOCK通路: P1=BLOCK + conf≥0.80 → 绕过BLOCK, 极小仓试错
  → 轻仓试错放行: conf(0.84-0.96) < eff_thr(0.98) → is_trial=True
  → 开仓 [轻仓试错] open_short 杠杆=5.0x
  → 逆势做空 → 持续亏损
```

### 1.3 四个根因

| # | 问题 | 代码位置 | 影响 |
|---|------|---------|------|
| F1 | 空单 f1_trial_threshold=0.80 过低，不区分多空 | L15168-15172 | 空单试错仓放行门槛过低，逆势空单轻易入场 |
| F2 | `_compute_effective_leverage` 未实现，试错仓杠杆 5x 无上限 | L15597-15602 | 试错仓杠杆与正常仓相同（5x），放大亏损 |
| F3 | 轻仓试错逻辑矛盾：score_cons=0.294<0.40 仍放行 | L15324-15363 | 共识分低于基础门槛仍开仓，逻辑矛盾 |
| F4 | 试错评估周期过长，无超时平仓 | L9877-9898, L14036-14093 | 持仓 9.4h 才判定 reverse，资金效率低 |

---

## 2. 修复方案

### 2.1 F1: 收紧空单 f1_trial_threshold（渐进式）

**现状**：

```python
# L15168-15172
_f1_trial_base_threshold = (
    float(self.short_confidence_threshold)   # 空单 = 0.80
    if direction == "DOWN"
    else float(self.confidence_threshold)     # 多单 = 0.70
)
```

空单 F1 试错门槛 = `short_confidence_threshold` = 0.80，低于多单 effective_threshold(0.91+)。

**问题**：0.80 太低，置信度 0.84-0.96 的逆势空单轻松通过 F1 通路。

**方案**：

1. 新增类常量 `F1_TRIAL_SHORT_BASE_THRESHOLD = 0.90`（空单 F1 试错门槛独立于 `short_confidence_threshold`）
2. 新增 `_f1_trial_short_state` 动态调节状态（复用 `_maybe_adjust_gate_base_threshold` 模式），基于空单历史盈亏收紧：
   - 最近 N≥30 笔空单胜率 < 40% → f1_trial_short_threshold +0.02（收紧）
   - 最近 N≥30 笔空单胜率 ≥ 60% → f1_trial_short_threshold -0.01（放宽）
   - 硬边界 [0.85, 0.98]
   - 冷却期 30min
3. 多单 F1 试错门槛不变（保持 0.70）

**改动点**：

| 文件 | 行号 | 改动 |
|------|------|------|
| polling_trader.py | L15168-15172 | `_f1_trial_base_threshold` 空单分支改为取 `self._f1_trial_short_threshold`（动态值） |
| polling_trader.py | __init__ 附近 L1416 | 新增 `self._f1_trial_short_threshold = 0.90` 和 `_f1_trial_short_state` dict |
| polling_trader.py | L9758 附近 | 平仓记录时额外调用 `_maybe_adjust_f1_trial_short_threshold(trade_snapshot)` |
| polling_trader.py | L16836 附近 | 新增 `_maybe_adjust_f1_trial_short_threshold` 方法（仿 `_maybe_adjust_gate_base_threshold`） |

**伪代码**：

```python
# 新增类常量
F1_TRIAL_SHORT_BASE_THRESHOLD: float = 0.90

# __init__ 中新增
self._f1_trial_short_threshold: float = self.F1_TRIAL_SHORT_BASE_THRESHOLD
self._f1_trial_short_state: dict = {
    "n_min": 30,
    "n_max": 150,
    "recent_pnl": [],       # [(pnl_pct, direction), ...] 仅空单
    "last_adjust_ts": 0.0,
    "adjust_cooldown_s": 1800,
}

# L15168 改为
_f1_trial_base_threshold = (
    float(self._f1_trial_short_threshold)    # 空单动态门槛
    if direction == "DOWN"
    else float(self.confidence_threshold)    # 多单不变
)

# 新增方法
def _maybe_adjust_f1_trial_short_threshold(self, trade_snapshot):
    """基于空单历史盈亏动态收紧 F1 试错门槛。"""
    # 仅记录空单
    if (trade_snapshot or {}).get("direction", "").upper() != "DOWN":
        # 需要在调用处补充 direction 字段
        ...
    # 逻辑同 _maybe_adjust_gate_base_threshold，步长 +0.02/-0.01，硬边界 [0.85, 0.98]
```

### 2.2 F2: 实现 `_compute_effective_leverage`（试错仓杠杆 ≤ 2x）

**现状**：

```python
# L15597-15602
leverage = self.okx_client.cfg.get("default_leverage", 3)       # = 5
leverage_factor = inference.get("leverage_factor", 1.0)
effective_leverage = max(1, round(leverage * leverage_factor))  # = 5，无 is_trial 检查
```

`_compute_effective_leverage` 方法在代码中**不存在**，但测试 `tests/test_loss_prevention_fixes.py` 已定义期望行为：

```python
def test_trial_leverage_capped_at_2x():
    lev = t._compute_effective_leverage(base_leverage=3, leverage_factor=2.0, is_trial=True)
    assert lev <= 2  # 试错仓杠杆应≤2x

def test_normal_position_no_cap():
    lev = t._compute_effective_leverage(base_leverage=3, leverage_factor=2.0, is_trial=False)
    assert lev == 6  # 非试错仓不受 2x 上限约束
```

**方案**：

1. 新增 `_compute_effective_leverage(base_leverage, leverage_factor, is_trial)` 方法
2. 当 `is_trial=True` 时，`effective_leverage = min(2, base_leverage * leverage_factor)`
3. 当 `is_trial=False` 时，`effective_leverage = base_leverage * leverage_factor`（无上限）
4. **★ 评审 Major-1 修复**：在 BDSM 杠杆块（L15623）**之后**调用 `_compute_effective_leverage`，而非替换 L15602

**代码顺序（评审后确认）**：

```python
# L15597-15602: 原始杠杆计算（保持不变）
leverage = self.okx_client.cfg.get("default_leverage", 3)
leverage_factor = inference.get("leverage_factor", 1.0)
effective_leverage = max(1, round(leverage * leverage_factor))  # 临时值

# L15611-15623: BDSM 杠杆上限约束（保持不变，先执行）
if _source_tag_here == "bdsm" and not inference.get("stop_loss_px"):
    if leverage > 2.0:
        leverage = 2.0
        effective_leverage = max(1, round(leverage * leverage_factor))

# ★ 新增：在 BDSM 块之后，应用 trial 2x cap（最终覆盖）
effective_leverage = self._compute_effective_leverage(leverage, leverage_factor, is_trial)
```

**为什么必须在 BDSM 之后**：BDSM 块会将 `leverage` 从 5 降到 2，然后 `_compute_effective_leverage(2, factor, is_trial=True)` 才能正确得到 `min(2, 2*factor)`。若在 BDSM 之前调用，BDSM 块的 `effective_leverage = max(1, round(2 * factor))` 会覆盖 trial cap（如 factor=1.5 时得到 3x）。

**伪代码**：

```python
TRIAL_MAX_LEVERAGE: float = 2.0  # 类常量

def _compute_effective_leverage(self, base_leverage: float, leverage_factor: float,
                                 is_trial: bool) -> int:
    """计算有效杠杆。试错仓杠杆上限 2x，正常仓无上限。"""
    raw = base_leverage * leverage_factor
    if is_trial:
        return max(1, min(int(self.TRIAL_MAX_LEVERAGE), int(round(raw))))
    return max(1, int(round(raw)))
```

### 2.3 F3: 修复轻仓试错逻辑矛盾

**现状**：

```python
# L15324-15363
if _score_consensus >= self._gate_base_threshold:       # ≥ 0.40 → 正常通路
    pass
elif _p1_out_for_gate == "BLOCK" and confidence >= _f1_trial_threshold:  # F1 试错通路
    _f1_trial_mode = True
    is_trial = True
else:
    return  # 跳过

# Step ④/⑤
if confidence >= effective_threshold:    # 正常开仓
    pass
else:                                     # 轻仓试错
    is_trial = True                       # ← 矛盾点：score_cons=0.294<0.40 仍走到这里
```

**矛盾**：当 `_score_consensus=0.294 < _gate_base_threshold=0.40` 时，正常通路（Step ③第一个 if）不通过。但如果 P1=BLOCK 且 confidence ≥ 0.80，F1 试错通路放行。即使 score_consensus 极低（0.294），只要有置信度就开仓。

**问题**：score_consensus 是三层（P1/Elder/BCRM）加权共识分，0.294 意味着三层共识极低，不应仅凭模型置信度就试错开仓。

**方案**（用户确认 F3 下限 = 0.30）：

1. 新增类常量 `F1_TRIAL_MIN_SCORE_CONSENSUS = 0.30`（F1 试错通路的 score_consensus 下限）
   - **设计决策**：0.30 而非 0.40，保留 F1 试错机制但拦截极端低值（如 0.294 被拦截，[0.30, 0.40) 仍可试错）
   - 0.40 等价于完全关闭空单 F1 试错通路，用户选择保留机制
2. 在 L15327 的 F1 试错通路条件中增加 `and _score_consensus >= self.F1_TRIAL_MIN_SCORE_CONSENSUS`
3. 当 `score_consensus < F1_TRIAL_MIN_SCORE_CONSENSUS` 时，即使 P1=BLOCK 且置信度高也不放行

**改动点**：

| 文件 | 行号 | 改动 |
|------|------|------|
| polling_trader.py | 类常量区 | 新增 `F1_TRIAL_MIN_SCORE_CONSENSUS = 0.30` |
| polling_trader.py | L15327 | 条件增加 `_score_consensus >= self.F1_TRIAL_MIN_SCORE_CONSENSUS` |
| polling_trader.py | L15340-15348 | else 分支日志补充"score_consensus 低于 F1 试错下限"原因 |

**伪代码**：

```python
# 类常量
F1_TRIAL_MIN_SCORE_CONSENSUS: float = 0.30

# L15327 改为
elif (_p1_out_for_gate == "BLOCK"
      and confidence >= _f1_trial_threshold
      and _score_consensus >= self.F1_TRIAL_MIN_SCORE_CONSENSUS):
    _f1_trial_mode = True
    is_trial = True
    ...

# else 分支补充
else:
    if _p1_out_for_gate == "BLOCK" and confidence >= _f1_trial_threshold:
        _reason = f"score_cons={_score_consensus:.3f} < F1试错下限={self.F1_TRIAL_MIN_SCORE_CONSENSUS}"
    else:
        _reason = f"conf={confidence:.2f} < f1_thr={_f1_trial_threshold:.4f}"
    self._log(f"[{coin}] 过滤层跳过开仓 | ... {_reason}", "INFO")
    return
```

### 2.4 F4: 试错仓超时平仓（4 小时无趋势则离场）

**现状**：

```python
# L9877-9882
TRIAL_CONFIRM_PCT = 0.010        # confirm: +1%
TRIAL_REVERSE_PCT = -0.030        # reverse: -3%
TRIAL_FIRST_EVAL_SEC = 1800       # 首次评估：30min
TRIAL_REEVAL_INTERVAL_SEC = 3600  # 重评估：60min
```

无最大持仓时间。ARB 持仓 9.4h 才触发 reverse，试错仓长期占仓、资金效率低。

**问题**：试错仓本质是"快进快出"的探路仓位，持仓过久意味着趋势未确认，应主动离场而非无限等待。

**方案**：

1. 新增类常量 `TRIAL_MAX_HOLD_SEC = 4 * 3600`（4 小时超时）
2. 在 `_should_run_trial_eval` 返回 True 的评估块中（L14036-14093），增加超时检查：
   - 如果 `position_age_sec >= TRIAL_MAX_HOLD_SEC` 且当前 action 为 "maintain"（非 confirm/reverse）→ 强制平仓
3. 平仓 reason = `"trial_max_hold_timeout"`

> **★ Minor-1 约束**：超时检查嵌在 eval 周期内（`TRIAL_REEVAL_INTERVAL_SEC=3600`），实际超时触发时间约 4-4.5h，非精确 4h。如持仓 3.5h 时 eval 触发但未达 4h，则下次 eval 在 4.5h 才触发超时。这是可接受的近似。

**改动点**：

| 文件 | 行号 | 改动 |
|------|------|------|
| polling_trader.py | L9882 附近 | 新增 `TRIAL_MAX_HOLD_SEC = 4 * 3600` |
| polling_trader.py | L14088-14092 | "maintain" 分支增加超时检查 |

**伪代码**：

```python
# 类常量
TRIAL_MAX_HOLD_SEC: int = 4 * 3600  # 4小时超时

# L14088-14092 的 else (maintain) 分支改为
else:
    if position_age_sec >= self.TRIAL_MAX_HOLD_SEC:
        # 超时且无趋势 → 强制平仓
        self._log(
            f"[{coin}] 试错评估:超时无趋势 → 平仓 | "
            f"持仓={position_age_sec/3600:.1f}h ≥ {self.TRIAL_MAX_HOLD_SEC/3600:.0f}h "
            f"盈亏={upl:.2f}({upl_ratio:.2%})",
            "WARN",
        )
        _exit_price = _cur_price
        if pos_side == "long":
            _r = self.okx_client.market_close_long(inst_id, reason="trial_max_hold_timeout")
        else:
            _r = self.okx_client.market_close_short(inst_id, reason="trial_max_hold_timeout")
        if _r.get("ok") or _r.get("dry_run"):
            self._handle_close_position(
                inst_id=inst_id, coin=coin, pos_side=pos_side,
                exit_price=_exit_price, exit_reason="trial_max_hold_timeout",
                pnl=upl, pnl_pct=upl_ratio,
            )
            _trial_closed = True
    else:
        self._log(
            f"[{coin}] 试错评估:趋势不明 → 维持试错仓位 "
            f"(持仓={position_age_sec/60:.0f}min, 超时={self.TRIAL_MAX_HOLD_SEC/3600:.0f}h)",
            "INFO",
        )
```

---

## 3. 代码改动总览

### 3.1 改动文件

| 文件 | 改动类型 | 改动量 |
|------|---------|-------|
| `11-易经推理系统/scripts/memory_l4/polling_trader.py` | 修改+新增方法 | ~60 行 |
| `11-易经推理系统/tests/test_loss_prevention_fixes.py` | 新增测试用例 | ~40 行 |

### 3.2 改动清单

| # | 改动 | 文件 | 行号(约) | 依赖 |
|---|------|------|---------|------|
| C1 | 新增 `F1_TRIAL_SHORT_BASE_THRESHOLD=0.90` 类常量 | polling_trader.py | 类常量区 | - |
| C2 | __init__ 新增 `_f1_trial_short_threshold` + `_f1_trial_short_state` | polling_trader.py | L1416 附近 | C1 |
| C3 | L15168 空单分支改用 `_f1_trial_short_threshold` | polling_trader.py | L15168-15172 | C2 |
| C4 | 新增 `_maybe_adjust_f1_trial_short_threshold` 方法 | polling_trader.py | L16836 附近 | C2 |
| C5 | 平仓记录调用 C4 方法（trade_snapshot 补充 `"direction": _dr`） | polling_trader.py | L9758 附近 | C4 |
| C6 | 新增 `TRIAL_MAX_LEVERAGE=2.0` 类常量 | polling_trader.py | 类常量区 | - |
| C7 | 新增 `_compute_effective_leverage` 方法 | polling_trader.py | L8398 附近 | C6 |
| C8 | **L15623 之后**新增 `_compute_effective_leverage` 调用（BDSM 块之后） | polling_trader.py | L15623 后 | C7 |
| C9 | 新增 `F1_TRIAL_MIN_SCORE_CONSENSUS=0.30` 类常量 | polling_trader.py | 类常量区 | - |
| C10 | L15327 F1 条件增加 score_consensus 下限 | polling_trader.py | L15327 | C9 |
| C11 | L15340 else 分支日志细化 | polling_trader.py | L15340-15348 | C10 |
| C12 | 新增 `TRIAL_MAX_HOLD_SEC=4*3600` 类常量 | polling_trader.py | L9882 附近 | - |
| C13 | L14088 maintain 分支增加超时平仓 | polling_trader.py | L14088-14092 | C12 |

### 3.3 不在范围

- 试错仓仓位大小调整（已有 EG3L F1地板+F2上限控制）
- BCRM2.0 推理模型本身的方向偏差修复（需重训）
- 多单试错仓逻辑调整（多单无此系统性偏差）
- `_gate_base_threshold` 动态调节逻辑修改（保持不变）

---

## 4. 测试计划

### 4.1 单元测试（TDD RED→GREEN）

测试文件：`tests/test_trial_short_deviation_fix.py`（新建）

| 测试 | 验证点 | 预期 |
|------|--------|------|
| `test_f1_trial_short_threshold_default_090` | 空单 F1 试错门槛默认值 | `_f1_trial_short_threshold == 0.90` |
| `test_f1_trial_short_threshold_tightens_on_loss` | 空单胜率<40%时收紧 | threshold +0.02，边界[0.85,0.98] |
| `test_f1_trial_short_threshold_relaxes_on_win` | 空单胜率≥60%时放宽 | threshold -0.01 |
| `test_f1_trial_short_threshold_ignores_long` | 多单平仓不影响空单门槛 | threshold 不变 |
| `test_compute_effective_leverage_trial_capped` | is_trial=True 杠杆≤2 | `min(2, base*factor)` |
| `test_compute_effective_leverage_normal_uncapped` | is_trial=False 无上限 | `base*factor` |
| `test_f1_trial_blocked_when_score_below_floor` | score_cons<0.30 时不走 F1 通路 | return（跳过开仓） |
| `test_f1_trial_allowed_when_score_above_floor` | score_cons≥0.30 时正常 F1 通路 | is_trial=True |
| `test_trial_max_hold_timeout_closes_position` | 持仓≥4h 且 maintain → 平仓 | exit_reason="trial_max_hold_timeout" |
| `test_trial_max_hold_not_triggered_under_4h` | 持仓<4h 且 maintain → 维持 | 不平仓 |

### 4.2 已有测试回归

| 测试文件 | 验证点 |
|---------|--------|
| `tests/test_loss_prevention_fixes.py` | `_compute_effective_leverage` 3个测试转 GREEN |
| 所有现有 polling_trader 测试 | 零回归 |

### 4.3 日志验证（上线后）

观察 `logs/trading_stdout.log`：

1. `[F1永不BLOCK试错通路]` 日志中 `f1_thr=` 应显示 0.90+（非 0.80）
2. 试错仓开仓日志中杠杆应为 ≤2x（非 5x）
3. `score_cons < F1试错下限` 日志应出现（低共识分被拦截）
4. `试错评估:超时无趋势 → 平仓` 日志应出现（4h超时触发）

---

## 5. 风险与约束

### 5.1 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 空单 F1 门槛过高导致空单试错量下降 | 试错仓减少 = 逆势空单亏损减少 | 这是预期效果，非风险 |
| `_compute_effective_leverage` 影响已有 BDSM 杠杆逻辑 | BDSM 已有独立 2x 上限（L15614-15623），互不冲突 | BDSM 逻辑在 `_compute_effective_leverage` 调用之前执行 |
| 超时平仓可能误杀即将反转的仓位 | 少量本可盈利的试错仓被提前平 | 4h 足够趋势确认，未确认=趋势不明=不应继续占仓 |

### 5.2 约束

- 所有改动 FAIL-OPEN：异常不阻塞主流程
- 动态调节冷却期 30min，不频繁调整
- 多单试错仓逻辑不受影响（无此偏差）
