"""CongressionalHearingCollector 测试 — 国会听证会采集。

SPEC-Phase2 §6.4:
  - 数据源: senate.gov 信贷委员会 + house.gov 金融服务委员会（HTML）
  - direction: 默认 neutral（由内容决定，初版固定 neutral）
  - crypto_related: 标题含 crypto/stablecoin/digital asset 等
  - is_scheduled: True（轨道 A 窗口预演型）
  - FAIL-OPEN: 抓取/解析失败返回空列表

RED 阶段：CongressionalHearingCollector 类尚未实现，测试应因 ImportError 失败。
"""
import pytest
from datetime import datetime, timezone

from data_center.core.contract import DataRecord

HEARING_MOD = "data_center.collectors.macro.congressional_hearing_collector"


@pytest.fixture
def collector(tmp_path):
    from data_center.collectors.macro.congressional_hearing_collector import (
        CongressionalHearingCollector,
    )
    return CongressionalHearingCollector(config={"urls": []})


# ---------- 基础属性 ----------

def test_source_category(collector):
    assert collector.source == "congress"
    # "hearing" 不在 DataRecord CATEGORIES，用 "macro"（宏观监管事件）
    assert collector.category == "macro"


# ---------- HTML 解析 ----------

_SENATE_HTML = """
<html><body>
<div class="hearing-item">
  <span class="hearing-date">October 15, 2026</span>
  <a href="/hearings/123">Oversight of Digital Assets: Examining the Market Structure</a>
</div>
<div class="hearing-item">
  <span class="hearing-date">November 2, 2026</span>
  <a href="/hearings/124">Annual Housing Finance Report</a>
</div>
</body></html>
"""


def test_parse_senate_html_extracts_hearings(collector):
    """解析 senate.gov HTML，提取日期 + 主题。"""
    hearings = collector._parse_hearings(_SENATE_HTML, "senate_banking")
    assert len(hearings) == 2
    assert hearings[0]["date"] == "2026-10-15"
    assert "Digital Assets" in hearings[0]["title"]
    assert hearings[1]["date"] == "2026-11-02"


def test_parse_marks_crypto_related(collector):
    """标题含 crypto/digital asset → crypto_related=True。"""
    hearings = collector._parse_hearings(_SENATE_HTML, "senate_banking")
    assert hearings[0]["crypto_related"] is True  # Digital Assets
    assert hearings[1]["crypto_related"] is False  # Housing Finance


# ---------- fetch 产出 DataRecord ----------

def test_fetch_returns_data_records(collector, mocker):
    """fetch 解析 HTML 并构造 DataRecord 列表。"""
    mocker.patch(
        f"{HEARING_MOD}.CongressionalHearingCollector._fetch_pages",
        return_value=[_SENATE_HTML],
    )
    recs = collector.fetch({})

    assert len(recs) == 2
    for r in recs:
        assert isinstance(r, DataRecord)
        assert r.source == "congress"
        assert r.category == "macro"
        assert r.sub_category == "congressional_hearing"
        assert r.metrics["event_type"] == "congressional_hearing"
        assert r.metrics["is_scheduled"] is True
        # direction 默认 neutral（SPEC §7.3）
        assert r.metrics["direction"] == "neutral"


def test_fetch_only_crypto_related_when_filtered(collector, mocker):
    """crypto_only=True 时仅返回加密相关听证会。"""
    mocker.patch(
        f"{HEARING_MOD}.CongressionalHearingCollector._fetch_pages",
        return_value=[_SENATE_HTML],
    )
    recs = collector.fetch({"crypto_only": True})
    assert len(recs) == 1
    assert "Digital Assets" in recs[0].metrics["title"]


def test_fetch_metrics_contain_date_event(collector, mocker):
    """DataRecord.metrics 含 date_event 供 GeneralEventWindowTracker 使用。"""
    mocker.patch(
        f"{HEARING_MOD}.CongressionalHearingCollector._fetch_pages",
        return_value=[_SENATE_HTML],
    )
    recs = collector.fetch({})
    # 第一条是 10/15 的 Digital Assets 听证
    crypto_recs = [r for r in recs if r.metrics["crypto_related"]]
    assert crypto_recs[0].metrics["date_event"] == "2026-10-15"


# ---------- FAIL-OPEN ----------

def test_fail_open_fetch_error(collector, mocker):
    """页面抓取异常 → 返回空列表。"""
    mocker.patch(
        f"{HEARING_MOD}.CongressionalHearingCollector._fetch_pages",
        side_effect=RuntimeError("network error"),
    )
    recs = collector.fetch({})
    assert recs == []


def test_fail_open_empty_html(collector, mocker):
    """空 HTML → 返回空列表。"""
    mocker.patch(
        f"{HEARING_MOD}.CongressionalHearingCollector._fetch_pages",
        return_value=[],
    )
    recs = collector.fetch({})
    assert recs == []


def test_fail_open_parse_invalid_html(collector, mocker):
    """无效 HTML（无 hearing 结构）→ 返回空列表，不抛异常。"""
    mocker.patch(
        f"{HEARING_MOD}.CongressionalHearingCollector._fetch_pages",
        return_value=["<html><body>No hearings here</body></html>"],
    )
    recs = collector.fetch({})
    assert recs == []


# ---------- 日期解析鲁棒性 ----------

def test_parse_various_date_formats(collector):
    """支持多种日期格式（月日年 / 月.日 / ISO）。"""
    html = """
    <div class="hearing-item">
      <span class="hearing-date">Oct 15 2026</span>
      <a>Stablecoin Regulation Hearing</a>
    </div>
    """
    hearings = collector._parse_hearings(html, "senate_banking")
    assert len(hearings) == 1
    assert hearings[0]["date"] == "2026-10-15"
    assert hearings[0]["crypto_related"] is True
