# 持仓与离场管理层 — ExitManager 策略链设计 Spec

> 日期: 2026-08-20
> 状态: 设计已确认 → 待写实现计划
> 关联文档:
> - [BCRM 2.0 满仓算力倾斜 + 三维度离场时机优化](2026-08-18-bcrm2-mode-evolution-design.md)（S2/S3/S4 开关）
> - [MorphCycle 周期动态修正](2026-08-19-morph-cycle-dynamic-correction-design.md)（前置层）
> - [TECHNICAL_DESIGN.md](../../11-易经推理系统/docs/TECHNICAL_DESIGN.md) 9.6/9.7 节（YijingExitSystem + ClassicExitSystem）
> 实现策略: **渐进提取**（单文件双模块，核心层不动，扩展层委托）
> 方法论: **严格 TDD**（先接口骨架→逐个策略迁移→核心层等价验证）
> 回滚铁律: 扩展层策略全关时，`_execute_trade` 行为等价于引入前（卦象主离场 + Classic 兜底原封不动）

---

## 1. 动机与背景

### 1.1 当前架构缺口

系统现有三层架构：前置层（市场形态预测）、核心层（入场信号计算）、后置层（回测阈值校正）。但**持仓与离场管理**散落在 `polling_trader._execute_trade` 的 8 个位置，无统一管理层：

| # | 离场机制 | 代码位置 | 触发条件 | 类型 |
|---|---|---|---|---|
| 1 | P3 提前退出 | L5676-5732 | `early_exit_signal` + 保护期内最小亏损阈值 | L1 硬风控 |
| 2 | 信号反转离场 | L5594-5645 | 方向反转 + 置信度达标 + 2 次确认 | L1 硬风控 |
| 3 | EV 雷达强平 | L3416-3454 | EV<-0.35 且非保护期 → force_close | L2 强平 |
| 4 | 超时止盈 | L5887-5965 | 29h 超时 + 盈利 + 信号排名对比 | L3 换仓 |
| 5 | 排名止盈 A/B/C | L3758-3866 | A 档立即换仓 / B 档排队 / C 档无动作 | L3 换仓 |
| 6 | EV 雷达调整 | L3456-3583 | EV 收紧(tighten) / EV 放宽(relax) | L4 动态调整 |
| 7 | 卦象主离场 | L5983-6017 | `yijing_exit_system.evaluate()` | 核心层 |
| 8 | Classic 兜底 | TECHNICAL_DESIGN 9.7 | 降级备用 | 核心层 |

### 1.2 问题

- 离场逻辑散落，优先级/互斥关系不清晰
- 保护期逻辑重复散布在各离场判断中
- 新增离场机制（EV 雷达、排名止盈）只是插入 `_execute_trade`，无统一接口
- 无法评估各策略的贡献值（早期 Classic 兜底表现差，后期优化策略表现好很多，但无量化追踪）

### 1.3 目标

以 `2026-08-18-bcrm2-mode-evolution-design.md` 为基础，新建 **ExitManager** 策略链，统一管理扩展层离场逻辑，核心层（卦象主离场 + Classic 兜底）保持原样。

---

## 2. 架构设计

### 2.1 核心层 vs 扩展层

**核心层（不可动摇的根本，ExitManager 不接管）**：
- **静态 SLTP** — 开仓时设置的基础止损止盈，最后安全网
- **卦象主离场**（YijingExitSystem）— 当前主离场决策引擎
- **保护期逻辑**（in_protection）— 所有离场的安全前提（<6h 限制强平）
- **Classic 兜底**（ClassicExitSystem）— 降级备用

**扩展层（ExitManager 编排，围绕核心组织）**：
- L1 硬风控前置：P3 提前退出、信号反转
- L2 强平类：EV 雷达强平
- L3 换仓优化：超时止盈、排名止盈 A/B/C
- L4 动态调整（移动止盈）：EV 雷达收紧/放宽

### 2.2 ExitManager 职责

```
polling_trader._execute_trade(coin, inference)
  ├─ 基础数据准备（pos_info / tracker_pos / in_protection / age_hours）
  ├─ 静态 SLTP 检查（核心层，不动）
  ├─ ExitManager.evaluate(coin, inference, pos_info, ...) → ExitDecision
  │    ├─ priority=10: P3EarlyExitStrategy.evaluate(ctx) → 非 pass 即返回
  │    ├─ priority=20: SignalReverseStrategy.evaluate(ctx) → 非 pass 即返回
  │    ├─ priority=30: EvForceCloseStrategy.evaluate(ctx) → 非 pass 即返回
  │    ├─ priority=40: TimeoutProfitSwitchStrategy.evaluate(ctx) → 非 pass 即返回
  │    ├─ priority=50: RankedTpStrategy.evaluate(ctx) → 非 pass 即返回
  │    ├─ priority=60: EvAdjustStrategy.evaluate(ctx) → 非 pass 即返回
  │    └─ 全部 pass → 返回 ExitDecision(action="pass")
  ├─ if decision.action == "force_close": 执行离场确认+平仓
  ├─ elif decision.action == "adjust_sl_tp": 调用 _adjust_sl_tp()
  ├─ elif decision.action == "ranked_tp": 执行排名止盈 A/B/C 逻辑
  ├─ elif decision.action == "pass":
  │    ├─ 卦象主离场（核心层，原样不动）
  │    └─ Classic 兜底（核心层，原样不动）
  └─ 记录 exit_strategy_log（策略贡献值追踪）
```

---

## 3. 接口设计

### 3.1 数据结构

```python
@dataclass
class ExitContext:
    """传入各 ExitStrategy 的上下文快照。"""
    coin: str
    inference: dict           # BCRM 2.0 推理结果
    pos_info: dict           # 持仓信息
    tracker_pos: Any         # PositionTracker 持仓对象
    in_protection: bool      # 是否在保护期（<6h）
    age_hours: float          # 持仓时长
    ev: float = None         # EV 风险价值（S2=ON 时计算）
    multi_horizon: dict = None  # 多 horizon 预测（S3=ON 时填充）
    confidence: float = 0.0  # 当前推理置信度


@dataclass
class ExitDecision:
    """ExitStrategy 返回的离场决策。"""
    action: str              # "force_close" | "adjust_sl_tp" | "ranked_tp" | "hold" | "pass"
    reason: str              # "p3_early_exit" | "signal_reverse" | "ev_force_close" | ...
    params: dict = None      # adjust_sl_tp 时的 new_sl/new_tp，ranked_tp 时的 tier/coin
    strategy_name: str = ""  # 贡献归属的策略名

    @staticmethod
    def pass_() -> "ExitDecision":
        """不触发，交由下一策略。"""
        return ExitDecision(action="pass", reason="", strategy_name="")
```

### 3.2 ExitStrategy 抽象接口

```python
class ExitStrategy(ABC):
    """离场策略抽象基类。"""

    name: str = ""               # 策略名（如 "p3_early_exit"）
    priority: int = 0            # 优先级（数字越小越先评估）
    enabled: bool = True         # 开关（对应 BCRM2 spec 的 S2/S3/S4）

    @abstractmethod
    def evaluate(self, context: ExitContext) -> ExitDecision:
        """评估离场决策。返回 action="pass" 表示不触发。"""

    def record_outcome(self, decision: ExitDecision, pnl: float, win: bool):
        """记录该次决策的实际盈亏结果，用于贡献值统计。"""
```

### 3.3 ExitManager

```python
class ExitManager:
    """离场策略链管理器。"""

    def __init__(self, strategies: List[ExitStrategy] = None):
        self._strategies = sorted(strategies or [], key=lambda s: s.priority)
        self._log_buffer: List[dict] = []

    def evaluate(self, coin, inference, pos_info, tracker_pos,
                 in_protection, age_hours, **kwargs) -> ExitDecision:
        """按优先级链调用各策略，返回首个非 pass 的决策。"""
        ctx = ExitContext(
            coin=coin, inference=inference, pos_info=pos_info,
            tracker_pos=tracker_pos, in_protection=in_protection,
            age_hours=age_hours, **kwargs,
        )
        for strategy in self._strategies:
            if not strategy.enabled:
                continue
            decision = strategy.evaluate(ctx)
            if decision.action != "pass":
                decision.strategy_name = strategy.name
                return decision
        return ExitDecision.pass_()

    def get_strategy_contribution(self, days=30) -> dict:
        """返回各策略近 N 天的贡献统计（触发次数/胜率/平均盈亏）。"""
```

---

## 4. 策略链详细设计

### 4.1 策略优先级与 BCRM2 spec 映射

| 优先级 | 策略类 | BCRM2 开关 | 动作 | 核心约束 |
|---|---|---|---|---|
| 10 | `P3EarlyExitStrategy` | — | force_close | 保护期内需最小亏损阈值 |
| 20 | `SignalReverseStrategy` | — | force_close | 2 次确认 |
| 30 | `EvForceCloseStrategy` | S2=enable_ev_radar | force_close | EV<-0.35 且非保护期 |
| 40 | `TimeoutProfitSwitchStrategy` | — | force_close | 29h 超时 + 盈利 + 信号排名对比 |
| 50 | `RankedTpStrategy` | S4=enable_ranked_tp | ranked_tp / adjust_sl_tp | A 档手续费前置校验 |
| 60 | `EvAdjustStrategy` | S2=enable_ev_radar | adjust_sl_tp | EV 收紧/放宽（移动止盈） |
| — | `pass` → 核心层 | — | — | 卦象主离场 → Classic 兜底 |

### 4.2 各策略迁移说明

#### P3EarlyExitStrategy (priority=10)
- **原位置**: `polling_trader.py` L5676-5732
- **迁移**: 提取 `early_exit_signal` 判断 + 保护期内最小亏损阈值 + 2 次确认逻辑
- **BCRM2 spec**: 不依赖 S2/S3/S4，始终启用
- **返回**: `ExitDecision(action="force_close", reason="p3_early_exit")`

#### SignalReverseStrategy (priority=20)
- **原位置**: `polling_trader.py` L5594-5645
- **迁移**: 提取方向反转 + 置信度达标 + 2 次确认逻辑
- **BCRM2 spec**: 不依赖 S2/S3/S4，始终启用
- **返回**: `ExitDecision(action="force_close", reason="signal_reverse")`

#### EvForceCloseStrategy (priority=30)
- **原位置**: `polling_trader.py` L3416-3454
- **迁移**: 提取 EV<-0.35 强平 + 非保护期判断 + 离场确认 2/2
- **BCRM2 spec**: `enabled = S2 (enable_ev_radar)`
- **返回**: `ExitDecision(action="force_close", reason="ev_force_close")`

#### TimeoutProfitSwitchStrategy (priority=40)
- **原位置**: `polling_trader.py` L5887-5965
- **迁移**: 提取 29h 超时 + 盈利判断 + 信号排名对比逻辑
- **BCRM2 spec**: 不直接依赖 S2/S3/S4，但 S4=ON 时排名止盈优先级更高
- **返回**: `ExitDecision(action="force_close", reason="timeout_profit_switch")`

#### RankedTpStrategy (priority=50)
- **原位置**: `polling_trader.py` L3758-3866
- **迁移**: 提取 A 档立即换仓（含手续费前置校验）+ B 档排队 + C 档无动作
- **BCRM2 spec**: `enabled = S4 (enable_ranked_tp)`，S3 影响其 dim1 信号来源
- **返回**: `ExitDecision(action="ranked_tp", reason="ranked_tp_a/b/c", params={...})`

#### EvAdjustStrategy (priority=60)
- **原位置**: `polling_trader.py` L3456-3583
- **迁移**: 提取 EV 收紧(tighten) / EV 放宽(relax) + `_adjust_sl_tp()` 调用
- **BCRM2 spec**: `enabled = S2 (enable_ev_radar)`
- **移动止盈**: EV 放宽(relax) 即移动止盈策略，复用现有 `_adjust_sl_tp`
- **返回**: `ExitDecision(action="adjust_sl_tp", reason="ev_warn/ev_strong_hold", params={...})`

### 4.3 与 BCRM2 spec 开关融合

| BCRM2 开关 | 影响的 ExitStrategy | 关闭时行为 |
|---|---|---|
| S1=enable_mode_switch | 无（仅影响推理层） | — |
| S2=enable_ev_radar | EvForceCloseStrategy + EvAdjustStrategy | 两者 enabled=False，跳过 EV 计算 |
| S3=enable_multi_horizon | RankedTpStrategy（dim1 信号来源） | RankedTp 使用 Phase B 方向一致性代理 |
| S4=enable_ranked_tp | RankedTpStrategy | enabled=False，跳过排名止盈，29h 超时直接走原 timeout_profit_switch |

---

## 5. 策略贡献值评估

### 5.1 exit_strategy_log 表

```sql
CREATE TABLE IF NOT EXISTS exit_strategy_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timestamp       TEXT NOT NULL,          -- ISO 8601 UTC
    strategy_name   TEXT NOT NULL,          -- "p3_early_exit" / "ev_force_close" / ...
    action          TEXT,                  -- "force_close" / "adjust_sl_tp" / "ranked_tp"
    reason          TEXT,
    age_hours       REAL,
    in_protection   INTEGER,              -- 0/1
    ev              REAL,
    confidence      REAL,
    pnl             REAL,                  -- 实际盈亏（平仓后回填）
    win             INTEGER               -- 0/1 胜负（平仓后回填）
);
CREATE INDEX IF NOT EXISTS idx_exit_strat_symbol_ts ON exit_strategy_log(symbol, timestamp);
```

### 5.2 贡献值统计

`ExitManager.get_strategy_contribution(days=30)` 返回：
```python
{
    "p3_early_exit": {"triggers": 12, "wins": 5, "win_rate": 0.42, "avg_pnl": -0.02},
    "signal_reverse": {"triggers": 8, "wins": 5, "win_rate": 0.63, "avg_pnl": 0.15},
    "ev_force_close": {"triggers": 3, "wins": 0, "win_rate": 0.0, "avg_pnl": -0.35},
    "timeout_profit_switch": {"triggers": 15, "wins": 9, "win_rate": 0.60, "avg_pnl": 0.08},
    "ranked_tp_a": {"triggers": 5, "wins": 4, "win_rate": 0.80, "avg_pnl": 0.22},
    "ev_adjust": {"triggers": 20, "wins": 12, "win_rate": 0.60, "avg_pnl": 0.05},
    "yijing_exit": {"triggers": 30, "wins": 18, "win_rate": 0.60, "avg_pnl": 0.10},
    "classic_fallback": {"triggers": 2, "wins": 0, "win_rate": 0.0, "avg_pnl": -0.15},
}
```

**策略调整规则**：
- 连续 30 天胜率 < 0.20 且触发次数 ≥ 5 → 自动降低优先级（priority += 10）
- 平均盈亏为负且触发次数 ≥ 5 → 日志 WARN 提示人工评估
- Classic 兜底胜率持续低 → 确认其仅作兜底，不主动触发

---

## 6. 文件结构

### 6.1 新增文件

```
scripts/memory_l4/bcrm2/
  ├── exit_manager.py          # ExitManager + ExitDecision + ExitContext + ExitStrategy 基类
  └── exit_strategies.py       # 6 个 ExitStrategy 子类
```

### 6.2 修改文件（最小改动）

| 文件 | 改动 |
|---|---|
| `polling_trader.py` | `__init__` 新增 `self._exit_manager`；`_execute_trade` 离场判断段委托给 ExitManager |
| `bcrm2/storage.py` | 新增 `exit_strategy_log` 表 + `save_exit_strategy_log` / `get_exit_strategy_log` / `get_exit_strategy_contribution` |
| `trading_utils.py` | `OpenPosition` 新增 `last_exit_strategy: str = ""`（记录触发策略名） |

### 6.3 实施顺序（TDD）

1. 定义 `ExitDecision` / `ExitContext` 数据结构 + `ExitStrategy` 抽象接口
2. 实现 `ExitManager.evaluate()` 优先级链（空策略列表 → 全 pass）
3. 逐个迁移 6 个策略（P3 → SignalReverse → EvForceClose → Timeout → RankedTp → EvAdjust）
4. `polling_trader._execute_trade` 切换到 `ExitManager` 调用
5. 新增 `exit_strategy_log` 表 + 贡献值统计
6. 验证核心层（卦象主离场 + Classic 兜底）行为等价

---

## 7. TDD 验证矩阵

| 测试名 | RED 原因 | GREEN 最小实现 | 断言 |
|---|---|---|---|
| `test_exit_manager_empty_strategies_returns_pass` | ExitManager 不存在 | 骨架类 + 空 evaluate | 空策略列表 → ExitDecision(action="pass") |
| `test_exit_manager_priority_chain_first_non_pass_wins` | 优先级链不存在 | 排序+短路逻辑 | 3 个策略，第二个返回 force_close → 第三个 never called |
| `test_p3_early_exit_protection_period_requires_min_loss` | P3 策略不存在 | 提取 L5676-5732 | 保护期内 + 亏损<阈值 → pass；亏损≥阈值 → force_close |
| `test_signal_reverse_requires_2_confirmations` | SignalReverse 不存在 | 提取 L5594-5645 | 第 1 次反转 → pass；第 2 次反转 → force_close |
| `test_ev_force_close_disabled_when_s2_off` | EvForceClose 不存在 | 提取 L3416-3454 | S2=False → enabled=False → pass |
| `test_ev_force_close_blocked_in_protection` | 保护期门禁未写 | 同上 | EV<-0.35 + in_protection=True → pass |
| `test_timeout_profit_switch_29h_profitable` | Timeout 不存在 | 提取 L5887-5965 | age=29h + 盈利 + 更强信号 → force_close |
| `test_ranked_tp_a_tier_fee_gate_downgrade_to_b` | RankedTp 不存在 | 提取 L3758-3866 | 手续费 > 期望收益 → 降级 B 档 |
| `test_ev_adjust_tighten_calls_adjust_sl_tp` | EvAdjust 不存在 | 提取 L3456-3583 | EV∈[-0.35,-0.1] → adjust_sl_tp(tighten) |
| `test_all_disabled_falls_to_yijing_exit` | 核心层等价验证 | 全策略 enabled=False | decision.action="pass" → polling_trader 走原卦象离场 |
| `test_strategy_contribution_records_pnl` | exit_strategy_log 不存在 | 表+CRUD | 平仓后回填 pnl/win，get_strategy_contribution 返回正确统计 |

---

## 8. 与现有文档的关系

| 现有文档 | 关系 |
|---|---|
| `2026-08-18-bcrm2-mode-evolution-design.md` | S2/S3/S4 开关作为 ExitStrategy.enabled 属性融入；S1 不涉及离场 |
| `TECHNICAL_DESIGN.md` 9.6 节 YijingExitSystem | 核心层，ExitManager pass 后进入，不动 |
| `TECHNICAL_DESIGN.md` 9.7 节 ClassicExitSystem | 核心层兜底，不动 |
| `2026-08-19-morph-cycle-dynamic-correction-design.md` | 前置层，提供 forecast_L/T 给 ExitContext |

---

## 9. 风险与约束

1. **核心层不动**: 卦象主离场 + Classic 兜底 + 保护期逻辑 + 静态 SLTP 保持原样，ExitManager 只编排扩展层
2. **回滚铁律**: 扩展层全关时，`_execute_trade` 行为等价于引入前
3. **BCRM2 spec 兼容**: S2/S3/S4 开关作为 ExitStrategy.enabled 属性，关闭时行为与 BCRM2 spec 一致
4. **迁移渐进**: 逐个策略迁移，每迁移一个策略跑一轮 TDD，确保不破坏现有行为
5. **贡献值数据延迟**: exit_strategy_log 的 pnl/win 字段需平仓后回填，非实时

---

## 10. 下一步

Spec 已写完并归档到 `docs/superpowers/specs/2026-08-20-exit-manager-design.md`。请你审阅这份实现设计 Spec，确认没有修改/补充后，进入 writing-plans 生成详细实现计划，然后严格按 TDD 循环推进。
