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


# ---- Task 2: Bayesian optimization trigger ----

def test_bayesian_trigger_consecutive_losses():
    """Test Bayesian trigger on 3 consecutive losses."""
    orch = OrchestratorV2(use_hermes=False)
    # Record 3 consecutive losses
    orch.record_trade_result(-10.0)
    assert orch.get_status()["consecutive_losses"] == 1
    orch.record_trade_result(-15.0)
    assert orch.get_status()["consecutive_losses"] == 2
    orch.record_trade_result(-20.0)
    assert orch.get_status()["consecutive_losses"] == 3

    # Should trigger Bayesian optimization
    triggered = orch.check_bayesian_trigger()
    assert triggered is True
    assert orch.get_status()["bayesian_optimizations"] == 1
    # Consecutive losses should be reset after optimization
    assert orch.get_status()["consecutive_losses"] == 0


def test_bayesian_trigger_no_loss():
    """Test Bayesian does not trigger with no losses."""
    orch = OrchestratorV2(use_hermes=False)
    triggered = orch.check_bayesian_trigger()
    assert triggered is False
    assert orch.get_status()["bayesian_optimizations"] == 0


# ---- Task 3: OrchestratorV2Node + integration ----

def test_orchestrator_v2_node():
    """Test OrchestratorV2Node node wrapper."""
    from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2Node
    from dreamos.shared.state import State, NodeResult, new_state

    node = OrchestratorV2Node()
    assert node.node_id == "ORCHESTRATOR_V2"
    assert node.chain == "F"

    state = new_state(cycle_id="test-orch-001")
    state.market = {
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

    result = node.execute(state)

    assert isinstance(result, NodeResult)
    assert result.node_id == "ORCHESTRATOR_V2"
    assert result.success
    assert "cycle_id" in result.outputs
    assert "status" in result.outputs
    assert result.outputs["status"] in ("COMPLETED", "PARTIAL", "FAILED")


def test_phase6_integration():
    """Phase 6 end-to-end: run_cycle -> bayesian -> status -> node."""
    from dreamos.capabilities.trading.orchestrator_v2 import OrchestratorV2, OrchestratorV2Node
    from dreamos.shared.state import new_state

    # Step 1: Initialize orchestrator
    orch = OrchestratorV2(use_hermes=False)
    assert orch is not None

    # Step 2: Run a full cycle
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
    assert result["status"] in ("COMPLETED", "PARTIAL")
    assert "selection" in result
    assert "signal" in result
    assert "execution" in result
    assert "review" in result

    # Step 3: Check status
    status = orch.get_status()
    assert status["total_cycles"] == 1

    # Step 4: Record losses and trigger Bayesian
    orch.record_trade_result(-10.0)
    orch.record_trade_result(-15.0)
    orch.record_trade_result(-20.0)
    triggered = orch.check_bayesian_trigger()
    assert triggered is True
    assert orch.get_status()["bayesian_optimizations"] == 1

    # Step 5: Verify node wrapper
    node = OrchestratorV2Node()
    assert node.node_id == "ORCHESTRATOR_V2"
    assert node.chain == "F"

    state = new_state(cycle_id="phase6-integration")
    state.market = market_data
    node_result = node.execute(state)
    assert node_result.success
    assert node_result.outputs["status"] in ("COMPLETED", "PARTIAL")
