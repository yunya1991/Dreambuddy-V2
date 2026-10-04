"""测试 classic_pipeline.risk 和 classic_pipeline.plan 模块。"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Risk Gatekeeper
# ---------------------------------------------------------------------------

class TestRiskGatekeeper:
    def test_approved_with_valid_signal(self):
        from classic_pipeline.risk import check
        result = check(
            {"direction": "long", "confidence": 0.8, "entry_price": 100.0},
            {"equity": 10000.0, "atr": 2.0},
            {},
        )
        assert result["approved"] is True
        assert result["position_size"] > 0
        assert result["stop_loss"] > 0
        assert result["take_profit"] > result["stop_loss"]

    def test_rejected_no_direction(self):
        from classic_pipeline.risk import check
        result = check({"direction": "neutral"}, {}, {})
        assert result["approved"] is False
        assert result["reason"] == "no_direction"

    def test_rejected_no_equity(self):
        from classic_pipeline.risk import check
        result = check({"direction": "long"}, {"equity": 0}, {})
        assert result["approved"] is False
        assert result["reason"] == "no_equity"

    def test_max_risk_2_percent(self):
        """单笔风险不超过 2%。"""
        from classic_pipeline.risk import check
        result = check(
            {"direction": "long", "entry_price": 100.0},
            {"equity": 10000.0, "atr": 2.0},
            {"max_risk_pct": 0.02},
        )
        # position_size * stop_loss <= max_risk_pct
        risk = result["position_size"] * result["stop_loss"]
        assert risk <= 0.02 + 1e-9

    def test_position_capped(self):
        """仓位不超过 max_position_pct。"""
        from classic_pipeline.risk import check
        result = check(
            {"direction": "long", "entry_price": 100.0},
            {"equity": 10000.0, "atr": 0.01},
            {"max_position_pct": 0.1},
        )
        assert result["position_size"] <= 0.1


# ---------------------------------------------------------------------------
# Plan Generator
# ---------------------------------------------------------------------------

class TestPlanGenerator:
    def test_open_when_signal_and_risk_ok(self):
        from classic_pipeline.plan import generate
        plan = generate(
            {"direction": "long", "confidence": 0.8, "strategy": "three_screen", "entry_price": 100.0},
            {"approved": True, "position_size": 0.1, "stop_loss": 0.02, "take_profit": 0.04},
            {},
        )
        assert plan["entry_decision"] == "open"
        assert plan["direction"] == "long"
        assert plan["position_size"] == 0.1
        assert plan["stop_loss_price"] == pytest.approx(98.0)
        assert plan["take_profit_price"] == pytest.approx(104.0)

    def test_observe_when_risk_not_approved(self):
        from classic_pipeline.plan import generate
        plan = generate(
            {"direction": "long", "confidence": 0.8},
            {"approved": False},
            {},
        )
        assert plan["entry_decision"] == "observe"

    def test_observe_when_no_signal(self):
        from classic_pipeline.plan import generate
        plan = generate({"direction": "neutral"}, {}, {})
        assert plan["entry_decision"] == "observe"

    def test_short_stop_loss_above_entry(self):
        from classic_pipeline.plan import generate
        plan = generate(
            {"direction": "short", "entry_price": 100.0},
            {"approved": True, "position_size": 0.1, "stop_loss": 0.02, "take_profit": 0.04},
            {},
        )
        assert plan["stop_loss_price"] == pytest.approx(102.0)
        assert plan["take_profit_price"] == pytest.approx(96.0)
