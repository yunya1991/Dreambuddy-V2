"""CoinSelector test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.coin_selector import CoinSelector
from dreamos.shared.state import State, NodeResult, NodeStatus, new_state


def test_coin_selector_initialization():
    """Test CoinSelector can be initialized."""
    selector = CoinSelector()
    assert selector is not None
    assert hasattr(selector, "select")


def test_coin_selector_returns_pools():
    """Test select method returns long/short pool structure."""
    selector = CoinSelector()
    result = selector.select(market_data={"symbols": ["BTC", "ETH"]})
    assert isinstance(result, dict)
    assert "long_pool" in result
    assert "short_pool" in result
    assert isinstance(result["long_pool"], list)
    assert isinstance(result["short_pool"], list)


def test_coin_selector_pool_format():
    """Test each pool item contains required fields."""
    selector = CoinSelector()
    result = selector.select(market_data={"symbols": ["BTC"]})
    for pool_key in ("long_pool", "short_pool"):
        for item in result[pool_key]:
            assert "symbol" in item
            assert "score" in item
            assert "reasons" in item


# ---- Task 2: SKILL call and fusion ----

def test_call_asset_research():
    """Test _call_asset_research returns asset research structure."""
    selector = CoinSelector(use_hermes=False)
    result = selector._call_asset_research(region="global")
    assert isinstance(result, dict)
    assert "engineName" in result
    assert "region" in result
    assert "phase" in result
    assert "priority_assets" in result
    assert isinstance(result["priority_assets"], list)
    assert "source" in result


def test_call_attention_radar():
    """Test _call_attention_radar returns attention radar structure."""
    selector = CoinSelector(use_hermes=False)
    result = selector._call_attention_radar(symbols=["BTC", "ETH", "SOL"])
    assert isinstance(result, dict)
    assert "long_top" in result
    assert "short_top" in result
    assert isinstance(result["long_top"], list)
    assert isinstance(result["short_top"], list)
    assert "source" in result


def test_fuse_results():
    """Test _fuse_results correctly fuses two SKILL results."""
    selector = CoinSelector(use_hermes=False)
    asset_research = {
        "engineName": "AssetResearch",
        "region": "global",
        "phase": "discovery",
        "priority_assets": [
            {"symbol": "BTC", "score": 0.9, "reason": "strong trend"},
            {"symbol": "ETH", "score": 0.8, "reason": "volume surge"},
        ],
        "source": "mock",
    }
    attention_radar = {
        "long_top": [
            {"symbol": "BTC", "score": 0.85, "reason": "attention high"},
            {"symbol": "SOL", "score": 0.7, "reason": "momentum up"},
        ],
        "short_top": [
            {"symbol": "DOGE", "score": 0.65, "reason": "attention low"},
        ],
        "source": "mock",
    }
    fused = selector._fuse_results(asset_research, attention_radar)
    assert isinstance(fused, dict)
    assert "long_pool" in fused
    assert "short_pool" in fused
    assert isinstance(fused["long_pool"], list)
    assert isinstance(fused["short_pool"], list)
    long_symbols = [item["symbol"] for item in fused["long_pool"]]
    assert "BTC" in long_symbols
    for item in fused["long_pool"]:
        assert "symbol" in item
        assert "score" in item
        assert "reasons" in item


# ---- Task 3: crypto_priority fusion logic ----

def test_coin_selector_fuse_results():
    """Test crypto_priority weight: non-crypto assets score * 0.5."""
    selector = CoinSelector(use_hermes=False)
    asset_research = {
        "engineName": "AssetResearch",
        "region": "global",
        "phase": "discovery",
        "priority_assets": [
            {"symbol": "BTC", "score": 0.9, "reason": "strong trend", "priority": 1.0},
            {"symbol": "DOGE", "score": 0.7, "reason": "meme coin", "priority": 0.5},
        ],
        "source": "mock",
    }
    attention_radar = {
        "long_top": [
            {"symbol": "BTC", "score": 0.85, "reason": "attention high"},
            {"symbol": "DOGE", "score": 0.6, "reason": "hype driven"},
        ],
        "short_top": [],
        "source": "mock",
    }
    fused = selector._fuse_results(asset_research, attention_radar)
    pool_by_symbol = {item["symbol"]: item for item in fused["long_pool"]}
    assert "BTC" in pool_by_symbol
    assert "DOGE" in pool_by_symbol
    btc_score = pool_by_symbol["BTC"]["score"]
    doge_score = pool_by_symbol["DOGE"]["score"]
    assert btc_score > doge_score, f"BTC score {btc_score} should be > DOGE score {doge_score}"


def test_coin_selector_select_uses_fusion():
    """Test select method uses fusion logic in mock mode."""
    selector = CoinSelector(use_hermes=False)
    result = selector.select(market_data={"symbols": ["BTC", "ETH", "SOL", "DOGE"]})
    assert isinstance(result, dict)
    assert "long_pool" in result
    assert "short_pool" in result
    assert "source" in result
    assert result["source"] == "mock"
    total = len(result["long_pool"]) + len(result["short_pool"])
    assert total > 0, "pools should not be empty"


# ---- Task 4: CoinSelectorNode ----

def test_coin_selector_node():
    """Test CoinSelectorNode node wrapper."""
    from dreamos.capabilities.trading.coin_selector import CoinSelectorNode

    node = CoinSelectorNode()
    assert node.node_id == "COIN_SELECTOR"
    assert node.chain == "A"

    state = new_state(cycle_id="test-001")
    state.market = {"symbols": ["BTC", "ETH", "SOL", "DOGE"]}

    result = node.execute(state)

    assert isinstance(result, NodeResult)
    assert result.node_id == "COIN_SELECTOR"
    assert result.success
    assert result.confidence > 0
    assert "long_pool" in result.outputs
    assert "short_pool" in result.outputs
    assert isinstance(result.outputs["long_pool"], list)
    assert isinstance(result.outputs["short_pool"], list)
