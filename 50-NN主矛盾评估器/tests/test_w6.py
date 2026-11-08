# R2-04: W6 维度权重学习器测试（50 SPEC §5.1）。
from __future__ import annotations

from core.w6 import (
    COLD_START_SAMPLES,
    WEIGHT_MAX,
    WEIGHT_MIN,
    W6Store,
    learn_weights,
    refresh,
    validate_sample,
)


def _sample(dim="D3", direction="long", ret=0.5, i=0):
    return {
        "decision_id": f"dec-{i}",
        "evidence_id": f"ev-{i}",
        "dimension": dim,
        "intent": "trend",
        "provenance": "42-bus",
        "predicted_direction": direction,
        "confidence": 0.7,
        "realized_return": ret,
        "label_ts": 1794100000.0 + i,
    }


def test_validate_sample_fields():
    assert validate_sample(_sample()) is True
    bad = _sample()
    del bad["realized_return"]
    assert validate_sample(bad) is False
    assert validate_sample({}) is False


def test_cold_start_equal_weights():
    samples = [_sample(i=i) for i in range(COLD_START_SAMPLES - 1)]
    weights, state = learn_weights(samples)
    assert state == "cold_start"
    assert set(weights.values()) == {1.0}


def test_learning_maps_accuracy():
    # D3 全对（acc=1.0 -> 1.5）；D4 全错（acc=0.0 -> 0.5）；C6 中性（acc=0.5 -> 1.0）
    samples = []
    i = 0
    for _ in range(200):
        samples.append(_sample(dim="D3", direction="long", ret=1.0, i=i)); i += 1
    for _ in range(200):
        samples.append(_sample(dim="D4", direction="long", ret=-1.0, i=i)); i += 1
    for _ in range(100):
        samples.append(_sample(dim="C6", direction="long", ret=1.0, i=i)); i += 1
    for _ in range(100):
        samples.append(_sample(dim="C6", direction="long", ret=-1.0, i=i)); i += 1
    weights, state = learn_weights(samples)
    assert state == "learning"
    assert abs(weights["D3"] - WEIGHT_MAX) < 1e-9
    assert abs(weights["D4"] - 0.5) < 1e-9
    assert abs(weights["C6"] - 1.0) < 1e-9
    assert all(WEIGHT_MIN <= v <= WEIGHT_MAX for v in weights.values())


def test_store_roundtrip(tmp_path):
    store = W6Store(tmp_path / "w6")
    assert store.append_sample(_sample(i=1)) is True
    bad = _sample(i=2)
    del bad["label_ts"]
    assert store.append_sample(bad) is False
    samples = store.load_samples()
    assert len(samples) == 1
    assert samples[0]["decision_id"] == "dec-1"
    store.save_weights({"D3": 9.9, "D4": 0.01}, "learning", 1)
    weights = store.load_weights()
    assert weights["D3"] == WEIGHT_MAX
    assert weights["D4"] == WEIGHT_MIN


def test_state_crash_recovery(tmp_path):
    store = W6Store(tmp_path / "w6")
    assert store.load_state() == {}
    store.save_state({"last_decision": "dec-9", "dedup_keys": ["k1"]})
    state = store.load_state()
    assert state["last_decision"] == "dec-9"
    assert state["dedup_keys"] == ["k1"]


def test_refresh_cold_start(tmp_path):
    store = W6Store(tmp_path / "w6")
    for i in range(10):
        store.append_sample(_sample(i=i))
    result = refresh(store)
    assert result["w6_state"] == "cold_start"
    assert result["n_samples"] == 10
    assert set(result["weights"].values()) == {1.0}
