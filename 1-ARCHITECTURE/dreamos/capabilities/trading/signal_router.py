"""Signal router — connects CoinSelector, YijingSignalGenerator, V15Executor, and HedgeExecutor.

Core responsibility:
    1. Receive market data (single or batch)
    2. Route through CoinSelector to get coin pools
    3. Route through YijingSignalGenerator to get directional signals
    4. Broadcast signals to multiple consumers:
       a. V15Executor — first position entry for Martin strategy
       b. HedgeExecutor — dual-leg hedge pair (if regime is RANGE_BOUND)
    5. Return unified result with signal + position info

Flow:
    market_data → CoinSelector.select() → pools
    pools + market_batch → YijingSignalGenerator.generate_from_pools() → signals
    signals → YijingSignalGenerator.fuse_signals() → decisions
    decisions → V15Executor.execute_signal() → positions
    decisions → HedgeExecutor.evaluate_entry() → hedge pair (if applicable)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from dreamos.capabilities.trading.coin_selector import CoinSelector
from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator
from dreamos.capabilities.trading.v15_executor import V15Executor

try:
    from dreamos.capabilities.trading.hedge_executor import HedgeExecutor
    _HEDGE_AVAILABLE = True
except ImportError:
    _HEDGE_AVAILABLE = False


class SignalRouter:
    """Signal router connecting core trading layers with multi-consumer broadcast.

    Orchestrates the flow: CoinSelector → YijingSignalGenerator → [V15Executor, HedgeExecutor].
    Yijing signals are broadcast to multiple consumers:
    - V15Executor: first position entry for Martin strategy
    - HedgeExecutor: dual-leg hedge pair (if regime is RANGE_BOUND)
    """

    def __init__(
        self,
        use_hermes: bool = False,
        seed: Optional[int] = 42,
        executor: Optional[V15Executor] = None,
        signal_generator: Optional[YijingSignalGenerator] = None,
        hedge_executor: Optional[Any] = None,
    ):
        """Initialize the signal router with all trading layers.

        Args:
            use_hermes: Whether to use Hermes for SKILL calls (default False = mock).
            seed: PRNG seed for YijingSignalGenerator.
            executor: Optional custom V15Executor instance.
            signal_generator: Optional custom YijingSignalGenerator instance.
            hedge_executor: Optional custom HedgeExecutor instance.
        """
        self.coin_selector = CoinSelector(use_hermes=use_hermes)
        self.signal_generator = signal_generator or YijingSignalGenerator(seed=seed)
        self.executor = executor or V15Executor()
        self.hedge_executor = hedge_executor or (HedgeExecutor(dry_run=False) if _HEDGE_AVAILABLE else None)

    def route(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Route a single symbol through all three layers.

        Flow:
            1. Generate Yijing signal from market data
            2. Execute signal via V15Executor

        Args:
            market_data: Dict with symbol, scores, indicators, entry_price.

        Returns:
            {
                "symbol": "BTC",
                "direction": "LONG",
                "confidence": 0.75,
                "hexagram": {...},
                "phase": "...",
                "risk_level": "...",
                "position": {status, position_size, ...},
                "timestamp": "...",
                "source": "signal-router",
            }
        """
        # Step 1: Generate Yijing signal
        signal = self.signal_generator.generate(market_data)

        # Step 2: Add entry_price for executor
        exec_signal = {
            "symbol": signal.get("symbol", ""),
            "direction": signal.get("direction", "HOLD"),
            "confidence": signal.get("confidence", 0.0),
            "entry_price": market_data.get("entry_price", market_data.get("close_price", 0.0)),
        }

        # Step 3: Execute via V15Executor
        position = self.executor.execute_signal(exec_signal)

        return {
            "symbol": signal.get("symbol", ""),
            "direction": signal.get("direction", "HOLD"),
            "confidence": signal.get("confidence", 0.0),
            "hexagram": signal.get("hexagram", {}),
            "phase": signal.get("phase", ""),
            "risk_level": signal.get("risk_level", ""),
            "position": position,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "signal-router",
        }

    def route_batch(
        self,
        pools: Dict[str, Any],
        market_batch: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Route multiple symbols from coin pools through all three layers.

        Flow:
            1. Generate signals from pools via YijingSignalGenerator
            2. Fuse signals with pool scores
            3. Execute each decision via V15Executor

        Args:
            pools: CoinSelector output with long_pool and short_pool.
            market_batch: Dict mapping symbol to market_data.

        Returns:
            {
                "long_results": [{symbol, direction, position, ...}],
                "short_results": [...],
                "timestamp": "...",
                "source": "signal-router-batch",
            }
        """
        # Step 1: Generate signals from pools
        signals = self.signal_generator.generate_from_pools(pools, market_batch)

        # Step 2: Fuse signals
        fused = self.signal_generator.fuse_signals(signals)

        # Step 3: Execute each decision
        long_results: List[Dict[str, Any]] = []
        short_results: List[Dict[str, Any]] = []

        for dec in fused.get("long_decisions", []):
            sym = dec.get("symbol", "")
            md = market_batch.get(sym, {})
            entry_price = md.get("entry_price", md.get("close_price", 0.0))

            exec_signal = {
                "symbol": sym,
                "direction": dec.get("final_direction", "HOLD"),
                "confidence": dec.get("final_confidence", 0.0),
                "entry_price": entry_price,
            }
            position = self.executor.execute_signal(exec_signal)

            long_results.append({
                "symbol": sym,
                "direction": dec.get("final_direction", "HOLD"),
                "confidence": dec.get("final_confidence", 0.0),
                "hexagram": dec.get("hexagram", {}),
                "position": position,
            })

        for dec in fused.get("short_decisions", []):
            sym = dec.get("symbol", "")
            md = market_batch.get(sym, {})
            entry_price = md.get("entry_price", md.get("close_price", 0.0))

            exec_signal = {
                "symbol": sym,
                "direction": dec.get("final_direction", "HOLD"),
                "confidence": dec.get("final_confidence", 0.0),
                "entry_price": entry_price,
            }
            position = self.executor.execute_signal(exec_signal)

            short_results.append({
                "symbol": sym,
                "direction": dec.get("final_direction", "HOLD"),
                "confidence": dec.get("final_confidence", 0.0),
                "hexagram": dec.get("hexagram", {}),
                "position": position,
            })

        # Multi-consumer broadcast: send signals to HedgeExecutor
        hedge_result = None
        if self.hedge_executor and long_results and short_results:
            try:
                # Pick best long and short candidates for hedge pair
                best_long = max(long_results, key=lambda x: x.get("confidence", 0))
                best_short = max(short_results, key=lambda x: x.get("confidence", 0))

                # Extract prices from market_batch
                hedge_prices = {}
                for sym, md in market_batch.items():
                    hedge_prices[sym] = md.get("entry_price", md.get("close_price", 0.0))

                # Get regime from pools
                regime = pools.get("regime", "")

                long_cand = {"symbol": best_long.get("symbol", ""), "score": best_long.get("confidence", 0.0)}
                short_cand = {"symbol": best_short.get("symbol", ""), "score": best_short.get("confidence", 0.0)}
                long_signal = {"direction": "LONG", "confidence": best_long.get("confidence", 0.0), "hexagram": best_long.get("hexagram", {})}
                short_signal = {"direction": "SHORT", "confidence": best_short.get("confidence", 0.0), "hexagram": best_short.get("hexagram", {})}

                hedge_result = self.hedge_executor.evaluate_entry(
                    long_cand=long_cand,
                    short_cand=short_cand,
                    long_signal=long_signal,
                    short_signal=short_signal,
                    regime=regime,
                    prices=hedge_prices,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"HedgeExecutor broadcast failed: {e}")
                hedge_result = {"status": "ERROR", "reason": str(e)}

        return {
            "long_results": long_results,
            "short_results": short_results,
            "hedge_result": hedge_result,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "signal-router-batch",
        }


# ---- Task 2: SignalRouterNode ----

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class SignalRouterNode(BaseNode):
    """SignalRouter node wrapper for DreamOS orchestration.

    Wraps SignalRouter into a BaseNode-compatible node,
    enabling it to participate in the DreamOS execution graph.
    """

    node_id: str = "SIGNAL_ROUTER"
    name: str = "Signal Router"
    description: str = "Route signals through CoinSelector -> Yijing -> V15Executor"
    chain: str = "D"
    tags: list = ["trading", "router", "orchestration"]

    def __init__(self, use_hermes: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._router = SignalRouter(use_hermes=use_hermes)

    def execute_core(self, state: State) -> NodeResult:
        """Execute signal routing and return NodeResult.

        Reads market data from state.market, calls SignalRouter.route(),
        and wraps the result into a NodeResult.
        """
        market_data = state.market or {}

        result = self._router.route(market_data)

        confidence = result.get("confidence", 0.5)
        direction = result.get("direction", "HOLD")
        position = result.get("position", {})
        status = position.get("status", "REJECTED")

        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS if status == "OPEN" else NodeStatus.DEGRADED,
            confidence=confidence,
            direction=direction,
            outputs={
                "symbol": result.get("symbol", ""),
                "direction": direction,
                "confidence": confidence,
                "hexagram": result.get("hexagram", {}),
                "phase": result.get("phase", ""),
                "risk_level": result.get("risk_level", ""),
                "position": position,
                "source": result.get("source", "signal-router"),
            },
        )
