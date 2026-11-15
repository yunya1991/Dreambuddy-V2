# -*- coding: utf-8 -*-
"""L1D-05 纸面回放单测：signal 历史 / 胜率与换手 / 同一 as_of 可重放。"""

import datetime
import json
import math
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.direction_rule import DEFAULT_PARAMS  # noqa: E402
from l1agg.trading import paper_replay, store, weights  # noqa: E402

_N = 380
_WARMUP = paper_replay.DEFAULT_WARMUP
_CACHE = {}


def _series(n: int = _N):
    """确定性合成序列：250 根弱升 → 60 根急升 → 剩余急跌（日内带正弦噪声）。"""
    prices, dates, highs, lows = [], [], [], []
    price = 100.0
    start = datetime.date(2026, 1, 1)
    for i in range(n):
        if i < 250:
            drift = 0.0006
        elif i < 310:
            drift = 0.004
        else:
            drift = -0.005
        price *= 1.0 + drift + 0.004 * math.sin(i / 5.0)
        prices.append(round(price, 6))
        dates.append((start + datetime.timedelta(days=i)).isoformat())
        highs.append(round(price * 1.004, 6))
        lows.append(round(price * 0.996, 6))
    return prices, dates, highs, lows


def _base():
    if "r" not in _CACHE:
        px, ds, hi, lo = _series()
        _CACHE["r"] = paper_replay.replay(px, symbol="BTC-USDT", dates=ds, highs=hi, lows=lo)
    return _CACHE["r"]


def test_replay_is_deterministic():
    first = _base()
    px, ds, hi, lo = _series()
    second = paper_replay.replay(px, symbol="BTC-USDT", dates=ds, highs=hi, lows=lo)
    assert first["replay_key"] == second["replay_key"]
    assert json.dumps(first["signals"], sort_keys=True) == json.dumps(
        second["signals"], sort_keys=True
    )
    assert first["rule_version"] == DEFAULT_PARAMS["version"]
    assert first["params_hash"] == second["params_hash"]


def test_replay_key_changes_with_params():
    px, ds, hi, lo = _series()
    tighter = dict(DEFAULT_PARAMS, flat_threshold=45.0)
    other = paper_replay.replay(px, symbol="BTC-USDT", dates=ds, highs=hi, lows=lo, params=tighter)
    assert other["params_hash"] != _base()["params_hash"]
    assert other["replay_key"] != _base()["replay_key"]


def test_signals_are_appendable_history():
    result = _base()
    signals = result["signals"]
    assert len(signals) == _N - _WARMUP == result["bars"]
    as_ofs = [s["as_of"] for s in signals]
    assert as_ofs == sorted(as_ofs) and len(set(as_ofs)) == len(as_ofs)
    for row in signals:
        assert row["symbol"] == "BTC-USDT"
        assert row["direction"] in (-1, 0, 1)
        assert 0.0 <= row["strength"] <= 1.0
        assert row["rule_version"] == DEFAULT_PARAMS["version"]
        assert row["params_hash"] == result["params_hash"]
        assert isinstance(row["inputs_snapshot"], dict)
        assert isinstance(row["flags"], list)


def test_metrics_win_rate_and_turnover():
    result = _base()
    metrics = result["metrics"]
    trades = result["trades"]
    assert metrics["bars"] == result["bars"]
    assert metrics["n_signals"] == len(result["signals"])
    assert metrics["n_closed"] == len(trades)
    assert metrics["wins"] == sum(1 for t in trades if t["ret"] > 0)
    if trades:
        assert metrics["win_rate"] == round(metrics["wins"] / len(trades), 6)
        assert metrics["avg_ret"] == round(sum(t["ret"] for t in trades) / len(trades), 8)
    assert metrics["turnover"] == round(2.0 * metrics["n_entries"] / metrics["bars"], 6)
    assert metrics["n_entries"] == metrics["n_closed"] + metrics["n_open"]


def test_execution_is_next_bar_close():
    """信号在第 i 根收盘产生，成交必须落在第 i+1 根收盘。"""
    result = _base()
    _, ds, _, _ = _series()
    signals = result["signals"]
    assert result["trades"], "合成序列应至少产生一笔纸面交易"
    first_signal = next(k for k, s in enumerate(signals) if s["direction"] != 0)
    expected = ds[_WARMUP + first_signal + 1]
    assert result["trades"][0]["entry_as_of"] == expected
    assert result["trades"][0]["entry_px"] == _series()[0][_WARMUP + first_signal + 1]


def test_persist_signals_idempotent(tmp_path):
    result = _base()
    db = str(tmp_path / "trading.db")
    store.migrate(db)
    first = paper_replay.persist_signals(result, db)
    assert first == {"inserted": len(result["signals"]), "duplicates": 0}
    second = paper_replay.persist_signals(result, db)
    assert second == {"inserted": 0, "duplicates": len(result["signals"])}
    rows = store.list_signals(db, symbol="BTC-USDT", limit=1000)
    assert len(rows) == len(result["signals"])
    head = rows[0]
    assert isinstance(head["slope_signs"], dict)
    assert isinstance(head["inputs_snapshot"], dict)
    assert head["direction"] in (-1, 0, 1)


def test_replay_rejects_short_sample():
    px, ds, hi, lo = _series(_WARMUP + 1)
    with pytest.raises(ValueError):
        paper_replay.replay(px, symbol="BTC-USDT", dates=ds, highs=hi, lows=lo)


# ---------------- 动态权重切换（§4.13 / L1D-08） ----------------


def test_default_mode_off_records_static_weights():
    result = _base()
    assert result["weights"]["mode"] == "off"
    static_hash = weights.weights_hash(weights.STATIC_WEIGHTS)
    expected = dict(weights.STATIC_WEIGHTS, gap=0.0)
    for row in result["signals"]:
        assert row["weights_version"] == weights.WEIGHTS_VERSION
        assert row["weights_hash"] == static_hash
        assert row["axis_weights"] == expected
        assert row["weights_effective_date"] == row["as_of"]
        assert not any(flag.startswith("dynamic_weights_") for flag in row["flags"])


def test_shadow_mode_records_weights_without_changing_decisions():
    base = _base()
    px, ds, hi, lo = _series()
    shadow = paper_replay.replay(
        px, symbol="BTC-USDT", dates=ds, highs=hi, lows=lo, weights_mode="shadow"
    )
    assert shadow["weights"]["mode"] == "shadow"
    assert shadow["weights"]["n_updates"] >= 1
    assert [s["total"] for s in shadow["signals"]] == [s["total"] for s in base["signals"]]
    assert [s["direction"] for s in shadow["signals"]] == [s["direction"] for s in base["signals"]]
    first = shadow["signals"][0]
    assert "dynamic_weights_shadow" in first["flags"]
    assert "weight_fallback" in first["flags"]
    # 否决期落库记静态先验（不是等权零假设），否则等权对照退化为全 0、gate 永久锁死
    assert first["weights_hash"] == weights.weights_hash(weights.STATIC_WEIGHTS)


def test_on_mode_blocks_injection_until_oos_gate_passes():
    base = _base()
    px, ds, hi, lo = _series()
    live = paper_replay.replay(
        px, symbol="BTC-USDT", dates=ds, highs=hi, lows=lo, weights_mode="on"
    )
    assert live["weights"]["mode"] == "on"
    # 130 根标签 < 250 → 每次周度再平衡都被等权否决门拦下（不注入），决策与 off 一致
    assert live["weights"]["n_updates"] >= 1
    assert live["weights"]["n_fallback"] == live["bars"]
    assert live["weights"]["n_frozen"] == live["bars"] - live["weights"]["n_updates"]
    assert [s["direction"] for s in live["signals"]] == [s["direction"] for s in base["signals"]]
    assert live["signals"][0]["weights_hash"] == weights.weights_hash(weights.STATIC_WEIGHTS)
    assert "dynamic_weights_on" in live["signals"][0]["flags"]


def test_seeded_state_freezes_weights_within_same_iso_week():
    base = _base()
    px, ds, hi, lo = _series()
    seeded = paper_replay.replay(
        px,
        symbol="BTC-USDT",
        dates=ds,
        highs=hi,
        lows=lo,
        weights_mode="shadow",
        weight_state={
            "previous_weights": weights.EQUAL_WEIGHTS,
            "last_effective_date": base["signals"][0]["as_of"],
        },
    )
    frozen = [s for s in seeded["signals"] if "weights_frozen" in s["flags"]]
    assert frozen, "同 ISO 周内必须冻结"
    assert seeded["weights"]["n_frozen"] >= 1
    for row in seeded["signals"][:2]:
        assert "weights_frozen" in row["flags"]
        assert row["weights_hash"] == weights.weights_hash(weights.EQUAL_WEIGHTS)


def test_replay_resumes_weight_state_from_trading_db(tmp_path):
    px, ds, hi, lo = _series()
    db = str(tmp_path / "trading.db")
    store.migrate(db)
    store.append_signal(
        {
            "as_of": ds[_WARMUP],
            "symbol": "BTC-USDT",
            "rule_version": DEFAULT_PARAMS["version"],
            "params_hash": "seed",
            "direction": 0,
            "strength": 0.0,
            "inputs_snapshot": {},
            "flags": ["weight_fallback"],
            "weights_version": weights.WEIGHTS_VERSION,
            "weights_hash": weights.weights_hash(weights.EQUAL_WEIGHTS),
            "weights_effective_date": ds[_WARMUP],
            "axis_weights": dict(weights.EQUAL_WEIGHTS, gap=0.0),
            "weight_sources": {},
        },
        db,
    )
    out = paper_replay.replay(
        px,
        symbol="BTC-USDT",
        dates=ds,
        highs=hi,
        lows=lo,
        weights_mode="on",
        db_path=db,
    )
    first = out["signals"][0]
    assert first["as_of"] == ds[_WARMUP]
    assert "weights_frozen" in first["flags"]
    assert "weight_fallback" in first["flags"]
    assert first["axis_weights"] == dict(weights.EQUAL_WEIGHTS, gap=0.0)
