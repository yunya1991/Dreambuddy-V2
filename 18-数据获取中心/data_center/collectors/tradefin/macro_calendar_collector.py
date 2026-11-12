"""MacroCalendarCollector — BLS 官方发布日历（CPI / 非农 / PPI）（SPEC §3.2 P0-C）。

数据源：https://www.bls.gov/schedule/{year}/home.htm（官方年度日历，含已发布与计划发布）

事件建模：每个发布日 08:30 ET（BLS 固定发布时间）→ UTC，作为 `available_at`。
本采集器只负责"事件何时发生、何时可得"；actual/consensus 留空（surprise=null），
按 §3.3 纪律：拿不到可记录的市场预期时，该事件只进 E 层描述，不进因子计算。
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data_center.collectors.tradefin._http import get_text

logger = logging.getLogger(__name__)

SOURCE = "macro_calendar"
SCHEDULE_URL = "https://www.bls.gov/schedule/{year}/home.htm"
ET = ZoneInfo("America/New_York")
RELEASE_HOUR_ET = 8
RELEASE_MINUTE_ET = 30

SYMBOLS = ["US500", "TLT", "XAU", "BTC"]

# 只采这三类；按名称前缀匹配（BLS 文案形如 "Consumer Price Index for October 2026"）
RELEASE_TYPES = (
    ("Consumer Price Index", "cpi", "cpi"),
    ("Employment Situation", "nfp", "employment_situation"),
    ("Producer Price Index", "macro_other", "ppi"),
)

_ROW_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s+"
    r"(.+)$"
)


def extract_rows(page_html: str) -> list[str]:
    """抽取 <tr> 行文本（去标签、反转义、压缩空白）。"""
    rows = []
    for raw in re.findall(r"<tr[^>]*>(.*?)</tr>", page_html, re.S):
        text = re.sub(r"<[^>]+>", " ", raw)
        text = html_lib.unescape(text).replace("\xa0", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            rows.append(text)
    return rows


def classify_release(release: str) -> tuple[str, str] | None:
    for prefix, type_, subtype in RELEASE_TYPES:
        if release.startswith(prefix):
            return type_, subtype
    return None


def rows_to_events(
    rows: list[str], *, days: int = 30, ahead_days: int = 0, now: datetime | None = None
) -> list[dict]:
    """ahead_days>0 时额外纳入未来已公布日程（经济日历用，非事件流默认行为）。"""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    end = now + timedelta(days=ahead_days)

    events: list[dict] = []
    for row in rows:
        m = _ROW_RE.match(row)
        if not m:
            continue
        date_str, time_str, release = m.group(1), m.group(2), m.group(3).strip()
        kind = classify_release(release)
        if not kind:
            continue
        type_, subtype = kind

        try:
            d = datetime.strptime(date_str, "%B %d, %Y").date()
            t = datetime.strptime(re.sub(r"\s+", " ", time_str), "%I:%M %p").time()
            ts = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=ET).astimezone(
                timezone.utc
            )
        except ValueError:
            continue
        if not (start <= ts <= end):
            continue

        iso = ts.isoformat().replace("+00:00", "Z")
        events.append(
            {
                "type": type_,
                "subtype": subtype,
                "symbols": list(SYMBOLS),
                "sector": "macro",
                "event_time": iso,
                "available_at": iso,
                "source": SOURCE,
                "source_url": SCHEDULE_URL.format(year=d.year),
                "title": release,
                "confidence": 1.0,
                "quality": "A",
            }
        )
    return events


def fetch(days: int = 30, ahead_days: int = 0, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    years = sorted(
        {(now - timedelta(days=days)).year, now.year, (now + timedelta(days=ahead_days)).year}
    )
    events: list[dict] = []
    for year in years:
        try:
            page = get_text(SCHEDULE_URL.format(year=year))
        except Exception as e:  # noqa: BLE001
            logger.warning("[macro_calendar] %d 日历抓取失败，FAIL-OPEN：%s", year, e)
            continue
        events.extend(rows_to_events(extract_rows(page), days=days, ahead_days=ahead_days, now=now))
    return events
