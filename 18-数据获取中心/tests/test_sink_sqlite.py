"""sqlite 落库测试 — 对齐 TECHNICAL_DESIGN.md §6/§3.3。

写入后可读回、字段一致；同 dedupe_key 二次写入被忽略。
"""
from data_center.core.contract import DataRecord
from data_center.storage.sink_sqlite import SqliteSink


def _rec(sub, date, val):
    return DataRecord(
        source="fred", category="macro", sub_category=sub,
        timestamp="2026-08-24T08:00:00+08:00",
        metrics={"value": val, "date": date},
        events=[], timeseries=[{"date": date, "value": val}],
        raw={"series_id": sub},
    )


def test_write_and_read_back(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    assert sink.write([_rec("FEDFUNDS", "2026-08-01", 5.25)]) == 1
    rows = sink.read_all()
    assert len(rows) == 1
    r = rows[0]
    assert r.source == "fred"
    assert r.sub_category == "FEDFUNDS"
    assert r.metrics["value"] == 5.25
    assert r.metrics["date"] == "2026-08-01"
    assert r.timeseries[0]["value"] == 5.25


def test_dedupe_at_sink(tmp_path):
    sink = SqliteSink(str(tmp_path / "t.db"))
    rec = _rec("FEDFUNDS", "2026-08-01", 5.25)
    assert sink.write([rec]) == 1
    assert sink.write([rec]) == 0  # 同 dedupe_key，INSERT OR IGNORE 跳过
    assert len(sink.read_all()) == 1
