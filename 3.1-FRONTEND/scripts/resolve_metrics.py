#!/usr/bin/env python3
"""resolve_metrics.py — resolve 观测存储与报表（SPEC-54 R6）。

职责：
  1. 逐次记录 `capability_id / tier / code / 耗时 / n / cache_hit`；
  2. 按日聚合成功率、P50/P95 与失败 code 分布；
  3. 分档 P95 报表（单资产 ≤3s / 多资产 ≤8s / 缓存命中 ≤3s）；
  4. 近 5 分钟失败率 >20% 时定位到具体能力。

用法：
  python3 scripts/resolve_metrics.py --report --days 7
  python3 scripts/resolve_metrics.py --report --days 1   # JSON 单行输出

FAIL-OPEN：任何写入/读取异常都不影响 resolve 主链路。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, Iterable, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
DEFAULT_DB_PATH = os.path.join(_REPO_ROOT, "19-数据访问层", "data", "visual_metrics.db")

# 与 SPEC-54 R6 一致的分档目标（毫秒）
TIER_TARGETS = {"single": 3000, "multi": 8000, "cache": 3000}
RETENTION_DAYS = 90
_ALERT_WINDOW_S = 300
_ALERT_MIN_COUNT = 5
_ALERT_FAILURE_RATE = 0.2

_write_count = 0


def db_path() -> str:
    return os.environ.get("VISUAL_METRICS_DB") or DEFAULT_DB_PATH


def _connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=3.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resolve_metric (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            day TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            tier TEXT NOT NULL,
            code TEXT NOT NULL,
            elapsed_ms INTEGER NOT NULL DEFAULT 0,
            n INTEGER NOT NULL DEFAULT 0,
            cache_hit INTEGER NOT NULL DEFAULT 0
        )
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resolve_metric_day ON resolve_metric(day)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resolve_metric_ts ON resolve_metric(ts)")


def record(
    capability_id: str,
    code: str,
    elapsed_ms: int,
    n: int = 0,
    tier: str = "single",
    cache_hit: bool = False,
    now: Optional[float] = None,
) -> None:
    """记录一次 resolve；异常全部吞掉（观测不得影响取数）。"""
    global _write_count
    try:
        ts = int(now if now is not None else time.time())
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        with _connect() as conn:
            _ensure_schema(conn)
            conn.execute(
                "INSERT INTO resolve_metric (ts, day, capability_id, tier, code, elapsed_ms, n, cache_hit) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    day,
                    capability_id or "",
                    tier or "single",
                    code or "error",
                    int(elapsed_ms),
                    int(n),
                    int(bool(cache_hit)),
                ),
            )
            _write_count += 1
            if _write_count % 200 == 0:
                conn.execute(
                    "DELETE FROM resolve_metric WHERE ts < ?",
                    (ts - RETENTION_DAYS * 86400,),
                )
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return


def _percentile(values: Iterable[int], pct: float) -> Optional[int]:
    """nearest-rank 百分位（与线上口径一致，无需插值）。"""
    ordered = sorted(int(v) for v in values)
    if not ordered:
        return None
    rank = max(1, int(-(-len(ordered) * pct // 100)))  # ceil(n * pct / 100)
    return ordered[min(rank, len(ordered)) - 1]


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"count": 0, "ok_count": 0, "success_rate": None, "p50_ms": None, "p95_ms": None}
    elapsed = [int(row["elapsed_ms"]) for row in rows]
    ok_count = sum(1 for row in rows if row["code"] == "ok")
    return {
        "count": len(rows),
        "ok_count": ok_count,
        "success_rate": round(ok_count / len(rows), 4),
        "p50_ms": _percentile(elapsed, 50),
        "p95_ms": _percentile(elapsed, 95),
    }


def _code_distribution(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    dist: Dict[str, int] = {}
    for row in rows:
        code = str(row["code"] or "error")
        dist[code] = dist.get(code, 0) + 1
    return dict(sorted(dist.items(), key=lambda item: (-item[1], item[0])))


def _report_tier(row: Dict[str, Any]) -> str:
    # 缓存命中单独成档：目标是 ≤3s，不能与多资产混淆
    return "cache" if int(row["cache_hit"]) else str(row["tier"] or "single")


def _fetch(conn: sqlite3.Connection, since_ts: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT ts, day, capability_id, tier, code, elapsed_ms, n, cache_hit "
        "FROM resolve_metric WHERE ts >= ? ORDER BY ts",
        (since_ts,),
    ).fetchall()
    return [
        {
            "ts": int(row[0]),
            "day": row[1],
            "capability_id": row[2],
            "tier": row[3],
            "code": row[4],
            "elapsed_ms": int(row[5]),
            "n": int(row[6]),
            "cache_hit": int(row[7]),
        }
        for row in rows
    ]


def _group_by(rows: List[Dict[str, Any]], key_fn) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(key_fn(row)), []).append(row)
    return grouped


def daily_report(days: int = 7, now: Optional[float] = None) -> Dict[str, Any]:
    """按日聚合 + 分档 P95 + 失败 code 分布 + 近 5 分钟能力级告警。"""
    now_ts = int(now if now is not None else time.time())
    days = max(1, int(days))
    since_ts = now_ts - days * 86400
    try:
        with _connect() as conn:
            _ensure_schema(conn)
            rows = _fetch(conn, since_ts)
    except Exception as exc:  # noqa: BLE001 — 报表不可用时不伪造
        return {
            "ok": False,
            "code": "error",
            "reason": f"{type(exc).__name__}: {exc}",
            "days": days,
        }

    daily = []
    for day in sorted({row["day"] for row in rows}):
        day_rows = [row for row in rows if row["day"] == day]
        daily.append(
            {
                "day": day,
                **_stats(day_rows),
                "codes": _code_distribution(day_rows),
                "tiers": {
                    tier: _stats(tier_rows)
                    for tier, tier_rows in _group_by(day_rows, _report_tier).items()
                },
            }
        )

    tiers = {
        tier: _stats(tier_rows) for tier, tier_rows in sorted(_group_by(rows, _report_tier).items())
    }
    breaches = [
        {"tier": tier, "p95_ms": stat["p95_ms"], "target_ms": TIER_TARGETS.get(tier)}
        for tier, stat in tiers.items()
        if stat["p95_ms"] is not None
        and tier in TIER_TARGETS
        and stat["p95_ms"] > TIER_TARGETS[tier]
    ]

    failures = [
        {"capability_id": cap, "code": code, "count": count}
        for cap, code, count in sorted(
            (
                (cap, code, sum(1 for row in cap_rows if row["code"] == code))
                for cap, cap_rows in _group_by(
                    [row for row in rows if row["code"] != "ok"], lambda row: row["capability_id"]
                ).items()
                for code in {row["code"] for row in cap_rows}
            ),
            key=lambda item: -item[2],
        )[:10]
    ]

    recent = [row for row in rows if row["ts"] >= now_ts - _ALERT_WINDOW_S]
    alerts = []
    for cap, cap_rows in _group_by(recent, lambda row: row["capability_id"]).items():
        if len(cap_rows) < _ALERT_MIN_COUNT:
            continue
        failure_rate = sum(1 for row in cap_rows if row["code"] != "ok") / len(cap_rows)
        if failure_rate > _ALERT_FAILURE_RATE:
            alerts.append(
                {
                    "capability_id": cap,
                    "count": len(cap_rows),
                    "failure_rate": round(failure_rate, 4),
                    "codes": _code_distribution(cap_rows),
                }
            )

    return {
        "ok": True,
        "days": days,
        "since": time.strftime("%Y-%m-%d", time.gmtime(since_ts)),
        "total": len(rows),
        **_stats(rows),
        "daily": daily,
        "tiers": tiers,
        "targets": TIER_TARGETS,
        "breaches": breaches,
        "failures": failures,
        "alerts": sorted(alerts, key=lambda item: -item["failure_rate"]),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="resolve 观测报表（SPEC-54 R6）")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)
    if not args.report:
        parser.print_help()
        return 2
    sys.stdout.write(json.dumps(daily_report(args.days), ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
