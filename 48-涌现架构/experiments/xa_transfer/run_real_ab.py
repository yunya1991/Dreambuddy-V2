"""
X-A 真实跨域 A/B 验证框架 — 端到端运行编排器。

产出: experiments/xa_transfer/results/XA-REAL-<hash>.json
FAIL-OPEN: D1 shadow 数据不足时 status=deferred，附带 proxy 结果。
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

from real_ab import evaluate_real_ab  # noqa: E402

RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run(
    domain_a: str = "A",
    domain_b: str = "B",
    min_pairs: int = 10,
    run_class: str = "formal",
    session_root: str | None = None,
) -> dict:
    result = evaluate_real_ab(
        domain_a=domain_a,
        domain_b=domain_b,
        min_pairs=min_pairs,
        session_memory_root=session_root,
    )

    verdict_seed = result.get("verdict", "unknown")
    g123_seed = result.get("g123_real") or result.get("proxy_result", {}).get("g123", 0.0) or 0.0
    run_id = (
        "XA-REAL-"
        + hashlib.sha1(
            f"{g123_seed:.6f}-{verdict_seed}-{domain_a}-{domain_b}".encode()
        ).hexdigest()[:12]
    )

    prereg = {
        "experiment_id": run_id,
        "protocol_version": "SPEC-EMERGENCE-3D-v0.1 §4.6 (真实 A/B)",
        "domain": "X-REAL",
        "criterion": "H-X-REAL",
        "hypothesis": "真实 session 跨域匹配验证三维超加性增益",
        "design": "真实 A/B cross-domain session matching (task_type overlap)",
        "dimensions": {
            "D1": "trading coupling (真实 session metrics)",
            "D2": "engineering arch (真实 session metrics)",
            "D3": "intent routing (真实 session metrics)",
        },
        "success_criteria": "G_123_real 95% CI > 0 AND Ω_real > 0",
    }

    out = {
        "run_id": run_id,
        "run_class": run_class,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "prereg": prereg,
        **result,
    }

    path = RESULTS / f"{run_id}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"saved -> {path}")
    print(f"status: {result.get('status')}")
    print(f"verdict: {result.get('verdict')}")
    if result.get("g123_real") is not None:
        print(
            f"G_123_real={result['g123_real']:.4f} CI "
            f"[{result['g123_bootstrap_real']['ci_low']:.4f}, {result['g123_bootstrap_real']['ci_high']:.4f}]"
        )
        print(f"Ω_real={result['omega_real']:.4f}")
    if result.get("status") == "deferred":
        print(f"deferred_reason: {result.get('deferred_reason')}")
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--domain-a", default="A")
    p.add_argument("--domain-b", default="B")
    p.add_argument("--min-pairs", type=int, default=10)
    p.add_argument("--run-class", default="formal", choices=["formal", "exploratory"])
    p.add_argument("--session-root", default=None)
    args = p.parse_args()
    run(
        domain_a=args.domain_a,
        domain_b=args.domain_b,
        min_pairs=args.min_pairs,
        run_class=args.run_class,
        session_root=args.session_root,
    )
