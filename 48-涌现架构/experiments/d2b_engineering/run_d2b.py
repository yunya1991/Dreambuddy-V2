"""
D2-B 工程方案生成 正式运行编排器。

产出: experiments/d2b_engineering/results/D2B-<hash>.json
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from evaluate import evaluate_all  # noqa: E402
from generator import generate, load_gaps  # noqa: E402

RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run(run_class: str = "formal") -> dict:
    gaps = load_gaps(PKG_ROOT / "registry" / "capability_gaps.jsonl")
    d2b_types = {"architecture_gap", "doc_debt", "interface_mismatch", "module_missing"}
    d2b_gaps = [g for g in gaps if g.get("gap_type") in d2b_types]

    eval_result = evaluate_all(d2b_gaps)
    plans = {g["gap_id"]: generate(g).to_dict() for g in d2b_gaps}

    run_id = (
        "D2B-"
        + hashlib.sha1(
            f"{len(d2b_gaps)}-{eval_result['n_candidate']}-{eval_result['overall_verdict']}".encode()
        ).hexdigest()[:12]
    )

    prereg = {
        "experiment_id": f"D2B-{run_id}",
        "protocol_version": "SPEC-EMERGENCE-3D-v0.1 §4.2",
        "domain": "D2",
        "criterion": "H2B",
        "hypothesis": "系统能针对 E6 缺口生成人未写过、通过 45 门禁的工程方案",
        "n_gaps": len(d2b_gaps),
        "gate_thresholds": {"coverage": 0.80, "test_pass": 0.95, "pycg": 0.70},
        "novelty": "模块名不在现有架构图中",
        "success_criteria": "gap_addressed + novelty + feasibility + 45_gate 全通过",
    }

    out = {
        "run_id": run_id,
        "run_class": run_class,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "prereg": prereg,
        "n_gaps": len(d2b_gaps),
        "overall_verdict": eval_result["overall_verdict"],
        "n_candidate": eval_result["n_candidate"],
        "evaluations": eval_result["results"],
        "plans": plans,
    }

    path = RESULTS / f"{run_id}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"saved -> {path}")
    print(
        f"overall_verdict: {eval_result['overall_verdict']} ({eval_result['n_candidate']}/{len(d2b_gaps)} candidate)"
    )
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--run-class", default="formal", choices=["formal", "exploratory"])
    args = p.parse_args()
    run(run_class=args.run_class)
