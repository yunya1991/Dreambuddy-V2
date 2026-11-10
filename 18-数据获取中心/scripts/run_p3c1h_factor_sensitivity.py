#!/usr/bin/env python3
"""P3-c1h 小时级敏感因子探测 — A 方案（补 1h K 线重测）。

与日线版 run_p3c1_factor_sensitivity.py 的唯一差别是粒度：
  - 事件对到发布小时，窗口按小时累计（pre/post_1h、post_4h、pre/post_24h）
  - Newey-West HAC 标准误（lag = 窗口跨度），修日线版重叠窗口 t 值虚高风险
  - 控制 hour-of-day（快讯发布时段不均匀，BTC 有日内季节性）

输出：
  backfill/p3c1/factor_sensitivity_1h.jsonl
  backfill/p3c1/factor_sensitivity_1h_v2.jsonl
  backfill/p3c1/p3c1h_summary.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "18-数据获取中心"))

from data_center.processing.event_study import spearman  # noqa: E402
from data_center.processing.event_study_hourly import (  # noqa: E402
    DEFAULT_1H_CSV,
    run_event_study_hourly,
)
from data_center.processing.newsflash_events import MAPPING_VERSION  # noqa: E402
from data_center.processing.validation_independence import (  # noqa: E402
    SourceProfile,
    stamp_validation,
)

SRC = _REPO / "18-数据获取中心" / "backfill" / "newsflash_history.jsonl"
OUT = _REPO / "18-数据获取中心" / "backfill" / "p3c1"
META = OUT / "btc_1h_meta.json"

PRIMARY = SourceProfile("binance-btc-1h", "1h", "binance", 0.0)
VALIDATOR = SourceProfile("binance-btc-1h", "1h", "binance", 0.0)  # 同源


def _stamp(rows: list[dict]) -> list[dict]:
    return [stamp_validation(r, PRIMARY, VALIDATOR) for r in rows]


def _dim_sens(rows: list[dict]) -> dict[str, float]:
    return {r["key"]: float(r["sens_f"]) for r in rows if r["unit"] == "dim"}


def _brief(rows: list[dict], unit: str) -> list[dict]:
    return [
        {
            "key": r["key"],
            "n_events": r["n_events"],
            "sens_f_bp": round(r["sens_f"] * 10000, 2),
            "t_post": r["t_post"],
            "p_holm": r["p_holm"],
            "post_1h_bp": round((r["mean_excess_post_1h"] or 0) * 10000, 2),
            "post_4h_bp": round((r["mean_excess_post_4h"] or 0) * 10000, 2),
            "eligible": r["eligible"],
        }
        for r in rows
        if r["unit"] == unit
    ]


def main() -> int:
    if not SRC.exists():
        print(json.dumps({"degraded": True, "reason": "newsflash_missing"}, ensure_ascii=False))
        return 1
    if not DEFAULT_1H_CSV.exists():
        print(json.dumps({"degraded": True, "reason": "btc_1h_missing"}, ensure_ascii=False))
        return 1

    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    n_records = sum(1 for line in SRC.open(encoding="utf-8") if line.strip())

    v1 = run_event_study_hourly(newsflash_path=SRC, mapping="v1")
    v2 = run_event_study_hourly(newsflash_path=SRC, mapping="v2")
    rows1, rows2 = _stamp(v1["rows"]), _stamp(v2["rows"])

    rho = spearman(_dim_sens(rows1), _dim_sens(rows2))
    eligible = [r for r in rows1 if r["eligible"]]
    summary = {
        "mapping_version": MAPPING_VERSION,
        "granularity": "1h",
        "n_records": n_records,
        "kline": {
            "n_bars": meta.get("n_bars"),
            "first_bar": meta.get("first_bar"),
            "last_bar": meta.get("last_bar"),
            "coverage_pct": meta.get("coverage_pct"),
            "missing_hours_total": meta.get("missing_hours_total"),
        },
        "v1": v1["diagnostics"],
        "v2": v2["diagnostics"],
        "spearman_v1_v2_dim": rho,
        "validation_type": rows1[0]["validation_type"] if rows1 else "same_source_review",
        "n_rows": len(rows1),
        "n_eligible": len(eligible),
        "families_v1": _brief(rows1, "event_family"),
        "dims_v1": _brief(rows1, "dim"),
        "families_v2": _brief(rows2, "event_family"),
        "dims_v2": _brief(rows2, "dim"),
        "conclusion": "p3c1h_pass" if eligible else "p3c1h_failed_no_significant_factor",
        "eligible": [
            {
                "unit": r["unit"],
                "key": r["key"],
                "dims": r.get("dims"),
                "n_events": r["n_events"],
                "sens_f_bp": round(r["sens_f"] * 10000, 2),
                "direction": r["direction"],
                "p_holm": r["p_holm"],
            }
            for r in eligible
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("factor_sensitivity_1h.jsonl", rows1),
        ("factor_sensitivity_1h_v2.jsonl", rows2),
    ):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "p3c1h_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "conclusion",
                    "n_records",
                    "n_eligible",
                    "spearman_v1_v2_dim",
                    "kline",
                    "families_v1",
                    "dims_v1",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
