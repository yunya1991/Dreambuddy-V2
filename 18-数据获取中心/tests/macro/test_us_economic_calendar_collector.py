"""UsEconomicCalendarCollector 测试 — CPI/非农/PPI actual/forecast/surprise。

覆盖：各指标采集、surprise 计算、FAIL-OPEN 降级、DataRecord 契约。
"""
import pytest

from data_center.collectors.macro.us_economic_calendar_collector import (
    UsEconomicCalendarCollector,
)
from data_center.core.contract import DataRecord

ECON_MOD = "data_center.collectors.macro.us_economic_calendar_collector"


def test_source_category():
    assert UsEconomicCalendarCollector.source == "econ_calendar"
    assert UsEconomicCalendarCollector.category == "macro"


def test_fetch_cpi_returns_surprise(mocker):
    """CPI 采集返回 actual/forecast/surprise。"""
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 3.2,
        "forecast": 3.0,
        "previous": 2.9,
        "release_date": "2026-09-11",
    }

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "cpi"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.sub_category == "cpi"
    assert r.metrics["actual"] == 3.2
    assert r.metrics["forecast"] == 3.0
    assert r.metrics["surprise"] == pytest.approx(0.2)  # actual - forecast
    assert r.metrics["release_date"] == "2026-09-11"


def test_fetch_nfp(mocker):
    """非农采集。"""
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 187.0,
        "forecast": 170.0,
        "previous": 157.0,
        "release_date": "2026-09-05",
    }

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "nfp"})

    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "nfp"
    assert r.metrics["actual"] == 187.0
    assert r.metrics["surprise"] == pytest.approx(17.0)


def test_fetch_ppi(mocker):
    """PPI 采集。"""
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 0.4,
        "forecast": 0.2,
        "previous": 0.1,
        "release_date": "2026-09-10",
    }

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "ppi"})

    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "ppi"
    assert r.metrics["surprise"] == pytest.approx(0.2)


def test_invalid_indicator_returns_empty():
    """无效指标返回空。"""
    c = UsEconomicCalendarCollector()
    assert c.fetch({"indicator": "gdp"}) == []


def test_no_indicator_returns_empty():
    c = UsEconomicCalendarCollector()
    assert c.fetch({}) == []


def test_fail_open_when_source_unavailable(mocker):
    """数据源不可用时降级返回空。"""
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.side_effect = Exception("API timeout")

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "cpi"})
    assert recs == []


def test_surprise_calculation(mocker):
    """surprise = actual - forecast。"""
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 2.5,
        "forecast": 3.0,
        "previous": 2.8,
        "release_date": "2026-09-11",
    }

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "cpi"})
    assert recs[0].metrics["surprise"] == pytest.approx(-0.5)


def test_supported_indicators():
    """支持的指标列表。"""
    c = UsEconomicCalendarCollector()
    assert "cpi" in c.SUPPORTED_INDICATORS
    assert "nfp" in c.SUPPORTED_INDICATORS
    assert "ppi" in c.SUPPORTED_INDICATORS


def test_fetch_cpi_returns_cesi_when_history_sufficient(mocker):
    """RED: SPEC §3.1.3 — 6+ 次历史时 metrics 包含 cesi 标准化值。
    CESI = (actual - forecast) / σ_history，σ 为最近 12 次 surprise 标准差。
    """
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 3.5,
        "forecast": 3.0,
        "previous": 2.9,
        "release_date": "2026-09-11",
    }
    mock_get = mocker.patch(f"{ECON_MOD}.get_surprise_history")
    mock_get.return_value = [0.1, -0.1, 0.2, -0.2, 0.15, -0.15]  # 6 次
    mock_append = mocker.patch(f"{ECON_MOD}.append_surprise")

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "cpi"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["surprise"] == 0.5
    assert r.metrics["cesi"] is not None
    assert isinstance(r.metrics["cesi"], float)
    # cesi = 0.5 / σ_history
    import numpy as np
    expected_sigma = float(np.std([0.1, -0.1, 0.2, -0.2, 0.15, -0.15]))
    assert r.metrics["cesi"] == round(0.5 / expected_sigma, 3)
    # append_surprise 被调用，积累历史
    mock_append.assert_called_once_with("cpi", 0.5)


def test_fetch_cpi_cesi_none_when_history_insufficient(mocker):
    """RED: SPEC §3.1.3 — 少于 6 次历史时 cesi=None（不在 metrics 中），
    surprise 仍存在，下游用 surprise 绝对值差兜底。
    """
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 3.5,
        "forecast": 3.0,
        "previous": 2.9,
        "release_date": "2026-09-11",
    }
    mock_get = mocker.patch(f"{ECON_MOD}.get_surprise_history")
    mock_get.return_value = [0.1, -0.1, 0.2]  # 3 次，不足 6 次
    mock_append = mocker.patch(f"{ECON_MOD}.append_surprise")

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "cpi"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["surprise"] == 0.5
    # cesi 不在 metrics 中（契约禁止 None，用 key 不存在表示）
    assert r.metrics.get("cesi") is None
    # append_surprise 仍被调用（积累历史）
    mock_append.assert_called_once_with("cpi", 0.5)


def test_fetch_cesi_fail_open_when_cesi_module_error(mocker):
    """RED: SPEC §3.1.3 — CESI 计算异常时 FAIL-OPEN，metrics 不含 cesi，不抛异常。"""
    mock_fetch = mocker.patch(f"{ECON_MOD}._fetch_indicator")
    mock_fetch.return_value = {
        "actual": 3.5,
        "forecast": 3.0,
        "previous": 2.9,
        "release_date": "2026-09-11",
    }
    mock_get = mocker.patch(f"{ECON_MOD}.get_surprise_history")
    mock_get.side_effect = Exception("file IO error")
    mock_append = mocker.patch(f"{ECON_MOD}.append_surprise")
    mock_append.side_effect = Exception("file IO error")

    c = UsEconomicCalendarCollector()
    recs = c.fetch({"indicator": "cpi"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["surprise"] == 0.5  # surprise 仍存在
    assert r.metrics.get("cesi") is None  # cesi 不存在，FAIL-OPEN
