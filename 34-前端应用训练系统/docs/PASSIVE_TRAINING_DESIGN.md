# 被动训练（纵深·Trae在线辅导）— 技术设计文档

> **版本**: v0.5 | **更新日期**: 2026-10-11
> **定位**: 被动训练子系统的技术架构设计，对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.2
> **关联SPEC**: [SPEC.md](../SPEC.md) §2.3 被动训练（纵深·Trae在线辅导）
> **实现状态**: ✅ v0.5 集成完成（P0-P4 全覆盖 + v0.5 增量训练升级）

---

## 1. 概述

### 1.1 系统定位

被动训练是 DreamBuddy-V2 前端应用训练系统的**双模式之一**，定位为**纵深·Trae在线辅导训练**。Trae 收尾后以教师角色在线，利用完整工程上下文对前端系统进行实时辅导训练——监控训练流程、纠正偏差、评估优化方向。不依赖案例数量，强调深度质量。

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| **深度质量** | 单案例即可触发增量训练，不等桶满阈值，聚焦本次工程的设计意图掌握 |
| **Trae在线辅导** | Trae 作为教师角色，对比 pre/post model 权重和 step 变化，自动评估训练有效性 |
| **FAIL-OPEN** | 每步独立 try/catch，任何接口异常降级不崩溃，确保收尾流程不阻塞 |
| **认知闭环** | 辅导结果通过 hermes反思 tag 触发 dream-self-iteration-workflow 自进化 |

### 1.3 业务边界

| 职责 | 归属 |
|------|------|
| 收尾案例价值评估（CaseIngestGate） | 本模块（被动训练） |
| 33-REA 逆向解析（算法模式/调用链/依赖图） | 33-REA逆向解析工程（本模块调用） |
| REA → TrainingCase 转换 | 本模块（rea_to_tdr_adapter） |
| v0.5 增量训练触发（trigger_incremental） | 前端 SPL 训练器（本模块通过 HTTP 调用） |
| Trae 在线辅导循环（监控/纠正/评估） | 本模块（coaching_loop v0.2） |
| 认知记忆 record | 认知系统（本模块准备参数，Trae 调用 MCP） |
| 主动训练（批量统计） | 本模块其他部分（本文档不覆盖） |

### 1.4 与主动训练的区别

| 维度 | 主动训练(统计) | 被动训练(在线辅导) |
|------|--------------|------------------|
| 数据规模 | 批量(桶满阈值) | 单案例(本次工程) |
| 训练机制 | 统计学习(模式挖掘/聚类/CBR) | Trae在线监控+纠正+评估 |
| Trae角色 | 离线(数据来源) | 在线(教师) |
| 目标 | 跨案例共同最优 | 单案例深度掌握 |
| 质量保证 | CaseIngestGate过滤 | Trae实时纠正 |
| 触发方式 | 桶满触发 `train()` | 单案例 `trigger_incremental()` |

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────┐
│  入口层 (Entry)                                      │
│  ├─ trigger_passive_training.py (CLI入口)            │
│  └─ scripts/run_passive_training.py (端到端脚本)      │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  编排层 (Orchestration)                              │
│  ├─ core/dual_mode_orchestrator.py (双模式调度器)     │
│  │   └─ trigger_passive_training() v0.5 流程         │
│  ├─ core/coaching_loop.py (Trae在线辅导循环 v0.2)    │
│  │   └─ run_coaching_cycle() 自动评估+纠正+计算       │
│  └─ core/orchestrator_factory.py (工厂创建)          │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  适配层 (Adapters)                                    │
│  ├─ ts_http_training_executor.py (5层HTTP训练执行器)  │
│  ├─ generic_case_evaluator.py (CaseIngestGate评估器)  │
│  ├─ rea_native_parser.py (33-REA原生解析器)           │
│  └─ rea_to_tdr_adapter.py (REA→TrainingCase转换)      │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  接口层 (Interfaces / Protocol)                       │
│  ├─ training_executor.py (TrainingExecutor + v0.5)    │
│  ├─ case_evaluator.py (CaseEvaluator Protocol)        │
│  ├─ rea_parser.py (REAParser + REAParseResult)        │
│  └─ training_data_provider.py (TrainingCase结构)      │
└─────────────────────────────────────────────────────┘
```

### 2.2 模块关系

```
收尾SKILL Step 5.5
    │
    ▼
┌─ trigger_passive_training.py ─────────────────────┐
│  run_trigger()                                    │
│    │                                              │
│    ▼                                              │
│  orchestrator_factory.create_orchestrator()       │
│    ├─ 5× TSHTTPTrainingExecutor (S/DSH/C/G/LLM)  │
│    ├─ GenericCaseEvaluator                        │
│    └─ REANativeParser (可选)                      │
│    │                                              │
│    ▼                                              │
│  DualModeOrchestrator.trigger_passive_training()  │
│    ├─ CaseIngestGate 评估                          │
│    ├─ 33-REA 解析 (analyze + trace)               │
│    ├─ rea_to_tdr_adapter 转换                      │
│    └─ v0.5 增量训练循环                            │
│         ├─ get_model() → pre_model                │
│         ├─ checkpoint()                           │
│         ├─ add_case()                             │
│         ├─ trigger_incremental() → TrainingResult │
│         └─ get_model() → post_model               │
│    │                                              │
│    ▼                                              │
│  CoachingSession.run_coaching_cycle()             │
│    ├─ _evaluate_all_monitoring_checks()           │
│    │   └─ 对比 pre/post model 权重+step            │
│    ├─ _generate_corrections()                     │
│    └─ _calculate_improvement()                    │
│    │                                              │
│    ▼                                              │
│  输出: coaching_report + record_params            │
└──────────────────────────────────────────────────┘
```

### 2.3 核心设计决策

| 决策 | 理由 |
|------|------|
| v0.5 方法为非抽象默认 raise NotImplementedError | 向后兼容：已有训练器无需改动，按需实现 v0.5 方法 |
| checkpoint() 仅做备份，pre_model 用 get_model() 获取 | 保证 pre/post model 格式一致（均为顶层 step+weights） |
| 每步独立 try/catch + degraded 标记 | FAIL-OPEN：异常不崩溃，降级标记传递到辅导循环跳过检查 |
| 无 REA 数据时降级为 _check_any_model_change() | 兼容 --no-rea 场景，仅检查 step 变化判断训练执行 |
| 监控检查覆盖全部 5 层（S/DSH/C/G/LLM） | 前端只有 S 层返回实际权重，其他层靠 step+1 判断 |

---

## 3. 核心算法

### 3.1 v0.5 增量训练流程

被动训练的核心是 v0.5 增量训练——单案例即可启动，不依赖桶满阈值。

**流程伪代码**：

```python
def trigger_passive_training(wrapup_case: dict) -> dict:
    # 1. CaseIngestGate 评估
    evaluation = case_evaluator.evaluate(wrapup_case)
    if evaluation.decision == "skip":
        return {"status": "skipped", "reason": evaluation.reason}

    # 2. 33-REA 解析 (FAIL-OPEN)
    rea_result = None
    if rea_parser and "code_path" in wrapup_case:
        analyze_result = rea_parser.analyze(wrapup_case["code_path"])
        trace_result = rea_parser.trace(feature=..., entry=...)
        rea_result = trace_result

    # 3. REA → TrainingCase 转换
    training_cases = rea_to_training_cases(wrapup_case, rea_result)

    # 4. v0.5 增量训练循环 (每层独立 try/catch)
    pre_models, post_models, training_results = {}, {}, {}
    for executor in training_executors:
        layer = executor.get_layer().value
        layer_cases = [c for c in training_cases if layer in c.layer_tags]
        if not layer_cases:
            continue

        # 4a. get_model → pre_model
        try:
            pre_models[layer] = executor.get_model()
        except (NotImplementedError, Exception):
            pre_models[layer] = {"degraded": True}

        # 4b. checkpoint → 备份用于 restore
        try:
            executor.checkpoint()
        except (NotImplementedError, Exception):
            pass

        # 4c. add_case → 向训练桶添加案例
        for case in layer_cases:
            try:
                executor.add_case(case)
            except Exception:
                pass

        # 4d. trigger_incremental → 增量训练
        try:
            result = executor.trigger_incremental()
            training_results[layer] = {"success": result.success, "metrics": result.metrics}
        except (NotImplementedError, Exception):
            training_results[layer] = {"success": False, "degraded": True}

        # 4e. get_model → post_model
        try:
            post_models[layer] = executor.get_model()
        except (NotImplementedError, Exception):
            post_models[layer] = {"degraded": True}

    return {"status": "coaching_started", "coaching_context": _build_coaching_context(...)}
```

**关键设计**：
- `get_model()` 获取 pre_model 和 post_model（格式一致：顶层 `step` + `weights`）
- `checkpoint()` 仅做备份，不用于 pre_model（因为返回格式嵌套在 `state` 键下，与 `get_model()` 不一致）
- 每层独立 try/catch，异常标记 `degraded: True`，不阻塞其他层

**实现位置**：
- [dual_mode_orchestrator.py](../core/dual_mode_orchestrator.py) → `trigger_passive_training()`

### 3.2 CaseIngestGate 四维评估

收尾案例进入被动训练前的价值评估，决定是否启动在线辅导。

**四维评分**：

| 维度 | 含义 | 计算依据 | 权重 |
|------|------|----------|------|
| **novelty** | 与历史案例的差异度 | TDR retrieve 相似度（越低越新颖） | 高 |
| **significance** | SPEC完成度+验收通过等级 | learned字段长度 + outcome=success + acceptance_level=full | 高 |
| **anomaly** | 是否有红旗/异常 | quality评分 + outcome异常 + known_gaps数量 | 中 |
| **reproducibility** | 验收证据是否完整 | learned/actions字段 + evidence + code_path存在 | 中 |

**决策逻辑**：

```
overall_score = weighted_average(novelty, significance, anomaly, reproducibility)

if overall_score >= INGEST_THRESHOLD:    → INGEST (启动在线辅导)
elif overall_score >= DEFERRED_THRESHOLD: → DEFERRED (暂缓)
else:                                     → SKIP (跳过)
```

**实现位置**：
- [generic_case_evaluator.py](../adapters/generic_case_evaluator.py) → `GenericCaseEvaluator.evaluate()`

### 3.3 33-REA → TrainingCase 映射

将 33-REA 逆向解析结果转换为带 `layer_tags` 的 `TrainingCase` 列表，分发到对应训练层。

**映射规则**：

| 33-REA 输出字段 | → TrainingCase 字段 | → layer_tags | 说明 |
|-----------------|---------------------|-------------|------|
| `algorithm_patterns` | `learned` | `["DSH", "C"]` | 算法模式作为DSH执行路径+C层反思材料 |
| `call_chain` | `actions` | `["DSH"]` | 调用链作为DSH执行路径训练数据 |
| `dependency_graph` | `metadata.graph` | `["G"]` | 依赖图作为G层图结构训练数据 |
| `known_gaps` | `learned` | `["C"]` | 已知局限作为C层反思材料 |
| `observations` | `learned` | `["LLM"]` | 观察作为LLM Prompt优化材料 |

**降级策略**：当 `rea_result is None`（REA 不可用）时，生成一个纯文本四元组案例，`layer_tags=["S","DSH","C","G","LLM"]`（全层覆盖）。

**实现位置**：
- [rea_to_tdr_adapter.py](../adapters/rea_to_tdr_adapter.py) → `rea_to_training_cases()`

### 3.4 coaching_loop v0.2 自动评估

Trae 在线辅导循环的核心——对比 pre/post model 自动判断训练有效性。

**run_coaching_cycle() 三步流程**：

```
1. _evaluate_all_monitoring_checks()
   │  对每项监控检查调用 _evaluate_monitoring(check_name)
   │  ├─ 无模型快照 → 跳过（passed=True, "无模型快照"）
   │  ├─ 无 REA 数据 → _check_any_model_change()
   │  │   └─ 检查任意层 step 变化（step+1 = 训练执行了）
   │  ├─ "算法模式" → _check_algorithm_patterns()
   │  │   └─ 检查全 5 层权重或 step 变化
   │  ├─ "DSH/执行路径" → _check_dsh_path()
   │  │   └─ 检查 call_chain 节点权重提升
   │  ├─ "C层/反思" → _check_c_layer_reflection()
   │  └─ "G层/图结构" → _check_g_layer_graph()
   ▼
2. _generate_corrections()
   │  基于未通过的监控检查生成纠正建议
   │  每条: {layer, issue, correction}
   ▼
3. _calculate_improvement()
   │  对比 pre/post model 计算各层提升
   │  ├─ step_delta = post.step - pre.step
   │  └─ weight_delta = Σ|post.weights[k] - pre.weights[k]|
   ▼
   辅导质量分 = passed_count / total_count × 100
```

**关键兼容性处理**：
- `degraded` 标记的层跳过检查（`pre.get("degraded") or post.get("degraded") → continue`）
- 前端 DSH/C/G/LLM 层 `get_model()` 返回空 `weights={}`，仅靠 `step` 变化判断
- 无 REA 数据时降级为 `_check_any_model_change()`，只看 step 变化

**实现位置**：
- [coaching_loop.py](../core/coaching_loop.py) → `CoachingSession.run_coaching_cycle()`

---

## 4. 数据流

### 4.1 主数据流

```
收尾SKILL Step 5.5
    │
    ▼ wrapup_case (JSON: intent/actions/outcome/learned/acceptance/code_path)
    │
┌───┴──────────────────────────────────────────────────┐
│  1. CaseIngestGate 评估                                │
│     input: wrapup_case                                 │
│     output: EvaluationResult(decision, novelty, ...)  │
│     decision ∈ {INGEST, DEFERRED, SKIP}               │
└───┬──────────────────────────────────────────────────┘
    │ (INGEST only)
    ▼
┌───┴──────────────────────────────────────────────────┐
│  2. 33-REA 逆向解析                                    │
│     input: code_path, feature, entry                  │
│     ├─ S33_rea_analyze → dependency_graph + evidence   │
│     └─ S33_rea_trace → call_chain + algorithm_patterns │
│     output: REAParseResult                             │
└───┬──────────────────────────────────────────────────┘
    │
    ▼
┌───┴──────────────────────────────────────────────────┐
│  3. rea_to_tdr_adapter 转换                            │
│     input: wrapup_case + REAParseResult               │
│     output: List[TrainingCase] (带 layer_tags)         │
└───┬──────────────────────────────────────────────────┘
    │
    ▼
┌───┴──────────────────────────────────────────────────┐
│  4. v0.5 增量训练循环 (5层并行)                         │
│     每层: get_model(pre) → checkpoint → add_case →     │
│           trigger_incremental → get_model(post)        │
│     output: pre_models, post_models, training_results  │
└───┬──────────────────────────────────────────────────┘
    │
    ▼
┌───┴──────────────────────────────────────────────────┐
│  5. coaching_loop v0.2 自动辅导循环                    │
│     input: coaching_context (含 pre/post models)       │
│     ├─ 自动评估监控检查 (pre vs post 对比)              │
│     ├─ 生成纠正建议                                    │
│     └─ 计算训练成果提升 (step_delta + weight_delta)    │
│     output: coaching_report (质量分 + 纠正 + 提升)      │
└───┬──────────────────────────────────────────────────┘
    │
    ▼
┌───┴──────────────────────────────────────────────────┐
│  6. 反馈                                               │
│     ├─ coaching_report → 收尾报告                      │
│     ├─ record_params → 认知系统 (tags: hermes反思)      │
│     └─ hermes反思 tag → dream-self-iteration-workflow  │
└──────────────────────────────────────────────────────┘
```

### 4.2 数据结构

#### TrainingCase

被动训练的通用案例结构，由 `rea_to_tdr_adapter` 生成。

| 字段 | 类型 | 说明 |
|------|------|------|
| `intent` | `str` | 案例意图描述 |
| `actions` | `List[str]` | 行动序列 |
| `outcome_text` | `str` | 结果描述 |
| `learned` | `List[str]` | 经验提取 |
| `layer_tags` | `List[str]` | 目标训练层标签（S/DSH/C/G/LLM） |
| `quality` | `str` | 质量等级（S/A/B/C/D） |
| `confidence` | `float` | 置信度 0-1 |
| `source` | `str` | 来源标识 |
| `metadata` | `dict` | 扩展元数据 |

**定义位置**：[training_data_provider.py](../interfaces/training_data_provider.py) → `TrainingCase`

#### REAParseResult

33-REA 逆向解析结果，由 `REANativeParser` 生成。

| 字段 | 类型 | 说明 |
|------|------|------|
| `algorithm_patterns` | `List[str]` | 算法模式（recursion/iteration/conditional_branch...） |
| `call_chain` | `List[str]` | 调用链函数名列表 |
| `dependency_graph` | `dict` | 依赖图（节点→依赖列表） |
| `known_gaps` | `List[str]` | 已知局限 |
| `observations` | `List[str]` | 观察记录 |
| `evidence_level` | `str` | 证据等级（observation/derivation/inference/unknown） |
| `confidence` | `float` | 解析置信度 |
| `raw_evidence` | `dict` | 原始证据数据 |

**定义位置**：[rea_parser.py](../interfaces/rea_parser.py) → `REAParseResult`

#### TrainingResult

增量训练结果，由 `trigger_incremental()` 返回。

| 字段 | 类型 | 说明 |
|------|------|------|
| `layer` | `TrainingLayer` | 训练层枚举 |
| `success` | `bool` | 训练是否成功 |
| `metrics` | `Dict[str, float]` | 指标（bucket_count/threshold/incremental_step/weights） |
| `message` | `str` | 状态消息 |

**定义位置**：[training_executor.py](../interfaces/training_executor.py) → `TrainingResult`

#### CoachingReport

辅导会话报告，由 `CoachingSession.to_report()` 生成。

| 字段 | 类型 | 说明 |
|------|------|------|
| `quality_score` | `int` | 辅导质量分 0-100 |
| `monitoring_log` | `List[dict]` | 监控检查结果列表 |
| `corrections` | `List[dict]` | 纠正建议列表（layer+issue+correction） |
| `improvement` | `Optional[dict]` | 各层提升（step_delta+weight_delta） |

**定义位置**：[coaching_loop.py](../core/coaching_loop.py) → `CoachingSession.to_report()`

---

## 5. 接口设计

### 5.1 内部接口（Protocol）

#### TrainingExecutor 协议

训练执行器的统一契约，SPL 5 层训练器通过适配器实现。

| 方法 | 签名 | 版本 | 说明 |
|------|------|------|------|
| `get_layer()` | `() → TrainingLayer` | v0.2 | 返回负责的训练层 |
| `get_bucket_threshold()` | `() → int` | v0.2 | 桶满阈值 |
| `get_bucket_count()` | `() → int` | v0.2 | 当前桶案例数 |
| `add_case(case)` | `(case) → bool` | v0.2 | 添加训练案例 |
| `train()` | `() → TrainingResult` | v0.2 | 桶满训练 |
| `get_dependencies()` | `() → List[TrainingLayer]` | v0.2 | 前置依赖层 |
| `trigger_incremental()` | `() → TrainingResult` | **v0.5** | 增量训练（单案例） |
| `checkpoint()` | `() → dict` | **v0.5** | 保存模型检查点 |
| `restore(state)` | `(state: dict) → dict` | **v0.5** | 恢复模型状态 |
| `get_model()` | `() → dict` | **v0.5** | 获取模型快照 |

> v0.5 方法为非抽象方法，默认 `raise NotImplementedError`，已有训练器按需实现。

**定义位置**：[training_executor.py](../interfaces/training_executor.py)

#### CaseEvaluator 协议

| 方法 | 签名 | 说明 |
|------|------|------|
| `evaluate(case)` | `(case: dict) → EvaluationResult` | 四维评估，返回决策+评分 |

#### REAParser 协议

| 方法 | 签名 | 说明 |
|------|------|------|
| `analyze(target_path)` | `(target_path: str) → REAParseResult` | 架构+依赖图分析 |
| `trace(target_path, feature, entry)` | `(...) → REAParseResult` | 调用链+算法模式追踪 |

### 5.2 对外接口

#### CLI 入口

```bash
# 标准触发（含33-REA）
python trigger_passive_training.py --case-data case.json

# 禁用33-REA（降级为文本四元组）
python trigger_passive_training.py --case-data case.json --no-rea

# 指定前端服务地址
python trigger_passive_training.py --case-data case.json --frontend-url http://localhost:3001
```

**入口位置**：[trigger_passive_training.py](../trigger_passive_training.py) → `run_trigger()`

#### 端到端脚本

```bash
# 端到端执行（自动构建样本案例+触发+生成报告）
python scripts/run_passive_training.py --report-out acceptance_bundles/report.md

# 禁用REA
python scripts/run_passive_training.py --no-rea --report-out acceptance_bundles/report.md
```

**入口位置**：[run_passive_training.py](../scripts/run_passive_training.py) → `run_passive_training()`

#### 前端 HTTP API（TSHTTPTrainingExecutor 调用）

| 操作 | HTTP | Endpoint | 说明 |
|------|------|----------|------|
| 添加案例 | POST | `/api/training/{layer}` | `action=add` |
| 桶满训练 | POST | `/api/training/{layer}` | `action=train` |
| 增量训练 | POST | `/api/training/{layer}` | `action=incremental` → `trainIncrementalLayer` |
| 检查点 | POST | `/api/training/{layer}` | `action=checkpoint` → `checkpointLayer` |
| 恢复 | POST | `/api/training/{layer}` | `action=restore` → `restoreLayer` |
| 获取桶状态 | GET | `/api/training/{layer}` | → `getBucketCount` |
| 获取模型快照 | GET | `/api/training/{layer}/model` | → `getModelSnapshot` |

> `{layer}` 为小写层名：`s` / `dsh` / `c` / `g` / `llm`

**实现位置**：[ts_http_training_executor.py](../adapters/ts_http_training_executor.py)

---

## 6. 状态管理

### 6.1 模型状态

模型状态通过 `get_model()` 获取，JSON 格式：

```json
{
  "step": 15,              // 训练步数（每次 trigger_incremental +1）
  "weights": {             // 模型权重（S层有实际权重，其他层可能为空 {}）
    "pattern_a": 0.35,
    "pattern_b": 0.28
  }
}
```

**降级状态**（接口异常时）：
```json
{"degraded": true, "step": 0}
```

**checkpoint() 返回格式**（仅做备份，不用于 pre_model 对比）：
```json
{"checkpointed": true, "state": {"weights": {...}, "step": N}}
```

### 6.2 状态机

```
                    ┌─────────┐
                    │ pending │ (收尾案例待评估)
                    └────┬────┘
                         │ evaluate()
                    ┌────▼────┐
              ┌──────┤evaluate ├──────┐
              │      └────┬────┘      │
              │           │           │
        ┌────▼───┐  ┌────▼────┐  ┌───▼────┐
        │ SKIPPED│  │ DEFERRED│  │ INGEST │
        └────────┘  └─────────┘  └───┬────┘
                                      │ trigger_passive_training()
                                 ┌────▼──────────┐
                                 │coaching_started│
                                 └────┬──────────┘
                                      │ run_coaching_cycle()
                                 ┌────▼──────────┐
                                 │  coaching_    │
                                 │  completed    │
                                 └──────────────┘
```

---

## 7. 配置管理

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `frontend_url` | `http://localhost:3001` | 前端 SPL 服务地址 |
| `enable_rea` | `True` | 是否启用 33-REA 解析 |
| `INGEST_THRESHOLD` | 0.6 | CaseIngestGate INGEST 决策阈值 |
| `DEFERRED_THRESHOLD` | 0.3 | CaseIngestGate DEFERRED 决策阈值 |
| `coaching_timeout` | 30 分钟 | 辅导循环总超时 |
| `quality_level` | `B` | 认知记录默认质量等级 |
| `record_tags` | `wrapup,收尾,认知闭环,...,hermes反思,被动训练,在线辅导` | 认知记录 tags |

**各层训练参数（前端 SPL 侧）**：

| 层 | bucket_cap | microBatch | λ(EWMA) | 特殊策略 |
|----|-----------|------------|---------|---------|
| S | 200 | 5 | 0.95 | TF-IDF频率表增量 |
| DSH | 300 | 10 | 0.95 | 路径频率统计+模板权重衰减 |
| C | 200 | 10 | 0.90 | 规则权重衰减+保留阈值0.05+ruleArchive |
| G | 500 | 15 | 0.99 | 增量节点/边+孤立节点标记不删除 |
| LLM | 100 | 5 | 0.90 | Prompt模板+KL散度约束 |

---

## 8. 错误处理

### 8.1 异常场景与处理策略

| 场景 | 处理策略 | 实现位置 |
|------|----------|----------|
| CaseIngestGate 评估异常 | 降级为 INGEST，继续流程 | `trigger_passive_training()` |
| 33-REA 解析失败 | `rea_result = None`，降级为文本四元组 | `rea_to_training_cases()` |
| `get_model()` 抛 NotImplementedError | `pre_models[layer] = {"degraded": True}` | v0.5 循环 try/catch |
| `trigger_incremental()` 抛异常 | `training_results[layer] = {"degraded": True}` | v0.5 循环 try/catch |
| 前端 HTTP 不可达 | `TrainingResult(success=False, message="degraded: ...")` | `ts_http_training_executor.py` |
| 编排器创建失败 | 返回 `{"status": "error", ...}` | `run_trigger()` |
| coaching_loop 无模型快照 | 监控检查 passed=True, "无模型快照，跳过" | `_evaluate_monitoring()` |
| coaching_loop 层 degraded | `continue` 跳过该层检查 | `_check_algorithm_patterns()` |

### 8.2 降级机制

```
33-REA 可用？
  ├─ 是 → rea_to_training_cases() 生成多层 TrainingCase（含 layer_tags）
  └─ 否 → _make_text_case() 生成全层文本四元组（layer_tags=["S","DSH","C","G","LLM"]）

前端返回实际权重？
  ├─ 是（S层） → coaching_loop 检查权重变化 + step 变化
  └─ 否（DSH/C/G/LLM） → coaching_loop 仅检查 step 变化（step+1 = 训练执行了）

有 REA 数据？
  ├─ 是 → 按检查类型分发（_check_algorithm_patterns/_check_dsh_path/...）
  └─ 否 → _check_any_model_change()（默认检查任意层 step 变化）
```

**FAIL-OPEN 原则**：每步独立 try/catch，异常标记 degraded，不阻塞后续步骤，不崩溃主流程。

---

## 9. 扩展性设计

### 9.1 新增训练层

1. 在 `TrainingLayer` 枚举新增层（如 `RISK = "RISK"`）
2. 实现该层的 `TrainingExecutor` 适配器（含 v0.5 方法）
3. 在 `orchestrator_factory.create_orchestrator()` 注册新执行器
4. 前端 SPL 侧实现对应层的 `trainIncrementalLayer` / `getModelSnapshot` API

### 9.2 新增评估维度

1. 在 `GenericCaseEvaluator.evaluate()` 新增评分逻辑
2. 更新 `EvaluationResult` 数据结构
3. 调整 INGEST/DEFERRED/SKIP 决策权重

### 9.3 新增解析器

1. 实现 `REAParser` Protocol（`analyze()` + `trace()`）
2. 在 `orchestrator_factory` 替换 `REANativeParser`
3. 确保 `REAParseResult` 字段兼容 `rea_to_tdr_adapter` 映射规则

### 9.4 集成到收尾 SKILL

被动训练已设计为收尾 SKILL（dream-completion-evolution-workflow）的 **Step 5.5**：

```
Step 5 (认知record) → Step 5.5 (被动训练触发) → Step 6 (最终报告)
```

集成方式：
1. 收尾 SKILL 在 Step 5 完成后，构建 `wrapup_case` JSON
2. 调用 `trigger_passive_training.py --case-data case.json`
3. 解析输出，将 `coaching_report` 写入收尾报告
4. 使用 `record_params` 调用认知系统 `record`（tags 含 `hermes反思`）
5. `hermes反思` tag 触发 `dream-self-iteration-workflow` 自进化

---

## 10. 测试与验收

### 10.1 测试覆盖

| 测试文件 | 测试数 | 覆盖范围 |
|----------|--------|----------|
| `tests/test_passive_training_v05.py` | 15 | v0.5 集成（trigger_passive_training + coaching_loop v0.2） |
| `tests/test_trigger_passive_training.py` | - | CLI 入口 |
| `tests/test_coaching_loop.py` | - | 辅导循环 v0.1/v0.2 |
| `tests/test_rea_to_tdr_adapter.py` | - | REA → TrainingCase 转换 |
| `tests/test_generic_case_evaluator.py` | - | CaseIngestGate 四维评估 |
| `tests/test_ts_http_training_executor.py` | - | HTTP 训练执行器 + v0.5 |
| `tests/test_rea_native_parser.py` | - | 33-REA 原生解析器 |

**全量回归**：Python 138/138 零回归，TS 544/544 零回归

### 10.2 端到端验收

| 验收项 | 状态 | 证据 |
|--------|------|------|
| F1 收尾触发被动训练 | ✅ | coaching_started 状态 |
| CaseIngestGate INGEST | ✅ | novelty=0.89, significance=1.0 |
| 5层 step 全部 +1 | ✅ | S=15, DSH=14, C=19, G=10, LLM=15 |
| S层 weight_delta=0.0864 | ✅ | 26→28 keys |
| 辅导质量分 100/100 | ✅ | 4项监控全通过 |
| 纠正次数 0 | ✅ | 无偏差 |
| 闭环验证 7/7 | ✅ | 全链路通过 |
| 认知记忆 record + verify | ✅ | VM-1791724916906 |

**报告位置**：[acceptance_bundles/passive_training_report.md](../acceptance_bundles/passive_training_report.md)

---

## 变更记录

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v0.2 | 2026-10-11 | 初始版本：被动训练触发链路（P0 骨架） |
| v0.5 | 2026-10-11 | v0.5 集成：trigger_passive_training 从桶满模式升级为增量训练模式；coaching_loop v0.2 自动监控+纠正+评估；TrainingExecutor 协议扩展 4 个 v0.5 可选方法 |

---

**文档版本**: v0.5
**最后更新**: 2026-10-11
**关联SPEC**: [SPEC.md §2.3](../SPEC.md)
**关联记忆**: VM-1791724338912 (v0.5集成完成)、VM-1791716579603 (SPL v0.5硬约束)、VM-1791718308108 (P0 TDD完成)
