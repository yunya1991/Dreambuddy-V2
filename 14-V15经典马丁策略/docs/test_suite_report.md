# V15 双基线 AB 影子对比框架 — 测试套件运行报告

**生成时间**: 2026-08-19 11:42:42

**总用例数**: 58
**通过**: 58 | **失败**: 0 | **错误**: 0

## 测试结果明细

| # | 测试类 | 用例 | 状态 | 耗时(s) |
|---|---|---|---|---|
| 1 | `TestABComparatorCore` | `test_a01_decision_record_new_fields` | PASS | 0.003 |
| 2 | `TestABComparatorCore` | `test_a02_build_position_ref_granularity` | PASS | 0.000 |
| 3 | `TestABComparatorCore` | `test_a03_exact_t_cdf` | PASS | 0.001 |
| 4 | `TestABComparatorCore` | `test_a04_backfill_matching_modes` | PASS | 0.002 |
| 5 | `TestABComparatorCore` | `test_a05_ai_path_pnl_estimates` | PASS | 0.004 |
| 6 | `TestABComparatorCore` | `test_a06_state_machine_promote_and_rollback` | PASS | 0.045 |
| 7 | `TestABComparatorCore` | `test_a07_corrupted_state_recovery` | PASS | 0.003 |
| 8 | `TestABComparatorCore` | `test_a08_dynamic_baseline_set_and_get` | PASS | 0.001 |
| 9 | `TestABComparatorCore` | `test_a09_version_comparison_promote` | PASS | 0.001 |
| 10 | `TestABComparatorCore` | `test_a10_version_comparison_reject` | PASS | 0.001 |
| 11 | `TestABComparatorCore` | `test_a11_version_comparison_no_baseline_auto_promote` | PASS | 0.001 |
| 12 | `TestABComparatorCore` | `test_a12_version_comparison_partial_win` | PASS | 0.001 |
| 13 | `TestModelVersionManager` | `test_b01_register_first_vs_second_version` | PASS | 0.003 |
| 14 | `TestModelVersionManager` | `test_b02_promote_shadow_demotes_old_live` | PASS | 0.003 |
| 15 | `TestModelVersionManager` | `test_b03_rollback_live` | PASS | 0.005 |
| 16 | `TestModelVersionManager` | `test_b04_disable_and_archive` | PASS | 0.005 |
| 17 | `TestIncrementalTrainerCore` | `test_b05_check_new_trades_various` | PASS | 0.002 |
| 18 | `TestIncrementalTrainerCore` | `test_b06_auto_retrain_threshold` | PASS | 0.002 |
| 19 | `TestIncrementalTrainerCore` | `test_b07_evaluate_and_promote_transitions` | PASS | 0.039 |
| 20 | `TestIncrementalTrainerCore` | `test_b08_gateway_hot_swap_models` | PASS | 1.653 |
| 21 | `TestIncrementalTrainerDualBaseline` | `test_b09_first_version_bootstrap` | PASS | 1.592 |
| 22 | `TestIncrementalTrainerDualBaseline` | `test_b10_inferior_version_rejected` | PASS | 0.006 |
| 23 | `TestIncrementalTrainerDualBaseline` | `test_b11_superior_version_promoted` | PASS | 0.003 |
| 24 | `TestDecisionMatrix` | `test_c01_row1_first_version_bootstrap` | PASS | 0.002 |
| 25 | `TestDecisionMatrix` | `test_c02_row2_inferior_version_disabled` | PASS | 0.003 |
| 26 | `TestDecisionMatrix` | `test_c03_row3_superior_with_ab_live` | PASS | 0.004 |
| 27 | `TestDecisionMatrix` | `test_c04_row4_superior_but_ab_no_samples` | PASS | 0.004 |
| 28 | `TestDecisionMatrix` | `test_c05_row5_superior_but_ab_disabled` | PASS | 0.003 |
| 29 | `TestDecisionMatrix` | `test_c06_row6_live_to_shadow_rollback` | PASS | 0.004 |
| 30 | `TestScoringRules` | `test_c07_score_0_all_inferior` | PASS | 0.001 |
| 31 | `TestScoringRules` | `test_c08_score_1_only_one_better` | PASS | 0.001 |
| 32 | `TestScoringRules` | `test_c09_score_2_pnl_within_tolerance` | PASS | 0.001 |
| 33 | `TestScoringRules` | `test_c10_score_2_pnl_beyond_tolerance` | PASS | 0.001 |
| 34 | `TestScoringRules` | `test_c11_score_3_all_superior` | PASS | 0.001 |
| 35 | `TestScoringRules` | `test_c12_pnl_delta_calculation` | PASS | 0.001 |
| 36 | `TestScoringRules` | `test_c13_pnl_delta_zero_baseline` | PASS | 0.001 |
| 37 | `TestBootstrapLogic` | `test_c14_bootstrap_sets_dynamic_baseline` | PASS | 0.002 |
| 38 | `TestBootstrapLogic` | `test_c15_bootstrap_does_not_fire_with_existing_baseline` | PASS | 0.002 |
| 39 | `TestABStateMachineTransitions` | `test_c16_shadow_to_live_positive_significance` | PASS | 0.032 |
| 40 | `TestABStateMachineTransitions` | `test_c17_shadow_to_disabled_negative_significance` | PASS | 0.036 |
| 41 | `TestABStateMachineTransitions` | `test_c18_insufficient_samples_no_transition` | PASS | 0.011 |
| 42 | `TestPnLBackfill` | `test_c19_level1_position_ref_exact_match` | PASS | 0.001 |
| 43 | `TestPnLBackfill` | `test_c20_level2_symbol_timestamp_fuzzy_match` | PASS | 0.001 |
| 44 | `TestPnLBackfill` | `test_c21_level3_symbol_fallback` | PASS | 0.001 |
| 45 | `TestPnLBackfill` | `test_c22_no_match_returns_zero` | PASS | 0.001 |
| 46 | `TestPnLBackfill` | `test_c23_ai_pnl_estimation_open_skip` | PASS | 0.001 |
| 47 | `TestPnLBackfill` | `test_c24_ai_pnl_estimation_same_action` | PASS | 0.001 |
| 48 | `TestVersionIteration` | `test_c25_scenario_6_1_normal_evolution` | PASS | 0.008 |
| 49 | `TestVersionIteration` | `test_c26_scenario_6_2_inferior_rejected` | PASS | 0.010 |
| 50 | `TestVersionIteration` | `test_c27_scenario_6_3_live_rollback` | PASS | 0.007 |
| 51 | `TestMonitoringReport` | `test_c28_report_has_all_fields` | PASS | 0.001 |
| 52 | `TestMonitoringReport` | `test_c29_report_dynamic_baseline_info` | PASS | 0.001 |
| 53 | `TestMonitoringReport` | `test_c30_report_no_dynamic_baseline` | PASS | 0.001 |
| 54 | `TestMonitoringReport` | `test_c31_report_action_distribution` | PASS | 0.004 |
| 55 | `TestMonitoringReport` | `test_c32_report_ai_model_stats` | PASS | 0.002 |
| 56 | `TestConfigParams` | `test_c33_min_samples_constant` | PASS | 0.000 |
| 57 | `TestConfigParams` | `test_c34_state_thresholds` | PASS | 0.000 |
| 58 | `TestConfigParams` | `test_c35_max_records_cap` | PASS | 9.706 |

## 测试套件结构

| 模块 | 测试类 | 用例数 | 覆盖文档章节 |
|---|---|---|---|
| §A ABShadowComparator 核心 | `TestABComparatorCore` | 12 | §5 状态机 + §5.3 PnL回填 + §7 配置 |
| §B ModelVersionManager | `TestModelVersionManager` | 4 | §4 版本注册/晋升/回滚 |
| §B IncrementalTrainer 核心 | `TestIncrementalTrainerCore` | 4 | §4 调用链 + §4.2 热切换 |
| §B 增量训练双基线 | `TestIncrementalTrainerDualBaseline` | 3 | §3.3 bootstrap + 版本迭代 |
| §C 决策矩阵 | `TestDecisionMatrix` | 6 | §3.1 决策矩阵 6 行 |
| §C 评分规则 | `TestScoringRules` | 7 | §3.2 评分边界条件 |
| §C Bootstrap | `TestBootstrapLogic` | 2 | §3.3 首版本 bootstrap |
| §C 状态机 | `TestABStateMachineTransitions` | 3 | §5.2 状态转移条件 |
| §C PnL回填 | `TestPnLBackfill` | 6 | §5.3 三级匹配 |
| §C 版本迭代 | `TestVersionIteration` | 3 | §6 三种迭代场景 |
| §C 监控报告 | `TestMonitoringReport` | 5 | §10 generate_report |
| §C 配置参数 | `TestConfigParams` | 3 | §7 阈值常量 |
| **合计** | **12 个测试类** | **58** | **10 个章节全覆盖** |
