# R1a: signal_publisher 四档约束包络字段测试（tier -> 杠杆/资产数量/多空数量/净偏置）。

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategic_extension import signal_publisher  # noqa: E402


class _StubComputer:
    enable_cycle_state_bridge = False

    def __init__(self, scores):
        self._scores = scores

    def compute(self, coin_data=None, system_state=None):
        return self._scores


def _scores_all(v):
    return {
        cls: {"dao": v, "tian": v, "di": v, "jiang": v, "fa": v}
        for cls in signal_publisher.ASSET_CLASSES
    }


def _build(monkeypatch, scores):
    monkeypatch.setattr(
        signal_publisher, "FiveDomainFeatureComputer", lambda: _StubComputer(scores)
    )
    monkeypatch.setattr(signal_publisher, "element_comparison", lambda *a, **k: None)
    monkeypatch.setattr(
        signal_publisher, "compute_market_sentiment_score", lambda: 50.0
    )
    return signal_publisher.build_signal()


def test_r1a_attack_tier_constraints(monkeypatch):
    sig = _build(monkeypatch, _scores_all(90))
    per = sig["payload"]["per_asset_class"]
    for cls in signal_publisher.ASSET_CLASSES:
        g = per[cls]
        assert g["tier"] == "attack"
        assert g["leverage_cap"] == 5
        assert g["asset_count_cap"] == 8
        assert g["long_count_cap"] == 6
        assert g["short_count_cap"] == 4
        assert g["net_bias"] == 0.2
    groups = sig["payload"]["asset_groups"]
    assert groups == {cls: [cls] for cls in signal_publisher.ASSET_CLASSES}


def test_r1a_full_freeze_tier_constraints(monkeypatch):
    sig = _build(monkeypatch, _scores_all(10))
    per = sig["payload"]["per_asset_class"]
    for cls in signal_publisher.ASSET_CLASSES:
        g = per[cls]
        assert g["tier"] == "full_freeze"
        assert g["leverage_cap"] == 1
        assert g["asset_count_cap"] == 0
        assert g["long_count_cap"] == 0
        assert g["short_count_cap"] == 0
        assert g["net_bias"] == 0.0
