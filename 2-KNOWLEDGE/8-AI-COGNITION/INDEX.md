# 8-AI-COGNITION — AI沉淀资料库索引

> **定位：** 指向4-MEMORY认知系统的导航索引，不存储记忆本身。
> **读者：** 需要从知识库反查认知记忆、理解记忆类型的开发者
> **来源：** 4-MEMORY/MEMORY_SYSTEM.md + 0-元记忆/MEMORY_TYPES.md

---

## 文件列表

| 文件 | 说明 |
|------|------|
| [认知系统架构.md](./认知系统架构.md) | 4-MEMORY系统结构说明 |
| [记忆类型映射.md](./记忆类型映射.md) | S/A/B/C/D级记忆→知识库域的映射 |
| [检索指南.md](./检索指南.md) | 如何通过recall检索认知记忆 |
| [SKILL_IMITATION_EVOLUTION_SPEC.md](../../1-ARCHITECTURE/specs/SKILL_IMITATION_EVOLUTION_SPEC.md) | **SIE-SPEC v0.3** — 路径B模仿+路径C联网兜底+ImitationCounter+token埋点（172/172 GREEN） |
| [SPEC-20261009-SOLUTION-PATTERN-LEARNER.md](../../3.1-FRONTEND/docs/SPEC-20261009-SOLUTION-PATTERN-LEARNER.md) | **SPL v0.3** — SolutionPatternLearner 全链路训练蒸馏：TDR+VQ-VAE+5层训练循环+评估层+MCTS反思+漂移检测（271/271 GREEN） |

## 与4-MEMORY的关系

```
2-KNOWLEDGE/8-AI-COGNITION/    ←──索引指向──    4-MEMORY/
  (导航索引)                                      (实际记忆存储)
  ├── 认知系统架构.md                              ├── 0-元记忆/
  ├── 记忆类型映射.md                              ├── 2-交易记忆单元/
  └── 检索指南.md                                  ├── 9-工具与接口/
                                                   └── data/cognitive_memory.db
```

**原则**: 本目录只存导航和说明，实际记忆数据在4-MEMORY/data/cognitive_memory.db。

---

_最后更新：2026-10-09 | 来源：知识库增量重构方案A + dream-doc-sync-workflow (SIE-SPEC v0.3 + SPL v0.3 落地)_
