# L4记忆规范目录

本目录用于集中管理 L4 记忆工作流在底层约束层的核心规范，减少 `workflows-spec` 根目录散乱问题。

## 文件索引

- `architecture-and-workflow-design.md`：L4 记忆工程架构规范（约束层基线）。
- `acceptance-checklist.md`：L4 两级门禁验收清单（`skeleton-ready` / `production-ready`）。

## 主从映射

- 顶层工程设计（主）：`docs/superpowers/plans/2026-05-12-l4-memory-architecture-upgrade.md`
- 补充规范：`docs/superpowers/specs/2026-05-12-l4-memory-architecture-and-workflow-design.md`
- 约束层架构规范（从）：`constraints/workflows-spec/l4-memory/architecture-and-workflow-design.md`
- 运行契约入口：`constraints/workflows-spec/memory.md`

## Schema 对照

- TradeCase v0.1：`.workbuddy/memory_l4/schemas/trade_case.schema.json`（现有基线）
- TradeCase v0.2：`.workbuddy/memory_l4/schemas/trade_case.schema.v0.2.json`（升级草案）
- Distill v0.1：`.workbuddy/memory_l4/schemas/distill.schema.json`（现有基线）
- Distill v0.2：`.workbuddy/memory_l4/schemas/distill.schema.v0.2.json`（升级草案）
- ReviewRecord v0.1：`.workbuddy/memory_l4/schemas/review.schema.json`（全新）
- StatsSnapshot：`.workbuddy/memory_l4/schemas/stats.schema.json`（已升级 v0.2）
