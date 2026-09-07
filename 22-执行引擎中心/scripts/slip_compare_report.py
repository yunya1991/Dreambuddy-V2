"""Rolling slip comparison report.

Reads an audit directory and returns aggregate statistics on:
  - TEE actual slip distribution (p50/p90/p99)
  - fail_open + kill_switch trigger totals
  - per-algo histogram
  - per-coin fail_open counts

Usage (CLI):
    python slip_compare_report.py --audit-dir logs/tee_audit \\
        [--shadow-suffix _shadow]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


# Import helper (sibling script shadow_compare) to re-use iter helper.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from shadow_compare import _iter_audit_lines  # type: ignore  # noqa: E402


def _percentile(values: List[float], pct: float) -> float:
    """Linear-interpolated percentile (numpy-style)."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    # Fractional rank 0-indexed.
    k = (len(xs) - 1) * float(pct)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(xs[int(k)])
    frac = k - lo
    return float(xs[lo] * (1.0 - frac) + xs[hi] * frac)


def generate_report(
    *,
    audit_dir: str | Path,
    shadow_suffix: Optional[str] = "_shadow",
) -> Dict[str, Any]:
    """Generate aggregate slip report.

    Keys returned: slip_distribution_p50/p90/p99, fail_open_total,
    kill_switch_total, algo_histogram (dict), n_parents,
    per_coin_fail_open (dict), total_improvement_bps_avg."""
    tee_slips: List[float] = []
    fail_open_total = 0
    kill_switch_total = 0
    algo_histogram: Dict[str, int] = {}
    per_coin_fail_open: Dict[str, int] = {}
    n_parents = 0
    impr_sum = 0.0
    impr_valid = 0

    for rec in _iter_audit_lines(audit_dir, shadow_suffix):
        n_parents += 1
        exec_block = rec.get("exec") or {}
        try:
            tee_bps = float(exec_block.get("slippage_bps_vs_decision"))
            if math.isfinite(tee_bps):
                tee_slips.append(tee_bps)
        except (TypeError, ValueError):
            pass
        # Algo histogram
        algo_name = str(((rec.get("algo") or {}).get("name") or "UNKNOWN"))
        algo_histogram[algo_name] = algo_histogram.get(algo_name, 0) + 1
        # Fail-open
        fail = (rec.get("fail_open") or {}).get("triggered")
        if fail:
            fail_open_total += 1
            inst_id = str(((rec.get("parent") or {}).get("inst_id") or "UNKNOWN"))
            per_coin_fail_open[inst_id] = (
                per_coin_fail_open.get(inst_id, 0) + 1
            )
        # Kill switch
        ks = (rec.get("kill_switch") or {}).get("runtime_triggered")
        if ks:
            kill_switch_total += 1
        # Improvement average
        dm_bps = exec_block.get("baseline_direct_market_slippage_bps")
        tee_val = exec_block.get("slippage_bps_vs_decision")
        try:
            if dm_bps is not None and tee_val is not None:
                impr_sum += (float(dm_bps) - float(tee_val))
                impr_valid += 1
        except (TypeError, ValueError):
            pass

    return {
        "n_parents": n_parents,
        "slip_distribution_p50": round(_percentile(tee_slips, 0.50), 4),
        "slip_distribution_p90": round(_percentile(tee_slips, 0.90), 4),
        "slip_distribution_p99": round(_percentile(tee_slips, 0.99), 4),
        "fail_open_total": int(fail_open_total),
        "kill_switch_total": int(kill_switch_total),
        "algo_histogram": dict(algo_histogram),
        "per_coin_fail_open": dict(per_coin_fail_open),
        "avg_improvement_bps": (
            round(impr_sum / impr_valid, 4) if impr_valid else 0.0
        ),
    }


def run_cli(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="TEE slip comparison report.")
    p.add_argument("--audit-dir", required=True)
    p.add_argument("--shadow-suffix", default="_shadow")
    args = p.parse_args(argv)
    report = generate_report(
        audit_dir=args.audit_dir,
        shadow_suffix=(args.shadow_suffix or None),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
