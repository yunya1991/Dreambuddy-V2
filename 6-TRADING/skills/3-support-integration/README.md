# 3-SUPPORT Integration — 6-TRADING 集成规范目录

本目录包含从 `dream-multiskill-v2/skills/3-SUPPORT` 引入的 SKILL 与 6-TRADING 的集成规范。

> 原始 SKILL 定义保留在 dream-multiskill-v2 仓库，本目录仅描述**接入点、触发规则、6-TRADING 专用参数**。

---

## 集成清单

| 文件夹 | SKILL | 集成位置 | 优先级 | 状态 |
|-------|-------|---------|-------|------|
| [ai-trading-compliance/](ai-trading-compliance/INTEGRATION.md) | ai-trading-compliance | Governance G2 — 提案合规门禁 | P0 | v1.0 |
| [auto-repair/](auto-repair/INTEGRATION.md) | auto-repair | Governance G3 — 提案落地 + 账户隔离 | P0 | v1.0 |
| [dream-cost-control/](dream-cost-control/INTEGRATION.md) | dream-cost-control | Team A Phase-0 预算守卫 + Process D CC | P0 | v1.0 |
| [dream-performance-review/](dream-performance-review/INTEGRATION.md) | dream-performance-review | Process D Step 0 前置评估 | P1 | v1.0 |
| [resource-efficiency-analyst/](resource-efficiency-analyst/INTEGRATION.md) | resource-efficiency-analyst | Process D Step 1.5c + 独立日报 | P1 | v1.0 |
| [dream-operation-director/](dream-operation-director/INTEGRATION.md) | dream-operation-director | Governance G4 — 跨团队升级路由 | P2 | v1.0 |

---

**集成方式说明**:
- `ai-trading-compliance` / `auto-repair`: 新增 Governance 层，提案全生命周期管理
- `dream-cost-control`: 双向集成——Team A Phase-0 Tavily 预算守卫 + Process D 成本归因
- `dream-performance-review` / `resource-efficiency-analyst`: Process D 量化评估扩充
- `dream-operation-director`: 纯升级路由，不改变执行流，按需触发

*维护规则: 每次原始 SKILL 版本升级时，检查对应 INTEGRATION.md 是否需要更新接入参数。*
