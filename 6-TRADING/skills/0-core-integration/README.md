# 0-CORE Integration — 6-TRADING 集成规范目录

本目录包含从 `dream-multiskill-v2/skills/0-CORE` 引入的 SKILL 与 6-TRADING 的集成规范。

> 原始 SKILL 定义保留在 dream-multiskill-v2 仓库，本目录仅描述**接入点、适配规则、6-TRADING 专用参数**。

---

## 集成清单

| 文件夹 | SKILL | 集成团队 | 状态 |
|-------|-------|---------|------|
| [artifact-alignment/](artifact-alignment/INTEGRATION.md) | artifact-alignment-manager | Team C (C4) | v1.0 |
| [episode-writer/](episode-writer/INTEGRATION.md) | learning-episode-writer | Team B (B9) | v1.0 |
| [knowledge/](knowledge/INTEGRATION.md) | dream-knowledge | Knowledge Base (K1) | v1.0 |
| [lesson-distiller/](lesson-distiller/INTEGRATION.md) | learning-lesson-distiller | Process D (D2) | v1.0 |
| [proposal-generator/](proposal-generator/INTEGRATION.md) | learning-proposal-generator | Process D (D3) | v1.0 |

dream-constitution 映射文件在 [docs/CONSTITUTION_COMPLIANCE.md](../../docs/CONSTITUTION_COMPLIANCE.md)。

---

*维护规则: 每次 0-CORE SKILL 版本升级时，检查对应 INTEGRATION.md 是否需要更新接入参数。*
