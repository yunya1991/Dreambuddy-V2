#!/usr/bin/env python3
"""P3-a 主导因素一致率 — SPEC-D1-MULTIDIM-STATE §7 P3-a。

流程：
  500 篇文章 → extract_dominance_claim（F3 主张）
             → get_dimension_matrix(as_of)（9 域实测上下文，18 域 adapter）
             → evaluate_claim（三档门控 / 样本权重）
             → dominance_agreement.jsonl + p3a_summary.json

预注册阈值见 dominance_agreement.GATE_WEIGHTS / MIN_Z_VALID。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "18-数据获取中心"))

from data_center.processing.dimension_context import get_dimension_matrix  # noqa: E402
from data_center.processing.dominance_agreement import (  # noqa: E402
    evaluate_claim,
    summarize,
)
from data_center.processing.factor_extractor import extract_dominance_claim  # noqa: E402

SRC = _REPO / "18-数据获取中心" / "backfill" / "odaily_p0" / "contents.jsonl"
OUT_DIR = _REPO / "18-数据获取中心" / "backfill" / "p3a"
KLINE_LAST_DATE = "2026-10-29"


def main() -> int:
    rows = [json.loads(line) for line in SRC.open(encoding="utf-8") if line.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    matrix_cache: dict[str, dict] = {}
    out_rows: list[dict] = []
    dim_counter: Counter = Counter()
    stale = 0

    for r in rows:
        text = r.get("content_text") or ""
        as_of = str(r.get("date_published") or "")[:10]
        claim = extract_dominance_claim(text, doc_id=str(r.get("id", "")), published_at=as_of)
        if claim["dominant_dimension"]:
            dim_counter[claim["dominant_dimension"]] += 1
        if as_of > KLINE_LAST_DATE:
            stale += 1

        matrix = matrix_cache.get(as_of)
        if matrix is None:
            matrix = get_dimension_matrix(as_of) if as_of else {}
            matrix_cache[as_of] = matrix

        verdict = evaluate_claim(claim, matrix)
        out_rows.append(
            {
                "doc_id": r.get("id"),
                "as_of": as_of,
                "title": r.get("title", "")[:80],
                "dominant_factor": claim["dominant_factor"],
                "dominant_dimension": claim["dominant_dimension"],
                "direction": claim["direction"],
                "horizon": claim["horizon"],
                "urgency": claim["urgency"],
                "impact": claim["impact"],
                **verdict,
            }
        )

    with (OUT_DIR / "dominance_agreement.jsonl").open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize(out_rows)
    summary.update(
        {
            "n_articles": len(rows),
            "n_with_dominant": sum(dim_counter.values()),
            "n_no_dominant": len(rows) - sum(dim_counter.values()),
            "dominant_dimension_dist": dict(dim_counter),
            "n_as_of_after_kline_end": stale,
            "kline_last_date": KLINE_LAST_DATE,
            "gate_weights": {"consistent": 1.0, "divergent_but_valid": 1.5, "no_signal": 0.3},
            "min_z_valid": 1.0,
            "source": str(SRC),
        }
    )
    (OUT_DIR / "p3a_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
