"""DataRecord 统一契约测试 — 对齐 TECHNICAL_DESIGN.md §3.1。

约束：metrics 仅存 number/string，不嵌套对象；timestamp 为 ISO8601；raw 保留溯源。
"""
import pytest

from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import ContractError


def _valid_record(**over):
    base = dict(
        source="fred",
        category="macro",
        sub_category="FEDFUNDS",
        timestamp="2026-08-24T08:00:00+08:00",
        metrics={"value": 5.25, "date": "2026-08-01"},
        events=[],
        timeseries=[{"date": "2026-08-01", "value": 5.25}],
        raw={"observations": [{"value": "5.25"}]},
    )
    base.update(over)
    return DataRecord(**base)


def test_valid_record_passes_validation():
    validate_record(_valid_record())  # 不抛异常


def test_schema_version_defaults_to_1_0():
    assert _valid_record().schema_version == "1.0"


def test_metrics_rejects_nested_dict():
    rec = _valid_record(metrics={"value": {"nested": 1}})
    with pytest.raises(ContractError):
        validate_record(rec)


def test_metrics_rejects_list_value():
    rec = _valid_record(metrics={"values": [1, 2, 3]})
    with pytest.raises(ContractError):
        validate_record(rec)


def test_metrics_accepts_number_string_bool():
    rec = _valid_record(metrics={"v": 1, "f": 2.5, "s": "x", "b": True})
    validate_record(rec)  # bool 视为 number


def test_timestamp_must_be_iso8601():
    rec = _valid_record(timestamp="2026/08/24 08:00")
    with pytest.raises(ContractError):
        validate_record(rec)


def test_empty_source_rejected():
    rec = _valid_record(source="")
    with pytest.raises(ContractError):
        validate_record(rec)
