# 通用风控引擎 — 技术设计文档

> **版本**: v1.0 | **更新日期**: 2026-07-31
> **定位**: 13-通用风控模块 技术设计文档，定义三层风控体系、规则注册机制与数据流
> **关联**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) · [API_SPEC.md](./API_SPEC.md) · [CHANGELOG.md](./CHANGELOG.md)

---

## 1. 概述

通用风控引擎（Universal Risk Engine）是为所有交易模块提供统一风控能力的核心组件。通过三层风控体系（事前门禁、仓位管理、事后离场）和可插拔的规则注册机制，为马丁策略、三屏趋势、易经推理等不同交易系统提供标准化、可配置、可扩展的风控服务。

### 1.1 设计目标

- **统一标准**：为所有交易模块提供一致的风控接口和规则
- **可插拔扩展**：基于注册表的规则机制，支持动态增删风控规则
- **分层架构**：事前-事中-事后三层风控，层层递进
- **Fail-Closed**：缺失数据或异常时默认拒绝，安全第一
- **SDK 集成**：Python 包形式，低侵入，渐进式迁移
- **理由码体系**：完整的审计追踪，每个决策都有明确原因

### 1.2 设计原则

1. **单一职责**：每层、每个规则只做一件事
2. **优先级驱动**：按优先级顺序执行，高优先级优先触发
3. **短路执行**：遇到硬阻断立即返回，不执行后续规则
4. **配置驱动**：所有阈值通过配置调整，无需修改代码
5. **与知识库对齐**：理由码、门禁优先级与 `2-KNOWLEDGE/1-TRADING/风控体系.md` 完全一致

---

## 2. 架构设计

### 2.1 整体架构

```
┌──────────────────────────────────────────────────────────┐
│                    RiskEngine (统一入口)                   │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ 事前门禁层   │  │ 仓位管理层   │  │ 事后离场层   │          │
│  └────────────┘  └────────────┘  └────────────┘          │
└──────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│                  RuleRegistry (规则注册表)                 │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐                     │
│  │ G1 │ │ G2 │ │ P1 │ │ P2 │ │ E1 │  ...                 │
│  └────┘ └────┘ └────┘ └────┘ └────┘                     │
└──────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│              RiskContext / StateStore (状态层)             │
│  账户状态 │ 持仓状态 │ 日盈亏 │ 回撤记录 │ 交易历史          │
└──────────────────────────────────────────────────────────┘
```

### 2.2 三层风控体系

#### L1 - 事前门禁层 (PreTradeGate)

交易执行前的风控检查，决定是否允许开仓。

**门禁优先级（按执行顺序）：**

| 优先级 | 规则名称 | 类别 | 说明 |
|:---:|---|---|---|
| 5 | daily_drawdown_circuit_breaker | P0 硬阻断 | 日回撤熔断，超过阈值全天禁止开仓 |
| 10 | leverage_cap_check | P0 硬阻断 | 杠杆上限检查 |
| 20 | concurrent_position_limit | 账户层 | 并发仓位数量限制 |
| 25 | consecutive_losses_limit | 账户层 | 连续亏损次数限制 |
| 30 | blackout_period_check | 账户层 | 黑窗时段检查 |
| 50 | confidence_minimum | 评分门禁 | 最低置信度检查 |
| 60 | drawdown_warning_degrade | 降级 | 回撤警告时仓位降级 |

**执行机制：**
- 按优先级从小到大顺序执行
- 遇到 `passed=False` 立即返回（短路）
- 遇到降级规则，累积 `position_modifier` 乘积
- 所有规则通过后返回最终结果

#### L2 - 仓位管理层 (PositionSizer)

计算合适的仓位大小，确保单笔风险在预算范围内。

**计算流程：**

```
基础风险预算 (equity × risk_pct)
    × position_modifier (门禁降级系数)
    × confidence_multiplier (置信度系数)
    × volatility_multiplier (波动率系数)
    ↓
调整后风险预算
    ↓
止损距离 → 仓位大小
    ↓
最大/最小仓位约束
    ↓
最终仓位结果
```

**仓位规则：**

| 规则 | 说明 |
|---|---|
| confidence_based_adjustment | 基于信号置信度动态调整 |
| volatility_based_adjustment | 基于市场波动率动态调整 |
| max_position_cap | 单笔最大仓位上限 |

#### L3 - 事后离场层 (ExitEngine)

持仓期间的持续风险监控和离场决策。

**四层离场体系（优先级从高到低）：**

| 优先级 | 层级 | 规则 | 说明 |
|:---:|---|---|---|
| P0 | 安全硬退出 | max_loss_stop | 最大亏损止损 |
| P0 | 安全硬退出 | liquidation_buffer | 强平安全缓冲 |
| P0 | 安全硬退出 | max_hold_time | 最大持仓时间 |
| P2 | 三重屏障 | stop_loss_barrier | 止损屏障 |
| P2 | 三重屏障 | take_profit_barrier | 止盈屏障 |
| P2 | 三重屏障 | time_barrier | 时间屏障 |
| P3 | 行为约束 | trailing_stop | 跟踪止损 |

**执行机制：**
- 按优先级（P0→P3）顺序检查
- 返回最高优先级的离场动作
- P0 触发后立即返回（一票否决）

---

## 3. 核心数据结构

### 3.1 枚举类型

```python
class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"

class ExitAction(str, Enum):
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"

class ExitPriority(str, Enum):
    P0_L0_HARD = "p0_l0"
    P1_VALUE_RISK = "p1"
    P2_TRIPLE_BARRIER = "p2"
    P3_BEHAVIORAL = "p3"

class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NORMAL = "normal"
```

### 3.2 理由码体系

与知识库 `风控体系.md` 对齐：

| 类别 | 码 | 含义 |
|---|---|---|
| 通过 | PASS | 风控通过 |
| 🔴 硬阻断 | HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER | 回撤熔断 |
| 🔴 硬阻断 | HARD_FAIL_LEVERAGE_EXCEEDS_CAP | 杠杆超限 |
| 🔴 硬阻断 | HARD_FAIL_CONCURRENT_LIMIT | 并发仓位超限 |
| 🔴 硬阻断 | HARD_FAIL_CONSECUTIVE_LOSSES | 连续亏损超限 |
| 🔴 硬阻断 | HARD_FAIL_BLACKOUT | 黑窗时段 |
| 🔴 硬阻断 | HARD_FAIL_STRATEGY_EXCLUDED | 战略排除 |
| 🟡 降级 | DEGRADE_DRAWDOWN_WARNING | 回撤警告降级 |
| 🟡 降级 | DEGRADE_DREAM_MODE | 梦模式降级 |
| 🔵 警告 | SOFT_WARN_LOW_CONFIDENCE | 低置信度警告 |

### 3.3 主要数据类

- **Signal**：交易信号（币种、方向、置信度、入场价、止损价等）
- **PositionState**：持仓状态（入场价、当前价、盈亏、杠杆、ATR等）
- **MarketSnapshot**：市场快照（价格、RSI、MACD、ATR、波动率等）
- **RiskContext**：风控上下文（账户权益、日盈亏、回撤、持仓列表等）
- **RiskCheckResult**：风控检查结果（是否通过、理由码、风险等级、仓位调整系数）
- **PositionSizeResult**：仓位计算结果（基础仓位、风险金额、加仓列表、仓位等级）
- **ExitResult**：离场决策结果（动作、优先级、原因、减仓比例）

---

## 4. 核心模块设计

### 4.1 RiskEngine（统一入口）

核心入口类，整合三层风控体系。

**主要接口：**

```python
# 事前风控检查
pre_trade_check(signal, context, extra=None) -> RiskCheckResult

# 仓位计算
calculate_position(signal, context, position_modifier=1.0, extra=None) -> PositionSizeResult

# 离场决策
check_exit(position, market=None, context=None, extra=None) -> ExitResult

# 完整事前流程（门禁+仓位）
full_pre_trade(signal, context, extra=None) -> dict

# 规则管理
register_rule(name, category, handler, priority, description)
enable_rule(name) -> bool
disable_rule(name) -> bool
list_rules() -> dict
```

### 4.2 RuleRegistry（规则注册表）

可插拔的规则注册与管理机制。

**核心功能：**
- 按类别（GATE / POSITION / EXIT）分组管理
- 按优先级排序执行
- 支持启用/禁用规则
- 支持装饰器式注册
- 支持链式执行（遇到失败可停止）

**使用方式：**

```python
registry = RuleRegistry()

@registry.register_gate("my_rule", priority=10)
def my_rule(signal, context, config, extra=None):
    return RiskCheckResult.pass_result()

rules = registry.get_enabled_rules(RuleCategory.GATE)
results = registry.execute_chain(RuleCategory.GATE, signal=signal, context=context)
```

### 4.3 RiskContext（风控上下文）

全局风控状态的单一真相源。

**核心状态：**
- 账户状态：总权益、可用余额、已用保证金
- 日度数据：日初权益、日最高权益、日盈亏、日回撤
- 交易统计：总交易数、胜数、胜率、连续亏损数
- 持仓管理：当前持仓字典、交易历史

**核心方法：**
- `update_equity()`：更新账户权益
- `add_position()` / `remove_position()`：管理持仓
- `record_trade()`：记录交易，更新统计
- `reset_daily()`：重置日度数据
- `daily_drawdown_pct`：当日回撤百分比
- `win_rate`：胜率

---

## 5. 默认规则说明

### 5.1 门禁规则

#### daily_drawdown_circuit_breaker
日回撤熔断 — 当日回撤超过阈值时全天禁止开仓。

**配置项：**
- `max_daily_drawdown_pct` (default: 0.10)：熔断阈值

#### leverage_cap_check
杠杆上限检查 — 确保杠杆不超过最大限制。

**配置项：**
- `max_leverage` (default: 10.0)：最大杠杆

#### concurrent_position_limit
并发仓位限制 — 限制同时持有的仓位数量。

**配置项：**
- `max_concurrent_positions` (default: 5)：最大并发仓位

#### consecutive_losses_limit
连续亏损限制 — 连续亏损达到阈值时暂停开仓。

**配置项：**
- `max_consecutive_losses` (default: 5)：最大连续亏损次数

#### blackout_period_check
黑窗时段检查 — 宏观数据发布等高风险时段禁止开仓。

**配置项：**
- `blackout_windows` (default: [])：黑窗时段列表，格式 `[{"start": "HH:MM", "end": "HH:MM"}]`

#### confidence_minimum
最低置信度检查 — 信号置信度不足时降级或拒绝。

**配置项：**
- `confidence_hard_min` (default: 0.2)：硬阈值，低于则拒绝
- `confidence_soft_min` (default: 0.4)：软阈值，低于则仓位降级

#### drawdown_warning_degrade
回撤警告降级 — 回撤达到警告线时仓位减半。

**配置项：**
- `drawdown_warn_1` (default: 0.05)：一级警告，仓位×0.5
- `drawdown_warn_2` (default: 0.08)：二级警告，仓位×0.25

### 5.2 仓位规则

#### confidence_based_adjustment
置信度仓位调整 — 高置信度加仓，低置信度减仓。

**配置项：**
- `high_conf_multiplier` (default: 1.2)：高置信度(>0.8)系数
- `mid_high_conf_multiplier` (default: 1.0)：中高置信度(0.6-0.8)系数
- `mid_conf_multiplier` (default: 1.0)：中置信度(0.4-0.6)系数
- `low_conf_multiplier` (default: 0.5)：低置信度(<0.4)系数

#### volatility_based_adjustment
波动率仓位调整 — 高波动减仓，低波动加仓。

**配置项：**
- `baseline_atr_pct` (default: 0.02)：基准ATR百分比

#### max_position_cap
最大仓位限制 — 单笔仓位不超过总权益的一定比例。

**配置项：**
- `max_position_pct` (default: 0.25)：最大仓位比例

### 5.3 离场规则

#### max_loss_stop (P0)
最大亏损止损 — 亏损达到最大阈值立即平仓。

**配置项：**
- `max_loss_pct` (default: 0.10)：最大亏损百分比

#### liquidation_buffer (P0)
强平安全缓冲 — 接近强平价时提前平仓。

**配置项：**
- `liquidation_buffer_pct` (default: 0.05)：强平缓冲百分比

#### max_hold_time (P0)
最大持仓时间 — 持仓超过最大时间平仓。

**配置项：**
- `max_hold_sec` (default: 7×24×3600)：最大持仓秒数

#### stop_loss_barrier (P2)
止损屏障 — 基于ATR或固定百分比的止损。

**配置项：**
- `stop_method` (default: "atr")：止损方法 ("atr" | "pct")
- `atr_stop_multiplier` (default: 2.0)：ATR止损倍数
- `stop_loss_pct` (default: 0.03)：固定止损百分比

#### take_profit_barrier (P2)
止盈屏障 — 基于盈亏比或固定百分比的止盈。

**配置项：**
- `tp_method` (default: "rr")：止盈方法 ("rr" | "pct")
- `rr_ratio` (default: 2.0)：盈亏比
- `take_profit_pct` (default: 0.06)：固定止盈百分比
- `tp_reduce_frac` (default: 0.5)：止盈减仓比例

#### time_barrier (P2)
时间屏障 — 持仓达到一定时间且盈利达标时触发离场。

**配置项：**
- `time_barrier_sec` (default: 24×3600)：时间屏障秒数
- `time_barrier_min_profit_pct` (default: 0.01)：最小盈利百分比

#### trailing_stop (P3)
跟踪止损 — 盈利达到一定幅度后启动跟踪止损。

**配置项：**
- `trailing_arm_pct` (default: 0.03)：激活阈值百分比
- `trailing_pct` (default: 0.02)：跟踪回撤百分比

---

## 6. 使用示例

### 6.1 基础使用

```python
from risk_engine import RiskEngine, RiskContext, Signal, Direction

# 初始化引擎
engine = RiskEngine({
    "gate": {
        "daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.10},
        "concurrent_position_limit": {"max_concurrent_positions": 5},
        "confidence_minimum": {"confidence_hard_min": 0.2, "confidence_soft_min": 0.4},
    },
    "position": {
        "risk_per_trade_pct": 0.02,
        "max_position_pct": 0.25,
        "default_stop_pct": 0.03,
    },
    "exit": {
        "max_loss_stop": {"max_loss_pct": 0.10},
        "stop_loss_barrier": {"stop_method": "pct", "stop_loss_pct": 0.03},
        "take_profit_barrier": {"tp_method": "rr", "rr_ratio": 2.0},
    },
})
engine.register_default_rules()

# 创建上下文
context = RiskContext(total_equity=10000)

# 事前风控检查
signal = Signal(
    coin="BTC",
    direction=Direction.LONG,
    confidence=0.7,
    entry_price=50000,
    stop_loss_price=48500,
)
result = engine.pre_trade_check(signal, context)

if result.passed:
    # 计算仓位
    size = engine.calculate_position(signal, context, result.position_modifier)
    print(f"开仓: {size.base_size_usdt:.2f} USDT")
```

### 6.2 自定义规则

```python
# 注册自定义门禁规则
@engine.registry.register_gate("my_custom_rule", priority=15)
def my_custom_rule(signal, context, config, extra=None):
    # 自定义逻辑
    if some_condition:
        return RiskCheckResult.fail_result(
            reason_code=ReasonCode.HARD_FAIL_STRATEGY_EXCLUDED,
            message="自定义规则不通过"
        )
    return RiskCheckResult.pass_result()

# 禁用/启用规则
engine.disable_rule("blackout_period_check")
engine.enable_rule("blackout_period_check")
```

### 6.3 离场监控

```python
from risk_engine import PositionState, MarketSnapshot, ExitAction

position = PositionState(
    coin="BTC",
    side=Direction.LONG,
    entry_price=50000,
    current_price=51000,
    unrealized_pnl_pct=0.02,
    leverage=5.0,
    atr_pct=0.02,
    position_age_sec=7200,
)

market = MarketSnapshot(coin="BTC", price=51000, rsi=65)

result = engine.check_exit(position, market, context)

if result.action == ExitAction.CLOSE:
    print(f"平仓: {result.reason}")
elif result.action == ExitAction.REDUCE:
    print(f"减仓 {result.reduce_frac:.0%}: {result.reason}")
```

---

## 7. 目录结构

```
13-通用风控模块/
├── core/                    # 核心引擎
│   ├── __init__.py
│   ├── engine.py           # RiskEngine 统一入口
│   ├── context.py          # 风控上下文与数据结构
│   ├── registry.py         # 规则注册表
│   ├── pre_trade_gate.py   # 事前门禁层
│   ├── position_sizer.py   # 仓位管理层
│   └── exit_engine.py      # 事后离场层
├── rules/                   # 风控规则集（可插拔）
│   ├── __init__.py
│   ├── gate_rules.py       # 门禁规则
│   ├── position_rules.py   # 仓位规则
│   └── exit_rules.py       # 离场规则
├── docs/                    # 文档
│   ├── TECHNICAL_DESIGN.md
│   ├── ENGINEERING_INDEX.md
│   └── API_SPEC.md
├── tests/                   # 测试
│   ├── __init__.py
│   └── test_risk_engine.py
├── README.md
└── __init__.py
```

---

## 8. 与现有系统的对接路径

### 8.1 马丁策略对接

1. 用 `PositionSizer` 替换 `capital_manager.py` 的仓位计算
2. 用 `PreTradeGate` 替换硬编码的并发/资金检查
3. 用 `ExitEngine` 替换 `v15_trader.py` 的止损止盈逻辑

### 8.2 三屏趋势系统对接

1. 接入 `PreTradeGate` 进行事前风控
2. 用 `PositionSizer` 的置信度调整替代内部仓位分级
3. 用 `ExitEngine` 替换 `classic_exit_system.py` 的调用

### 8.3 经典指标系统对接

1. 逐步迁移 `classic_exit_system.py` 的规则到 `ExitEngine`
2. 统一风控状态到 `RiskContext`
3. 接入 `PreTradeGate` 增强事前风控

---

## 9. L1 价值-风险评估（v1.1 新增）

### 9.1 概述

L1 价值-风险评估器（L1ValueRiskAssessor）复现了经典离场系统 `classic_exit_system.py` 的核心评估逻辑，提供完整的 `hold_risk → 动作映射` 链路。

### 9.2 计算链路

```
[基础指标] → _calc_hold_risk (10维加权，dd_risk主导 0.42权重)
          → MRD 调整 (p_mrd < 0.40 加风险 / > 0.60 减风险)
          → ML 调整 (p_tail 启发式融合，blend_h=0.25)
          → 风险预算惩罚 (序列 dd 增量归一化 × 0.15)
          → clip[0,1] = final hold_risk
          → hold_value = 1 - hold_risk
          → Regime 偏移 (震荡市 +0.05, 低ADX +0.03)
          → L2 滞回状态机 (armed + confirm_n + deadband)
          → 动作映射 (CLOSE / REDUCE / HOLD)
          → reduce_frac 线性插值 (base=0.30, max=0.70)
```

### 9.3 三种评估模式

| 模式 | 说明 | 输入 |
|---|---|---|
| HEURISTIC | 纯启发式（默认） | 基础技术指标 |
| MRD | MRD概率调整 | + p_mrd（方向共振评分） |
| ML | 模型 p_tail/p_move 融合 | + p_tail（尾部风险概率） |

### 9.4 L2 滞回状态机

```python
# 阈值 + 死区 + 确认计数
close_thr  = 0.75 + regime_shift
reduce_thr = 0.55 + regime_shift
deadband   = 0.03

# 滞回：armed 状态需回落到 exit_thr 才解除
if risk >= close_thr:
    close_armed = True
    close_confirm += 1
elif risk <= close_thr - deadband:
    close_armed = False
    close_confirm = 0

# 动作触发需 confirm_n 次连续确认
if close_armed and close_confirm >= confirm_n:
    action = CLOSE
```

### 9.5 核心配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| l2_close_threshold | 0.75 | 平仓阈值 |
| l2_reduce_threshold | 0.55 | 减仓阈值 |
| l2_deadband | 0.03 | 死区宽度 |
| l2_confirm_n | 1 | 确认次数 |
| l2_reduce_base_frac | 0.30 | 基础减仓比例 |
| l2_reduce_max_frac | 0.70 | 最大减仓比例 |
| l2_reduce_risk_span | 0.20 | 减仓线性插值跨度 |
| mrd_p_low / p_high | 0.40 / 0.60 | MRD概率阈值 |
| mrd_risk_up / down | 0.10 / 0.06 | MRD风险调整幅度 |
| ml_blend_h | 0.25 | ML启发式融合权重 |
| risk_budget_len | 12 | dd快照窗口 |
| risk_budget_dd | 0.35 | 风险预算归一化基准 |
| risk_budget_risk_up | 0.15 | 风险预算最大惩罚 |

### 9.6 使用示例

```python
from risk_engine import RiskEngine, PositionState, Direction, ExitFeatureSet, L1Mode

engine = RiskEngine({"l1": {"l2_close_threshold": 0.75}})

position = PositionState(coin="BTC", side=Direction.LONG, entry_price=50000, current_price=51000)
features = ExitFeatureSet.from_market_data(
    rsi=65, macd_hist=-0.005, adx=20, atr_pct=0.025, dd=0.15, chop=60
)

# 启发式模式
result = engine.assess_value_risk(position, features, L1Mode.HEURISTIC)
print(f"hold_risk={result.hold_risk:.3f}, action={result.action}")

# ML模式（需先加载模型）
features.p_tail = 0.8  # 外部注入ML概率
result = engine.assess_value_risk(position, features, L1Mode.ML)
```

---

## 10. ML 风控模型集成（v1.1 新增）

### 10.1 概述

ML 模型集成框架支持加载和推理多种模型类型，为 L1 评估提供 `p_tail` / `p_move` 概率。

### 10.2 支持的模型类型

| 类型 | 说明 | 加载方式 |
|---|---|---|
| sklearn_pickle | sklearn 模型 (lr/rf/xgb) | `pickle.load` → `predict_proba` |
| xgb | XGBoost Booster | `Booster.load_model` → `DMatrix.predict` |
| committee | 多模型加权集成 | 多个子模型加权平均 |

### 10.3 模型加载

```python
# 从 meta JSON 加载（与 committee_meta.json 格式对齐）
engine.load_ml_model("tail", "path/to/tail_meta.json")

# 加载 Committee
engine.load_ml_committee("committee", [
    ("path/to/tail_meta.json", 0.6),
    ("path/to/move_meta.json", 0.4),
])

# 预测
pred = engine.ml_predict("tail", {"feat1": 0.5, "feat2": 0.3})
print(pred.p_tail, pred.confidence)
```

### 10.4 meta JSON 格式

```json
{
    "model_type": "xgb",
    "model_path": "/path/to/model.xgb",
    "feature_names": ["feat1", "feat2", ...],
    "latest_version": 1
}
```

---

## 11. 飞书告警通知（v1.1 新增）

### 11.1 概述

风控事件触发时，通过飞书发送告警通知。支持 Webhook 和 OpenAPI 两种模式。

### 11.2 告警级别

| 级别 | 颜色 | 说明 |
|---|---|---|
| INFO | 蓝色 | 信息通知 |
| WARNING | 黄色 | 警告 |
| CRITICAL | 红色 | 严重告警 |

### 11.3 告警类别

| 类别 | 说明 | 默认级别 |
|---|---|---|
| GATE_BLOCK | 门禁阻断 | CRITICAL |
| GATE_DEGRADE | 门禁降级 | WARNING |
| EXIT_TRIGGER | 离场触发 | WARNING/CRITICAL |
| DRAWDOWN | 回撤告警 | WARNING/CRITICAL |
| CONSECUTIVE_LOSS | 连续亏损 | WARNING/CRITICAL |
| ML_MODEL | ML模型异常 | WARNING |
| SYSTEM | 系统通知 | INFO |

### 11.4 配置

```python
engine = RiskEngine({
    "alert": {
        "mode": "webhook",               # webhook | openapi | file
        "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
        "min_level": "warning",          # 最低发送级别
        "rate_limit_sec": 60,            # 同类告警限频（秒）
        "log_file": "logs/risk_alert.log",
    }
})
```

### 11.5 使用示例

```python
from risk_engine import AlertEvent, AlertLevel, AlertCategory

# 直接发送告警
engine.alert(AlertEvent(
    level=AlertLevel.CRITICAL,
    category=AlertCategory.GATE_BLOCK,
    title="日回撤熔断",
    message="日回撤 12% 超过熔断阈值 10%",
    coin="BTC",
    details={"drawdown": "12%", "threshold": "10%"},
))

# 便捷方法
engine.alert_notifier.alert_gate_block("BTC", "回撤熔断", {"dd": "12%"})
engine.alert_notifier.alert_drawdown(0.12, 0.10)
engine.alert_notifier.alert_consecutive_loss(6, 5)

# 查看告警历史
history = engine.get_alert_history(limit=20)
```

### 11.6 OpenAPI 模式

OpenAPI 模式自动复用 `6-TRADING/scripts/feishu_notify.py` 的接口，推送到风控群（`risk` channel）。

```python
engine = RiskEngine({
    "alert": {
        "mode": "openapi",
        "feishu_channel": "risk",
        "min_level": "warning",
    }
})
```

---

## 12. 后续扩展方向

- ~~L1 价值-风险评估~~ ✅ v1.1 已实现
- ~~机器学习风控~~ ✅ v1.1 已实现
- ~~实时告警~~ ✅ v1.1 已实现
- **多账户风控**：支持多账户、多交易所的统一风控
- **风控仪表盘**：可视化风控状态、规则触发统计
- **回测集成**：在回测引擎中统一使用风控引擎
- **ML 模型训练**：端到端的 p_tail/p_move 模型训练流水线
