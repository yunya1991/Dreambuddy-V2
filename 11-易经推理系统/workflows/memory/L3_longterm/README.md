# L3 Longterm 入口映射

## 职责

- 维护向量索引产物，保障长期检索基座可用。
- 提供长期一致性与健康状态快照。

## 调用映射

- `run_l3_longterm_maintenance(...)` -> `MemoryEngine.build_vector_artifacts(...)`
- `run_l3_longterm_maintenance(...)` -> `MemoryEngine.check_consistency() + get_health_score()`
