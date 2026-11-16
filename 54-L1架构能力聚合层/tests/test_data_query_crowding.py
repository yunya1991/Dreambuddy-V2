# -*- coding: utf-8 -*-
"""L1 直答 D-A14 取数回归：三指标必须按 UTC 日期对齐，禁止按位置拼接。"""

import importlib.util
import os
import sys
from datetime import datetime, timezone

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

_REPO = os.path.normpath(os.path.join(_MODULE_ROOT, ".."))


def _load_data_query_executor():
    script = os.path.join(_REPO, "3.1-FRONTEND", "scripts", "data_query_executor.py")
    spec = importlib.util.spec_from_file_location("_dqe_crowding_tests", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ts(day):
    year, month, date = (int(part) for part in day.split("-"))
    return int(datetime(year, month, date, tzinfo=timezone.utc).timestamp())


class _FakeL0:
    def __init__(self, rows):
        self.rows = rows

    def fetch_context(self, scope, params):
        assert scope == "datacenter.series"
        points = [
            {"ts": _ts(day), "value": value} for day, value in self.rows[params["metric_name"]]
        ]
        return {"data": {"points": points}}


def _rows():
    return {
        "funding_rate_pct": [
            ("2024-01-01", 1.0),
            ("2024-01-02", 2.0),
            ("2024-01-03", 3.0),
            ("2024-01-04", 4.0),
        ],
        "open_interest_value_binance": [
            ("2024-01-02", 20.0),
            ("2024-01-03", 30.0),
            ("2024-01-04", 40.0),
            ("2024-01-05", 50.0),
        ],
        "long_short_ratio": [
            ("2024-01-03", 300.0),
            ("2024-01-04", 400.0),
            ("2024-01-05", 500.0),
            ("2024-01-06", 600.0),
        ],
    }


def test_crowding_panel_aligns_by_utc_day(monkeypatch):
    dqe = _load_data_query_executor()
    monkeypatch.setattr(dqe, "get_l0", lambda: _FakeL0(_rows()))

    panel, dates, missing = dqe._load_crowding_panel()

    assert missing == []
    assert dates == ["2024-01-03", "2024-01-04"]
    assert panel["资金费率"] == [3.0, 4.0]
    assert panel["未平仓"] == [30.0, 40.0]
    assert panel["多空比"] == [300.0, 400.0]


def test_crowding_panel_reports_missing_series(monkeypatch):
    dqe = _load_data_query_executor()
    rows = _rows()
    rows["long_short_ratio"] = []
    monkeypatch.setattr(dqe, "get_l0", lambda: _FakeL0(rows))

    panel, dates, missing = dqe._load_crowding_panel()

    assert panel == {}
    assert dates == []
    assert missing == ["多空比"]
