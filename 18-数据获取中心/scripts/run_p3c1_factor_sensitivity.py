#!/usr/bin/env python3
"""P3-c1 敏感因子探测 — SPEC §2.9.2 / §2.10。

流式读取 newsflash → 事件族/维度事件研究（OLS 控制同期事件共振）
→ factor_sensitivity.jsonl + p3c1_summary.json

口径：
  - 日线，pre_24h = r[D-1]，post_24h = r[D]，72h 为 3 日累计
  - 判据：pre/post 同号且过 5bp、事件日 ≥30、Holm p<0.10
  - 双映射 v1/v2 各跑一遍，报 Spearman
  - 单一价格源 → validation_type = same_source_review
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "18-数据获取中心"))

from data_center.processing.event_study import run_event_study, spearman  # noqa: E402
from data_center.processing.newsflash_events import MAPPING_VERSION  # noqa: E402
from data_center.processing.validation_independence import (  # noqa: E402
    SourceProfile,
    stamp_validation,
)

SRC = _REPO / "18-数据获取中心" / "backfill" / "newsflash_history.jsonl"
OUT = _REPO / "18-数据获取中心" / "backfill" / "p3c1"

PRIMARY = SourceProfile("yfinance-btc-daily", "1d", "yfinance", 0.0)
VALIDATOR = SourceProfile("yfinance-btc-daily", "1d", "yfinance", 0.0)  # 同源


def _stamp(rows: list[dict]) -> list[dict]:
    return [stamp_validation(r, PRIMARY, VALIDATOR) for r in rows]


def _dim_sens(rows: list[dict]) -> dict[str, float]:
    """映射差异只体现在维度归属上，故 Spearman 必须按维度比较。"""
    return {r["key"]: float(r["sens_f"]) for r in rows if r["unit"] == "dim"}


def main() -> int:
    if not SRC.exists():
        print(json.dumps({"degraded": True, "reason": "newsflash_missing"}, ensure_ascii=False))
        return 1

    n_records = sum(1 for line in SRC.open(encoding="utf-8") if line.strip())
    v1 = run_event_study(newsflash_path=SRC, mapping="v1")
    v2 = run_event_study(newsflash_path=SRC, mapping="v2")
    rows1, rows2 = _stamp(v1["rows"]), _stamp(v2["rows"])

    rho = spearman(_dim_sens(rows1), _dim_sens(rows2))
    eligible1 = [r for r in rows1 if r["eligible"]]
    summary = {
        "mapping_version": MAPPING_VERSION,
        "n_records": n_records,
        "v1": v1["diagnostics"],
        "v2": v2["diagnostics"],
        "spearman_v1_v2": rho,
        "validation_type": rows1[0]["validation_type"] if rows1 else "same_source_review",
        "n_rows": len(rows1),
        "n_eligible": len(eligible1),
        "conclusion": "p3c1_pass" if eligible1 else "p3c1_failed_no_significant_factor",
        "eligible": [
            {
                "unit": r["unit"],
                "key": r["key"],
                "dims": r.get("dims"),
                "n_events": r["n_events"],
                "sens_f": r["sens_f"],
                "direction": r["direction"],
                "p_holm": r["p_holm"],
            }
            for r in eligible1
        ],
        "kline_gap": "2026-09-11..2026-10-28 无日线，事件日落入缺口即丢弃",
    }

    OUT.mkdir(parents=True, exist_ok=True)
    for name, rows in (("factor_sensitivity.jsonl", rows1), ("factor_sensitivity_v2.jsonl", rows2)):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "p3c1_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
