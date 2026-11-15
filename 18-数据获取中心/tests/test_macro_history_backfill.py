"""宏观事件历史回填测试：官方页面解析 + 无窗口回填 + 幂等 + FAIL-OPEN。

背景：`mm_events` 仅 16 行、`events.jsonl` 只保留滚动窗口，导致 F19–F23 事件研究
无法满足 ≥30 事件门禁。本模块从美联储官方日历（含历史年页面）与 BLS 年度发布
日历（直连被 403 时回退 Wayback 归档）回填 2015 年起的事件日期。
"""

from __future__ import annotations

import json
from datetime import timezone

from data_center.collectors.tradefin import macro_history_backfill as mh

_FOMC_HIST_SNIPPET = """
<div class="panel panel-default">
  <div class="panel-heading"><h4><a id="2015">2015 FOMC Meetings</a></h4></div>
  <div class="panel-body">
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month"><strong>January</strong></div>
      <div class="fomc-meeting__date">27-28</div>
      <a href="/monetarypolicy/monetary20150128a.htm">Statement</a>
    </div>
    <div class="row fomc-meeting">
      <div class="fomc-meeting__month"><strong>July</strong></div>
      <div class="fomc-meeting__date">28-29</div>
      <a href="/monetarypolicy/monetary20150729a.htm">Statement</a>
    </div>
  </div>
</div>
"""

_BLS_ROWS = [
    "Friday, January 08, 2016 08:30 AM Employment Situation for December 2015",
    "Wednesday, January 20, 2016 08:30 AM Consumer Price Index for December 2015",
    "Friday, July 15, 2016 08:30 AM Consumer Price Index for June 2016",
    "Friday, January 15, 2016 08:30 AM Producer Price Index for December 2015",
    "Tuesday, January 12, 2016 10:00 AM Job Openings and Labor Turnover Survey for November 2015",
]


def test_parse_fomc_statement_dates_applies_new_york_dst():
    dates = mh.parse_fomc_statement_dates(_FOMC_HIST_SNIPPET)
    assert [d.strftime("%Y-%m-%d %H:%M") for d in dates] == [
        "2015-01-28 19:00",  # EST
        "2015-07-29 18:00",  # EDT
    ]
    assert all(d.tzinfo == timezone.utc for d in dates)


def test_build_fomc_events_satisfies_event_contract():
    dates = mh.parse_fomc_statement_dates(_FOMC_HIST_SNIPPET)
    events = mh.build_fomc_events(dates)
    assert len(events) == 2
    first = events[0]
    assert first["type"] == "fomc"
    assert first["source"] == "fed_calendar"
    assert first["event_time"] == first["available_at"] == "2015-01-28T19:00:00Z"
    assert first["symbols"] and first["quality"] == "A"
    assert first["title"] == "FOMC statement 2015-01-28"


def test_parse_bls_release_rows_maps_types_without_window_filter():
    events = mh.parse_bls_release_rows(_BLS_ROWS)
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    assert sorted(by_type) == ["cpi", "macro_other", "nfp"]
    assert len(by_type["cpi"]) == 2
    assert by_type["cpi"][0]["event_time"] == "2016-01-20T13:30:00Z"  # EST
    assert by_type["cpi"][1]["event_time"] == "2016-07-15T12:30:00Z"  # EDT
    assert by_type["nfp"][0]["event_time"] == "2016-01-08T13:30:00Z"
    assert all(e["source"] == "macro_calendar" for e in events)


def test_backfill_appends_idempotently_and_reports_failed_years(tmp_path):
    out = tmp_path / "macro_calendar_history.jsonl"
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        if "fomc" in url:
            return _FOMC_HIST_SNIPPET
        year = int(url.split("/schedule/")[1].split("/")[0])
        if year <= 2016:
            return "<table><tr><td>" + "</td></tr><tr><td>".join(_BLS_ROWS) + "</td></tr></table>"
        raise RuntimeError("upstream 403")

    first = mh.backfill(start_year=2015, end_year=2017, output=out, fetch=fetch)
    assert first["ok"] is True
    assert first["appended"] >= 3
    assert first["failed_years"] == ["bls:2017"]
    assert first["by_type"]["fomc"] >= 1 and first["by_type"]["cpi"] == 2

    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {r["event_id"] for r in rows} == {r["event_id"] for r in rows}
    assert all(r["available_at"] and r["source"] for r in rows)

    second = mh.backfill(start_year=2015, end_year=2017, output=out, fetch=fetch)
    assert second["appended"] == 0
    assert second["skipped"] == first["appended"]
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(rows)


def test_backfill_falls_back_to_wayback_when_bls_blocks(tmp_path):
    out = tmp_path / "macro_calendar_history.jsonl"

    def fetch(url: str) -> str:
        if url.startswith("https://www.bls.gov/"):
            raise RuntimeError("Access Denied (403)")
        if "web.archive.org" in url:
            return "<table><tr><td>" + "</td></tr><tr><td>".join(_BLS_ROWS) + "</td></tr></table>"
        return _FOMC_HIST_SNIPPET

    result = mh.backfill(start_year=2015, end_year=2016, output=out, fetch=fetch)
    assert result["ok"] is True
    assert result["wayback_years"] == [2015, 2016]
    assert result["failed_years"] == []
    assert result["by_type"]["nfp"] == 1
