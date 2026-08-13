"""V15Executor test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.v15_executor import V15Executor


def test_v15_executor_initialization():
    """Test V15Executor can be initialized with default params."""
    executor = V15Executor()
    assert executor is not None
    assert hasattr(executor, "execute_signal")
    assert hasattr(executor, "compute_addon_grid")
    assert hasattr(executor, "check_exit_conditions")


def test_v15_executor_execute_signal():
    """Test execute_signal opens a position with correct params."""
    executor = V15Executor()
    signal = {
        "symbol": "BTC",
        "direction": "LONG",
        "confidence": 0.75,
        "entry_price": 100000.0,
    }
    result = executor.execute_signal(signal)
    assert isinstance(result, dict)
    assert "symbol" in result
    assert result["symbol"] == "BTC"
    assert "direction" in result
    assert result["direction"] == "LONG"
    assert "entry_price" in result
    assert "position_size" in result
    assert "addons_remaining" in result
    assert result["addons_remaining"] == 3
    assert "tp_pct" in result
    assert result["tp_pct"] == 0.04
    assert "addon_gap_pct" in result
    assert result["addon_gap_pct"] == 0.08
    assert "status" in result
    assert result["status"] == "OPEN"


def test_v15_executor_rejects_invalid_signal():
    """Test execute_signal rejects signals with low confidence."""
    executor = V15Executor()
    signal = {
        "symbol": "BTC",
        "direction": "LONG",
        "confidence": 0.30,
        "entry_price": 100000.0,
    }
    result = executor.execute_signal(signal)
    assert result["status"] == "REJECTED"
    assert "reason" in result
