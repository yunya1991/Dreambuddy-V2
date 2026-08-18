# 设计规格：账户资金调控通用组件（CapitalControlComponent）

> **位置：** 16-调控系统/core/capital_control/
> **创建日期：** 2026-08-17
> **状态：** 待审核
> **作者：** TRAE Code Assistant
> **关联文档：**
> - [16-调控系统/docs/TECHNICAL_DESIGN.md](../../../16-调控系统/docs/TECHNICAL_DESIGN.md) v2.0
> - [13-通用风控模块/core/registry.py](../../../13-通用风控模块/core/registry.py)
> - [14-V15经典马丁策略/lib/capital_manager.py](../../../14-V15经典马丁策略/lib/capital_manager.py)
> - [16-调控系统/core/unified_position_query.py](../../../16-调控系统/core/unified_position_query.py)
> - [16-调控系统/scripts/auto_exit_system.py](../../../16-调控系统/scripts/auto_exit_system.py)

---

## 0. 背景与目标

### 0.1 背景

DreamBuddy-V2 现有 6 个独立交易系统（Agent A/B/C、V15 马丁、易经推理、三屏趋势），资金来源完全独立：
- V15 马丁用 OKX 实盘 API（动态）+ `TOTAL_BUDGET=260`（静态兜底）
- 易经推理用 OKX 模拟盘 API + `initial_equity` 参数
- 三屏趋势用 Aster/Hyperliquid 执行器余额 + `INITIAL_CAPITAL=200` 兜底
- Agent A/B/C 用 Hyperliquid `client.get_account()` + `BUDGET_USDC=60` 截断

各系统独立的资金查询逻辑导致：
1. 无全局资金视图，无法跨系统统一调控
2. 重复 API 调用（V15 和 16-调控系统都查 OKX 余额）触发限流
3. 风控状态分散（V15 的 `v15_state.json`、易经的 `risk_state.json`、其他无统一文件）
4. 资金不足时各系统无法感知全局压力

### 0.2 目标

在 16-调控系统中增加通用组件 `CapitalControlComponent`，统一调控所有纳入名单的交易系统账户可用交易资金。

**核心能力：**
- 支持两种模式：**固定金额**（FIXED）与**动态资金调控**（DYNAMIC，默认）
- 用户通过配置选择启动任意一种模式
- 通过注册名单机制（复用 13-通用风控 RuleRegistry），统一调控全局交易系统
- 实质影响全局（二期：接入 A9 决策链，对资金压力大的系统降级建议）

### 0.3 非目标

- 不替代各系统自主开仓决策
- 不做跨账户资金调度（OKX 实盘/OKX 模拟/Hyperliquid/Aster 4 类账户隔离）
- 不修改各系统的 `.env` 配置文件结构

---

## 1. 总体架构

### 1.1 在 16-调控系统五层架构中的位置

新组件位于 **L1.5 资金调控层**——L1 数据层与 L2 SKILL 引擎之间：

```
L1 数据层
  unified_position_query.py  ← 补齐 equity 字段（前置工作）
  market_data_fetcher.py
  realtime_market_stream.py
        ↓
L1.5 资金调控层（新增）
  capital_control/
    component.py              ← 主组件
    types.py                  ← 数据结构
    capital_registry.py       ← RuleRegistry 实例化与规则加载
    capital_rules/
      okx_live_rule.py        ← V15 OKX 实盘（priority=10）
      okx_simulated_rule.py   ← 易经 OKX 模拟盘（priority=20）
      hyperliquid_rule.py     ← Agent A/B/C（priority=30）
      aster_rule.py           ← 三屏趋势（priority=40）
        ↓
L2 SKILL 引擎与分析层（A1/A2/A3）
        ↓
L3 离场决策与融合层（A9 + 融合）  ← 二期接入：消费资金调控输出
        ↓
L4 执行与反馈层
        ↓
L5 进化闭环层
```

### 1.2 两期落地范围

| 期次 | 范围 | 干预程度 |
|------|------|---------|
| **一期** | 只读资金全景监控：聚合各系统可用资金，输出到调控报告 | 不干预决策 |
| **二期** | 接入 A9 决策链：对资金压力大的系统降级建议（HOLD 而非 RAISE_TP） | 建议制（遵循 16-调控系统核心原则） |

### 1.3 设计原则

1. **建议制原则**：组件输出"资金可用性建议"，不直接拦截各系统开仓。遵循 [16-调控系统核心原则](../../../16-调控系统/docs/ENGINEERING_INDEX.md)
2. **账户隔离原则**：4 类账户（OKX 实盘 / OKX 模拟 / Hyperliquid / Aster）独立计算，不做跨账户总额分配
3. **缓存复用原则**：复用 [unified_position_query.py](../../../16-调控系统/core/unified_position_query.py) 的 60s 缓存，避免重复 API 调用
4. **降级回退原则**：动态查询失败时回退到各系统静态配置（`TOTAL_BUDGET` / `BUDGET_USDC` / `INITIAL_CAPITAL`）
5. **零侵入原则**：一期不修改 A9 决策链；二期仅在 A9 输入契约新增可选字段

---

## 2. CAPITAL 类别与注册机制

### 2.1 RuleRegistry 扩展

在 [13-通用风控模块/core/registry.py](../../../13-通用风控模块/core/registry.py) 的 `RuleCategory` 枚举新增 `CAPITAL` 类别：

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
    def decorator(func):
        RuleRegistry.DEFAULT_RULES[name] = RuleInfo(
            name=name,
            category=RuleCategory.CAPITAL,
            priority=priority,
            enabled=True,
            config_schema=config_schema or {},
            description=description,
            handler=func,
        )
        return func
    return decorator
```

### 2.2 资金规则注册名单

每条资金规则对应一个交易系统（账户），规则按 `priority` 排序：

| 规则名 | 系统 | 账户类型 | priority | handler 关键逻辑 |
|--------|------|---------|---------|----------------|
| `capital.okx_live` | V15 马丁 | OKX 实盘 | 10 | 复用 V15 `get_account_balance()` + 60s 缓存 |
| `capital.okx_simulated` | 易经推理 | OKX 模拟盘 | 20 | 复用易经 `okx_simulated.py` + `risk_state.json` |
| `capital.hyperliquid` | Agent A/B/C | Hyperliquid | 30 | 复用 `unified_position_query` 的 HL 查询（已含 equity） |
| `capital.aster` | 三屏趋势 | Aster | 40 | 复用 `ml_trade_service` API |

### 2.3 用户可选择性

通过 `16-调控系统/config/capital_control.json` 选择纳入调控名单的系统：

```json
{
  "enabled_systems": ["v15_martin", "yijing_bcrm", "agent_a", "agent_b"],
  "disabled_systems": ["agent_c_memory", "three_screen"]
}
```

未纳入名单的系统：
- 一期：不在调控报告中显示资金信息
- 二期：A9 决策时跳过资金检查（视作"无约束"）

### 2.4 注册流程

```
启动期：
  CapitalControlComponent.__init__()
    ↓ 实例化 RuleRegistry
    ↓ 遍历 capital_rules/ 目录，import 所有模块
    ↓ @register_capital 装饰器自动注册到 RuleRegistry.DEFAULT_RULES
    ↓ 根据 capital_control.json 的 enabled_systems 过滤
    ↓ registry.enable(name) / registry.disable(name)
  运行期：
  component.evaluate()
    ↓ registry.execute_chain(CAPITAL, context)
    ↓ 按 priority 顺序执行各资金规则 handler
    ↓ 每条 handler 返回 CapitalResult
    ↓ 聚合为全局 CapitalSnapshot
```

---

## 3. 核心数据结构与 API

### 3.1 数据结构

```python
# 16-调控系统/core/capital_control/types.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

class CapitalMode(str, Enum):
    FIXED = "fixed"        # 固定金额模式
    DYNAMIC = "dynamic"   # 动态资金调控（默认）

class AccountType(str, Enum):
    OKX_LIVE = "okx_live"
    OKX_SIMULATED = "okx_simulated"
    HYPERLIQUID = "hyperliquid"
    ASTER = "aster"
    UNKNOWN = "unknown"

@dataclass
class CapitalResult:
    """单系统资金查询结果"""
    system: str                       # 系统名
    account_type: AccountType         # 账户类型
    mode: CapitalMode                 # 实际使用的模式
    total_eq: float                   # 账户总权益（USDT）
    avail_balance: float              # 可用余额
    used_margin: float                # 已用保证金
    used_pct: float                   # 保证金使用率
    fallback_used: bool = False       # 是否降级到静态值
    fallback_reason: str = ""         # 降级原因
    timestamp: str = ""               # 查询时间戳
    extra: Dict = field(default_factory=dict)

@dataclass
class CapitalSnapshot:
    """全局资金快照（多账户聚合）"""
    timestamp: str
    mode: CapitalMode
    by_account: Dict[str, CapitalResult]   # 按账户类型分组
    by_system: Dict[str, CapitalResult]    # 按系统名分组
    total_equity: float              # 全局总权益（数值加总，不可跨账户调度）
    total_avail: float
    total_used: float
    overall_used_pct: float
    health: str                      # HEALTHY / WARNING / CRITICAL
    recommendations: Dict[str, str] = field(default_factory=dict)
```

### 3.2 CapitalControlComponent 主类

```python
# 16-调控系统/core/capital_control/component.py
class CapitalControlComponent:
    """账户资金调控通用组件"""

    def __init__(
        self,
        mode: CapitalMode = CapitalMode.DYNAMIC,
        config_path: Optional[Path] = None,
        registry: Optional[RuleRegistry] = None,
        cache_ttl: int = 60,
    ):
        """初始化组件"""

    def evaluate(self, systems: Optional[List[str]] = None) -> CapitalSnapshot:
        """执行资金调控评估（一期：只读监控；二期：附带建议）"""

    def get_capital_advice(self, system: str, action: str) -> Dict:
        """二期接口：给定系统+动作，返回资金建议"""

    def get_snapshot(self) -> Optional[CapitalSnapshot]:
        """获取最近一次 evaluate() 缓存结果"""

    def health_check(self) -> Dict:
        """组件健康检查"""
```

### 3.3 资金规则 handler 签名

```python
@register_capital(
    name="capital.okx_live",
    priority=10,
    config_schema={
        "total_budget_fallback": {"type": "float", "default": 260.0},
        "cache_ttl_sec": {"type": "int", "default": 60},
    },
    description="V15 马丁 OKX 实盘资金查询",
)
def okx_live_capital_handler(
    signal: Optional[Signal] = None,
    context: RiskContext = None,
    base_risk: float = 0.0,
    config: Dict = None,
    extra: Optional[Dict] = None,
) -> CapitalResult:
    """复用 14-V15/lib/capital_manager.py 的 get_account_balance()"""
```

### 3.4 健康等级判定

| health | 条件 |
|--------|------|
| HEALTHY | 全局 used_pct < 50% 且所有系统 status=ok |
| WARNING | 全局 used_pct ∈ [50%, 80%] 或某系统 fallback_used=True |
| CRITICAL | 全局 used_pct ≥ 80% 或某系统查询失败 |

---

## 4. equity 字段补齐与全局聚合

### 4.1 现状

[unified_position_query.py](../../../16-调控系统/core/unified_position_query.py) 中 `_make_system_result()` 含 `equity` 字段，但 6 个系统中只有 Agent A/B 真正填充。

### 4.2 V15 马丁补齐

在 [fetch_v15_martin_positions()](../../../16-调控系统/core/unified_position_query.py) 中新增：

```python
equity = 0.0
extra = {}
try:
    sys.path.insert(0, str(V15_DIR / "lib"))
    from capital_manager import get_account_balance
    bal = get_account_balance()
    if bal.get("ok"):
        equity = bal["total_eq"]
        extra = {
            "avail_balance": bal["avail_balance"],
            "used_margin": bal["used_margin"],
            "account_type": "okx_live",
        }
except Exception as e:
    extra = {"equity_fetch_error": str(e)}

result = _make_system_result(
    system="v15_martin",
    exchange="okx",
    positions=positions,
    status=status,
    equity=equity,
    extra=extra,
)
```

### 4.3 易经推理补齐

复用 [11-易经/scripts/memory_l4/okx_simulated.py](../../../11-易经推理系统/scripts/memory_l4/okx_simulated.py) 的 `OKXSimulatedClient`（`simulated=True`），与 V15 实盘凭证独立。

### 4.4 三屏趋势补齐

通过 `ml_trade_service` API 的 `/tracker/stats` 端点获取 `account_value` 字段。

### 4.5 Agent C 补齐

Agent C 共用 Agent B 账户，直接复用 Agent B 的 equity 缓存（避免重复 API 调用）。

### 4.6 全局聚合

在 [fetch_all_positions()](../../../16-调控系统/core/unified_position_query.py) 中新增：

```python
total_equity = 0.0
for sys_name, data in systems_data.items():
    total_equity += data.get("equity", 0.0)

return {
    ...
    "version": "1.1",
    "total_equity": round(total_equity, 2),  # 新增字段
    ...
}
```

### 4.7 缓存复用

| 调用方 | 缓存层级 | TTL |
|--------|---------|-----|
| unified_position_query | 进程内 dict `_cache` | 60s |
| V15 `get_account_balance()` | OKX API 单次调用 | 无（由 unified 缓存兜底） |
| 易经 `okx_simulated.get_balance()` | OKX API 单次调用 | 无（由 unified 缓存兜底） |

**关键约束**：资金调控组件的 `evaluate()` 必须先调用 `fetch_all_positions()`，再从结果中提取各系统 equity，**避免直接调 OKX API**。

---

## 5. 挂载点与 A9 接入

### 5.1 一期挂载（步骤 1.5）

修改 [auto_exit_system.py](../../../16-调控系统/scripts/auto_exit_system.py) 的 `run_exit_evaluation_cycle()`，在步骤 1（fetch_all_positions）之后插入：

```python
# 步骤 1.5（新增）: 资金调控评估（一期）
capital_component = CapitalControlComponent(
    mode=CapitalMode.DYNAMIC,
    config_path=Path("16-调控系统/config/capital_control.json"),
)
capital_snapshot = capital_component.evaluate()

# 一期：写入调控报告
_write_capital_report(capital_snapshot, positions_result)
```

### 5.2 二期 A9 接入

#### 5.2.1 A9 输入契约扩展

在 [a9_exit_decision.py](../../../16-调控系统/core/a9_exit_decision.py) 的 `a9_exit_decision_handler` 输入中新增可选字段 `capital_advice`：

```python
def a9_exit_decision_handler(inputs: Dict, engine) -> Dict:
    ...
    capital_advice = inputs.get("capital_advice", {})  # 新增可选字段
    
    for pos in positions:
        # ... 现有 4 层决策链 ...
        
        # 新增 Layer 5（资金调控修正）
        sys_advice = capital_advice.get(pos["system"], {})
        if sys_advice:
            margin_pressure = sys_advice.get("margin_pressure", "LOW")
            if margin_pressure == "HIGH" and action in {"RAISE_TP"}:
                action = "HOLD"
                confidence *= 0.8
                reason += " [资金压力降级]"
        
        evaluations.append({
            ...
            "layers": {
                ...,
                "layer5_capital_adjustment": {
                    "margin_pressure": margin_pressure,
                    "original_action": "RAISE_TP",
                    "adjusted_action": "HOLD",
                    "confidence_adjustment": 0.8,
                }
            }
        })
```

#### 5.2.2 调用方传入 capital_advice

```python
# 步骤 6.5（新增）: 构建各系统的资金建议
capital_advice = {}
for system in positions_result["systems"]:
    capital_advice[system] = capital_component.get_capital_advice(
        system=system,
        action="HOLD",
    )

# 步骤 7: A9 融合决策（传入 capital_advice）
a9_result = SkillEngine.execute("dream-exit-skill-v2", {
    "positions": all_positions,
    "a1_result": a1_result,
    "a2_result": a2_result,
    "a3_result": a3_result,
    "market": market_data,
    "capital_advice": capital_advice,
})
```

### 5.3 已知 Bug 修复

[API_SPEC.md](../../../16-调控系统/docs/API_SPEC.md) 记录 `auto_exit_system.py:183` 调用不存在的 `a9_exit_decision.evaluate_position_for_exit`，本设计建议一并修复：

```python
# 修复后：走 SKILL 引擎
result = SkillEngine.execute("dream-exit-skill-v2", {...})
```

### 5.4 一期报告输出

```json
// artifacts/capital-reports/capital_YYYYMMDD_HHMMSS.json
{
  "timestamp": "2026-08-17T08:00:00Z",
  "mode": "dynamic",
  "health": "HEALTHY",
  "by_account": {
    "okx_live": {
      "system": "v15_martin",
      "total_eq": 260.50,
      "avail_balance": 180.30,
      "used_margin": 80.20,
      "used_pct": 30.79,
      "fallback_used": false
    },
    ...
  },
  "totals": {
    "total_equity": 580.50,
    "total_avail": 410.30,
    "total_used": 170.20,
    "overall_used_pct": 29.30
  },
  "recommendations": {}
}
```

通过 [aam_deliverer.py](../../../16-调控系统/core/aam_deliverer.py) 投递到 AAM 产物中心（双通道）。

---

## 6. 配置项设计与错误降级

### 6.1 主配置：`16-调控系统/config/capital_control.json`

```json
{
  "version": "1.0",
  "mode": "dynamic",
  "enabled_systems": [
    "v15_martin",
    "yijing_bcrm",
    "agent_a",
    "agent_b",
    "agent_c_memory",
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

### 6.2 与 .env 配置的关系

| 配置项 | 来源 | 说明 |
|--------|------|------|
| `mode` | capital_control.json | 资金调控模式开关 |
| `enabled_systems` | capital_control.json | 注册名单（用户可选） |
| `fallback_static_budget.v15_martin` | capital_control.json | V15 静态回退值（与 .env 的 `TOTAL_BUDGET` 解耦，但建议保持一致） |
| `OKX_API_KEY` 等 | .env.common | OKX 凭证仍由 V15/易经各自 config_loader 加载 |

**设计原则**：资金调控配置独立，但默认值与现有 .env 保持一致。

### 6.3 三级降级链

```
主流程：DYNAMIC 模式实时查询
    ↓ 查询失败（API 不可用 / 限流 / 凭证错误）
降级 1：使用 unified_position_query 的 60s 缓存数据
    ↓ 缓存过期或不存在
降级 2：回退到 fallback_static_budget（capital_control.json 配置）
    ↓ 静态值也缺失
降级 3：返回 CapitalResult(total_eq=0, fallback_used=True, fallback_reason)
```

### 6.4 单系统失败不影响整体

```python
def evaluate(self, systems=None) -> CapitalSnapshot:
    results = []
    for sys_name in self._get_enabled_systems(systems):
        try:
            result = self.registry.execute_chain(
                RuleCategory.CAPITAL,
                context=self._build_context(sys_name),
            )
            results.append(result)
        except Exception as e:
            results.append(CapitalResult(
                system=sys_name,
                account_type=AccountType.UNKNOWN,
                mode=self.mode,
                total_eq=0.0,
                avail_balance=0.0,
                used_margin=0.0,
                used_pct=0.0,
                fallback_used=True,
                fallback_reason=f"rule_execution_failed: {e}",
            ))
    return self._aggregate(results)
```

### 6.5 OKX API 限流保护

借鉴 [V15 capital_manager.py:111-153](../../../14-V15经典马丁策略/lib/capital_manager.py) 的错误处理：
- 429 限流：直接降级到静态值，不重试
- 401 凭证错误：标记 `fallback_reason="auth_failed"`，触发健康告警
- 网络超时：降级到 unified_position_query 的 60s 缓存

### 6.6 告警联动

CRITICAL 健康状态通过 [15-监控告警系统](../../../15-监控告警系统/feishu_alert.py) 推送飞书告警：

```python
if snapshot.health == "CRITICAL":
    from feishu_alert import send_alert
    send_alert(
        title="资金调控告警",
        content=f"全局保证金使用率 {snapshot.overall_used_pct}%，"
                f"失败系统: {[s for s, r in snapshot.by_system.items() if r.fallback_used]}",
        severity="critical",
    )
```

### 6.7 配置加载优先级

```
显式传入参数（如 CapitalControlComponent(mode=...)）
    ↓ 未传
capital_control.json 文件
    ↓ 文件不存在
环境变量 CAPITAL_CONTROL_MODE / CAPITAL_CONTROL_ENABLED_SYSTEMS
    ↓ 未设
代码默认值（mode=DYNAMIC, enabled_systems=全部）
```

---

## 7. 测试策略

### 7.1 测试分层

| 层级 | 范围 | 位置 |
|------|------|------|
| 单元测试 | 各资金规则 handler、数据结构、健康判定 | `16-调控系统/tests/capital_control/test_unit.py` |
| 集成测试 | RuleRegistry 注册链、Component.evaluate() 主流程、降级链 | `16-调控系统/tests/capital_control/test_integration.py` |
| 端到端测试 | auto_exit_system.py 步骤 1.5 挂载、A9 二期接入 | `16-调控系统/tests/capital_control/test_e2e.py` |

### 7.2 关键测试用例

#### 7.2.1 单元测试

```python
class TestOkxLiveRule:
    def test_dynamic_mode_success(self, mocker):
        """动态模式成功查询"""
        mocker.patch("capital_manager.get_account_balance", 
                     return_value={"ok": True, "total_eq": 260.5, "avail_balance": 180.3, "used_margin": 80.2})
        result = okx_live_capital_handler(context=mock_context, config={})
        assert result.total_eq == 260.5
        assert result.fallback_used is False
    
    def test_dynamic_mode_fallback_on_api_failure(self, mocker):
        """API 失败时降级到静态值"""
        mocker.patch("capital_manager.get_account_balance", 
                     return_value={"ok": False, "error": "429 rate limit"})
        result = okx_live_capital_handler(context=mock_context, config={"total_budget_fallback": 260.0})
        assert result.total_eq == 260.0
        assert result.fallback_used is True
        assert "429" in result.fallback_reason

class TestHealthAssessment:
    def test_healthy(self):
        snapshot = build_snapshot(used_pct=30.0, fallback=False)
        assert assess_health(snapshot) == "HEALTHY"
    
    def test_critical_on_80_pct(self):
        snapshot = build_snapshot(used_pct=80.0, fallback=False)
        assert assess_health(snapshot) == "CRITICAL"
    
    def test_warning_on_fallback(self):
        snapshot = build_snapshot(used_pct=30.0, fallback=True)
        assert assess_health(snapshot) == "WARNING"
```

#### 7.2.2 集成测试

```python
class TestCapitalControlComponent:
    def test_evaluate_all_systems(self, tmp_path):
        config = create_test_config(tmp_path, mode="dynamic", enabled_systems=["v15_martin"])
        component = CapitalControlComponent(config_path=config)
        snapshot = component.evaluate()
        assert "v15_martin" in snapshot.by_system
        assert snapshot.mode == CapitalMode.DYNAMIC
    
    def test_fixed_mode_uses_static_budget(self, tmp_path):
        config = create_test_config(tmp_path, mode="fixed", 
                                     fallback_static_budget={"v15_martin": 260.0})
        component = CapitalControlComponent(config_path=config)
        snapshot = component.evaluate(systems=["v15_martin"])
        assert snapshot.by_system["v15_martin"].total_eq == 260.0
        assert snapshot.by_system["v15_martin"].mode == CapitalMode.FIXED
    
    def test_single_system_failure_doesnt_break_overall(self, mocker):
        mocker.patch("okx_live_capital_handler", side_effect=Exception("OKX down"))
        component = CapitalControlComponent()
        snapshot = component.evaluate()
        assert snapshot.health in {"WARNING", "CRITICAL"}
        assert snapshot.by_system["v15_martin"].fallback_used is True
        assert snapshot.by_system["agent_a"].fallback_used is False
```

#### 7.2.3 端到端测试

```python
class TestAutoExitSystemIntegration:
    def test_step_1_5_capital_evaluation(self, mocker):
        mocker.patch("auto_exit_system.CapitalControlComponent.evaluate",
                     return_value=mock_snapshot())
        run_exit_evaluation_cycle()
        assert any(ARTIFACTS_DIR.glob("capital_*.json"))
    
    def test_phase2_a9_consumes_capital_advice(self, mocker):
        mocker.patch("a9_exit_decision_handler", wraps=real_handler)
        run_exit_evaluation_cycle()
        for eval in a9_result["exit_evaluations"]:
            if eval["position"]["system"] == "v15_martin":
                assert "layer5_capital_adjustment" in eval["layers"]
```

### 7.3 覆盖率目标

| 模块 | 覆盖率目标 |
|------|----------|
| capital_control/types.py | 95% |
| capital_control/component.py | 85% |
| capital_rules/*.py | 75% |
| auto_exit_system.py（步骤 1.5） | 80% |

### 7.4 验收清单

- [ ] `python -m pytest 16-调控系统/tests/capital_control/ -v` 全部通过
- [ ] 手动运行 `python 16-调控系统/scripts/auto_exit_system.py`，验证 `artifacts/capital-reports/` 产物生成
- [ ] 验证 CRITICAL 健康状态触发飞书告警
- [ ] 验证 OKX API 限流时降级到静态值
- [ ] 验证 capital_control.json 中 `enabled_systems` 过滤生效

---

## 8. 文件清单

### 8.1 新增文件

| 文件 | 说明 |
|------|------|
| `16-调控系统/core/capital_control/__init__.py` | 包入口 |
| `16-调控系统/core/capital_control/types.py` | 数据结构（CapitalMode/AccountType/CapitalResult/CapitalSnapshot） |
| `16-调控系统/core/capital_control/component.py` | CapitalControlComponent 主类 |
| `16-调控系统/core/capital_control/capital_registry.py` | RuleRegistry 实例化与规则加载 |
| `16-调控系统/core/capital_control/capital_rules/__init__.py` | 规则包入口 |
| `16-调控系统/core/capital_control/capital_rules/okx_live_rule.py` | V15 OKX 实盘规则 |
| `16-调控系统/core/capital_control/capital_rules/okx_simulated_rule.py` | 易经 OKX 模拟盘规则 |
| `16-调控系统/core/capital_control/capital_rules/hyperliquid_rule.py` | Agent A/B/C 规则 |
| `16-调控系统/core/capital_control/capital_rules/aster_rule.py` | 三屏趋势规则 |
| `16-调控系统/config/capital_control.json` | 主配置文件 |
| `16-调控系统/tests/capital_control/__init__.py` | 测试包入口 |
| `16-调控系统/tests/capital_control/test_unit.py` | 单元测试 |
| `16-调控系统/tests/capital_control/test_integration.py` | 集成测试 |
| `16-调控系统/tests/capital_control/test_e2e.py` | 端到端测试 |
| `16-调控系统/docs/CAPITAL_CONTROL_DESIGN.md` | 设计文档（本 spec 的产品化版本） |

### 8.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| [13-通用风控模块/core/registry.py](../../../13-通用风控模块/core/registry.py) | 新增 `RuleCategory.CAPITAL` 与 `register_capital` 装饰器 |
| [16-调控系统/core/unified_position_query.py](../../../16-调控系统/core/unified_position_query.py) | 补齐 V15/易经/三屏/Agent C 的 equity 字段；fetch_all_positions 新增 total_equity |
| [16-调控系统/scripts/auto_exit_system.py](../../../16-调控系统/scripts/auto_exit_system.py) | 新增步骤 1.5 资金调控挂载；修复 line 183 Bug |
| [16-调控系统/core/a9_exit_decision.py](../../../16-调控系统/core/a9_exit_decision.py) | 新增 Layer 5 资金调控修正（二期） |
| [16-调控系统/core/__init__.py](../../../16-调控系统/core/__init__.py) | 导出 CapitalControlComponent |
| [16-调控系统/docs/TECHNICAL_DESIGN.md](../../../16-调控系统/docs/TECHNICAL_DESIGN.md) | 更新分层架构，补充 L1.5 资金调控层 |
| [16-调控系统/docs/ENGINEERING_INDEX.md](../../../16-调控系统/docs/ENGINEERING_INDEX.md) | 新增 capital_control 模块文件索引 |

---

## 9. 风险与依赖

| 风险 | 说明 | 缓解 |
|------|------|------|
| 账户隔离 | V15(实盘)/易经(模拟)/Agent(HL)/三屏(Aster) 4 个独立账户 | 按账户维度分别调控，不做跨账户总额分配 |
| 重复 API 调用 | V15 + unified_position_query + 新组件三次查 OKX 余额触发限流 | 复用 60s 缓存，单例工厂模式 |
| 配置不一致 | .env.common 与 .env.v15 优先级覆盖 | 资金调控配置独立于 .env |
| 建议制约束 | 16-调控系统核心原则是"建议制，不替代各系统自主离场逻辑" | 输出资金可用性建议，不直接拦截开仓 |
| equity 缺失 | 4 个系统未填充 equity 字段 | 前置工作（4.2-4.5） |
| auto_exit_system Bug | line 183 调用不存在的函数 | 本设计一并修复 |

---

## 10. 实施顺序

1. **前置工作**：补齐 unified_position_query 的 equity 字段 + total_equity 聚合
2. **RuleRegistry 扩展**：新增 CAPITAL 类别与 register_capital 装饰器
3. **数据结构**：实现 types.py
4. **资金规则**：实现 4 条 capital rule handler
5. **主组件**：实现 CapitalControlComponent
6. **配置文件**：创建 capital_control.json
7. **一期挂载**：修改 auto_exit_system.py 步骤 1.5 + 修复 line 183 Bug
8. **测试**：单元 + 集成 + 端到端
9. **文档**：更新 TECHNICAL_DESIGN.md 和 ENGINEERING_INDEX.md
10. **二期接入**：A9 handler 新增 Layer 5（最后实施）

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-08-17 | 初始设计稿，经 brainstorming skill 7 节分节呈现并确认 |
