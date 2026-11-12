"""P0-C 事件采集契约测试（SPEC §3.1 / §3.2 / §10.1）。

覆盖：EventRecord 契约、event_id 幂等、append-only、available_at 100%、
SEC Form→type 映射与窗口过滤、FOMC 日历解析与 ET→UTC、BLS 行解析。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from data_center.collectors.tradefin import (
    fed_calendar_collector as fed,
)
from data_center.collectors.tradefin import (
    macro_calendar_collector as mac,
)
from data_center.collectors.tradefin import (
    sec_edgar_collector as sec,
)
from data_center.events import store

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _event(**overrides) -> dict:
    base = {
        "type": "cpi",
        "symbols": ["US500"],
        "event_time": "2026-11-10T13:30:00Z",
        "available_at": "2026-11-10T13:30:00Z",
        "source": "macro_calendar",
        "title": "CPI test",
        "quality": "A",
    }
    base.update(overrides)
    return base


# ────────────────────────────── store 契约


def test_make_event_id_stable_and_16_hex():
    a = store.make_event_id("cpi", ["US500", "TLT"], "2026-11-10T13:30:00Z", "cpi")
    b = store.make_event_id("cpi", ["TLT", "US500"], "2026-11-10T13:30:00Z", "cpi")
    assert a == b and len(a) == 16
    assert store.make_event_id("cpi", ["US500"], "2026-11-10T13:30:00Z", "nfp") != a


def test_normalize_fills_defaults_and_trace_id():
    row = store.normalize_event(_event())
    assert row["event_id"] == row["trace_id"]
    assert row["type_source"] == "fin_env_spec"
    assert row["surprise"] is None and row["surprise_unit"] is None
    assert row["available_at"] == "2026-11-10T13:30:00Z"


@pytest.mark.parametrize(
    "patch",
    [
        {"available_at": None},
        {"event_time": None},
        {"type": "unknown_type"},
        {"quality": "D"},
        {"available_at": "2026-11-09T00:00:00Z"},  # 早于 event_time
        {"symbols": []},
        {"surprise_unit": "bp"},
    ],
)
def test_normalize_rejects_invalid(patch):
    with pytest.raises(store.EventContractError):
        store.normalize_event(_event(**patch))


def test_append_events_idempotent_and_append_only(tmp_path):
    path = tmp_path / "events.jsonl"
    assert store.append_events([_event()], path=path) == (1, 0)
    assert store.append_events([_event()], path=path) == (0, 1)
    assert store.append_events([_event(type="nfp")], path=path) == (1, 0)

    rows = store.load_events(path)
    assert len(rows) == 2
    assert all(r["available_at"] for r in rows)


def test_audit_events_reports_100_percent(tmp_path):
    path = tmp_path / "events.jsonl"
    store.append_events([_event(), _event(type="nfp", title="NFP")], path=path)
    audit = store.audit_events(store.load_events(path))
    assert audit["total"] == 2
    assert audit["available_at_completeness"] == 1.0
    assert audit["available_at_before_event_time"] == 0
    assert audit["by_source"] == {"macro_calendar": 2}


# ────────────────────────────── SEC EDGAR


def test_sec_classify_form():
    assert sec.classify("10-Q", "") == ("earnings", "10-Q")
    assert sec.classify("8-K", "2.02,9.01") == ("earnings", "8-K 2.02")
    assert sec.classify("8-K", "1.01") == ("mna", "8-K 1.01")
    assert sec.classify("8-K", "3.01") == ("legal", "8-K 3.01")
    assert sec.classify("8-K", "5.02") == ("regulatory", "8-K 5.02")
    assert sec.classify("8-K", "8.01") == ("regulatory", "8-K")


def test_sec_filings_to_events_window_and_fields():
    payload = {
        "cik": 1045810,
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "4", "8-K"],
                "acceptanceDateTime": [
                    "2026-11-10T21:05:03.000Z",  # 窗口内
                    "2026-09-01T20:00:00.000Z",  # 窗口外（>30 天）
                    "2026-11-10T21:00:00.000Z",  # Form 4 噪音
                    "2026-11-01T11:00:00.000Z",  # 窗口内
                ],
                "items": ["2.02,9.01", "", "", "5.02"],
                "accessionNumber": ["0001045810-26-000123"] * 4,
                "primaryDocument": ["nvda-20261110.htm"] * 4,
                "reportDate": ["2026-11-10", "2026-06-30", "", "2026-11-01"],
            }
        },
    }
    events = sec.filings_to_events(payload, "NVDA", days=30, now=NOW)
    assert len(events) == 2
    first = events[0]
    assert first["type"] == "earnings" and first["subtype"] == "8-K 2.02"
    assert first["available_at"] == "2026-11-10T21:05:03Z"
    assert first["source"] == "sec_edgar" and first["quality"] == "A"
    assert first["source_url"].endswith("/000104581026000123/nvda-20261110.htm")
    assert events[1]["type"] == "regulatory"
    # 强制过契约：不产生 available_at 缺失行
    for ev in events:
        assert store.normalize_event(ev)["available_at"]


# ────────────────────────────── Fed calendar


FOMC_HTML = """
<div class="panel panel-default"><div class="panel-heading"><h4><a id="42828">2026 FOMC Meetings</a></h4></div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5"><strong>January</strong></div>
    <div class="fomc-meeting__date col-xs-4">27-28</div>
  </div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5"><strong>March</strong></div>
    <div class="fomc-meeting__date col-xs-4">17-18*</div>
  </div>
</div>
<div class="panel panel-default"><div class="panel-heading"><h4><a id="45694">2027 FOMC Meetings</a></h4></div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5"><strong>January</strong></div>
    <div class="fomc-meeting__date col-xs-4">26-27</div>
  </div>
</div>
"""


def test_fomc_parse_calendar():
    meetings = fed.parse_calendar(FOMC_HTML)
    assert {(m["year"], m["month"], m["last_day"]) for m in meetings} == {
        (2026, 1, 28),
        (2026, 3, 18),
        (2027, 1, 27),
    }


def test_fomc_statement_time_is_14et_in_utc():
    # 1 月 EST：19:00Z；10 月 EDT：18:00Z
    assert fed.statement_time(2026, 1, 28).isoformat() == "2026-01-28T19:00:00+00:00"
    assert fed.statement_time(2026, 10, 28).isoformat() == "2026-10-28T18:00:00+00:00"


def test_fomc_meetings_to_events_window():
    meetings = fed.parse_calendar(FOMC_HTML)
    now = datetime(2026, 1, 30, tzinfo=timezone.utc)
    events = fed.meetings_to_events(meetings, days=30, now=now)
    assert len(events) == 1
    assert events[0]["available_at"] == "2026-01-28T19:00:00Z"
    assert events[0]["type"] == "fomc"
    assert store.normalize_event(events[0])["available_at"]


# ────────────────────────────── BLS macro calendar


def test_bls_extract_rows_and_classify():
    page = """
    <table><tr><th>Date</th><th>Time</th><th>Release</th></tr>
    <tr><td>Friday, November 06, 2026</td><td>08:30 AM</td>
        <td>Employment Situation for October 2026</td></tr>
    <tr><td>Tuesday, November 10, 2026</td><td>08:30 AM</td>
        <td>Consumer Price Index for October 2026</td></tr>
    <tr><td>Thursday, January 1, 2026</td><td>&nbsp;</td><td>New Year's Day</td></tr>
    </table>
    """
    rows = mac.extract_rows(page)
    assert mac.classify_release("Employment Situation for October 2026") == (
        "nfp",
        "employment_situation",
    )
    assert mac.classify_release("Consumer Price Index for October 2026") == ("cpi", "cpi")
    assert mac.classify_release("Producer Price Index for September 2026") == (
        "macro_other",
        "ppi",
    )
    assert mac.classify_release("Job Openings and Labor Turnover Survey") is None

    events = mac.rows_to_events(rows, days=30, now=NOW)
    assert len(events) == 2
    assert events[0]["type"] == "nfp" and events[0]["available_at"] == "2026-11-06T13:30:00Z"
    assert events[1]["type"] == "cpi" and events[1]["available_at"] == "2026-11-10T13:30:00Z"
    assert all(store.normalize_event(e)["available_at"] for e in events)


def test_bls_rows_to_events_ignores_out_of_window():
    rows = [
        "Friday, October 02, 2026 08:30 AM Employment Situation for September 2026",
    ]
    assert mac.rows_to_events(rows, days=30, now=NOW) == []


def test_merged_events_write_available_at_complete(tmp_path):
    """三源合并落盘后 available_at 完整率必须 100%（P0-C 验收）。"""
    rows = [
        _event(),
        _event(type="nfp", title="NFP", source="macro_calendar"),
        _event(
            type="fomc",
            title="FOMC statement",
            source="fed_calendar",
            symbols=["US500", "TLT"],
        ),
        _event(
            type="earnings",
            title="NVDA files 8-K",
            source="sec_edgar",
            symbols=["NVDA"],
            available_at="2026-11-10T21:05:03Z",
        ),
    ]
    path = tmp_path / "events.jsonl"
    added, _ = store.append_events(rows, path=path)
    assert added == 4
    audit = store.audit_events(store.load_events(path))
    assert audit["available_at_completeness"] == 1.0
    assert set(audit["by_source"]) == {"fed_calendar", "macro_calendar", "sec_edgar"}
    with open(path, encoding="utf-8") as f:
        assert all(json.loads(line)["event_id"] for line in f if line.strip())
