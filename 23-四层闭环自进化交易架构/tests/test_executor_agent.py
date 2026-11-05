"""executor_agent Phase 1 运行骨架契约测试（SPEC-L0-TRADE-EXEC-MCP §10）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dreambuddy_evolution.core.executor_agent import (  # noqa: E402
    MAX_SIZE_MULTIPLIER,
    ExecutorAgent,
)


def test_low_confidence_blocks_execution():
    out = ExecutorAgent().decide({"direction": "long", "confidence": 0.45})
    assert out["execute"] is False
    assert "low_confidence" in out["reasons"]


def test_expired_blocks_execution():
    out = ExecutorAgent().decide({"confidence": 0.9}, {"expired": True})
    assert out["execute"] is False
    assert "expired" in out["reasons"]


def test_critical_risk_blocks_and_zero_size():
    out = ExecutorAgent().decide({"confidence": 0.95}, {"risk_level": "critical"})
    assert out["execute"] is False
    assert out["size_multiplier"] == 0.0


def test_high_volatility_reduces_size_and_uses_limit():
    out = ExecutorAgent().decide({"confidence": 0.9}, {"volatility_bps": 120.0})
    assert out["execute"] is True
    assert out["size_multiplier"] == 0.5
    assert out["order_type"] == "limit"


def test_policy_cannot_exceed_hard_cap():
    class _GreedyPolicy:
        def predict(self, _features):
            return {"size_multiplier": 2.0}

    out = ExecutorAgent(policy=_GreedyPolicy()).decide({"direction": "short", "confidence": 0.9})
    assert out["size_multiplier"] <= MAX_SIZE_MULTIPLIER
    assert out["direction"] == "short"  # 方向不被 agent 改写


def test_policy_exception_falls_back_to_rules():
    class _BrokenPolicy:
        def predict(self, _features):
            raise RuntimeError("model not ready")

    out = ExecutorAgent(policy=_BrokenPolicy()).decide({"confidence": 0.9})
    assert "policy_fallback" in out["reasons"]
    assert out["execute"] is True
