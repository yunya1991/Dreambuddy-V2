#!/usr/bin/env python3
# priors_differential_probe.py — G4 升级影响面实测（differential harness）。
#
# 目的：用真实 40 因子方向先验（factor_contradiction_priors.json）+ 真实 42 总线快照，
# 实测"如果把 priors_40 从审计挂载升级为参与 50 决策计算"，在不同 overlay 系数下：
#   - path 命中率 / direction 翻转率 / divergence_rate（复用 R0-04 diff_path_sets）
#   - w4.total / force / impact 偏移、整体决策方向与 raw_position 变化
# 产出数据支撑 SPEC 的 overlay 系数预注册。
#
# 纪律：
#   - 只读测量，不写任何生产状态、不改决策、不触执行。
#   - 基线可复现：now 固定为 bus_state.generated_at（避免 freshness 随真实时间漂移）。
#   - 与生产 make_decision 同路径：load_evidences → synthesize_paths → w4.adjudicate。
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_50_ROOT = _REPO_ROOT / "50-NN主矛盾评估器"
if str(_50_ROOT) not in sys.path:
    sys.path.insert(0, str(_50_ROOT))

from adapters.bus_reader import load_evidences  # noqa: E402
from core.factor_priors_overlay import (  # noqa: E402
    MAX_COEF,
    _bucket_factors_by_dimension,
    apply_factor_priors_overlay,
)
from core.path_synthesis import Path as SynPath  # noqa: E402
from core.path_synthesis import synthesize_paths  # noqa: E402
from core.w4 import adjudicate  # noqa: E402

from tools.differential_harness import diff_path_sets  # noqa: E402

DEFAULT_BUS = _REPO_ROOT / "42-神经网络交易协调层" / "runtime" / "bus_state.json"
DEFAULT_PRIORS = _REPO_ROOT / "40-周期神经网络系统" / "factor_contradiction_priors.json"
DEFAULT_COEFS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50]


def _parse_ts(value: object) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _load_factors(priors_path: Path) -> dict:
    data = json.loads(priors_path.read_text(encoding="utf-8"))
    fdp = data.get("factor_direction_priors", {}) if isinstance(data, dict) else {}
    return fdp.get("factors", {}) or {}


def _to_diff_dict(p: SynPath) -> dict:
    return {
        "path_id": p.path_id,
        "direction": p.direction,
        "confidence": round(p.confidence, 6),
        "dimension": p.dimension,
        "horizon": p.horizon,
        "intent": p.intent,
        "continuation_score": round(p.continuation_score, 6),
    }


def _raw_position(direction: str, confidence: float) -> float:
    return 50.0 + 50.0 * (
        confidence if direction == "long" else -confidence if direction == "short" else 0.0
    )


def _summarize_w4(w4: dict) -> dict:
    return {
        "direction": w4["direction"],
        "total": w4["total"],
        "force": w4["force"],
        "urgency": w4["urgency"],
        "consistency": w4["consistency"],
        "impact": w4["impact"],
        "resonance": w4["resonance"],
        "dominant": w4["dominant"],
        "raw_position": round(_raw_position(w4["direction"], w4["total"]), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="priors_40 differential 影响面实测")
    ap.add_argument("--bus-state", default=str(DEFAULT_BUS))
    ap.add_argument("--priors", default=str(DEFAULT_PRIORS))
    ap.add_argument("--coefs", default=",".join(str(c) for c in DEFAULT_COEFS))
    ap.add_argument("--out", default="", help="可选：报告 JSON 落盘路径")
    args = ap.parse_args()

    bus_path = Path(args.bus_state)
    bus = json.loads(bus_path.read_text(encoding="utf-8"))
    now = _parse_ts(bus.get("generated_at"))
    evidences = load_evidences(str(bus_path))
    factors = _load_factors(Path(args.priors))
    buckets = _bucket_factors_by_dimension(factors)

    paths = synthesize_paths(evidences, now=now)
    base_dicts = [_to_diff_dict(p) for p in paths]
    base_w4 = adjudicate(paths)
    base_pos = _raw_position(base_w4["direction"], base_w4["total"])

    report: dict = {
        "meta": {
            "bus_generated_at": bus.get("generated_at"),
            "now_fixed": now.isoformat(),
            "evidence_count": len(evidences),
            "n_paths": len(paths),
            "n_factors": len(factors),
            "factor_dims_covered": sorted(buckets.keys()),
            "max_coef_cap": MAX_COEF,
        },
        "baseline": _summarize_w4(base_w4),
        "coef_sweep": [],
    }

    coefs = [float(c) for c in args.coefs.split(",") if c.strip()]
    for coef in coefs:
        overlaid = apply_factor_priors_overlay(paths, factors, coef)
        over_dicts = [_to_diff_dict(p) for p in overlaid]
        over_w4 = adjudicate(overlaid)
        over_pos = _raw_position(over_w4["direction"], over_w4["total"])

        diff = diff_path_sets(base_dicts, over_dicts)
        # 命中率：confidence 被调制的 path 数；方向翻转：direction 字段变化数
        conf_changed = sum(1 for d in diff["field_diffs"] if d["field"] == "confidence")
        dir_flips = sum(1 for d in diff["field_diffs"] if d["field"] == "direction")
        entry = {
            "coef": coef,
            "paths_modulated": conf_changed,
            "modulation_rate": round(conf_changed / len(paths), 4) if paths else 0.0,
            "path_direction_flips": dir_flips,
            "divergence_rate": diff["divergence_rate"],
            "w4": _summarize_w4(over_w4),
            "delta": {
                "total": round(over_w4["total"] - base_w4["total"], 6),
                "force": round(over_w4["force"] - base_w4["force"], 6),
                "impact": round(over_w4["impact"] - base_w4["impact"], 6),
                "raw_position": round(over_pos - base_pos, 4),
                "decision_direction_flip": over_w4["direction"] != base_w4["direction"],
                "decision_resonance_flip": over_w4["resonance"] != base_w4["resonance"],
                "decision_dominance_flip": over_w4["dominant"] != base_w4["dominant"],
            },
        }
        report["coef_sweep"].append(entry)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\n[report written] {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
