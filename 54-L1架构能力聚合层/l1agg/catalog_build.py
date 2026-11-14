# -*- coding: utf-8 -*-
"""全量数据目录生成器：把 mm_metrics 的 (sub_category, metric_name) 穷举落盘。

产出 `l1agg/data_catalog.json`，供 `series_catalog.resolve_series` 做 Tier-2 精确解析：
用户直接说英文序列名（如 `mvrv_z_score`、`derivatives_spot`）也能命中。

用法：
    python3 -m l1agg.catalog_build                # 默认读本地 DAL 快照
    python3 -m l1agg.catalog_build --db <path>    # 指定库

注意：这是**离线生成**步骤。运行时只读 JSON，不扫库（execFile 每次调用都要快）。
数据源更新后重跑一次即可；`tests/test_data_catalog.py` 会校验目录与库不漂移。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from typing import Any, Dict

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(
    os.path.join(_HERE, "..", "..", "19-数据访问层", "data", "dreambuddy_core.db")
)
DEFAULT_OUT = os.path.join(_HERE, "data_catalog.json")


def build(db_path: str = "", out_path: str = "") -> Dict[str, Any]:
    """扫描 mm_metrics，返回 {"series": {"sub::metric": rows}, "events": {...}}。"""
    db = db_path or os.environ.get("DREAMBUDDY_CORE_DB") or DEFAULT_DB
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        series = {
            f"{sub}::{metric}": int(rows)
            for sub, metric, rows in conn.execute(
                "SELECT sub_category, metric_name, COUNT(*) FROM mm_metrics "
                "GROUP BY sub_category, metric_name "
                "ORDER BY sub_category, metric_name"
            )
        }
        events: Dict[str, int] = {}
        try:
            events = {
                str(etype): int(rows)
                for etype, rows in conn.execute(
                    "SELECT event_type, COUNT(*) FROM mm_events GROUP BY event_type"
                )
            }
        except sqlite3.Error:
            events = {}
    finally:
        conn.close()
    payload = {
        "generated_from": os.path.basename(db),
        "series": series,
        "events": events,
        "total_series": len(series),
    }
    path = out_path or DEFAULT_OUT
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="生成全量数据关键词目录 data_catalog.json")
    ap.add_argument("--db", default="", help="SQLite 路径（默认本地 DAL 快照）")
    ap.add_argument("--out", default="", help="输出路径（默认 l1agg/data_catalog.json）")
    args = ap.parse_args()
    payload = build(args.db, args.out)
    print(
        json.dumps(
            {
                "ok": True,
                "out": args.out or DEFAULT_OUT,
                "total_series": payload["total_series"],
                "events": payload["events"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
