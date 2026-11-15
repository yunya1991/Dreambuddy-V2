"""Odaily 星球日报快讯 → canonical EventRecord 适配器。

断链修复：`odaily_newsflash` 采集器（BaseCollector）只写入 PG `records` 表，
未进入 `events.jsonl` 规范事件链路，导致 39 金融语义系统产物（hot_news /
news_digest）零条星球日报内容。本适配器把 DataRecord 映射为 EventRecord，
由 `collect_events.py` 统一落盘。

设计（用户要求"不必那么复杂数据处理"）：
  · 复用现有 `_classify.classify` 把中文快讯映射到 §3.1 的 13 种 type；
  · 标的优先取采集器已提取的 `raw.tickers_hit`（BTC/ETH/SOL…），不足时
    回退 classify 的 symbols，兜底 ["CRYPTO"]；
  · 时间取 `raw.publishTimestamp`（毫秒），缺失则用 `record.timestamp`；
  · 正文（description 去 HTML）写入 bodies.jsonl，事件只存 body_ref，
    让新闻检索可命中快讯正文。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from data_center.collectors.news.odaily_newsflash import OdailyNewsflashCollector
from data_center.collectors.tradefin._classify import classify
from data_center.collectors.tradefin._result import CollectResult
from data_center.collectors.tradefin._util import html_to_text, now_utc, to_iso
from data_center.events.body_store import body_ref, make_body_id

logger = logging.getLogger(__name__)

SOURCE = "odaily_newsflash"
DEFAULT_SYMBOL = "CRYPTO"

_collector = OdailyNewsflashCollector()


def _publish_iso(record) -> str:
    """从 DataRecord 取发布时间（毫秒时间戳 → UTC ISO8601）。"""
    raw = record.raw or {}
    ms = raw.get("publishTimestamp") or 0
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        ms = 0
    if ms > 0:
        return to_iso(datetime.fromtimestamp(ms / 1000, tz=timezone.utc))
    # 兜底：采集时间（record.timestamp 已是带时区 ISO）
    ts = str(record.timestamp or "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return to_iso(dt)
    except (ValueError, TypeError):
        return to_iso(now_utc())


def _symbols(record, title: str, text: str) -> list[str]:
    """tickers_hit → classify symbols → ['CRYPTO'] 三级兜底。"""
    raw = record.raw or {}
    ticks = raw.get("tickers_hit") or []
    if isinstance(ticks, str):
        ticks = [t for t in ticks.split(",") if t]
    out: list[str] = []
    for t in ticks or []:
        t = str(t).strip().upper()
        if t and t not in out:
            out.append(t)
    # 补 classify 抓到的宏观龙头（BTC/ETH/XAU…）
    _, cls_syms = classify(title, text)
    for s in cls_syms:
        if s not in out:
            out.append(s)
    return out or [DEFAULT_SYMBOL]


def fetch(days: int = 30, now: datetime | None = None) -> CollectResult:
    """拉取最新 odaily 快讯，过滤 days 窗口，输出 EventRecord + 正文。

    注：odaily 公开接口一次最多返回 20 条最新快讯，`days` 仅用于窗口过滤，
    历史回填需在云端多次执行或调大 limit。
    """
    now = now or now_utc()
    start = now - timedelta(days=days)
    fetched_at = to_iso(now)
    result = CollectResult()

    try:
        records = _collector.fetch({})
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN：单源失败不影响其他源
        logger.warning("[odaily] 采集失败：%s", e)
        return result

    for rec in records:
        raw = rec.raw or {}
        title = str(raw.get("title") or "").strip()
        desc = html_to_text(str(raw.get("description") or ""))
        text = desc or title
        if not title:
            title = (desc or "")[:60]
        if not title:
            continue

        published = _publish_iso(rec)
        try:
            ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if not (start <= ts <= now):
            continue

        type_, _ = classify(title, text)
        symbols = _symbols(rec, title, text)
        # newsUrl 可能为空（外部源链接缺失），用 odaily 源 ID 构造兜底 URL，
        # 满足 body_store 的 url 必填契约。
        od_id = (rec.metrics or {}).get("od_source_id") or 0
        url = str(raw.get("newsUrl") or "").strip() or f"https://www.odaily.news/newsflash/{od_id}"
        body_id = make_body_id(SOURCE, url, published)
        confidence = float((rec.metrics or {}).get("od_policy_sentiment_0_1", 0.5) or 0.5)
        confidence = max(0.0, min(1.0, confidence))

        result.events.append(
            {
                "type": type_,
                "subtype": "newsflash",
                "symbols": symbols,
                "sector": "crypto",
                "event_time": published,
                "available_at": published,
                "source": SOURCE,
                "source_url": url,
                "title": title,
                "body_ref": body_ref(body_id),
                "confidence": confidence,
                "quality": "B",
            }
        )
        result.bodies.append(
            {
                "id": body_id,
                "source": SOURCE,
                "url": url,
                "title": title,
                "content_text": text,
                "date_published": published,
                "fetched_at": fetched_at,
                "fetch_ok": True,
                "lang": "zh",
            }
        )
    return result


def guard_stats() -> dict:
    """collect_events.py 会调用各源的 guard_stats；odaily 未接入 SourceGuard，返回空。"""
    return {}
