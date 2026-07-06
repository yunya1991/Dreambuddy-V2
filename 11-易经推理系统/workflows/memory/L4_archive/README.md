# L4 Archive 入口映射

## 职责

- 对归档记忆进行失败复盘、跨市场迁移分析。
- 生成共享记忆图谱和元学习任务，服务进化工作流。

## 调用映射

- `run_l4_failure_analysis(...)` -> `MemoryEngine.analyze_failure_memory(...)`
- `run_l4_cross_market_migration(...)` -> `MemoryEngine.analyze_cross_market_migration(...)`
- `run_l4_graph_build(...)` -> `MemoryEngine.build_shared_memory_graph(...)`
- `run_l4_meta_task_enqueue(...)` -> `MemoryEngine.enqueue_meta_learning_tasks(...)`
