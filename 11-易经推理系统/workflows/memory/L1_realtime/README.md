# L1 Realtime 入口映射

## 职责

- 提供实时记忆检索入口。
- 输出结构化检索、语义检索与融合排序结果。

## 调用映射

- `run_l1_realtime_retrieval(...)` -> `MemoryEngine.retrieve_for_decision(...)`
- `run_l1_realtime_relevance(...)` -> `MemoryEngine.build_relevance_matrix(...)`
