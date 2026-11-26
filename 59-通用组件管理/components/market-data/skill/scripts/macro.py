#!/usr/bin/env python3
"""D1 海外宏观指标：从 FRED 公开 CSV 取数，输出可复核的统计事实。

用法:
    python3 macro.py --series DGS10,CPIAUCSL,UNRATE
    python3 macro.py --series DGS10 --window 250 --json
    python3 macro.py --series DGS10,CPIAUCSL,UNRATE --history 60 --json
    python3 macro.py --version

数据源:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>
    美国圣路易斯联储 FRED，公共领域（Public Domain），需标注来源。

输出: Markdown 表格 + 方法ID/来源/许可/缺失/说明；--json 输出结构化结果。
仅使用标准库。
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

import cloud

VERSION = "1.0.0"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
UA = {"User-Agent": "market-data-hub/1.0 (research; contact: ops@neodrm.com)"}
LICENSE = "Public Domain"
SOURCE_NAME = "FRED / Federal Reserve Bank of St. Louis"
SOURCE_URL = "https://fred.stlouisfed.org/"
LIMITS = "仅提供已发布数据的统计描述，不含方向判断、预测或建议。"
METHODS = ["M11", "M12", "M13"]

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
RATE_SERIES = {"DGS10", "DGS2", "DGS3MO", "FEDFUNDS", "UNRATE"}


def err_code(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "E_HTTP_{}".format(exc.code)
    if isinstance(exc, ssl.SSLError):
        return "E_TLS"
    if isinstance(exc, (socket.timeout, TimeoutError, urllib.error.URLError)):
        return "E_NET"
    if isinstance(exc, KeyError):
        return "E_SCHEMA"
    if isinstance(exc, ValueError):
        return "E_EMPTY"
    return "E_SCHEMA"


def fetch(series, timeout=25, attempts=3):
    req = urllib.request.Request(FRED.format(series), headers=UA)
    for attempt in range(max(1, attempts)):  # 最多重试 attempts-1 次，指数退避应对 TLS 抖动
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == attempts - 1:
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
            continue  # FRED 用 "." 表示缺失
    if not out:
        raise ValueError("no numeric observations")
    return out


def chg(values, k):
    if len(values) <= k:
        return None
    return values[-1] - values[-1 - k]


def pctile(values, window):
    sample = values[-window:]
    if len(sample) < window:
        return None
    return sum(1 for x in sample if x <= sample[-1]) / float(len(sample))


def vol(values, window=20):
    if len(values) < window + 1:
        return None
    rets = [
        math.log(values[i] / values[i - 1])
        for i in range(len(values) - window, len(values))
        if values[i - 1] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def build_history(obs, points):
    """最近 points 个观测的历史序列；不足 2 个点时返回 None。"""
    points = int(points or 0)
    if points <= 0 or len(obs) < 2:
        return None
    sample = obs[-min(points, 400) :]
    return {
        "dates": [d for d, _ in sample],
        "values": [v for _, v in sample],
        "points": len(sample),
    }


def build_row(series, obs, window, history=0):
    dates = [d for d, _ in obs]
    vals = [v for _, v in obs]
    n = len(vals)
    is_rate = series in RATE_SERIES
    p = pctile(vals, window)
    return {
        "series": series,
        "name": NAMES.get(series, series),
        "n": min(n, window) if p is not None else n,
        "observations": n,
        "date": dates[-1],
        "latest": vals[-1],
        "unit": "%" if is_rate else "index",
        "chg_1m_bp": (chg(vals, 21) * 100) if (is_rate and chg(vals, 21) is not None) else None,
        "chg_1m": None if is_rate else chg(vals, 21),
        "chg_3m_bp": (chg(vals, 63) * 100) if (is_rate and chg(vals, 63) is not None) else None,
        "chg_3m": None if is_rate else chg(vals, 63),
        "pctile": p,
        "pctile_n": min(n, window),
        "vol": vol(vals),
        "history": build_history(obs, history),
    }


def fmt(x, digits=2, suffix=""):
    return "—" if x is None else "{:.{}f}{}".format(x, digits, suffix)


def fmt_signed(x, digits=2, suffix=""):
    return "—" if x is None else "{:+.{}f}{}".format(x, digits, suffix)


def render(rows, missing, window, data_date, channel="local"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "海外宏观事实 · 数据日期 {} · 生成于 {}".format(data_date, now),
        "",
        "| 指标 | 最新值 | 1月变动 | 3月变动 | {}期分位 | 20期波动(年化) | 样本量 |".format(window),
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        c1 = fmt_signed(r["chg_1m_bp"], 1, "bp") if r["unit"] == "%" else fmt_signed(r["chg_1m"])
        c2 = fmt_signed(r["chg_3m_bp"], 1, "bp") if r["unit"] == "%" else fmt_signed(r["chg_3m"])
        p = (
            "—"
            if r["pctile"] is None
            else "{:.1f}% (n={})".format(r["pctile"] * 100, r["pctile_n"])
        )
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                r["name"],
                fmt(r["latest"]),
                c1,
                c2,
                p,
                "—" if r["vol"] is None else "{:.1f}%".format(r["vol"] * 100),
                r["observations"],
            )
        )
    lines += [
        "",
        "方法ID：M11 区间变动 / M12 序列分位 / M13 年化波动",
        "数据源：{}（{}）｜ 通道：{}".format(
            SOURCE_NAME, SOURCE_URL, "云端" if channel == "cloud" else "本地直连"
        ),
        "许可：{}".format(LICENSE),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：{}".format(LIMITS),
    ]
    return "\n".join(lines)


def _fill_history(rows, points):
    """云端行缺历史时用本地 FRED 补齐；失败静默降级，不影响原有统计字段。"""
    filled = 0
    for row in rows or []:
        if not isinstance(row, dict) or row.get("history"):
            if isinstance(row, dict) and row.get("history"):
                filled += 1
            continue
        series = str(row.get("series") or "").strip()
        if not series:
            continue
        try:
            payload = build_history(fetch(series, timeout=10, attempts=1), points)
        except Exception:  # noqa: BLE001 - 历史只是增强，失败保留分位降级
            continue
        if payload:
            row["history"] = payload
            filled += 1
    return filled


def main(argv=None):
    p = argparse.ArgumentParser(description="海外宏观事实（D1）")
    p.add_argument("--series", default="DGS10,CPIAUCSL,UNRATE")
    p.add_argument("--window", type=int, default=250)
    p.add_argument(
        "--history",
        type=int,
        nargs="?",
        const=60,
        default=0,
        metavar="N",
        help="附带最近 N 个观测的历史序列（不带值默认 60，最多 400）",
    )
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--endpoint",
        default="auto",
        choices=["auto", "cloud", "local"],
        help="数据通道：auto 云端优先并自动回退本地",
    )
    p.add_argument("--version", action="version", version="market-data-hub " + VERSION)
    a = p.parse_args(argv)

    if a.window < 30:
        print("E_INPUT：--window 不得小于 30", file=sys.stderr)
        return 2

    rows, missing, data_date, used = [], [], None, "local"
    history_route = "none"
    if a.endpoint != "local":
        params = {"series": a.series, "window": a.window}
        if a.history:
            params["history"] = a.history
        payload = cloud.call("macro", params)
        if payload:
            rows = payload.get("rows", [])
            missing = payload.get("missing", [])
            data_date = payload.get("data_date")
            used = "cloud"
            if a.history:
                filled = _fill_history(rows, a.history)
                history_route = (
                    "cloud" if filled == len(rows) and rows else ("local" if filled else "none")
                )
        elif a.endpoint == "cloud":
            print("数据不可用：云端通道不可用（{}）".format(cloud.describe()))
            return 1

    if used == "local":
        for s in [x.strip() for x in a.series.split(",") if x.strip()]:
            try:
                rows.append(build_row(s, fetch(s), a.window, a.history))
            except Exception as exc:
                missing.append({"key": s, "code": err_code(exc), "detail": type(exc).__name__})
        data_date = max([r["date"] for r in rows], default=None)
        history_route = "local" if a.history and any(r.get("history") for r in rows) else "none"

    if a.json:
        print(
            json.dumps(
                {
                    "skill": "market-data-hub",
                    "version": VERSION,
                    "module": "D1",
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "data_date": data_date,
                    "data_route": used,
                    "history_points": a.history,
                    "history_route": history_route,
                    "window": a.window,
                    "rows": rows,
                    "missing": missing,
                    "method_ids": METHODS,
                    "sources": [{"name": SOURCE_NAME, "url": SOURCE_URL, "license": LICENSE}],
                    "limits": LIMITS,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if rows else 1

    if not rows:
        print("数据不可用：全部序列获取失败（{}）".format("、".join(m["key"] for m in missing)))
        return 1
    print(render(rows, [m["key"] for m in missing], a.window, data_date, used))
    return 0


if __name__ == "__main__":
    sys.exit(main())
