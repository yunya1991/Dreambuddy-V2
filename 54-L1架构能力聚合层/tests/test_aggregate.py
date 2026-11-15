# -*- coding: utf-8 -*-
"""D-E16 聚合曲线 + D-E17 类别看板（SPEC-54-L1交易层 §4.3 / §4.4，P0-3）。

覆盖：
  - `base_date = max(各成员首个可用日)`，全部成员当日 rebase=100；
  - 先归一后加权（原始价格禁止直接加权）；
  - 短样本成员剔除 + 剩余权重重归一；
  - 每点 `coverage_ratio` / `<0.8 → partial_members`；**无前向填充**；
  - `chart_weights_hash` 覆盖最终展示权重且可复现；
  - D-E17 固定 19 列 / 组内 `ret_60` 降序 / 降级首列 / 点亮计数零重算；
  - 信封与 JSON Schema 一致。
"""

import datetime
import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import chart_weights  # noqa: E402
from l1agg.capabilities.aggregate import (  # noqa: E402
    COVERAGE_FLOOR,
    aggregate_block,
    aggregate_curve,
    class_board,
)
from l1agg.capabilities.visual import CLASS_BOARD_COLUMNS  # noqa: E402

CAVEAT = "历史统计，不代表未来"
DIRECTION_WORDS = ("看涨", "看跌", "建议", "目标价")


def _dates(n, start=datetime.date(2024, 1, 1)):
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _series(n, *, base=100.0, drift=1.0, start=datetime.date(2024, 1, 1)):
    days = _dates(n, start)
    return {day: base + drift * i + (i * 7) % 5 for i, day in enumerate(days)}


# ------------------------------------------------------------ D-E16


def test_base_date_is_latest_first_available_day():
    btc = _series(300)
    eth = _series(300, base=50.0, drift=2.0, start=datetime.date(2024, 2, 1))
    out = aggregate_curve({"BTC": btc, "ETH": eth}, weights={"BTC": 0.6, "ETH": 0.4})
    block = out["data"]["capabilities"]["D-E16"]
    assert block["meta"]["base_date"] == "2024-02-01"
    first = block["points"][0]
    assert first["date"] == "2024-02-01"
    assert first["members"] == {"BTC": 100.0, "ETH": 100.0}
    assert first["agg"] == pytest.approx(100.0)


def test_short_member_pruned_and_weights_renormalized():
    btc = _series(300)
    eth = _series(100)
    out = aggregate_curve({"BTC": btc, "ETH": eth}, weights={"BTC": 0.6, "ETH": 0.4})
    meta = out["data"]["capabilities"]["D-E16"]["meta"]
    assert meta["pruned"] is True
    dropped = {item["symbol"]: item for item in meta["dropped"]}
    assert dropped["ETH"]["reason"] == "insufficient_history"
    assert dropped["ETH"]["n"] == 100
    assert meta["chart_weights"] == {"BTC": 1.0}
    assert meta["members"][0]["status"] == "available"
    assert all(
        "ETH" not in point["members"] for point in out["data"]["capabilities"]["D-E16"]["points"]
    )


def test_no_forward_fill_and_coverage_ratio_per_point():
    btc = _series(300)
    eth = _series(300, base=50.0)
    gap = _dates(300)[100]
    eth.pop(gap)
    out = aggregate_curve(
        {"BTC": btc, "ETH": eth},
        weights={"BTC": 0.6, "ETH": 0.4},
        min_rows=100,
    )
    block = out["data"]["capabilities"]["D-E16"]
    point = next(item for item in block["points"] if item["date"] == gap)
    assert "ETH" not in point["members"]  # 不做前向填充
    assert point["coverage_ratio"] == pytest.approx(0.6)
    assert point["partial_members"] is True
    assert block["meta"]["min_coverage"] == pytest.approx(0.6)
    assert out["quality"]["status"] == "partial"
    assert out["data"]["visual"]["dataset"]["meta"]["base_date"] == "2024-01-01"


def test_rebase_before_weighting_not_raw_prices():
    btc = _series(300, base=60000.0, drift=120.0)
    spx = _series(300, base=5000.0, drift=2.0)
    out = aggregate_curve({"BTC": btc, "SPX": spx}, weights={"BTC": 0.5, "SPX": 0.5})
    points = out["data"]["capabilities"]["D-E16"]["points"]
    assert points[0]["agg"] == pytest.approx(100.0)
    last = points[-1]
    expected = 0.5 * (btc[last["date"]] / btc["2024-01-01"]) * 100.0
    expected += 0.5 * (spx[last["date"]] / spx["2024-01-01"]) * 100.0
    assert last["agg"] == pytest.approx(expected)


def test_visual_series_contract_and_smoothing_meta():
    out = aggregate_curve(
        {"BTC": _series(300), "ETH": _series(300, base=50.0)},
        weights={"BTC": 0.6, "ETH": 0.4},
    )
    visual = out["data"]["visual"]
    assert visual["kind"] == "series"
    assert visual["spec_version"] == "1.0"
    assert visual["source_capability"] == "D-E16"
    assert visual["n_scope"] == "global"
    assert len(visual["title"]) <= 60
    meta = visual["dataset"]["meta"]
    assert meta["smoothing"] == {"method": "EMA", "window": 26}
    assert meta["normalize"] == "rebased_100"
    assert meta["unit"] == "rebased_index"
    assert meta["n"] == 300
    assert len(meta["chart_weights_hash"]) == 64
    point = visual["dataset"]["points"][-1]
    assert point["y"] == pytest.approx(point["agg"])
    assert set(point["members"]) == {"BTC", "ETH"}
    assert 0.0 <= point["coverage_ratio"] <= 1.0
    assert point["smoothed"] is not None


def test_chart_weights_hash_covers_effective_weights_and_is_deterministic():
    series = {"BTC": _series(300), "ETH": _series(300, base=50.0)}
    first = aggregate_curve(series, weights={"BTC": 0.6, "ETH": 0.4})
    second = aggregate_curve(series, weights={"BTC": 0.6, "ETH": 0.4})
    meta = first["data"]["capabilities"]["D-E16"]["meta"]
    assert meta["chart_weights_hash"] == chart_weights.chart_weights_hash(meta["chart_weights"])
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_mode_off_falls_back_to_equal_weights():
    cfg = chart_weights.load()
    out = aggregate_curve(
        {"BTC": _series(300), "ETH": _series(300, base=50.0)},
        weights=cfg,
        mode="off",
    )
    meta = out["data"]["capabilities"]["D-E16"]["meta"]
    assert meta["chart_weights_source"] == "equal"
    assert meta["chart_weights"]["BTC"] == pytest.approx(0.5, abs=1e-4)
    assert meta["chart_weights"]["ETH"] == pytest.approx(0.5, abs=1e-4)


def test_empty_series_returns_unavailable_without_fake_curve():
    out = aggregate_curve({})
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"
    assert "visual" not in out["data"]


def test_no_direction_words_in_answer():
    out = aggregate_curve({"BTC": _series(300)}, weights={"BTC": 1.0})
    for word in DIRECTION_WORDS:
        assert word not in out["answer"]
    assert CAVEAT in out["answer"]


def test_aggregate_validates_against_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    out = aggregate_curve(
        {"BTC": _series(300), "ETH": _series(300, base=50.0)},
        weights={"BTC": 0.6, "ETH": 0.4},
    )
    jsonschema.validate(instance=out, schema=schema)


def test_block_gate_not_ok_when_no_member_has_history():
    block = aggregate_block({}, weights={"BTC": 1.0})
    assert block["gate"] != "ok"
    assert block["reason"] == "no_member_with_history"


def test_coverage_floor_matches_spec():
    assert COVERAGE_FLOOR == 0.8


# ------------------------------------------------------------ D-E17


def _board_assets():
    return {
        "BTC": {
            "prices": list(_series(300, drift=1.0).values()),
            "view": "加密",
            "role": "leader",
            "label": "比特币",
        },
        "ETH": {
            "prices": list(_series(300, base=50.0, drift=3.0).values()),
            "view": "加密",
            "role": "member",
            "label": "以太坊",
        },
        "XAU": {
            "prices": list(_series(300, base=2000.0).values()),
            "view": "避险",
            "role": "leader",
            "label": "黄金",
        },
        "US500": {
            "prices": list(_series(300, base=5000.0, drift=0.5).values()),
            "view": "美股",
            "role": "co_leader",
            "label": "标普500",
        },
    }


def test_class_board_columns_are_fixed_19_in_order():
    out = class_board(_board_assets(), light_ref="light-hash")
    visual = out["data"]["visual"]
    assert visual["kind"] == "table"
    assert visual["source_capability"] == "D-E17"
    assert visual["n_scope"] == "per_row"
    assert visual["dataset"]["groups"] == ["class", "role"]
    keys = [col["key"] for col in visual["dataset"]["columns"]]
    assert keys == [col["key"] for col in CLASS_BOARD_COLUMNS]
    assert len(keys) == 19
    assert keys[0] == "class" and keys[-1] == "status"


def test_class_board_sorted_by_view_order_then_ret_60_desc():
    out = class_board(_board_assets())
    rows = out["data"]["capabilities"]["D-E17"]["rows"]
    assert [row["symbol"] for row in rows] == ["ETH", "BTC", "XAU", "US500"]
    crypto = [row for row in rows if row["class"] == "加密"]
    assert crypto[0]["ret_60"] >= crypto[1]["ret_60"]
    assert rows[0]["ret_60"] == pytest.approx(
        _board_assets()["ETH"]["prices"][-1] / _board_assets()["ETH"]["prices"][-61] - 1.0,
        abs=1e-6,
    )


def test_class_board_degraded_member_prepends_reason_column():
    assets = _board_assets()
    assets["XAG"] = {
        "prices": list(_series(100, base=25.0).values()),
        "view": "避险",
        "role": "member",
        "label": "白银",
    }
    out = class_board(assets)
    visual = out["data"]["visual"]
    keys = [col["key"] for col in visual["dataset"]["columns"]]
    assert keys[0] == "degraded_reason"
    assert len(keys) == 20
    rows = {row["symbol"]: row for row in visual["dataset"]["rows"]}
    assert rows["XAG"]["status"] == "partial"
    assert rows["XAG"]["degraded_reason"] == "history_lt_min_rows"
    assert rows["BTC"]["degraded_reason"] is None
    assert out["quality"]["status"] == "partial"


def test_class_board_lights_counts_come_from_input_not_recomputed():
    assets = _board_assets()
    assets["BTC"].update({"lit_n": 3, "warm_n": 2})
    out = class_board(assets, light_ref="abc123")
    rows = {row["symbol"]: row for row in out["data"]["capabilities"]["D-E17"]["rows"]}
    assert rows["BTC"]["lit_n"] == 3
    assert rows["BTC"]["warm_n"] == 2
    assert rows["BTC"]["lights_ref"] == "abc123"
    assert rows["ETH"]["lights_ref"] == "abc123"
    assert rows["ETH"]["lit_n"] == 0


def test_class_board_metrics_are_statistical_facts():
    out = class_board(_board_assets())
    row = out["data"]["capabilities"]["D-E17"]["rows"][0]
    assert row["n"] == 300
    assert row["status"] == "available"
    assert row["vol_60"] is not None and row["vol_60"] >= 0.0
    assert 0.0 <= row["mdd"] <= 1.0
    assert row["adx14"] is None  # 未提供 high/low，不伪造 ADX
    assert row["corr_to_leader_90d"] is None


def test_class_board_corr_to_leader_uses_return_overlap():
    assets = _board_assets()
    assets["ETH"]["prices"] = [price * 2.0 for price in assets["BTC"]["prices"]]
    assets["ETH"]["leader_prices"] = assets["BTC"]["prices"]
    out = class_board(assets)
    rows = {row["symbol"]: row for row in out["data"]["capabilities"]["D-E17"]["rows"]}
    assert rows["ETH"]["corr_to_leader_90d"] == pytest.approx(1.0, abs=1e-6)


def test_class_board_adx14_uses_registered_method_when_hl_given():
    assets = _board_assets()
    prices = assets["BTC"]["prices"]
    assets["BTC"]["highs"] = [price * 1.01 for price in prices]
    assets["BTC"]["lows"] = [price * 0.99 for price in prices]
    out = class_board(assets)
    rows = {row["symbol"]: row for row in out["data"]["capabilities"]["D-E17"]["rows"]}
    assert rows["BTC"]["adx14"] is not None
    assert rows["BTC"]["adx14"] >= 0.0


def test_class_board_no_direction_words_and_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema_path = os.path.join(_MODULE_ROOT, "contracts", "capability_result.schema.json")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    out = class_board(_board_assets())
    for word in DIRECTION_WORDS:
        assert word not in out["answer"]
    jsonschema.validate(instance=out, schema=schema)
