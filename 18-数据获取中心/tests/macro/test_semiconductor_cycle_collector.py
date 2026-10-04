"""SemiconductorCycleCollector 测试 — T13c AI 周期评分数据采集。

SOX 指数 30 天涨幅 / 半导体资本开支同比 / HBM 需求指数。
FAIL-OPEN：无数据/异常返回空列表，不阻塞交易。
"""
from datetime import datetime, timezone

import pytest

from data_center.collectors.macro.semiconductor_cycle_collector import (
    SemiconductorCycleCollector,
)
from data_center.core.contract import DataRecord


class TestSemiconductorCycleCollector:
    """半导体周期采集器。"""

    def test_source_and_category(self):
        c = SemiconductorCycleCollector()
        assert c.source == "semiconductor"
        assert c.category == "macro"

    def test_is_available_with_config(self):
        c = SemiconductorCycleCollector(config={"sox_symbol": "^SOX"})
        assert c.is_available() is True

    def test_fetch_sox_returns_datarecord(self, mocker):
        """mock yfinance → 产出 SOX 30 天涨幅 DataRecord。"""
        mock_yf = mocker.patch(
            "data_center.collectors.macro.semiconductor_cycle_collector.yf"
        )
        import pandas as pd
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame(
            {"Close": [3500.0, 3700.0]},
            index=[pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")],
        )

        c = SemiconductorCycleCollector()
        recs = c.fetch({"metric": "sox_change_30d"})
        assert len(recs) == 1
        r = recs[0]
        assert isinstance(r, DataRecord)
        assert r.sub_category == "sox_change_30d"
        # 涨幅 ≈ 5.71%
        assert abs(r.metrics["value"] - 5.71) < 0.5

    def test_fetch_capex_from_config(self):
        """CapEx 同比从配置读取。"""
        c = SemiconductorCycleCollector(
            config={"capex_yoy": 25.0}
        )
        recs = c.fetch({"metric": "semiconductor_capex_yoy"})
        assert len(recs) == 1
        assert recs[0].metrics["value"] == 25.0

    def test_fetch_hbm_from_config(self):
        """HBM 需求指数从配置读取。"""
        c = SemiconductorCycleCollector(
            config={"hbm_demand_index": 0.85}
        )
        recs = c.fetch({"metric": "hbm_demand_index"})
        assert len(recs) == 1
        assert recs[0].metrics["value"] == 0.85

    def test_fetch_all_metrics(self, mocker):
        """fetch_all → 3 条 DataRecord。"""
        mock_yf = mocker.patch(
            "data_center.collectors.macro.semiconductor_cycle_collector.yf"
        )
        import pandas as pd
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame(
            {"Close": [3500.0, 3700.0]},
            index=[pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")],
        )
        c = SemiconductorCycleCollector(config={"capex_yoy": 20.0, "hbm_demand_index": 0.8})
        recs = c.fetch_all()
        assert len(recs) == 3
        cats = {r.sub_category for r in recs}
        assert cats == {"sox_change_30d", "semiconductor_capex_yoy", "hbm_demand_index"}

    def test_fail_open_yfinance_error(self, mocker):
        """yfinance 异常 → 空列表，不抛异常。"""
        mock_yf = mocker.patch(
            "data_center.collectors.macro.semiconductor_cycle_collector.yf"
        )
        mock_yf.Ticker.side_effect = Exception("Network error")

        c = SemiconductorCycleCollector()
        recs = c.fetch({"metric": "sox_change_30d"})
        assert recs == []

    def test_fail_open_no_metric(self):
        """无 metric 参数 → 空列表。"""
        c = SemiconductorCycleCollector()
        assert c.fetch({}) == []

    def test_sox_change_calculation(self, mocker):
        """SOX 30天涨幅计算正确（下跌场景）。"""
        mock_yf = mocker.patch(
            "data_center.collectors.macro.semiconductor_cycle_collector.yf"
        )
        import pandas as pd
        mock_yf.Ticker.return_value.history.return_value = pd.DataFrame(
            {"Close": [3700.0, 3500.0]},
            index=[pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01")],
        )
        c = SemiconductorCycleCollector()
        recs = c.fetch({"metric": "sox_change_30d"})
        assert len(recs) == 1
        assert recs[0].metrics["value"] < 0  # 下跌
