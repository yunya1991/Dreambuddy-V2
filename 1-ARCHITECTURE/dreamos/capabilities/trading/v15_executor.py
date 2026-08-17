"""C-series V15 executor — 14-V15 Martin strategy adapter for DreamOS.

Core responsibility:
    1. Receive Yijing signal from SignalRouter as first position entry trigger
    2. Load coin pool from coin_pool.json (hermes-weekly)
    3. Convert to 14-V15 decision format
    4. Delegate to 14-V15 execute_open_position() for first position
    5. Return structured position info for CognitiveReviewer
    6. Subsequent management (addon/take-profit/exit) handled by 14-V15 run_poll_cycle()

Architecture compliance:
    - BaseNode interface unchanged (NodeRegistry dynamic loading)
    - No hardcoded business node imports (H-01 compliant)
    - Pure orchestration: capability invocation only
    - Three systems independent: DreamOS / 14-V15 / Yijing
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path
import sys
import json
import logging
import os

logger = logging.getLogger(__name__)

# 14-V15 module path injection
_V15_CORE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "14-V15经典马丁策略" / "core"
if str(_V15_CORE_PATH) not in sys.path:
    sys.path.insert(0, str(_V15_CORE_PATH))

# HyperliquidClient path injection
_HL_EXEC_PATH = Path(__file__).resolve().parent.parent.parent.parent / "experiments" / "ab-trading" / "execution"
if str(_HL_EXEC_PATH) not in sys.path:
    sys.path.insert(0, str(_HL_EXEC_PATH))

# 14-V15 capability imports
try:
    import v15_trader
    _V15_AVAILABLE = True
except ImportError as e:
    logger.warning(f"14-V15 module unavailable: {e}")
    _V15_AVAILABLE = False

# HyperliquidClient import
try:
    from aster_spot import HyperliquidClient
    _HL_AVAILABLE = True
except ImportError as e:
    logger.warning(f"HyperliquidClient unavailable: {e}")
    _HL_AVAILABLE = False

# Hyperliquid adapter for 14-V15 interface compatibility
from dreamos.capabilities.trading.hyperliquid_adapter import HyperliquidV15Adapter

# Coin pool file path
COIN_POOL_FILE = Path(__file__).resolve().parent.parent.parent / "cli" / "scheduler_data" / "coin_pool.json"


class V15Executor:
    """14-V15 Martin strategy adapter for DreamOS.

    Thin wrapper layer that delegates all trading logic to 14-V15 module.
    Maintains DreamOS node interface while leveraging 14-V15's complete
    risk management and position lifecycle capabilities.

    Key design decisions:
        - Yijing signal as first position entry trigger (user requirement)
        - 14-V15 execute_open_position() handles all risk gates internally
        - Subsequent management delegated to 14-V15 run_poll_cycle() (independent)
        - State unified in 14-V15 v15_state.json (no dual ledger)
        - Coin pool loaded from coin_pool.json (hermes-weekly)
        - HyperliquidClient for real execution (DreamOS trading account)
    """

    def __init__(
        self,
        dry_run: Optional[bool] = None,
        long_only: bool = False,
        agent_id: str = "c",
    ):
        """Initialize V15 executor adapter.

        Args:
            dry_run: P0-3 safety gate. True = paper mode. Default None -> env DREAMOS_TRADING_DRY_RUN.
            long_only: PROP-20260816 module2: V15 long-only gate (default False).
            agent_id: Hyperliquid agent ID (default "c" for DreamOS main account).
        """
        self.long_only = bool(long_only)
        if dry_run is None:
            dry_run = os.environ.get("DREAMOS_TRADING_DRY_RUN", "false").strip().lower() == "true"
        self.dry_run = bool(dry_run)
        self.agent_id = agent_id

        if not _V15_AVAILABLE:
            raise RuntimeError("14-V15 module not available, cannot initialize V15Executor")

        # Initialize HyperliquidClient and adapter
        self._hl_client = None
        self._hl_adapter = None
        if not self.dry_run and _HL_AVAILABLE:
            try:
                self._hl_client = HyperliquidClient(agent_id)
                self._hl_adapter = HyperliquidV15Adapter(self._hl_client)
                logger.info(f"HyperliquidClient initialized for agent_id={agent_id}")
            except Exception as e:
                logger.error(f"Failed to initialize HyperliquidClient: {e}")
                raise RuntimeError(f"HyperliquidClient initialization failed: {e}")

        # Load coin pool
        self._coin_pool = self._load_coin_pool()

    def _load_coin_pool(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load coin pool from coin_pool.json (hermes-weekly).

        Returns:
            Dict with "long_pool" and "short_pool" lists.
        """
        try:
            if not COIN_POOL_FILE.exists():
                logger.warning(f"Coin pool file not found: {COIN_POOL_FILE}")
                return {"long_pool": [], "short_pool": []}

            with open(COIN_POOL_FILE, "r", encoding="utf-8") as f:
                pool = json.load(f)

            long_symbols = [item["symbol"] for item in pool.get("long_pool", [])]
            short_symbols = [item["symbol"] for item in pool.get("short_pool", [])]
            logger.info(f"Coin pool loaded: LONG({len(long_symbols)})={long_symbols}, SHORT({len(short_symbols)})={short_symbols}")

            return {
                "long_pool": pool.get("long_pool", []),
                "short_pool": pool.get("short_pool", []),
            }
        except Exception as e:
            logger.error(f"Failed to load coin pool: {e}")
            return {"long_pool": [], "short_pool": []}

    def _get_client(self):
        """Get trading client (Hyperliquid adapter or 14-V15 default).

        Returns:
            Client instance compatible with 14-V15's interface.
        """
        if self.dry_run:
            # Use 14-V15's default client (paper mode)
            return v15_trader._get_okx_client()
        else:
            # Use Hyperliquid adapter for real execution
            if self._hl_adapter is None:
                raise RuntimeError("HyperliquidClient not initialized (dry_run=False but no adapter)")
            return self._hl_adapter

    def execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Yijing signal as first position entry trigger.

        Converts Yijing signal to 14-V15 decision format and delegates
        to 14-V15 execute_open_position() for actual execution.

        Args:
            signal: Dict with symbol, direction, confidence, entry_price.
                   Signal from YijingSignalGenerator (B layer).

        Returns:
            {
                "status": "OPEN" / "REJECTED" / "ERROR",
                "symbol": "BTC",
                "direction": "LONG" / "SHORT",
                "position_size": 0.0,
                "entry_price": 0.0,
                "reason": "...",
                "source": "14-V15-adapter",
            }
        """
        symbol = signal.get("symbol", "")
        direction = signal.get("direction", "HOLD")
        confidence = signal.get("confidence", 0.0)
        entry_price = signal.get("entry_price", 0.0)

        # Gate 0: HOLD signal rejection
        if direction == "HOLD":
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "direction": direction,
                "reason": "HOLD signal not executable",
                "source": "14-V15-adapter",
            }

        # Gate 1: long_only gate (PROP-20260816 module2)
        if self.long_only and direction == "SHORT":
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "direction": direction,
                "reason": "v15_long_only",
                "source": "14-V15-adapter",
            }

        # Gate 2: Check if symbol is in coin pool
        long_symbols = [item["symbol"] for item in self._coin_pool.get("long_pool", [])]
        short_symbols = [item["symbol"] for item in self._coin_pool.get("short_pool", [])]

        if direction == "LONG" and symbol not in long_symbols:
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "direction": direction,
                "reason": f"{symbol} not in long_pool (hermes-weekly)",
                "source": "14-V15-adapter",
            }

        if direction == "SHORT" and symbol not in short_symbols:
            return {
                "status": "REJECTED",
                "symbol": symbol,
                "direction": direction,
                "reason": f"{symbol} not in short_pool (hermes-weekly)",
                "source": "14-V15-adapter",
            }

        try:
            # Load 14-V15 state
            state = v15_trader.load_state()
            client = self._get_client()

            if not client:
                return {
                    "status": "ERROR",
                    "symbol": symbol,
                    "direction": direction,
                    "reason": "trading client unavailable",
                    "source": "14-V15-adapter",
                }

            # Check if position already exists
            # If exists, it means 14-V15 run_poll_cycle() is already managing it
            if symbol in state.get("positions", {}):
                return {
                    "status": "REJECTED",
                    "symbol": symbol,
                    "direction": direction,
                    "reason": "position already exists, managed by 14-V15 run_poll_cycle()",
                    "source": "14-V15-adapter",
                }

            # Convert Yijing signal to 14-V15 decision format
            # Yijing confidence is 0.0-1.0, 14-V15 expects 0-100
            v15_confidence = int(confidence * 100)
            v15_action = "OPEN_BULL" if direction == "LONG" else "OPEN_BEAR"

            decision = {
                "action": v15_action,
                "confidence": v15_confidence,
                "reasons": [f"Yijing signal: {direction} conf={confidence:.2f}"],
                "mode": "yijing_triggered",
                "vol_mult": 1.0,  # Default, 14-V15 will calculate dynamically
                "direction_ctx": {},  # 14-V15 will populate if needed
            }

            # Delegate to 14-V15 execute_open_position()
            # This includes all risk gates: Phase D skip gate, risk engine, bounce filter, etc.
            success = v15_trader.execute_open_position(client, symbol, decision, state)

            if success:
                # Save state after successful open
                v15_trader.save_state(state)

                # Extract position info from state
                pos = state["positions"].get(symbol, {})
                return {
                    "status": "OPEN",
                    "symbol": symbol,
                    "direction": direction,
                    "position_size": pos.get("sz", 0.0),
                    "entry_price": pos.get("entry_price", entry_price),
                    "reason": "14-V15 execute_open_position success",
                    "source": "14-V15-adapter",
                }
            else:
                return {
                    "status": "REJECTED",
                    "symbol": symbol,
                    "direction": direction,
                    "reason": "14-V15 execute_open_position rejected (check logs for details)",
                    "source": "14-V15-adapter",
                }

        except Exception as e:
            logger.error(f"V15Executor adapter error: {e}")
            return {
                "status": "ERROR",
                "symbol": symbol,
                "direction": direction,
                "reason": f"adapter exception: {e}",
                "source": "14-V15-adapter",
            }


# ---- DreamOS Node Wrapper ----

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class V15ExecutorNode(BaseNode):
    """V15Executor node wrapper for DreamOS orchestration.

    Maintains BaseNode interface for NodeRegistry compatibility.
    """

    node_id: str = "V15_EXECUTOR"
    name: str = "V15 Martin Executor"
    description: str = "14-V15 Martin strategy execution layer (adapter)"
    chain: str = "C"
    tags: list = ["trading", "v15", "martin", "execution", "adapter"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._executor = V15Executor()

    def execute_core(self, state: State) -> NodeResult:
        """Execute V15 signal and return NodeResult.

        Reads market data from state.market, constructs signal,
        calls V15Executor.execute_signal(), wraps result into NodeResult.
        """
        market_data = state.market or {}

        signal = {
            "symbol": market_data.get("symbol", ""),
            "direction": market_data.get("direction", "HOLD"),
            "confidence": market_data.get("confidence", 0.0),
            "entry_price": market_data.get("entry_price", market_data.get("close_price", 0.0)),
        }

        position = self._executor.execute_signal(signal)

        status = position.get("status", "ERROR")
        confidence = position.get("position_size", 0.0) / 260.0  # Normalize to [0,1]
        confidence = max(0.0, min(1.0, confidence))

        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS if status == "OPEN" else NodeStatus.DEGRADED,
            confidence=confidence,
            direction=position.get("direction", "HOLD"),
            outputs={
                "symbol": position.get("symbol", ""),
                "direction": position.get("direction", "HOLD"),
                "status": status,
                "position_size": position.get("position_size", 0.0),
                "entry_price": position.get("entry_price", 0.0),
                "reason": position.get("reason", ""),
                "source": position.get("source", "14-V15-adapter"),
            },
        )
