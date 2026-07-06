# SKILL 全量清单（用于复制完整性审计）

- 审计时间：`2026-05-11`
- 源基线：`dream-trading-automation@origin/feature/add-skills`
- 目标基线：`dream-multiskill-v2@origin/main`（`skills/`）
- 审计口径：按 `SKILL.md` 所在目录对比（`0-CORE` ~ `4-GENERIC`）

## 1. 审计结论

- 系统所需基线技能总数：`47`
- 已复制到目标 `skills/` 的基线技能：`47`
- 未复制缺口：`0`
- 目标仓额外治理技能（非源仓基线）：`3`
- 复制完整率：`100%`

额外治理技能如下（属于 `dream-multiskill-v2` 自有能力，不计为缺口）：

- `skills/0-CORE/architecture-sync-guard/SKILL.md`
- `skills/0-CORE/code-review-merge-assistant/SKILL.md`
- `skills/0-CORE/safe-main-merge/SKILL.md`

## 2. 按重要级状态

### P0（交易主链与记忆闭环，必须）

- `1-TRADE` A0-A9 对应技能：`已全部覆盖`
- `0-CORE/memory-manager`：`已覆盖`
- `2-INTELLIGENCE/dream-oneirology`、`dream-archive-center`、`dream-intelligence-analysis`：`已覆盖`

### P1（运行保障与治理协同，应覆盖）

- `0-CORE` 其余治理/知识技能：`已覆盖`
- `3-SUPPORT` 全部支撑技能：`已覆盖`
- `2-INTELLIGENCE` 其余分析技能：`已覆盖`

### P2（通用与效率增强，可持续优化）

- `4-GENERIC` 全部工具技能：`已覆盖`
- `skills/4-GENERIC/skill-creator/skill-creator/SKILL.md` 与父目录并存：`保留，建议后续做目录规范化评审`

## 3. 分层基线清单（47/47）

### 0-CORE（8/8）

- `0-CORE/artifact-alignment-manager/SKILL.md`
- `0-CORE/dream-constitution/SKILL.md`
- `0-CORE/dream-governance-manager/SKILL.md`
- `0-CORE/dream-knowledge/SKILL.md`
- `0-CORE/learning-episode-writer/SKILL.md`
- `0-CORE/learning-lesson-distiller/SKILL.md`
- `0-CORE/learning-proposal-generator/SKILL.md`
- `0-CORE/memory-manager/SKILL.md`

### 1-TRADE（16/16）

- `1-TRADE/A7-practice-theory/SKILL.md`
- `1-TRADE/A8-theory-practice-verification/SKILL.md`
- `1-TRADE/dream-contradiction-theory/SKILL.md`
- `1-TRADE/dream-execution-cost-model/SKILL.md`
- `1-TRADE/dream-exit-skill-v2/SKILL.md`
- `1-TRADE/dream-first-principles/SKILL.md`
- `1-TRADE/dream-intelligence-monitor/SKILL.md`
- `1-TRADE/dream-pretrade-gatekeeper/SKILL.md`
- `1-TRADE/dream-regime-detector/SKILL.md`
- `1-TRADE/dream-risk-position-sizing/SKILL.md`
- `1-TRADE/dream-signal-scoring-spec/SKILL.md`
- `1-TRADE/dream-strategy-designer/SKILL.md`
- `1-TRADE/dream-strategy-parser/SKILL.md`
- `1-TRADE/dream-strategy-research/SKILL.md`
- `1-TRADE/dream-tactical-executor/SKILL.md`
- `1-TRADE/dream-tactical-validator/SKILL.md`

### 2-INTELLIGENCE（7/7）

- `2-INTELLIGENCE/dream-archive-center/SKILL.md`
- `2-INTELLIGENCE/dream-bailian-integration/SKILL.md`
- `2-INTELLIGENCE/dream-data-analysis/SKILL.md`
- `2-INTELLIGENCE/dream-intelligence-analysis/SKILL.md`
- `2-INTELLIGENCE/dream-knowledge/SKILL.md`
- `2-INTELLIGENCE/dream-oneirology/SKILL.md`
- `2-INTELLIGENCE/master-seminar/SKILL.md`

### 3-SUPPORT（9/9）

- `3-SUPPORT/ai-trading-compliance/SKILL.md`
- `3-SUPPORT/auto-repair/SKILL.md`
- `3-SUPPORT/boss-secretary/SKILL.md`
- `3-SUPPORT/dream-cost-control/SKILL.md`
- `3-SUPPORT/dream-hr-recruitment/SKILL.md`
- `3-SUPPORT/dream-operation-director/SKILL.md`
- `3-SUPPORT/dream-performance-review/SKILL.md`
- `3-SUPPORT/dream-product-hub-maintenance/SKILL.md`
- `3-SUPPORT/resource-efficiency-analyst/SKILL.md`

### 4-GENERIC（7/7）

- `4-GENERIC/find-skills/SKILL.md`
- `4-GENERIC/github/SKILL.md`
- `4-GENERIC/markdown-convert/SKILL.md`
- `4-GENERIC/ontology/SKILL.md`
- `4-GENERIC/skill-creator/SKILL.md`
- `4-GENERIC/skill-creator/skill-creator/SKILL.md`
- `4-GENERIC/tavily/SKILL.md`
