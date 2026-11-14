#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S1.0-4 覆盖体检：mm_metrics 每个 metric 的 n / 起止 / 缺失率 / 异常值。

只读：连接一律 mode=ro，不建表、不写 mm_metrics。

口径（两条，避免把「交易所休市」误判成缺口）：
- 7×24 市场（okx 标的）：分母用日历日；缺口阈值 max_gap_ratio
- 交易日市场（fred 序列）：分母用工作日（周一~周五，含美股假日）；阈值 max_gap_ratio_trading

已知事实在报告中显式登记，不当脏数据：
- 负 epoch（1970 前）为 FRED 长序列真实历史（PPIACO 1913、CPIAUCSL 1947 等）
- XAU 用 OKX XAUT-USDT 代理现货黄金
- SP500 序列仅从 2016 起

用法:
  python3 scripts/coverage_audit.py --db <path> --days 1095 --out reports/coverage/<date>.md
  python3 scripts/coverage_audit.py --json          # 机器可读
"""

import argparse
import datetime
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.asset_pool import Anchor, load  # noqa: E402

_DEFAULT_DB = os.path.join(_MODULE_ROOT, "..", "19-数据访问层", "data", "dreambuddy_core.db")
_DAY = 86400
_TOP_N = 25  # 明细表最多展示的 series 数


# ============================================================ 时间口径
def _day_index(ts: int) -> int:
    return ts // _DAY


def _calendar_days(first_ts: int, last_ts: int) -> int:
    return _day_index(last_ts) - _day_index(first_ts) + 1


def _business_days(first_ts: int, last_ts: int) -> int:
    start = datetime.datetime.fromtimestamp(_day_index(first_ts) * _DAY, datetime.UTC).date()
    end = datetime.datetime.fromtimestamp(_day_index(last_ts) * _DAY, datetime.UTC).date()
    total = (end - start).days + 1
    full_weeks, rest = divmod(total, 7)
    count = full_weeks * 5
    weekday = start.weekday()
    for i in range(rest):
        if (weekday + i) % 7 < 5:
            count += 1
    return max(1, count)


def _source_of(anchor: Anchor) -> str:
    return anchor.venue or ""


# ============================================================ 采集
def _connect_ro(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def collect_metrics(conn: sqlite3.Connection, since: int) -> List[Dict[str, Any]]:
    """一次聚合出全部 series 的规模指标（不做逐点扫描）。"""
    rows = conn.execute(
        """
        SELECT source, sub_category, metric_name,
               COUNT(*) AS n,
               SUM(CASE WHEN metric_value IS NULL THEN 1 ELSE 0 END) AS nulls,
               MIN(timestamp) AS ts_min,
               MAX(timestamp) AS ts_max,
               MIN(metric_value) AS v_min,
               MAX(metric_value) AS v_max,
               AVG(metric_value) AS v_avg
        FROM mm_metrics
        WHERE timestamp >= ?
        GROUP BY 1, 2, 3
        """,
        (since,),
    ).fetchall()
    out = []
    for src, sub, metric, n, nulls, ts_min, ts_max, v_min, v_max, v_avg in rows:
        span_days = _calendar_days(int(ts_min), int(ts_max))
        out.append(
            {
                "source": src,
                "sub_category": sub,
                "metric_name": metric,
                "n": int(n),
                "nulls": int(nulls or 0),
                "ts_min": int(ts_min),
                "ts_max": int(ts_max),
                "span_days": span_days,
                "v_min": v_min,
                "v_max": v_max,
                "v_avg": v_avg,
                "rows_per_day": round(int(n) / span_days, 2),
                "non_null_ratio": round(1 - (int(nulls or 0) / int(n)), 4) if n else 0.0,
            }
        )
    return out


def series_detail(
    conn: sqlite3.Connection, key: Tuple[str, str, str], since: int
) -> Dict[str, Any]:
    """单个 series 的逐点扫描：缺口、最长空档、|z|>5 异常点。"""
    src, sub, metric = key
    rows = conn.execute(
        """
        SELECT timestamp, metric_value FROM mm_metrics
        WHERE source=? AND sub_category=? AND metric_name=? AND timestamp >= ?
        ORDER BY timestamp
        """,
        (src, sub, metric, since),
    ).fetchall()
    if not rows:
        return {"outliers": 0, "outlier_samples": [], "distinct_days": 0, "longest_gap_days": 0}

    vals = [float(v) for _, v in rows if v is not None]
    mean = sum(vals) / len(vals) if vals else 0.0
    var = sum((v - mean) ** 2 for v in vals) / len(vals) if vals else 0.0
    std = var**0.5

    outliers = []
    for ts, v in rows:
        if v is None or std == 0:
            continue
        z = (float(v) - mean) / std
        if abs(z) > 5:
            outliers.append({"ts": int(ts), "value": float(v), "z": round(z, 2)})

    days = sorted({_day_index(int(ts)) for ts, _ in rows})
    longest = 0
    for prev, cur in zip(days, days[1:], strict=False):
        longest = max(longest, cur - prev - 1)
    return {
        "outliers": len(outliers),
        "outlier_samples": outliers[:3],
        "distinct_days": len(days),
        "longest_gap_days": longest,
    }


def collect_anomalies(conn: sqlite3.Connection) -> Dict[str, Any]:
    null_rows = conn.execute("""
        SELECT source, sub_category, metric_name, COUNT(*)
        FROM mm_metrics WHERE metric_value IS NULL
        GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 10
        """).fetchall()
    negative = conn.execute("""
        SELECT sub_category, COUNT(*), MIN(timestamp), MAX(timestamp)
        FROM mm_metrics WHERE timestamp < 0
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """).fetchall()
    multi_source = conn.execute("""
        SELECT sub_category, metric_name, COUNT(DISTINCT source) AS s,
               GROUP_CONCAT(DISTINCT source)
        FROM mm_metrics GROUP BY 1,2 HAVING s > 1 ORDER BY s DESC, 1 LIMIT 10
        """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM mm_metrics").fetchone()[0]
    null_total = conn.execute(
        "SELECT COUNT(*) FROM mm_metrics WHERE metric_value IS NULL"
    ).fetchone()[0]
    neg_total = conn.execute("SELECT COUNT(*) FROM mm_metrics WHERE timestamp < 0").fetchone()[0]
    return {
        "total_rows": int(total),
        "null_total": int(null_total),
        "negative_total": int(neg_total),
        "null_top": [
            {"source": r[0], "sub_category": r[1], "metric_name": r[2], "n": int(r[3])}
            for r in null_rows
        ],
        "negative_top": [
            {
                "sub_category": r[0],
                "n": int(r[1]),
                "first": int(r[2]),
                "last": int(r[3]),
            }
            for r in negative
        ],
        "multi_source": [
            {"sub_category": r[0], "metric_name": r[1], "sources": r[3].split(",")}
            for r in multi_source
        ],
    }


# ============================================================ 判定
def judge_anchor(
    anchor: Anchor,
    metrics: List[Dict[str, Any]],
    detail: Dict[str, Any],
    quality: Dict[str, Any],
    now: int,
) -> Dict[str, Any]:
    """按资产池 quality 门禁判定单个锚定资产（7×24 与交易日两套口径）。"""
    src = _source_of(anchor)
    sub, metric = anchor.storage_key
    row = next(
        (
            m
            for m in metrics
            if m["source"] == src and m["sub_category"] == sub and m["metric_name"] == metric
        ),
        None,
    )
    trading_calendar = src == "fred"
    if row is None:
        return {
            "id": anchor.id,
            "source": src,
            "series": f"{sub}.{metric}",
            "status": "MISSING",
            "reasons": ["窗口内无数据"],
            "n": 0,
            "span_days": 0,
            "gap_ratio": None,
            "stale_days": None,
            "non_null_ratio": 0.0,
            "outliers": 0,
            "longest_gap_days": 0,
            "proxy": anchor.proxy,
            "proxy_note": anchor.proxy_note,
        }

    denominator = (
        _business_days(row["ts_min"], row["ts_max"]) if trading_calendar else row["span_days"]
    )
    present = detail.get("distinct_days") or row["span_days"]
    gap_ratio = round(max(0.0, 1 - present / denominator), 4)
    stale_days = max(0, (_day_index(now) - _day_index(row["ts_max"])))
    min_rows = int(quality.get("min_rows_3y_trading" if trading_calendar else "min_rows_3y", 0))
    max_gap = float(
        quality.get("max_gap_ratio_trading" if trading_calendar else "max_gap_ratio", 0.01)
    )

    reasons = []
    if row["n"] < min_rows:
        reasons.append(f"行数 {row['n']} < {min_rows}")
    if gap_ratio > max_gap:
        reasons.append(f"缺口率 {gap_ratio:.2%} > {max_gap:.0%}")
    if row["non_null_ratio"] < float(quality.get("min_non_null_ratio", 0)):
        reasons.append(f"非空率 {row['non_null_ratio']:.2%} 不足")
    if stale_days > int(quality.get("stale_days", 3)):
        reasons.append(f"陈旧 {stale_days} 天")

    return {
        "id": anchor.id,
        "source": src,
        "series": f"{sub}.{metric}",
        "status": "PASS" if not reasons else "FAIL",
        "reasons": reasons,
        "n": row["n"],
        "span_days": row["span_days"],
        "gap_ratio": gap_ratio,
        "stale_days": stale_days,
        "non_null_ratio": row["non_null_ratio"],
        "trading_calendar": trading_calendar,
        "outliers": detail.get("outliers", 0),
        "longest_gap_days": detail.get("longest_gap_days", 0),
        "ts_min": row["ts_min"],
        "ts_max": row["ts_max"],
        "proxy": anchor.proxy,
        "proxy_note": anchor.proxy_note,
    }


# ============================================================ 主流程
def audit(
    db_path: str, *, days: int = 1095, top_n: int = _TOP_N, now: Optional[int] = None
) -> Dict[str, Any]:
    now = now or int(datetime.datetime.now(datetime.UTC).timestamp())
    since = now - days * _DAY
    pool = load()
    conn = _connect_ro(db_path)
    try:
        metrics = collect_metrics(conn, since)
        anomalies = collect_anomalies(conn)
        keys = {(m["source"], m["sub_category"], m["metric_name"]): m for m in metrics}
        details: Dict[str, Dict[str, Any]] = {}
        for key in keys:
            details[key[0] + "|" + key[1] + "|" + key[2]] = series_detail(conn, key, since)
    finally:
        conn.close()

    anchors = []
    for anchor in pool.anchors:
        if not anchor.enabled:
            continue
        src = _source_of(anchor)
        sub, metric = anchor.storage_key
        detail = details.get(f"{src}|{sub}|{metric}", {})
        anchors.append(judge_anchor(anchor, metrics, detail, pool.quality, now))

    top = sorted(metrics, key=lambda m: m["n"], reverse=True)[:top_n]
    worst = sorted(
        [m for m in metrics if m["n"] >= 30 and m["non_null_ratio"] < 1.0],
        key=lambda m: m["non_null_ratio"],
    )[:10]

    return {
        "db": os.path.abspath(db_path),
        "generated_at": datetime.datetime.fromtimestamp(now, datetime.UTC).isoformat(),
        "window_days": days,
        "since": since,
        "series_total": len(metrics),
        "anchors": anchors,
        "anchors_pass": sum(1 for a in anchors if a["status"] == "PASS"),
        "top_series": top,
        "worst_non_null": worst,
        "anomalies": anomalies,
        "detail_index": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in details.items()},
    }


# ============================================================ 渲染
def _fmt_date(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    return datetime.datetime.fromtimestamp(int(ts), datetime.UTC).strftime("%Y-%m-%d")


def render_markdown(result: Dict[str, Any]) -> str:
    a = result["anomalies"]
    lines = [
        f"# 覆盖体检报告 · {_fmt_date(result['since'] + result['window_days'] * _DAY)}",
        "",
        f"- 数据库：`{result['db']}`",
        f"- 生成时间：{result['generated_at']}",
        f"- 统计窗口：近 {result['window_days']} 天（{_fmt_date(result['since'])} 起）",
        f"- series 数：{result['series_total']} ｜ 总行数：{a['total_rows']:,}",
        f"- 锚定资产：{result['anchors_pass']}/{len(result['anchors'])} PASS",
        "",
        "## 1. 锚定资产达标",
        "",
        "| 资产 | source | series | n | 跨度(天) | 缺口率 | 非空率 | 陈旧(天) | 异常点 | 判定 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for x in result["anchors"]:
        gap = "-" if x["gap_ratio"] is None else f"{x['gap_ratio']:.2%}"
        stale = "-" if x["stale_days"] is None else str(x["stale_days"])
        lines.append(
            f"| {x['id']} | {x['source']} | `{x['series']}` | {x['n']} | {x['span_days']} | "
            f"{gap} | {x['non_null_ratio']:.1%} | {stale} | {x['outliers']} | "
            f"{'PASS' if x['status'] == 'PASS' else '**FAIL**'} |"
        )
    fails = [x for x in result["anchors"] if x["status"] != "PASS"]
    if fails:
        lines += ["", "失败原因："]
        for x in fails:
            lines.append(f"- `{x['id']}`：{'；'.join(x['reasons'])}")
    proxies = [x for x in result["anchors"] if x["proxy"]]
    if proxies:
        lines += ["", "代理资产："]
        for x in proxies:
            lines.append(f"- `{x['id']}`：{x['proxy_note']}")

    lines += [
        "",
        "## 2. 口径说明",
        "",
        "- **7×24 市场**（`okx` 标的）：缺口率分母为日历日，阈值 `max_gap_ratio`。",
        "- **交易日市场**（`fred` 序列）：缺口率分母为工作日（含美股假日），阈值 `max_gap_ratio_trading`；"
        "行数下限用 `min_rows_3y_trading`，避免把周末与休市误判为缺口。",
        "- 缺口率 = 1 − 实际覆盖日数 / 应有日数；窗口内首个/末个数据点之间按天对齐。",
        "",
        "## 3. 数据规模 Top series",
        "",
        "| source | sub_category | metric | n | 起 | 止 | 行/天 | 非空率 |",
        "|---|---|---|---:|---|---|---:|---:|",
    ]
    for m in result["top_series"]:
        lines.append(
            f"| {m['source']} | `{m['sub_category']}` | `{m['metric_name']}` | {m['n']} | "
            f"{_fmt_date(m['ts_min'])} | {_fmt_date(m['ts_max'])} | {m['rows_per_day']} | "
            f"{m['non_null_ratio']:.1%} |"
        )

    lines += [
        "",
        "## 4. 异常与缺失",
        "",
        f"- `metric_value IS NULL`：**{a['null_total']:,}** 行"
        f"（占 {a['null_total'] / max(1, a['total_rows']):.2%}）",
        f"- 负时间戳（1970 前）：**{a['negative_total']:,}** 行 —— 属 FRED 长序列真实历史，"
        "做分位/相关性时按窗口截取，不得当脏数据删除",
        "",
    ]
    if a["null_top"]:
        lines += [
            "NULL 最多的 series：",
            "",
            "| source | sub_category | metric | NULL 行数 |",
            "|---|---|---|---:|",
        ]
        for r in a["null_top"]:
            lines.append(
                f"| {r['source']} | `{r['sub_category']}` | `{r['metric_name']}` | {r['n']} |"
            )
        lines.append("")
    if a["negative_top"]:
        lines += [
            "1970 前历史 series：",
            "",
            "| sub_category | 行数 | 起点 | 终点 |",
            "|---|---:|---|---|",
        ]
        for r in a["negative_top"]:
            lines.append(
                f"| `{r['sub_category']}` | {r['n']} | {_fmt_date(r['first'])} | {_fmt_date(r['last'])} |"
            )
        lines.append("")
    if result["worst_non_null"]:
        lines += [
            "非空率最低（n≥30）：",
            "",
            "| source | sub_category | metric | 非空率 | n |",
            "|---|---|---|---:|---:|",
        ]
        for m in result["worst_non_null"]:
            lines.append(
                f"| {m['source']} | `{m['sub_category']}` | `{m['metric_name']}` | "
                f"{m['non_null_ratio']:.1%} | {m['n']} |"
            )
        lines.append("")

    lines += [
        "## 5. 跨源重复",
        "",
        "同一 `(sub_category, metric_name)` 被多个 source 写入，统计前需按 `source_priority` 去重：",
        "",
    ]
    if a["multi_source"]:
        lines += ["| sub_category | metric | sources |", "|---|---|---|"]
        for r in a["multi_source"]:
            lines.append(
                f"| `{r['sub_category']}` | `{r['metric_name']}` | {', '.join(r['sources'])} |"
            )
    else:
        lines.append("- 未发现跨源重复")
    lines += [
        "",
        "## 6. 结论",
        "",
        f"- 锚定资产 {result['anchors_pass']}/{len(result['anchors'])} 达标；"
        + (
            "S1.0-4 通过，可进入 S1。"
            if not fails
            else "存在 FAIL 项，按失败原因补齐后才可进入 S1。"
        ),
        "- 未覆盖项：本报告只体检「行数与可用性」，不做指标别名与前端模块的一一映射"
        "（该映射在 S1 交付时逐模块验收）。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="mm_metrics 覆盖体检（S1.0-4）")
    parser.add_argument("--db", default=_DEFAULT_DB)
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--top", type=int, default=_TOP_N)
    parser.add_argument("--out", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = audit(args.db, days=args.days, top_n=args.top)
    md = render_markdown(result)
    if args.out:
        out = args.out
        if not os.path.isabs(out):
            out = os.path.join(_MODULE_ROOT, out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(md)
    if args.json:
        payload = {k: v for k, v in result.items() if k != "detail_index"}
        print(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        print(md)
    all_pass = result["anchors_pass"] == len(result["anchors"])
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
