"""Signal router — connects CoinSelector, YijingSignalGenerator, and V15Executor.

Core responsibility:
    1. Receive market data (single or batch)
    2. Route through CoinSelector to get coin pools
    3. Route through YijingSignalGenerator to get directional signals
    4. Route through V15Executor to execute positions
    5. Return unified result with signal + position info

Flow:
    market_data → CoinSelector.select() → pools
    pools + market_batch → YijingSignalGenerator.generate_from_pools() → signals
    signals → YijingSignalGenerator.fuse_signals() → decisions
    decisions → V15Executor.execute_signal() → positions
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime

from dreamos.capabilities.trading.coin_selector import CoinSelector
from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator
from dreamos.capabilities.trading.v15_executor import V15Executor


class SignalRouter:
    """Signal router connecting the three core trading layers.

    Orchestrates the flow: CoinSelector → YijingSignalGenerator → V15Executor.
    """

    def __init__(
        self,
        use_hermes: bool = False,
        seed: Optional[int] = 42,
        executor: Optional[V15Executor] = None,
    ):
        """Initialize the signal router with all three layers.

        Args:
            use_hermes: Whether to use Hermes for SKILL calls (default False = mock).
            seed: PRNG seed for YijingSignalGenerator.
            executor: Optional custom V15Executor instance.
        """
        self.coin_selector = CoinSelector(use_hermes=use_hermes)
        self.signal_generator = YijingSignalGenerator(seed=seed)
        self.executor = executor or V15Executor()

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

        return {
            "long_results": long_results,
            "short_results": short_results,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "signal-router-batch",
        }
