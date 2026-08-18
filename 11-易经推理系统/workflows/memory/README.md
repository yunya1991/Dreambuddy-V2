# 记忆工作流分层映射（L1~L4）

本文档定义 `workflows/memory/L1~L4_archive/` 与 `MemoryEngine` 的显式映射关系。

## 分层到能力映射

| 层级目录 | 入口文件 | 主要职责 | 对应 MemoryEngine 能力 |
|---|---|---|---|
| `L1_realtime/` | `entrypoint.py` | 实时检索与排序 | `retrieve_for_decision`, `build_relevance_matrix` |
| `L2_shortterm/` | `entrypoint.py` | 短期反馈回写与健康检查 | `update_bandit_from_episodes`, `check_consistency`, `get_health_score` |
| `L3_longterm/` | `entrypoint.py` | 长期索引维护与质量巡检 | `build_vector_artifacts`, `check_consistency`, `get_health_score` |
| `L4_archive/` | `entrypoint.py` | 归档分析与策略进化输入 | `analyze_failure_memory`, `analyze_cross_market_migration`, `build_shared_memory_graph`, `enqueue_meta_learning_tasks` |

## 设计约束

- 每层入口只做参数编排和调用转发，不在入口层实现复杂业务逻辑。
- 复杂能力统一收敛在 `workflows/memory/memory_engine/engine.py` 与 `scripts/memory_l4/*`。
- 调用方优先通过分层入口访问能力，避免直接散落调用底层脚本。
