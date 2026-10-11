# 日志证据 — SPEC→代码→运行→日志 追溯链（HC-9 强制）

> 本文档对齐 dream-acceptance-verify v1.1.0 HC-9：功能验收日志必须追溯 SPEC。
> 每个功能四点一致：SPEC AC 定义 → 代码实现 → 运行触发 → 日志/Evidence 非空 metrics

## 追溯链矩阵

| SPEC AC | 代码位置 | 运行命令 | repro_after.log observed= 标记行 | metrics 非空验证 |
|---------|---------|---------|-----------------------------------|------------------|
| AC-1 设计决策还原 | core/design_decision_recovery.py:DesignDecisionRecoverer.recover | run_repro.py AC-1 块 | `observed=AC-1 decisions_count=1 has_decision=True has_context=True has_evidence=True` | decisions_count=1 (非0), has_evidence=True ✅ |
| AC-2 架构模式识别 | core/architecture_pattern_detector.py:ArchitecturePatternDetector.detect | run_repro.py AC-2 块 | `observed=AC-2 patterns_count=1 provenance_nonempty=True level=derivation` | patterns_count=1, provenance_nonempty=True, level=derivation ✅ |
| AC-3 演化叙事 | core/evolution_narrative.py:EvolutionNarrator.generate | run_repro.py AC-3 块 | `observed=AC-3 turning_points_count=1 commit_hash_exists=True files_changed=2` | turning_points_count=1, commit_hash_exists=True, files_changed=2(非0) ✅ |
| AC-4 方法论抽象 | core/methodology_abstraction.py:MethodologyAbstractor.abstract | run_repro.py AC-4 块 | `observed=AC-4 methodologies_count=1 problem_pattern_has_MVC=True source_projects_count=3` | methodologies_count=1, problem_pattern_has_MVC=True, source_projects_count=3 ✅ |
| AC-5 AI 审计 | core/ai_audit.py:AIAuditor.audit + compute_poe_score | run_repro.py AC-5 块 | `observed=AC-5 evidence_chain_score=0.000 poe_score=0.200 gate=reject debts_count=4` | poe_score=0.200 (非默认0), gate=reject, debts_count=4 (非0) ✅ |
| AC-6 Evidence-First | 全模块 evidence 字段扫描 | run_repro.py AC-6 块 | `observed=AC-6 total_evidence=6 bare_conclusions=0 verdict=PASS` | total_evidence=6, bare_conclusions=0 (硬约束通过) ✅ |
| AC-7 DSH 节点 | dsh_nodes.py:S33_rea_audit | run_repro.py AC-7 块 | `observed=AC-7 ok=True has_target=True has_evidence=True has_known_gaps=True gate=reject` | ok=True, has_target/evidence/known_gaps=True ✅ |
| AC-8 认知集成 | core/cognitive_integration.py:prepare_audit_record_params | run_repro.py AC-8 块 | `observed=AC-8 has_content=True has_quality_level=True tags_has_rea_audit=True` | has_content=True, tags_has_rea_audit=True ✅ |
| AC-9 决策质量 | core/design_decision_recovery.py (对 33-REA 自身 core/) | run_repro.py AC-9 块 | `observed=AC-9 self_recover decisions_count=8` | decisions_count=8 (非0，能识别自身模块的设计) ✅ |
| AC-10 叙事可读性 | core/evolution_narrative.py + core/ai_audit.py (对 33-REA 自身 core/) | run_repro.py AC-10 块 | `observed=AC-10 self_audit poe_score=0.333 gate=reject evidence_chain=0.315` | poe_score=0.333, evidence_chain=0.315 (非空) ✅ |
| NFR-1a Inference 控制 | core/design_decision_recovery.py:_infer_alternatives | run_repro.py NFR-1a 块 | `observed=NFR-1a inference_count=1 all_have_known_gaps=True all_confidence_le_0.6=True` | all_have_known_gaps=True, all_confidence_le_0.6=True ✅ |
| NFR-7 FAIL-OPEN | core/ai_audit.py:_failopen_unknown | run_repro.py NFR-7 块 | `observed=NFR-7 poe_score=0.0 gate=review has_unknown_evidence=True` | poe_score=0.0, gate=review, has_unknown_evidence=True ✅ |

## 结论

**12/12 追溯链全部通过**：每个 SPEC 规划功能都有：
1. ✅ 明确的 SPEC AC 定义（在 SPEC-工程实践复现器.md）
2. ✅ 代码实现位置（在 33-REA逆向解析工程/core/ 相应文件）
3. ✅ 实际运行触发（run_repro.py 端到端）
4. ✅ 日志 observed= 标记行（repro_after.log），含非空、非默认的 metrics

**SPEC→代码→运行→日志 四点一致**，符合 dream-acceptance-verify v1.1.0 HC-9 硬约束。
