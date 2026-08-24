"""M1 端到端集成测试 — 对齐 IMPLEMENTATION_PLAN.md M1 验收。

1) DataCenter 加载 .env（新行为，先红）
2) 端到端：fetch macro -> DataRecord -> 去重 -> sqlite 落库（验收）
"""
import os

import pandas as pd

from data_center import DataCenter, DataRecord
from data_center.storage.sink_sqlite import SqliteSink

FRED_MOD = "data_center.collectors.macro.fred_collector.Fred"


def _make_series():
    idx = [pd.Timestamp("2026-07-01"), pd.Timestamp("2026-08-01")]
    return pd.Series([5.0, 5.25], index=idx)


def test_datacenter_loads_env_file(tmp_path, monkeypatch):
    env = tmp_path / "test.env"
    env.write_text("FRED_API_KEY=from-file\n")
    monkeypatch.setenv("FRED_API_KEY", "")  # 占位，保证 teardown 还原

    DataCenter(env_path=str(env))  # 构造即加载 .env

    assert os.environ.get("FRED_API_KEY") == "from-file"


def test_end_to_end_fetch_dedupe_sink(mocker, monkeypatch, tmp_path):
    mocker.patch(FRED_MOD).return_value.get_series.return_value = _make_series()
    monkeypatch.setenv("FRED_API_KEY", "fake-key")

    dc = DataCenter()
    recs = dc.fetch("macro", series="FEDFUNDS", source="fred")
    assert len(recs) == 1
    assert isinstance(recs[0], DataRecord)
    assert recs[0].metrics["value"] == 5.25

    sink = SqliteSink(str(tmp_path / "integ.db"))
    assert sink.write(recs) == 1
    assert sink.write(recs) == 0  # 二次写入被去重
    rows = sink.read_all()
    assert len(rows) == 1
    assert rows[0].metrics["value"] == 5.25
