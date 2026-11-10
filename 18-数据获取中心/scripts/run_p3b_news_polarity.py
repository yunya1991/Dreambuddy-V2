#!/usr/bin/env python3
"""P3-b NEWS 维快讯极性 — SPEC-D1-MULTIDIM-STATE §2.8 / §7 P3-b。

与 P3-a 的区别：NEWS 维不再"无源不可测"，改由 193,300 条快讯的实时极性驱动。

流程：
  500 篇文章 → extract_dominance_claim
             → get_dimension_matrix(as_of, newsflash_jsonl=...)   # NEWS 已有数据
             → evaluate_claim（三档门控，与 P3-a 同口径）
             → NEWS 主导样本额外计算 pre_24h/pre_72h/post_24h/post_72h + lead/lag
             → p3b/news_agreement.jsonl + p3b_summary.json

预注册：NEWS 方向由日度 score 的滚动 z 决定（§2.6 契约）；一致率主口径 pre_72h
只用于 lead/lag 报告，不进分母。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "18-数据获取中心"))

from data_center.processing.dimension_context import get_dimension_matrix  # noqa: E402
from data_center.processing.dominance_agreement import (  # noqa: E402
    evaluate_claim,
    summarize,
)
from data_center.processing.factor_extractor import extract_dominance_claim  # noqa: E402
from data_center.processing.news_polarity import (  # noqa: E402
    all_window_scores,
    lead_lag,
    load_flashes,
)

SRC = _REPO / "18-数据获取中心" / "backfill" / "odaily_p0" / "contents.jsonl"
NEWSFLASH = _REPO / "18-数据获取中心" / "backfill" / "newsflash_history.jsonl"
OUT_DIR = _REPO / "18-数据获取中心" / "backfill" / "p3b"
KLINE_LAST_DATE = "2026-10-29"


def _parse_ts(s) -> int:
    """ISO 字符串 → epoch 秒；仅日期按 UTC 00:00。失败 → 0。"""
    try:
        raw = str(s or "").strip()
        if not raw:
            return 0
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


NEWS_SCORE_THRESHOLD = 0.05  # 预注册：实时窗口分绝对值阈值


def _flash_coverage() -> dict:
    """193k 条快讯的极性覆盖率 + 多空基准率（判据①）。"""
    flashes = load_flashes(NEWSFLASH)
    src = Counter(f.source for f in flashes)
    n_polar = sum(1 for f in flashes if f.sign)
    n_bull = sum(1 for f in flashes if f.sign > 0)
    n_bear = sum(1 for f in flashes if f.sign < 0)
    return {
        "n_flashes": len(flashes),
        "n_polar": n_polar,
        "coverage": round(n_polar / len(flashes), 4) if flashes else 0.0,
        "n_bull": n_bull,
        "n_bear": n_bear,
        "bull_share": round(n_bull / (n_bull + n_bear), 4) if n_polar else 0.0,
        "source_dist": dict(src),
    }


def _realtime_agreement(news_rows: list[dict]) -> dict:
    """快讯实时口径（pre_72h 符号）：一致率 + 多空拆分 + 平衡准确率。

    平衡准确率 = (多头敏感度 + 空头敏感度) / 2，用于剔除多头基准率污染。
    """
    tp = fn = tn = fp = 0
    for r in news_rows:
        win = r.get("news_windows")
        if not win:
            continue
        score = win.get("pre_72h", 0.0)
        measured = (
            "bullish"
            if score >= NEWS_SCORE_THRESHOLD
            else "bearish" if score <= -NEWS_SCORE_THRESHOLD else "neutral"
        )
        if measured == "neutral":
            continue
        claim = r.get("direction")
        if claim == "bullish":
            tp += measured == "bullish"
            fn += measured == "bearish"
        elif claim == "bearish":
            tn += measured == "bearish"
            fp += measured == "bullish"
    n = tp + fn + tn + fp
    sens = tp / (tp + fn) if (tp + fn) else None
    spec = tn / (tn + fp) if (tn + fp) else None
    ba = (sens + spec) / 2 if sens is not None and spec is not None else None
    return {
        "n_measurable": n,
        "n_agree": tp + tn,
        "agreement_rate": round((tp + tn) / n, 4) if n else None,
        "bull_claims_agree": tp,
        "bull_claims_total": tp + fn,
        "bear_claims_agree": tn,
        "bear_claims_total": tn + fp,
        "sensitivity_bull": round(sens, 4) if sens is not None else None,
        "specificity_bear": round(spec, 4) if spec is not None else None,
        "balanced_accuracy": round(ba, 4) if ba is not None else None,
        "threshold": NEWS_SCORE_THRESHOLD,
    }


def main() -> int:
    rows = [json.loads(line) for line in SRC.open(encoding="utf-8") if line.strip()]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    matrix_cache: dict[str, dict] = {}
    out_rows: list[dict] = []
    dim_counter: Counter = Counter()
    leadlag_counter: Counter = Counter()
    stale = 0

    for r in rows:
        text = r.get("content_text") or ""
        published = str(r.get("date_published") or "")
        as_of = published[:10]
        claim = extract_dominance_claim(text, doc_id=str(r.get("id", "")), published_at=as_of)
        if claim["dominant_dimension"]:
            dim_counter[claim["dominant_dimension"]] += 1
        if as_of > KLINE_LAST_DATE:
            stale += 1

        matrix = matrix_cache.get(as_of)
        if matrix is None:
            matrix = get_dimension_matrix(as_of, newsflash_jsonl=NEWSFLASH) if as_of else {}
            matrix_cache[as_of] = matrix

        verdict = evaluate_claim(claim, matrix)
        row = {
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
        if claim["dominant_dimension"] == "NEWS":
            ts = _parse_ts(published)
            if ts:
                w = all_window_scores(ts)
                ll = lead_lag(w["pre_72h"], w["post_24h"], claim["direction"])
                leadlag_counter[ll] += 1
                row["news_windows"] = {k: v["score"] for k, v in w.items()}
                row["news_coverage"] = w["pre_72h"]["coverage"]
                row["lead_lag"] = ll
        out_rows.append(row)

    with (OUT_DIR / "news_agreement.jsonl").open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize(out_rows)
    news_rows = [x for x in out_rows if x.get("dominant_dimension") == "NEWS"]
    news_meas = [x for x in news_rows if x.get("gate") != "unmeasurable"]
    news_agree = sum(1 for x in news_meas if x.get("agreement") is True)
    summary.update(
        {
            "n_articles": len(rows),
            "n_with_dominant": sum(dim_counter.values()),
            "n_no_dominant": len(rows) - sum(dim_counter.values()),
            "dominant_dimension_dist": dict(dim_counter),
            "n_as_of_after_kline_end": stale,
            "kline_last_date": KLINE_LAST_DATE,
            "flash_coverage": _flash_coverage(),
            "news_subset": {
                "n": len(news_rows),
                "n_measurable": len(news_meas),
                "measurable_rate": round(len(news_meas) / len(news_rows), 4) if news_rows else 0.0,
                "n_agree": news_agree,
                "agreement_rate_zbasis": (
                    round(news_agree / len(news_meas), 4) if news_meas else None
                ),
                "realtime": _realtime_agreement(news_rows),
                "lead_lag_dist": dict(leadlag_counter),
            },
            "gate_weights": {"consistent": 1.0, "divergent_but_valid": 1.5, "no_signal": 0.3},
            "min_z_valid": 1.0,
            "source": str(SRC),
            "newsflash": str(NEWSFLASH),
        }
    )
    (OUT_DIR / "p3b_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
