#!/usr/bin/env python3
"""A-2 数据上下文 + A-3 交叉统计：在已发布序列上做分布描述与分组统计。

用法:
    python3 context.py --describe DGS10
    python3 context.py --describe DGS10 --peers DGS2,FEDFUNDS
    python3 context.py --cross DGS10,CPIAUCSL --bucket year
    python3 context.py --basket DGS10,DGS2,CPIAUCSL,UNRATE
    python3 context.py --version

数据源: FRED 公开 CSV（Public Domain）。
输出: 口径 / 分布 / 分组 / 相关；只分组不排序，不含判断与建议。仅使用标准库。
"""

import argparse
import csv
import io
import json
import math
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

VERSION = "1.0.0"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
UA = {"User-Agent": "market-data-hub/1.0 (research; contact: ops@neodrm.com)"}
LICENSE = "Public Domain"
SOURCE_NAME = "FRED / Federal Reserve Bank of St. Louis"
SOURCE_URL = "https://fred.stlouisfed.org/"
LIMITS = "仅提供分布与分组描述，不含排序、因果解释或方向判断。"

NAMES = {
    "DGS10": "美国10年期国债收益率(%)",
    "DGS2": "美国2年期国债收益率(%)",
    "DGS3MO": "美国3个月期国债收益率(%)",
    "FEDFUNDS": "联邦基金有效利率(%)",
    "CPIAUCSL": "美国CPI指数",
    "UNRATE": "美国失业率(%)",
    "GDPC1": "美国实际GDP(十亿美元)",
    "DTWEXBGS": "美元贸易加权指数",
}


def err_code(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "E_HTTP_{}".format(exc.code)
    if isinstance(exc, ssl.SSLError):
        return "E_TLS"
    if isinstance(exc, (socket.timeout, TimeoutError, urllib.error.URLError)):
        return "E_NET"
    if isinstance(exc, ValueError):
        return "E_EMPTY"
    return "E_SCHEMA"


def fetch(series, timeout=25):
    req = urllib.request.Request(FRED.format(series), headers=UA)
    for attempt in range(3):  # 最多重试 2 次，指数退避应对 TLS 抖动
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        raise ValueError("empty series")
    out = []
    for r in rows[1:]:
        if len(r) < 2:
            continue
        try:
            out.append((r[0], float(r[1])))
        except ValueError:
            continue
    if not out:
        raise ValueError("no numeric observations")
    return out


def quantile(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def pctile(values, window):
    sample = values[-window:]
    if not sample:
        return None
    return sum(1 for x in sample if x <= sample[-1]) / float(len(sample))


def frequency(obs):
    if len(obs) < 3:
        return "unknown"
    gaps = []
    for i in range(1, min(len(obs), 20)):
        d0 = datetime.strptime(obs[i - 1][0], "%Y-%m-%d")
        d1 = datetime.strptime(obs[i][0], "%Y-%m-%d")
        gaps.append((d1 - d0).days)
    g = sum(gaps) / len(gaps)
    if g <= 3:
        return "daily"
    if g <= 10:
        return "weekly"
    if g <= 45:
        return "monthly"
    return "quarterly"


def align(a, b):
    da = dict(a)
    db = dict(b)
    keys = sorted(set(da) & set(db))
    return [da[k] for k in keys], [db[k] for k in keys], keys


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def describe(series, window, peers):
    obs = fetch(series)
    vals = [v for _, v in obs]
    sample = sorted(vals[-window:])
    latest = vals[-1]
    row = {
        "series": series,
        "name": NAMES.get(series, series),
        "unit": "%" if series in ("DGS10", "DGS2", "DGS3MO", "FEDFUNDS", "UNRATE") else "index",
        "frequency": frequency(obs),
        "range": {"start": obs[0][0], "end": obs[-1][0], "n": len(obs)},
        "latest": latest,
        "latest_date": obs[-1][0],
        "distribution": {
            "window": window, "n": len(sample),
            "p05": quantile(sample, 0.05), "p25": quantile(sample, 0.25),
            "p50": quantile(sample, 0.50), "p75": quantile(sample, 0.75),
            "p95": quantile(sample, 0.95),
            "latest_pctile": pctile(vals, window),
        },
        "comparables": [],
        "n": len(sample),
    }
    for p in peers:
        try:
            px, py, keys = align(obs, fetch(p))
            row["comparables"].append({
                "series": p, "name": NAMES.get(p, p),
                "corr": pearson(px[-60:], py[-60:]),
                "window": 60, "n": min(len(keys), 60),
            })
        except Exception as exc:
            row["comparables"].append({"series": p, "name": NAMES.get(p, p),
                                       "corr": None, "window": 60, "n": 0,
                                       "code": err_code(exc)})
    return row


def cross(x_series, y_series, bucket):
    xa, ya, keys = align(fetch(x_series), fetch(y_series))
    if not keys:
        raise ValueError("no overlapping dates")
    groups = {}
    for x, y, k in zip(xa, ya, keys):
        b = k[:4] if bucket == "year" else k[:7]
        g = groups.setdefault(b, {"x": [], "y": []})
        g["x"].append(x)
        g["y"].append(y)
    rows = []
    for b in sorted(groups):
        g = groups[b]
        rows.append({
            "bucket": b, "n": len(g["x"]),
            "x_mean": sum(g["x"]) / len(g["x"]),
            "y_mean": sum(g["y"]) / len(g["y"]),
            "corr": pearson(g["x"], g["y"]) if len(g["x"]) >= 5 else None,
        })
    return {
        "x": x_series, "y": y_series, "bucket": bucket,
        "overall_corr": pearson(xa, ya), "overall_n": len(keys),
        "groups": rows,
        "order": "按时间升序排列，非评价性排序",
    }


def basket(series_list):
    data = {}
    for s in series_list:
        data[s] = dict(fetch(s))
    keys = sorted(set.intersection(*[set(d) for d in data.values()]))
    if not keys:
        raise ValueError("no overlapping dates")
    matrix = []
    for a in series_list:
        row = []
        for b in series_list:
            xs = [data[a][k] for k in keys]
            ys = [data[b][k] for k in keys]
            row.append(pearson(xs, ys))
        matrix.append({"series": a, "corr": row})
    return {"series": series_list, "n": len(keys), "matrix": matrix}


def footer(extra, missing):
    lines = []
    for k, v in extra:
        lines.append("{}：{}".format(k, v))
    lines += [
        "数据源：{}（{}）".format(SOURCE_NAME, SOURCE_URL),
        "许可：{}".format(LICENSE),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：{}".format(LIMITS),
    ]
    return "\n".join(lines)


def f4(x):
    return "—" if x is None else "{:.4f}".format(x)


def main(argv=None):
    p = argparse.ArgumentParser(description="数据上下文与交叉统计（A-2 / A-3）")
    p.add_argument("--describe", metavar="SERIES")
    p.add_argument("--peers", default="", help="可比序列，逗号分隔")
    p.add_argument("--cross", metavar="X,Y")
    p.add_argument("--basket", metavar="S1,S2,...")
    p.add_argument("--bucket", default="year", choices=["year", "month"])
    p.add_argument("--window", type=int, default=250)
    p.add_argument("--json", action="store_true")
    p.add_argument("--version", action="version", version="market-data-hub " + VERSION)
    a = p.parse_args(argv)

    modes = [bool(a.describe), bool(a.cross), bool(a.basket)]
    if sum(modes) != 1:
        print("E_INPUT：--describe / --cross / --basket 三选一", file=sys.stderr)
        return 2
    if a.window < 30:
        print("E_INPUT：--window 不得小于 30", file=sys.stderr)
        return 2

    missing, payload = [], {}
    try:
        if a.describe:
            peers = [x.strip() for x in a.peers.split(",") if x.strip()]
            payload = {"mode": "describe", "data": describe(a.describe.strip(), a.window, peers),
                       "method_ids": ["M02", "M14", "M16"]}
        elif a.cross:
            parts = [x.strip() for x in a.cross.split(",") if x.strip()]
            if len(parts) != 2:
                print("E_INPUT：--cross 需要两个序列，如 DGS10,CPIAUCSL", file=sys.stderr)
                return 2
            payload = {"mode": "cross", "data": cross(parts[0], parts[1], a.bucket),
                       "method_ids": ["M15", "M16"]}
        else:
            parts = [x.strip() for x in a.basket.split(",") if x.strip()]
            if len(parts) < 2:
                print("E_INPUT：--basket 至少两个序列", file=sys.stderr)
                return 2
            payload = {"mode": "basket", "data": basket(parts), "method_ids": ["M16"]}
    except Exception as exc:
        missing.append({"key": a.describe or a.cross or a.basket,
                        "code": err_code(exc), "detail": type(exc).__name__})

    if a.json:
        print(json.dumps({
            "skill": "market-data-hub",
            "version": VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "data_date": datetime.now().strftime("%Y-%m-%d"),
            "rows": [] if not payload else [payload["data"]],
            "missing": missing,
            "mode": payload.get("mode"),
            "method_ids": payload.get("method_ids", []),
            "sources": [{"name": SOURCE_NAME, "url": SOURCE_URL, "license": LICENSE}],
            "limits": LIMITS,
        }, ensure_ascii=False, indent=2))
        return 0 if payload else 1

    if not payload:
        print("数据不可用：{}".format("、".join(m["key"] for m in missing)))
        return 1

    out = []
    if payload["mode"] == "describe":
        d = payload["data"]
        out.append("{} 数据上下文 · 数据日期 {}".format(d["name"], d["latest_date"]))
        out.append("")
        out.append("| 项 | 值 |")
        out.append("|---|---|")
        out.append("| 序列 | {} |".format(d["series"]))
        out.append("| 单位 | {} |".format(d["unit"]))
        out.append("| 频率 | {} |".format(d["frequency"]))
        out.append("| 样本区间 | {} → {}（n={}） |".format(
            d["range"]["start"], d["range"]["end"], d["range"]["n"]))
        out.append("| 最新值 | {} |".format(d["latest"]))
        dist = d["distribution"]
        for k in ("p05", "p25", "p50", "p75", "p95"):
            out.append("| {} 分位（{}期） | {} |".format(k.upper(), dist["window"], f4(dist[k])))
        out.append("| 最新值位置 | {} |".format(
            "—" if dist["latest_pctile"] is None else "{:.1f}%".format(dist["latest_pctile"] * 100)))
        if d["comparables"]:
            out.append("")
            out.append("| 可比序列 | 60期相关 | 样本量 |")
            out.append("|---|---|---|")
            for c in d["comparables"]:
                out.append("| {} | {} | {} |".format(c["name"], f4(c["corr"]), c["n"]))
        out.append("")
        out.append(footer([("方法ID", "M02 分位 / M14 分布五数 / M16 相关")], []))
        print("\n".join(out))
        return 0

    if payload["mode"] == "cross":
        d = payload["data"]
        out.append("{} × {} 分组统计（按 {}） · 数据日期 {}".format(
            NAMES.get(d["x"], d["x"]), NAMES.get(d["y"], d["y"]),
            "年" if d["bucket"] == "year" else "月", datetime.now().strftime("%Y-%m-%d")))
        out.append("")
        out.append("| 分组 | 样本量 | {} 均值 | {} 均值 | 组内相关 |".format(d["x"], d["y"]))
        out.append("|---|---|---|---|---|")
        for g in d["groups"]:
            out.append("| {} | {} | {} | {} | {} |".format(
                g["bucket"], g["n"], f4(g["x_mean"]), f4(g["y_mean"]), f4(g["corr"])))
        out.append("")
        out.append("整体相关：{}（n={}）".format(f4(d["overall_corr"]), d["overall_n"]))
        out.append("排序说明：{}".format(d["order"]))
        out.append("")
        out.append(footer([("方法ID", "M15 分组统计 / M16 Pearson 相关")], []))
        print("\n".join(out))
        return 0

    d = payload["data"]
    out.append("相关矩阵 · 对齐样本 n={} · 数据日期 {}".format(
        d["n"], datetime.now().strftime("%Y-%m-%d")))
    out.append("")
    out.append("| 序列 | " + " | ".join(d["series"]) + " |")
    out.append("|---" * (len(d["series"]) + 1) + "|")
    for row in d["matrix"]:
        out.append("| {} | {} |".format(
            row["series"], " | ".join(f4(x) for x in row["corr"])))
    out.append("")
    out.append(footer([("方法ID", "M16 Pearson 相关")], []))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
