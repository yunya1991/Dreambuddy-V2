"""T_C5 验收测试：baseline_manager 双基线扩展

位置: scripts/memory_l4/tests/test_phase_c_dual_baseline.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_dual_baseline.py -v

对应 Plan §T_C5: baseline_manager 双基线扩展。

核心验证（project_memory 硬约束）：
  • compare_dual_baseline 方法存在
  • 静态基线通过 + 无动态基线 → bootstrap 晋升
  • 静态+动态双基线通过 → promote
  • 静态通过 + 动态不通过 → hold
  • 静态不通过 → reject
  • 返回结构包含 both_passed 和 recommendation
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.baseline_manager import BaselineManager, ComparisonReport


@pytest.fixture
def mgr(tmp_path) -> BaselineManager:
    """临时 BaselineManager。"""
    return BaselineManager(baseline_dir=tmp_path)


def _make_result(version="v2", sharpe=1.5, win_rate=0.55, pf=1.3, mdd=-0.08, ret=0.15):
    """构造回测结果 dict。"""
    return {
        "version": version,
        "summary": {
            "avg_sharpe_ratio": sharpe,
            "avg_win_rate": win_rate,
            "avg_profit_factor": pf,
            "avg_max_drawdown_pct": mdd,
            "avg_return_pct": ret,
            "coin_count": 3,
        },
        "per_coin_metrics": {
            "BTC": {"sharpe_ratio": sharpe, "win_rate": win_rate},
            "ETH": {"sharpe_ratio": sharpe - 0.1, "win_rate": win_rate - 0.02},
            "SOL": {"sharpe_ratio": sharpe + 0.1, "win_rate": win_rate + 0.02},
        },
    }


def _make_report(passed=True, recommendation="live"):
    """构造 ComparisonReport mock。"""
    return ComparisonReport(
        version="v2",
        baseline_version="v1",
        created_at="2026-08-20T00:00:00",
        passed=passed,
        recommendation=recommendation,
        reason="test",
        metric_comparisons=[],
        significant_improvements=["sharpe_ratio"] if passed else [],
        degradations=[] if passed else ["sharpe_ratio"],
        summary={},
    )


# ================================================================
# T_C5: baseline_manager 双基线扩展
# ================================================================

class TestDualBaseline:
    """验证 compare_dual_baseline 方法。"""

    def test_method_exists(self, mgr):
        """T_C5.1: compare_dual_baseline 方法存在。"""
        assert hasattr(mgr, "compare_dual_baseline")
        assert callable(mgr.compare_dual_baseline)

    def test_bootstrap_when_no_dynamic_baseline(self, mgr):
        """T_C5.2: 静态基线通过 + 无动态基线 → bootstrap 晋升。"""
        # 新版本比静态基线好
        new_result = _make_result(version="v2-alpha-blend", sharpe=2.0, win_rate=0.6, pf=1.5, ret=0.2)
        # 静态基线
        mgr.snapshot(_make_result(version="v15", sharpe=1.0, win_rate=0.5, pf=1.0, ret=0.1), version="v15_strategy")
        # 动态基线不存在

        result = mgr.compare_dual_baseline(
            new_result,
            static_baseline_version="v15_strategy",
            dynamic_baseline_version="current_best",
        )

        assert result["both_passed"] is True
        assert result["recommendation"] == "promote"
        assert result.get("bootstrap") is True

    def test_both_passed_promote(self, mgr):
        """T_C5.3: 静态+动态双基线通过 → promote。"""
        new_result = _make_result(version="v2-alpha-blend", sharpe=2.0)
        # 静态基线
        mgr.snapshot(_make_result(version="v15", sharpe=1.0), version="v15_strategy")
        # 动态基线（比新版本差）
        mgr.snapshot(_make_result(version="v1-ai", sharpe=1.2), version="current_best")

        result = mgr.compare_dual_baseline(
            new_result,
            static_baseline_version="v15_strategy",
            dynamic_baseline_version="current_best",
        )

        assert result["both_passed"] is True
        assert result["recommendation"] == "promote"

    def test_static_pass_dynamic_fail_hold(self, mgr):
        """T_C5.4: 静态通过 + 动态不通过 → hold。"""
        # 新版本比静态基线好，但比动态基线差
        new_result = _make_result(version="v2", sharpe=1.1)
        mgr.snapshot(_make_result(version="v15", sharpe=1.0), version="v15_strategy")
        mgr.snapshot(_make_result(version="v1-ai", sharpe=1.5), version="current_best")

        result = mgr.compare_dual_baseline(
            new_result,
            static_baseline_version="v15_strategy",
            dynamic_baseline_version="current_best",
        )

        assert result["both_passed"] is False
        assert result["recommendation"] == "hold"

    def test_static_fail_reject(self, mgr):
        """T_C5.5: 静态不通过 → reject。"""
        # 新版本比静态基线差
        new_result = _make_result(version="v2", sharpe=0.5, win_rate=0.3, pf=0.8)
        mgr.snapshot(_make_result(version="v15", sharpe=1.5, win_rate=0.6, pf=1.5), version="v15_strategy")

        result = mgr.compare_dual_baseline(
            new_result,
            static_baseline_version="v15_strategy",
            dynamic_baseline_version="current_best",
        )

        assert result["both_passed"] is False
        assert result["recommendation"] == "reject"

    def test_return_structure(self, mgr):
        """T_C5.6: 返回结构包含 both_passed 和 recommendation。"""
        new_result = _make_result(version="v2")
        mgr.snapshot(_make_result(version="v15"), version="v15_strategy")

        result = mgr.compare_dual_baseline(
            new_result,
            static_baseline_version="v15_strategy",
            dynamic_baseline_version="current_best",
        )

        assert "both_passed" in result
        assert "recommendation" in result
        assert "static_report" in result
        assert "dynamic_report" in result
        assert "bootstrap" in result

    def test_promote_sets_dynamic_baseline(self, mgr):
        """T_C5.6b: promote 后新版本自动设为动态基线。"""
        new_result = _make_result(version="v2-better", sharpe=2.0)
        mgr.snapshot(_make_result(version="v15", sharpe=1.0), version="v15_strategy")
        # 动态基线不存在 → bootstrap

        mgr.compare_dual_baseline(
            new_result,
            static_baseline_version="v15_strategy",
            dynamic_baseline_version="current_best",
        )

        # promote 后 current_best 应被更新为新版本
        dynamic = mgr.load_baseline("current_best")
        assert dynamic is not None
        assert dynamic.get("version") == "v2-better"
