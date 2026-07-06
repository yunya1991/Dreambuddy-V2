# A0-A9 全链路清单（用于迁移对齐）

- 生成时间：`2026-05-10T16:57:23Z`
- 检查范围：
  - 源仓库：`dream-trading-automation` 分支 `feature/add-skills`（本地分支 `tmp-add-skills` 对齐）
  - 目标仓库：`dream-multiskill-v2`（本地当前）
  - 外部参考：CodeBuddy 分享清单（识别到三大链路与 A1-A6 章节）

## 1. 链路阶段对照表

| 阶段 | v2 目标目录 | 源技能主文件（feature/add-skills） | 源脚本证据（示例） | v2 本地状态 |
|---|---|---|---|---|
| A0 | `workflows/trading-decision/A0_contradiction/` | `1-TRADE/dream-contradiction-theory/SKILL.md` | （未检出阶段脚本） | 待对齐(缺少 entrypoint.py / SKILL) |
| A1 | `workflows/trading-decision/A1_research/` | `1-TRADE/dream-strategy-research/SKILL.md` | `scripts/a1_research.py` | 待对齐(缺少 entrypoint.py / SKILL) |
| A2 | `workflows/trading-decision/A2_first-principles/` | `1-TRADE/dream-first-principles/SKILL.md` | `scripts/a2_first_principles_v2.6.py` | 待对齐(缺少 entrypoint.py / SKILL) |
| A3 | `workflows/trading-decision/A3_simulation/` | `1-TRADE/dream-strategy-designer/SKILL.md`<br>`1-TRADE/dream-strategy-parser/SKILL.md` | `scripts/a4_step9_best_strategy_test.py`<br>`scripts/dream_strategy_pipeline.py`<br>`scripts/master_strategy_retriever.py`<br>`scripts/test_strategy_integration.py` | 待对齐(缺少 entrypoint.py / SKILL) |
| A4 | `workflows/trading-decision/A4_validation/` | `1-TRADE/dream-tactical-validator/SKILL.md`<br>`1-TRADE/dream-pretrade-gatekeeper/SKILL.md` | `scripts/a4_a6_a5_stress_test.py`<br>`scripts/a4_a6_linkage_test.py`<br>`scripts/a4_circuit_breaker_test.py`<br>`scripts/a4_compulsion_repeat_test.py`<br>`scripts/a4_preplacement_checklist.sh`<br>`scripts/a4_scenario_convergence.py` | 待对齐(缺少 entrypoint.py / SKILL) |
| A5 | `workflows/trading-decision/A5_execution/` | `1-TRADE/dream-tactical-executor/SKILL.md` | `scripts/a4_a6_a5_stress_test.py`<br>`scripts/a5_episode_writer_test.py`<br>`scripts/a5_gatekeeper_real_test.py`<br>`scripts/a5_gatekeeper_test.py`<br>`scripts/a5_guards.py`<br>`scripts/a5_l2_l3_test.py` | 待对齐(缺少 entrypoint.py / SKILL) |
| A6 | `workflows/trading-decision/A6_intelligence/` | `1-TRADE/dream-intelligence-monitor/SKILL.md`<br>`1-TRADE/dream-signal-scoring-spec/SKILL.md`<br>`1-TRADE/dream-regime-detector/SKILL.md` | `scripts/a4_a6_a5_stress_test.py`<br>`scripts/a4_a6_linkage_test.py`<br>`scripts/test_a6_level15.py` | 待对齐(缺少 entrypoint.py / SKILL) |
| A7 | `workflows/trading-decision/A7_audit/` | `1-TRADE/A7-practice-theory/SKILL.md` | （未检出阶段脚本） | 待对齐(缺少 entrypoint.py / SKILL) |
| A8 | `workflows/trading-decision/A8_theory-practice/` | `1-TRADE/A8-theory-practice-verification/SKILL.md` | （未检出阶段脚本） | 待对齐(缺少 entrypoint.py / SKILL) |
| A9 | `workflows/trading-decision/A9_exit/` | `1-TRADE/dream-exit-skill-v2/SKILL.md` | （未检出阶段脚本） | 待对齐(缺少 entrypoint.py / SKILL) |

## 2. 结论（本地仓库专项）

- `dream-multiskill-v2` 的 `workflows/trading-decision/A0~A9` 目录已齐全，但目前仍是骨架（仅 `.gitkeep`），尚未引入交易链路技能与入口实现。
- A0-A9 能力在源仓主要以 `1-TRADE/*/SKILL.md` + `scripts/a*_*.py` 形式存在，后续复制应以“阶段技能 + 阶段脚本 + 产物契约”三件套推进。
- 建议迁移顺序：`A0/A1/A2` -> `A3/A4/A5` -> `A6/A7/A8/A9`，每组迁移后做一次门禁与回归。
