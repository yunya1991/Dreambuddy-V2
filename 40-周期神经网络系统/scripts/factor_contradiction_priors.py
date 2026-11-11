"""factor_contradiction_priors.py — 40 域因子/矛盾先验输出（G4）。

职责（SPEC-EMERGENCE-FULL-CHAIN v1.0 §6 G4）：
  1. 聚合 39 域矛盾事件（contradiction_events.jsonl）→ 矛盾先验
     （按 contradiction_type / layer 统计频次与最近窗口）；
  2. 透传 18 域因子先验（factor_prior.json，degraded 时如实标注）；
  3. 聚合 48 域训练样本（training_samples/*.jsonl）→ 因子方向先验
     （按 dominant_factor × direction 统计，gate 加权）；
  4. 输出 `40-周期神经网络系统/factor_contradiction_priors.json`，
     供 43/49/50 下游消费。

纪律：FAIL-OPEN（任一源缺失/解析失败降级跳过，不中断）；只读上游，不回写。
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_BASE = os.environ.get("DREAMBUDDY_ROOT") or str(
    Path(__file__).resolve().parents[2]
)
D39 = os.path.join(_BASE, "39-金融语义蒸馏系统")
D40 = os.path.join(_BASE, "40-周期神经网络系统")
D18 = os.path.join(_BASE, "18-数据获取中心")
D48 = os.path.join(_BASE, "48-涌现架构")

CONTRADICTION_EVENTS = os.path.join(D39, "contradiction_events.jsonl")
FACTOR_PRIOR = os.path.join(D18, "backfill", "p3c1", "factor_prior.json")
TRAINING_SAMPLES_DIR = os.path.join(D48, "events", "training_samples")
OUT_PATH = os.path.join(D40, "factor_contradiction_priors.json")

SCHEMA_VERSION = "factor_contradiction_priors.v0.1"


def _rel(p: str) -> str:
    """绝对路径 → 仓库相对路径（产物可移植，避免硬编码部署路径）。"""
    return os.path.relpath(p, _BASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not os.path.exists(path):
        logger.warning("jsonl 源缺失（跳过）: %s", path)
        return rows
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except json.JSONDecodeError:
                    continue
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("jsonl 读取失败（降级）: %s %s", path, exc)
    return rows


def _read_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        logger.warning("json 源缺失（跳过）: %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
            return obj if isinstance(obj, dict) else {}
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("json 读取失败（降级）: %s %s", path, exc)
        return {}


def build_contradiction_priors() -> Dict[str, Any]:
    events = _read_jsonl(CONTRADICTION_EVENTS)
    by_type: Counter = Counter()
    by_layer: Counter = Counter()
    last_window: str = ""
    for ev in events:
        by_type[str(ev.get("contradiction_type", "unknown"))] += 1
        by_layer[str(ev.get("layer", "unknown"))] += 1
        w = str(ev.get("window_end", ""))
        if w > last_window:
            last_window = w
    return {
        "n_events": len(events),
        "by_contradiction_type": dict(by_type.most_common(20)),
        "by_layer": dict(by_layer.most_common(20)),
        "last_window_end": last_window or None,
        "source": _rel(CONTRADICTION_EVENTS),
    }


def build_factor_direction_priors() -> Dict[str, Any]:
    """聚合 48 域训练样本：dominant_factor × direction，gate 权重加权。"""
    if not os.path.isdir(TRAINING_SAMPLES_DIR):
        logger.warning("训练样本目录缺失（跳过）: %s", TRAINING_SAMPLES_DIR)
        return {"n_samples": 0, "factors": {}, "source": TRAINING_SAMPLES_DIR}
    weighted: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    n = 0
    for name in sorted(os.listdir(TRAINING_SAMPLES_DIR)):
        if not name.endswith(".jsonl"):
            continue
        for row in _read_jsonl(os.path.join(TRAINING_SAMPLES_DIR, name)):
            factor = row.get("dominant_factor")
            direction = row.get("direction")
            if not factor or not direction:
                continue
            n += 1
            weight = row.get("weight")
            w = float(weight) if isinstance(weight, (int, float)) else 1.0
            weighted[str(factor)][str(direction)] += w
            counts[str(factor)][str(direction)] += 1
    factors = {}
    for factor, dirs in weighted.items():
        total_w = sum(dirs.values())
        factors[factor] = {
            "directions": dict(dirs),
            "counts": dict(counts[factor]),
            "dominant_direction": max(dirs, key=lambda k: dirs[k]) if dirs else None,
            "total_weight": round(total_w, 4),
        }
    return {
        "n_samples": n,
        "factors": factors,
        "source": _rel(TRAINING_SAMPLES_DIR),
    }


def build_priors() -> Dict[str, Any]:
    factor_prior_18 = _read_json(FACTOR_PRIOR)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "factor_prior_18": {
            "degraded": bool(factor_prior_18.get("degraded", True)),
            "n_factors": factor_prior_18.get("n_factors", 0),
            "reason": factor_prior_18.get("reason"),
            "source": _rel(FACTOR_PRIOR),
        },
        "factor_direction_priors": build_factor_direction_priors(),
        "contradiction_priors": build_contradiction_priors(),
    }


def main() -> int:
    priors = build_priors()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(priors, f, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "out": _rel(OUT_PATH),
                "n_samples": priors["factor_direction_priors"]["n_samples"],
                "n_factors": len(priors["factor_direction_priors"]["factors"]),
                "n_contradiction_events": priors["contradiction_priors"]["n_events"],
                "factor_prior_18_degraded": priors["factor_prior_18"]["degraded"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
