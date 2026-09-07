"""Phase 2: 严格型「一损全弃」特征筛选 RED 测试。

验收门槛：5 指标（Sharpe/胜率/收益/回撤/利润因子）任一劣于下限则 FAIL；
必须至少 2 项显著提升；输出 csv 末尾加 [EVAL] 行（不新建脚本）。
"""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def fake_baselines():
    """两条基线 5 指标：B0=K=0 无宏观；B1=现有宏观 Top-K 最优。"""
    return {
        "B0": {"sharpe": 1.20, "win_pct": 0.520, "return_pct": 0.15, "max_dd_pct": 0.16, "profit_factor": 1.35},
        "B1": {"sharpe": 1.45, "win_pct": 0.545, "return_pct": 0.22, "max_dd_pct": 0.12, "profit_factor": 1.55},
    }


class TestStrictCriteriaEvaluator:
    """严格型「一损全弃」判定函数应定义在 macro_feature_select_v2.evaluate_strict_criteria。"""

    def test_evaluator_function_exists(self):
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2
        assert hasattr(mfsv2, "evaluate_strict_criteria"), "evaluate_strict_criteria 函数未定义（FAIL-RED）"

    def test_one_metric_bad_triggers_fail(self, fake_baselines):
        """任一指标劣于下限 → FAIL。例：sharpe 仅 1.10 < min(B0=1.20,B1=1.45)-0.05=1.15 ，应 FAIL。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2

        cand = {"sharpe": 1.10, "win_pct": 0.54, "return_pct": 0.21, "max_dd_pct": 0.12, "profit_factor": 1.50}
        ok, reasons = mfsv2.evaluate_strict_criteria(cand, fake_baselines["B0"], fake_baselines["B1"])
        assert ok is False
        assert any("sharpe" in r for r in reasons), f"原因未含 sharpe 劣: {reasons}"

    def test_two_wins_but_one_lose_fail(self, fake_baselines):
        """即使 2 项显著提升（如 sharpe+0.20，胜率+2pct），但有 1 项劣（回撤 20% > max(16,12)+2=18%）仍 FAIL。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2

        # sharpe=1.68(>1.45+0.2 → 显著), win_pct=0.567(>0.545+0.02 → 显著)
        # return=0.24, pf=1.60 → OK
        # dd=0.20, max(B0,B1)dd=0.16 → 上限=0.18 < 0.20 → 劣
        cand = {"sharpe": 1.68, "win_pct": 0.567, "return_pct": 0.24, "max_dd_pct": 0.20, "profit_factor": 1.60}
        ok, reasons = mfsv2.evaluate_strict_criteria(cand, fake_baselines["B0"], fake_baselines["B1"])
        assert ok is False
        assert any("dd" in r or "drawdown" in r or "回撤" in r for r in reasons)

    def test_no_significant_enhance_fail_even_if_no_degrade(self, fake_baselines):
        """5 指标都不劣，但「显著提升项 <2」→ FAIL（严格型）。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2

        # 各项略优，但无一项达显著
        cand = {"sharpe": 1.47,  # +0.02 vs B1, 远低于 +0.20
                "win_pct": 0.547,  # +0.2pct vs B1, 远低于 +2pct
                "return_pct": 0.225,  # +0.5pct vs B1, 低于 +5pct
                "max_dd_pct": 0.118,  # -0.2pct vs B1, 高于 -3pct
                "profit_factor": 1.56,  # +0.01 vs B1, 低于 +0.10
                }
        ok, reasons = mfsv2.evaluate_strict_criteria(cand, fake_baselines["B0"], fake_baselines["B1"])
        assert ok is False
        assert any("显著" in r or "significant" in r for r in reasons), f"缺少「显著提升不足」原因: {reasons}"

    def test_all_pass_2_significant_returns_true(self, fake_baselines):
        """不劣 + 至少 2 项显著 → PASS。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2

        cand = {
            "sharpe": 1.70,          # 比 B1(1.45) +0.25 → 显著
            "win_pct": 0.570,        # 比 B1 +2.5pct → 显著
            "return_pct": 0.27,      # OK
            "max_dd_pct": 0.10,      # OK（减 2pct）
            "profit_factor": 1.65,   # OK
        }
        ok, reasons = mfsv2.evaluate_strict_criteria(cand, fake_baselines["B0"], fake_baselines["B1"])
        assert ok is True, f"应通过: {reasons}"

    def test_baseline_logger_prints_three_elements(self):
        """Phase0 必须在现有函数入口处 print 基线三要素日志行（不新建脚本）。
        定义 print_baseline_with_evidence(B0_row, B1_row, coin, fold) → 返回 str（含 [BASELINE] 前缀）。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2
        assert hasattr(mfsv2, "print_baseline_with_evidence")
        line = mfsv2.print_baseline_with_evidence(
            {"sharpe": 1.2, "win_pct": 0.52, "return_pct": 0.15, "max_dd_pct": 0.16, "profit_factor": 1.35},
            {"sharpe": 1.45, "win_pct": 0.545, "return_pct": 0.22, "max_dd_pct": 0.12, "profit_factor": 1.55},
            coin="BTC", fold=0,
        )
        assert "[BASELINE]" in line
        assert "BTC" in line and "fold=0" in line


class TestPhase3BestSubsetAndTtest:
    """Phase 3: 最佳子集剪枝 + 走时 t 检验。"""

    def test_subset_pruning_helper(self):
        """best_subset_search(candidate_scores, threshold=0.5) 支持剪枝，返回 (best_names, best_score)。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2
        assert hasattr(mfsv2, "best_subset_search")
        # 单个特征评分: a=1.0, b=0.9, ab=2.1 → best=ab
        scores = {"a": 1.0, "b": 0.9, ("a", "b"): 2.1}
        best, sc = mfsv2.best_subset_search(scores, threshold=0.5)
        assert sc == 2.1
        assert set(best) == {"a", "b"}

    def test_paired_ttest_helper(self):
        """paired_improvement_significant(baseline_metrics, cand_metrics) → bool。
        baseline 15 个样本，cand 15 样本按配对 t 检验 α=0.05。"""
        from scripts.memory_l4.bcrm2 import macro_feature_select_v2 as mfsv2
        assert hasattr(mfsv2, "paired_improvement_significant")
        np.random.seed(42)
        baseline = [1.2 + np.random.randn() * 0.1 for _ in range(15)]
        good = [1.5 + np.random.randn() * 0.1 for _ in range(15)]
        bad = [1.2 + np.random.randn() * 0.1 for _ in range(15)]
        assert mfsv2.paired_improvement_significant(baseline, good, alpha=0.05) is True
        assert mfsv2.paired_improvement_significant(baseline, bad, alpha=0.05) is False
