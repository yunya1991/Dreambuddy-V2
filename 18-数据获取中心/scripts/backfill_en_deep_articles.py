#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""英文源深度文章采集：4 个英文加密媒体 RSS → 正文抓取 → C1 剔除 → 增量合并。

源：CoinDesk / The Block / Bitcoin Magazine / Cointelegraph（RSS 全部实测可达）
产出：backfill/en_deep_articles/contents.jsonl（本轮）+ contents_all.jsonl（累积库，按 link 去重）

FAIL-OPEN：单源失败不影响其余源；正文抓取失败保留标题+摘要。
用法：python3 scripts/backfill_en_deep_articles.py [--per-source 25]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

import feedparser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_center.processing.ad_filter import filter_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_en_deep")

OUT_DIR = ROOT / "backfill" / "en_deep_articles"
SOURCES = {
    "bitcoinmagazine": "https://bitcoinmagazine.com/feed",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
    "newsbtc": "https://www.newsbtc.com/feed/",
    "bitcoinist": "https://bitcoinist.com/feed/",
}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
SLEEP_S = 1.0


class _TextExtractor(HTMLParser):
    """极简 HTML 正文提取：<p> 段落文本拼接。"""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._in_p = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip += 1
        elif tag == "p":
            self._in_p = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self._skip:
            self._skip -= 1
        elif tag == "p":
            self._in_p = False

    def handle_data(self, data):
        if self._skip == 0 and data.strip():
            self.parts.append(data.strip())


def fetch_html_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    p = _TextExtractor()
    p.feed(html)
    return "\n".join(p.parts)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text).strip()


def collect_source(name: str, url: str, per_source: int) -> list[dict]:
    try:
        parsed = feedparser.parse(url)
        entries = parsed.entries[:per_source]
    except Exception as e:
        logger.warning("%s RSS 拉取失败: %s", name, e)
        return []
    rows: list[dict] = []
    for e in entries:
        link = e.get("link", "")
        title = e.get("title", "")
        summary = strip_html(e.get("summary", ""))
        published = e.get("published", "")
        content_text = ""
        if link:
            try:
                content_text = fetch_html_text(link)
                time.sleep(SLEEP_S)
            except Exception as ex:
                logger.warning("%s 正文抓取失败 %s: %s", name, link, ex)
        rows.append(
            {
                "id": link,
                "source_name": name,
                "title": title,
                "summary": summary,
                "content_text": content_text,
                "content_len": len(content_text),
                "date_published": published,
                "link": link,
            }
        )
    logger.info("%s 采集 %d 篇", name, len(rows))
    return rows


def merge_cumulative(rows: list[dict]) -> None:
    dst = OUT_DIR / "contents_all.jsonl"
    existing: dict[str, dict] = {}
    if dst.exists():
        for line in dst.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                existing[r["id"]] = r
    n_new = 0
    for r in rows:
        if r["id"] not in existing:
            existing[r["id"]] = r
            n_new += 1
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in existing.values()) + "\n",
        encoding="utf-8",
    )
    tmp.replace(dst)
    logger.info(
        "累积库合并：原有 %d，本轮新增 %d，当前 %d", len(existing) - n_new, n_new, len(existing)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-source", type=int, default=25)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for name, url in SOURCES.items():
        rows.extend(collect_source(name, url, args.per_source))
    if not rows:
        logger.warning("全部源均无产出，跳过落盘")
        return 0
    decisions = filter_batch(rows, audit_path=str(OUT_DIR / "c1_audit.jsonl"))
    for r, d in zip(rows, decisions, strict=False):
        r["c1_decision"] = d["decision"]
        r["c1_rules"] = d["hit_rules"]
    (OUT_DIR / "contents.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    merge_cumulative(rows)
    ok = [r for r in rows if r["content_len"] > 200]
    report = {
        "per_source": args.per_source,
        "crawled": len(rows),
        "content_ok": len(ok),
        "c1_drop": sum(1 for r in rows if r.get("c1_decision") == "drop"),
        "by_source": {n: sum(1 for r in rows if r["source_name"] == n) for n in SOURCES},
    }
    (OUT_DIR / "report_en_deep.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("报告: %s", json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
