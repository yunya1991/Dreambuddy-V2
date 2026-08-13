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
