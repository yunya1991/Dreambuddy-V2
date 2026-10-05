---
name: dream-subagent-tdd-workflow
description: "Orchestrates DSH subagent TDD: RED test (ModuleNotFoundError) → GREEN impl (subagent_types.py shared contract) → IPC handler registration → cognitive closure. Invoke for subagent dev, macro/flow/onchain/valuation/risk/portfolio agent."
version: 1.0.0
created: 2026-09-24
updated: 2026-09-24
license: Internal
status: active
category: orchestration
triggers: [subagent TDD, subagent 开发, RED-GREEN-IPC, macro-agent, flow-agent, onchain-agent, valuation-agent, risk-agent, portfolio-agent]
depends_on: [dream-tdd-dev-workflow, tee-red-green-progress, test-driven-development]
provides: [subagent-tdd-orchestration]
cognitive_links: [VM-1790261456324-ba7d24fb, VM-1790262741311-786a4b67, VM-1790262869228-c8c3cfee, VM-1790262886147-84ec91f1]
---

## Autonomy Boundary

可自主执行：
- 任务编排与流程调度
- 节点间数据流转发
- 编排优化与节点选择
- 执行状态监控与汇报

需用户确认：
- 涉及实盘交易的编排执行
- 修改核心编排规则

禁止：
- 将编排结论直接作为交易指令执行
- 绕过风控或审批流程


# Dream Subagent TDD Workflow — DSH Subagent TDD 开发工作流 SKILL

> 把"RED 测试（断言 ModuleNotFoundError）→ GREEN 实现（subagent_types.py 共享契约 + FAIL-OPEN）→ IPC handler 注册 → 认知闭环"的 DSH subagent 开发循环固化为可复用编排。元 SKILL 为 `dream-tdd-dev-workflow`，本 SKILL 聚焦 DSH subagent 域特有模式。

> **双位置存储**：本 SKILL 同时存在于：
> - `.trae/skills/dream-subagent-tdd-workflow/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-subagent-tdd-workflow/SKILL.md`（项目级索引发现，本文件）

---

## 一、何时调用（触发条件）

满足以下任一条件即应调用本 SKILL：

1. **DSH subagent 开发**：需要为 DreamOS SACG 架构新增一个 subagent（technical/sentiment/macro/flow/onchain/valuation/risk/portfolio）
   - 触发词：「subagent TDD」「subagent 开发」「RED-GREEN-IPC」「macro-agent」「flow-agent」「onchain-agent」「valuation-agent」「risk-agent」「portfolio-agent」
2. **Spec §3.2 节点扩展**：需要为某个 F 链节点（F1~F5）或 C 链节点新增对应的 subagent 提炼层
3. **hermes 反思衍生**：P0 试点完成后，后续 P1/P2 subagent 开发复用本 SKILL

**与 `dream-tdd-dev-workflow` 的边界**：`dream-tdd-dev-workflow` 是通用 TDD 5 步编排（需求→RED→GREEN→REFACTOR→hermes）；本 SKILL 是 DSH subagent 域特化版本，新增 **IPC handler 注册** 步骤，强制使用 `subagent_types.py` 共享契约，并遵循 HC-1~HC-8 subagent 硬约束。

---

## 二、4 步标准流程

### 步骤 1：RED — 写失败测试

**输入**：subagent 需求（来自 Spec §3.2 节点定义）

**处理**：
1. 确定目标节点（如 F5=macro, F2=flow, F4=onchain, F3=valuation）
2. 写测试文件 `test_<module>_agent.py`，放在 `python-server/` 顶层（与 `jev_judge.py` 约定一致，非 `modules/` 子目录）
3. 第一个测试断言 `ModuleNotFoundError`（TEE Task N→N+1 标准起手）
4. 后续测试覆盖：信号提取、摘要生成、图表生成、FAIL-OPEN 降级、IPC handler
5. 测试用 `sys.path.insert(0, SERVER_DIR)` 处理导入

**RED 示例**（以 macro-agent 为例）：

```python
# test_macro_agent.py
import sys, os
SERVER_DIR = os.path.join(os.path.dirname(__file__), "..", "python-server")
sys.path.insert(0, SERVER_DIR)

import pytest

def test_module_importable():
    with pytest.raises(ModuleNotFoundError):
        from macro_agent import MacroAgent  # noqa

def test_extract_gdp_signal():
    from macro_agent import MacroAgent
    agent = MacroAgent()
    output = agent.execute({"indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1}})
    assert output.module == "macro"
    assert len(output.signals) > 0

def test_llm_fn_none_fails_open():
    from macro_agent import MacroAgent
    agent = MacroAgent(llm_fn=None)
    output = agent.execute({"indicators": {}})
    assert output.summary  # 规则生成, 非空

def test_ipc_handler():
    from macro_agent import handle_macro_agent
    result = handle_macro_agent({"node_output": {"indicators": {"gdp_yoy": 2.5}}})
    assert result["ok"] is True
```

**运行确认 RED**：

```bash
cd 1-ARCHITECTURE/dream-harness-bridge/packages/python-server
python -m pytest test_macro_agent.py -v
# 预期：4 failed（第 1 个 ModuleNotFoundError，其余连锁失败）
# red count = 4 → RED 确认
```

**输出**：测试文件路径 + RED 运行日志

### 步骤 2：GREEN — 最简实现通过测试

**输入**：测试文件 + 节点定义

**处理**：
1. 写实现文件 `<module>_agent.py`，放在 `python-server/` 顶层
2. 导入 `subagent_types.py` 共享契约（`SubagentOutput` / `Signal` / `ChartSpec`）
3. 实现 `<Module>Agent` 类：`__init__(self, llm_fn=None)` + `execute(node_output: dict) -> SubagentOutput`
4. 从节点已验证输出提取 signals（**HC-1: LLM 只提炼不生成原始数据**）
5. 生成 charts（**HC-6: ECharts option 格式**）
6. `llm_fn` 为 None 或异常时 → 规则降级（**FAIL-OPEN**）
7. 实现 `handle_<module>_agent(params: dict) -> dict` IPC handler

**GREEN 示例**（macro-agent）：

```python
# macro_agent.py
from __future__ import annotations
import traceback
from typing import Any, Callable, Dict, List, Optional
from subagent_types import ChartSpec, Signal, SubagentOutput

class MacroAgent:
    """宏观面 subagent: F5 节点输出 → SubagentOutput"""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def execute(self, node_output: dict) -> SubagentOutput:
        indicators = node_output.get("indicators", {})
        signals = self._extract_signals(indicators)
        summary = self._generate_summary(signals, indicators)
        charts = self._generate_charts(indicators)
        return SubagentOutput(
            module="macro", summary=summary,
            signals=signals, charts=charts, raw_data=node_output,
        )

    def _extract_signals(self, indicators: Dict[str, Any]) -> List[Signal]:
        signals: List[Signal] = []
        gdp = indicators.get("gdp_yoy", 0)
        cpi = indicators.get("cpi_yoy", 0)
        rate = indicators.get("interest_rate", 0)

        if gdp > 2.0:
            signals.append(Signal("GDP同比", gdp, "long", 0.7))
        elif gdp < 0:
            signals.append(Signal("GDP同比", gdp, "short", 0.7))

        if cpi > 5:
            signals.append(Signal("CPI同比", cpi, "short", 0.6))
        elif cpi < 1:
            signals.append(Signal("CPI同比", cpi, "long", 0.5))

        return signals

    def _generate_summary(self, signals, indicators):
        if self._llm_fn is not None:
            try:
                prompt = f"宏观摘要: signals={signals}, indicators={indicators}"
                return self._llm_fn(prompt)[:300]
            except Exception:  # FAIL-OPEN
                pass
        long_n = sum(1 for s in signals if s.direction == "long")
        short_n = sum(1 for s in signals if s.direction == "short")
        return f"宏观面多{long_n}/空{short_n}"

    def _generate_charts(self, indicators):
        charts: List[ChartSpec] = []
        if indicators:
            charts.append(ChartSpec(
                type="bar", title="宏观指标概览",
                data=indicators,
                config={"yAxis": {"type": "value"}},
            ))
        return charts

def handle_macro_agent(params: dict) -> dict:
    try:
        agent = MacroAgent()
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
```

**运行确认 GREEN**：

```bash
python -m pytest test_macro_agent.py -v   # 预期：4 passed → GREEN
# 全量回归：
python -m pytest test_c_drive_agent.py test_technical_agent.py test_sentiment_agent.py test_macro_agent.py -v
# 预期：原 74 + 新 4 = 78 passed → 零回归
```

**输出**：实现文件路径 + GREEN 日志 + 零回归日志

### 步骤 3：IPC handler 注册

**输入**：GREEN 实现 + server.py

**处理**：
1. 打开 `python-server/server.py`，找到 IPC 路由 dispatch 区域
2. 新增 `elif method == "<module>_agent":` 分支，调用 `handle_<module>_agent`
3. 确认注册无语法错误

**注册示例**：

```python
# server.py IPC dispatch 区域
elif method == "macro_agent":
    from macro_agent import handle_macro_agent
    return handle_macro_agent(params)
```

**验证**：

```bash
# 启动 server 确认无 import 错误（可选，视开发环境而定）
python -c "from server import *; print('ok')"
```

**输出**：server.py 修改 diff + 验证日志

### 步骤 4：认知闭环（record + verify + hermes 反思）

**输入**：GREEN 实现 + IPC 注册完成

**处理**：
1. 调用 `record` 记录本次 subagent 开发经验
2. 如验证了已有记忆，调用 `verify`
3. hermes 反思：评估是否衍生新 SKILL（通常本 SKILL 已覆盖，仅 record）

**record 模板**：

```
record(
  content="[P1 subagent] <module>_agent.py 完成, <N>/<N> 测试 GREEN, 零回归(<原+N> passed). 关键设计: (1)从<节点>提取signals; (2)图表: <chart类型>; (3)llm_fn可注入, FAIL-OPEN; (4)IPC handler已注册",
  quality_level="B",
  tags="P1,<module>-agent,SubagentOutput,FAIL-OPEN,HC-1,TDD"
)
```

---

## 三、Subagent 节点数据源速查（Spec §3.2）

| Subagent | 节点 | 数据字段 | 图表类型 |
|----------|------|---------|---------|
| technical | C1/C2/C3 | ema/rsi/macd/volume | candlestick/line |
| sentiment | F1 | sentiment{impact,score,fgi} | gauge/line |
| macro | F5 | gdp/cpi/rate/liquidity | bar+趋势线 |
| flow | F2 | etf/leverage/stablecoin | sankey+bar |
| onchain | F4 | active_addr/hashrate/mvrv | line+heatmap |
| valuation | F3 | nvt/stock_to_flow | scatter+回归线 |
| risk | 新建 | var/correlation/stress | heatmap+矩阵 |
| portfolio | 新建 | positions/rebalance | pie+bar |

---

## 四、架构硬约束（HC-1~HC-8）

| HC | 约束 | 本 SKILL 落实 |
|----|------|-------------|
| HC-1 | LLM 只提炼不生成原始数据 | signals 从节点已验证 indicators 提取 |
| HC-5 | SubagentOutput 契约 | 所有 subagent 返回 SubagentOutput |
| HC-6 | 图表 ECharts option 格式 | ChartSpec.config 使用 ECharts option |
| HC-7 | subagent 间禁止通信 | 只与 C-Drive-Agent 交互 |
| HC-8 | Bull/Bear 并行调用 | C-Drive-Agent 层负责，subagent 不涉及 |
| FAIL-OPEN | llm_fn None/异常 → 规则降级 | try/except 包裹 LLM 调用 |
| 零回归 | 独立新模块不改现有 | 新文件放 python-server/ 顶层 |

---

## 五、输入输出契约

| 阶段 | 输入 | 输出 |
|------|------|------|
| 步骤 1 | 节点定义 + Spec §3.2 | test_<module>.py + RED 日志 |
| 步骤 2 | 测试文件 | <module>_agent.py + GREEN 日志 + 零回归日志 |
| 步骤 3 | GREEN 实现 + server.py | server.py diff + 注册验证 |
| 步骤 4 | 全部完成 | record + verify + hermes 反思 |

---

## 六、相关 SKILL

| 类型 | 名称 | 用途 |
|------|------|------|
| 元 | `dream-tdd-dev-workflow` | 通用 TDD 5 步编排（本 SKILL 的元） |
| 工具 | `tee-red-green-progress` | TEE Task N→N+1 红绿进度 |
| 工具 | `test-driven-development` | 通用 TDD 方法论 |
| 上游 | DSH Subagent Architecture Spec | 节点定义 + 契约规范 |
| 认知 | `recall`/`record`/`verify` | 认知闭环 |

---

## 七、认知闭环

**任务开始前**（硬约束）：

```
recall(context="subagent TDD <module> agent", top_k=5, min_quality="C")
```

**任务完成后**：

```
record(content="<本次 subagent 摘要> | <N>/<N> GREEN | 回归 <原+N> passed",
       quality_level="B",
       tags="P1,<module>-agent,SubagentOutput,FAIL-OPEN,HC-1,TDD")
```

**已沉淀的认知记忆**：

| Memory ID | 等级 | 内容摘要 |
|-----------|------|---------|
| VM-1790261456324-ba7d24fb | B | DSH Subagent 架构硬约束 |
| VM-1790262741311-786a4b67 | B | P0-2 C-Drive-Agent 四步循环经验 |
| VM-1790262869228-c8c3cfee | B | P0-3 technical/sentiment agent 试点 |
| VM-1790262886147-84ec91f1 | B | hermes 反思结论（本 SKILL 来源） |

---

## 八、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-09-24 | 初始版本，4 步流程 + 6 节点速查 + HC-1~HC-8 约束映射 |
