# L4记忆工程架构规范（约束层）

Date: 2026-05-12
Status: Active Baseline (Constraint Layer)
Type: 顶层工程设计在约束层的正式落地镜像
Upstream Canonical: `docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md`

## 1. 规范定位

本文件是 L4 记忆工作流在约束层的核心工程规范。目标是把顶层设计固化为可执行条款，并作为后续分支实现对齐基准。

主从关系：

- 顶层设计（主）：`docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md`
- 补充规范：`docs/superpowers/specs/2026-05-12-l4-memory-architecture-and-workflow-design.md`
- 约束镜像（从）：`constraints/workflows-spec/l4-memory/architecture-and-workflow-design.md`

## 2. 强制约束

- `constraints` 是唯一规则源（SSOT）。
- 进化主链必须为：`memory -> evolution -> constraints`。
- 任一阶段失败必须 fail-closed，并落审计字段：`stage/reason_code/evidence_refs`。
- 入口层只做薄封装，复杂逻辑下沉至 `memory_engine` 与 `scripts/memory_l4/`。

## 3. 核心对象契约（最小集）

### 3.1 TradeCase.vNext

- `thinking_chain[]`
- `evidence_chain[]`
- `decision_outcome`
- `l4_status`

兼容策略：保留旧字段（如 `plan.steps`）读取，新字段先可选后强约束。

### 3.2 ReviewRecord

- `mistakes[]`
- `successes[]`
- `theory_practice_gap`

### 3.3 DistillRecord.vNext

- `what_is_it`
- `why_it_works`
- `how_to_apply`
- `process_trace`

兼容策略：保留 `claim/actionable_rules` 并建立映射。

### 3.4 StatsSnapshot

四象限 `x/y` 不变，新增过滤维度：

- `regime`
- `category`
- `severity`

## 4. L4状态机与失败语义

状态机：

- `M0_CASE_REGISTERED`
- `M1_REVIEW_COMPLETED`
- `M2_DISTILL_COMPLETED`
- `M3_STATS_UPDATED`
- `M4_CANDIDATE_EMITTED`
- `M_FAIL`

失败语义最小集：

- `CASE_INCOMPLETE`
- `EVIDENCE_MISSING`
- `REVIEW_INCONSISTENT`
- `DISTILL_INVALID`
- `STATS_INTEGRITY_FAILED`
- `CANDIDATE_EMIT_BLOCKED`

## 5. 顶层到实现映射

| 层级 | 路径 | 职责 |
|---|---|---|
| 顶层设计 | `docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md` | 完整架构方案 |
| 约束层 | `constraints/workflows-spec/l4-memory/` | 可执行条款 + 验收清单 |
| Schema | `.workbuddy/memory_l4/schemas/` | 数据契约 JSON Schema |
| 入口层 | `workflows/memory/L1~L4_archive/entrypoint.py` | 薄封装 |
| 编排层 | `workflows/memory/memory_engine/` | 核心编排 |
| 实现层 | `scripts/memory_l4/` | 具体模块实现 |

已实现的工程模块：

- `case_registry.py` — TradeCase 注册（支持 v0.2 字段初始化）
- `a0a9_bridge.py` — A0-A9 阶段数据桥接（含 `l4_status` + `decision_outcome`）
- `review_engine.py` — 对错双向复盘
- `a7a8_bridge.py` — A7/A8 报告桥接
- `distill_engine.py` — 11步流程 + 三问蒸馏
- `index_builder.py` — 索引构建（含思维链特征）
- `query_similar.py` — 相似检索（含 L1 实时接口）
- `stats_engine.py` — 统计快照（含 event_library + evolution_metrics）
- `pipeline.py` — M0→M4 全流程编排器
- `distill_template.py` — 蒸馏模板（兼容 CLI）
- `quadrant_migrator.py` — 四象限迁移
- `failure_analyzer.py` — 失败分析（将并入 review_engine）
- `dashboard_renderer.py` — 仪表盘渲染
- `shared_memory_bus.py` — JSONL 事件总线
- `memory_graph.py` — Agent-记忆关系图
- `meta_learning_tasks.py` — 元学习任务调度
- `migration_mapper.py` — 跨市场迁移映射

目标能力（分阶段落地）：

- `review_engine` — P2 完成
- `a7_a8_adapter` — P2 完成
- `thinking_chain_index_extension` — P1 完成
- `semantic_index` — P3

## 6. 阶段路线

- P0：契约固化（Schema + 状态机 + 失败语义）
- P1：链路打通（事件入库 → 复盘 → 蒸馏 → 统计 → 候选）
- P2：演化强化（动态演化 + evolution 门禁联动）
- P3：认知强化（语义索引 + 知识源扩展）

## 7. 维护规则

- 任何字段/状态机变更必须同步本文件与顶层设计文档。
- 新增 L4 规范必须更新 `constraints/workflows-spec/l4-memory/README.md` 与上层索引。
- Schema 版本升级（v0.1 → v0.2）必须保持向后兼容。
