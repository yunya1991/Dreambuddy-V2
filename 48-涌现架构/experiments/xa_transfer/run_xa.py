"""
X-A 跨域迁移 2×2×2 正式运行编排器。

产出: experiments/xa_transfer/results/XA-<hash>.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from evaluate import evaluate  # noqa: E402

RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run(run_class: str = "formal") -> dict:
    result = evaluate()
    run_id = (
        "XA-" + hashlib.sha1(f"{result['g123']:.6f}-{result['verdict']}".encode()).hexdigest()[:12]
    )

    prereg = {
        "experiment_id": f"XA-{run_id}",
        "protocol_version": "SPEC-EMERGENCE-3D-v0.1 §4.5",
        "domain": "X",
        "criterion": "H-X",
        "hypothesis": "D1/D2/D3 三维联合产生超加性增益（三阶交互显著）",
        "design": "2x2x2 factorial (8 arms)",
        "dimensions": {
            "D1": "trading (proxy=E3 coupling improvement)",
            "D2": "engineering (proxy=D2-A F1)",
            "D3": "intent (proxy=D3-B step reduction)",
        },
        "success_criteria": "G_123 95% CI > 0 AND Ω > 0 AND at least one G_ij > 0",
    }

    out = {
        "run_id": run_id,
        "run_class": run_class,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "prereg": prereg,
        "dimension_gains": result["dimension_gains"],
        "arms": result["arms"],
        "main_effects": result["main_effects"],
        "two_way_interactions": result["two_way_interactions"],
        "g123": result["g123"],
        "g123_bootstrap": result["g123_bootstrap"],
        "omega_o_information": result["omega_o_information"],
        "verdict": result["verdict"],
        "reason": result["reason"],
    }

    path = RESULTS / f"{run_id}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"saved -> {path}")
    print(f"verdict: {result['verdict']}")
    print(
        f"G_123={result['g123']:.4f} CI [{result['g123_bootstrap']['ci_low']:.4f}, {result['g123_bootstrap']['ci_high']:.4f}]"
    )
    print(f"Ω={result['omega_o_information']:.4f}")
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--run-class", default="formal", choices=["formal", "exploratory"])
    args = p.parse_args()
    run(run_class=args.run_class)
