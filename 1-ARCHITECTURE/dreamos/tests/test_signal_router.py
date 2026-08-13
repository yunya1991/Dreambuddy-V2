"""SignalRouter test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.signal_router import SignalRouter


def test_signal_router_initialization():
    """Test SignalRouter can be initialized with all three layers."""
    router = SignalRouter()
    assert router is not None
    assert hasattr(router, "route")
    assert hasattr(router, "coin_selector")
    assert hasattr(router, "signal_generator")
    assert hasattr(router, "executor")


def test_signal_router_route_single_symbol():
    """Test route method processes a single symbol end-to-end."""
    router = SignalRouter(use_hermes=False)
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
    result = router.route(market_data)
    assert isinstance(result, dict)
    assert "symbol" in result
    assert "direction" in result
    assert "confidence" in result
    assert "hexagram" in result
    assert "position" in result
    assert result["position"]["status"] in ("OPEN", "REJECTED")


def test_signal_router_route_batch():
    """Test route_batch processes multiple symbols from coin pools."""
    router = SignalRouter(use_hermes=False)
    pools = {
        "long_pool": [
            {"symbol": "BTC", "score": 0.85, "reasons": ["trend up"]},
            {"symbol": "ETH", "score": 0.80, "reasons": ["volume surge"]},
        ],
        "short_pool": [
            {"symbol": "DOGE", "score": 0.65, "reasons": ["trend down"]},
        ],
    }
    market_batch = {
        "BTC": {
            "symbol": "BTC", "supply_demand_score": 0.65, "technical_score": 0.60,
            "capital_flow_score": 0.55, "sentiment_score": 0.50,
            "trend_strength": 0.70, "volatility": 0.30, "volume_ratio": 1.2,
            "price_position": 0.45, "ma5": 100.0, "ma10": 98.0, "ma20": 95.0,
            "momentum_direction": "UP", "close_price": 100000.0,
            "entry_price": 100000.0,
        },
        "ETH": {
            "symbol": "ETH", "supply_demand_score": 0.60, "technical_score": 0.55,
            "capital_flow_score": 0.50, "sentiment_score": 0.45,
            "trend_strength": 0.65, "volatility": 0.35, "volume_ratio": 1.1,
            "price_position": 0.40, "ma5": 50.0, "ma10": 49.0, "ma20": 48.0,
            "momentum_direction": "UP", "close_price": 5000.0,
            "entry_price": 5000.0,
        },
        "DOGE": {
            "symbol": "DOGE", "supply_demand_score": 0.35, "technical_score": 0.30,
            "capital_flow_score": 0.25, "sentiment_score": 0.20,
            "trend_strength": 0.25, "volatility": 0.55, "volume_ratio": 0.7,
            "price_position": 0.80, "ma5": 0.12, "ma10": 0.13, "ma20": 0.14,
            "momentum_direction": "DOWN", "close_price": 0.12,
            "entry_price": 0.12,
        },
    }
    results = router.route_batch(pools, market_batch)
    assert isinstance(results, dict)
    assert "long_results" in results
    assert "short_results" in results
    assert isinstance(results["long_results"], list)
    assert isinstance(results["short_results"], list)
    assert len(results["long_results"]) == 2
    assert len(results["short_results"]) == 1
    for r in results["long_results"] + results["short_results"]:
        assert "symbol" in r
        assert "direction" in r
        assert "position" in r


# ---- Task 2: SignalRouterNode ----

def test_signal_router_node():
    """Test SignalRouterNode node wrapper."""
    from dreamos.capabilities.trading.signal_router import SignalRouterNode
    from dreamos.shared.state import State, NodeResult, new_state

    node = SignalRouterNode()
    assert node.node_id == "SIGNAL_ROUTER"
    assert node.chain == "D"

    state = new_state(cycle_id="test-router-001")
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
    assert result.node_id == "SIGNAL_ROUTER"
    assert result.success
    assert result.confidence > 0
    assert "direction" in result.outputs
    assert "position" in result.outputs
    assert result.outputs["position"]["status"] in ("OPEN", "REJECTED")


# ---- Task 3: Phase 4 integration test ----

def test_phase4_integration():
    """Phase 4 end-to-end: COIN_SELECTOR -> YIJING_SIGNAL -> V15_EXECUTOR."""
    from dreamos.capabilities.trading.signal_router import SignalRouter, SignalRouterNode
    from dreamos.shared.state import new_state

    # Step 1: Initialize router
    router = SignalRouter(use_hermes=False)
    assert router.coin_selector is not None
    assert router.signal_generator is not None
    assert router.executor is not None

    # Step 2: Route single symbol
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
    result = router.route(market_data)
    assert result["symbol"] == "BTC"
    assert result["direction"] in ("LONG", "SHORT", "HOLD")
    assert "hexagram" in result
    assert "position" in result

    # Step 3: Route batch from pools
    pools = router.coin_selector.select(market_data={"symbols": ["BTC", "ETH", "SOL", "DOGE"]})
    market_batch = {
        "BTC": market_data,
        "ETH": {
            "symbol": "ETH", "supply_demand_score": 0.60, "technical_score": 0.55,
            "capital_flow_score": 0.50, "sentiment_score": 0.45,
            "trend_strength": 0.65, "volatility": 0.35, "volume_ratio": 1.1,
            "price_position": 0.40, "ma5": 50.0, "ma10": 49.0, "ma20": 48.0,
            "momentum_direction": "UP", "close_price": 5000.0,
            "entry_price": 5000.0,
        },
        "SOL": {
            "symbol": "SOL", "supply_demand_score": 0.55, "technical_score": 0.50,
            "capital_flow_score": 0.45, "sentiment_score": 0.40,
            "trend_strength": 0.60, "volatility": 0.40, "volume_ratio": 1.0,
            "price_position": 0.50, "ma5": 150.0, "ma10": 148.0, "ma20": 145.0,
            "momentum_direction": "UP", "close_price": 150.0,
            "entry_price": 150.0,
        },
        "DOGE": {
            "symbol": "DOGE", "supply_demand_score": 0.35, "technical_score": 0.30,
            "capital_flow_score": 0.25, "sentiment_score": 0.20,
            "trend_strength": 0.25, "volatility": 0.55, "volume_ratio": 0.7,
            "price_position": 0.80, "ma5": 0.12, "ma10": 0.13, "ma20": 0.14,
            "momentum_direction": "DOWN", "close_price": 0.12,
            "entry_price": 0.12,
        },
    }
    batch_result = router.route_batch(pools, market_batch)
    assert len(batch_result["long_results"]) + len(batch_result["short_results"]) > 0

    # Step 4: Verify node wrapper
    node = SignalRouterNode()
    assert node.node_id == "SIGNAL_ROUTER"
    assert node.chain == "D"

    state = new_state(cycle_id="phase4-integration")
    state.market = market_data
    node_result = node.execute(state)
    assert node_result.success
    assert "direction" in node_result.outputs
    assert "position" in node_result.outputs
