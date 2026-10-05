---
name: "dream-self-iteration-workflow"
description: "Orchestrates L4 self-iteration: hermes reflection (trace analysis → skill-creator) + param optimization (Bayesian + walk-forward) + case ingest gate (4-dim value assessment) + doc sync (checksum → dream-doc-sync). Invoke for L4 self-iteration, hermes auto-reflection, parameter auto-optimization, case library ingest, or document auto-sync."
---

## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- SKILL 索引与生命周期管理
- 架构同步校验
- 代码审查与合并建议

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批


# Dream Self-Iteration Workflow

L4 自迭代编排 SKILL — 自运行系统四层落地路径的顶层闭环。

## 定位

纯编排层，不重复建设能力。协调 4 个 L4 模块 + 认知库闭环（recall → record → verify）。

## 触发词

`L4 自迭代` / `hermes 反思自动化` / `参数自优化` / `案例库 ingest` / `文档自同步` / `自运行闭环`

## 编排流程

### 1. recall（任务前 — 硬约束）

```
recall(context="L4 自迭代 hermes 反思 参数优化 案例入库 文档同步", top_k=5, min_quality="C")
```

### 2. hermes 反思自动化（L4.1）

模块: `dreamos/core/compute/hermes_reflector.py` → `HermesReflector`

```
reflector = HermesReflector(
    events_root=Path("~/.workbuddy/events"),
    record_fn=cognitive_record,
    skill_creator_fn=skill_creator,  # 可选
)
report = reflector.reflect(hours=24)
```

决策树（来自 CLAUDE.md 硬约束）:
- 流程被复用 ≥ 2 次 → CREATE_SKILL
- 涉及多步编排 ≥ 3 步 → CREATE_SKILL
- 涉及 bsk 自动化 ≥ 1 步 → CREATE_SKILL
- 错误-修复循环 ≥ 2 次 → CREATE_SKILL
- 否则 → RECORD_ONLY

#### 2.1 SKILL 候选挖掘（前置建议）

在决策树判定前，调用 `skill_candidate_miner` 从认知记忆库挖掘可复用为 SKILL 的候选模式：

```
from skill_candidate_miner import mine_candidates
candidates = mine_candidates(min_occurrences=3)
# candidates: [{pattern, occurrences, sample_memories, suggestion}, ...]
```

- 出现 ≥ 3 次的模式自动标记为候选
- 候选列表作为决策树的输入参考（辅助判断是否值得 CREATE_SKILL）
- FAIL-OPEN：挖掘失败不阻塞主流程

### 3. 参数自优化（L4.2）

模块: `dreamos/core/compute/param_optimizer.py` → `ParamOptimizer` + `CostAdaptiveScheduler`

```
optimizer = ParamOptimizer(param_space={
    "tp_ratio": (0.01, 0.05),
    "sl_ratio": (0.01, 0.03),
})
result = optimizer.optimize(
    objective_fn=backtest_fn,
    baseline_score=current_score,
    n_trials=50,
    walk_forward_fn=walk_forward_fn,  # 可选
)
if result.should_apply:
    apply_params(result.best_trial.params)
```

过拟合防护:
- 参数 ≤ 5 个
- walk-forward 验证（3 分割）
- 变异系数 CV > 0.5 → REJECT
- 改进 ≥ 2% 才 APPLY

### 4. 案例库自动 ingest（L4.3）

模块: `dreamos/core/compute/case_ingest_gate.py` → `CaseIngestGate`

```
gate = CaseIngestGate(
    recall_fn=cognitive_recall,
    ingest_fn=evolution_case_ingest,
    record_fn=cognitive_record,
)
report = gate.evaluate_and_ingest(
    cycle_result={"direction": "LONG", "pnl_pct": 0.08, ...},
    market_context={...},
)
```

4 维评估:
- novelty（新颖性）: 与历史案例差异，权重 35%
- significance（显著性）: 盈亏幅度 + 置信度，权重 30%
- anomaly（异常度）: RSI极端/量能异常/价格突变，权重 25%
- reproducibility（可复现性）: 历史相似越多 → 价值越低，权重 10%

决策: ≥0.5 INGEST / 0.3-0.5 DEFERRED / <0.3 SKIP

### 5. 文档自同步（L4.4）

模块: `dreamos/core/compute/doc_sync_trigger.py` → `DocSyncTrigger`

```
trigger = DocSyncTrigger(
    project_root=Path("/path/to/project"),
    record_fn=cognitive_record,
    sync_fn=dream_doc_sync,  # 可选
)
before = trigger.scan_checksums()
# ... 代码变更 ...
after = trigger.scan_checksums()
changes = trigger.detect_changes(before, after)
if changes.needs_sync:
    report = trigger.sync(changes)
```

影响分级:
- critical: Schema/SQL 变更
- major: API 变更、新增/删除文件
- minor: 常规修改
- 仅 major/critical 触发同步

### 6. 认知闭环（任务后）

```
record(content="L4 自迭代经验...", quality_level="B", tags="L4自迭代,hermes反思,SKILL")
verify(memory_id="VM-xxx", success=True)
```

## hermes 反思决策树（任务结束后必执行）

```
本次流程是否值得形成/衍生 SKILL？
├── 是（满足任一）：
│   ├── 流程被复用 ≥ 2 次
│   ├── 涉及多步编排（≥ 3 步）
│   ├── 涉及 bsk 自动化（≥ 1 步）
│   └── 用户明确要求「形成 SKILL」
│   → 调用 skill-creator 创建新 SKILL
│   → record 经验，tags 含「SKILL,hermes反思」
└── 否 → 仅 record 经验
```

## 模块清单

| 模块 | 文件 | 覆盖率 | 测试 |
|------|------|--------|------|
| HermesReflector | `dreamos/core/compute/hermes_reflector.py` | 89% | 17 |
| ParamOptimizer | `dreamos/core/compute/param_optimizer.py` | 91% | 12 |
| CaseIngestGate | `dreamos/core/compute/case_ingest_gate.py` | 88% | 7 |
| DocSyncTrigger | `dreamos/core/compute/doc_sync_trigger.py` | 88% | 16 |
| **合计** | — | **89%** | **52** |

## FAIL-OPEN 原则

所有 L4 模块失败时仅 `logging.warning`，不阻断业务:
- hermes 反思失败 → 跳过，不阻断交易
- 参数优化失败 → 保持当前参数
- 案例入库失败 → 跳过，不影响 SACG 循环
- 文档同步失败 → 跳过，不影响代码运行

## 四层落地路径全貌

| 层级 | 能力 | 状态 |
|------|------|------|
| L1 可观测性 | trace_id + JSONL + PostgreSQL + 中台看板 | ✅ |
| L2 自检测 | 单测 + 契约测试 + 运行时健康检查 | ✅ |
| L3 自修复 | TraceReplay + CircuitBreaker + AutoBugfix + Canary | ✅ |
| L4 自迭代 | HermesReflector + ParamOptimizer + CaseIngestGate + DocSyncTrigger | ✅ |
