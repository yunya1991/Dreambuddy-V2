# 接口规格文档 — 16-调控系统

> **定位：** 调控系统全部公开 Python API 与 CLI 命令的签名、参数、返回值、调用示例
> **版本：** v2.0 | **更新：** 2026-07-25
> **说明：** 本系统无自有 HTTP 服务，由 TRAE Work 调度层定时调用，故以 Python API 与 CLI 为主

---

## 目录

- [1. 接口概览](#1-接口概览)
- [2. 认证方式](#2-认证方式)
- [3. 接口详情](#3-接口详情)
  - [3.1 统一持仓查询 API (core/unified_position_query.py)](#31-统一持仓查询-api-coreunified_position_querypy)
  - [3.2 SKILL 引擎 API (core/skill_engine.py)](#32-skill-引擎-api-coreskill_enginepy)
  - [3.3 A9 离场决策 API (core/a9_exit_decision.py)](#33-a9-离场决策-api-corea9_exit_decisionpy)
  - [3.4 宏观分析 SKILL 适配器 (A1/A2/A3)](#34-宏观分析-skill-适配器-a1a2a3)
  - [3.5 技术离场适配器 API (core/technical_exit_adapter.py)](#35-技术离场适配器-api-coretechnical_exit_adapterpy)
  - [3.6 离场执行器 API (core/exit_executor.py)](#36-离场执行器-api-coreexit_executorpy)
  - [3.7 权限反馈 API (core/feedback_and_permission.py)](#37-权限反馈-api-corefeedback_and_permissionpy)
  - [3.8 进化闭环 API (core/evolution_loop.py / enhanced_evolution.py)](#38-进化闭环-api-coreevolution_looppy--enhanced_evolutionpy)
  - [3.9 回测框架 API (core/backtest_framework.py)](#39-回测框架-api-corebacktest_frameworkpy)
  - [3.10 AAM 产物投递 API (core/aam_deliverer.py)](#310-aam-产物投递-api-coreaam_delivererpy)
  - [3.11 CLI 命令 (scripts/)](#311-cli-命令-scripts)
- [4. 错误码](#4-错误码)
- [5. 版本管理](#5-版本管理)

---

## 1. 接口概览

### 1.1 接口列表

| 模块 | 入口 | 关键公开 API |
|------|------|--------------|
| 包入口 | `core/__init__.py` | `fetch_all_positions`, `get_position_summary`, `SkillEngine`, `SkillResult`, `register_skill` |
| 统一持仓查询 | `core/unified_position_query.py` | `fetch_all_positions(systems)`, `get_position_summary()`, `fetch_agent_a_positions()`, `fetch_agent_b_positions()`, `fetch_agent_c_positions()`, `fetch_v15_martin_positions()`, `fetch_yijing_positions()`, `fetch_three_screen_positions()` |
| SKILL 引擎 | `core/skill_engine.py` | `SkillEngine.execute()`, `SkillEngine.register()`, `register_skill()`, `SkillPhase`, `SkillResult` |
| A9 离场决策 | `core/a9_exit_decision.py` | `a9_exit_decision_handler(inputs, engine)` |
| A1 调研 | `core/a1_research_adapter.py` | `a1_research_handler(inputs, engine)` |
| A2 第一性原理 | `core/a2_first_principles_adapter.py` | `a2_first_principles_handler(inputs, engine)` |
| A3 策略设计 | `core/a3_strategy_adapter.py` | `a3_strategy_designer_handler(inputs, engine)` |
| 技术离场适配器 | `core/technical_exit_adapter.py` | `technical_exit_handler(inputs, engine)`, `fuse_macro_technical(...)`, `_calc_simple_technical_signals(...)` |
| 策略离场适配器 | `core/strategy_exit_adapter.py` | `get_strategy_exit_design(strategy_id)`, `evaluate_exit_rationality(...)`, `get_all_strategy_designs()` |
| 离场执行器 | `core/exit_executor.py` | `ExitExecutor.execute_evaluations(...)`, `create_executor_from_env()`, `ExitExecution`, `ExecutionMode`, `ExecutionStatus` |
| 权限反馈 | `core/feedback_and_permission.py` | `can_auto_execute(...)`, `record_feedback(...)`, `get_feedback_stats(...)`, `set_system_permission(...)`, `get_system_permission(...)`, `PermissionLevel` |
| 基础进化闭环 | `core/evolution_loop.py` | `EvolutionLoop.record_decision()`, `record_outcome()`, `analyze_accuracy()`, `get_evolved_params()`, `get_evolution_loop()` |
| 增强进化闭环 | `core/enhanced_evolution.py` | `EnhancedEvolutionLoop.run_full_evolution_cycle()`, `run_a8_inspection()`, `run_dream_analysis()`, `get_summary()`, `get_enhanced_evolution()` |
| 回测框架 | `core/backtest_framework.py` | `run_backtest(...)`, `generate_simulated_bars(...)`, `BacktestResult`, `Bar`, `Position`, `TradeRecord`, `ExitAction` |
| AAM 产物投递 | `core/aam_deliverer.py` | `deliver_exit_evaluation(...)`, `deliver_artifact(...)`, `generate_frontmatter(...)`, `list_delivered_artifacts(...)` |
| 自动化调度 | `scripts/auto_exit_system.py` | `run_exit_evaluation_cycle()`, `main()` |

### 1.2 调用拓扑

```
TRAE Work 调度层（08:00 / 20:00）
  └─→ scripts/auto_exit_system.py::run_exit_evaluation_cycle()
        ├─→ unified_position_query.fetch_all_positions()         (6 系统聚合)
        ├─→ market_data_fetcher.fetch_market_data()              (市场数据)
        ├─→ SkillEngine.execute("dream-strategy-research", ...)  (A1)
        ├─→ SkillEngine.execute("dream-first-principles", ...)   (A2)
        ├─→ SkillEngine.execute("dream-strategy-designer", ...)  (A3)
        ├─→ technical_exit_adapter.fuse_macro_technical(...)     (融合决策)
        │     └─→ strategy_exit_adapter.evaluate_exit_rationality()
        ├─→ feedback_and_permission.can_auto_execute(...)        (权限检查)
        ├─→ exit_executor.execute_evaluations(...)               (执行)
        ├─→ enhanced_evolution.record_decision/record_outcome()  (进化闭环)
        └─→ aam_deliverer.deliver_exit_evaluation(...)           (产物投递)
```

---

## 2. 认证方式

本系统为**离线 Python 库 + CLI 脚本**形态，**无自有 HTTP 服务，无需 HTTP 鉴权**。

### 2.1 调度层调用

由 **TRAE Work 调度层** 定时触发 `scripts/auto_exit_system.py`（默认每天 08:00 / 20:00 各一次）。调度链路本身由 TRAE Work 平台鉴权，不在本系统范围内。

### 2.2 外部数据源凭证

通过环境变量传入下游系统所需的凭证（本系统不直接持有密钥）：

| 凭证 | 用途 | 使用模块 |
|------|------|----------|
| `OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` | OKX REST API（V15 马丁持仓查询 / 实盘下单） | `unified_position_query.fetch_v15_martin_positions()`、`exit_executor._get_okx_client()` |
| `EXIT_MODE` | 执行模式 `dry_run` / `simulated` / `real` | `exit_executor.create_executor_from_env()` |
| Hyperliquid | 公开 REST，无需鉴权 | `unified_position_query._fetch_hl_positions()` |
| ml_trade_service | 本地 HTTP `127.0.0.1:8092`，无鉴权 | `fetch_three_screen_positions()` |

### 2.3 权限体系（系统内）

本系统内部通过 `feedback_and_permission.PermissionLevel` 实行 5 级权限管控（详见 [3.7](#37-权限反馈-api-corefeedback_and_permissionpy)），各交易系统默认权限：

| 系统 | 默认权限 | 自动执行紧急度阈值 | 最大自动减仓比例 |
|------|----------|--------------------|------------------|
| `agent_a` / `agent_b` / `agent_c` | `ADVISE` | `CRITICAL` | 30% |
| `v15_martin` | `NOTIFY` | `CRITICAL` | 0%（仅通知） |
| `yijing_bcrm` | `ADVISE` | `HIGH` | 50% |
| `screen_trend` | `NOTIFY` | `CRITICAL` | 0%（仅通知） |

---

## 3. 接口详情

### 3.1 统一持仓查询 API (core/unified_position_query.py)

#### 3.1.1 fetch_all_positions

聚合 6 个交易系统持仓，输出统一格式。单系统失败降级容错，单源超时 8s，进程内 60s 缓存。

```python
def fetch_all_positions(systems: Optional[List[str]] = None) -> Dict
```

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| systems | Optional[List[str]] | None | 指定要查询的系统名列表；None 则查全部。可选值：`agent_a` / `agent_b` / `agent_c_memory` / `v15_martin` / `yijing_bcrm` / `three_screen` |

**返回值：**

```python
{
    "timestamp": "2026-07-25T08:00:00+00:00",  # ISO8601 UTC
    "version": "1.0",
    "total_systems": 6,                          # 本轮实际查询的系统数
    "total_positions": 12,                       # 聚合后持仓总数
    "total_unrealized_pnl": 123.45,              # 聚合未实现盈亏（USDT，2 位小数）
    "overall_status": "ok",                      # ok / degraded / failed
    "system_status": {                           # 每个系统的状态
        "agent_a": "ok",
        "v15_martin": "partial",
        "three_screen": "unavailable",
        # ...
    },
    "systems_summary": {"ok": 4, "partial": 1, "error": 1},
    "systems": {                                 # 每系统完整结果（见 _make_system_result）
        "agent_a": { "system": "agent_a", "exchange": "hyperliquid",
                     "equity": 1234.56, "positions": [...],
                     "position_count": 3, "status": "ok" },
        # ...
    },
    "all_positions": [                           # 聚合后的统一格式持仓列表
        {
            "system": "agent_a",
            "symbol": "BTC",
            "inst_id": "",
            "exchange": "hyperliquid",
            "direction": "LONG",                 # LONG / SHORT / UNKNOWN
            "size": 0.5,
            "entry_price": 60000.0,
            "unrealized_pnl": 100.0,
            "upl_ratio": 0.0,
            "leverage": 3.0,
            "open_time": "",
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "meta": { "position_value": 30000.0 }
        },
        # ...
    ],
}
```

**`overall_status` 取值规则：**
- `ok` — 所有系统均 ok
- `degraded` — 至少 1 个 error 但还有 ok
- `failed` — 全部 error / unavailable

**调用示例：**

```python
from core import fetch_all_positions

# 查询全部 6 个系统
result = fetch_all_positions()

# 只查 Agent A 与 V15 马丁
result = fetch_all_positions(systems=["agent_a", "v15_martin"])
```

---

#### 3.1.2 get_position_summary

快速获取持仓摘要（不返回完整持仓列表，体积更小）。

```python
def get_position_summary() -> Dict
```

**返回值：**

```python
{
    "timestamp": "2026-07-25T08:00:00+00:00",
    "total_systems": 6,
    "total_positions": 12,
    "total_unrealized_pnl": 123.45,
    "overall_status": "ok",
    "system_status": {"agent_a": "ok", "v15_martin": "partial", "...": "..."},
    "by_system": {
        "agent_a": {"position_count": 3, "status": "ok"},
        # ...
    },
}
```

---

#### 3.1.3 单系统查询函数

每个函数返回 `_make_system_result` 结构（即 `fetch_all_positions` 返回值中 `systems[<sys_name>]` 的内容）。

| 函数 | 数据源 |
|------|--------|
| `fetch_agent_a_positions() -> Dict` | Hyperliquid REST（地址 `0x9384...39934`） |
| `fetch_agent_b_positions() -> Dict` | Hyperliquid REST（地址 `0x6632...4004A`） |
| `fetch_agent_c_positions() -> Dict` | `experiments/agent_c/data/agent_c_b/memory.json`（共用 Agent B 账户） |
| `fetch_v15_martin_positions() -> Dict` | `14-V15经典马丁策略/data/v15_state.json` + OKX API；无 API key 时降级仅用 state 文件 |
| `fetch_yijing_positions() -> Dict` | `11-易经推理系统/.workbuddy/memory_l4/open_positions/*.json` |
| `fetch_three_screen_positions() -> Dict` | `http://127.0.0.1:8092/tracker/stats?sync=1`（ml_trade_service）；不可用时返回 `status="unavailable"` |

**单系统结果结构：**

```python
{
    "system": "agent_a",
    "exchange": "hyperliquid",
    "equity": 1234.56,
    "positions": [ <统一持仓对象> ],
    "position_count": 3,
    "status": "ok",                 # ok / partial / warning / error / unavailable
    "error": "",                    # status != "ok" 时存在
    # ...各系统特有 extra 字段
}
```

---

### 3.2 SKILL 引擎 API (core/skill_engine.py)

#### 3.2.1 SkillEngine 类

```python
class SkillEngine:
    SKILL_REGISTRY: Dict[str, Dict] = {}  # 类级注册表

    @classmethod
    def register(cls, skill_name: str, handler: Callable,
                 skill_path: str = "", version: str = "1.0.0") -> None

    def __init__(self, project_root: str = None)

    def load_skill_md(self, skill_name: str) -> Optional[str]
    def parse_skill_info(self, skill_md: str) -> Dict
    def parse_phases(self, skill_md: str) -> List[SkillPhase]

    def execute(self, skill_name: str, inputs: Dict[str, Any]) -> SkillResult
```

**`execute(skill_name, inputs)` 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| skill_name | str | 已注册的 SKILL 名称（如 `"dream-strategy-research"`） |
| inputs | Dict[str, Any] | 输入数据，结构由各 SKILL 自定义 |

**返回值 `SkillResult`：**

```python
@dataclass
class SkillResult:
    skill_name: str
    skill_version: str
    status: str = "completed"                # completed / error
    execution_mode: str = "code_adapter"
    phases_executed: List[str] = []
    data: Dict[str, Any] = {}                # handler 返回的数据
    error: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""

    def to_dict(self) -> Dict
```

**错误情形：**
- SKILL 未注册 → `status="error"`、`fallback_used=True`、`fallback_reason="not_registered"`
- handler 抛异常 → `status="error"`、`fallback_used=True`、`fallback_reason="handler_error: <异常类名>"`

**调用示例：**

```python
from core.skill_engine import SkillEngine

engine = SkillEngine()
result = engine.execute("dream-strategy-research", {
    "symbol": "BTC",
    "symbols": ["BTC", "ETH", "SOL"],
    "market_type": "crypto",
    "use_llm": False,
})
if result.status == "completed":
    print(result.data)
```

---

#### 3.2.2 register_skill 装饰器

```python
def register_skill(skill_name: str, skill_path: str = "", version: str = "1.0.0") -> Callable
```

将 handler 函数注册到 `SkillEngine.SKILL_REGISTRY`。装饰器返回原函数（不包装），因此被装饰函数仍可直接调用。

**用法：**

```python
@register_skill("my-skill", "path/to/SKILL.md", "1.0.0")
def my_skill_handler(inputs: Dict, engine) -> Dict:
    return {"result": ...}
```

---

#### 3.2.3 SkillPhase 数据类

```python
@dataclass
class SkillPhase:
    phase_id: str       # 如 "Phase 1" / "阶段 1"
    name: str
    description: str = ""
```

由 `SkillEngine.parse_phases(skill_md)` 从 SKILL.md 文本中正则解析得到。

---

### 3.3 A9 离场决策 API (core/a9_exit_decision.py)

#### 3.3.1 a9_exit_decision_handler

A9 四层决策链主入口，通过 `@register_skill` 注册为 `dream-exit-skill-v2` v2.2.0。

```python
@register_skill("dream-exit-skill-v2",
                "6-TRADING/skills/dream-exit-skill-v2/SKILL.md",
                "2.2.0")
def a9_exit_decision_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]
```

**输入 `inputs`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| positions | List[Dict] | 待评估的持仓列表（统一持仓格式） |
| a1_result | Dict | A1 调研结果（含 `research_report.market_state`） |
| a2_result | Dict | A2 第一性原理结果（含 `first_principles_analysis.synthesis.path_confidence`、`market_regime_classification.regime`） |
| a3_result | Dict | A3 策略设计结果（含 `strategy_directive.directive_bias`） |
| market | Dict | 市场数据（含 `atr_pct` 等） |

**四层决策链：**

| 层 | 名称 | 输入 | 作用 |
|----|------|------|------|
| Layer 1 | 战略方向一致性 | 持仓方向 vs A3 `directive_bias` | 计算 `alignment_score`（+1/0/-1） |
| Layer 2 | 置信度加权 | A2 `path_confidence` | `confidence_weight = 0.5 + 0.5 * path_confidence` |
| Layer 3 | 市场状态修正 | A2 `regime` | TREND_STRONG/BREAKOUT_PENDING +0.15；TREND_EXHAUSTION -0.2；EXTREME -0.3 |
| Layer 4 | 最终合成 + 紧急度 | final_score + 趋势阶段 + 盈亏 | 输出四态动作 + 紧急度 |

**`final_score` → 动作映射：**

| final_score | 动作 | 紧急度 |
|-------------|------|--------|
| ≤ -0.55 | CLOSE | CRITICAL |
| (-0.55, -0.30] | CLOSE | HIGH |
| (-0.30, -0.10] | REDUCE | MEDIUM |
| (-0.10, 0.10] | HOLD | LOW |
| (0.10, 0.30] 且趋势加速/启动 + 盈利 | RAISE_TP | LOW |
| (0.10, 0.30] 其他 | HOLD | LOW |
| > 0.30 且趋势加速 + 盈利 | RAISE_TP | MEDIUM |
| > 0.30 且盈利 | RAISE_TP | LOW |
| > 0.30 其他 | HOLD | LOW |

**返回值：**

```python
{
    "exit_evaluations": [ <单持仓评估> ],
    "overall_summary": {
        "total_evaluated": 12,
        "close_count": 1, "reduce_count": 2,
        "hold_count": 8,   "raise_tp_count": 1,
        "overall_stance": "REDUCE",          # CLOSE>REDUCE>RAISE_TP>HOLD 优先级
        "rationale": "有 2 个持仓建议减仓，注意风险控制",
        "urgency_breakdown": {"critical": 1, "high": 0, "medium": 2, "low": 9},
    },
    "decision_layers": {
        "layer1_strategy_alignment": "strategic direction vs position direction",
        "layer2_confidence_weighting": "A2 path_confidence weight",
        "layer3_regime_correction": "market regime adjustment",
        "layer4_final_synthesis": "urgency + final action",
    },
}
```

**单持仓评估对象：**

```python
{
    "position": {
        "symbol": "BTC", "system": "agent_a", "direction": "LONG",
        "size": 0.5, "entry_price": 60000.0,
        "current_price": 61000.0, "unrealized_pnl": 100.0,
    },
    "recommended_action": "REDUCE",            # CLOSE / REDUCE / HOLD / RAISE_TP
    "reason": "战略方向(SHORT)与持仓方向(LONG)矛盾，...",
    "urgency": "MEDIUM",                       # CRITICAL / HIGH / MEDIUM / LOW
    "confidence": 0.65,
    "scoring": {
        "alignment_score": -1.0, "lr_alignment": -1.0,
        "weighted_score": -0.825, "regime_bonus": 0.0, "final_score": -0.825,
    },
    "parameters": {
        "new_tp_price": 0.0,        # RAISE_TP 时为 new_tp_pct*current_price
        "new_tp_pct": 0.0,          # RAISE_TP 时为 min(atr_pct*4, 0.08)*100
        "reduce_fraction": 0.35,    # REDUCE 时为 max(0.25, min(0.5, 1-path_confidence))
    },
    "layers": {
        "layer1_alignment": {"position_direction": "LONG", "strategy_direction": "SHORT", "alignment_score": -1.0},
        "layer2_confidence": {"path_confidence": 0.65, "confidence_weight": 0.825},
        "layer3_regime": {"regime": "RANGE_BOUND", "trend_phase": "盘整", "regime_bonus": 0.0},
        "layer4_synthesis": {"final_score": -0.825, "action": "REDUCE", "urgency": "MEDIUM"},
    },
}
```

> ⚠️ **已知代码不一致**：`scripts/auto_exit_system.py:183` 调用了 `a9_exit_decision.evaluate_position_for_exit(pos, a3_result.data)`，但该函数在 `core/a9_exit_decision.py` 中**并不存在**（实际仅有 `a9_exit_decision_handler`）。直接运行 `auto_exit_system.py` 会在步骤 7 抛 `AttributeError`。详见 CHANGELOG 已知技术债。

---

### 3.4 宏观分析 SKILL 适配器 (A1/A2/A3)

三个适配器均通过 `@register_skill` 注册，由 `SkillEngine.execute(skill_name, inputs)` 调用。handler 直接函数签名相同：`(inputs: Dict, engine) -> Dict`。

| 模块文件 | SKILL 名称 | 版本 | handler 函数 |
|----------|-----------|------|--------------|
| `core/a1_research_adapter.py` | `dream-strategy-research` | 1.7.0 | `a1_research_handler(inputs, engine)` |
| `core/a2_first_principles_adapter.py` | `dream-first-principles` | 2.6.1 | `a2_first_principles_handler(inputs, engine)` |
| `core/a3_strategy_adapter.py` | `dream-strategy-designer` | 2.7.0 | `a3_strategy_designer_handler(inputs, engine)` |

**A1 输入关键字段：** `symbol`、`symbols`（最多 3 个）、`market_type`、`use_llm`
**A1 输出关键字段：** `research_report.market_state`（含 `atr_pct`、`rsi_1h` 等）

**A2 输入关键字段：** `research_result`（A1 的 `data`）、`use_llm`
**A2 输出关键字段：**
- `first_principles_analysis.synthesis.path_confidence`（0-1）
- `first_principles_analysis.synthesis.least_resistance_path`（UP/DOWN/NEUTRAL）
- `first_principles_analysis.trend_analysis.trend_phase`（盘整/启动期/加速期/...）
- `market_regime_classification.regime`（TREND_STRONG / BREAKOUT_PENDING / TREND_EXHAUSTION / FALSE_BREAKOUT_RISK / EXTREME / RANGE_BOUND）

**A3 输入关键字段：** `research_result`、`first_principles_result`、`use_llm`
**A3 输出关键字段：** `strategy_directive.directive_bias`（LONG / PROBE_LONG / DIP_BUY / SHORT / PROBE_SHORT / HEDGE / HOLD）

---

### 3.5 技术离场适配器 API (core/technical_exit_adapter.py)

#### 3.5.1 technical_exit_handler

```python
@register_skill("technical-exit-adapter",
                "10-经典指标系统/classic_exit_system.py",
                "1.0.0")
def technical_exit_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]
```

接入 ClassicExitSystem 作为技术离场 SSOT，与 A9 宏观离场融合。

**融合逻辑：**

| 场景 | 处理 |
|------|------|
| P0 安全硬退出（技术） | 一票否决，直接执行 |
| 技术信号 + 宏观确认（同向） | 强化建议 |
| 技术信号 vs 宏观矛盾 | 降级为观察，降低置信度 |
| 宏观信号 + 技术支持 | 强化 |
| 宏观信号 + 技术不支持 | 降级（减仓而非平仓） |

---

#### 3.5.2 TechnicalExitSignal 数据类

```python
@dataclass
class TechnicalExitSignal:
    action: str = "HOLD"            # CLOSE / REDUCE / HOLD / RAISE_TP
    urgency: str = "LOW"
    confidence: float = 0.5
    reason: str = ""
    source_layers: Dict[str, Any] = None
```

---

#### 3.5.3 fuse_macro_technical

融合宏观离场评估与技术离场信号，输出最终建议。

```python
def fuse_macro_technical(
    macro_evaluation: Dict[str, Any],
    technical_signal: TechnicalExitSignal,
    position_info: Dict[str, Any] = None,
    strategy_id: str = "",
) -> Dict[str, Any]
```

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| macro_evaluation | Dict | A9 单持仓评估结果（含 `recommended_action`、`urgency`、`confidence`） |
| technical_signal | TechnicalExitSignal | 技术离场信号 |
| position_info | Dict | 持仓上下文（含 `upl_ratio`、`open_time`、`addon_count`、`direction`、`system`） |
| strategy_id | str | 策略 ID，用于查询策略离场设计原则 |

**返回值：** 融合后的评估字典，包含 `recommended_action`、`urgency`、`confidence`、`fusion_mode`、`technical_input.p0_triggered` 等字段。

---

#### 3.5.4 _calc_simple_technical_signals

ClassicExitSystem 不可用时的降级方案，覆盖 P0-P2 核心逻辑（最大亏损/强平缓冲/持仓时间、RSI 超买超卖/ATR 止损止盈、三重屏障简化版）。

```python
def _calc_simple_technical_signals(
    position: Dict[str, Any],
    market_data: Dict[str, Any],
    market_state: Dict[str, Any],
) -> TechnicalExitSignal
```

---

### 3.6 离场执行器 API (core/exit_executor.py)

#### 3.6.1 ExitExecutor 类

```python
class ExitExecutor:
    def __init__(self,
                 mode: str = "dry_run",
                 max_executions_per_cycle: int = 5,
                 min_position_usdt: float = 1.0)

    def execute_evaluations(self, fused_evaluations: List[Dict]) -> List[Dict]
```

**`__init__` 参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| mode | str | "dry_run" | 执行模式：`dry_run` / `simulated` / `real` |
| max_executions_per_cycle | int | 5 | 每周期最多执行笔数（防批量砸盘） |
| min_position_usdt | float | 1.0 | 最小执行仓位 USDT 价值 |

**`execute_evaluations` 流程：**
1. 过滤 `HOLD` / `OBSERVE` / `RAISE_TP` 动作（直接 SKIPPED）
2. 达到 `max_executions_per_cycle` 上限后跳过
3. 逐条 `_execute_single`：权限检查 → 最小仓位检查 → dry_run / real 执行
4. 执行成功时尝试注册到 L4 TradeEvent（跨系统统一记录，依赖 `11-易经推理系统/scripts/memory_l4`）
5. 全部完成后保存执行日志到 `artifacts/execution_logs/exit_execution_<时间戳>.json`

**返回值：** 每条评估对应的执行结果字典列表，含 `status`、`order_id`、`executed_size`、`execution_price`、`actual_pnl` 等字段。

---

#### 3.6.2 ExecutionMode / ExecutionStatus 枚举

```python
class ExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    SIMULATED = "simulated"
    REAL = "real"

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"
```

---

#### 3.6.3 ExitExecution 数据类

```python
@dataclass
class ExitExecution:
    execution_id: str
    timestamp: str
    strategy_id: str
    system_name: str
    symbol: str
    direction: str
    action: str               # CLOSE / REDUCE / HOLD / OBSERVE
    confidence: float
    urgency: str
    mode: str                 # dry_run / simulated / real
    allowed: bool
    rejection_reason: str = ""
    status: str = "pending"
    order_id: str = ""
    executed_size: float = 0.0
    execution_price: float = 0.0
    actual_pnl: float = 0.0
    error_message: str = ""
    position_size: float = 0.0
    entry_price: float = 0.0
    reduce_fraction: float = 0.0
    fusion_mode: str = ""
```

---

#### 3.6.4 create_executor_from_env

从环境变量构造执行器。

```python
def create_executor_from_env() -> ExitExecutor
```

**环境变量映射：**

| 环境变量 | 参数 | 默认值 |
|----------|------|--------|
| `EXIT_MODE` | mode | `dry_run` |
| `MAX_EXECUTIONS` | max_executions_per_cycle | `5` |
| `MIN_POSITION_USDT` | min_position_usdt | `1.0` |

未知 `EXIT_MODE` 值会打印警告并降级为 `dry_run`。

---

### 3.7 权限反馈 API (core/feedback_and_permission.py)

#### 3.7.1 PermissionLevel 枚举

```python
class PermissionLevel(str, Enum):
    NOTIFY = "NOTIFY"                # 仅通知，不执行
    ADVISE = "ADVISE"                # 建议执行，人工确认
    AUTO_REDUCE = "AUTO_REDUCE"      # 自动减仓（≤ max_auto_reduce_pct）
    AUTO_CLOSE = "AUTO_CLOSE"        # 自动平仓（仅限 P0 安全硬退出）
    FULL_AUTO = "FULL_AUTO"          # 全自动
```

权限等级从低到高：`NOTIFY(0) < ADVISE(1) < AUTO_REDUCE(2) < AUTO_CLOSE(3) < FULL_AUTO(4)`。

---

#### 3.7.2 can_auto_execute

判断是否可自动执行建议。

```python
def can_auto_execute(system_name: str, action: str, urgency: str) -> Dict[str, Any]
```

**参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| system_name | str | 系统名称 |
| action | str | 建议动作（CLOSE/REDUCE/HOLD/RAISE_TP） |
| urgency | str | 紧急度（LOW/MEDIUM/HIGH/CRITICAL） |

**返回值：**

```python
{
    "can_execute": bool,
    "reason": str,
    "max_reduce_pct": float,       # 仅 REDUCE 时有意义
    "permission_level": str,
}
```

**判定逻辑：**
1. `HOLD` / `RAISE_TP` → 不可执行（无需执行）
2. `FULL_AUTO` → 可执行
3. `urgency` 低于系统 `auto_execute_urgency` 阈值 → 不可执行
4. `CLOSE` → 需 `AUTO_CLOSE` 或更高
5. `REDUCE` → 需 `AUTO_REDUCE` 或更高，受 `max_auto_reduce_pct` 限制

---

#### 3.7.3 record_feedback

记录建议反馈。

```python
def record_feedback(
    evaluation_id: str,
    system_name: str,
    symbol: str,
    position_direction: str,
    recommended_action: str,
    recommendation_urgency: str,
    recommendation_confidence: float,
    feedback_action: str,            # ACCEPTED / REJECTED / PARTIAL / PENDING
    executed_action: str = "",
    executed_pct: float = 0.0,
    note: str = "",
) -> Dict[str, Any]
```

**返回值：** 反馈记录字典。文件落盘到 `artifacts/feedback/feedback_<evaluation_id>.json`，按 `(system_name, symbol)` 去重 upsert。

---

#### 3.7.4 get_feedback_stats

```python
def get_feedback_stats(max_evaluations: int = 20) -> Dict[str, Any]
```

返回最近 `max_evaluations` 次评估的反馈统计，含 `total_evaluations`、`total_records`、`accepted_count`、`rejected_count`、`partial_count`、`pending_count`、`acceptance_rate`、`by_system`。

---

#### 3.7.5 set_system_permission / get_system_permission

```python
def set_system_permission(system_name: str, permission_level: str,
                          auto_execute_urgency: str = "CRITICAL",
                          max_auto_reduce_pct: float = 0.3,
                          notes: str = "") -> Dict[str, Any]

def get_system_permission(system_name: str) -> Dict[str, Any]
```

`set_system_permission` 传入无效 `permission_level` 会抛 `ValueError`。配置文件落盘到 `16-调控系统/config/permission_config.json`，不存在时使用 `DEFAULT_SYSTEM_PERMISSIONS`。

---

### 3.8 进化闭环 API (core/evolution_loop.py / enhanced_evolution.py)

#### 3.8.1 EvolutionLoop（基础闭环）

```python
class EvolutionLoop:
    def record_decision(self, evaluation: Dict[str, Any]) -> str
    def record_outcome(self, decision_id: str, outcome: str,
                       actual_pnl: float, exit_price: float,
                       source: str) -> None
    def analyze_accuracy(self, strategy_id: str = None) -> Dict[str, Any]
    def get_evolved_params(self, strategy_id: str) -> Dict[str, float]

def get_evolution_loop() -> EvolutionLoop   # 单例
```

7 步闭环：① 记录决策 → ② 追踪结果 → ③ 分析准确性 → ④ 参数调优 → ⑤ 反馈决策 → ⑥ 回测验证 → ⑦ 采纳/回滚。

---

#### 3.8.2 EnhancedEvolutionLoop（增强闭环）

```python
class EnhancedEvolutionLoop:
    def record_decision(self, evaluation: Dict[str, Any]) -> str
    def record_outcome(self, decision_id: str, outcome: str,
                       actual_pnl: float, exit_price: float, source: str) -> None
    def run_a8_inspection(self, strategy_id: str = None) -> Dict
    def run_dream_analysis(self, strategy_id: str = None) -> Dict
    def run_full_evolution_cycle(self, min_samples: int = 5,
                                 run_backtest: bool = False) -> Dict
    def get_evolved_params(self, strategy_id: str) -> Dict[str, float]
    def get_summary(self) -> Dict[str, Any]

def get_enhanced_evolution() -> EnhancedEvolutionLoop   # 单例
```

**三层进化：**
- Layer 1：A8 理论实践验证（内部自我批评）
- Layer 2：做梦部潜意识分析（外部视角反思）
- Layer 3：数据驱动调优（历史准确性参数自适应）

**验证三层：** 回测验证 + Walk-Forward 滚动前向 + 7 天观察期再采纳。

集成 DreamOS `gap_score`、三屏置信度校准（ECE/Platt Scaling）、过拟合检测（参数敏感性/置换检验）。

**`get_evolved_params` 返回的关键参数：**

```python
{
    "confidence_threshold_close": 0.70,     # 平仓置信度门槛
    "confidence_threshold_reduce": 0.60,    # 减仓置信度门槛
    # ...其他可进化参数
}
```

---

### 3.9 回测框架 API (core/backtest_framework.py)

#### 3.9.1 generate_simulated_bars

生成模拟 K 线（几何布朗运动 + 波动率聚集）。

```python
def generate_simulated_bars(
    start_price: float = 60000,
    num_bars: int = 500,
    volatility_pct: float = 2.0,
    drift_pct: float = 0.0,
    timeframe_min: int = 60,
    seed: int = 42,
) -> List[Bar]
```

**返回值：** `Bar` 数据类列表，字段 `timestamp` / `open` / `high` / `low` / `close` / `volume`。

---

#### 3.9.2 run_backtest

运行单策略回测。

```python
def run_backtest(
    bars: List[Bar],
    strategy: str = "macro_enhanced",     # baseline / macro_enhanced / hold
    entry_interval: int = 30,
    max_positions: int = 3,
    direction: str = "random",            # LONG / SHORT / random
    leverage: float = 1.0,
    strategy_name: str = "",
    use_macro: bool = True,
    tech_weight: float = 0.5,
    macro_weight: float = 0.5,
    close_threshold: float = 0.70,
    reduce_threshold: float = 0.60,
) -> BacktestResult
```

**策略对比矩阵：**

| 策略名 | 入场 | 离场 | 说明 |
|--------|------|------|------|
| `baseline` | 随机 | 技术指标 | 纯技术离场基准 |
| `macro_enhanced` | 随机 | 宏观+技术融合 | 宏观赋能离场 |
| `hold` | 随机 | 持有到结束 | 买入持有基准 |

**返回值 `BacktestResult`：**

```python
@dataclass
class BacktestResult:
    strategy_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_factor: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    avg_bars_held: float = 0.0
    trades: List[TradeRecord] = []
    equity_curve: List[float] = []
```

---

#### 3.9.3 辅助数据类与枚举

```python
class ExitAction(str, Enum):
    CLOSE = "CLOSE"; REDUCE = "REDUCE"; HOLD = "HOLD"; RAISE_TP = "RAISE_TP"

@dataclass
class Bar: timestamp, open, high, low, close, volume=0.0
@dataclass
class Position: symbol, direction, entry_price, entry_time, size=1.0,
               current_price=0.0, unrealized_pnl_pct=0.0,
               stop_loss=0.0, take_profit=0.0, is_open=True
@dataclass
class TradeRecord: symbol, direction, entry_price, entry_time,
                   exit_price, exit_time, pnl_pct, exit_reason, bars_held
```

---

### 3.10 AAM 产物投递 API (core/aam_deliverer.py)

#### 3.10.1 deliver_exit_evaluation

```python
def deliver_exit_evaluation(
    full_data: Dict[str, Any],
    report_md: str,
    # ... 其他可选参数
) -> "DeliveryResult"
```

**双通道投递：**
1. 秘书邮箱：`~/.workbuddy/skills/boss-secretary/reports/trading/`
2. 前端产物中心：`~/.workbuddy/artifacts/trading/`

同时更新 `index.json` 并执行投递验证。

---

#### 3.10.2 其他函数

```python
def generate_frontmatter(...) -> Dict
def deliver_artifact(...) -> "DeliveryResult"
def list_delivered_artifacts(channel: str = "frontend_artifact_center", ...) -> List[Dict]

@dataclass
class DeliveryResult:
    # 投递结果（成功/失败、各通道状态、文件路径等）
    ...
```

---

### 3.11 CLI 命令 (scripts/)

#### 3.11.1 auto_exit_system.py — 自动化调度主脚本

```bash
python scripts/auto_exit_system.py
```

执行一次完整的离场评估周期（10 步流程）：初始化 → 查询持仓 → 市场数据 → A1 → A2 → A3 → 技术离场 → A9 融合 → 执行 → 进化闭环 → 报告投递。

**环境变量：**

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `EXIT_MODE` | `dry_run` | 执行模式：`dry_run` / `simulated` / `real` |
| `USE_LLM` | `0` | 是否启用 LLM 增强（`1`/`0`） |
| `DELIVER` | `0` | 是否投递到 AAM（`1`/`0`） |
| `MAX_EXECUTIONS` | `5` | 单周期最大执行笔数 |
| `MIN_POSITION_USDT` | `1.0` | 最小执行仓位 USDT |
| `EVOLUTION` | `1` | 是否运行进化闭环（`1`/`0`） |
| `BACKFILL` | `0` | 是否回填历史决策结果（`1`/`0`） |

**日志输出：** 控制台 + `16-调控系统/logs/exit_system_<YYYYMMDD>.log`

**产物输出：**
- `artifacts/exit-evaluations/auto_exit_<YYYYMMDD_HHMMSS>.json`
- `artifacts/exit-evaluations/auto_exit_<YYYYMMDD_HHMMSS>.md`
- `artifacts/execution_logs/exit_execution_<YYYYMMDD_HHMMSS>.json`

> ⚠️ **已知 Bug**：脚本第 183 行调用 `a9_exit_decision.evaluate_position_for_exit(...)`，该函数不存在，运行到步骤 7 会抛 `AttributeError`。详见 CHANGELOG。

---

#### 3.11.2 其他脚本

| 脚本 | 用途 |
|------|------|
| `scripts/phase0_exit_evaluator.py` | Phase 0 MVP 离场评估（技术通路验证） |
| `scripts/phase2_exit_evaluator.py` | Phase 2 离场评估（SKILL 引擎集成） |
| `scripts/phase3_exit_evaluator.py` | Phase 3 离场评估（决策执行层完整版）；支持 `USE_LLM` / `DELIVER` / `BACKTEST` / `USE_REALTIME` 环境变量 |
| `scripts/test_e2e_exit_system.py` | E2E 离场系统测试，产物 `artifacts/tests/e2e_exit_test.json` |
| `scripts/stress_test_7scenarios.py` | 7 场景压力测试（步进式笔记本框架 + 三链门禁 + 笔记本钩子） |
| `scripts/write_health_status.py` | 系统健康状态写入 `3-EVOLUTION/health_dashboard.json`，供元链治理周报使用 |
| `scripts/step_controller.py` | 步骤控制器 |
| `scripts/skill_importer.py` | SKILL 导入器 |
| `scripts/notebook_hook.py` / `notebook_stress_test.py` | Notebook 钩子与压力测试 |
| `scripts/test_strategy_exit_adapter.py` | 策略离场适配器测试 |
| `scripts/review_filter.py` | 复盘过滤器 |
| `scripts/sync_artifact.py` | 产物同步 |

---

## 4. 错误码

本系统使用字符串状态码而非数字错误码。以下是统一的状态/错误枚举：

### 4.1 持仓查询状态 (`overall_status` / `system_status`)

| 状态 | 含义 |
|------|------|
| `ok` | 正常 |
| `partial` | 部分降级（如 V15 缺 OKX API key，仅用 state 文件） |
| `warning` | 警告（如目录不存在但非致命） |
| `error` | 错误（异常被捕获） |
| `unavailable` | 依赖服务不可用（如 ml_trade_service 未启动） |
| `degraded` | 聚合状态：至少 1 个 error 但还有 ok |
| `failed` | 聚合状态：全部 error |

### 4.2 SKILL 执行状态 (`SkillResult.status`)

| 状态 | 含义 |
|------|------|
| `completed` | 正常完成 |
| `error` | 执行异常，`fallback_used=True`，`fallback_reason` 取值：`not_registered` / `handler_error: <异常类名>` |

### 4.3 离场执行状态 (`ExecutionStatus`)

| 状态 | 含义 |
|------|------|
| `pending` | 待执行 |
| `executing` | 执行中 |
| `success` | 执行成功 |
| `failed` | 执行失败（`error_message` 字段提供详情） |
| `skipped` | 跳过（HOLD/OBSERVE/RAISE_TP 动作，或达到单周期上限，或仓位低于最小值） |
| `rejected` | 权限拒绝（`rejection_reason` 字段提供原因） |

### 4.4 权限拒绝原因 (`can_auto_execute.reason`)

| 触发条件 | reason 示例 |
|----------|-------------|
| HOLD/RAISE_TP | `HOLD 类建议无需自动执行` |
| 紧急度不足 | `紧急度(MEDIUM)低于自动执行阈值(CRITICAL)` |
| CLOSE 权限不足 | `权限等级(ADVISE)不允许自动平仓，需要人工确认` |
| REDUCE 权限不足 | `权限等级(NOTIFY)不允许自动减仓` |
| 未知动作 | `未知动作类型` |

### 4.5 进化闭环决策结果 (`record_outcome.outcome`)

| 取值 | 含义 |
|------|------|
| `CORRECT` | 决策正确（如平仓后行情继续反向） |
| `INCORRECT` | 决策错误 |

---

## 5. 版本管理

### 5.1 文档版本

| 版本 | 日期 | 变更 |
|------|------|------|
| v2.0 | 2026-07-25 | 首版 API_SPEC.md，对齐 `core/` 实际代码（19 个核心 Python 文件），覆盖持仓查询/SKILL 引擎/A9 决策/技术融合/执行器/权限/进化/回测/AAM 投递/CLI 全链路 |

### 5.2 SKILL 版本矩阵

| SKILL 名称 | 版本 | 注册模块 |
|-----------|------|----------|
| `dream-strategy-research` | 1.7.0 | `core/a1_research_adapter.py` |
| `dream-first-principles` | 2.6.1 | `core/a2_first_principles_adapter.py` |
| `dream-strategy-designer` | 2.7.0 | `core/a3_strategy_adapter.py` |
| `dream-exit-skill-v2` | 2.2.0 | `core/a9_exit_decision.py` |
| `technical-exit-adapter` | 1.0.0 | `core/technical_exit_adapter.py` |

### 5.3 接口版本策略

- **Python API**：通过 `core/__init__.py` 导出的公共符号（`fetch_all_positions` / `get_position_summary` / `SkillEngine` / `SkillResult` / `register_skill`）视为稳定接口，跨版本保持向后兼容。
- **SKILL 版本**：由 `@register_skill(name, path, version)` 显式声明，每个 SKILL 独立版本号。SKILL.md 路径变更需同步更新装饰器参数。
- **持仓查询数据格式**：`fetch_all_positions` 返回值含 `"version": "1.0"` 字段，未来字段变更需提升该版本号。
- **CLI 环境变量**：现有 7 个环境变量（`EXIT_MODE`/`USE_LLM`/`DELIVER`/`MAX_EXECUTIONS`/`MIN_POSITION_USDT`/`EVOLUTION`/`BACKFILL`）视为稳定契约，新增环境变量不破坏旧值语义。
- **未版本化内部模块**：未通过 `core/__init__.py` 导出的函数/类（如 `_evaluate_single_position`、`_calc_simple_technical_signals` 等下划线前缀私有函数）不保证跨版本稳定。

---

_最后更新：2026-07-25 | 来源：16-调控系统（统一 AI 调控系统）_
