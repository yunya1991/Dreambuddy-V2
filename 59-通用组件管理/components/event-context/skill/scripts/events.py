#!/usr/bin/env python3
"""官方源事件拉取与归一（SEC 披露 / SEC 公告 / 美联储声明）。

用法:
    python3 events.py --subject AAPL --since 30
    python3 events.py --subject AAPL --types 8-K,10-Q --json
    python3 events.py --feed sec-press --since 7
    python3 events.py --feed fed-all --since 7 --json
    python3 events.py --version

数据源（均为政府/监管机构公开文件，Public Domain）:
    https://data.sec.gov/submissions/CIK##########.json
    https://www.sec.gov/news/pressreleases.rss
    https://www.federalreserve.gov/feeds/press_all.xml

输出: 归一后的一级事实（不含正文、不含解读）。仅使用标准库。
"""

import argparse
import hashlib
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import cloud

VERSION = "1.0.0"
UA = {"User-Agent": "event-context/1.0 (research; contact: ops@neodrm.com)", "Accept": "*/*"}
LIMITS = "仅提供已发生事实与来源，不含影响判断、方向判断或建议。"
LICENSE = "Public Domain"

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

FEEDS = {
    "sec-press": {
        "url": "https://www.sec.gov/news/pressreleases.rss",
        "source": "SEC 新闻发布",
        "subject": {"name": "U.S. Securities and Exchange Commission"},
        "type": "press-release",
        "license": "Public Domain",
    },
    "fed-all": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "source": "美联储新闻发布",
        "subject": {"name": "Board of Governors of the Federal Reserve System"},
        "type": "press-release",
        "license": "Public Domain",
    },
}

_TICKERS = {}


class UnknownTicker(Exception):
    pass


ROUTE = "auto"
LAST_ROUTE = "local"


def set_endpoint(value):
    global ROUTE
    ROUTE = cloud.route(value)
    return ROUTE


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


def fetch_bytes(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):  # 最多重试 2 次，指数退避应对 TLS 抖动
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.8 * (attempt + 1))


def get_json(url):
    return json.loads(fetch_bytes(url).decode("utf-8", errors="replace"))


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
    key = ticker.strip().upper()
    m = load_tickers()
    if key not in m:
        raise UnknownTicker(key)
    return m[key]


def make_id(source_key, etype, key):
    raw = "{}:{}:{}".format(source_key, etype, key).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def iso_now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def cutoff_date(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def company_events(ticker, days, types):
    global LAST_ROUTE
    if ROUTE != "local":
        payload = cloud.call(
            "events", {"subject": ticker, "since": days, "types": ",".join(types or [])}
        )
        if payload and payload.get("rows") is not None:
            LAST_ROUTE = "cloud"
            return payload.get("rows", []), None
        if ROUTE == "cloud":
            raise ValueError("云端通道不可用")
    cik, name = resolve(ticker)
    data = get_json(SUBMISSIONS_URL.format(cik=cik))
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    since = cutoff_date(days)
    want = set(types) if types else None
    rows = []
    for i, form in enumerate(forms):
        if want and form not in want:
            continue
        fdate = recent["filingDate"][i]
        if fdate < since:
            continue
        acc = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]
        items = recent.get("items", [None] * len(forms))[i] or ""
        facts = ["提交 {}".format(form)]
        if items:
            facts.append("事项编号 {}".format(items))
        rdate = recent.get("reportDate", [""] * len(forms))[i]
        if rdate:
            facts.append("报告期 {}".format(rdate))
        rows.append(
            {
                "event_id": make_id("sec-submissions", form, acc),
                "source_key": "sec-submissions",
                "time": fdate,
                "source": "SEC EDGAR",
                "type": form,
                "subject": {"ticker": ticker.upper(), "cik": cik, "name": data.get("name", name)},
                "facts": facts,
                "url": "https://www.sec.gov/Archives/edgar/data/{}/{}/{}".format(
                    int(cik), acc.replace("-", ""), doc
                ),
                "license": LICENSE,
            }
        )
    return rows, data


def feed_events(feed, days):
    global LAST_ROUTE
    if ROUTE != "local":
        payload = cloud.call("events", {"feed": feed, "since": days})
        if payload and payload.get("rows") is not None:
            LAST_ROUTE = "cloud"
            return payload.get("rows", [])
        if ROUTE == "cloud":
            raise ValueError("云端通道不可用")
    meta = FEEDS[feed]
    raw = fetch_bytes(meta["url"])
    text = raw.decode("utf-8-sig", errors="replace")
    root = ET.fromstring(text)
    items = root.findall(".//item")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if not title or not link:
            continue
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt < since:
            continue
        guid = it.findtext("guid") or link
        rows.append(
            {
                "event_id": make_id(feed, meta["type"], guid),
                "source_key": feed,
                "time": dt.astimezone().isoformat(timespec="seconds"),
                "source": meta["source"],
                "type": meta["type"],
                "subject": meta["subject"],
                "facts": ["标题：{}".format(title[:80])],
                "title": title,
                "url": link,
                "license": meta["license"],
            }
        )
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows


def render(rows, title, missing, channel="local"):
    out = [title, "", "| 时间 | 来源 | 类型 | 主体 | 事实要点 |", "|---|---|---|---|---|"]
    for r in rows:
        subj = r["subject"].get("ticker") or r["subject"].get("name") or "—"
        facts = "；".join(r["facts"])[:120]
        out.append(
            "| {} | {} | {} | {} | {} |".format(r["time"], r["source"], r["type"], subj, facts)
        )
    out += [
        "",
        "方法ID：E01 事件归一",
        "数据源：SEC EDGAR / 美联储（均为官方公开文件）｜ 通道：{}".format(
            "云端" if channel == "cloud" else "本地直连"
        ),
        "许可：Public Domain",
        "缺失：{}".format("、".join(missing) if missing else "无"),
        "说明：{}".format(LIMITS),
    ]
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="官方源事件归一（E01）")
    p.add_argument("--subject", default=None, help="股票代码，如 AAPL")
    p.add_argument("--feed", default=None, choices=sorted(FEEDS))
    p.add_argument("--types", default="", help="表单类型，逗号分隔，如 8-K,10-Q")
    p.add_argument("--since", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--endpoint",
        default="auto",
        choices=["auto", "cloud", "local"],
        help="数据通道：auto 云端优先并自动回退本地",
    )
    p.add_argument("--version", action="version", version="event-context " + VERSION)
    a = p.parse_args(argv)

    set_endpoint(a.endpoint)

    if bool(a.subject) == bool(a.feed):
        print("E_INPUT：--subject 与 --feed 二选一", file=sys.stderr)
        return 2
    if a.since < 1 or a.since > 3650:
        print("E_INPUT：--since 取值 1–3650 天", file=sys.stderr)
        return 2

    rows, missing, title = [], [], ""
    types = [x.strip() for x in a.types.split(",") if x.strip()]

    try:
        if a.subject:
            rows, _ = company_events(a.subject, a.since, types)
            title = "{} 事件清单 · 近 {} 天 · 生成于 {}".format(
                a.subject.upper(), a.since, datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            if not rows:
                missing.append(
                    {"key": a.subject, "code": "E_EMPTY", "detail": "no events in window"}
                )
        else:
            rows = feed_events(a.feed, a.since)
            title = "{} 事件清单 · 近 {} 天 · 生成于 {}".format(
                FEEDS[a.feed]["source"], a.since, datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            if not rows:
                missing.append({"key": a.feed, "code": "E_EMPTY", "detail": "no events in window"})
    except UnknownTicker:
        print(
            "E_INPUT：未收录的 ticker「{}」，请使用美股代码，如 AAPL / MSFT".format(a.subject),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        missing.append(
            {"key": a.subject or a.feed, "code": err_code(exc), "detail": type(exc).__name__}
        )

    if a.json:
        print(
            json.dumps(
                {
                    "skill": "event-context",
                    "version": VERSION,
                    "generated_at": iso_now(),
                    "data_date": rows[0]["time"] if rows else None,
                    "data_route": LAST_ROUTE,
                    "scope": {"subject": a.subject, "feed": a.feed, "since_days": a.since},
                    "rows": rows,
                    "missing": missing,
                    "method_ids": ["E01"],
                    "sources": [
                        {
                            "name": "SEC EDGAR",
                            "url": "https://www.sec.gov/edgar/",
                            "license": LICENSE,
                        },
                        {
                            "name": "Federal Reserve",
                            "url": "https://www.federalreserve.gov/feeds/",
                            "license": LICENSE,
                        },
                    ],
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
    print(render(rows, title, [m["key"] for m in missing], LAST_ROUTE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
