"""宏观事件历史回填 — FOMC 决议日 + BLS CPI/非农/PPI 发布日（2015 起）。

背景：`events.jsonl` 只保留滚动窗口、`sync_events_to_dal` 只同步 [-60d,+90d]，
`mm_events` 长期只有十几行，F19–F23 事件研究（D-E04/D-E09）因此无法满足 ≥30
事件门禁。本模块一次性回填历史事件日期，写入独立的历史事件流：

    data_center/events/macro_calendar_history.jsonl

数据源（2026-11-15 实测）：
  - FOMC：federalreserve.gov 官方日历。2021+ 用 `fomccalendars.htm`，
    2015–2020 用 `fomchistorical{year}.htm`；决议日从声明链接
    `monetary{YYYYMMDD}a.htm` 提取，比解析月份文本稳。
  - BLS：`bls.gov/schedule/{year}/home.htm`。直连可能 403（实测本机被拒），
    因此失败时回退 Wayback 归档快照，仍失败记入 `failed_years`（FAIL-OPEN）。

纪律：`available_at` = `event_time`（日程计划时间本就公开，不构成前视）；
类型只用 §3.1 枚举；幂等键沿用 `EventStore` 的 `sha1(source|symbols|event_time|type)`。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from data_center.collectors.tradefin.fed_calendar_collector import (
    CALENDAR_URL as FOMC_CURRENT_URL,
)
from data_center.collectors.tradefin.fed_calendar_collector import (
    SYMBOLS as FED_SYMBOLS,
)
from data_center.collectors.tradefin.macro_calendar_collector import (
    SYMBOLS as MACRO_SYMBOLS,
)
from data_center.collectors.tradefin.macro_calendar_collector import (
    classify_release,
    extract_rows,
)
from data_center.events.store import append_events

logger = logging.getLogger(__name__)

FOMC_HISTORICAL_URL = "https://www.federalreserve.gov/monetarypolicy/fomchistorical{year}.htm"
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/{year}/home.htm"
WAYBACK_URL = "https://web.archive.org/web/{stamp}/https://www.bls.gov/schedule/{year}/home.htm"

HISTORY_PATH = Path(__file__).resolve().parents[2] / "events" / "macro_calendar_history.jsonl"

ET = ZoneInfo("America/New_York")
STATEMENT_HOUR_ET = 14  # FOMC 声明发布 14:00 ET

_STATEMENT_RE = re.compile(r"monetary(\d{8})a\.htm")
_ROW_RE = re.compile(
    r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"([A-Z][a-z]+ \d{1,2}, \d{4})\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s+"
    r"(.+)$"
)


def parse_fomc_statement_dates(page_html: str) -> list[datetime]:
    """从官方日历页提取决议时刻（会议最后一天 14:00 ET → UTC），去重升序。"""
    found: dict[int, datetime] = {}
    for stamp in _STATEMENT_RE.findall(page_html or ""):
        try:
            day = datetime.strptime(stamp, "%Y%m%d")
        except ValueError:
            continue
        local = datetime(day.year, day.month, day.day, STATEMENT_HOUR_ET, tzinfo=ET)
        found[int(stamp)] = local.astimezone(timezone.utc)
    return [found[k] for k in sorted(found)]


def build_fomc_events(dates: list[datetime]) -> list[dict]:
    return [
        {
            "type": "fomc",
            "subtype": "statement",
            "symbols": list(FED_SYMBOLS),
            "sector": "macro",
            "event_time": d.isoformat().replace("+00:00", "Z"),
            "available_at": d.isoformat().replace("+00:00", "Z"),
            "source": "fed_calendar",
            "source_url": FOMC_CURRENT_URL,
            "title": f"FOMC statement {d.strftime('%Y-%m-%d')}",
            "confidence": 1.0,
            "quality": "A",
        }
        for d in dates
    ]


def parse_bls_release_rows(rows: list[str]) -> list[dict]:
    """BLS 年度日历行 → 事件（不做时间窗过滤，供历史回填使用）。"""
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
        iso = ts.isoformat().replace("+00:00", "Z")
        events.append(
            {
                "type": type_,
                "subtype": subtype,
                "symbols": list(MACRO_SYMBOLS),
                "sector": "macro",
                "event_time": iso,
                "available_at": iso,
                "source": "macro_calendar",
                "source_url": BLS_SCHEDULE_URL.format(year=d.year),
                "title": release,
                "confidence": 1.0,
                "quality": "A",
            }
        )
    return events


def _default_fetch(url: str) -> str:
    from data_center.collectors.tradefin._http import get_text

    return get_text(url)


def _wayback_url(year: int) -> str:
    return WAYBACK_URL.format(stamp=f"{year}0701", year=year)


def _dedupe(events: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for e in events:
        key = (e["source"], e["type"], e["event_time"], tuple(sorted(e["symbols"])))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def backfill(
    start_year: int = 2015,
    end_year: int | None = None,
    output: str | Path = HISTORY_PATH,
    fetch=None,
) -> dict:
    """回填历史宏观事件；单源失败不影响其他源，返回汇总。"""
    fetch = fetch or _default_fetch
    end_year = end_year or datetime.now(timezone.utc).year
    events: list[dict] = []
    failed: list[str] = []
    wayback_years: list[int] = []

    fomc_dates: list[datetime] = []
    for year in range(start_year, min(end_year, 2020) + 1):
        try:
            html = fetch(FOMC_HISTORICAL_URL.format(year=year))
        except Exception as e:  # noqa: BLE001 — 单年失败不阻断
            logger.warning("[macro_history] FOMC %d 失败：%s", year, e)
            failed.append(f"fomc:{year}")
            continue
        fomc_dates.extend(d for d in parse_fomc_statement_dates(html) if d.year == year)
    if end_year >= 2021:
        try:
            html = fetch(FOMC_CURRENT_URL)
            fomc_dates.extend(
                d for d in parse_fomc_statement_dates(html) if start_year <= d.year <= end_year
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[macro_history] FOMC 当前日历失败：%s", e)
            failed.append("fomc:current")
    events.extend(build_fomc_events(sorted(set(fomc_dates))))

    for year in range(start_year, end_year + 1):
        html = None
        try:
            html = fetch(BLS_SCHEDULE_URL.format(year=year))
        except Exception as direct_err:  # noqa: BLE001
            try:
                html = fetch(_wayback_url(year))
                wayback_years.append(year)
            except Exception as wb_err:  # noqa: BLE001
                logger.warning("[macro_history] BLS %d 双源失败：%s / %s", year, direct_err, wb_err)
                failed.append(f"bls:{year}")
                continue
        events.extend(parse_bls_release_rows(extract_rows(html)))

    events = _dedupe(events)
    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for e in events:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1

    appended, skipped = append_events(events, path=output)
    return {
        "ok": True,
        "appended": appended,
        "skipped": skipped,
        "candidate_rows": len(events),
        "by_source": dict(sorted(by_source.items())),
        "by_type": dict(sorted(by_type.items())),
        "failed_years": failed,
        "wayback_years": wayback_years,
        "output": str(output),
    }
