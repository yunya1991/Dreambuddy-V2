"""SPEC-54 能力卡片全景接入：装配器与 schema 验收（AC6/AC7/AC9/AC10）。"""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_L1 = os.path.join(_REPO, "54-L1架构能力聚合层")
_SCRIPTS = os.path.join(_REPO, "3.1-FRONTEND", "scripts")
for _p in (_L1, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_resolve as cr  # noqa: E402
from l1agg.capabilities import param_schema  # noqa: E402

_DB_READY = os.path.exists(cr.DB_PATH)
_needs_db = pytest.mark.skipif(not _DB_READY, reason="dreambuddy_core.db 不存在")


# ---------------------------------------------------------------- schema
def test_schema_total_and_unsupported():
    schemas = param_schema.all_schemas()
    assert len(schemas) == 94
    unsupported = {cid for cid, schema in schemas.items() if schema["unsupported"]}
    assert unsupported == {"D-G23", "D-A14", "D-A16"}


def test_schema_snapshot_stable():
    """94 项 schema 快照：name/type/required/source 与资产/基准标记漂移必须显式确认。"""
    from pathlib import Path

    from l1agg.capabilities import param_schema

    fixture = Path(__file__).with_name("fixtures") / "param_schema_snapshot.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))
    actual = {}
    for cid, schema in param_schema.all_schemas().items():
        actual[cid] = {
            "sym": bool(schema.get("requires_symbol")),
            "bm": bool(schema.get("requires_benchmark")),
            "args": [
                f"{arg['name']}:{arg['type']}:{int(bool(arg['required']))}:{arg['source']}"
                for arg in schema.get("args") or []
            ],
        }
    assert actual == expected


def test_schema_t6_has_four_shapes():
    schemas = param_schema.all_schemas()
    assert [a["name"] for a in schemas["D-E16"]["args"]] == ["series"]
    assert [a["name"] for a in schemas["D-E17"]["args"]] == ["assets"]
    assert [a["name"] for a in schemas["D-E18"]["args"]] == ["flows"]
    assert [a["name"] for a in schemas["D-E19"]["args"]] == ["block"]


def test_schema_derived_forward():
    schema = param_schema.for_capability("D-E08")
    args = {arg["name"]: arg for arg in schema["args"]}
    assert args["factor"]["source"] == "derived"
    assert args["forward"]["derived_by"] == "forward_returns(1)"


# ---------------------------------------------------------------- 装配
def test_momentum_warmup_trim():
    close = [1.0 + i * 0.01 for i in range(100)]
    factor = cr.momentum_20d(close)
    assert factor[:20] == [None] * 20
    cols, trimmed = cr.trim(factor, close)
    assert trimmed == 20
    assert len(cols[0]) == len(cols[1]) == 80


def test_forward_returns_is_not_price():
    close = [100.0, 110.0, 121.0]
    forward = cr.forward_returns(close, 1)
    assert forward[-1] is None
    assert math.isclose(forward[0], 0.1, rel_tol=1e-9)
    assert math.isclose(forward[1], 0.1, rel_tol=1e-9)
    cols, _ = cr.trim(cr.momentum_20d([1.0] * 60), [1.0] * 60)
    assert cols is not None


def test_custom_series_rejects_bad_input():
    too_long = {
        "dates": [f"{2000 + i // 365}-{i % 12 + 1:02d}-01" for i in range(6000)],
        "values": [1.0] * 6000,
    }
    unsorted = {"dates": ["2020-01-03", "2020-01-01"], "values": [1.0, 2.0]}
    for payload in (too_long, unsorted):
        result = cr.resolve("D-A04", {"custom_series": payload})
        assert result["code"] == "invalid_params"
    nan_case = {"dates": ["2020-01-01", "2020-01-02"], "values": [1.0, float("nan")]}
    assert cr.resolve("D-A04", {"custom_series": nan_case})["code"] == "invalid_params"


def test_unsupported_and_missing():
    assert cr.resolve("D-A16")["code"] == "unsupported"
    assert cr.resolve("D-G23")["code"] == "unsupported"
    # E19 依赖主览图 lights 块（上游产物），卡片直连时按 product_missing 明示
    assert cr.resolve("D-E19")["code"] == "product_missing"
    assert cr.resolve("D-UNKNOWN")["code"] == "not_found"


def test_requires_user_params():
    j30 = cr.resolve("D-J30")
    assert j30["code"] == "missing_args"
    assert j30["missing_params"] == ["indicator"]
    for capability_id, expected in (
        ("D-J25", ["coords"]),
        ("D-J26", ["time", "event"]),
        ("D-J27", ["time", "event"]),
        ("D-J28", ["effects", "se"]),
    ):
        result = cr.resolve(capability_id)
        assert result["code"] == "missing_args"
        assert result["missing_params"] == expected


# ---------------------------------------------------------------- 集成（需 DB）
@_needs_db
def test_e17_assets_mapping():
    result = cr.resolve("D-E17", {"assets": ["BTC", "ETH"]})
    assert result["code"] == "ok"
    assert result["quality"]["n"] > 0


@_needs_db
def test_a11_cross_asset_pair():
    result = cr.resolve("D-A11", {"symbol": "BTC", "benchmark": "US500"})
    assert result["code"] == "ok"
    assert result["meta"]["warmup_trimmed"] == 0
