# 2-INTELLIGENCE Integration — 6-TRADING 集成规范目录

本目录包含从 `dream-multiskill-v2/skills/2-INTELLIGENCE` 引入的 SKILL 与 6-TRADING 的集成规范。

> 原始 SKILL 定义保留在 dream-multiskill-v2 仓库，本目录仅描述**接入点、注入规则、6-TRADING 专用参数**。

---

## 集成清单

| 文件夹 | SKILL | 集成位置 | 优先级 | 状态 |
|-------|-------|---------|-------|------|
| [data-analysis/](data-analysis/INTEGRATION.md) | dream-data-analysis | Process D Step 1.5 + Screen 2 Phase-2 | P1 | v1.0 |
| [intelligence-analysis/](intelligence-analysis/INTEGRATION.md) | dream-intelligence-analysis | Screen1 A1/A2/A3 注入 + Gate C + A8 | P1 | v1.0 |
| [master-seminar/](master-seminar/INTEGRATION.md) | master-seminar | Screen1 A3后 + Process D 大师进化 | P2 | v1.0 |
| [archive-center/](archive-center/INTEGRATION.md) | dream-archive-center | Screen1 Phase-0 P0.4b | P3 | v1.0 |
| [oneirology/](oneirology/INTEGRATION.md) | dream-oneirology | Process D Step 0 并行 | P4 | v1.0 |

---

**集成方式说明**:
- `dream-data-analysis` / `master-seminar` / `dream-oneirology`: 新增独立步骤，产出新文件
- `dream-intelligence-analysis` / `dream-archive-center`: **纯提示词注入**，不改变文件结构骨架

*维护规则: 每次原始 SKILL 版本升级时，检查对应 INTEGRATION.md 是否需要更新接入参数。*
