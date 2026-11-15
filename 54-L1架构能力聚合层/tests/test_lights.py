# -*- coding: utf-8 -*-
"""D-E19 信号点亮投影（SPEC-54-L1交易层 §5.2 / §5.3，P0-4）。

覆盖：
  - 五档状态边界（`lit/warm/dim` 阈值、`conflict` 只读旗标、`unavailable` 优先）；
  - 轴值零重算：`axes.*.strength == |axis_value| / axis_weight`（≤1e-9）；
  - 总体 `strength = Σ lw × norm`，缺失轴剔除后按剩余权重重新归一；
  - 短样本 / `gate != ok` / `not_collected` → 整标的不可点亮（LT-G6）；
  - 权重运行期非法 → 等权降级；`mode=off` → 等权回滚档；
  - `light_weights_hash` 确定且随阈值变化；同输入字节一致（LT-G3）；
  - 无方向措辞（LT-G1）与信封契约（`data.lights`，无 `visual`）。
"""

import json
import math
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import chart_weights  # noqa: E402
from l1agg.capabilities.lights import (  # noqa: E402
    AXES,
    BUCKETS,
    CONFLICT_FLAGS,
    DEFAULT_THRESHOLDS,
    STATES,
    axes_from_direction,
    light_block,
    lights,
    normalize_axis,
    resolve_light_weights,
    resolve_thresholds,
)

CONFIG_WEIGHTS = {"trend": 0.40, "inertia": 0.25, "cycle": 0.15, "foresight": 0.20}
THRESHOLDS = {"lit_pct": 0.70, "warm_pct": 0.40}
DIRECTION_WORDS = ("看涨", "看跌", "建议", "目标价")


def _entry(symbol="BTC", *, axes=None, n=300, **kwargs):
    entry = {"symbol": symbol, "class": "crypto", "as_of": "2026-11-14", "n": n}
    if axes is not None:
        entry["axes"] = axes
    entry.update(kwargs)
    return entry


def _flat(strength):
    return dict.fromkeys(AXES, strength)


def _block(entries, **kwargs):
    kwargs.setdefault("weights", CONFIG_WEIGHTS)
    kwargs.setdefault("thresholds", THRESHOLDS)
    return light_block(entries, **kwargs)


# ------------------------------------------------------------ 常量与归一


def test_state_and_bucket_whitelists():
    assert STATES == ("lit", "warm", "dim", "conflict", "unavailable")
    assert BUCKETS == ("high", "mid", "low", "none")
    assert "curve_inverted" in CONFLICT_FLAGS
    assert "vix_pct_ge_0.90" in CONFLICT_FLAGS
    assert DEFAULT_THRESHOLDS == {"lit_pct": 0.70, "warm_pct": 0.40}


def test_normalize_axis_is_zero_recompute():
    assert normalize_axis(40.0, 40.0) == 1.0
    assert normalize_axis(-20.0, 40.0) == pytest.approx(0.5)
    assert normalize_axis(15.0, 15.0) == 1.0
    assert normalize_axis(None, 40.0) is None
    assert normalize_axis(1.0, 0.0) is None
    # 越界不放大：轴值超权重重时截断到 1
    assert normalize_axis(80.0, 40.0) == 1.0


def test_axes_from_direction_maps_internal_axes():
    scored = {
        "axes": {"trend": 30.0, "adx": 12.5, "inertia": -5.0, "coherence": 7.5},
        "axis_weights": {"trend": 40.0, "adx": 25.0, "inertia": 20.0, "coherence": 15.0},
    }
    facts = axes_from_direction(
        scored, cycle={"strength": 0.21, "flags": ["seasonality_depth_lt_5y"]}
    )
    assert facts["trend"]["strength"] == pytest.approx(0.75)
    assert facts["inertia"]["strength"] == pytest.approx(0.25)
    assert facts["foresight"]["strength"] == pytest.approx(0.5)
    assert facts["cycle"]["strength"] == pytest.approx(0.21)
    assert facts["cycle"]["flags"] == ["seasonality_depth_lt_5y"]
    assert facts["cycle"]["capability"] == "I39"
    # adx 不进入点亮轴
    assert set(facts) == set(AXES)


# ------------------------------------------------------------ 五档边界


def test_five_state_boundaries():
    block = _block(
        [
            _entry(
                axes={
                    "trend": 0.70,  # == lit_pct → lit
                    "inertia": 0.699,  # < lit_pct → warm
                    "cycle": 0.40,  # == warm_pct → warm
                    "foresight": 0.399,  # < warm_pct → dim
                }
            )
        ]
    )
    axes = block["lights"][0]["axes"]
    assert (axes["trend"]["state"], axes["trend"]["bucket"]) == ("lit", "high")
    assert (axes["inertia"]["state"], axes["inertia"]["bucket"]) == ("warm", "mid")
    assert (axes["cycle"]["state"], axes["cycle"]["bucket"]) == ("warm", "mid")
    assert (axes["foresight"]["state"], axes["foresight"]["bucket"]) == ("dim", "low")
    assert block["lights"][0]["summary"] == {
        "lit_n": 1,
        "warm_n": 2,
        "conflict_n": 0,
        "unavailable_n": 0,
    }


def test_overall_strength_is_weighted_sum():
    entry = _entry(axes={"trend": 0.5, "inertia": 0.5, "cycle": 0.2, "foresight": 0.5})
    row = _block([entry])["lights"][0]
    expected = 0.40 * 0.5 + 0.25 * 0.5 + 0.15 * 0.2 + 0.20 * 0.5
    assert row["strength"] == pytest.approx(expected, abs=1e-9)


def test_scored_input_matches_internal_normalized_value():
    """LT-AC3：点亮轴强度必须等于内部轴分解归一值（±1e-9，不重算）。"""
    scored = {
        "axes": {"trend": 36.4, "adx": 0.0, "inertia": 8.0, "coherence": -12.0},
        "axis_weights": {"trend": 40.0, "adx": 25.0, "inertia": 20.0, "coherence": 15.0},
    }
    row = _block([_entry(scored=scored, cycle={"strength": 0.3})])["lights"][0]
    assert row["axes"]["trend"]["strength"] == pytest.approx(36.4 / 40.0, abs=1e-9)
    assert row["axes"]["inertia"]["strength"] == pytest.approx(8.0 / 20.0, abs=1e-9)
    assert row["axes"]["foresight"]["strength"] == pytest.approx(12.0 / 15.0, abs=1e-9)
    assert row["axes"]["cycle"]["strength"] == pytest.approx(0.3, abs=1e-9)


# ------------------------------------------------------------ conflict 只读旗标


def test_conflict_triggered_by_readonly_flag_not_strength():
    entry = _entry(
        axes={
            "trend": 0.85,
            "inertia": 0.30,
            "cycle": 0.20,
            "foresight": {"strength": 0.62, "flags": ["curve_inverted"]},
        }
    )
    row = _block([entry])["lights"][0]
    assert row["axes"]["trend"]["state"] == "lit"
    assert row["axes"]["foresight"]["state"] == "conflict"
    # bucket 仍由 strength 决定，与 state 无关
    assert row["axes"]["foresight"]["bucket"] == "mid"
    assert row["summary"]["conflict_n"] == 1
    assert "curve_inverted" in row["flags"]


def test_conflict_not_triggered_when_trend_not_lit():
    entry = _entry(
        axes={
            "trend": 0.69,
            "inertia": 0.30,
            "cycle": 0.20,
            "foresight": {"strength": 0.62, "flags": ["vix_pct_ge_0.90"]},
        }
    )
    row = _block([entry])["lights"][0]
    assert row["axes"]["trend"]["state"] == "warm"
    assert row["axes"]["foresight"]["state"] == "warm"
    assert row["summary"]["conflict_n"] == 0


def test_conflict_flag_via_foresight_flags_input():
    scored = {
        "axes": {"trend": 40.0, "inertia": 0.0, "coherence": 9.0},
        "axis_weights": {"trend": 40.0, "inertia": 20.0, "coherence": 15.0},
    }
    row = _block(
        [_entry(scored=scored, cycle={"strength": 0.2}, foresight_flags=["vix_divergence"])]
    )["lights"][0]
    assert row["axes"]["foresight"]["state"] == "conflict"


# ------------------------------------------------------------ unavailable 优先


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"n": 179}, "history_lt_250"),
        ({"n": 300, "status": "not_collected"}, "status_not_collected"),
        ({"n": 300, "gate": "gate_failed"}, "gate_gate_failed"),
    ],
)
def test_unavailable_takes_precedence(kwargs, reason):
    row = _block([_entry(axes=_flat(0.99), **kwargs)])["lights"][0]
    assert row["status"] == "unavailable"
    assert row["strength"] is None
    assert row["summary"]["unavailable_n"] == len(AXES)
    assert row["summary"]["lit_n"] == 0
    assert reason in row["flags"]
    assert all(axis_row["state"] == "unavailable" for axis_row in row["axes"].values())


def test_short_symbol_does_not_block_long_symbol():
    block = _block(
        [
            _entry("BTC", axes=_flat(0.8), n=300),
            _entry("GEV", axes=_flat(0.8), n=179, min_rows=250),
        ]
    )
    by_symbol = {row["symbol"]: row for row in block["lights"]}
    assert by_symbol["BTC"]["status"] == "available"
    assert by_symbol["GEV"]["status"] == "unavailable"


def test_missing_axis_excluded_and_weights_renormalized():
    entry = _entry(axes={"trend": 0.8, "inertia": 0.4, "cycle": None, "foresight": 0.6})
    row = _block([entry])["lights"][0]
    assert row["axes"]["cycle"]["state"] == "unavailable"
    assert row["axes"]["cycle"]["strength"] is None
    assert row["status"] == "partial"
    total = 0.40 + 0.25 + 0.20
    expected = (0.40 * 0.8 + 0.25 * 0.4 + 0.20 * 0.6) / total
    assert row["strength"] == pytest.approx(expected, abs=1e-6)
    assert "axis_missing_cycle" in row["flags"]


# ------------------------------------------------------------ 权重/阈值降级


def test_invalid_light_weights_degrade_to_equal():
    row = _block(
        [_entry(axes=_flat(0.5))],
        weights={"trend": 0.5, "inertia": 0.5, "cycle": 0.5, "foresight": 0.5},
    )["lights"][0]
    assert row["strength"] == pytest.approx(0.5, abs=1e-9)
    block = _block(
        [_entry(axes=_flat(0.5))],
        weights={"trend": 0.5, "inertia": 0.5, "cycle": 0.5, "foresight": 0.5},
    )
    assert block["meta"]["weights_degraded"] is True
    assert block["meta"]["light_weights_source"] == "equal"
    assert block["meta"]["light_weights"] == dict.fromkeys(AXES, 0.25)
    assert "light_weights_invalid" in block["meta"]["flags"]


def test_mode_off_rolls_back_to_equal():
    block = _block([_entry(axes=_flat(0.5))], mode="off")
    assert block["meta"]["light_weights_mode"] == "off"
    assert block["meta"]["light_weights_source"] == "equal"
    assert block["meta"]["light_weights"] == dict.fromkeys(AXES, 0.25)
    assert "light_weights_off" in block["meta"]["flags"]


def test_invalid_thresholds_fall_back_to_defaults():
    resolved = resolve_thresholds(None, {"lit_pct": 0.3, "warm_pct": 0.8})
    assert resolved["thresholds"] == DEFAULT_THRESHOLDS
    assert resolved["flags"] == ["thresholds_invalid"]


def test_resolve_light_weights_fail_open():
    resolved = resolve_light_weights(None, {})
    assert resolved["weights"] == dict.fromkeys(AXES, 0.25)
    assert resolved["weights_degraded"] is True


# ------------------------------------------------------------ 指纹（LT-G3）


def test_hash_is_deterministic_and_byte_identical():
    entries = [_entry(axes=_flat(0.55), n=250)]
    first = _block(entries)
    second = _block([_entry(axes=_flat(0.55), n=250)])
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(
        second, sort_keys=True, ensure_ascii=False
    )
    assert first["meta"]["light_weights_hash"] == second["meta"]["light_weights_hash"]
    assert first["lights"][0]["light_weights_hash"] == first["meta"]["light_weights_hash"]


def test_hash_matches_chart_weights_light_hash():
    block = _block([_entry(axes=_flat(0.5))])
    expected = chart_weights.light_weights_hash(CONFIG_WEIGHTS, THRESHOLDS)
    assert block["meta"]["light_weights_hash"] == expected


def test_hash_changes_with_thresholds():
    base = _block([_entry(axes=_flat(0.5))])
    moved = _block([_entry(axes=_flat(0.5))], thresholds={"lit_pct": 0.45, "warm_pct": 0.20})
    assert base["meta"]["light_weights_hash"] != moved["meta"]["light_weights_hash"]
    assert base["lights"][0]["axes"]["trend"]["state"] == "warm"
    assert moved["lights"][0]["axes"]["trend"]["state"] == "lit"


# ------------------------------------------------------------ 信封契约


def test_envelope_contract_and_no_direction_words():
    out = lights(
        [_entry("BTC", axes=_flat(0.8)), _entry("GEV", axes=_flat(0.1), n=179)],
        weights=CONFIG_WEIGHTS,
        thresholds=THRESHOLDS,
    )
    assert out["ok"] is True
    assert out["capability"] == "D-E19"
    assert out["quality"]["status"] == "partial"
    assert [row["symbol"] for row in out["data"]["lights"]] == ["BTC", "GEV"]
    assert out["data"]["capabilities"]["D-E19"]["gate"] == "ok"
    assert "visual" not in out["data"]
    dumped = json.dumps(out, ensure_ascii=False)
    for word in DIRECTION_WORDS:
        assert word not in dumped


def test_envelope_good_quality_when_all_axes_available():
    out = lights([_entry(axes=_flat(0.8))], weights=CONFIG_WEIGHTS, thresholds=THRESHOLDS)
    assert out["quality"]["status"] == "good"
    assert out["quality"]["sample_n"] == 300
    assert out["data"]["lights"][0]["status"] == "available"


def test_empty_entries_handoff():
    out = lights([])
    assert out["ok"] is False
    assert out["quality"]["status"] == "empty"
    assert "lights" not in out["data"]


def test_meta_declares_uncalibrated_thresholds_by_default():
    block = _block([_entry(axes=_flat(0.5))])
    assert block["meta"]["thresholds_uncalibrated"] is True
    assert block["meta"]["min_rows"] == 250
    assert math.isclose(sum(block["meta"]["light_weights"].values()), 1.0, abs_tol=1e-9)
