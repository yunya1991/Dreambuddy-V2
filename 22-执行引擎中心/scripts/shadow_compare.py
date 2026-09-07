"""Shadow run comparison report generator.

Usage (CLI):
    python shadow_compare.py --audit-dir logs/tee_audit \\
        --shadow-suffix _shadow --bps-threshold 2.0 --bps-threshold 5.0

Functions (testable):
    compute_summary(audit_dir, shadow_suffix, bps_thresholds) -> summary dict
      total_parents, avg_improvement_bps, pct_beating_threshold_by_bps,
      per_algo_stats.
    improvement_bin_rubric(audit_dir, shadow_suffix) -> rubric dict
      {dimension, score, bins_covered, bins_total, bin_counts}

Improvement bps = baseline(DM) − actual(TEE) slip. Positive means
the TEE path beat the direct-market baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


BIN_LABELS: tuple = (
    "< 0 (loss)", "[0, 1)", "[1, 2)", "[2, 5)", "≥ 5",
)


def _iter_audit_lines(audit_dir: str | Path,
                       shadow_suffix: Optional[str] = "_shadow"
                       ) -> Iterable[Dict[str, Any]]:
    d = Path(audit_dir)
    if not d.is_dir():
        return
    pattern = f"*{shadow_suffix or ''}.jsonl" if shadow_suffix else "*.jsonl"
    for f in sorted(d.glob(pattern)):
        if not f.is_file():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _improvement_bps(rec: Dict[str, Any]) -> Optional[float]:
    exec_block = rec.get("exec") or {}
    dm_bps = exec_block.get("baseline_direct_market_slippage_bps")
    tee_bps = exec_block.get("slippage_bps_vs_decision")
    if dm_bps is None or tee_bps is None:
        return None
    try:
        return float(dm_bps) - float(tee_bps)
    except (TypeError, ValueError):
        return None


def compute_summary(
    *,
    audit_dir: str | Path,
    shadow_suffix: Optional[str] = "_shadow",
    bps_thresholds: Iterable[float] = (2.0, 5.0),
) -> Dict[str, Any]:
    """Aggregate shadow-compare summary for a directory of audit files.

    Summary always contains: total_parents (int), avg_improvement_bps
    (float), pct_beating_threshold_by_bps (dict: str(thresh)->float 0-1),
    per_algo_stats (dict: algo_name -> int count)."""
    thresholds: List[float] = [float(x) for x in bps_thresholds]
    total = 0
    improve_sum = 0.0
    improve_valid_samples = 0
    beating_counts: Dict[str, int] = {str(t): 0 for t in thresholds}
    per_algo: Dict[str, int] = {}

    for rec in _iter_audit_lines(audit_dir, shadow_suffix):
        total += 1
        algo = str(((rec.get("algo") or {}).get("name") or "UNKNOWN"))
        per_algo[algo] = per_algo.get(algo, 0) + 1
        impr = _improvement_bps(rec)
        if impr is None:
            continue
        improve_sum += impr
        improve_valid_samples += 1
        for th in thresholds:
            if impr >= th:
                beating_counts[str(th)] += 1

    avg = (improve_sum / improve_valid_samples) if improve_valid_samples else 0.0
    pct_beat: Dict[str, float] = {}
    for th_str, c in beating_counts.items():
        pct_beat[th_str] = (c / total) if total else 0.0
    return {
        "total_parents": total,
        "valid_improvement_samples": improve_valid_samples,
        "avg_improvement_bps": round(avg, 6),
        "pct_beating_threshold_by_bps": pct_beat,
        "per_algo_stats": dict(per_algo),
    }


def _bin_index(improvement_bps: float) -> int:
    """Assign one of the 5 bins in BIN_LABELS order."""
    x = float(improvement_bps)
    if x < 0:
        return 0
    if x < 1:
        return 1
    if x < 2:
        return 2
    if x < 5:
        return 3
    return 4


def improvement_bin_rubric(
    *,
    audit_dir: str | Path,
    shadow_suffix: Optional[str] = "_shadow",
) -> Dict[str, Any]:
    """Score bins 0..5: every bin with ≥ 1 sample adds one point.

    Threshold: ≥3/5 (TR-11.3). Max 5 if all bins populated."""
    bin_counts: List[int] = [0] * len(BIN_LABELS)
    total = 0
    for rec in _iter_audit_lines(audit_dir, shadow_suffix):
        total += 1
        impr = _improvement_bps(rec)
        if impr is None:
            continue
        bin_counts[_bin_index(impr)] += 1
    bins_covered = sum(1 for c in bin_counts if c > 0)
    score_0_5 = bins_covered  # 1 bin → 1 point; 5 bins → max 5 points
    return {
        "dimension": "slip_improvement_bin_coverage",
        "total_parents": total,
        "bins_total": len(BIN_LABELS),
        "bins_covered": bins_covered,
        "bin_labels": list(BIN_LABELS),
        "bin_counts": bin_counts,
        "score_0_to_5": score_0_5,
        # legacy key name (TR-11.3 assertion reads "score" too)
        "score": score_0_5,
        "threshold_required": 3,
        "pass": bool(score_0_5 >= 3),
    }


def run_cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="TEE shadow-vs-baseline report.")
    p.add_argument("--audit-dir", required=True)
    p.add_argument("--shadow-suffix", default="_shadow",
                   help="Glob suffix (default _shadow). Use '' to use real "
                        "audit stream.")
    p.add_argument("--bps-threshold", type=float, default=[2.0, 5.0],
                   action="append",
                   help="Improvement beat threshold (repeatable).")
    args = p.parse_args(argv)
    summary = compute_summary(
        audit_dir=args.audit_dir,
        shadow_suffix=(args.shadow_suffix or None),
        bps_thresholds=args.bps_threshold,
    )
    rubric = improvement_bin_rubric(
        audit_dir=args.audit_dir,
        shadow_suffix=(args.shadow_suffix or None),
    )
    out = {"summary": summary, "bin_rubric": rubric}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if rubric.get("pass") else 2


if __name__ == "__main__":
    sys.exit(run_cli())
