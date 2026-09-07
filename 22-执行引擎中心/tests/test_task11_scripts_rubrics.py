"""Task 11 RED → GREEN tests — E2E scripts + rubrics.

4 TRs:
  TR-11.1 scripts/shadow_compare.py:
      compute_summary(audit_dir_with_shadow_files, bps_threshold) returns a
      dict with keys: total_parents, avg_improvement_bps,
      pct_beating_threshold_by_bps, per_algo_stats(dict), and a CLI
      `run_cli(argv)` that prints JSON summary to stdout.
      Test: build 20 synthetic shadow audit lines with known
      improvement distribution → avg_improvement == Σ(expected)/20 exact
      within 0.01 bps; pct_beating_threshold(2bps) matches.

  TR-11.2 scripts/slip_compare_report.py:
      generate_report(audit_dir) returns
      {slip_distribution_p50/p90/p99, fail_open_total, kill_switch_total,
       algo_histogram, n_parents, per_coin_fail_open}.
      Test: generate synthetic audit lines → all fields populated match
      hand-calculated aggregates.

  TR-11.3 (rubric) Slip-improvement Dimension: threshold ≥ 3/5.
      Dimension = "影子模式 vs 基线 DM 滑点改善分布 bin 覆盖率";
      scale 0-5: score = number of bins with ≥ 1 parent. bins =
      (-∞,0),[0,1),[1,2),[2,5),[5,∞). 0 bins =0, all 5=5. For test we
      synthesize 20 parents that cover at least 3 of 5 bins → score ≥3.
      Evidence: script returns rubric dict with score.

  TR-11.4 (rubric) Docs consistency ≥ 4/5.
      tasks.md spec lists 11 tasks; for each declared completed we look
      at tests/ directory for matching test_task*.py file. score = number
      of completed-tasks with (UTs file exists + completion evidence) /
      total 11 tasks * 5. Test: spec lists 11 Tasks (1-11) with
      status=completed or pending; completed ones (now 10/11 after this
      GREEN run, but during RED test we lower threshold) produce score
      ≥ 4/5 → (0.8*5=4). RED test simply checks
      scripts.docs_consistency.score_report_spec_vs_tests(tasks_md_path,
      tests_dir) returns a score dict and overall 0-5 score.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO / "22-执行引擎中心" / "scripts"
sys.path.insert(0, str(REPO / "22-执行引擎中心"))


def _load_module_from(path: Path):
    """Load a module from absolute filesystem path (avoids ``scripts``
    name collision with other packages in the repo)."""
    path = Path(path).resolve()
    name = f"_tee_script_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to build spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_shadow_compare():
    return _load_module_from(SCRIPTS_DIR / "shadow_compare.py")


def _load_slip_compare():
    return _load_module_from(SCRIPTS_DIR / "slip_compare_report.py")


def _load_docs_consistency():
    return _load_module_from(SCRIPTS_DIR / "docs_consistency.py")


# =====================================================================
# Fixture: write 20 synthetic shadow audit files
# =====================================================================
@pytest.fixture
def audit_dir_with_shadow(tmp_path: Path) -> Path:
    """Produce 1x 2026-05-20_shadow.jsonl with 20 parents.

    Improvement distribution (DM_baseline_bps - TEE_slippage_bps):
      [improvement, count]:
        -1    (TEE worse than DM)       × 2  →  bin (-∞,0)
         0.5  (small beat)                × 3  →  bin [0,1)
         1.4  (modest)                    × 4  →  bin [1,2)
         3.2  (good)                      × 7  →  bin [2,5)
         7.0  (excellent)                 × 4  →  bin [5,∞)

    Mean improvement = (-2 + 1.5 + 5.6 + 22.4 + 28.0)/20 = 55.5/20 = 2.775 bps.
    % beating threshold ≥ 2bps = bins [2,5) ∪ [5,∞) count = 7+4=11 → 55.0%.
    % beating threshold ≥ 5bps = just bin [5,∞) = 4/20 = 20.0%.
    Per-algo: 7 SmartTWAP + 5 SmartPassive + 8 DirectMarket.
    """
    d = tmp_path / "audit"
    d.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    specs: List[Dict[str, Any]] = []
    # Distribute improvements.
    schedule: list[tuple[float, int, str]] = [
        (-1.0, 2, "SmartTWAP"),
        (0.5,  3, "SmartPassive"),
        (1.4,  4, "SmartTWAP"),
        (3.2,  7, "SmartPassive"),
        (7.0,  4, "DirectMarket"),
    ]
    idx = 0
    for impr, count, algo in schedule:
        for _ in range(count):
            idx += 1
            dm_bps = 10.0  # all fixed baseline for simplicity
            tee_bps = dm_bps - impr
            lines.append(json.dumps({
                "ts_epoch_ms": 1_716_200_000_000 + idx * 1000,
                "parent": {
                    "parent_id": f"SH{idx:03d}",
                    "inst_id": ("BTC-USDT-SWAP" if idx % 2
                                 else "ETH-USDT-SWAP"),
                    "side": ("buy" if idx % 2 else "sell"),
                    "sz": 0.5 + idx % 3,
                },
                "exec": {
                    "slippage_bps_vs_decision": tee_bps,
                    "baseline_direct_market_slippage_bps": dm_bps,
                    "filled_sz_total": 0.5 + idx % 3,
                },
                "algo": {"name": algo},
                "fail_open": {"triggered": idx % 7 == 0},  # fail_open 3×
                "kill_switch": {
                    "runtime_triggered": idx % 10 == 0,  # ks 2×
                },
            }, ensure_ascii=False))
    (d / "2026-05-20_shadow.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return d


# =====================================================================
# TR-11.1 shadow_compare.py summary script
# =====================================================================
class TestTR111ShadowCompare:
    def test_compute_summary_returns_all_required_keys(
            self, audit_dir_with_shadow: Path):
        shadow_compare = _load_shadow_compare()
        summary = shadow_compare.compute_summary(
            audit_dir=str(audit_dir_with_shadow),
            shadow_suffix="_shadow",
            bps_thresholds=[2.0, 5.0],
        )
        required = ("total_parents", "avg_improvement_bps",
                     "pct_beating_threshold_by_bps", "per_algo_stats")
        for k in required:
            assert k in summary, f"Missing summary key {k}"
        assert summary["total_parents"] == 20
        # Mean improvement 55.5/20 = 2.775
        assert abs(float(summary["avg_improvement_bps"]) - 2.775) < 0.01, (
            f"avg improvement wrong: {summary['avg_improvement_bps']}"
        )
        # BPS 2.0 threshold → 11/20 = 0.55
        pct_2 = float(summary["pct_beating_threshold_by_bps"].get("2.0"))
        assert abs(pct_2 - 0.55) < 0.001, (
            f"beating 2bps pct wrong: {pct_2}"
        )
        # BPS 5.0 → 4/20 = 0.20
        pct_5 = float(summary["pct_beating_threshold_by_bps"].get("5.0"))
        assert abs(pct_5 - 0.20) < 0.001
        # Per-algo: SmartTWAP(6) + SmartPassive(10) + DirectMarket(4) wait:
        # 2+4=6 SmartTWAP, 3+7=10 SmartPassive, 4 DirectMarket
        stats = summary["per_algo_stats"]
        assert stats.get("SmartTWAP", 0) == 6
        assert stats.get("SmartPassive", 0) == 10
        assert stats.get("DirectMarket", 0) == 4


# =====================================================================
# TR-11.2 slip_compare_report.py
# =====================================================================
class TestTR112SlipCompareReport:
    def test_generate_report_matches_hand_aggregates(
            self, audit_dir_with_shadow: Path):
        slip_compare_report = _load_slip_compare()
        report = slip_compare_report.generate_report(
            audit_dir=str(audit_dir_with_shadow),
            shadow_suffix="_shadow",
        )
        required = ("slip_distribution_p50", "slip_distribution_p90",
                     "slip_distribution_p99", "fail_open_total",
                     "kill_switch_total", "algo_histogram",
                     "n_parents", "per_coin_fail_open")
        for k in required:
            assert k in report, f"Missing report key {k}"
        assert report["n_parents"] == 20
        # Fail-open 3×: idx=7,14 (idx%7==0) + idx? Let's recount: 1-indexed:
        # 7,14=2 → wait idx%7==0 → idx=7,14 → 2? Let's count. 1-indexed:
        # idx runs 1..20. idx%7==0 → {7,14} → 2. But wait idx=21 would also.
        # So 2 total fail_open in 1..20.
        assert report["fail_open_total"] == 2, (
            f"Expected 2 fail_open, got {report['fail_open_total']}"
        )
        # kill_switch: idx 10, 20 → 2×.
        assert report["kill_switch_total"] == 2
        # algo histogram: same as before.
        hist = report["algo_histogram"]
        assert hist.get("SmartTWAP") == 6 and hist.get("SmartPassive") == 10
        assert hist.get("DirectMarket") == 4
        # p50 / P90 / P99 of TEE slip values:
        # 20 TEE slip = dm_bps(10) - impr:
        # impr=-1 → 11 (twice); impr=0.5→9.5 (3×); impr=1.4→8.6 (4×);
        # impr=3.2→6.8 (7×); impr=7.0→3.0 (4×).
        # Sorted ascending: [3,3,3,3, 6.8,6.8,6.8,6.8,6.8,6.8,6.8,
        #                   8.6,8.6,8.6,8.6, 9.5,9.5,9.5, 11,11].
        # Linear-interpolated percentile (numpy convention (n-1)*p):
        #   p50: index 9.5 → (6.8 + 6.8)/2 = 6.8
        #   p90: index 17.1 → 9.5 + 0.1*(11 − 9.5) = 9.65
        #   p99: index 18.81 → 11 + 0.81*(11 − 11) = 11.0
        assert abs(float(report["slip_distribution_p50"]) - 6.8) < 0.01
        assert abs(float(report["slip_distribution_p90"]) - 9.65) < 0.01
        assert abs(float(report["slip_distribution_p99"]) - 11.0) < 0.01


# =====================================================================
# TR-11.3 Rubric — slip-improvement bins (≥3/5 → pass)
# =====================================================================
class TestTR113SlipImprovementRubric:
    def test_rubric_5_bin_coverage_scores_at_least_3_5(
            self, audit_dir_with_shadow: Path):
        shadow_compare = _load_shadow_compare()
        rubric = shadow_compare.improvement_bin_rubric(
            audit_dir=str(audit_dir_with_shadow),
            shadow_suffix="_shadow",
        )
        assert rubric.get("dimension") == "slip_improvement_bin_coverage"
        # bins covered by fixture: (-1→bin 0), (0.5→bin 1), (1.4→bin 2),
        # (3.2→bin 3), (7.0→bin 4) = all 5 bins covered → score == 5.
        score = int(rubric.get("score"))
        bins_covered = int(rubric.get("bins_covered"))
        assert score >= 3, (
            f"Rubric score {score} < 3/5 threshold (bins covered="
            f"{bins_covered}/5)."
        )
        assert bins_covered == 5 and score == 5


# =====================================================================
# TR-11.4 Rubric — docs consistency ≥4/5 → score ≥ 4
# =====================================================================
class TestTR114DocsConsistencyRubric:
    def test_score_spec_tasks_matches_tests_dir(self):
        docs_consistency = _load_docs_consistency()
        spec_path = (REPO / ".trae" / "specs" /
                      "execution-engine-smart-order-splitting" / "tasks.md")
        tests_dir = REPO / "22-执行引擎中心" / "tests"
        result = docs_consistency.score_report_spec_vs_tests(
            tasks_md_path=str(spec_path), tests_dir=str(tests_dir),
        )
        assert "score_0_to_5" in result
        assert "summary_by_task_id" in result
        score = float(result.get("score_0_to_5", 0))
        # During RED: will fail because docs_consistency module missing.
        # During GREEN: 10 of 11 tasks completed + matching test files exist
        # → (10/11)*5 ≈ 4.55 ≥ 4.
        assert score >= 4.0, (
            f"Docs consistency rubric score {score:.2f} < 4.0 threshold. "
            f"Summary: {result.get('summary_by_task_id')}"
        )
