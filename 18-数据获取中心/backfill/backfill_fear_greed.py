#!/usr/bin/env python3
"""一次性回填（2026-11-11 / SPEC §10.0 D1）：crypto Fear & Greed 全历史 → data_center。

- 源：https://api.alternative.me/fng/?limit=0（2018-02-01 至今）
- 粒度：每日 1 条 records 行（source=fear_greed / sub_category=crypto_fear_greed，
  timestamp=<date>T00:00:00Z），供既有消费方按 ts[:10] 直接取日值
- 幂等：chain stable_id = `BTC|<date>` → dedupe_key 稳定，可安全重跑
- 可复现：报告记录 git_sha + 原始响应 sha256（§10.0 质量门禁「可复现」）

用法：
    python backfill/backfill_fear_greed.py            # 写 DATA_CENTER_BACKEND 指定后端（默认 postgres）
    python backfill/backfill_fear_greed.py --dry-run  # 只抓取 + 算覆盖度，不落库
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parents[1]  # 18-数据获取中心
sys.path.insert(0, str(_ROOT))

from data_center.core.contract import DataRecord, validate_record  # noqa: E402
from data_center.storage import sink_postgres  # noqa: E402

BASE_URL = "https://api.alternative.me/fng/"
REPORT_PATH = _ROOT.parent / "48-涌现架构" / "runtime" / "data_quality" / "fear_greed_backfill.json"

# §10.0 D1 验收 + 质量门禁
MIN_DAYS = 2500
MAX_GAP_DAYS = 5
MIN_COVERAGE_3Y = 0.95


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(_ROOT.parent), "rev-parse", "--short=10", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def fetch_all(attempts: int = 3) -> tuple[list[dict], str]:
    """抓全量历史；alternative.me 偶发 SSL EOF，重试 3 次。"""
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            resp = requests.get(BASE_URL, params={"limit": 0, "format": "json"}, timeout=30)
            resp.raise_for_status()
            return resp.json().get("data", []), hashlib.sha256(resp.content).hexdigest()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if i < attempts - 1:
                time.sleep(2 * (i + 1))
    raise RuntimeError(f"alternative.me 抓取失败（{attempts} 次）：{last_exc}")


def to_records(items: list[dict]) -> list[DataRecord]:
    records: list[DataRecord] = []
    for item in items:
        try:
            ts = int(item["timestamp"])
            day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            value = int(item["value"])
        except (KeyError, ValueError, TypeError):
            continue
        rec = DataRecord(
            source="fear_greed",
            category="chain",
            sub_category="crypto_fear_greed",
            timestamp=f"{day}T00:00:00Z",
            metrics={
                "symbol": "BTC",
                "value": value,
                "classification": item.get("value_classification", ""),
                "date": day,
                "count": 1,
            },
            events=[],
            timeseries=[],
            raw={
                "source": "alternative.me",
                "classification": item.get("value_classification", ""),
            },
        )
        validate_record(rec)
        records.append(rec)
    return records


def coverage_stats(days: list[date]) -> dict:
    days = sorted(set(days))
    if not days:
        return {"n_days": 0}
    gaps = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    cutoff = days[-1] - timedelta(days=365 * 3)
    recent = [d for d in days if d >= cutoff]
    expected = (days[-1] - cutoff).days + 1
    return {
        "n_days": len(days),
        "first": days[0].isoformat(),
        "last": days[-1].isoformat(),
        "max_gap_days": max(gaps) if gaps else 0,
        "coverage_3y": round(len(recent) / expected, 4) if expected > 0 else 0.0,
        "stale_days": (datetime.now(timezone.utc).date() - days[-1]).days,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fear & Greed 全历史回填（P0-E D1）")
    parser.add_argument("--dry-run", action="store_true", help="不落库，只输出覆盖度")
    args = parser.parse_args()

    items, response_sha = fetch_all()
    records = to_records(items)
    days = [date.fromisoformat(r.metrics["date"]) for r in records]
    stats = coverage_stats(days)

    inserted = 0
    backend = "dry-run"
    if not args.dry_run:
        import os

        backend = os.environ.get("DATA_CENTER_BACKEND", "postgres")
        inserted = sink_postgres.get_sink().write(records)

    passed = (
        stats["n_days"] >= MIN_DAYS
        and stats.get("max_gap_days", 999) <= MAX_GAP_DAYS
        and stats.get("coverage_3y", 0) >= MIN_COVERAGE_3Y
    )
    report = {
        "task": "SPEC-EMERGENCE-FINANCIAL-ENV §10.0 D1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": backend,
        "source": BASE_URL,
        "response_sha256": response_sha,
        "git_sha": _git_sha(),
        "fetched_rows": len(records),
        "inserted_rows": inserted,
        "stats": stats,
        "thresholds": {
            "min_days": MIN_DAYS,
            "max_gap_days": MAX_GAP_DAYS,
            "min_coverage_3y": MIN_COVERAGE_3Y,
        },
        "passed": passed,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
