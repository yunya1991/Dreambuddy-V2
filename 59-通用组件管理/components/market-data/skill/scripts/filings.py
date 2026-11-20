#!/usr/bin/env python3
"""D2 美股公司披露：SEC EDGAR 公开数据，输出结构化披露事实。

用法:
    python3 filings.py --ticker AAPL
    python3 filings.py --ticker AAPL --form 8-K --limit 10
    python3 filings.py --ticker AAPL --facts Revenues,NetIncomeLoss --json
    python3 filings.py --version

数据源:
    https://www.sec.gov/files/company_tickers.json      ticker -> CIK
    https://data.sec.gov/submissions/CIK##########.json 披露清单
    https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json 结构化字段
    美国 SEC EDGAR，公共领域（Public Domain）。

输出: Markdown 表格 + 五行尾注；--json 输出结构化结果。仅使用标准库。
"""

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import cloud

VERSION = "1.0.0"
UA = {"User-Agent": "market-data-hub/1.0 (research; contact: ops@neodrm.com)"}
LICENSE = "Public Domain"
SOURCE_NAME = "SEC EDGAR"
SOURCE_URL = "https://www.sec.gov/edgar/"
LIMITS = "仅提供已披露文件与字段的原始记录，不含解读、判断或建议。"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
UNIT_PREF = ["USD", "shares", "USD/shares"]

_TICKERS = {}


class UnknownTicker(Exception):
    pass


def err_code(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return "E_HTTP_{}".format(exc.code)
    if isinstance(exc, ssl.SSLError):
        return "E_TLS"
    if isinstance(exc, (socket.timeout, TimeoutError, urllib.error.URLError)):
        return "E_NET"
    if isinstance(exc, StopIteration):
        return "E_SCHEMA"
    if isinstance(exc, ValueError):
        return "E_EMPTY"
    return "E_SCHEMA"


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):  # 最多重试 2 次，指数退避应对 TLS 抖动
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))


def load_tickers():
    global _TICKERS
    if _TICKERS:
        return _TICKERS
    raw = get_json(TICKERS_URL)
    for item in raw.values():
        _TICKERS[str(item["ticker"]).upper()] = (str(item["cik_str"]).zfill(10), item["title"])
    if not _TICKERS:
        raise ValueError("empty ticker map")
    return _TICKERS


def resolve(ticker):
    m = load_tickers()
    key = ticker.strip().upper()
    if key not in m:
        raise UnknownTicker(key)
    return m[key]


def list_filings(cik, form, limit):
    data = get_json(SUBMISSIONS_URL.format(cik=cik))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    rows = []
    for i, f in enumerate(forms):
        if form and f != form:
            continue
        acc = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]
        rows.append(
            {
                "form": f,
                "filing_date": recent["filingDate"][i],
                "report_date": (
                    recent["reportDate"][i] if i < len(recent.get("reportDate", [])) else None
                ),
                "items": recent.get("items", [None] * len(forms))[i],
                "accession": acc,
                "url": "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(
                    int(cik), acc.replace("-", ""), doc
                ),
                "n": 1,
            }
        )
        if len(rows) >= limit:
            break
    return data.get("name"), data.get("sicDescription"), rows


def pick_unit(concept_units):
    for u in UNIT_PREF:
        if u in concept_units and concept_units[u]:
            return u, concept_units[u]
    for u, vals in concept_units.items():
        if vals:
            return u, vals
    raise ValueError("no unit values")


def dedupe(entries):
    seen = {}
    for e in entries:
        if "end" not in e or "val" not in e:
            continue
        prev = seen.get(e["end"])
        if prev is None or str(e.get("filed", "")) > str(prev.get("filed", "")):
            seen[e["end"]] = e
    return sorted(seen.values(), key=lambda x: x["end"])


def pick_periods(entries):
    """按最新期间判定口径（年度 / 季度），避免把年报总额与季度值混在一列。"""
    deduped = dedupe(entries)
    if not deduped:
        return [], "unknown"
    max_end = deduped[-1]["end"]
    quarterly = [e for e in deduped if e.get("fp") in ("Q1", "Q2", "Q3", "Q4")]
    annual = [e for e in deduped if e.get("fp") == "FY" or e.get("form") == "10-K"]
    latest_is_q = any(
        e["end"] == max_end and e.get("fp") in ("Q1", "Q2", "Q3", "Q4") for e in deduped
    )
    if latest_is_q and quarterly:
        return quarterly, "quarterly"
    if annual:
        return annual, "annual"
    return deduped, "mixed"


def facts_rows(gaap, concepts):
    rows = []
    for c in concepts:
        concept = gaap.get(c)
        if not concept:
            raise KeyError("concept not found: " + c)
        unit, entries = pick_unit(concept.get("units", {}))
        periods, period_type = pick_periods(entries)
        if not periods:
            raise ValueError("empty periods: " + c)
        last = periods[-1]
        yoy = None
        fp, fy = last.get("fp"), last.get("fy")
        if isinstance(fy, int):
            for p in periods:
                same = (
                    (p.get("fp") == fp)
                    if period_type == "quarterly"
                    else (p.get("form") == "10-K" or p.get("fp") == "FY")
                )
                if same and p.get("fy") == fy - 1 and p.get("val"):
                    yoy = last["val"] / p["val"] - 1
                    break
        age_days = (datetime.now() - datetime.strptime(last["end"], "%Y-%m-%d")).days
        rows.append(
            {
                "concept": c,
                "label": concept.get("label", c),
                "unit": unit,
                "latest": last["val"],
                "period_end": last["end"],
                "period_type": period_type,
                "fy": fy,
                "fp": fp,
                "form": last.get("form"),
                "yoy": yoy,
                "stale": age_days > 540,
                "n": len(periods),
                "recent": [{"end": p["end"], "val": p["val"]} for p in periods[-5:]],
            }
        )
    return rows


def fmt_pct(x):
    return "—" if x is None else "{:+.2%}".format(x)


def render_filings(ticker, name, sic, rows, missing, data_date, channel="local"):
    lines = [
        "{} 披露事实 · 数据日期 {} · 生成于 {}".format(
            ticker.upper(), data_date, datetime.now().strftime("%Y-%m-%d %H:%M")
        ),
        "",
        "| 披露日 | 表单 | 报告期 | 事项 | 样本量 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {} | {} | {} | {} | 1 |".format(
                r["filing_date"], r["form"], r["report_date"] or "—", r["items"] or "—"
            )
        )
    lines += [
        "",
        "主体：{}（SIC：{}）".format(name or ticker.upper(), sic or "—"),
        "方法ID：M19 披露清单归一",
        "数据源：{}（{}）｜ 通道：{}".format(
            SOURCE_NAME, SOURCE_URL, "云端" if channel == "cloud" else "本地直连"
        ),
        "许可：{}".format(LICENSE),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：{}".format(LIMITS),
    ]
    return "\n".join(lines)


def render_facts(ticker, rows, missing, data_date, channel="local"):
    lines = [
        "{} 披露字段 · 数据日期 {} · 生成于 {}".format(
            ticker.upper(), data_date, datetime.now().strftime("%Y-%m-%d %H:%M")
        ),
        "",
        "| 字段 | 最新值 | 单位 | 截止期 | 口径 | 财年/季度 | 同比 | 样本量 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {} | {} | {} | {}{} | {} | {} {} | {} | {} |".format(
                r["label"],
                r["latest"],
                r["unit"],
                r["period_end"],
                "（陈旧）" if r.get("stale") else "",
                "年度" if r.get("period_type") == "annual" else "季度",
                r["fy"] or "—",
                r["fp"] or "—",
                fmt_pct(r["yoy"]),
                r["n"],
            )
        )
    lines += [
        "",
        "方法ID：M18 披露字段同比",
        "数据源：{}（{}）｜ 通道：{}".format(
            SOURCE_NAME, SOURCE_URL, "云端" if channel == "cloud" else "本地直连"
        ),
        "许可：{}".format(LICENSE),
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：{}".format(LIMITS),
    ]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description="美股公司披露事实（D2）")
    p.add_argument("--ticker", required=True)
    p.add_argument("--form", default=None, help="表单类型，如 8-K / 10-K / 10-Q")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--facts", default=None, help="us-gaap 字段，逗号分隔")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--endpoint",
        default="auto",
        choices=["auto", "cloud", "local"],
        help="数据通道：auto 云端优先并自动回退本地",
    )
    p.add_argument("--version", action="version", version="market-data-hub " + VERSION)
    a = p.parse_args(argv)

    if a.limit < 1 or a.limit > 100:
        print("E_INPUT：--limit 取值 1–100", file=sys.stderr)
        return 2

    rows, missing, name, sic, cik = [], [], None, None, None
    data_date, used = None, "local"
    mode = "facts" if a.facts else "filings"

    if a.endpoint != "local":
        payload = cloud.call(
            "filings", {"ticker": a.ticker, "form": a.form, "limit": a.limit, "facts": a.facts}
        )
        if payload:
            rows = payload.get("rows", [])
            missing = payload.get("missing", [])
            ent = payload.get("entity") or {}
            name, sic, cik = ent.get("name"), ent.get("sic"), ent.get("cik")
            data_date = payload.get("data_date")
            mode = payload.get("mode", mode)
            used = "cloud"
        elif a.endpoint == "cloud":
            print("数据不可用：云端通道不可用（{}）".format(cloud.describe()))
            return 1

    if used == "local":
        try:
            cik, name = resolve(a.ticker)
        except UnknownTicker:
            print(
                "E_INPUT：未收录的 ticker「{}」，请使用美股代码，如 AAPL / MSFT".format(a.ticker),
                file=sys.stderr,
            )
            return 2
        except Exception as exc:
            missing.append({"key": a.ticker, "code": err_code(exc), "detail": type(exc).__name__})
            rows = []

    if used == "local" and not missing:
        if mode == "filings":
            try:
                name, sic, rows = list_filings(cik, a.form, a.limit)
                data_date = rows[0]["filing_date"] if rows else None
                if not rows:
                    missing.append({"key": a.ticker, "code": "E_EMPTY", "detail": "no filings"})
            except Exception as exc:
                missing.append(
                    {"key": a.ticker, "code": err_code(exc), "detail": type(exc).__name__}
                )
        else:
            concepts = [x.strip() for x in a.facts.split(",") if x.strip()]
            try:
                gaap = get_json(FACTS_URL.format(cik=cik)).get("facts", {}).get("us-gaap", {})
                if not gaap:
                    raise KeyError("us-gaap facts missing")
            except Exception as exc:
                missing.append(
                    {"key": a.ticker, "code": err_code(exc), "detail": type(exc).__name__}
                )
                gaap = None
            for c in (concepts if gaap is not None else []):
                try:
                    rows.extend(facts_rows(gaap, [c]))
                except Exception as exc:
                    missing.append({"key": c, "code": err_code(exc), "detail": type(exc).__name__})
            if rows:
                info = get_json(SUBMISSIONS_URL.format(cik=cik))
                name, sic = info.get("name"), info.get("sicDescription")
                data_date = max(r["period_end"] for r in rows)

    if a.json:
        print(
            json.dumps(
                {
                    "skill": "market-data-hub",
                    "version": VERSION,
                    "module": "D2",
                    "mode": mode,
                    "ticker": a.ticker.upper(),
                    "entity": {"name": name, "sic": sic, "cik": cik if not missing else None},
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "data_date": data_date,
                    "data_route": used,
                    "rows": rows,
                    "missing": missing,
                    "method_ids": ["M18"] if mode == "facts" else ["M19"],
                    "sources": [{"name": SOURCE_NAME, "url": SOURCE_URL, "license": LICENSE}],
                    "limits": LIMITS,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if rows else 1

    if not rows:
        print("数据不可用：{}".format("、".join(m["key"] for m in missing)))
        return 1
    if mode == "facts":
        print(render_facts(a.ticker, rows, [m["key"] for m in missing], data_date, used))
    else:
        print(
            render_filings(a.ticker, name, sic, rows, [m["key"] for m in missing], data_date, used)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
