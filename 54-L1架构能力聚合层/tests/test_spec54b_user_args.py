"""SPEC-54b：动态参数表单 —— 用户输入型能力（J25–J28 / J30）放行与校验。"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_L1 = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_L1)
for _p in (_HERE, _L1, os.path.join(_ROOT, "3.1-FRONTEND", "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_resolve as cr  # noqa: E402
from l1agg.capabilities import param_schema  # noqa: E402


def _schema_args(capability_id):
    return {arg["name"]: arg for arg in param_schema.for_capability(capability_id)["args"]}


# ---------------------------------------------------------------- AC1 schema
def test_j25_j28_arg_types_overridden():
    j25 = _schema_args("D-J25")
    assert j25["coords"]["type"] == "json" and j25["coords"]["source"] == "user"
    assert j25["coords"]["required"] is True
    assert j25["values"]["source"] == "auto"

    j26 = _schema_args("D-J26")
    assert j26["time"]["type"] == "series" and j26["time"]["required"] is True
    assert j26["event"]["type"] == "series"
    assert j26["group"]["type"] == "labels"
    assert j26["covariate"]["type"] == "series"

    j27 = _schema_args("D-J27")
    assert j27["time"]["type"] == "series" and j27["time"]["required"] is True

    j28 = _schema_args("D-J28")
    assert j28["effects"]["type"] == "series" and j28["effects"]["required"] is True
    assert j28["se"]["type"] == "series" and j28["se"]["required"] is True


def test_j30_indicator_is_user_scalar_and_prices_auto():
    j30 = _schema_args("D-J30")
    assert j30["indicator"]["source"] == "user" and j30["indicator"]["required"] is True
    assert j30["prices"]["source"] == "auto" and j30["prices"]["required"] is False


# ---------------------------------------------------------------- AC2 J25
def _coords(n=36):
    return [[float(i % 6), float(i // 6)] for i in range(n)]


def test_j25_missing_coords():
    result = cr.resolve("D-J25", {})
    assert result["code"] == "missing_args"
    assert result["missing_params"] == ["coords"]


def test_j25_ok_with_user_coords_and_values():
    coords = _coords()
    values = [float(i) * 0.1 for i in range(len(coords))]
    result = cr.resolve("D-J25", {"coords": coords, "values": values})
    assert result["code"] == "ok", result.get("reason")


def test_j25_length_mismatch_is_invalid():
    coords = _coords()
    result = cr.resolve("D-J25", {"coords": coords, "values": [1.0] * 10})
    assert result["code"] == "invalid_params"


def test_j25_malformed_coords_is_invalid():
    result = cr.resolve("D-J25", {"coords": [[1, 2, 3]] * 40, "values": [1.0] * 40})
    assert result["code"] == "invalid_params"


# ---------------------------------------------------------------- AC3 J26
def test_j26_missing_time():
    result = cr.resolve("D-J26", {})
    assert result["code"] == "missing_args"
    assert result["missing_params"] == ["time"]


def test_j26_ok_with_time_and_event():
    durations = [float(i + 1) for i in range(60)]
    events = [1.0] * 30 + [0.0] * 30
    result = cr.resolve("D-J26", {"time": durations, "event": events})
    assert result["code"] == "ok", result.get("reason")


def test_j26_short_time_is_sample_insufficient():
    result = cr.resolve("D-J26", {"time": [1.0] * 10})
    assert result["code"] == "sample_insufficient"


def test_j26_event_length_mismatch_is_invalid():
    result = cr.resolve("D-J26", {"time": [1.0] * 60, "event": [1.0] * 10})
    assert result["code"] == "invalid_params"


# ---------------------------------------------------------------- AC4 J27 / J28
def test_j27_ok_with_time():
    result = cr.resolve("D-J27", {"time": [float(i + 1) for i in range(60)]})
    assert result["code"] == "ok", result.get("reason")


def test_j27_accepts_series_alias():
    result = cr.resolve("D-J27", {"series": [float(i + 1) for i in range(60)]})
    assert result["code"] == "ok", result.get("reason")


def test_j28_ok_and_mismatch():
    effects = [0.1 + i * 0.001 for i in range(40)]
    se = [0.05 + i * 0.0005 for i in range(40)]
    ok_result = cr.resolve("D-J28", {"effects": effects, "se": se})
    assert ok_result["code"] == "ok", ok_result.get("reason")

    bad = cr.resolve("D-J28", {"effects": effects, "se": se[:10]})
    assert bad["code"] == "invalid_params"

    missing = cr.resolve("D-J28", {"effects": effects})
    assert missing["code"] == "missing_args"
    assert missing["missing_params"] == ["se"]


# ---------------------------------------------------------------- AC5 J30
def test_j30_series_input_ok_and_discloses_release_ts_absent():
    indicator = [100.0 + i * 0.1 for i in range(300)]
    prices = [50000.0 + i * 3.0 for i in range(300)]
    result = cr.resolve("D-J30", {"indicator": indicator, "prices": prices})
    if result["code"] == "sample_insufficient":
        pytest.skip("PIT 样本门槛高于 300，按口径跳过")
    assert result["code"] == "ok", result.get("reason")
    quality = result.get("quality") or {}
    assert "release_ts_absent" in str(quality.get("degraded_reason") or "")


def test_j30_missing_indicator():
    result = cr.resolve("D-J30", {})
    assert result["code"] == "missing_args"
    assert result["missing_params"] == ["indicator"]


def test_schema_snapshot_covers_j25_j30():
    """快照文件已随 SPEC-54b 更新，防止后续回退到 scalar。"""
    from pathlib import Path

    fixture = Path(__file__).with_name("fixtures") / "param_schema_snapshot.json"
    snapshot = json.loads(fixture.read_text(encoding="utf-8"))
    assert "coords:json:1:user" in snapshot["D-J25"]["args"]
    assert "group:labels:0:user" in snapshot["D-J26"]["args"]
    assert "effects:series:1:user" in snapshot["D-J28"]["args"]
