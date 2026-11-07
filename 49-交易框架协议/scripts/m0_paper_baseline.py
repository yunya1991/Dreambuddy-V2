#!/usr/bin/env python3
"""M0-03 paper baseline harness.

Runs 23's paper decision path on a deterministic synthetic market dataset and
records production + shadow diagnostics. Falls back to a deterministic
shadow-only baseline when the full pipeline dependencies are unavailable.

Usage:
  python 49-交易框架协议/scripts/m0_paper_baseline.py
  python 49-交易框架协议/scripts/m0_paper_baseline.py --mode shadow
  python 49-交易框架协议/scripts/m0_paper_baseline.py --compare <baseline.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
EVOLUTION_ROOT = REPO_ROOT / "23-四层闭环自进化交易架构"
if str(EVOLUTION_ROOT) not in sys.path:
    sys.path.insert(0, str(EVOLUTION_ROOT))

BASELINE_VERSION = "m0-paper-baseline-v1"
DEFAULT_OUT = (
    REPO_ROOT / "49-交易框架协议" / "runtime" / "baselines" / "m0_paper_baseline_latest.json"
)


def _market_data(seed: int = 42, n: int = 200) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    close = 35000.0 + np.cumsum(rng.normal(0, 50, n))
    return {
        "close": close,
        "volume": np.full(n, 3000.0),
        "okx_positions": {"long": 0.55, "short": 0.45},
        "liquidation_buy": np.zeros(n),
        "liquidation_sell": np.zeros(n),
        "ma_200": float(np.mean(close)),
        "fib_retrace_0786": 37000.0,
        "fib_retrace_0618": 35000.0,
        "fib_retrace_0500": 33500.0,
        "bid_ask_spread_bps": 2.0,
        "news_sentiment_score": 0.60,
    }


def _synthetic_paths() -> list[dict[str, Any]]:
    paths = [
        {
            "path_id": "bcrm_technical",
            "source": "bcrm",
            "direction": "long",
            "confidence": 0.78,
            "expected_return": 0.16,
            "resistance": 0.22,
            "continuation_score": 0.60,
        },
        {
            "path_id": "bdsm_fundamental_long",
            "source": "bdsm",
            "direction": "long",
            "confidence": 0.62,
            "expected_return": 0.12,
            "resistance": 0.35,
            "continuation_score": 0.55,
        },
        {
            "path_id": "strategic_macro_short",
            "source": "strategic",
            "direction": "short",
            "confidence": 0.55,
            "expected_return": 0.10,
            "resistance": 0.40,
            "continuation_score": 0.50,
        },
        {
            "path_id": "l2_gene_0",
            "source": "l2_gene",
            "direction": "long",
            "confidence": 0.72,
            "expected_return": 0.18,
            "resistance": 0.30,
            "continuation_score": 0.65,
        },
        {
            "path_id": "synthesized_new_gene",
            "source": "synthesized",
            "direction": "long",
            "confidence": 0.68,
            "expected_return": 0.14,
            "resistance": 0.28,
            "continuation_score": 0.58,
        },
    ]
    for path in paths:
        path["score"] = round(
            float(path["expected_return"])
            * float(path["confidence"])
            * (1.0 - float(path["resistance"])),
            6,
        )
    return paths


def _primary() -> dict[str, Any]:
    return {
        "dimension": "C4",
        "direction": "long",
        "strength": 0.50,
        "confidence": 0.60,
        "timeframe": "medium",
    }


def _attention_weights() -> list:
    # (B=1, H=8, 1, N=1); C4/C8 (macro heads) dominate.
    values = [0.01, 0.01, 0.01, 0.50, 0.01, 0.01, 0.40, 0.01]
    return [[[[float(value)] for _ in range(1)] for value in values]]


def _event_data() -> dict[str, Any]:
    return {
        "event_context": {
            "in_fomc_cycle": True,
            "cycle_phase": "expectation_jump",
            "hike_prob": 0.85,
            "probability_trend": "rising",
        }
    }


def _run_pipeline(symbol: str, market_data: dict[str, Any]) -> dict[str, Any]:
    from dreambuddy_evolution.core.resistance_vector import ResistanceVector
    from dreambuddy_evolution.evolution_pipeline import EvolutionPipeline

    gene_root = EVOLUTION_ROOT / "dreambuddy_evolution" / "gene_data"
    pipe = EvolutionPipeline(gene_root=gene_root)
    return pipe.run_symbol(symbol, market_data, rv=ResistanceVector())


def _shadow_baseline(
    symbol: str,
    market_data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from dreambuddy_evolution.core.attention_shadow import compute_a_dim_shadow
    from dreambuddy_evolution.core.cd_mapping import attach_shadow
    from dreambuddy_evolution.core.contradiction_identifier import (
        ContradictionWeightLearner,
    )
    from dreambuddy_evolution.core.dimension_force_evaluator import (
        DimensionForceEvaluator,
    )
    from dreambuddy_evolution.core.dominance_resolver import resolve
    from dreambuddy_evolution.core.event_contradiction_shadow import (
        compute_event_contradiction_shadow,
    )
    from dreambuddy_evolution.core.self_vote_guard import compute_self_vote_shadow

    paths = _synthetic_paths()
    primary = _primary()
    production_path = max(paths, key=lambda path: path["score"])

    production = {
        "action": None,
        "tier": None,
        "position_mult": None,
        "regime": None,
        "d_star": None,
        "ri": None,
        "l4_v": None,
        "primary_contradiction": primary,
        "selected_path": production_path["path_id"],
        "selected_source": production_path["source"],
        "selected_score": production_path["score"],
        "production_fields_available": False,
    }

    cd_shadow = attach_shadow(dict(primary), enabled=True)["dimension_shadow"]
    dominance = resolve(
        paths,
        primary_contradiction=primary,
        production_path_id=production_path["path_id"],
    )
    attention = compute_a_dim_shadow(primary, attn_weights=_attention_weights())
    event = compute_event_contradiction_shadow(_event_data(), enabled=True)
    self_vote = compute_self_vote_shadow(paths, primary_contradiction=primary, enabled=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        learner = ContradictionWeightLearner(
            storage_path=str(Path(tmp_dir) / "contradiction_samples.json")
        )
        learner.record_prediction(
            {"power": 0.4, "time": 0.2, "consistency": 0.3, "market_weight": 0.1},
            direction="long",
            confidence=0.7,
        )
        learner.label_previous(0.01)
        w6_status = learner.status()
        # 临时路径/时间不参与 before-after 对比
        w6_status["path"] = "<temp>"
        w6_status["bytes"] = 0
        w6_status["last_learn_ts"] = 0.0

    d2 = DimensionForceEvaluator().d2_coverage(symbol)

    shadow = {
        "cd_mapping": cd_shadow,
        "dominance": dominance,
        "attention": attention,
        "event_contradiction": event,
        "w6_status": w6_status,
        "self_vote": self_vote,
        "d2_coverage": d2,
    }
    return production, shadow


def _pipeline_sections(result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    production_keys = (
        "action",
        "tier",
        "position_mult",
        "regime",
        "d_star",
        "ri",
        "l4_v",
        "primary_contradiction",
        "cross_validation",
    )
    production = {key: result.get(key) for key in production_keys}
    primary = production.get("primary_contradiction")
    if isinstance(primary, dict) and "dimension_shadow" in primary:
        production["primary_contradiction"] = {
            key: value for key, value in primary.items() if key != "dimension_shadow"
        }
    production["production_fields_available"] = True
    shadow = {
        "cd_mapping": (result.get("primary_contradiction") or {}).get("dimension_shadow"),
        "dominance": result.get("dominance_shadow"),
        "attention": (result.get("cross_validation") or {}).get("attention_shadow"),
        "event_contradiction": result.get("event_contradiction_shadow"),
        "w6_status": result.get("w6_status"),
        "self_vote": result.get("self_vote_shadow"),
    }
    return production, shadow


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if hasattr(value, "tolist"):
        return _sanitize(value.tolist())
    return str(value)


def _build_baseline(
    *,
    mode: str,
    symbol: str,
    seed: int,
) -> dict[str, Any]:
    from dreambuddy_evolution.agi_config import get_all_switches

    market_data = _market_data(seed=seed)
    pipeline_error = None
    actual_mode = mode
    if mode in ("auto", "pipeline"):
        try:
            result = _run_pipeline(symbol, market_data)
            production, shadow = _pipeline_sections(result)
            actual_mode = "pipeline"
        except Exception as exc:  # noqa: BLE001
            if mode == "pipeline":
                raise
            pipeline_error = f"{type(exc).__name__}: {exc}"
            production, shadow = _shadow_baseline(symbol, market_data)
            actual_mode = "shadow-fallback"
    else:
        production, shadow = _shadow_baseline(symbol, market_data)
        actual_mode = "shadow"

    close = np.asarray(market_data["close"], dtype=float)
    baseline = {
        "schema_version": BASELINE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": actual_mode,
        "requested_mode": mode,
        "pipeline_error": pipeline_error,
        "symbol": symbol,
        "seed": seed,
        "market_data_sha256": hashlib.sha256(close.tobytes()).hexdigest(),
        "switches": get_all_switches(),
        "production": _sanitize(production),
        "shadow": _sanitize(shadow),
    }
    return baseline


def _walk_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        diffs = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else key
            diffs.extend(_walk_diff(before.get(key), after.get(key), child))
        return diffs
    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return []
        return [{"path": path, "before": before, "after": after}]
    if before != after:
        return [{"path": path, "before": before, "after": after}]
    return []


def _compare(baseline_path: Path, current: dict[str, Any], include_shadow: bool) -> int:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    sections = ["production"] + (["shadow"] if include_shadow else [])
    all_diffs: list[dict[str, Any]] = []
    for section in sections:
        diffs = _walk_diff(baseline.get(section), current.get(section), section)
        all_diffs.extend(diffs)
    if not all_diffs:
        print(f"OK: {', '.join(sections)} identical to {baseline_path}")
        return 0
    print(f"DIFF: {len(all_diffs)} change(s) vs {baseline_path}")
    for diff in all_diffs[:50]:
        print(f"  {diff['path']}: {diff.get('before')!r} -> {diff.get('after')!r}")
    if len(all_diffs) > 50:
        print(f"  ... {len(all_diffs) - 50} more")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="M0-03 paper baseline harness")
    parser.add_argument("--mode", choices=("auto", "pipeline", "shadow"), default="auto")
    parser.add_argument("--symbol", default="BTC")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--compare", type=Path, default=None)
    parser.add_argument("--include-shadow", action="store_true")
    args = parser.parse_args()

    baseline = _build_baseline(mode=args.mode, symbol=args.symbol, seed=args.seed)
    if args.compare is not None:
        return _compare(args.compare, baseline, args.include_shadow)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Baseline written: {args.out}")
    print(
        f"mode={baseline['mode']} symbol={baseline['symbol']} "
        f"production_fields={baseline['production'].get('production_fields_available')}"
    )
    if baseline.get("pipeline_error"):
        print(f"pipeline fallback reason: {baseline['pipeline_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
