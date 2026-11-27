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
from datetime import datetime, timezone
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
CSV_1H = OUT / "btc_1h.csv"

PRIMARY = SourceProfile("yfinance-btc-daily", "1d", "yfinance", 0.0)
VALIDATOR = SourceProfile("yfinance-btc-daily", "1d", "yfinance", 0.0)  # 同源


def _daily_returns_from_1h(csv_path: Path) -> dict[str, float]:
    """从 btc_1h.csv 聚合 UTC 日收益。

    云端 `18-数据获取中心/data_center.db` 的 yfinance BTC-USD 序列为空，
    直接读库会 no_returns；1h 线（fetch_btc_1h.py 产出）覆盖 2023→当前，
    按日取最后收盘再算收益，作为日线源的无缺口替代。
    """
    if not csv_path.exists():
        return {}
    closes: dict[str, float] = {}
    with csv_path.open(encoding="utf-8") as fh:
        for idx, line in enumerate(fh):
            if idx == 0 or not line.strip():
                continue
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            try:
                ts_ms, close = int(parts[0]), float(parts[4])
            except ValueError:
                continue
            day = datetime.fromtimestamp(ts_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
            closes[day] = close  # 文件按时间升序，最后一条即当日收盘
    days = sorted(closes)
    return {
        days[i]: closes[days[i]] / closes[days[i - 1]] - 1.0
        for i in range(1, len(days))
        if closes[days[i - 1]]
    }


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
    returns = _daily_returns_from_1h(CSV_1H) or None
    v1 = run_event_study(newsflash_path=SRC, mapping="v1", returns=returns)
    v2 = run_event_study(newsflash_path=SRC, mapping="v2", returns=returns)
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
        "kline_gap": f"日收益源 {CSV_1H.name}（1h 聚合，2023→当前，仅缺 1 小时）",
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
