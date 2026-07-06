# 记忆工作流规范

定义 L1-L4 记忆、复盘、蒸馏、索引与统计的输入输出契约。

## 顶层工程规范映射

- 顶层工程设计（主）：`docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md`
- 补充规范：`docs/superpowers/specs/2026-05-12-l4-memory-architecture-and-workflow-design.md`
- 约束层架构规范（从）：`constraints/workflows-spec/l4-memory/architecture-and-workflow-design.md`

执行原则：

- 本文档负责运行入口与调用契约。
- L4 架构细则以约束层架构规范为准，并与顶层工程设计保持同步。
- 任何 L4 对象模型变更（`TradeCase/ReviewRecord/DistillRecord/StatsSnapshot`）必须双向同步至上述两份文档。

## L1~L4 显式入口映射

- `workflows/memory/L1_realtime/entrypoint.py`
  - `run_l1_realtime_retrieval` -> `MemoryEngine.retrieve_for_decision`
  - `run_l1_realtime_relevance` -> `MemoryEngine.build_relevance_matrix`
- `workflows/memory/L2_shortterm/entrypoint.py`
  - `run_l2_shortterm_feedback` -> `MemoryEngine.update_bandit_from_episodes`
  - `run_l2_shortterm_health_check` -> `MemoryEngine.check_consistency + get_health_score`
- `workflows/memory/L3_longterm/entrypoint.py`
  - `run_l3_longterm_maintenance` -> `MemoryEngine.build_vector_artifacts + check_consistency + get_health_score`
- `workflows/memory/L4_archive/entrypoint.py`
  - `run_l4_failure_analysis` -> `MemoryEngine.analyze_failure_memory`
  - `run_l4_cross_market_migration` -> `MemoryEngine.analyze_cross_market_migration`
  - `run_l4_graph_build` -> `MemoryEngine.build_shared_memory_graph`
  - `run_l4_meta_task_enqueue` -> `MemoryEngine.enqueue_meta_learning_tasks`

## 约束

- 入口层只做薄封装，不承载复杂业务逻辑。
- 复杂能力统一下沉至 `workflows/memory/memory_engine/` 与 `scripts/memory_l4/`。
- 所有入口调用应传递 `trace_id`、`evidence_refs` 等主链必需字段（由上游调用方负责组装）。
- L4 工作流状态机与失败语义（`M0~M4/M_FAIL`）遵循 `l4-memory/architecture-and-workflow-design.md`。
- L4 输出候选进入进化链时，必须遵循 `memory -> evolution -> constraints`。
