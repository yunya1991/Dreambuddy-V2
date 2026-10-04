"""FedEventCollector 测试 — FOMC 决议 + CME FedWatch 概率。

覆盖：FedWatch 概率采集、FOMC 决议采集、FAIL-OPEN 降级、DataRecord 契约。
"""
import pytest

from data_center.collectors.macro.fed_event_collector import FedEventCollector
from data_center.core.contract import DataRecord

FED_EVENT_MOD = "data_center.collectors.macro.fed_event_collector"


def test_source_category():
    assert FedEventCollector.source == "cme"
    assert FedEventCollector.category == "macro"


def test_fetch_fedwatch_returns_probabilities(mocker):
    """FedWatch 概率采集：返回 hike/cut/hold 概率。"""
    mock_cme = mocker.patch(f"{FED_EVENT_MOD}._fetch_fedwatch_from_cme")
    mock_cme.return_value = {
        "hike_prob": 0.93,
        "cut_prob": 0.0,
        "hold_prob": 0.07,
        "meeting_date": "2026-09-16",
        "target_rate": "5.50-5.75",
    }

    c = FedEventCollector()
    recs = c.fetch({"type": "fedwatch"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "cme"
    assert r.category == "macro"
    assert r.sub_category == "fedwatch"
    assert r.metrics["hike_prob"] == 0.93
    assert r.metrics["cut_prob"] == 0.0
    assert r.metrics["hold_prob"] == 0.07
    assert r.metrics["meeting_date"] == "2026-09-16"


def test_fedwatch_metrics_includes_p0_new_fields(mocker):
    """RED: SPEC §3.1.2 — _fetch_fedwatch_from_cme 真实返回时，
    DataRecord.metrics 必须包含 effr/current_target/trade_date 三个新字段。
    effr 替代 EventDrivenStrategy._score_real_rate() 中 BASE_RATE_MIDPOINT 硬编码。
    """
    mock_cme = mocker.patch(f"{FED_EVENT_MOD}._fetch_fedwatch_from_cme")
    mock_cme.return_value = {
        "hike_prob": 0.07,
        "cut_prob": 0.93,
        "hold_prob": 0.0,
        "meeting_date": "2026-11-07",
        "target_rate": "4.00-4.25",
        "effr": 4.33,
        "current_target": "4.00-4.25",
        "trade_date": "2026-10-02",
    }

    c = FedEventCollector()
    recs = c.fetch({"type": "fedwatch"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["effr"] == 4.33, "effr 缺失：无法替代 BASE_RATE_MIDPOINT 硬编码"
    assert r.metrics["current_target"] == "4.00-4.25", "current_target 缺失"
    assert r.metrics["trade_date"] == "2026-10-02", "trade_date 缺失"


def test_fedwatch_fallback_when_cme_not_installed(mocker):
    """RED: SPEC §3.1.2 — cme-fedwatch 包未安装时降级到 investing.com 爬虫，
    metrics 的 effr/current_target/trade_date 用 0.0/"" 兜底，不抛异常。
    """
    from data_center.collectors.macro import fed_event_collector as mod

    # 模拟 cme-fedwatch 未安装：_fetch_fedwatch_from_cme 内部 ImportError → 降级 investing
    # investing 路径 mock 返回不含新字段
    mock_investing = mocker.patch(
        f"{FED_EVENT_MOD}._fetch_fedwatch_from_investing"
    )
    mock_investing.return_value = {
        "hike_prob": 0.50,
        "cut_prob": 0.30,
        "hold_prob": 0.20,
        "meeting_date": "2026-11-07",
        "target_rate": "4.00-4.25",
    }
    # 让 _fetch_fedwatch_from_cme 走降级路径（cme_fedwatch 导入失败）
    mocker.patch("builtins.__import__", side_effect=ImportError("no cme_fedwatch"))

    c = FedEventCollector()
    recs = c.fetch({"type": "fedwatch"})

    assert len(recs) == 1
    r = recs[0]
    # 降级路径下新字段用 0.0/"" 兜底，契约校验通过
    assert r.metrics["effr"] == 0.0
    assert r.metrics["current_target"] == ""
    assert r.metrics["trade_date"] == ""


def test_fetch_fomc_decision_returns_result(mocker):
    """FOMC 决议采集：返回实际利率决议 + 点阵图中位数。"""
    mock_fomc = mocker.patch(f"{FED_EVENT_MOD}._fetch_fomc_decision")
    mock_fomc.return_value = {
        "decision": "hike",
        "rate_change": 0.25,
        "new_rate_range": "5.50-5.75",
        "dot_plot_median": 5.6,
        "votes": "11-1",
        "meeting_date": "2026-09-16",
    }

    c = FedEventCollector()
    recs = c.fetch({"type": "fomc_decision"})

    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "fomc_decision"
    assert r.metrics["decision"] == "hike"
    assert r.metrics["rate_change"] == 0.25
    assert r.metrics["new_rate_range"] == "5.50-5.75"
    assert r.metrics["dot_plot_median"] == 5.6


def test_fetch_invalid_type_returns_empty():
    """无效 type 返回空列表，不抛异常。"""
    c = FedEventCollector()
    assert c.fetch({"type": "invalid"}) == []


def test_fetch_no_type_returns_empty():
    """无 type 参数返回空列表。"""
    c = FedEventCollector()
    assert c.fetch({}) == []


def test_fail_open_when_cme_unavailable(mocker):
    """CME 抓取失败时降级返回空，不抛异常（FAIL-OPEN）。"""
    mock_cme = mocker.patch(f"{FED_EVENT_MOD}._fetch_fedwatch_from_cme")
    mock_cme.side_effect = Exception("CME timeout")

    c = FedEventCollector()
    recs = c.fetch({"type": "fedwatch"})
    assert recs == []  # 降级返回空，不抛异常


def test_fail_open_when_fomc_unavailable(mocker):
    """FOMC 数据不可用时降级返回空。"""
    mock_fomc = mocker.patch(f"{FED_EVENT_MOD}._fetch_fomc_decision")
    mock_fomc.side_effect = Exception("source unavailable")

    c = FedEventCollector()
    recs = c.fetch({"type": "fomc_decision"})
    assert recs == []


def test_is_available_default_true():
    """FedEventCollector 不需要 API Key，默认可用。"""
    c = FedEventCollector()
    assert c.is_available() is True
