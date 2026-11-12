"""FedCalendarCollector — FOMC 官方会议日历（SPEC §3.2 P0-C）。

数据源：https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm（官方，含 2021-2027）

事件建模：每个 FOMC 会议的最后一天 14:00 ET 发布声明。
`available_at` = 该发布时刻（计划时间公开可查，非前视）；`event_time` 同值。
预期/实际值（利率 surprise）不在本采集器范围 → surprise=null。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data_center.collectors.tradefin._http import get_text

logger = logging.getLogger(__name__)

SOURCE = "fed_calendar"
CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ET = ZoneInfo("America/New_York")
STATEMENT_HOUR_ET = 14  # 2:00 p.m. ET

SYMBOLS = ["US500", "TLT"]

_PANEL_RE = re.compile(
    r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a></h4>(.*?)(?=<div class="panel panel-default">|\Z)',
    re.S,
)
_MEETING_RE = re.compile(
    r"fomc-meeting__month[^>]*>\s*<strong>([A-Za-z]+)</strong>.*?"
    r"fomc-meeting__date[^>]*>\s*(\d{1,2}(?:\s*-\s*\d{1,2})?)\*?\s*</div>",
    re.S,
)


def parse_calendar(html: str) -> list[dict]:
    """解析会议面板 → [{year, month, last_day}]（月份用 1-12）。"""
    meetings: list[dict] = []
    for panel in _PANEL_RE.finditer(html):
        year = int(panel.group(1))
        body = panel.group(2)
        for m in _MEETING_RE.finditer(body):
            month_name, days = m.group(1), m.group(2)
            try:
                month = datetime.strptime(month_name, "%B").month
                last_day = int(re.split(r"[-\s]+", days.strip())[-1])
            except (ValueError, IndexError):
                continue
            meetings.append({"year": year, "month": month, "last_day": last_day})
    return meetings


def statement_time(year: int, month: int, day: int) -> datetime:
    """会议最后一天 14:00 ET → UTC。"""
    local = datetime(year, month, day, STATEMENT_HOUR_ET, 0, tzinfo=ET)
    return local.astimezone(timezone.utc)


def meetings_to_events(
    meetings: list[dict], *, days: int = 30, ahead_days: int = 0, now: datetime | None = None
) -> list[dict]:
    """ahead_days>0 时额外纳入未来已公布日程（经济日历用，非事件流默认行为）。"""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    end = now + timedelta(days=ahead_days)

    events: list[dict] = []
    for m in meetings:
        try:
            ts = statement_time(m["year"], m["month"], m["last_day"])
        except ValueError:
            continue
        if not (start <= ts <= end):
            continue
        iso = ts.isoformat().replace("+00:00", "Z")
        month_name = datetime(m["year"], m["month"], 1).strftime("%B")
        events.append(
            {
                "type": "fomc",
                "subtype": "statement",
                "symbols": list(SYMBOLS),
                "sector": "macro",
                "event_time": iso,
                "available_at": iso,
                "source": SOURCE,
                "source_url": CALENDAR_URL,
                "title": f"FOMC statement {month_name} {m['last_day']}, {m['year']}",
                "confidence": 1.0,
                "quality": "A",
            }
        )
    return events


def fetch(days: int = 30, ahead_days: int = 0, now: datetime | None = None) -> list[dict]:
    try:
        html = get_text(CALENDAR_URL)
    except Exception as e:  # noqa: BLE001
        logger.warning("[fed_calendar] 日历抓取失败，FAIL-OPEN：%s", e)
        return []
    return meetings_to_events(parse_calendar(html), days=days, ahead_days=ahead_days, now=now)
