# 接口规格文档 — 通用风控引擎

> **定位：** 全部公开类与函数的签名、参数、返回值、调用示例
> **版本：** v1.1.0 | **更新：** 2026-07-25

---

## 目录

- [1. 接口概览](#1-接口概览)
- [2. 认证方式](#2-认证方式)
- [3. 接口详情](#3-接口详情)
  - [3.1 RiskEngine 核心API (core/engine.py)](#31-riskengine-核心api-coreenginepy)
  - [3.2 数据结构 (core/context.py)](#32-数据结构-corecontextpy)
  - [3.3 规则注册表 API (core/registry.py)](#33-规则注册表-api-coreregistrypy)
  - [3.4 L1 价值-风险评估 API (core/l1_assessor.py)](#34-l1-价值-风险评估-api-corel1_assessorpy)
  - [3.5 ML 风控模型 API (core/ml_model.py)](#35-ml-风控模型-api-coreml_modelpy)
  - [3.6 告警通知 API (core/alert.py)](#36-告警通知-api-corealertpy)
  - [3.7 默认规则清单 (rules/)](#37-默认规则清单-rules)
- [4. 错误码](#4-错误码)
- [5. 版本管理](#5-版本管理)

---

## 1. 接口概览

通用风控引擎采用 **纯 SDK 设计**，无 HTTP 路由、无独立 CLI，通过 Python 包导入集成：

```python
from risk_engine import RiskEngine
```

### 1.1 公开类列表

| 类名 | 模块路径 | 说明 |
|------|----------|------|
| `RiskEngine` | core/engine.py | 统一入口，整合三层风控 + L1 + ML + 告警 |
| `RiskContext` | core/context.py | 风控上下文，全局状态的单一真相源 |
| `PositionState` | core/context.py | 持仓状态 |
| `MarketSnapshot` | core/context.py | 市场快照 |
| `Signal` | core/context.py | 交易信号 |
| `RuleRegistry` | core/registry.py | 规则注册表 |
| `L1ValueRiskAssessor` | core/l1_assessor.py | L1 价值-风险评估器 |
| `ExitFeatureSet` | core/l1_assessor.py | 离场特征集 |
| `L1Mode` | core/l1_assessor.py | L1 评估模式枚举 |
| `L2HysteresisState` | core/l1_assessor.py | L2 滞回状态机 |
| `MLRiskModel` | core/ml_model.py | ML 风控模型适配器 |
| `CommitteeModel` | core/ml_model.py | Committee 多模型加权集成 |
| `MLModelRegistry` | core/ml_model.py | ML 模型注册表 |
| `ModelPrediction` | core/ml_model.py | 模型预测结果 |
| `RiskAlertNotifier` | core/alert.py | 风控告警通知器 |
| `AlertEvent` | core/alert.py | 告警事件 |
| `AlertLevel` | core/alert.py | 告警级别枚举 |
| `AlertCategory` | core/alert.py | 告警类别枚举 |

### 1.2 辅助数据结构（core/context.py）

| 类名 | 说明 |
|------|------|
| `Direction` | 交易方向枚举 (LONG / SHORT) |
| `ExitAction` | 离场动作枚举 (CLOSE / REDUCE / HOLD / RAISE_TP) |
| `ExitPriority` | 离场优先级枚举 (P0_L0_HARD / P1_VALUE_RISK / P2_TRIPLE_BARRIER / P3_BEHAVIORAL) |
| `RiskLevel` | 风险等级枚举 (CRITICAL / HIGH / MEDIUM / LOW / NORMAL) |
| `ReasonCode` | 理由码枚举（与知识库风控体系.md 对齐） |
| `RiskCheckResult` | 风控检查结果 |
| `PositionSizeResult` | 仓位计算结果 |
| `ExitResult` | 离场决策结果 |

### 1.3 RiskEngine 方法速查

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `register_default_rules()` | - | 注册 17 条默认规则（门禁7 + 仓位3 + 离场7） |
| `pre_trade_check(signal, context, extra)` | `RiskCheckResult` | 事前风控检查 |
| `calculate_position(signal, context, modifier, extra)` | `PositionSizeResult` | 仓位计算 |
| `check_exit(position, market, context, extra)` | `ExitResult` | 离场决策 |
| `full_pre_trade(signal, context, extra)` | `dict` | 完整事前流程（门禁 + 仓位） |
| `assess_value_risk(position, features, l1_mode)` | `L1AssessmentResult` | L1 价值-风险评估 |
| `load_ml_model(name, meta_path)` | `bool` | 加载 ML 模型 |
| `load_ml_committee(name, members)` | `bool` | 加载 Committee 模型 |
| `ml_predict(model_name, features)` | `ModelPrediction` | ML 模型预测 |
| `list_ml_models()` | `dict` | 列出所有 ML 模型 |
| `alert(event)` | `bool` | 发送告警 |
| `get_alert_history(limit)` | `list` | 获取告警历史 |
| `register_rule(name, category, handler, priority, description)` | - | 注册自定义规则 |
| `enable_rule(name)` / `disable_rule(name)` | `bool` | 启用/禁用规则 |
| `list_rules()` | `dict` | 列出所有规则 |
| `get_status(context)` | `dict` | 获取风控状态概览 |

---

## 2. 认证方式

**无需认证（SDK 集成）**。

通用风控引擎为纯 Python SDK，零外部依赖（仅 Python 标准库），通过进程内导入使用，不涉及 HTTP 鉴权、Token 或 API Key。

### 2.1 集成方式

```python
# 1. 将 13-通用风控模块 加入 sys.path，或安装为本地包
# 2. 导入统一入口
from risk_engine import RiskEngine, RiskContext, Signal, Direction

engine = RiskEngine({"gate": {"max_daily_drawdown_pct": 0.10}})
engine.register_default_rules()
```

### 2.2 可选外部凭证（仅告警 OpenAPI 模式）

当使用飞书 OpenAPI 告警模式时，需复用 `6-TRADING/scripts/feishu_notify.py` 的应用凭证（由该模块自行管理），风控引擎本身不持有任何密钥。

---

## 3. 接口详情

### 3.1 RiskEngine 核心API (core/engine.py)

#### 3.1.1 RiskEngine.__init__

```python
def __init__(self, config: Optional[Dict[str, Any]] = None)
```

初始化风控引擎，整合三层风控体系 + L1 评估器 + ML 注册表 + 告警通知器。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| config | Dict[str, Any] | None | 全局配置，支持 `gate` / `position` / `exit` / `l1` / `alert` 子键 |

**内部组件：**
- `registry`: `RuleRegistry` — 规则注册表
- `pre_trade_gate`: `PreTradeGate` — 事前门禁层
- `position_sizer`: `PositionSizer` — 仓位管理层
- `exit_engine`: `ExitEngine` — 事后离场层
- `l1_assessor`: `L1ValueRiskAssessor` — L1 评估器
- `ml_registry`: `MLModelRegistry` — ML 模型注册表
- `alert_notifier`: `RiskAlertNotifier` — 告警通知器

**调用示例：**

```python
engine = RiskEngine({
    "gate": {
        "daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.10},
        "concurrent_position_limit": {"max_concurrent_positions": 5},
        "confidence_minimum": {"confidence_hard_min": 0.2, "confidence_soft_min": 0.4},
    },
    "position": {"risk_per_trade_pct": 0.02, "max_position_pct": 0.25},
    "exit": {
        "max_loss_stop": {"max_loss_pct": 0.10},
        "stop_loss_barrier": {"stop_method": "pct", "stop_loss_pct": 0.03},
    },
    "l1": {"l2_close_threshold": 0.75, "l2_reduce_threshold": 0.55},
    "alert": {"mode": "webhook", "webhook_url": "https://open.feishu.cn/..."},
})
```

---

#### 3.1.2 register_default_rules

```python
def register_default_rules(self)
```

注册所有默认风控规则（共 17 条：门禁 7 + 仓位 3 + 离场 7）。幂等，重复调用不会重复注册。

---

#### 3.1.3 pre_trade_check

```python
def pre_trade_check(
    self,
    signal: Signal,
    context: RiskContext,
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult
```

事前风控检查 — 执行所有事前门禁规则，决定是否允许开仓。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| signal | Signal | 交易信号 |
| context | RiskContext | 风控上下文 |
| extra | Dict[str, Any] | 额外参数（如 `leverage`） |

**返回值：** `RiskCheckResult`（见 [3.2.7](#327-riskcheckresult)）

**执行机制：**
- 按优先级从小到大顺序执行
- 遇到 `passed=False` 立即返回（短路）
- 降级规则累积 `position_modifier` 乘积

**调用示例：**

```python
result = engine.pre_trade_check(signal, context)
if result.passed:
    print(f"通过，仓位系数×{result.position_modifier}")
else:
    print(f"拒绝：{result.reason_code.value} - {result.message}")
```

---

#### 3.1.4 calculate_position

```python
def calculate_position(
    self,
    signal: Signal,
    context: RiskContext,
    position_modifier: float = 1.0,
    extra: Optional[Dict[str, Any]] = None,
) -> PositionSizeResult
```

计算仓位大小 — 根据风险预算、置信度、波动率等计算合适的仓位。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| signal | Signal | - | 交易信号 |
| context | RiskContext | - | 风控上下文 |
| position_modifier | float | 1.0 | 仓位调整系数（来自门禁降级） |
| extra | Dict[str, Any] | None | 额外参数（如 `atr_pct`） |

**返回值：** `PositionSizeResult`（见 [3.2.8](#328-positionsizeresult)）

---

#### 3.1.5 check_exit

```python
def check_exit(
    self,
    position: PositionState,
    market: Optional[MarketSnapshot] = None,
    context: Optional[RiskContext] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ExitResult
```

离场决策检查 — 对持仓进行离场决策，返回最高优先级的离场动作。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| position | PositionState | - | 持仓状态 |
| market | MarketSnapshot | None | 市场快照 |
| context | RiskContext | None | 风控上下文 |
| extra | Dict[str, Any] | None | 额外参数 |

**返回值：** `ExitResult`（见 [3.2.9](#329-exitresult)）

**执行机制：**
- 按优先级 P0 → P3 顺序检查
- 返回最高优先级的离场动作
- P0 触发后立即返回（一票否决）

---

#### 3.1.6 full_pre_trade

```python
def full_pre_trade(
    self,
    signal: Signal,
    context: RiskContext,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]
```

完整的事前风控流程 — 一次性执行事前门禁检查和仓位计算。

**返回值：**

```python
{
    "check": RiskCheckResult,            # 始终返回
    "position": PositionSizeResult,      # 仅当 check.passed 时返回
}
```

**调用示例：**

```python
result = engine.full_pre_trade(signal, context)
if result["check"].passed:
    size = result["position"]
    print(f"开仓: {size.base_size_usdt:.2f} USDT")
```

---

#### 3.1.7 assess_value_risk

```python
def assess_value_risk(
    self,
    position: PositionState,
    features: ExitFeatureSet,
    l1_mode: L1Mode = L1Mode.HEURISTIC,
) -> L1AssessmentResult
```

L1 价值-风险评估 — 对持仓进行 `hold_risk` / `hold_value` 评估，输出离场动作建议。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| position | PositionState | - | 持仓状态 |
| features | ExitFeatureSet | - | 离场特征集 |
| l1_mode | L1Mode | HEURISTIC | 评估模式 (HEURISTIC / MRD / ML) |

**返回值：** `L1AssessmentResult`（见 [3.4.5](#345-l1assessmentresult)）

**副作用：** 当 `action ∈ {close, reduce}` 时，自动触发 `alert_exit_trigger` 告警。

**调用示例：**

```python
from risk_engine import ExitFeatureSet, L1Mode

features = ExitFeatureSet.from_market_data(rsi=65, macd_hist=-0.005, adx=20, atr_pct=0.025, dd=0.15)
result = engine.assess_value_risk(position, features, L1Mode.HEURISTIC)
print(f"hold_risk={result.hold_risk:.3f}, action={result.action}, reduce_frac={result.reduce_frac:.2f}")
```

---

#### 3.1.8 load_ml_model / load_ml_committee

```python
def load_ml_model(self, name: str, meta_path: str) -> bool
def load_ml_committee(self, name: str, members: list) -> bool
```

加载 ML 模型 / Committee 模型。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| name | str | 模型注册名称 |
| meta_path | str | meta JSON 文件路径 |
| members | list | `[(meta_path, weight), ...]` 子模型列表 |

**返回值：** `bool` — 是否加载成功

**meta JSON 格式：**

```json
{
    "model_type": "xgb",
    "model_path": "/path/to/model.xgb",
    "feature_names": ["feat1", "feat2"],
    "latest_version": 1
}
```

---

#### 3.1.9 ml_predict

```python
def ml_predict(self, model_name: str, features: Dict[str, float]) -> ModelPrediction
```

ML 模型预测。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| model_name | str | 已注册的模型名称 |
| features | Dict[str, float] | 特征字典 `{feature_name: value}` |

**返回值：** `ModelPrediction`（见 [3.5.4](#354-modelprediction)）

---

#### 3.1.10 list_ml_models

```python
def list_ml_models(self) -> Dict[str, Any]
```

列出所有已注册 ML 模型。

**返回值：**

```python
{
    "tail": {"type": "MLRiskModel", "loaded": True, "name": "tail"},
    "committee": {"type": "CommitteeModel", "loaded": True, "name": "committee", "members": 2}
}
```

---

#### 3.1.11 alert / get_alert_history

```python
def alert(self, event: AlertEvent) -> bool
def get_alert_history(self, limit: int = 50) -> list
```

发送告警 / 获取告警历史。

**返回值：**
- `alert`: `bool` — 是否发送成功（受级别过滤与限频约束）
- `get_alert_history`: `list[Dict]` — 告警历史记录

---

#### 3.1.12 register_rule / enable_rule / disable_rule

```python
def register_rule(
    self,
    name: str,
    category: str,
    handler: Callable,
    priority: int = 100,
    description: str = "",
)

def enable_rule(self, name: str) -> bool
def disable_rule(self, name: str) -> bool
```

注册自定义规则 / 启用 / 禁用规则。

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| name | str | 规则唯一名称 |
| category | str | 规则类别：`'gate'` / `'position'` / `'exit'` |
| handler | Callable | 规则处理函数 |
| priority | int | 优先级（数字越小越先执行，默认 100） |
| description | str | 规则描述 |

**异常：** `category` 无效时抛出 `ValueError`。

---

#### 3.1.13 list_rules

```python
def list_rules(self) -> Dict[str, List[Dict[str, Any]]]
```

列出所有规则，按类别分组。

**返回值：**

```python
{
    "gate": [
        {"name": "daily_drawdown_circuit_breaker", "priority": 5, "enabled": True, "description": "..."},
        ...
    ],
    "position": [...],
    "exit": [...],
}
```

---

#### 3.1.14 get_status

```python
def get_status(self, context: RiskContext) -> Dict[str, Any]
```

获取风控状态概览。

**返回值：**

```python
{
    "total_equity": 10000.0,
    "daily_pnl": 0.0,
    "daily_drawdown_pct": 0.0,
    "consecutive_losses": 0,
    "active_positions": 0,
    "win_rate": 0.0,
    "total_trades": 0,
    "rules_count": 17,
    "gate_rules": 7,
    "position_rules": 3,
    "exit_rules": 7,
    "ml_models": {...},
    "alert_count": 0,
}
```

---

### 3.2 数据结构 (core/context.py)

#### 3.2.1 Signal

```python
@dataclass
class Signal:
    coin: str
    direction: Direction
    confidence: float = 0.5
    strategy: str = ""
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
```

交易信号。

---

#### 3.2.2 PositionState

```python
@dataclass
class PositionState:
    coin: str
    side: Direction
    entry_price: float = 0.0
    current_price: float = 0.0
    position_size: float = 0.0
    position_age_sec: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    leverage: float = 1.0
    atr_pct: float = 0.02
    mfe_pnl_pct: float = 0.0
    max_dd_pct: float = 0.0
    entry_ts: int = 0
    trailing_armed: bool = False
    trailing_stop_price: float = 0.0
    liq_price: float = 0.0
    addon_count: int = 0
    max_addons: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)
```

持仓状态。

**属性：**

| 属性 | 类型 | 说明 |
|------|------|------|
| `pnl_eff` | float | 含杠杆的有效收益率 = `unrealized_pnl_pct × leverage` |
| `is_long` | bool | 是否多头 |

---

#### 3.2.3 MarketSnapshot

```python
@dataclass
class MarketSnapshot:
    coin: str
    price: float = 0.0
    rsi: float = 50.0
    macd_hist: float = 0.0
    atr_pct: float = 0.02
    volume_24h: float = 0.0
    trend: str = "neutral"
    volatility: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
```

市场快照。

---

#### 3.2.4 RiskContext

```python
class RiskContext:
    def __init__(
        self,
        total_equity: float = 0.0,
        available_balance: float = 0.0,
        used_margin: float = 0.0,
        daily_pnl: float = 0.0,
        daily_start_equity: Optional[float] = None,
        max_daily_equity: Optional[float] = None,
        consecutive_losses: int = 0,
        total_trades: int = 0,
        total_wins: int = 0,
        positions: Optional[Dict[str, PositionState]] = None,
        trade_history: Optional[List[Dict[str, Any]]] = None,
    )
```

风控上下文 — 全局风控状态的单一真相源。

**属性：**

| 属性 | 类型 | 说明 |
|------|------|------|
| `total_equity` | float | 总权益 |
| `available_balance` | float | 可用余额 |
| `used_margin` | float | 已用保证金 |
| `daily_pnl` | float | 日盈亏 |
| `daily_start_equity` | float | 日初权益 |
| `max_daily_equity` | float | 日最高权益 |
| `consecutive_losses` | int | 连续亏损次数 |
| `total_trades` | int | 总交易数 |
| `total_wins` | int | 胜数 |
| `positions` | Dict[str, PositionState] | 当前持仓字典 |
| `trade_history` | List[Dict] | 交易历史 |
| `daily_drawdown_pct` | float | 当日回撤百分比（相对于日最高权益） |
| `daily_return_pct` | float | 当日收益率（相对于日初权益） |
| `win_rate` | float | 胜率 |
| `active_positions_count` | int | 活跃持仓数量 |

**方法：**

| 方法 | 说明 |
|------|------|
| `update_equity(total_equity, available_balance=None)` | 更新账户权益 |
| `add_position(position)` | 添加持仓 |
| `remove_position(coin)` | 移除持仓 |
| `record_trade(trade)` | 记录交易，更新统计 |
| `reset_daily(new_start_equity=None)` | 重置日度数据 |
| `to_dict()` | 序列化为字典 |

---

#### 3.2.5 Direction / ExitAction / ExitPriority / RiskLevel

```python
class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"

class ExitAction(str, Enum):
    CLOSE = "close"
    REDUCE = "reduce"
    HOLD = "hold"
    RAISE_TP = "raise_tp"   # 提高止盈价（强反弹时让利润奔跑）

class ExitPriority(str, Enum):
    P0_L0_HARD = "p0_l0"              # 安全硬退出
    P1_VALUE_RISK = "p1"              # 价值-风险评估
    P2_TRIPLE_BARRIER = "p2"          # 三重屏障
    P3_BEHAVIORAL = "p3"              # 行为约束

class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NORMAL = "normal"
```

---

#### 3.2.6 ReasonCode

见 [4. 错误码](#4-错误码)。

---

#### 3.2.7 RiskCheckResult

```python
@dataclass
class RiskCheckResult:
    passed: bool
    reason_code: ReasonCode = ReasonCode.PASS
    risk_level: RiskLevel = RiskLevel.NORMAL
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    position_modifier: float = 1.0
```

风控检查结果。

**工厂方法：**

| 方法 | 说明 |
|------|------|
| `pass_result(message="")` | 通过结果 |
| `fail_result(reason_code, message="")` | 失败结果（risk_level=HIGH） |
| `degrade_result(reason_code, modifier, message="")` | 降级结果（passed=True，risk_level=MEDIUM，position_modifier=modifier） |

---

#### 3.2.8 PositionSizeResult

```python
@dataclass
class PositionSizeResult:
    base_size_usdt: float = 0.0
    base_size_coins: float = 0.0
    risk_per_trade_usdt: float = 0.0
    max_addons: int = 0
    addon_sizes: List[float] = field(default_factory=list)
    position_tier: str = "trial"
    leverage: float = 1.0
    details: Dict[str, Any] = field(default_factory=dict)
```

仓位计算结果。

---

#### 3.2.9 ExitResult

```python
@dataclass
class ExitResult:
    action: ExitAction = ExitAction.HOLD
    priority: ExitPriority = ExitPriority.P3_BEHAVIORAL
    reason: str = ""
    reduce_frac: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
```

离场决策结果。

---

### 3.3 规则注册表 API (core/registry.py)

#### 3.3.1 RuleCategory

```python
class RuleCategory(str, Enum):
    GATE = "gate"
    POSITION = "position"
    EXIT = "exit"
```

---

#### 3.3.2 RuleInfo

```python
@dataclass
class RuleInfo:
    name: str
    category: RuleCategory
    priority: int = 100
    description: str = ""
    enabled: bool = True
    config_schema: Dict[str, Any] = field(default_factory=dict)
```

规则元信息。

---

#### 3.3.3 RuleRegistry

```python
class RuleRegistry:
    def __init__(self)
```

风控规则注册表。

**核心方法：**

| 方法 | 说明 |
|------|------|
| `register(name, category, handler, priority=100, description="", config_schema=None) -> RuleInfo` | 注册规则（重名抛 `ValueError`） |
| `register_gate(name, priority=100, description="", **kwargs)` | 门禁规则装饰器 |
| `register_position(name, priority=100, description="", **kwargs)` | 仓位规则装饰器 |
| `register_exit(name, priority=100, description="", **kwargs)` | 离场规则装饰器 |
| `unregister(name) -> bool` | 注销规则 |
| `get_handler(name) -> Optional[Callable]` | 获取处理函数 |
| `get_rule(name) -> Optional[RuleInfo]` | 获取规则元信息 |
| `get_rules(category=None) -> List[RuleInfo]` | 获取规则列表（按优先级排序） |
| `get_enabled_rules(category=None) -> List[RuleInfo]` | 获取启用的规则列表 |
| `enable(name) -> bool` / `disable(name) -> bool` | 启用/禁用规则 |
| `execute_chain(category, *args, config=None, stop_on_fail=True, **kwargs) -> List[Any]` | 链式执行规则 |
| `list_all() -> Dict[str, List[Dict[str, Any]]]` | 列出所有规则（按类别分组） |
| `__len__()` / `__contains__(name)` | 规则数量 / 是否存在 |

**装饰器使用示例：**

```python
registry = RuleRegistry()

@registry.register_gate("my_rule", priority=15)
def my_rule(signal, context, config, extra=None):
    return RiskCheckResult.pass_result()
```

---

### 3.4 L1 价值-风险评估 API (core/l1_assessor.py)

#### 3.4.1 L1Mode

```python
class L1Mode(str, Enum):
    HEURISTIC = "heuristic"   # 纯启发式（默认）
    MRD = "mrd"               # MRD 概率调整
    ML = "ml"                 # 模型 p_tail/p_move 融合
```

---

#### 3.4.2 TrendShape

```python
class TrendShape(str, Enum):
    UP_STRONG = "up_strong"
    UP_REVERSAL = "up_reversal"
    DOWN_STRONG = "down_strong"
    DOWN_REVERSAL = "down_reversal"
    CHOP = "chop"
```

趋势形态（5 类）。

---

#### 3.4.3 ExitFeatureSet

```python
@dataclass
class ExitFeatureSet:
    # 持仓状态
    dd: float = 0.0
    mfe: float = 0.0
    # 基础技术指标
    rsi: float = 50.0
    macd_hist: float = 0.0
    adx: float = 25.0
    atr_pct: float = 0.02
    ema_short_dist: float = 0.0
    chop: float = 50.0
    # 时间纬度
    trend_shape: TrendShape = TrendShape.CHOP
    trend_w_dir: int = 0
    trend_d_dir: int = 0
    # 动能因子
    mom_dir: int = 0
    mom_chg_dir: int = 0
    mom_rsi_delta: float = 0.0
    mom_macdh_delta: float = 0.0
    # 量能因子
    vol_dir: int = 0
    vol_chg_dir: int = 0
    vol_z: float = 0.0
    vol_ratio_delta: float = 0.0
    # 势能因子
    pot_dir: int = 0
    pot_chg_dir: int = 0
    pot_adx_delta: float = 0.0
    pot_dist_to_ema50: float = 0.0
    # 资金流向
    flow_dir: int = 0
    macro_flow_dir: int = 0
    # ML 概率（外部注入）
    p_tail: Optional[float] = None
    p_move: Optional[float] = None
    # Regime
    regime: str = ""
```

离场特征集 — L1 评估的输入。

**工厂方法：**

```python
@classmethod
def from_market_data(
    cls,
    rsi: float = 50.0,
    macd_hist: float = 0.0,
    adx: float = 25.0,
    atr_pct: float = 0.02,
    chop: float = 50.0,
    ema_short_dist: float = 0.0,
    dd: float = 0.0,
    mfe: float = 0.0,
    trend_shape: str = "chop",
    trend_w_dir: int = 0,
    trend_d_dir: int = 0,
    mom_dir: int = 0,
    mom_rsi_delta: float = 0.0,
    mom_macdh_delta: float = 0.0,
    vol_dir: int = 0,
    vol_z: float = 0.0,
    vol_ratio_delta: float = 0.0,
    pot_adx_delta: float = 0.0,
    pot_dist_to_ema50: float = 0.0,
    regime: str = "",
    p_tail: Optional[float] = None,
    p_move: Optional[float] = None,
) -> "ExitFeatureSet"
```

从市场数据构建特征集（`trend_shape` 非法时回退为 `CHOP`）。

---

#### 3.4.4 L2HysteresisState

```python
@dataclass
class L2HysteresisState:
    close_armed: bool = False
    close_confirm_count: int = 0
    reduce_armed: bool = False
    reduce_confirm_count: int = 0
    last_risk: float = 0.0
    last_update_ts: int = 0
```

L2 滞回状态机 — per-coin 持久化。

---

#### 3.4.5 L1AssessmentResult

```python
@dataclass
class L1AssessmentResult:
    hold_risk: float = 0.5
    hold_value: float = 0.5
    mrd_score: float = 0.0
    p_mrd: float = 0.5
    p_tail: Optional[float] = None
    p_move: Optional[float] = None
    model_conf: float = 0.0
    risk_budget_penalty: float = 0.0
    regime_shift: float = 0.0
    action: str = "hold"          # "close" | "reduce" | "hold"
    reduce_frac: float = 0.0
    confidence: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
```

L1 评估结果（由 `L1ValueRiskAssessor.assess` 返回）。

---

#### 3.4.6 L1ValueRiskAssessor

```python
class L1ValueRiskAssessor:
    def __init__(self, config: Optional[Dict[str, Any]] = None)

    def assess(
        self,
        position: Any,
        features: ExitFeatureSet,
        l2_state: Optional[L2HysteresisState] = None,
        l1_mode: L1Mode = L1Mode.HEURISTIC,
        snapshot_history: Optional[List[Dict[str, Any]]] = None,
    ) -> L1AssessmentResult
```

L1 价值-风险评估器。

**计算链路：**

```
[基础指标] → hold_risk 加权（10 维，dd_risk 主导 0.42 权重）
          → MRD 调整（p_mrd < 0.40 加风险 / > 0.60 减风险）
          → ML 调整（p_tail 启发式融合，blend_h=0.25）
          → 风险预算惩罚（序列 dd 增量归一化 × 0.15）
          → clip[0,1] = final hold_risk
          → hold_value = 1 - hold_risk
          → Regime 偏移（震荡市 +0.05, 低 ADX +0.03）
          → L2 滞回状态机（armed + confirm_n + deadband）
          → 动作映射 (CLOSE / REDUCE / HOLD)
          → reduce_frac 线性插值（base=0.30, max=0.70）
```

**核心配置项：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `l2_close_threshold` | 0.75 | 平仓阈值 |
| `l2_reduce_threshold` | 0.55 | 减仓阈值 |
| `l2_deadband` | 0.03 | 死区宽度 |
| `l2_confirm_n` | 1 | 确认次数 |
| `l2_reduce_base_frac` | 0.30 | 基础减仓比例 |
| `l2_reduce_max_frac` | 0.70 | 最大减仓比例 |
| `l2_reduce_risk_span` | 0.20 | 减仓线性插值跨度 |
| `l2_reduce_min_profit_pct` | 0.01 | 减仓最小盈利要求 |
| `l2_low_value_threshold` | 0.30 | 低价值阈值 |
| `mrd_p_low` / `mrd_p_high` | 0.40 / 0.60 | MRD 概率阈值 |
| `mrd_risk_up` / `mrd_risk_down` | 0.10 / 0.06 | MRD 风险调整幅度 |
| `mrd_min_model_conf` | 0.25 | MRD 最小置信度 |
| `ml_blend_h` | 0.25 | ML 启发式融合权重 |
| `risk_budget_enabled` | True | 是否启用风险预算 |
| `risk_budget_len` | 12 | dd 快照窗口 |
| `risk_budget_dd` | 0.35 | 风险预算归一化基准 |
| `risk_budget_risk_up` | 0.15 | 风险预算最大惩罚 |
| `regime_chop_shift` | 0.05 | 震荡市阈值偏移 |
| `regime_low_adx_shift` | 0.03 | 低 ADX 阈值偏移 |
| `regime_threshold_shifts` | {} | 按 regime 字段的偏移字典 |

---

### 3.5 ML 风控模型 API (core/ml_model.py)

#### 3.5.1 ModelPrediction

```python
@dataclass
class ModelPrediction:
    p_tail: Optional[float] = None
    p_move: Optional[float] = None
    confidence: float = 0.0
    model_name: str = ""
    model_version: str = ""
    raw_output: Any = None
    details: Dict[str, Any] = field(default_factory=dict)
```

模型预测结果。

---

#### 3.5.2 MLRiskModel

```python
class MLRiskModel:
    def __init__(
        self,
        model: Any = None,
        model_type: str = "sklearn_pickle",
        feature_names: Optional[List[str]] = None,
        name: str = "",
        version: str = "",
    )

    @classmethod
    def load_from_meta(cls, meta_path: str) -> "MLRiskModel"

    @property
    def is_loaded(self) -> bool

    def predict(self, features: Dict[str, float]) -> ModelPrediction
```

ML 风控模型适配器，支持 `sklearn_pickle` / `xgb` / `committee` 三类模型。

**支持的模型类型：**

| 类型 | 说明 | 加载方式 |
|------|------|----------|
| `sklearn_pickle` | sklearn 模型 (lr / rf / xgb sklearn) | `pickle.load` → `predict_proba` |
| `xgb` | XGBoost Booster | `Booster.load_model` → `DMatrix.predict` |
| `committee` | 多模型加权集成（见 `CommitteeModel`） | 多子模型加权平均 |

---

#### 3.5.3 CommitteeModel

```python
class CommitteeModel:
    def __init__(self, name: str = "committee")

    def add_member(self, model: MLRiskModel, weight: float = 1.0)

    @property
    def is_loaded(self) -> bool

    def predict(self, features: Dict[str, float]) -> ModelPrediction
```

Committee 多模型加权集成 — 加载多个子模型，加权平均后输出 `p_tail` / `p_move`。

---

#### 3.5.4 ModelPrediction

见 [3.5.1](#351-modelprediction)。

---

#### 3.5.5 MLModelRegistry

```python
class MLModelRegistry:
    def __init__(self)

    def load_model(self, name: str, meta_path: str) -> bool
    def load_committee(self, name: str, members: List[tuple]) -> bool
    def register_model(self, name: str, model: Union[MLRiskModel, CommitteeModel])
    def get_model(self, name: str) -> Optional[Union[MLRiskModel, CommitteeModel]]
    def predict(self, name: str, features: Dict[str, float]) -> ModelPrediction
    def list_models(self) -> Dict[str, Dict[str, Any]]
```

ML 模型注册表 — 管理多个风控模型。

**`load_committee` 参数 `members`：** `[(meta_path, weight), ...]`

---

### 3.6 告警通知 API (core/alert.py)

#### 3.6.1 AlertLevel / AlertCategory

```python
class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class AlertCategory(str, Enum):
    GATE_BLOCK = "gate_block"
    GATE_DEGRADE = "gate_degrade"
    EXIT_TRIGGER = "exit_trigger"
    DRAWDOWN = "drawdown"
    CONSECUTIVE_LOSS = "consecutive_loss"
    ML_MODEL = "ml_model"
    SYSTEM = "system"
```

---

#### 3.6.2 AlertEvent

```python
@dataclass
class AlertEvent:
    level: AlertLevel
    category: AlertCategory
    title: str
    message: str
    coin: str = ""
    timestamp: str = ""           # 自动填充为 UTC 时间
    details: Dict[str, Any] = field(default_factory=dict)

    def to_card(self) -> Dict[str, Any]    # 飞书卡片消息
    def to_text(self) -> str               # 纯文本消息
```

告警事件。

**颜色映射：** INFO=blue / WARNING=yellow / CRITICAL=red

---

#### 3.6.3 RiskAlertNotifier

```python
class RiskAlertNotifier:
    def __init__(self, config: Optional[Dict[str, Any]] = None)
```

风控告警通知器，支持三种推送模式。

**配置项：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `mode` | "webhook" | 推送模式：`webhook` / `openapi` / `file` |
| `webhook_url` | "" | 飞书 Webhook 地址 |
| `min_level` | "warning" | 最低发送级别 |
| `rate_limit_sec` | 60 | 同类告警限频（秒） |
| `log_file` | "" | 本地日志文件路径 |
| `feishu_channel` | "risk" | OpenAPI 模式的飞书频道 |

**核心方法：**

| 方法 | 说明 |
|------|------|
| `alert(event: AlertEvent) -> bool` | 发送告警（受级别过滤与限频约束） |
| `get_history(limit=50) -> List[Dict]` | 获取告警历史 |
| `clear_history()` | 清空告警历史与限频状态 |

**便捷方法：**

| 方法 | 说明 |
|------|------|
| `alert_gate_block(coin, reason, details=None, level=CRITICAL)` | 门禁阻断告警 |
| `alert_gate_degrade(coin, reason, modifier, details=None)` | 门禁降级告警（WARNING） |
| `alert_exit_trigger(coin, action, reason, priority="", details=None)` | 离场触发告警（priority 含 "p0" → CRITICAL） |
| `alert_drawdown(drawdown_pct, threshold_pct, details=None)` | 回撤告警 |
| `alert_consecutive_loss(count, threshold, details=None)` | 连续亏损告警 |

**推送模式：**

| 模式 | 说明 |
|------|------|
| `webhook` | 飞书 Webhook 推送（轻量级，无需应用凭证） |
| `openapi` | 复用 `6-TRADING/scripts/feishu_notify.py`，需应用凭证；模块不可用时自动降级为 webhook |
| `file` | 仅写本地日志文件（兜底） |

**调用示例：**

```python
from risk_engine import RiskAlertNotifier, AlertEvent, AlertLevel, AlertCategory

notifier = RiskAlertNotifier({
    "mode": "webhook",
    "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
    "min_level": "warning",
})

notifier.alert(AlertEvent(
    level=AlertLevel.CRITICAL,
    category=AlertCategory.GATE_BLOCK,
    title="日回撤熔断",
    message="日回撤 12% 超过熔断阈值 10%",
    coin="BTC",
    details={"drawdown": "12%", "threshold": "10%"},
))

# 便捷方法
notifier.alert_drawdown(0.12, 0.10)
notifier.alert_consecutive_loss(6, 5)
```

---

### 3.7 默认规则清单 (rules/)

#### 3.7.1 门禁规则（7 条）

| 规则名称 | 优先级 | 说明 | 默认配置 |
|------|:---:|------|------|
| `daily_drawdown_circuit_breaker` | 5 | 日回撤熔断 (P0 硬阻断) | `max_daily_drawdown_pct=0.10` |
| `leverage_cap_check` | 10 | 杠杆上限检查 (P0 硬阻断) | `max_leverage=10.0` |
| `concurrent_position_limit` | 20 | 并发仓位限制 | `max_concurrent_positions=5` |
| `consecutive_losses_limit` | 25 | 连续亏损限制 | `max_consecutive_losses=5` |
| `blackout_period_check` | 30 | 黑窗时段检查 | `blackout_windows=[]` |
| `confidence_minimum` | 50 | 最低置信度检查 | `confidence_hard_min=0.2`, `confidence_soft_min=0.4` |
| `drawdown_warning_degrade` | 60 | 回撤警告降级 | `drawdown_warn_1=0.05`, `drawdown_warn_2=0.08` |

**规则处理函数签名：**

```python
def gate_rule(
    signal: Signal,
    context: RiskContext,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> RiskCheckResult
```

---

#### 3.7.2 仓位规则（3 条）

| 规则名称 | 优先级 | 说明 | 默认配置 |
|------|:---:|------|------|
| `confidence_based_adjustment` | 10 | 置信度仓位调整 | `high_conf_multiplier=1.2`, `low_conf_multiplier=0.5` |
| `volatility_based_adjustment` | 20 | 波动率仓位调整 | `baseline_atr_pct=0.02` |
| `max_position_cap` | 90 | 最大仓位限制 | `max_position_pct=0.25` |

**规则处理函数签名：**

```python
def position_rule(
    signal: Signal,
    context: RiskContext,
    base_risk: float,
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> PositionRuleResult   # dataclass { adjusted_risk: float, details: Dict }
```

---

#### 3.7.3 离场规则（7 条）

| 规则名称 | 优先级 | 层级 | 说明 | 默认配置 |
|------|:---:|:---:|------|------|
| `max_loss_stop` | 5 | P0 | 最大亏损止损 | `max_loss_pct=0.10` |
| `liquidation_buffer` | 8 | P0 | 强平安全缓冲 | `liquidation_buffer_pct=0.05` |
| `max_hold_time` | 10 | P0 | 最大持仓时间 | `max_hold_sec=604800`（7 天） |
| `stop_loss_barrier` | 20 | P2 | 止损屏障 | `stop_method="atr"`, `atr_stop_multiplier=2.0`, `stop_loss_pct=0.03` |
| `take_profit_barrier` | 25 | P2 | 止盈屏障 | `tp_method="rr"`, `rr_ratio=2.0`, `tp_reduce_frac=0.5` |
| `time_barrier` | 30 | P2 | 时间屏障 | `time_barrier_sec=86400`, `time_barrier_min_profit_pct=0.01` |
| `trailing_stop` | 35 | P3 | 跟踪止损 | `trailing_arm_pct=0.03`, `trailing_pct=0.02` |

**规则处理函数签名：**

```python
def exit_rule(
    position: PositionState,
    market: Optional[MarketSnapshot],
    context: Optional[RiskContext],
    config: Dict[str, Any],
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ExitResult]   # None 表示未触发
```

---

## 4. 错误码

错误码通过 `ReasonCode` 枚举定义，与知识库 `2-KNOWLEDGE/1-TRADING/风控体系.md` 完全对齐。

### 4.1 通过

| 码 | 含义 |
|---|---|
| `PASS` | 风控通过 |

### 4.2 硬阻断（HARD_FAIL_*）

| 码 | 含义 | 触发规则 |
|---|---|---|
| `HARD_FAIL_MISSING_CORE_DATA` | 核心数据缺失 | - |
| `HARD_FAIL_LEVERAGE_EXCEEDS_CAP` | 杠杆超限 | leverage_cap_check |
| `HARD_FAIL_STRATEGY_EXCLUDED` | 战略/币种排除 | strategy_exclusion_check |
| `HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER` | 日回撤熔断 | daily_drawdown_circuit_breaker |
| `HARD_FAIL_DIRECTION_MISMATCH` | 方向不匹配 | - |
| `HARD_FAIL_NO_STRATEGY` | 无策略 | - |
| `HARD_FAIL_SLIPPAGE` | 滑点超限 | - |
| `HARD_FAIL_NEGATIVE_EDGE` | 负期望 | - |
| `HARD_FAIL_BLACKOUT` | 黑窗时段 | blackout_period_check |
| `HARD_FAIL_CONCURRENT_LIMIT` | 并发仓位超限 | concurrent_position_limit |
| `HARD_FAIL_CONSECUTIVE_LOSSES` | 连续亏损超限 | consecutive_losses_limit |

### 4.3 软失败（FAIL_*）

| 码 | 含义 | 触发规则 |
|---|---|---|
| `FAIL_LOW_DIM` | 置信度低于硬阈值 | confidence_minimum |
| `FAIL_LOW_TOTAL` | 综合评分过低 | - |

### 4.4 降级（DEGRADE_*）

| 码 | 含义 | 触发规则 |
|---|---|---|
| `DEGRADE_DREAM_MODE` | 梦模式降级 | - |
| `DEGRADE_STRATEGY_REDUCED_RISK` | 策略降风险 | - |
| `DEGRADE_DRAWDOWN_WARNING` | 回撤警告降级 | drawdown_warning_degrade |

### 4.5 软警告（SOFT_WARN_*）

| 码 | 含义 | 触发规则 |
|---|---|---|
| `SOFT_WARN_STRATEGY_DIRECTS_WAIT` | 策略指示等待 | - |
| `SOFT_WARN_LOW_CONFIDENCE` | 低置信度警告（仓位降级） | confidence_minimum |

### 4.6 异常处理

- 规则处理函数抛异常时，`RuleRegistry.execute_chain` 会捕获并记录 `{"rule_name": ..., "error": str(e)}`，`stop_on_fail=True` 时停止后续规则。
- 默认遵循 **Fail-Closed 原则**：缺失数据或异常时默认拒绝。

---

## 5. 版本管理

### 5.1 版本策略

- 采用 **语义化版本号**：`MAJOR.MINOR.PATCH`（如 `1.1.0`）。
- 当前版本通过 `risk_engine.__version__` 暴露：`"1.1.0"`。
- 向后兼容的规则新增/配置项新增 → MINOR 升级。
- 不兼容的接口变更（签名调整、删除公开类） → MAJOR 升级。
- 文档/测试/缺陷修复 → PATCH 升级。

### 5.2 版本查询

```python
import risk_engine
print(risk_engine.__version__)   # "1.1.0"
```

### 5.3 兼容性承诺

- `RiskEngine` 公开方法签名在 MINOR 版本内保持向后兼容。
- 默认规则名称、优先级在 MINOR 版本内保持稳定。
- 配置项新增不影响旧配置（缺失时使用默认值）。
- 自定义规则处理函数签名保持稳定。

### 5.4 集成方升级路径

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1 (v1.0) | ✅ 已完成 | 三层架构 + 17 条默认规则 |
| Phase 2 (v1.1.0) | ✅ 已完成 | L1 评估 + ML 集成 + 飞书告警 |
| Phase 3 | ⏳ 待办 | 马丁/三屏/经典/易经系统对接 |
| Phase 4 | ⏳ 待办 | ML 训练流水线 / 多账户统一风控 / 风控回测 / 可视化仪表盘 |

### 5.5 测试命令

```bash
# 核心测试（24 个用例）
python -m pytest tests/test_risk_engine.py -v

# 增强测试（27 个用例：L1 / ML / 告警）
python -m pytest tests/test_l1_ml_alert.py -v
```

---

## 调用关系速查

```
策略层
  └─→ RiskEngine.pre_trade_check(signal, context)
        └─→ PreTradeGate.check()
              └─→ RuleRegistry.execute_chain(GATE, ...)
                    └─→ gate_rules.* (7 条，按优先级)

  └─→ RiskEngine.calculate_position(signal, context, modifier)
        └─→ PositionSizer.calculate()
              └─→ RuleRegistry.execute_chain(POSITION, ...)
                    └─→ position_rules.* (3 条)

  └─→ RiskEngine.check_exit(position, market, context)
        └─→ ExitEngine.check()
              └─→ RuleRegistry.execute_chain(EXIT, ...)
                    └─→ exit_rules.* (7 条，P0→P3)

  └─→ RiskEngine.assess_value_risk(position, features, l1_mode)
        └─→ L1ValueRiskAssessor.assess()
              ├─→ _calc_hold_risk (10 维加权)
              ├─→ _calc_mrd_score → MRD 调整
              ├─→ _apply_ml_adjustment (p_tail/p_move)
              ├─→ _calc_risk_budget_penalty
              ├─→ _calc_regime_shift
              ├─→ _evaluate_value_risk (L2 滞回状态机)
              └─→ alert_notifier.alert_exit_trigger (动作触发时)

  └─→ RiskEngine.ml_predict(model_name, features)
        └─→ MLModelRegistry.predict()
              └─→ MLRiskModel.predict() / CommitteeModel.predict()

  └─→ RiskEngine.alert(event)
        └─→ RiskAlertNotifier.alert()
              ├─→ _send_webhook()  (飞书 Webhook)
              ├─→ _send_openapi()  (feishu_notify.py)
              └─→ _log_to_file()   (本地日志)
```

---

_最后更新：2026-07-25 | 来源：13-通用风控模块（risk-engine v1.1.0）_
