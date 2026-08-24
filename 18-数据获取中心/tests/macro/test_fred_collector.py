"""FRED macro collector 测试 — 迁移自 flow_collector.py 的 fetch_fred_* 四序列。

无 Key 降级返回空、429 限流抛 RateLimitError、产出 DataRecord 契约。
"""
import pandas as pd
import pytest

from data_center.collectors.macro.fred_collector import FredCollector
from data_center.core.contract import DataRecord
from data_center.core.errors import RateLimitError

FRED_MOD = "data_center.collectors.macro.fred_collector.Fred"


def _make_series():
    idx = [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")]
    return pd.Series([5.0, 5.25], index=idx)


def test_series_registered_matches_flow_collector_plus_five_domain():
    # 原有 4 序列 + 易经推理五维需求新增 6 个（M2NS/M2SL/WALCL/CPIAUCSL/PPIACO/INDPRO）
    assert set(FredCollector.SERIES) == {
        "FEDFUNDS", "RRPONTSYD", "DFII10", "T10YIE",
        "M2NS", "M2SL", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO",
    }


def test_all_new_series_fetch_datarecord(mocker):
    """五维新增的 6 个 series，mock 都能产出 DataRecord。"""
    mock_cls = mocker.patch(FRED_MOD)
    mock_cls.return_value.get_series.return_value = _make_series()

    c = FredCollector(config={"api_key": "fake-key"})
    new_series = ("M2NS", "M2SL", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO")
    for s in new_series:
        recs = c.fetch({"series": s})
        assert len(recs) == 1
        assert recs[0].sub_category == s
        assert recs[0].metrics["value"] == 5.25


def test_fetch_returns_datarecord(mocker):
    mock_cls = mocker.patch(FRED_MOD)
    mock_cls.return_value.get_series.return_value = _make_series()

    c = FredCollector(config={"api_key": "fake-key"})
    recs = c.fetch({"series": "FEDFUNDS"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "fred"
    assert r.category == "macro"
    assert r.sub_category == "FEDFUNDS"
    assert r.metrics["value"] == 5.25
    assert r.metrics["date"] == "2026-08-01"  # 取最新值（修正原版取 observations[0] 的最旧值）
    assert r.timeseries[0]["value"] == 5.25
    assert r.raw["series_id"] == "FEDFUNDS"


def test_no_api_key_returns_empty(mocker, monkeypatch):
    mocker.patch(FRED_MOD)
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    c = FredCollector()  # 无 config 且无环境变量
    assert c.is_available() is False
    assert c.fetch({"series": "FEDFUNDS"}) == []  # 无 Key 降级，不抛异常


def test_rate_limit_raises(mocker):
    mock_cls = mocker.patch(FRED_MOD)
    mock_cls.return_value.get_series.side_effect = Exception("HTTP 429 Too Many Requests")

    c = FredCollector(config={"api_key": "fake-key"})
    with pytest.raises(RateLimitError):
        c.fetch({"series": "FEDFUNDS"})
