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


# ---- Task 2: Martin addon grid ----

def test_v15_executor_addon_grid_long():
    """Test compute_addon_grid for LONG direction."""
    executor = V15Executor()
    grid = executor.compute_addon_grid("LONG", 100000.0, vol_mult=1.0)

    assert len(grid) == 3
    assert grid[0]["level"] == 1
    assert grid[1]["level"] == 2
    assert grid[2]["level"] == 3

    # LONG addons: price drops by 8% each level
    assert abs(grid[0]["price"] - 92000.0) < 1.0   # 100000 * (1 - 0.08)
    assert abs(grid[1]["price"] - 84000.0) < 1.0   # 100000 * (1 - 0.16)
    assert abs(grid[2]["price"] - 76000.0) < 1.0   # 100000 * (1 - 0.24)

    assert grid[0]["gap_pct"] == 0.08
    assert grid[1]["gap_pct"] == 0.16
    assert grid[2]["gap_pct"] == 0.24


def test_v15_executor_addon_grid_short_with_vol_mult():
    """Test compute_addon_grid for SHORT with volatility multiplier."""
    executor = V15Executor()
    grid = executor.compute_addon_grid("SHORT", 100000.0, vol_mult=1.5)

    assert len(grid) == 3
    # SHORT addons: price rises by 8%*1.5=12% each level
    gap = 0.08 * 1.5  # 0.12
    assert abs(grid[0]["price"] - 112000.0) < 1.0   # 100000 * (1 + 0.12)
    assert abs(grid[1]["price"] - 124000.0) < 1.0   # 100000 * (1 + 0.24)
    assert abs(grid[2]["price"] - 136000.0) < 1.0   # 100000 * (1 + 0.36)
