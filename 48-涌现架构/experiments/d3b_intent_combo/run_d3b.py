"""
D3-B 意图知识组合 正式运行编排器。

产出: experiments/d3b_intent_combo/results/D3B-<hash>.json
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

from combo import build_combos, index_by_session, load_events, load_split  # noqa: E402
from evaluate import evaluate  # noqa: E402

RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run(run_class: str = "formal") -> dict:
    art = PKG_ROOT / "baselines" / "artifacts" / "d3_intent_events"
    events = load_events(art / "intent_events.jsonl")
    train_ids, test_ids = load_split(art / "split_manifest.json")
    idx = index_by_session(events)
    train = [idx[s] for s in train_ids if s in idx]
    test = [idx[s] for s in test_ids if s in idx]

    combos = build_combos(train)
    result = evaluate(test, combos)

    run_id = (
        "D3B-"
        + hashlib.sha1(
            f"{len(train)}-{len(test)}-{len(combos)}-{result['verdict']}".encode()
        ).hexdigest()[:12]
    )

    prereg = {
        "experiment_id": f"D3B-{run_id}",
        "protocol_version": "SPEC-EMERGENCE-3D-v0.1 §4.4",
        "domain": "D3",
        "criterion": "H3B",
        "hypothesis": "意图知识组合显著减少 recall 步数且不增加错误",
        "n_train": len(train),
        "n_test": len(test),
        "min_combo_size": 3,
        "hit_rate_threshold": 0.3,
        "stat_test": "paired_bootstrap_10k",
        "success_criteria": "delta_recall_steps CI 下界 > 0 且 hit_rate >= 0.3",
        "falsification_criteria": "delta CI 上界 <= 0 或 hit_rate < 0.1",
    }

    out = {
        "run_id": run_id,
        "run_class": run_class,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "prereg": prereg,
        "n_train": len(train),
        "n_test": len(test),
        "n_combos": len(combos),
        "result": {k: v for k, v in result.items() if k != "per_session"},
        "combos": {p: c.to_dict() for p, c in combos.items()},
    }

    path = RESULTS / f"{run_id}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"saved -> {path}")
    print(f"verdict: {result['verdict']}")
    print(
        f"delta_recall_steps: {result['mean_delta_recall_steps']:.3f} (CI {result['delta_ci_low']:.3f}..{result['delta_ci_high']:.3f})"
    )
    print(f"hit_rate: {result['mean_hit_rate']:.3f}")
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--run-class", default="formal", choices=["formal", "exploratory"])
    args = p.parse_args()
    run(run_class=args.run_class)
