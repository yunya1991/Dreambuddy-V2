"""Odaily 星球日报深度文章正文 Collector — 详情页二次爬取（P0 叙事原语素材前置）。

与 odaily_post 互补：
  - odaily_post：        /post/page 列表元数据（无正文）
  - odaily_post_content：/post/{id} 详情页 HTML → 正文纯文本

上游页面（实测 2026-11-09 /post/5213824）：
  GET https://www.odaily.news/post/{id}
    - 无鉴权；正文容器 <div id="post-content">，内部 <p>/<img> 标签
    - 页面含 application/ld+json（NewsArticle schema，有 datePublished，无 articleBody）
    - 正文抽取 = 容器内文本，段落间保留换行，HTML 实体反转义

契约（6 个扁平 metrics，前缀 odpc_）：
  odpc_source_id       int   文章 id
  odpc_fetch_ok        str   "true"/"false"（false 也出记录，失败可审计）
  odpc_content_len     int   正文纯文本字符数
  odpc_para_count      int   非空段落数
  odpc_content_sha1    str   正文 sha1[:12]（去重/校验）
  odpc_date_published  str   ld+json datePublished（缺省 ""）

raw：
  id / content_text / datePublished / url

fetch 参数：
  ids       list[int] 必填，文章 id 列表
  sleep_ms  int  请求间隔毫秒（默认 0，批量回填时建议 ≥500）

FAIL-OPEN：
  L1 网络/HTTP 异常 → 该 id 出 fetch_ok="false" 记录，不抛
  L2 单条解析异常 → 该 id fetch_ok="false"，不阻塞其他
"""

from __future__ import annotations

import hashlib
import logging
import re
import time

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger("data_center.collectors.news.odaily_post_content")

_DETAIL_URL = "https://www.odaily.news/post/{id}"
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}
_HTTP_TIMEOUT = 15
_LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _extract_date_published(html: str) -> str:
    """从 ld+json NewsArticle 提取 datePublished；失败返回 ""。"""
    import json

    for m in _LD_JSON_RE.finditer(html):
        try:
            d = json.loads(m.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and d.get("@type") == "NewsArticle":
            dp = d.get("datePublished")
            if dp:
                return str(dp)
    return ""


def _extract_content_text(html: str) -> str:
    """div#post-content → 纯文本。容器缺失返回 ""。"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    node = soup.find(id="post-content")
    if node is None:
        return ""
    # 段落级提取：每个 <p> 一行，去纯图片段
    lines: list[str] = []
    blocks = node.find_all("p") or [node]
    for p in blocks:
        t = p.get_text(separator=" ", strip=True)
        if t:
            lines.append(t)
    if not lines:
        # 兜底：容器整体文本
        t = node.get_text(separator="\n", strip=True)
        lines = [ln for ln in t.split("\n") if ln.strip()]
    return "\n".join(lines)


class OdailyPostContentCollector(BaseCollector):
    """Odaily 深度文章正文爬取器（news / odaily_post_content）。"""

    source = "odaily_post_content"
    category = "news"

    def is_available(self) -> bool:
        return True  # 公开页面，无 key

    def fetch(self, params: dict) -> list[DataRecord]:
        params = params or {}
        ids = params.get("ids") or []
        if isinstance(ids, int):
            ids = [ids]
        sleep_ms = int(params.get("sleep_ms", 0) or 0)

        recs: list[DataRecord] = []
        for i, raw_id in enumerate(ids):
            try:
                oid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if i > 0 and sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
            recs.append(self._fetch_one(oid))
        return recs

    def _fetch_one(self, oid: int) -> DataRecord:
        url = _DETAIL_URL.format(id=oid)
        html = ""
        fetch_ok = False
        try:
            resp = requests.get(url, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT)
            if resp.status_code == 200:
                html = resp.text
                fetch_ok = True
            else:
                logger.warning("[FAIL-OPEN] odaily content HTTP %s id=%s", resp.status_code, oid)
        except Exception as e:  # noqa: BLE003  FAIL-OPEN L1
            logger.warning(
                "[FAIL-OPEN L1] odaily content fetch 异常 id=%s %s: %s",
                oid,
                type(e).__name__,
                str(e)[:200],
            )

        content_text = ""
        date_published = ""
        if fetch_ok:
            try:
                content_text = _extract_content_text(html)
                date_published = _extract_date_published(html)
                if not content_text:
                    fetch_ok = False  # 容器缺失/空正文
            except Exception as e:  # noqa: BLE003  FAIL-OPEN L2
                logger.warning(
                    "[FAIL-OPEN L2] odaily content 解析异常 id=%s %s: %s",
                    oid,
                    type(e).__name__,
                    str(e)[:200],
                )
                content_text = ""
                fetch_ok = False

        rec = DataRecord(
            source="odaily_post_content",
            category="news",
            sub_category=f"post_content_{oid}",
            timestamp=self._now_iso(),
            metrics={
                "odpc_source_id": int(oid),
                "odpc_fetch_ok": "true" if fetch_ok else "false",
                "odpc_content_len": len(content_text),
                "odpc_para_count": len([ln for ln in content_text.split("\n") if ln.strip()]),
                "odpc_content_sha1": (
                    hashlib.sha1(content_text.encode("utf-8")).hexdigest()[:12]
                    if content_text
                    else ""
                ),
                "odpc_date_published": date_published,
            },
            events=[],
            timeseries=[],
            raw={
                "id": oid,
                "url": url,
                "content_text": content_text,
                "datePublished": date_published,
            },
        )
        try:
            validate_record(rec)
        except Exception as e:  # noqa: BLE003
            logger.warning("[FAIL-OPEN] odaily content 契约校验异常 id=%s: %s", oid, e)
        return rec

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
