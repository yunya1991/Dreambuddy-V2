# Archive Information Model

本文件冻结 `7-ARTIFACT-HUB-V2` 当前阶段的文档分类法与归档信息模型，用来回答“什么文档应该放在哪一层”。

当前阶段只冻结文档骨架、目录语义和索引入口，不移动代码或原始设计文件。

## 1. Document Classes

| Class | Directory | Examples |
|---|---|---|
| Architecture | `docs/architecture/` | system map, boundaries, diagrams |
| Integration | `docs/integration/` | frontend-hub-trading linkage |
| Governance | `docs/governance/` | policy, console, board, market console |
| Recovery | `docs/recovery/` | migration, recovery, archive ledger |
| Execution Plans | `docs/superpowers/plans/` | step-by-step implementation plans |

## 2. Placement Rules

- A doc describing runtime ownership goes to `architecture/`.
- A doc describing system coupling goes to `integration/`.
- A doc describing control, audit, approval, policy goes to `governance/`.
- A doc describing migration, restore, rollback, archive execution goes to `recovery/`.

## 3. Freeze Scope

- 冻结的是文档分类口径，不是物理文件迁移动作。
- 现有根目录文档和 `docs/*.html` 可以先通过索引承接，不要求立即改路径。
- 后续新增文档应优先按本模型归档，避免继续按临时路径散落。
