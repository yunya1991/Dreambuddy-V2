# 账户资金调控通用组件设计文档

> **定位：** 16-调控系统 L1.5 资金调控层核心组件设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.3
> **版本：** v1.0 | **创建日期：** 2026-08-17
> **组件：** `CapitalControlComponent`
> **关联文档：**
> - [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) v2.1（L1.5 架构）
> - [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) v2.1（文件清单）
> - [API_SPEC.md](./API_SPEC.md) v2.1（API 签名）
> - [13-通用风控模块/core/registry.py](../../13-通用风控模块/core/registry.py)（CAPITAL 类别）
> - [设计规格源文件](../../docs/superpowers/specs/2026-08-17-capital-control-component-design.md)

---

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 总体架构](#2-总体架构)
- [3. 核心数据结构](#3-核心数据结构)
- [4. CAPITAL 类别与注册机制](#4-capital-类别与注册机制)
- [5. 主组件 API](#5-主组件-api)
- [6. 资金规则清单](#6-资金规则清单)
- [7. 降级与健康判定](#7-降级与健康判定)
- [8. 配置文件](#8-配置文件)
- [9. 一期挂载与二期接入](#9-一期挂载与二期接入)
- [10. 产物格式](#10-产物格式)
- [11. 测试策略](#11-测试策略)
- [12. 文件清单](#12-文件清单)
- [变更记录](#变更记录)

---

## 1. 背景与目标

### 1.1 背景

DreamBuddy-V2 现有 6 个独立交易系统（Agent A/B/C、V15 马丁、易经推理、三屏趋势），资金来源完全独立：

| 系统 | 账户类型 | 实时查询来源 | 静态兜底 |
|------|---------|------------|---------|
| V15 马丁 | OKX 实盘 | `capital_manager.get_account_balance()` | `TOTAL_BUDGET=260` |
| 易经推理 | OKX 模拟盘 | `okx_simulated.get_balance()` | `initial_equity=150` |
| 三屏趋势 | Aster | `ml_trade_service /tracker/stats` | `INITIAL_CAPITAL=200` |
| Agent A/B/C | Hyperliquid | `client.get_account()` | `BUDGET_USDC=60` |

各系统独立的资金查询逻辑导致：

1. 无全局资金视图，无法跨系统统一调控
2. 重复 API 调用（V15 和 16-调控系统都查 OKX 余额）触发限流
3. 风控状态分散（V15 的 `v15_state.json`、易经的 `risk_state.json`、其他无统一文件）
4. 资金不足时各系统无法感知全局压力

### 1.2 目标

在 16-调控系统中增加通用组件 `CapitalControlComponent`，统一调控所有纳入名单的交易系统账户可用交易资金。

**核心能力：**

- 支持两种模式：**固定金额**（FIXED）与 **动态资金调控**（DYNAMIC，默认）
- 用户通过配置选择启动任意一种模式
- 通过注册名单机制（复用 [13-通用风控模块 RuleRegistry](../../13-通用风控模块/core/registry.py)），统一调控全局交易系统
- 实质影响全局（二期：接入 A9 决策链，对资金压力大的系统降级建议）

### 1.3 非目标

- 不替代各系统自主开仓决策
- 不做跨账户资金调度（OKX 实盘 / OKX 模拟 / Hyperliquid / Aster 4 类账户隔离）
- 不修改各系统的 `.env` 配置文件结构

### 1.4 设计原则

1. **建议制原则**：组件输出"资金可用性建议"，不直接拦截各系统开仓。遵循 16-调控系统核心原则。
2. **账户隔离原则**：4 类账户（OKX 实盘 / OKX 模拟 / Hyperliquid / Aster）独立计算，不做跨账户总额分配。
3. **缓存复用原则**：复用 [unified_position_query.py](../core/unified_position_query.py) 的 60s 缓存，避免重复 API 调用。
4. **降级回退原则**：动态查询失败时回退到各系统静态配置。
5. **零侵入原则**：一期不修改 A9 决策链；二期仅在 A9 输入契约新增可选字段。

---

## 2. 总体架构

### 2.1 在 16-调控系统分层架构中的位置

新组件位于 **L1.5 资金调控层**——L1 数据层与 L2 SKILL 引擎之间：

```
L1 数据层
  unified_position_query.py        ← 补齐 equity 字段（前置工作，已完成）
  market_data_fetcher.py
  realtime_market_stream.py
        ↓
L1.5 资金调控层（新增）
  capital_control/
    component.py                   ← CapitalControlComponent 主类
    types.py                       ← 数据结构（CapitalMode/AccountType/...）
    capital_rules/
      okx_live_rule.py              ← V15 OKX 实盘（priority=10）
      okx_simulated_rule.py         ← 易经 OKX 模拟盘（priority=20）
      hyperliquid_rule.py           ← Agent A/B/C（priority=30）
      aster_rule.py                 ← 三屏趋势（priority=40）
        ↓
L2 SKILL 引擎与分析层（A1/A2/A3）
        ↓
L3 离场决策与融合层（A9 + 融合）  ← 二期接入：消费资金调控输出
        ↓
L4 执行与反馈层
        ↓
L5 进化闭环层
```

### 2.2 两期落地范围

| 期次 | 范围 | 干预程度 | 状态 |
|------|------|---------|------|
| **一期** | 只读资金全景监控：聚合各系统可用资金，输出到调控报告 | 不干预决策 | ✅ 已完成 |
| **二期** | 接入 A9 决策链：对资金压力大的系统降级建议（HOLD 而非 RAISE_TP） | 建议制（遵循 16-调控系统核心原则） | ⏳ 默认禁用（`phase2.enabled=false`） |

### 2.3 核心流程

```
auto_exit_system.py::run_exit_evaluation_cycle()
  └─→ 步骤 1: fetch_all_positions()  ← unified_position_query（6 系统聚合 + equity 字段）
       └─→ 步骤 1.5（新增）: CapitalControlComponent.evaluate()
            ├─→ RuleRegistry.execute_chain(CAPITAL, context)   按 priority 顺序
            │     ├─→ capital.okx_live       (priority=10)   V15 马丁
            │     ├─→ capital.okx_simulated  (priority=20)   易经推理
            │     ├─→ capital.hyperliquid    (priority=30)   Agent A/B/C
            │     └─→ capital.aster          (priority=40)   三屏趋势
            ├─→ 聚合为 CapitalSnapshot
            ├─→ 健康判定（HEALTHY/WARNING/CRITICAL）
            └─→ _write_capital_report(snapshot)  → artifacts/capital-reports/capital_*.json
```

---

## 3. 核心数据结构

定义于 [types.py](../core/capital_control/types.py)。

### 3.1 CapitalMode 枚举

```python
class CapitalMode(str, Enum):
    FIXED = "fixed"        # 固定金额模式：始终使用 capital_control.json 的静态预算
    DYNAMIC = "dynamic"   # 动态资金模式（默认）：优先实时查询，失败时三级降级
```

### 3.2 AccountType 枚举

```python
class AccountType(str, Enum):
    OKX_LIVE = "okx_live"           # V15 实盘
    OKX_SIMULATED = "okx_simulated" # 易经模拟盘
    HYPERLIQUID = "hyperliquid"     # Agent A/B/C
    ASTER = "aster"                 # 三屏趋势
    UNKNOWN = "unknown"
```

### 3.3 HealthLevel 枚举

```python
class HealthLevel(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
```

### 3.4 CapitalResult 数据类

单交易系统（单账户）的资金查询结果，由每条 capital rule handler 产出。

```python
@dataclass
class CapitalResult:
    system: str                       # 系统名（如 "v15_martin"）
    account_type: AccountType         # 账户类型
    mode: CapitalMode                 # 实际使用的模式
    total_eq: float                   # 账户总权益（USDT）
    avail_balance: float              # 可用余额
    used_margin: float                 # 已用保证金
    used_pct: float                    # 保证金使用率（0-100）
    fallback_used: bool = False       # 是否降级到静态值
    fallback_reason: str = ""          # 降级原因
    timestamp: str = ""               # 查询时间戳（UTC ISO）
    extra: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]
```

### 3.5 CapitalSnapshot 数据类

全局资金快照——`evaluate()` 输出的主数据结构。

```python
@dataclass
class CapitalSnapshot:
    timestamp: str
    mode: CapitalMode
    by_system: Dict[str, CapitalResult]    # 按系统名分组
    total_equity: float                    # 全局总权益（数值加总，不可跨账户调度）
    total_avail: float
    total_used: float
    overall_used_pct: float                # 全局保证金使用率（0-100）
    health: HealthLevel
    recommendations: Dict[str, str] = field(default_factory=dict)
    by_account: Dict[str, CapitalResult] = field(default_factory=dict)  # 按账户类型分组（同账户取 equity 最大者）
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]
```

### 3.6 辅助函数

```python
def now_iso() -> str
    # 生成 UTC ISO 时间戳字符串

def assess_health(
    overall_used_pct: float,
    any_system_fallback: bool,
    any_system_unavailable: bool,
    thresholds: Optional[Dict[str, float]] = None,
) -> HealthLevel
    # 按 §7.2 健康等级判定

def calc_margin_pressure(used_pct: float) -> str
    # 单系统保证金使用率 → "LOW" / "MEDIUM" / "HIGH"
```

---

## 4. CAPITAL 类别与注册机制

### 4.1 RuleRegistry 扩展

在 [13-通用风控模块/core/registry.py](../../13-通用风控模块/core/registry.py) 的 `RuleCategory` 枚举新增 `CAPITAL` 类别：

```python
class RuleCategory(str, Enum):
    GATE = "gate"
    POSITION = "position"
    EXIT = "exit"
    CAPITAL = "capital"   # 新增：资金调控类规则
```

新增 `register_capital` 装饰器（与现有 `register_gate` / `register_position` / `register_exit` 同构）：

```python
def register_capital(
    name: str,
    priority: int = 100,
    config_schema: Optional[Dict] = None,
    description: str = "",
):
    """资金调控规则注册装饰器"""
```

### 4.2 注册流程

```
启动期：
  CapitalControlComponent.__init__()
    ↓ 实例化 RuleRegistry
    ↓ import capital_rules/{okx_live,okx_simulated,hyperliquid,aster}_rule.py
    ↓ @register_capital 装饰器自动注册到 RuleRegistry.DEFAULT_RULES
    ↓ registry.load_defaults()
    ↓ 根据 capital_control.json 的 enabled_systems 过滤
    ↓ registry.enable(name) / registry.disable(name)

运行期：
  component.evaluate()
    ↓ fetch_all_positions()（复用 60s 缓存）
    ↓ 按 priority 顺序执行各资金规则 handler
    ↓ 每条 handler 返回 CapitalResult（或 dict[system→CapitalResult]）
    ↓ 聚合为全局 CapitalSnapshot
```

### 4.3 系统 → 规则映射

| 系统 | 规则名 | 账户类型 | priority |
|------|--------|---------|---------|
| `v15_martin` | `capital.okx_live` | OKX 实盘 | 10 |
| `yijing_bcrm` | `capital.okx_simulated` | OKX 模拟盘 | 20 |
| `agent_a` / `agent_b` / `agent_c_memory` | `capital.hyperliquid` | Hyperliquid | 30 |
| `three_screen` | `capital.aster` | Aster | 40 |

> **注意**：`capital.hyperliquid` 规则一条覆盖三个系统（Agent A/B/C 共用同一 HL 账户），handler 返回 `Dict[str, CapitalResult]`。`by_account` 分组时同账户取 equity 最大者，避免重复计入。

### 4.4 用户可选择性

通过 [capital_control.json](../config/capital_control.json) 的 `enabled_systems` 选择纳入调控名单的系统：

```json
{
  "enabled_systems": ["v15_martin", "yijing_bcrm", "agent_a", "agent_b", "agent_c_memory", "three_screen"]
}
```

未纳入名单的系统：一期不在调控报告中显示资金信息；二期 A9 决策时跳过资金检查（视作"无约束"）。

---

## 5. 主组件 API

定义于 [component.py](../core/capital_control/component.py)。

### 5.1 CapitalControlComponent 类

```python
class CapitalControlComponent:
    def __init__(
        self,
        mode: Optional[CapitalMode] = None,         # None 则从配置文件读取
        config_path: Optional[Path] = None,          # None 则用默认路径
        registry: Optional[RuleRegistry] = None,      # None 则内部实例化
        cache_ttl: Optional[int] = None,              # None 则从配置读取
    )

    def evaluate(self, systems: Optional[List[str]] = None) -> CapitalSnapshot
    def get_capital_advice(self, system: str, action: str = "HOLD") -> Dict[str, Any]
    def get_snapshot(self) -> Optional[CapitalSnapshot]
    def health_check(self) -> Dict[str, Any]
```

### 5.2 `evaluate(systems=None)`

执行资金调控评估。

**流程：**

1. 如距离上次 `evaluate` < `cache_ttl` 秒，直接返回缓存快照（仅当 `systems=None`）。
2. 调用 `fetch_all_positions()` 拉取全局 positions_result（60s 缓存兜底）。
3. 按 `enabled_systems` 遍历，对每个系统调用注册好的 rule handler。
4. 聚合为 `CapitalSnapshot`，含健康判定 + 建议。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| systems | Optional[List[str]] | None | 指定要查询的子集系统；None 则查全部 enabled_systems |

**返回值：** `CapitalSnapshot`（见 §3.5）

### 5.3 `get_capital_advice(system, action="HOLD")`

二期接口：为指定系统+动作返回资金压力建议。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| system | str | — | 系统名 |
| action | str | "HOLD" | 建议动作（CLOSE / REDUCE / HOLD / RAISE_TP） |

**返回值：**

```python
{
    "allowed": bool,                 # 是否允许该动作
    "reason": str,                   # 拒绝/通过原因
    "max_position_usdt": float,      # 建议最大开仓 USDT（可用余额 × 20%）
    "current_avail": float,          # 当前可用余额
    "margin_pressure": "LOW" | "MEDIUM" | "HIGH",
    "used_pct": float,               # 单系统保证金使用率
    "total_eq": float,               # 单系统总权益
    "phase2_enabled": bool,           # 二期是否启用
}
```

**判定逻辑：**

- 系统不在 registry → `allowed=True`、`reason="system_not_in_capital_registry"`
- `phase2.enabled=true` 且 `margin_pressure=HIGH` 且 `action ∈ high_pressure_actions_to_block` → `allowed=False`
- `fallback_used=True` → reason 追加 `fallback_to_static_budget`

### 5.4 `get_snapshot()`

返回最近一次 `evaluate()` 的快照缓存（无则返回 None）。

### 5.5 `health_check()`

组件健康检查——用于 16-调控系统统一健康监控。

**返回值：**

```python
{
    "ok": bool,
    "evaluated": bool,                # 是否触发了 evaluate
    "health": "HEALTHY" | "WARNING" | "CRITICAL",
    "mode": "dynamic" | "fixed",
    "total_systems": int,
    "total_equity": float,
    "systems_with_fallback": List[str],
    "registry_rules_loaded": int,     # 应 ≥ 4
    "config_path": str,
    "cache_ttl_sec": int,
}
```

---

## 6. 资金规则清单

### 6.1 规则总览

| 规则名 | 模块 | 系统 | 账户类型 | priority | handler 关键逻辑 |
|--------|------|------|---------|---------|----------------|
| `capital.okx_live` | [okx_live_rule.py](../core/capital_control/capital_rules/okx_live_rule.py) | V15 马丁 | OKX 实盘 | 10 | 从 unified_position_query 结果提取 V15 equity（实盘账户，最高优先级） |
| `capital.okx_simulated` | [okx_simulated_rule.py](../core/capital_control/capital_rules/okx_simulated_rule.py) | 易经推理 | OKX 模拟盘 | 20 | 从 unified_position_query 结果提取易经 equity |
| `capital.hyperliquid` | [hyperliquid_rule.py](../core/capital_control/capital_rules/hyperliquid_rule.py) | Agent A/B/C | Hyperliquid | 30 | 一对多：返回 `Dict[str, CapitalResult]`，覆盖 3 个 HL 系统 |
| `capital.aster` | [aster_rule.py](../core/capital_control/capital_rules/aster_rule.py) | 三屏趋势 | Aster | 40 | ml_trade_service 不可用时降级到静态 200 |

### 6.2 Handler 签名

```python
@register_capital(
    name="capital.<name>",
    priority=<int>,
    config_schema={...},
    description="<描述>",
)
def <name>_capital_handler(
    signal: Optional[Any] = None,       # 兼容 RuleRegistry 调用约定，资金规则不使用
    context: Any = None,                 # 含 mode + positions_result
    base_risk: float = 0.0,              # 兼容参数，资金规则不使用
    config: Optional[Dict[str, Any]] = None,  # rule_config，含 fallback_static_budget
    extra: Optional[Dict[str, Any]] = None,
) -> CapitalResult | Dict[str, CapitalResult]
```

**`context` 关键字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | CapitalMode | DYNAMIC / FIXED |
| `positions_result` | Dict | `fetch_all_positions()` 返回值 |
| `target_system` | str | （单系统规则）指定系统名 |

### 6.3 共享辅助 `_shared.py`

[build_result_from_system](../core/capital_control/capital_rules/_shared.py) 提供 4 条规则共用的降级与构建逻辑：

- FIXED 模式直接使用静态值
- DYNAMIC 模式从 `positions_result["systems"][system]` 提取 equity
- equity=0 或系统数据缺失时降级到静态值，标记 `fallback_used=True`

---

## 7. 降级与健康判定

### 7.1 三级降级链

```
主流程：DYNAMIC 模式实时查询（通过 unified_position_query.fetch_all_positions）
    ↓ 查询失败（API 不可用 / 限流 / 凭证错误）
降级 1：使用 unified_position_query 的 60s 缓存数据
    ↓ 缓存过期或不存在
降级 2：回退到 fallback_static_budget（capital_control.json 配置）
    ↓ 静态值也缺失
降级 3：返回 CapitalResult(total_eq=0, fallback_used=True, fallback_reason)
```

### 7.2 健康等级判定

`assess_health()` 按 [Spec 3.4](../../docs/superpowers/specs/2026-08-17-capital-control-component-design.md) 判定：

| health | 条件 |
|--------|------|
| `HEALTHY` | 全局 used_pct < 50% 且所有系统未降级 |
| `WARNING` | 全局 used_pct ∈ [50%, 80%) 或某系统 `fallback_used=True` |
| `CRITICAL` | 全局 used_pct ≥ 80% 或某系统查询不可用（`fallback_reason` 含 `unified_fetch_failed` / `system_data_missing` / `handler_error` / `rule_execution_failed`） |

阈值可通过 `capital_control.json` 的 `health_thresholds` 覆盖。

### 7.3 单系统保证金压力

`calc_margin_pressure(used_pct)`：

| used_pct | pressure |
|---------|---------|
| ≥ 80% | HIGH |
| ≥ 50% | MEDIUM |
| < 50% | LOW |

### 7.4 单系统失败不影响整体

`evaluate()` 对每条规则 try/except 包裹，handler 异常时降级为静态兜底结果，不中断整体聚合。

---

## 8. 配置文件

### 8.1 主配置 `16-调控系统/config/capital_control.json`

```json
{
  "version": "1.0",
  "mode": "dynamic",
  "enabled_systems": [
    "v15_martin", "yijing_bcrm",
    "agent_a", "agent_b", "agent_c_memory",
    "three_screen"
  ],
  "cache_ttl_sec": 60,
  "health_thresholds": {
    "healthy_used_pct_max": 50.0,
    "warning_used_pct_max": 80.0
  },
  "fallback_static_budget": {
    "v15_martin": 260.0,
    "yijing_bcrm": 150.0,
    "agent_a": 60.0,
    "agent_b": 60.0,
    "agent_c_memory": 0.0,
    "three_screen": 200.0
  },
  "account_mapping": {
    "v15_martin": "okx_live",
    "yijing_bcrm": "okx_simulated",
    "agent_a": "hyperliquid",
    "agent_b": "hyperliquid",
    "agent_c_memory": "hyperliquid",
    "three_screen": "aster"
  },
  "phase2": {
    "enabled": false,
    "high_pressure_actions_to_block": ["RAISE_TP"],
    "high_pressure_confidence_multiplier": 0.8
  }
}
```

### 8.2 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `version` | str | "1.0" | 配置文件版本 |
| `mode` | str | "dynamic" | 资金调控模式：`fixed` / `dynamic` |
| `enabled_systems` | List[str] | 全部 6 系统 | 纳入调控名单的系统 |
| `cache_ttl_sec` | int | 60 | evaluate() 缓存 TTL（秒） |
| `health_thresholds.healthy_used_pct_max` | float | 50.0 | HEALTHY 阈值上限 |
| `health_thresholds.warning_used_pct_max` | float | 80.0 | WARNING 阈值上限（≥ 即 CRITICAL） |
| `fallback_static_budget.<system>` | float | 见 §1.1 | 各系统静态兜底预算（USDT） |
| `account_mapping.<system>` | str | — | 系统 → 账户类型映射 |
| `phase2.enabled` | bool | false | 二期开关 |
| `phase2.high_pressure_actions_to_block` | List[str] | ["RAISE_TP"] | HIGH 压力下阻断的动作 |
| `phase2.high_pressure_confidence_multiplier` | float | 0.8 | 置信度衰减系数 |

### 8.3 配置加载优先级

```
显式传入参数（如 CapitalControlComponent(mode=...)）
    ↓ 未传
capital_control.json 文件
    ↓ 文件不存在或损坏
代码默认值（_DEFAULT_CONFIG，mode=DYNAMIC, enabled_systems=全部）
```

### 8.4 与 .env 配置的关系

| 配置项 | 来源 | 说明 |
|--------|------|------|
| `mode` | capital_control.json | 资金调控模式开关 |
| `enabled_systems` | capital_control.json | 注册名单（用户可选） |
| `fallback_static_budget.v15_martin` | capital_control.json | V15 静态回退值（与 .env 的 `TOTAL_BUDGET` 解耦，但建议保持一致） |
| `OKX_API_KEY` 等 | .env.common | OKX 凭证仍由 V15/易经各自 config_loader 加载 |

**设计原则**：资金调控配置独立，但默认值与现有 .env 保持一致。

---

## 9. 一期挂载与二期接入

### 9.1 一期挂载（已完成）

修改 [auto_exit_system.py](../scripts/auto_exit_system.py) 的 `run_exit_evaluation_cycle()`，在步骤 1（fetch_all_positions）之后插入步骤 1.5：

```python
# 步骤 1.5 资金调控评估（一期：只读监控）
_log("\n[步骤 1.5/10] 资金调控评估...")
capital_snapshot = None
try:
    from capital_control import CapitalControlComponent, CapitalMode
    capital_component = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
    capital_snapshot = capital_component.evaluate()
    _log(f"  资金健康: {capital_snapshot.health.value}, "
         f"总权益: ${capital_snapshot.total_equity:,.2f}, "
         f"使用率: {capital_snapshot.overall_used_pct:.1f}%")
    for sys_name, r in capital_snapshot.by_system.items():
        tag = "降级" if r.fallback_used else "正常"
        _log(f"    - {sys_name}: ${r.total_eq:,.2f} ({tag}, {r.account_type.value})")
    _write_capital_report(capital_snapshot, positions_data)
except Exception as e:
    _log(f"  资金调控评估失败（不影响主流程）: {e}", "WARN")
```

**容错要点**：整个步骤 1.5 用 try/except 包裹，失败仅打印 WARN 日志，不中断主流程。

### 9.2 `_write_capital_report(snapshot, positions_data)`

写入资金调控报告 JSON 产物。

- **产物路径**：`16-调控系统/artifacts/capital-reports/capital_YYYYMMDD_HHMMSS.json`
- **结构**：见 §10
- **AAM 投递**：仅当 `DELIVER=1` 时调用 `aam_deliverer.deliver_capital_report()`

### 9.3 二期 A9 接入（默认禁用）

**A9 输入契约扩展**（[a9_exit_decision.py](../core/a9_exit_decision.py)）：

在 `a9_exit_decision_handler` 输入中新增可选字段 `capital_advice`，新增 Layer 5（资金调控修正）：

```python
# Layer 5: 资金调控修正
sys_advice = capital_advice.get(pos["system"], {})
if sys_advice:
    margin_pressure = sys_advice.get("margin_pressure", "LOW")
    if margin_pressure == "HIGH" and action in {"RAISE_TP"}:
        action = "HOLD"
        confidence *= 0.8
        reason += " [资金压力降级]"
```

**调用方传入 capital_advice**：

```python
# 步骤 6.5（新增）：构建各系统的资金建议
capital_advice = {}
for system in positions_result["systems"]:
    capital_advice[system] = capital_component.get_capital_advice(
        system=system, action="HOLD",
    )

# 步骤 7：A9 融合决策（传入 capital_advice）
a9_result = SkillEngine.execute("dream-exit-skill-v2", {
    "positions": all_positions,
    "a1_result": a1_result, "a2_result": a2_result, "a3_result": a3_result,
    "market": market_data,
    "capital_advice": capital_advice,  # 新增可选字段
})
```

**二期开关**：`capital_control.json` 的 `phase2.enabled=false` 默认关闭，仅在显式开启时生效。

---

## 10. 产物格式

### 10.1 资金调控报告 JSON

路径：`16-调控系统/artifacts/capital-reports/capital_YYYYMMDD_HHMMSS.json`

```json
{
  "timestamp": "2026-08-17T07:25:14Z",
  "mode": "dynamic",
  "health": "WARNING",
  "by_account": {
    "okx_live": {
      "system": "v15_martin",
      "account_type": "okx_live",
      "mode": "dynamic",
      "total_eq": 516.94,
      "avail_balance": 516.94,
      "used_margin": 0.0,
      "used_pct": 0.0,
      "fallback_used": false,
      "fallback_reason": "",
      "timestamp": "2026-08-17T07:25:14Z",
      "extra": {"source": "unified_position_query#fetch_v15_martin_positions"}
    }
  },
  "by_system": {
    "v15_martin": { "...": "..." }
  },
  "totals": {
    "total_equity": 516.94,
    "total_avail": 516.94,
    "total_used": 0.0,
    "overall_used_pct": 0.0
  },
  "recommendations": {},
  "positions_summary": {
    "total_positions": 0,
    "total_systems": 6,
    "total_equity_from_positions": 516.94
  }
}
```

### 10.2 字段说明

| 字段 | 说明 |
|------|------|
| `timestamp` | 快照时间戳（UTC ISO） |
| `mode` | 资金调控模式 |
| `health` | 全局健康等级 |
| `by_account` | 按账户类型分组（同账户取 equity 最大者，避免重复计入） |
| `by_system` | 按系统名分组（每系统一条 CapitalResult） |
| `totals` | 全局聚合（数值加总，不可跨账户调度） |
| `recommendations` | 建议字典（key=系统名，value=建议说明） |
| `positions_summary` | positions_data 摘要（来自 fetch_all_positions） |

---

## 11. 测试策略

### 11.1 测试分层

| 层级 | 范围 | 位置 | 用例数 |
|------|------|------|-------|
| 单元测试 | 数据结构、健康判定、4 条规则 handler | [tests/capital_control/test_unit.py](../tests/capital_control/test_unit.py) | 27 |
| 集成测试 | RuleRegistry 注册链、Component.evaluate() 主流程、缓存、降级 | [tests/capital_control/test_integration.py](../tests/capital_control/test_integration.py) | 15 |
| 端到端测试 | auto_exit_system.py 步骤 1.5 挂载、报告产物、配置文件 | [tests/capital_control/test_e2e.py](../tests/capital_control/test_e2e.py) | 6 |

**运行方式：**

```bash
cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
python -m pytest 16-调控系统/tests/capital_control/ -v
# 预期：48 passed
```

### 11.2 关键测试用例

- **`test_dynamic_success`**：DYNAMIC 模式成功查询返回真实 equity
- **`test_fallback_on_equity_zero`**：equity=0 时降级到静态值
- **`test_fixed_mode_uses_static_budget`**：FIXED 模式始终使用静态值
- **`test_single_system_failure_doesnt_break_overall`**：单系统失败不影响整体
- **`test_cache_hit`**：60s 缓存命中，fetch_all_positions 仅调用一次
- **`test_phase2_advice_blocks_raise_tp`**：phase2 启用时 HIGH 压力阻断 RAISE_TP
- **`test_capital_report_artifact_generated`**：步骤 1.5 生成 capital-reports 产物
- **`test_capital_failure_doesnt_crash_main`**：资金调控失败不影响主流程

### 11.3 验收清单

- [x] `python -m pytest 16-调控系统/tests/capital_control/ -v` 全部通过（48/48）
- [x] 手动运行 `python 16-调控系统/scripts/auto_exit_system.py`，验证 `artifacts/capital-reports/` 产物生成
- [x] 验证单系统失败时降级到静态值
- [x] 验证 capital_control.json 中 `enabled_systems` 过滤生效
- [ ] 验证 CRITICAL 健康状态触发飞书告警（待 15-监控告警系统联动）
- [ ] 二期接入 A9 Layer 5（待 phase2.enabled=true 启用）

---

## 12. 文件清单

### 12.1 新增文件

| 文件 | 说明 |
|------|------|
| [core/capital_control/\_\_init\_\_.py](../core/capital_control/__init__.py) | 包入口，导出 `CapitalControlComponent` / `CapitalMode` |
| [core/capital_control/types.py](../core/capital_control/types.py) | 数据结构（CapitalMode/AccountType/CapitalResult/CapitalSnapshot） |
| [core/capital_control/component.py](../core/capital_control/component.py) | CapitalControlComponent 主类 |
| [core/capital_control/capital_rules/\_\_init\_\_.py](../core/capital_control/capital_rules/__init__.py) | 规则包入口 |
| [core/capital_control/capital_rules/_shared.py](../core/capital_control/capital_rules/_shared.py) | 共享辅助（build_result_from_system / _static_from_config） |
| [core/capital_control/capital_rules/okx_live_rule.py](../core/capital_control/capital_rules/okx_live_rule.py) | V15 OKX 实盘规则（priority=10） |
| [core/capital_control/capital_rules/okx_simulated_rule.py](../core/capital_control/capital_rules/okx_simulated_rule.py) | 易经 OKX 模拟盘规则（priority=20） |
| [core/capital_control/capital_rules/hyperliquid_rule.py](../core/capital_control/capital_rules/hyperliquid_rule.py) | Agent A/B/C 规则（priority=30，一对多） |
| [core/capital_control/capital_rules/aster_rule.py](../core/capital_control/capital_rules/aster_rule.py) | 三屏趋势规则（priority=40） |
| [config/capital_control.json](../config/capital_control.json) | 主配置文件 |
| [config/capital_control.example.json](../config/capital_control.example.json) | 示例配置 |
| [tests/capital_control/\_\_init\_\_.py](../tests/capital_control/__init__.py) | 测试包入口 |
| [tests/capital_control/test_unit.py](../tests/capital_control/test_unit.py) | 单元测试（27 用例） |
| [tests/capital_control/test_integration.py](../tests/capital_control/test_integration.py) | 集成测试（15 用例） |
| [tests/capital_control/test_e2e.py](../tests/capital_control/test_e2e.py) | 端到端测试（6 用例） |
| [docs/CAPITAL_CONTROL_DESIGN.md](./CAPITAL_CONTROL_DESIGN.md) | 本设计文档 |

### 12.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| [13-通用风控模块/core/registry.py](../../13-通用风控模块/core/registry.py) | 新增 `RuleCategory.CAPITAL` 与 `register_capital` 装饰器 |
| [16-调控系统/core/unified_position_query.py](../core/unified_position_query.py) | 补齐 V15/易经/三屏/Agent C 的 equity 字段；fetch_all_positions 新增 `total_equity` 聚合字段；版本升至 "1.1" |
| [16-调控系统/scripts/auto_exit_system.py](../scripts/auto_exit_system.py) | 新增步骤 1.5 资金调控挂载；新增 `_write_capital_report`；新增 `--dry-run` CLI 参数 |
| [16-调控系统/docs/TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) | 更新分层架构，补充 L1.5 资金调控层 |
| [16-调控系统/docs/ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) | 新增 capital_control 模块文件索引 |
| [16-调控系统/docs/API_SPEC.md](./API_SPEC.md) | 新增资金调控组件 API 章节 |

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-08-17 | 初始版本。一期完成：核心组件 + 4 条资金规则 + 一期挂载 + 三层测试（48/48 通过）。二期预留 `phase2.enabled=false`。 |

---

**文档版本**: v1.0
**最后更新**: 2026-08-17
**对齐状态**: 已对齐 [设计规格源文件](../../docs/superpowers/specs/2026-08-17-capital-control-component-design.md) v1.0 与实际代码实现
