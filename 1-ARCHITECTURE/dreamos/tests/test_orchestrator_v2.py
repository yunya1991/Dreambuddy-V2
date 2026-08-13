"""OrchestratorV2 test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2


def test_orchestrator_v2_initialization():
    """Test OrchestratorV2 can be initialized with all five layers."""
    orch = OrchestratorV2()
    assert orch is not None
    assert hasattr(orch, "run_cycle")
    assert hasattr(orch, "check_bayesian_trigger")
    assert hasattr(orch, "get_status")


def test_orchestrator_v2_run_cycle():
    """Test run_cycle executes the full five-layer pipeline."""
    orch = OrchestratorV2(use_hermes=False)
    market_data = {
        "symbol": "BTC",
        "supply_demand_score": 0.65,
        "technical_score": 0.60,
        "capital_flow_score": 0.55,
        "sentiment_score": 0.50,
        "trend_strength": 0.70,
        "volatility": 0.30,
        "volume_ratio": 1.2,
        "price_position": 0.45,
        "ma5": 100.0,
        "ma10": 98.0,
        "ma20": 95.0,
        "momentum_direction": "UP",
        "close_price": 100000.0,
        "entry_price": 100000.0,
    }
    result = orch.run_cycle(market_data)
    assert isinstance(result, dict)
    assert "cycle_id" in result
    assert "selection" in result
    assert "signal" in result
    assert "execution" in result
    assert "review" in result
    assert "status" in result
    assert result["status"] in ("COMPLETED", "PARTIAL", "FAILED")


def test_orchestrator_v2_get_status():
    """Test get_status returns current orchestrator state."""
    orch = OrchestratorV2(use_hermes=False)
    status = orch.get_status()
    assert isinstance(status, dict)
    assert "total_cycles" in status
    assert "total_pnl" in status
    assert "win_rate" in status
    assert "consecutive_losses" in status
    assert "bayesian_optimizations" in status
