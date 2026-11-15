# -*- coding: utf-8 -*-
"""动态权重切换层单测：三档开关 / 状态恢复 / 等权对照 / 注入与不注入。"""

import math
import os
import sys

import pytest
import yaml

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.direction_rule import DEFAULT_PARAMS  # noqa: E402
from l1agg.trading import store, weight_switch, weights  # noqa: E402

_N = 300


def _axes(n: int = _N):
    base = [math.sin(i / 9.0) for i in range(n)]
    return {
        "trend": list(base),
        "adx": [0.5 * v for v in base],
        "inertia": [0.3 * v for v in base],
        "coherence": [0.2 * v for v in base],
    }


def _fwd(n: int = _N):
    return [0.01 * math.sin(i / 9.0) for i in range(n)]


_GOOD_EXCESS = [0.002] * _N


def _config(tmp_path, mode: str):
    path = tmp_path / "weights.yaml"
    path.write_text(yaml.safe_dump({"weights": {"mode": mode}}), encoding="utf-8")
    return str(path)


# ---------------- 开关 ----------------


def test_shipped_config_defaults_to_off():
    cfg = weight_switch.load_config()
    assert cfg["mode"] == "off"
    assert cfg["window"] == weights.WINDOW
    assert cfg["min_labels"] == weights.MIN_OBS


def test_invalid_mode_fails_closed(tmp_path):
    with pytest.raises(weight_switch.WeightSwitchError):
        weight_switch.normalize_mode("live")
    with pytest.raises(weight_switch.WeightSwitchError):
        weight_switch.resolve_mode(environ={"L1_DYNAMIC_WEIGHTS": "bogus"})
    bad = tmp_path / "bad.yaml"
    bad.write_text("weights:\n  mode: turbo\n", encoding="utf-8")
    with pytest.raises(weight_switch.WeightSwitchError):
        weight_switch.load_config(str(bad))


def test_precedence_explicit_over_env_over_config(tmp_path):
    cfg = _config(tmp_path, "off")
    assert weight_switch.resolve_mode(None, environ={}, config_path=cfg) == "off"
    assert (
        weight_switch.resolve_mode(None, environ={"L1_DYNAMIC_WEIGHTS": "shadow"}, config_path=cfg)
        == "shadow"
    )
    assert (
        weight_switch.resolve_mode("on", environ={"L1_DYNAMIC_WEIGHTS": "shadow"}, config_path=cfg)
        == "on"
    )


# ---------------- 解析 ----------------


def test_off_returns_static_weights_and_never_injects():
    resolved = weight_switch.resolve_weights(mode="off")
    assert resolved["weights"] == weights.STATIC_WEIGHTS
    assert resolved["weights_hash"] == weights.weights_hash(weights.STATIC_WEIGHTS)
    assert resolved["inject"] is False
    assert resolved["inject_axis_weights"] is None
    assert "dynamic_disabled" in resolved["flags"]


def test_shadow_computes_weights_but_does_not_inject():
    resolved = weight_switch.resolve_weights(
        _axes(), _fwd(), mode="shadow", oos_excess=_GOOD_EXCESS
    )
    assert resolved["gate"]["passed"] is True
    assert resolved["weight_fallback"] is False
    assert resolved["inject"] is False
    assert resolved["weights"] != weights.STATIC_WEIGHTS
    assert resolved["weights_hash"] == weights.weights_hash(resolved["weights"])
    assert resolved["weight_sources"]["ic"]["trend"] > 0.9


def test_on_injects_gate_passed_weights():
    resolved = weight_switch.resolve_weights(_axes(), _fwd(), mode="on", oos_excess=_GOOD_EXCESS)
    assert resolved["inject"] is True
    injected = resolved["inject_axis_weights"]
    assert set(injected) == set(weights.AXES)
    assert abs(sum(injected.values()) - 1.0) < 1e-6
    assert all(weights.MIN_WEIGHT <= v <= weights.MAX_WEIGHT for v in injected.values())

    params = weight_switch.apply_to_params(DEFAULT_PARAMS, resolved)
    assert params["axis_weights"] == injected
    assert params["version"] == DEFAULT_PARAMS["version"]


def test_on_falls_back_to_static_when_gate_fails():
    resolved = weight_switch.resolve_weights(
        _axes(), _fwd(), mode="on", oos_excess=_GOOD_EXCESS[:10]
    )
    assert resolved["weight_fallback"] is True
    assert resolved["weights"] == weights.EQUAL_WEIGHTS
    assert resolved["inject"] is False
    assert weight_switch.apply_to_params(DEFAULT_PARAMS, resolved) == dict(DEFAULT_PARAMS)


def test_recorded_weights_keep_static_on_veto_and_computed_otherwise():
    vetoed = weight_switch.resolve_weights(_axes(), _fwd(), mode="on", oos_excess=_GOOD_EXCESS[:10])
    recorded = weight_switch.recorded_weights(vetoed)
    assert recorded["weights"] == weights.STATIC_WEIGHTS
    assert recorded["weights_hash"] == weights.weights_hash(weights.STATIC_WEIGHTS)
    assert recorded["axis_weights"]["gap"] == 0.0

    passed = weight_switch.resolve_weights(_axes(), _fwd(), mode="on", oos_excess=_GOOD_EXCESS)
    kept = weight_switch.recorded_weights(passed)
    assert kept["weights"] == passed["weights"] != weights.STATIC_WEIGHTS
    assert kept["weights_hash"] == passed["weights_hash"]
    assert abs(sum(v for k, v in kept["axis_weights"].items() if k != "gap") - 1.0) < 1e-6


# ---------------- 等权对照与状态 ----------------


def test_oos_excess_series_is_zero_against_equal_weights():
    axes, fwd = _axes(), _fwd()
    zeros = weight_switch.oos_excess_series(axes, fwd, weights.EQUAL_WEIGHTS, window=_N)
    assert len(zeros) == _N
    assert all(value == 0.0 for value in zeros)
    static_excess = weight_switch.oos_excess_series(axes, fwd, weights.STATIC_WEIGHTS, window=_N)
    assert len(static_excess) == _N
    assert any(value != 0.0 for value in static_excess)
    assert len(weight_switch.oos_excess_series(axes, fwd, weights.STATIC_WEIGHTS)) == 250
    assert weight_switch.oos_excess_series(axes, fwd, None) == []


def test_load_state_reads_latest_weights_from_signal(tmp_path):
    db = str(tmp_path / "trading.db")
    store.migrate(db)
    assert weight_switch.load_state("BTC-USDT", db)["source"] == "none"
    for as_of in ("2026-11-02", "2026-11-09"):
        store.append_signal(
            {
                "as_of": as_of,
                "symbol": "BTC-USDT",
                "rule_version": DEFAULT_PARAMS["version"],
                "params_hash": "p",
                "direction": 1,
                "strength": 0.5,
                "inputs_snapshot": {},
                "weights_version": weights.WEIGHTS_VERSION,
                "weights_hash": "h",
                "weights_effective_date": as_of,
                "axis_weights": {
                    "trend": 0.4,
                    "adx": 0.25,
                    "inertia": 0.2,
                    "coherence": 0.15,
                    "gap": 0.0,
                },
                "weight_sources": {},
            },
            db,
        )
    state = weight_switch.load_state("BTC-USDT", db)
    assert state["source"] == "db"
    assert state["last_effective_date"] == "2026-11-09"
    assert state["weights_version"] == weights.WEIGHTS_VERSION
    assert state["previous_weights"] == weights.STATIC_WEIGHTS
    assert weight_switch.load_state("ETH-USDT", db)["source"] == "none"


def test_load_state_missing_db_is_fail_open(tmp_path):
    target = str(tmp_path / "absent.db")
    state = weight_switch.load_state("BTC-USDT", target)
    assert state["source"] == "none"
    assert not os.path.exists(target)
