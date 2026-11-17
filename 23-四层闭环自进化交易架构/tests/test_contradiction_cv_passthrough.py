"""矛盾 / 交叉验证数据从管线透传到 23 信号的回归测试。"""

from __future__ import annotations

from dreambuddy_evolution.engines.result_aggregator import ResultAggregator


def test_contradiction_and_cv_reach_signal_payload():
    captured: dict = {}

    def _cb(**kwargs):
        captured.update(kwargs)

    agg = ResultAggregator(build_position_callback=_cb)
    agg.trigger_build_position(
        "BTC",
        "long",
        "d1",
        0.72,
        position_mult=0.8,
        tier="standard",
        primary_contradiction={
            "dimension": "structure",
            "direction": "long",
            "strength": 0.66,
        },
        cross_validation={
            "degraded_mode": "partial",
            "shift_signal": True,
            "confidence_mult": 0.8,
        },
        elastic_result={"band": "wide"},
        regime="trend",
    )
    payload = captured["signal"]["payload"]
    assert payload["primary_contradiction"]["dimension"] == "structure"
    assert payload["primary_contradiction"]["strength"] == 0.66
    assert payload["cross_validation"]["degraded_mode"] == "partial"
    assert payload["cross_validation"]["confidence_mult"] == 0.8
    assert payload["elastic_result"] == {"band": "wide"}
    assert payload["regime"] == "trend"


def test_missing_contradiction_is_explicit_unknown_not_fabricated():
    captured: dict = {}
    agg = ResultAggregator(build_position_callback=lambda **kw: captured.update(kw))
    agg.trigger_build_position("ETH", "short", "d2", 0.61)
    pc = captured["signal"]["payload"]["primary_contradiction"]
    assert pc["dimension"] == "unknown"
    assert captured["signal"]["payload"]["cross_validation"] == {}
