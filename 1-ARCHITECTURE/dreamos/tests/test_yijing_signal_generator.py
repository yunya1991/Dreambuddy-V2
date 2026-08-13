"""YijingSignalGenerator test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator


def test_yijing_signal_generator_initialization():
    """Test YijingSignalGenerator can be initialized."""
    gen = YijingSignalGenerator()
    assert gen is not None
    assert hasattr(gen, "generate")


def test_yijing_signal_generator_returns_signal():
    """Test generate method returns a signal with required fields."""
    gen = YijingSignalGenerator()
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
        "close_price": 100.0,
    }
    signal = gen.generate(market_data)
    assert isinstance(signal, dict)
    assert "symbol" in signal
    assert "direction" in signal
    assert signal["direction"] in ("LONG", "SHORT", "HOLD")
    assert "confidence" in signal
    assert 0.0 <= signal["confidence"] <= 1.0
    assert "hexagram" in signal
    assert "source" in signal


def test_yijing_signal_generator_hexagram_structure():
    """Test the hexagram field contains required sub-fields."""
    gen = YijingSignalGenerator()
    market_data = {
        "symbol": "ETH",
        "supply_demand_score": 0.40,
        "technical_score": 0.35,
        "capital_flow_score": 0.30,
        "sentiment_score": 0.25,
        "trend_strength": 0.20,
        "volatility": 0.50,
        "volume_ratio": 0.8,
        "price_position": 0.75,
        "ma5": 50.0,
        "ma10": 52.0,
        "ma20": 55.0,
        "momentum_direction": "DOWN",
        "close_price": 50.0,
    }
    signal = gen.generate(market_data)
    hex = signal["hexagram"]
    assert isinstance(hex, dict)
    assert "original_gua" in hex
    assert "changed_gua" in hex
    assert "moving_yaos" in hex
    assert isinstance(hex["moving_yaos"], list)


# ---- Task 2: Pool integration ----

def test_yijing_generate_from_pools():
    """Test generate_from_pools processes a full coin pool."""
    gen = YijingSignalGenerator(seed=42)
    pools = {
        "long_pool": [
            {"symbol": "BTC", "score": 0.85, "reasons": ["trend up"]},
            {"symbol": "ETH", "score": 0.80, "reasons": ["volume surge"]},
        ],
        "short_pool": [
            {"symbol": "DOGE", "score": 0.65, "reasons": ["trend down"]},
        ],
    }
    market_data_batch = {
        "BTC": {
            "symbol": "BTC", "supply_demand_score": 0.65, "technical_score": 0.60,
            "capital_flow_score": 0.55, "sentiment_score": 0.50,
            "trend_strength": 0.70, "volatility": 0.30, "volume_ratio": 1.2,
            "price_position": 0.45, "ma5": 100.0, "ma10": 98.0, "ma20": 95.0,
            "momentum_direction": "UP", "close_price": 100.0,
        },
        "ETH": {
            "symbol": "ETH", "supply_demand_score": 0.60, "technical_score": 0.55,
            "capital_flow_score": 0.50, "sentiment_score": 0.45,
            "trend_strength": 0.65, "volatility": 0.35, "volume_ratio": 1.1,
            "price_position": 0.40, "ma5": 50.0, "ma10": 49.0, "ma20": 48.0,
            "momentum_direction": "UP", "close_price": 50.0,
        },
        "DOGE": {
            "symbol": "DOGE", "supply_demand_score": 0.35, "technical_score": 0.30,
            "capital_flow_score": 0.25, "sentiment_score": 0.20,
            "trend_strength": 0.25, "volatility": 0.55, "volume_ratio": 0.7,
            "price_position": 0.80, "ma5": 0.12, "ma10": 0.13, "ma20": 0.14,
            "momentum_direction": "DOWN", "close_price": 0.12,
        },
    }
    signals = gen.generate_from_pools(pools, market_data_batch)
    assert isinstance(signals, dict)
    assert "long_signals" in signals
    assert "short_signals" in signals
    assert isinstance(signals["long_signals"], list)
    assert isinstance(signals["short_signals"], list)
    assert len(signals["long_signals"]) == 2
    assert len(signals["short_signals"]) == 1
    for sig in signals["long_signals"] + signals["short_signals"]:
        assert "symbol" in sig
        assert "direction" in sig
        assert "confidence" in sig


def test_yijing_generate_from_pools_missing_data():
    """Test generate_from_pools handles missing market data gracefully."""
    gen = YijingSignalGenerator(seed=42)
    pools = {
        "long_pool": [
            {"symbol": "BTC", "score": 0.85, "reasons": ["trend up"]},
            {"symbol": "MISSING", "score": 0.70, "reasons": ["unknown"]},
        ],
        "short_pool": [],
    }
    market_data_batch = {
        "BTC": {
            "symbol": "BTC", "supply_demand_score": 0.65, "technical_score": 0.60,
            "capital_flow_score": 0.55, "sentiment_score": 0.50,
            "trend_strength": 0.70, "volatility": 0.30, "volume_ratio": 1.2,
            "price_position": 0.45, "ma5": 100.0, "ma10": 98.0, "ma20": 95.0,
            "momentum_direction": "UP", "close_price": 100.0,
        },
    }
    signals = gen.generate_from_pools(pools, market_data_batch)
    # Should only process symbols with available market data
    assert len(signals["long_signals"]) == 1
    assert signals["long_signals"][0]["symbol"] == "BTC"


# ---- Task 3: Signal fusion and direction decision ----

def test_yijing_fuse_signals():
    """Test fuse_signals combines yijing signals with pool scores."""
    gen = YijingSignalGenerator(seed=42)
    signals = {
        "long_signals": [
            {"symbol": "BTC", "direction": "LONG", "confidence": 0.75, "hexagram": {}, "pool_score": 0.85},
            {"symbol": "ETH", "direction": "HOLD", "confidence": 0.50, "hexagram": {}, "pool_score": 0.80},
        ],
        "short_signals": [
            {"symbol": "DOGE", "direction": "SHORT", "confidence": 0.65, "hexagram": {}, "pool_score": 0.70},
        ],
    }
    fused = gen.fuse_signals(signals)
    assert isinstance(fused, dict)
    assert "long_decisions" in fused
    assert "short_decisions" in fused
    assert isinstance(fused["long_decisions"], list)
    assert isinstance(fused["short_decisions"], list)
    for dec in fused["long_decisions"] + fused["short_decisions"]:
        assert "symbol" in dec
        assert "final_direction" in dec
        assert "final_confidence" in dec
        assert "yijing_confidence" in dec
        assert "pool_score" in dec


def test_yijing_fuse_signals_weighting():
    """Test fuse_signals applies correct weighting: yijing 0.6 + pool 0.4."""
    gen = YijingSignalGenerator(seed=42)
    signals = {
        "long_signals": [
            {"symbol": "BTC", "direction": "LONG", "confidence": 0.80, "hexagram": {}, "pool_score": 0.90},
        ],
        "short_signals": [],
    }
    fused = gen.fuse_signals(signals)
    dec = fused["long_decisions"][0]
    # final_confidence should be weighted: 0.80*0.6 + 0.90*0.4 = 0.84
    expected = round(0.80 * 0.6 + 0.90 * 0.4, 4)
    assert abs(dec["final_confidence"] - expected) < 0.01
    assert dec["final_direction"] == "LONG"
