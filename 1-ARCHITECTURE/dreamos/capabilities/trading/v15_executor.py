"""C-series V15 executor — Martin strategy execution layer for DreamOS.

Core responsibility:
    1. Receive directional signals from YijingSignalGenerator
    2. Execute opening positions with V15 Martin strategy params
    3. Compute addon grid (-8%/-16%/-24% for LONG, +8%/+16%/+24% for SHORT)
    4. Check exit conditions (ATR trailing TP, timeout exit)
    5. Manage concurrent positions and budget allocation

V9 Red Line (immutable):
    - addon_gap_pct = 8% * vol_mult
    - tp_pct = 4% * vol_mult
    - max_addons = 3 (baseline) / 4 (5 orders)
    - No fixed stop loss

V15 Core Params:
    - LEVERAGE = 5.0
    - TOTAL_BUDGET = 260
    - MAX_CONCURRENT_POSITIONS = 3
    - BASE_TP_PCT = 0.04
    - ADDON_PCT = 0.08
    - MAX_ADDONS = 3
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math


# ── V9 Red Line Constants (immutable) ──────────────────────────

BASE_TP_PCT = 0.04
ADDON_GAP_PCT = 0.08
MAX_ADDONS = 3
LEVERAGE = 5.0
TOTAL_BUDGET = 260.0
MAX_CONCURRENT_POSITIONS = 3

# V15 timing params
MAX_BASE_HOLDING_HOURS = 29.9
MAX_POST_ADDON_HOURS = 37.7
GOLDEN_WINDOW_HOURS = 11.1
COOLDOWN_HOURS = 48

# Confidence threshold for signal acceptance
MIN_CONFIDENCE = 0.50


@dataclass
class Position:
    """Represents an open Martin position."""

    symbol: str
    direction: str  # LONG / SHORT
    entry_price: float
    position_size: float
    addons_remaining: int = MAX_ADDONS
    addon_count: int = 0
    tp_pct: float = BASE_TP_PCT
    addon_gap_pct: float = ADDON_GAP_PCT
    atr_at_entry: float = 0.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    last_addon_at: Optional[datetime] = None
    status: str = "OPEN"  # OPEN / CLOSED / REJECTED
    addon_prices: List[float] = field(default_factory=list)
    close_reason: Optional[str] = None

    @property
    def total_orders(self) -> int:
        """Total orders including base + addons."""
        return 1 + self.addon_count

    @property
    def effective_entry(self) -> float:
        """Weighted average entry price across all orders."""
        if not self.addon_prices:
            return self.entry_price
        all_prices = [self.entry_price] + self.addon_prices
        return sum(all_prices) / len(all_prices)


class V15Executor:
    """V15 Martin strategy executor for DreamOS.

    Encapsulates the V15 classic Martin strategy with strict adherence
    to V9 red line parameters. Supports both standalone and orchestrated
    execution modes.
    """

    def __init__(
        self,
        leverage: float = LEVERAGE,
        total_budget: float = TOTAL_BUDGET,
        max_concurrent: int = MAX_CONCURRENT_POSITIONS,
        max_addons: int = MAX_ADDONS,
        base_tp_pct: float = BASE_TP_PCT,
        addon_gap_pct: float = ADDON_GAP_PCT,
        min_confidence: float = MIN_CONFIDENCE,
    ):
        """Initialize V15 executor with strategy params.

        Args:
            leverage: Trading leverage (default 5.0).
            total_budget: Total budget in USDT (default 260).
            max_concurrent: Max concurrent positions (default 3).
            max_addons: Max addon orders per position (default 3).
            base_tp_pct: Base take-profit percentage (default 0.04).
            addon_gap_pct: Addon gap percentage (default 0.08).
            min_confidence: Minimum signal confidence to accept (default 0.50).
        """
        self.leverage = leverage
        self.total_budget = total_budget
        self.max_concurrent = max_concurrent
        self.max_addons = max_addons
        self.base_tp_pct = base_tp_pct
        self.addon_gap_pct = addon_gap_pct
        self.min_confidence = min_confidence
        self._positions: Dict[str, Position] = {}

    def execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a trading signal and open a position.

        Args:
            signal: Dict with symbol, direction, confidence, entry_price.

        Returns:
            Position info dict with status, position_size, addons_remaining, etc.
        """
        symbol = signal.get("symbol", "")
        direction = signal.get("direction", "HOLD")
        confidence = signal.get("confidence", 0.0)
        entry_price = signal.get("entry_price", 0.0)

        # Reject low confidence signals
        if confidence < self.min_confidence:
            return {
                "symbol": symbol,
                "direction": direction,
                "status": "REJECTED",
                "reason": f"confidence {confidence} below threshold {self.min_confidence}",
            }

        # Reject HOLD signals
        if direction == "HOLD":
            return {
                "symbol": symbol,
                "direction": direction,
                "status": "REJECTED",
                "reason": "HOLD signal not executable",
            }

        # Check max concurrent positions
        open_count = sum(1 for p in self._positions.values() if p.status == "OPEN")
        if open_count >= self.max_concurrent:
            return {
                "symbol": symbol,
                "direction": direction,
                "status": "REJECTED",
                "reason": f"max concurrent positions reached ({self.max_concurrent})",
            }

        # Compute position size
        per_position_budget = self.total_budget / self.max_concurrent
        position_size = (per_position_budget * self.leverage) / entry_price if entry_price > 0 else 0.0

        # Create position
        pos = Position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            position_size=position_size,
            addons_remaining=self.max_addons,
            tp_pct=self.base_tp_pct,
            addon_gap_pct=self.addon_gap_pct,
        )
        self._positions[symbol] = pos

        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "position_size": position_size,
            "addons_remaining": self.max_addons,
            "tp_pct": self.base_tp_pct,
            "addon_gap_pct": self.addon_gap_pct,
            "status": "OPEN",
            "leverage": self.leverage,
            "budget_allocated": per_position_budget,
        }

    def compute_addon_grid(
        self,
        direction: str,
        entry_price: float,
        vol_mult: float = 1.0,
    ) -> List[Dict[str, Any]]:
        """Compute Martin addon grid prices.

        V9 Red Line: addon_gap_pct = 8% * vol_mult

        Args:
            direction: LONG or SHORT.
            entry_price: Base entry price.
            vol_mult: Volatility multiplier (default 1.0).

        Returns:
            List of addon dicts with price, level, gap_pct.
        """
        gap = self.addon_gap_pct * vol_mult
        grid = []

        for i in range(1, self.max_addons + 1):
            if direction == "LONG":
                # Long addons: price drops by gap each level
                addon_price = entry_price * (1 - gap * i)
            else:
                # Short addons: price rises by gap each level
                addon_price = entry_price * (1 + gap * i)

            grid.append({
                "level": i,
                "price": round(addon_price, 4),
                "gap_pct": round(gap * i, 4),
                "direction": direction,
            })

        return grid

    def check_exit_conditions(
        self,
        position: Dict[str, Any],
        current_price: float,
        atr: float = 0.0,
        vol_mult: float = 1.0,
    ) -> Dict[str, Any]:
        """Check if a position should exit based on V15 rules.

        Exit conditions:
            1. ATR trailing take-profit (tp_pct = 4% * vol_mult)
            2. Timeout exit (base: 29.9h, post-addon: 37.7h)

        Args:
            position: Position dict from execute_signal.
            current_price: Current market price.
            atr: Current ATR value for trailing TP.
            vol_mult: Volatility multiplier.

        Returns:
            {should_exit: bool, reason: str, exit_price: float}
        """
        direction = position.get("direction", "LONG")
        entry_price = position.get("entry_price", 0.0)
        tp_pct = self.base_tp_pct * vol_mult
        opened_at_str = position.get("opened_at")

        # Parse opened_at if string
        if isinstance(opened_at_str, str):
            try:
                opened_at = datetime.fromisoformat(opened_at_str.replace("Z", ""))
            except Exception:
                opened_at = datetime.utcnow()
        elif isinstance(opened_at_str, datetime):
            opened_at = opened_at_str
        else:
            opened_at = datetime.utcnow()

        # Check ATR trailing TP
        if direction == "LONG":
            tp_price = entry_price * (1 + tp_pct)
            if current_price >= tp_price:
                return {
                    "should_exit": True,
                    "reason": "ATR trailing TP hit",
                    "exit_price": current_price,
                }
        else:
            tp_price = entry_price * (1 - tp_pct)
            if current_price <= tp_price:
                return {
                    "should_exit": True,
                    "reason": "ATR trailing TP hit",
                    "exit_price": current_price,
                }

        # Check timeout
        elapsed_hours = (datetime.utcnow() - opened_at).total_seconds() / 3600
        addon_count = position.get("addon_count", 0)

        if addon_count > 0:
            max_hours = MAX_POST_ADDON_HOURS
        else:
            max_hours = MAX_BASE_HOLDING_HOURS

        if elapsed_hours >= max_hours:
            return {
                "should_exit": True,
                "reason": f"Timeout exit ({elapsed_hours:.1f}h >= {max_hours}h)",
                "exit_price": current_price,
            }

        return {
            "should_exit": False,
            "reason": "",
            "exit_price": 0.0,
        }

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get open position by symbol."""
        return self._positions.get(symbol)

    @property
    def open_positions(self) -> Dict[str, Position]:
        """Get all open positions."""
        return {k: v for k, v in self._positions.items() if v.status == "OPEN"}
