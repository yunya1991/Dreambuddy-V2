# SPEC-20261012-DSH-v0.4 — DSH 层训练数据源（TDD 核心重构版）

> **版本**: v0.4 (TDD核心重构 — 评审问题修复 + TDD测试为主数据源)
> **日期**: 2026-10-12
> **作者**: Trae + User
> **状态**: Draft（待评审）
> **关联**: SPEC-DSH-训练数据源-v0.3-扩展.md (v0.3 评审7问题), SPEC-DSH-训练数据源.md (v0.2 已实现4采集器)
> **方法论**: recall → v0.3评审7问题 → TDD测试文件调研(388+文件) → SPEC v0.4
> **目标层**: DSH 层 (ExecutionPathTrainingLoop — 序列模式挖掘 + 路径模板)
> **v0.4 变更**:
> - **P0 核心变更**: TDD 测试文件作为 P0 核心数据源（388+文件，~1000+ DSH条），替换 v0.3 有问题的日志/数据库方案
> - 修复 v0.3 全部 7 个评审问题
> - v0.3 的日志/认知/REA 降级为 P1-P3 补充数据源
> - node_sequence 从 AST 解析真实测试代码，彻底解决静态模板问题
> - 新增 .cognitive/sessions/ 作为 P1 数据源（v0.3 完全遗漏）

---

## 0. Executive Summary

### 0.1 v0.3 评审问题 → v0.4 修复对照

| # | v0.3 问题 | 严重度 | v0.4 修复方案 |
|---|----------|--------|--------------|
| 1 | all_trades.jsonl 声称37万条，实际仅152条 | P0 | **P0 改为 TDD 测试**（388+文件，数据量充足）；all_trades.jsonl 降为 P2 補充 |
| 2 | node_sequence 全是静态模板，无决策过程 | P0★ | **AST 解析测试函数体**提取真实调用链；参数化场景生成多样 node_sequence |
| 3 | 完全遗漏 .cognitive/sessions/ 558个会话 | P1 | **新增 P1: CognitiveSessionCollector** |
| 4 | REA 报告预期30-60条，实际仅1份JSON | P3 | **P3 改为 REA测试文件**(22个) + 1份JSON报告，预期降为~60条 |
| 5 | 与 trading_log_collector 关系未说明 | P2 | **明确差异化**: trading_log_collector 是 S/C 层日志采集，v0.4 是 DSH 层代码测试采集 |
| 6 | 缺 TDD 规划 | P1 | **TDD 测试本身就是核心数据源**，RED→GREEN 循环 = 训练数据生成管道 |
| 7 | 缺认知闭环 | P1 | **§7 新增认知闭环**：record + verify 步骤 |

### 0.2 核心命题

v0.3 试图从运行日志和数据库中挖掘决策序列，但发现：
- all_trades.jsonl 只有最终交易结果，**无决策过程**
- memories 表只存最终记忆，**无 recall→record→verify 调用链**
- shadow_validation 样本只有交易结果，**无进化过程节点**

**v0.4 核心转变**: TDD 测试文件**天然就是决策序列** — 每个测试函数包含 场景设定 → 执行步骤 → 断言结果，直接映射 DSH 的 `task → node_sequence → outcome` 格式。

| 优先级 | 数据源 | 数据域 | 采集方式 | 预期条数 |
|--------|--------|--------|---------|---------|
| **P0** | TDD 测试文件 | 代码决策逻辑 | AST 解析 test_*.py | **800-1200** |
| **P1** | .cognitive/sessions/ 会话 | 认知推理链 | 会话目录扫描 | 40-80 |
| **P2** | polling_trader 日志 | 交易执行链(补充) | 日志关键词提取 | 30-60 |
| **P3** | REA 测试+报告 | 逆向工程 | 测试AST+JSON解析 | 40-80 |
| **P4** | shadow_validation | 进化链(补充) | 样本文件解析 | 20-40 |

**预期增量**: DSH 层从 80 条 → 1010-1460 条 (+930-1380 条)
**node_sequence 复杂度**: 平均5节点 → 8-20节点（AST提取真实调用链）
**数据质量**: 从"静态模板/最终结果" → "结构化决策逻辑+参数化场景"

### 0.3 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | v0.3 评审发现 all_trades.jsonl 仅152条且无决策过程 | v0.3 评审问题#1#2 |
| F2 | TDD测试388+文件~2300函数，天然含决策逻辑和多样场景 | Glob 调研 test_*.py |
| F3 | 测试参数化(@parametrize)一键生成多场景训练数据 | test_p0_score_b_event_boost.py 6场景 |
| F4 | .cognitive/sessions/ 558个会话目录含认知闭环链 | v0.3 评审问题#3 |
| F5 | trading_log_collector 已覆盖 S/C 层日志，DSH 层需差异化 | recall VM-1791796267529 |
| F6 | 用户偏好TDD方法论，测试本身就是训练资产 | user_profile |
| F7 | 测试的 pass/fail = ground truth，可作评估基准 | test_exit_manager.py assert 结构 |

### 0.4 范围边界

**In Scope:**
- 定义 5 个采集器设计（P0-P4），P0 为 TDD 测试核心
- AST 解析测试函数体的技术方案
- 各采集器的 node_sequence 提取逻辑
- 与 v0.2 已有采集器 + trading_log_collector 的协同关系
- TDD RED→GREEN→REFACTOR 工作流整合
- 认知闭环（record + verify）

**Out of Scope:**
- 不修改 ExecutionPathTrainingLoop 内部逻辑
- 不修改任何测试文件本身（只读取不写入）
- 不修改 polling_trader/bcrm2/cognitive_loop_entry 核心逻辑
- 不新增测试文件（消费已有388+文件）

---

## 1. 调研结论（事实清单）

### 1.1 DSH 层训练数据格式（同 v0.2，已确认）

**来源**: [run_continual_training.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/scripts/run_continual_training.py#L139-L140) L139-140

```python
elif layer == "DSH":
    return {"task": case.intent, "node_sequence": case.actions, "outcome": outcome}
```

### 1.2 TDD 测试文件清单（v0.4 P0 核心数据源，已确认 ✅）

| 子系统目录 | 测试文件数 | 估计测试函数 | 可提取DSH条数 | 覆盖域 |
|-----------|-----------|------------|-------------|--------|
| 11-易经推理系统/tests/ | ~100 | ~600 | ~300 | BCRM/BDSM/Score_B/exit/trading_protocol/memory_l4 |
| 11-易经/scripts/memory_l4/tests/ | ~100+(截断) | ~600 | ~200 | shadow_logger/exit_manager/evolution/force_vector/cycle_bounds/phase_c |
| 23-四层闭环/tests/ + dreambuddy_evolution/tests/ | ~140 | ~800 | ~350 | cross_validation/shadow_rl/neural_sde/cognitive_bridge/evolution_pipeline |
| 33-REA逆向解析/tests/ | 22 | ~120 | ~60 | investigate_dsh/dsh_nodes/algorithm_reducer/architecture_pattern |
| 34-前端训练系统/tests/ | 26 | ~150 | ~50 | training_executor/cognitive_loop/rea_adapter |
| **合计** | **388+** | **~2300** | **~960** | — |

**关键发现**: 11-易经推理系统 Glob 搜索结果在200条截断，实际文件数更多。

### 1.3 测试结构 → DSH 映射验证（已确认 ✅）

**样例1**: [test_p0_score_b_event_boost.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/tests/test_p0_score_b_event_boost.py) — Score_B 决策链

```python
# 参数化测试 = 6个训练场景（A-F），每个场景不同参数
@pytest.mark.parametrize("cont,conf,strength,expected_score_b,expected_boost", [
    (0.75, 0.70, 0.0, 0.73, 0.0),     # A: 无快讯 → baseline
    (0.75, 0.70, 1.0, 0.844, 0.10),   # B: 强正面 → boost=0.10
    (0.75, 0.70, None, 0.73, 0.0),    # D: FAIL-OPEN → 回退baseline
])
def test_formula_and_clamp(cont, conf, strength, expected_score_b, expected_boost):
    score, boost = compute_score_b_with_event_boost(cont, conf, strength)
    assert abs(boost - expected_boost) < 1e-3
    assert abs(score - expected_score_b) < 1e-3
```

**映射**:
- `task`: `"score_b_event_boost.formula_and_clamp"` (文件名+函数名)
- `node_sequence`: `["baseline_compute(0.60*cont+0.40*conf)", "event_boost_compute", "clamp(0,0.10)", "score_b_final", "assert_score"]`
- `outcome`: `"success"` (GREEN阶段pass)
- **6个参数化场景 = 6条训练数据**，node_sequence 各不相同

**样例2**: [test_cross_validation_gate.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/tests/test_cross_validation_gate.py) — 交叉验证决策链

```python
def test_quality_change_on_persistent_divergence():
    gate = CrossValidationGate(persistence_threshold=3)
    for _ in range(3):
        r = gate.compare(G_dim="fundamental", G_conf=0.9,
                         A_dim="macro", A_strength=0.7,
                         structural_break={"market_form_shift": True})
    assert r["quality_change"] is True
    assert r["granger_reestimate_trigger"] is True
```

**映射**:
- `task`: `"cross_validation.quality_change_persistent_divergence"`
- `node_sequence`: `["compare_dims(fundamental,macro)", "confidence_mult(0.9)", "shift_signal(true)", "divergence_count(3)", "structural_break(market_form_shift)", "quality_change(true)", "granger_reestimate(true)"]`
- `outcome`: `"success"`

**样例3**: [test_exit_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/tests/test_exit_manager.py) — 出场策略链

```python
def test_exit_manager_priority_chain_first_non_pass_wins():
    mgr = ExitManager(strategies=[AlwaysPass(), ForceClose(), ShouldNotBeCalled()])
    decision = mgr.evaluate(coin="BTC", inference={}, pos_info={}, ...)
    assert decision.action == "force_close"
    assert should_not_be_called.call_count == 0  # 短路验证
```

**映射**:
- `task`: `"exit_manager.priority_chain_first_non_pass_wins"`
- `node_sequence`: `["strategy_evaluate(always_pass)", "strategy_returns_pass", "strategy_evaluate(force_close)", "strategy_returns_force_close", "priority_chain_short_circuit", "assert_action(force_close)", "assert_not_called(should_not_be_called)"]`
- `outcome`: `"success"`

### 1.4 v0.3 评审问题#1: all_trades.jsonl 实际数据量（已确认 ✅）

- **SPEC v0.3 声称**: 37万条交易记录
- **实际验证**: [all_trades.jsonl](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl) 仅 **152 条**
- **37万来源**: recall VM-1791796267529 确认是 trading_log_collector.py 统计的 polling_trader **日志文件**条数（非 all_trades.jsonl）
- **v0.4 处理**: all_trades.jsonl 降为 P2 补充源；P0 改为 TDD 测试

### 1.5 v0.3 评审问题#3: .cognitive/sessions/ 会话目录（已确认 ✅）

- **会话目录数**: 558 个（如 CS-1786238933440）
- **v0.3 处理**: 完全遗漏
- **v0.4 处理**: 新增 P1 CognitiveSessionCollector

### 1.6 v0.3 评审问题#5: 与 trading_log_collector 关系（已确认 ✅）

**来源**: recall VM-1791796267529 + [trading_log_collector.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/adapters/trading_log_collector.py)

| 维度 | trading_log_collector | v0.4 TddTestCollector |
|------|----------------------|----------------------|
| 数据来源 | 运行日志文件 (.log) | 测试代码文件 (.py) |
| layer_tags | ['S','C'] (意图+反思) | ['DSH'] (执行序列) |
| node_sequence 内容 | 日志行文本 | AST解析的函数调用链 |
| 数据量 | 37万条日志→200条采样 | 388+文件→~1000条 |
| 去重/配额 | 4源公平分配 limit//4 | 按子系统目录比例分配 |
| **重叠度** | **0%** — 完全不同数据源、不同层、不同格式 |

---

## 2. P0: TddTestCollector — TDD 测试文件采集器

### 2.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `tdd_test_collector` |
| 类名 | `TddTestCollector` |
| 文件路径 | `34-前端应用训练系统/adapters/tdd_test_collector.py` |
| 实现接口 | `TrainingDataProvider` |
| layer_tags | `["DSH"]` |
| quality | `"B"` (测试是结构化、有意设计的) |
| 数据源 | 388+ test_*.py 文件 |
| 预期条数 | 800-1200 |
| node_sequence 长度 | 5-15 节点 |

### 2.2 扫描目录配置

```python
TEST_DIRECTORIES = [
    # 11-易经推理系统
    ("11-易经推理系统/tests", "yijing"),
    ("11-易经推理系统/scripts/memory_l4/tests", "yijing_l4"),
    # 23-四层闭环自进化
    ("23-四层闭环自进化交易架构/tests", "evolution"),
    ("23-四层闭环自进化交易架构/dreambuddy_evolution/tests", "evolution_core"),
    # 33-REA逆向解析
    ("33-REA逆向解析工程/tests", "rea"),
    # 34-前端训练系统
    ("34-前端应用训练系统/tests", "training_system"),
]
```

### 2.3 AST 解析方案

**核心**: 用 Python `ast` 模块解析测试文件，提取:

1. **测试函数名** → `intent` (task)
   - `test_formula_and_clamp` → `"score_b_event_boost.formula_and_clamp"`
   - 去掉 `test_` 前缀，用 `_` → `.` 分隔

2. **函数调用链** → `actions` (node_sequence)
   - 遍历 AST `ast.Call` 节点，提取函数名
   - 过滤掉 `assert`/`pytest`/`MagicMock` 等框架调用
   - 保留业务逻辑调用（如 `compute_score_b_with_event_boost`、`gate.compare`）
   - 保留关键 `assert` 语句作为终节点

3. **参数化场景** → 多条 TrainingCase
   - 解析 `@pytest.mark.parametrize` 装饰器
   - 每个 parametrize 场景生成独立的 TrainingCase
   - 参数值附加到 node_sequence 节点（如 `baseline_compute(cont=0.75,conf=0.70)`）

4. **测试类名** → `intent` 前缀
   - `class TestScoreBEventBoost` → 前缀 `score_b_event_boost`

5. **docstring** → `outcome_text` 补充描述

### 2.4 AST 解析伪代码

```python
import ast

class TestASTVisitor(ast.NodeVisitor):
    def __init__(self):
        self.node_sequence = []
        self.parametrize_cases = []

    def visit_FunctionDef(self, node):
        # 提取测试函数名
        func_name = node.name.removeprefix("test_")
        # 提取 parametrize 装饰器
        for decorator in node.decorator_list:
            if self._is_parametrize(decorator):
                self.parametrize_cases = self._extract_parametrize(decorator)
        # 遍历函数体提取调用链
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Call):
                call_name = self._get_call_name(stmt.func)
                if self._is_business_call(call_name):
                    self.node_sequence.append(call_name)
            elif isinstance(stmt, ast.Assert):
                self.node_sequence.append(f"assert_{self._get_assert_desc(stmt)}")
        return self.node_sequence, self.parametrize_cases

    def _is_business_call(self, name: str) -> bool:
        """过滤框架调用，保留业务调用。"""
        framework_prefixes = {"pytest", "mock", "patch", "MagicMock",
                               "tmp_path", "fixture", "unittest"}
        return not any(name.startswith(p) for p in framework_prefixes)
```

### 2.5 TrainingCase 构造

```python
def _build_training_case(self, file_path, class_name, func_name,
                         node_sequence, param_case=None):
    intent = f"{class_name}.{func_name}" if class_name else func_name
    if param_case:
        # 参数化场景：参数附加到 node_sequence
        param_str = ", ".join(f"{k}={v}" for k, v in param_case.items())
        node_sequence = [f"{n}({param_str})" if "(" not in n else n
                         for n in node_sequence]
    return TrainingCase(
        intent=intent,
        actions=node_sequence,  # node_sequence
        outcome_text="pass",    # GREEN 阶段
        layer_tags=["DSH"],
        quality="B",
        source=f"tdd:{file_path}",
    )
```

### 2.6 配额分配

```python
# 按 5 个子系统目录公平分配 limit
QUOTA = {
    "yijing": 0.25,       # 11-易经/tests
    "yijing_l4": 0.20,    # 11-易经/scripts/memory_l4/tests
    "evolution": 0.25,    # 23-四层/tests + dreambuddy_evolution/tests
    "rea": 0.15,          # 33-REA/tests
    "training_system": 0.15,  # 34-前端/tests
}
# limit=100 → yijing:25, yijing_l4:20, evolution:25, rea:15, training:15
```

### 2.7 FAIL-OPEN

- AST 解析异常 → 跳过该文件，继续下一个
- 文件无 test 函数 → 返回空列表
- parametrize 格式异常 → 用函数本身作为1条 case（无参数化）

---

## 3. P1: CognitiveSessionCollector — 认知会话采集器

### 3.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `cognitive_session_collector` |
| 类名 | `CognitiveSessionCollector` |
| 文件路径 | `34-前端应用训练系统/adapters/cognitive_session_collector.py` |
| layer_tags | `["DSH"]` |
| 数据源 | `.cognitive/sessions/` 558个会话目录 |
| 预期条数 | 40-80 |
| node_sequence 长度 | 9-15 节点 |

### 3.2 数据源结构

```
.cognitive/sessions/
├── CS-1786238933440/     # 会话目录
│   ├── session.jsonl     # 会话记录（recall→record→verify 调用链）
│   └── ...
├── CS-1786238951234/
│   └── ...
└── ... (558个目录)
```

### 3.3 node_sequence 模板

```json
[
  "session_start",
  "recall.query(context)",
  "recall.cache_check",
  "recall.db_query(min_quality=C)",
  "recall.rank_by_score",
  "recall.merge_dedup(top_k)",
  "action.execute(based_on_recall)",
  "outcome.observe",
  "record.write(content, quality_level)",
  "record.ledger_receipt",
  "verify.bayesian_update(memory_id, success)",
  "verify.quality_update",
  "verify.distill_check",
  "session_end"
]
```

### 3.4 采集逻辑

1. 扫描 `.cognitive/sessions/` 目录，列出所有 CS-* 会话目录
2. 读取每个会话的 session.jsonl
3. 提取 recall/record/verify 调用记录
4. 重构调用链为 node_sequence
5. outcome 从 verify 的 success 字段派生

**来源**: [cognitive_session.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口/cognitive_session.py#L1445-L1488) L1445-1488 事后校验闭环逻辑

---

## 4. P2: PollingTraderLogCollector — 交易日志补充采集器

### 4.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `polling_trader_log_collector` |
| 类名 | `PollingTraderLogCollector` |
| layer_tags | `["DSH"]` |
| 数据源 | polling_trader 日志文件（非 all_trades.jsonl） |
| 预期条数 | 30-60 |
| node_sequence 长度 | 8-12 节点 |

### 4.2 v0.3 问题修复

- **v0.3 错误**: 声称 all_trades.jsonl 有37万条，实际仅152条且无决策过程
- **v0.4 修复**: 改从 polling_trader **日志文件**采集（recall VM-1791369371282 确认日志路径 `11-易经推理系统/logs/trading_stdout.log`），日志含 Score_B 计算过程
- all_trades.jsonl 的152条仍可用（作为交易结果 outcome 派生），但不作为 node_sequence 来源

### 4.3 日志 → node_sequence 提取

从日志关键词提取决策节点（来源: recall VM-1791198440399）:

| 日志关键词 | node_sequence 节点 |
|-----------|-------------------|
| `src=bcrm2` | `score_b_baseline` |
| `Score_B` + `event_boost` | `event_boost_compute` |
| `BDSM 出场巡检` | `bdsm_exit_scan` |
| `战略层影子` | `strategy_shadow_check` |
| `war_state` / `total_score` | `strategy_score_compute` |
| `累计进化 N 次` | `evolution_step` |

---

## 5. P3: REATestCollector — REA 测试+报告采集器

### 5.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `rea_test_collector` |
| 类名 | `REATestCollector` |
| layer_tags | `["DSH"]` |
| 数据源 | 33-REA/tests/ 22个测试文件 + 1份JSON报告 |
| 预期条数 | 40-80 |

### 5.2 v0.3 问题修复

- **v0.3 错误**: 预期 REA reports/ 有30-60条，实际仅1份JSON+3份markdown
- **v0.4 修复**: 改从 REA **测试文件**采集（22个 test_*.py），用 P0 的 AST 解析方案
- 1份JSON报告（self_evolution_rea_report.json）作为补充

### 5.3 REA 测试覆盖

| 测试文件 | 覆盖域 | 预期条数 |
|---------|--------|---------|
| test_investigate_dsh.py | DSH 调查链 | ~8 |
| test_dsh_nodes.py | DSH 节点解析 | ~5 |
| test_algorithm_reducer.py | 算法归约 | ~5 |
| test_architecture_pattern_detector.py | 架构模式检测 | ~5 |
| test_investigation_workflow.py | 调查工作流 | ~5 |
| test_cognitive_integration.py | 认知集成 | ~5 |
| 其他16个 | — | ~27 |
| **合计** | — | **~60** |

---

## 6. P4: ShadowValidationCollector — 进化链补充采集器

### 6.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `shadow_validation_collector` |
| 类名 | `ShadowValidationCollector` |
| layer_tags | `["DSH"]` |
| 数据源 | shadow_validation/ 16个 _samples.jsonl + evolution 测试 |
| 预期条数 | 20-40 |

### 6.2 数据源

1. **shadow_validation/ 16个 _samples.jsonl**（10KB-211KB）：从样本提取 Shadow-RL 决策节点
2. **evolution 测试文件**（~140个）：用 P0 的 AST 解析，提取 shadow_rl_trainer/bellman/cross_validation 调用链

### 6.3 node_sequence 模板（从 evolution 测试提取）

```json
[
  "sample_count_check(>=2000)",
  "maybe_activate(sample_count)",
  "mutate_gmax(original_weight)",
  "delta_check([0.01,0.05])",
  "clamp([0,1])",
  "thompson_sample(Beta(alpha,beta))",
  "record_only_if_not_activated"
]
```

来源: [test_shadow_rl_trainer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/tests/test_shadow_rl_trainer.py) L1-60

---

## 7. TDD 工作流整合 + 认知闭环

### 7.1 TDD RED→GREEN→REFACTOR = 训练数据生成管道

| TDD 阶段 | 训练数据 | outcome | 用途 |
|---------|---------|---------|------|
| **RED** | 测试函数存在但实现不存在 | `"failure"` (ModuleNotFoundError) | 训练"缺失实现"场景 |
| **GREEN** | 测试通过 | `"success"` | 主训练数据 |
| **REFACTOR** | 测试仍通过 | `"success"` | 验证重构不破坏行为 |

**自动化管道**:
1. 开发者写新测试 → TddTestCollector 自动扫描
2. RED 阶段: outcome=failure，训练 DSH 层识别"未实现"模式
3. GREEN 阶段: outcome=success，训练 DSH 层学习正确执行路径
4. REFACTOR: 验证训练后的模型仍能预测重构后的路径

### 7.2 评估用途

- **训练**: TDD 测试 → TrainingCase → DSH 层 ExecutionPathTrainingLoop
- **评估**: 模型预测给定 task 的 node_sequence → 与测试实际执行路径对比 → 通过率 = 模型质量
- **回归**: 新增测试 → 检查模型是否能预测新场景 → 覆盖率增长指标

### 7.3 认知闭环（修复 v0.3 问题#7）

**硬约束**: SPEC 完成后必须执行 record + verify:

```
# 1. 记录 v0.4 核心经验
record(
    content="[经验][DSH训练数据源] v0.4 核心转变: TDD测试文件作为P0数据源(388+文件~1000条), "
             "AST解析测试函数体提取node_sequence, 解决v0.3静态模板问题. "
             "5采集器: P0-TddTestCollector/P1-CognitiveSession/P2-PollingLog/P3-REATest/P4-ShadowValidation. "
             "与trading_log_collector零重叠(S/C层日志 vs DSH层代码).",
    quality_level="B",
    tags="DSH训练数据源,TDD,AST解析,硬约束"
)

# 2. 验证升级
verify(memory_id="VM-1791796267529", success=True)
# trading_log_collector 经验确认与 v0.4 差异化方向一致
```

---

## 8. 实施计划

### 8.1 TDD 开发顺序

| 步骤 | 阶段 | 内容 | 验收标准 |
|------|------|------|---------|
| 1 | **RED** | 写 `test_tdd_test_collector.py` — 断言 `TddTestCollector` 类不存在 | `ModuleNotFoundError` |
| 2 | **GREEN** | 实现 `tdd_test_collector.py` — AST 解析 + TrainingCase 构造 | 采集≥100条DSH数据 |
| 3 | **REFACTOR** | 优化配额分配 + FAIL-OPEN | 全388+文件无crash |
| 4 | **RED** | 写 `test_cognitive_session_collector.py` | `ModuleNotFoundError` |
| 5 | **GREEN** | 实现 `cognitive_session_collector.py` | 采集≥20条 |
| 6 | **RED** | 写 `test_polling_trader_log_collector.py` | `ModuleNotFoundError` |
| 7 | **GREEN** | 实现 `polling_trader_log_collector.py` | 采集≥15条 |
| 8 | **RED** | 写 `test_rea_test_collector.py` | `ModuleNotFoundError` |
| 9 | **GREEN** | 实现 `rea_test_collector.py` | 采集≥20条 |
| 10 | **RED** | 写 `test_shadow_validation_collector.py` | `ModuleNotFoundError` |
| 11 | **GREEN** | 实现 `shadow_validation_collector.py` | 采集≥10条 |
| 12 | **集成** | 注册到 `run_continual_training.py` collectors 列表 | 全采集器全绿 |
| 13 | **验收** | 运行 `python scripts/run_continual_training.py --limit 100` | DSH层≥500条 |

### 8.2 注册到 run_continual_training.py

```python
# 在 collectors 列表中添加（L95-108 之后）:
("TddTest", "tdd_test_collector", "TddTestCollector"),              # P0
("CognitiveSession", "cognitive_session_collector", "CognitiveSessionCollector"),  # P1
("PollingLog", "polling_trader_log_collector", "PollingTraderLogCollector"),      # P2
("REATest", "rea_test_collector", "REATestCollector"),              # P3
("ShadowValidation", "shadow_validation_collector", "ShadowValidationCollector"),  # P4
```

### 8.3 验收标准

| 指标 | 目标 | 来源 |
|------|------|------|
| DSH 层总条数 | ≥500 (v0.2的80条+ v0.4的420+) | run_continual_training 输出 |
| node_sequence 平均长度 | ≥8 节点 (v0.2平均5) | TrainingCase.actions 长度 |
| node_sequence 多样性 | 无重复模板 (v0.3静态模板问题) | distinct node_sequence 数/总数 > 0.8 |
| P0 TddTestCollector 条数 | ≥300 | 单采集器验收 |
| 全采集器无 crash | 388+文件全部处理 | FAIL-OPEN 验证 |
| TDD RED 测试 | 5个新采集器各有 RED 测试 | test_*.py 存在 |

---

## 9. v0.2 已有采集器保留

v0.2 的 4 个 DSH 层采集器（CleaningTrace/DalRoute/DataFetchRoute/DshSubagent 共80条）保留不变。v0.4 的 5 个新采集器叠加后:

```
v0.2 (4采集器, 80条) + v0.4 (5采集器, 930-1380条) = 1010-1460 条 DSH 层训练数据
```

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| AST 解析覆盖率不足（部分测试格式复杂） | 中 | node_sequence 不完整 | FAIL-OPEN: 解析失败用函数名作为1节点 |
| .cognitive/sessions/ 格式不统一 | 中 | P1 采集失败 | 先读3-5个会话目录确认格式再实现 |
| polling_trader 日志文件不存在或已清理 | 低 | P2 采集失败 | 降级为 all_trades.jsonl 152条 |
| 测试文件更新导致训练数据漂移 | 中 | 模型需重训 | 持续训练模式自动适应（EWMA 衰减旧数据） |
| 388+文件扫描耗时 | 低 | 采集速度慢 | 并行解析 + 缓存 AST 结果 |

---

## 附录A: v0.3 → v0.4 变更摘要

| 维度 | v0.3 | v0.4 |
|------|------|------|
| P0 数据源 | all_trades.jsonl (152条, 无决策过程) | **TDD 测试文件 (388+文件, ~1000条)** |
| node_sequence | 静态模板 (所有case相同) | **AST 解析真实调用链 (每case不同)** |
| P1 数据源 | cognitive_memory.db memories表 | **.cognitive/sessions/ 558个会话** |
| P2 数据源 | BCRM/BDSM/战略层代码推断 | **polling_trader 日志关键词提取** |
| P3 数据源 | REA reports (预期30-60, 实际1份) | **REA 测试文件 (22个) + 1份JSON** |
| P4 数据源 | evolution shadow_validation | shadow_validation + **evolution 测试AST** |
| 预期总量 | 220-420条 | **930-1380条** |
| TDD 规划 | 无 | **TDD RED→GREEN = 训练数据管道** |
| 认知闭环 | 无 | **record + verify 步骤** |
| 与trading_log_collector关系 | 未说明 | **明确: 零重叠, S/C层 vs DSH层** |
