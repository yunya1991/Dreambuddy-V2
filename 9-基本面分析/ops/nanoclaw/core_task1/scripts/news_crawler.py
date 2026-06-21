#!/usr/bin/env python3
"""
新闻爬虫模块 - 获取可验证时间戳的最新新闻数据

支持（主源/辅源）：
- 加密：Odaily 星球日报快讯（主源，JSON-LD 列表 + 逐条详情页时间戳）
- 宏观：华尔街见闻（主源，api-one.wallstcn.com 信息流 + 详情页）
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _http_get(url: str, timeout: int = 20) -> Tuple[int, bytes, str]:
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    last_err = None
    for i in range(3):
        try:
            if HAS_REQUESTS:
                resp = requests.get(url, headers=headers, timeout=timeout)
                return resp.status_code, resp.content, resp.headers.get("content-type", "")

            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as r:
                status = getattr(r, "status", 200)
                content_type = r.headers.get("content-type", "")
                body = r.read()
                return status, body, content_type
        except IncompleteRead as e:
            last_err = e
        except Exception as e:
            last_err = e
        time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"http get failed after retries: {url}, err={last_err}")


def _http_get_text(url: str, timeout: int = 20) -> str:
    status, body, _ = _http_get(url, timeout=timeout)
    if status >= 400:
        raise RuntimeError(f"http {status}: {url}")
    return body.decode("utf-8", errors="replace")


def _http_get_json(url: str, timeout: int = 20) -> Any:
    status, body, _ = _http_get(url, timeout=timeout)
    if status >= 400:
        raise RuntimeError(f"http {status}: {url}")
    return json.loads(body.decode("utf-8", errors="replace"))


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clamp(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _parse_json_ld_blocks(html: str) -> List[Any]:
    blocks: List[Any] = []
    for m in re.finditer(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except Exception:
            continue
    return blocks


def _parse_odaily_list_urls(html: str, limit: int) -> List[Tuple[str, str]]:
    urls: List[Tuple[str, str]] = []
    for block in _parse_json_ld_blocks(html):
        graph = None
        if isinstance(block, dict) and "@graph" in block:
            graph = block.get("@graph")
        if not isinstance(graph, list):
            continue

        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "ItemList":
                continue
            items = node.get("itemListElement")
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                url = it.get("url")
                name = it.get("name") or ""
                if url:
                    urls.append((str(url), str(name)))
    dedup: Dict[str, str] = {}
    for url, name in urls:
        dedup[url] = name
    return list(dedup.items())[:limit]


def _parse_odaily_detail(html: str) -> Tuple[Optional[str], str]:
    published = None
    m = re.search(
        r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )
    if m:
        published = m.group(1).strip()

    desc = ""
    m2 = re.search(
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
        html,
        flags=re.IGNORECASE,
    )
    if m2:
        desc = unescape(m2.group(1)).strip()
    return published, desc


def _odaily_category_guess(title: str) -> str:
    t = title or ""
    if re.search(r"(链上|地址|净流入|净流出|链上|矿工|gas|手续费|活跃|交易所余额|稳定币)", t, re.IGNORECASE):
        return "onchain_data"
    if re.search(r"(观点|认为|称|表示|发文|指出)", t):
        return "kols_view"
    return "project_update"


def _parse_rss_items(xml_text: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    out: List[Dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        published_at = None
        if pub:
            try:
                published_at = parsedate_to_datetime(pub).astimezone(timezone.utc)
            except Exception:
                published_at = None
        out.append(
            {
                "title": title,
                "source_url": link,
                "published_at_dt": published_at,
                "summary": _clamp(_strip_html(desc), 240),
            }
        )
    return out


def _fetch_rss(url: str, timeout: int = 20) -> str:
    return _http_get_text(url, timeout=timeout)


def _fetch_jinse_lives(hours: int, limit: int, fetched_at: str) -> List[Dict[str, Any]]:
    now = _now_utc()
    cutoff = now - timedelta(hours=hours)

    url = "https://api.jinse.cn/noah/v2/lives"
    params = f"?limit={max(50, limit * 3)}&reading=false&source=web&flag=up&id=0&category=0"

    items: List[Dict[str, Any]] = []
    try:
        resp = _http_get_json(url + params, timeout=20)
        payload = resp.get("data") if isinstance(resp, dict) else None
        if payload is None:
            payload = resp
        groups = payload.get("list") if isinstance(payload, dict) else None
        if not isinstance(groups, list):
            return []

        for g in groups:
            lives = g.get("lives") if isinstance(g, dict) else None
            if not isinstance(lives, list):
                continue
            for it in lives:
                if not isinstance(it, dict):
                    continue
                created_at = it.get("created_at")
                if created_at is None:
                    continue
                try:
                    published_dt = datetime.fromtimestamp(int(created_at), tz=timezone.utc)
                except Exception:
                    continue
                if published_dt < cutoff:
                    continue

                title = str(it.get("content_prefix") or "").strip()
                content = str(it.get("content") or "").strip()
                summary = _clamp(_strip_html(content), 240) if content else ""
                if not title:
                    title = _clamp(summary, 120) if summary else "无标题"

                live_id = it.get("id")
                source_url = f"https://jinse.cn/lives/{live_id}.html" if live_id else "https://jinse.cn/lives"

                risk_flags: List[str] = []
                if not summary:
                    risk_flags.append("正文缺失，仅标题级信息")

                items.append(
                    {
                        "title": title,
                        "category": _odaily_category_guess(title),
                        "source_url": source_url,
                        "published_at": _iso(published_dt),
                        "fetched_at": fetched_at,
                        "summary": summary or "正文缺失，仅标题级信息",
                        "source_confidence": "medium",
                        "impact_horizon": "T1",
                        "cross_market_map": "",
                        "risk_flags": risk_flags,
                        "market_impact": "",
                        "source": "jinse",
                    }
                )
    except Exception:
        return []

    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[:limit]


def _fetch_crypto_aux_sources(hours: int, limit: int, fetched_at: str) -> List[Dict[str, Any]]:
    now = _now_utc()
    cutoff = now - timedelta(hours=hours)
    feeds = [
        ("blockbeats", "https://api.theblockbeats.news/v2/rss/newsflash"),
        ("blockbeats", "https://api.theblockbeats.news/v2/rss/article"),
        ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
        ("cointelegraph", "https://cointelegraph.com/rss"),
    ]

    items: List[Dict[str, Any]] = []
    for source, url in feeds:
        try:
            xml_text = _fetch_rss(url, timeout=20)
            for it in _parse_rss_items(xml_text):
                published_dt = it.get("published_at_dt")
                if not isinstance(published_dt, datetime):
                    continue
                if published_dt < cutoff:
                    continue
                title = it.get("title") or ""
                summary = it.get("summary") or ""
                risk_flags: List[str] = []
                if not summary:
                    risk_flags.append("正文缺失，仅标题级信息")
                items.append(
                    {
                        "title": title,
                        "category": _odaily_category_guess(title),
                        "source_url": it.get("source_url") or "",
                        "published_at": _iso(published_dt),
                        "fetched_at": fetched_at,
                        "summary": summary or "正文缺失，仅标题级信息",
                        "source_confidence": "medium",
                        "impact_horizon": "T1",
                        "cross_market_map": "",
                        "risk_flags": risk_flags,
                        "market_impact": "",
                        "source": source,
                    }
                )
        except Exception:
            continue

    try:
        items.extend(_fetch_jinse_lives(hours=hours, limit=limit, fetched_at=fetched_at))
    except Exception:
        pass

    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[:limit]


def _fetch_macro_aux_sources(hours: int, limit: int, fetched_at: str) -> List[Dict[str, Any]]:
    now = _now_utc()
    cutoff = now - timedelta(hours=hours)
    feeds = [
        ("federal_reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
        ("marketwatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ]
    items: List[Dict[str, Any]] = []
    for source, url in feeds:
        try:
            xml_text = _fetch_rss(url, timeout=20)
            for it in _parse_rss_items(xml_text):
                published_dt = it.get("published_at_dt")
                if not isinstance(published_dt, datetime):
                    continue
                if published_dt < cutoff:
                    continue
                title = it.get("title") or ""
                key_fact = it.get("summary") or "正文缺失，仅标题级信息"
                topic = _wscn_topic_guess(title, key_fact)
                expectation = _extract_macro_expectation_fields(title, key_fact, topic)
                items.append(
                    {
                        "title": title,
                        "topic": topic,
                        "source_url": it.get("source_url") or "",
                        "published_at": _iso(published_dt),
                        "fetched_at": fetched_at,
                        "key_fact": key_fact,
                        "source_confidence": "low" if source == "marketwatch" else "medium",
                        "impact_horizon": "T1",
                        "cross_market_map": "",
                        "risk_flags": ["正文缺失，仅标题级信息"] if "正文缺失" in key_fact else [],
                        "market_impact": "",
                        "source": source,
                        **expectation,
                    }
                )
        except Exception:
            continue
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return items[:limit]


def _degraded_crypto_placeholder(fetched_at: str) -> List[Dict[str, Any]]:
    return [
        {
            "title": "加密主源与备源不可用",
            "category": "project_update",
            "source_url": "https://www.odaily.news/zh-CN/newsflash",
            "published_at": fetched_at,
            "fetched_at": fetched_at,
            "summary": "正文缺失，仅标题级信息",
            "source_confidence": "low",
            "impact_horizon": "T0",
            "cross_market_map": "",
            "risk_flags": ["数据不可复核", "正文缺失，仅标题级信息", "主备源不可用"],
            "market_impact": "",
            "source": "degraded",
        }
    ]


def _degraded_macro_placeholder(fetched_at: str) -> List[Dict[str, Any]]:
    return [
        {
            "title": "宏观主源与备源不可用",
            "topic": "market_analysis",
            "source_url": "https://wallstreetcn.com/search?q=%E6%97%A9%E9%A4%90",
            "published_at": fetched_at,
            "fetched_at": fetched_at,
            "key_fact": "正文缺失，仅标题级信息",
            "source_confidence": "low",
            "impact_horizon": "T0",
            "cross_market_map": "",
            "risk_flags": ["数据不可复核", "正文缺失，仅标题级信息", "主备源不可用"],
            "market_impact": "",
            "source": "degraded",
        }
    ]


def fetch_odaily_newsflash(limit: int = 20, hours: int = 24, include_aux: bool = True) -> List[Dict[str, Any]]:
    """
    获取 Odaily 星球日报快讯
    方案：列表页 JSON-LD 拿 URL → 逐条详情页拿 published_time（UTC）与 description
    """
    now = _now_utc()
    cutoff = now - timedelta(hours=hours)
    fetched_at = _iso(now)

    try:
        list_url = "https://www.odaily.news/zh-CN/newsflash"
        list_html = _http_get_text(list_url)
        url_pairs = _parse_odaily_list_urls(list_html, limit=limit * 2)

        items: List[Dict[str, Any]] = []
        for url, title in url_pairs:
            try:
                detail_html = _http_get_text(url)
                published_iso, desc = _parse_odaily_detail(detail_html)
                if not published_iso:
                    continue
                published_dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
                if published_dt < cutoff:
                    continue
                items.append(
                    {
                        "title": title or _clamp(desc.split(" - ")[0], 120),
                        "category": _odaily_category_guess(title),
                        "source_url": url,
                        "published_at": _iso(published_dt),
                        "fetched_at": fetched_at,
                        "summary": _clamp(desc, 240) if desc else "正文缺失，仅标题级信息",
                        "source_confidence": "medium",
                        "impact_horizon": "T1",
                        "cross_market_map": "",
                        "risk_flags": ["正文缺失，仅标题级信息"] if not desc else [],
                        "market_impact": "",
                        "source": "odaily",
                    }
                )
                if len(items) >= limit:
                    break
            except Exception:
                continue

        if not items:
            raise RuntimeError("no odaily items parsed")
        if include_aux:
            aux = _fetch_crypto_aux_sources(hours=hours, limit=limit, fetched_at=fetched_at)
            mention: Dict[str, int] = {}
            for it in items + aux:
                title = (it.get("title") or "").strip()
                if not title:
                    continue
                mention[title] = mention.get(title, 0) + 1
            combined = items + aux
            for it in combined:
                title = (it.get("title") or "").strip()
                it["mention_count"] = mention.get(title, 1)
            combined.sort(key=lambda x: x.get("published_at", ""), reverse=True)
            return combined[:limit]
        return items
    except Exception as e:
        print(f"[WARN] Odaily 抓取失败：{e}，执行降级策略（不使用 mock）")
        aux = _fetch_crypto_aux_sources(hours=hours, limit=limit, fetched_at=fetched_at)
        if aux:
            return aux[:limit]
        return _degraded_crypto_placeholder(fetched_at)[:limit]


def _wscn_topic_guess(title: str, text: str) -> str:
    t = (title or "") + " " + (text or "")
    if re.search(r"(美联储|FOMC|鲍威尔|点阵图|降息|加息|议息|会议纪要)", t, re.IGNORECASE):
        return "fed"
    if re.search(r"(CPI|PPI|NFP|非农|失业率|就业|零售|PMI|GDP|通胀)", t, re.IGNORECASE):
        return "us_data"
    if re.search(r"(伊朗|以色列|中东|俄乌|乌克兰|制裁|地缘|战争)", t):
        return "geopolitics"
    if re.search(r"(关税|财政部|监管|法案|政策|白宫|特朗普|拜登|国会|SEC)", t, re.IGNORECASE):
        return "us_policy"
    return "market_analysis"


def _extract_macro_expectation_fields(title: str, text: str, topic: str) -> Dict[str, Any]:
    full = f"{title or ''} {text or ''}"
    result: Dict[str, Any] = {
        "actual_value": None,
        "expected_value": None,
        "surprise": None,
        "implied_surprise_score": None,
        "expectation_source": "none",
    }
    value_pattern = re.findall(r"(-?\d+(?:\.\d+)?)\s*(%|BP|bp|万|亿)?", full, flags=re.IGNORECASE)
    parsed_values: List[float] = []
    for raw_v, unit in value_pattern:
        try:
            num = float(raw_v)
        except Exception:
            continue
        u = (unit or "").lower()
        if u in {"bp"}:
            num = num / 100.0
        parsed_values.append(num)
    if len(parsed_values) >= 2:
        result["actual_value"] = parsed_values[0]
        result["expected_value"] = parsed_values[1]
        result["surprise"] = parsed_values[0] - parsed_values[1]
        result["expectation_source"] = "explicit_numeric"
        return result

    hawkish_words = ["超预期", "高于预期", "强于预期", "高企", "顽固", "上行", "偏热"]
    dovish_words = ["低于预期", "不及预期", "弱于预期", "回落", "降温", "放缓", "下行"]
    neutral_words = ["符合预期", "基本符合", "大致符合", "持平", "如期"]
    score = 0.0
    for w in hawkish_words:
        if w in full:
            score += 1.0
    for w in dovish_words:
        if w in full:
            score -= 1.0
    for w in neutral_words:
        if w in full:
            score = 0.0
            break
    if topic in {"geopolitics", "us_policy", "market_analysis"}:
        if "风险偏好" in full or "上涨" in full:
            score += 0.5
        if "避险" in full or "承压" in full:
            score -= 0.5
    if abs(score) > 0:
        result["implied_surprise_score"] = max(-1.0, min(1.0, score / 2.0))
        result["surprise"] = result["implied_surprise_score"]
        result["expectation_source"] = "implied_text"
    return result


def _fetch_wscn_information_flow(channel: str, limit: int) -> List[Dict[str, Any]]:
    api = f"https://api-one.wallstcn.com/apiv1/content/information-flow?channel={channel}&accept=article&limit={limit}"
    data = _http_get_json(api)
    if not isinstance(data, dict) or data.get("code") != 20000:
        raise RuntimeError(f"wscn api error: {data.get('code')}")
    items = data.get("data", {}).get("items", [])
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in items:
        res = (it or {}).get("resource") or {}
        out.append(
            {
                "resource_type": (it or {}).get("resource_type"),
                "id": res.get("id"),
                "uri": res.get("uri"),
                "title": res.get("title") or res.get("content_text") or "",
                "content_text": res.get("content_text") or "",
                "content_short": res.get("content_short") or "",
                "display_time": res.get("display_time"),
                "categories": res.get("categories") or [],
            }
        )
    return out


def _fetch_wscn_article_detail(article_id: int) -> Dict[str, Any]:
    url = f"https://api-one.wallstcn.com/apiv1/content/articles/{article_id}?extract=0"
    data = _http_get_json(url)
    if not isinstance(data, dict) or data.get("code") != 20000:
        raise RuntimeError(f"wscn detail error: {data.get('code')}")
    return data.get("data", {}) or {}


def fetch_wallstreetcn_breakfast(limit: int = 10, hours: int = 24) -> List[Dict[str, Any]]:
    """
    获取华尔街见闻早餐和宏观新闻
    """
    now = _now_utc()
    cutoff = now - timedelta(hours=hours)
    fetched_at = _iso(now)

    try:
        primary = _fetch_wscn_information_flow("breakfast-channel", limit=60)
        secondary = _fetch_wscn_information_flow("global-channel", limit=120)

        mention_map: Dict[str, int] = {}
        for row in primary + secondary:
            title = (row.get("title") or "").strip()
            if not title:
                continue
            mention_map[title] = mention_map.get(title, 0) + 1

        picked: List[Dict[str, Any]] = []
        for row in primary:
            ts = row.get("display_time")
            if not isinstance(ts, int):
                continue
            published_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            if published_dt < cutoff:
                continue

            rid = row.get("id")
            uri = row.get("uri") or ""
            title = row.get("title") or ""
            text = row.get("content_text") or row.get("content_short") or ""

            key_fact = _clamp(text, 260)
            if row.get("resource_type") == "article" and isinstance(rid, int):
                try:
                    detail = _fetch_wscn_article_detail(rid)
                    title = detail.get("title") or title
                    raw_html = detail.get("content") or ""
                    key_fact = _clamp(_strip_html(raw_html), 280) or key_fact
                    uri = detail.get("uri") or uri
                except Exception:
                    pass

            topic = _wscn_topic_guess(title, key_fact)
            expectation = _extract_macro_expectation_fields(title, key_fact, topic)
            picked.append(
                {
                    "title": title,
                    "topic": topic,
                    "source_url": uri,
                    "published_at": _iso(published_dt),
                    "fetched_at": fetched_at,
                    "key_fact": key_fact,
                    "source_confidence": "medium",
                    "impact_horizon": "T1",
                    "cross_market_map": "",
                    "risk_flags": [],
                    "market_impact": "",
                    "mention_count": mention_map.get(title, 1),
                    "source": "wallstreetcn",
                    **expectation,
                }
            )

            if len(picked) >= limit:
                break

        if not picked:
            raise RuntimeError("no wscn items parsed")
        return picked
    except Exception as e:
        print(f"[WARN] 华尔街见闻抓取失败：{e}，执行降级策略（不使用 mock）")
        aux = _fetch_macro_aux_sources(hours=hours, limit=limit, fetched_at=fetched_at)
        if aux:
            return aux[:limit]
        return _degraded_macro_placeholder(fetched_at)[:limit]


def main():
    """测试爬虫功能"""
    print("=== 新闻爬虫测试 ===\n")

    print("【Odaily 星球日报】")
    crypto_news = fetch_odaily_newsflash(limit=5)
    for i, item in enumerate(crypto_news[:3], 1):
        print(f"  {i}. {item['title']}")
        print(f"     可信度：{item['source_confidence']}, 时效：{item['impact_horizon']}")

    print("\n【华尔街见闻】")
    macro_news = fetch_wallstreetcn_breakfast(limit=6)
    for i, item in enumerate(macro_news[:3], 1):
        print(f"  {i}. {item['title']}")
        print(f"     类别：{item['topic']}, 可信度：{item['source_confidence']}")

    print("\n=== 测试完成 ===")

    return {
        "crypto_news": crypto_news,
        "macro_news": macro_news
    }


if __name__ == "__main__":
    main()
