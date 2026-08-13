"""F-series orchestrator v2 — Hermes scheduling and Bayesian optimization layer.

Core responsibility:
    1. Orchestrate the full five-layer trading pipeline
    2. Monitor trade status and performance metrics
    3. Trigger Bayesian optimization (consecutive losses >= 3, >= 7 days, cross-month)
    4. Provide Hermes-compatible scheduling interface for SKILL calls

Pipeline:
    A: CoinSelector.select() → coin pools
    B: YijingSignalGenerator.generate() → directional signal
    C: V15Executor.execute_signal() → position
    D: SignalRouter.route() → unified result
    E: CognitiveReviewer.review() → cognitive lesson

Bayesian triggers:
    - Consecutive losses >= 3 → parameter re-optimization
    - No profit for >= 7 days → strategy review
    - Cross-month boundary → full parameter sweep
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import uuid

from dreamos.capabilities.trading.coin_selector import CoinSelector
from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator
from dreamos.capabilities.trading.v15_executor import V15Executor
from dreamos.capabilities.trading.signal_router import SignalRouter
from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewer


# Bayesian optimization trigger thresholds
BAYESIAN_LOSS_THRESHOLD = 3
BAYESIAN_DAYS_THRESHOLD = 7


@dataclass
class CycleResult:
    """Represents a single orchestration cycle result."""

    cycle_id: str
    status: str  # COMPLETED / PARTIAL / FAILED
    selection: Dict[str, Any] = field(default_factory=dict)
    signal: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)
    review: Dict[str, Any] = field(default_factory=dict)
    bayesian_triggered: bool = False
    timestamp: str = ""
    errors: List[str] = field(default_factory=list)


class OrchestratorV2:
    """Orchestrator v2 for DreamOS trading pipeline.

    Connects all five layers and provides scheduling, monitoring,
    and Bayesian optimization trigger logic.
    """

    def __init__(
        self,
        use_hermes: bool = False,
        seed: Optional[int] = 42,
    ):
        """Initialize the orchestrator with all five layers.

        Args:
            use_hermes: Whether to use Hermes for SKILL calls.
            seed: PRNG seed for reproducibility.
        """
        self.use_hermes = use_hermes
        self._coin_selector = CoinSelector(use_hermes=use_hermes)
        self._signal_generator = YijingSignalGenerator(seed=seed)
        self._executor = V15Executor()
        self._router = SignalRouter(use_hermes=use_hermes, seed=seed)
        self._reviewer = CognitiveReviewer()

        # State tracking
        self._total_cycles = 0
        self._total_pnl = 0.0
        self._wins = 0
        self._losses = 0
        self._consecutive_losses = 0
        self._last_profit_date: Optional[datetime] = None
        self._last_optimization_date: Optional[datetime] = None
        self._bayesian_optimizations = 0
        self._cycle_history: List[Dict[str, Any]] = []

    def run_cycle(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a full trading cycle through all five layers.

        Pipeline:
            1. CoinSelector: select coins (mock or Hermes)
            2. YijingSignalGenerator: generate signal from market data
            3. V15Executor: execute signal (open position)
            4. SignalRouter: route result (unified)
            5. CognitiveReviewer: review and extract lessons

        Args:
            market_data: Market data dict with symbol, scores, indicators.

        Returns:
            CycleResult dict with all layer outputs.
        """
        cycle_id = f"cycle-{self._total_cycles + 1:04d}"
        errors: List[str] = []
        status = "COMPLETED"

        # Layer A: Coin selection (mock mode uses market data symbols)
        try:
            symbols = [market_data.get("symbol", "BTC")]
            pools = self._coin_selector.select(market_data={"symbols": symbols})
            selection = {"pools": pools, "status": "OK"}
        except Exception as e:
            selection = {"status": "ERROR", "error": str(e)}
            errors.append(f"selection: {e}")
            status = "PARTIAL"

        # Layer B: Yijing signal generation
        try:
            signal = self._signal_generator.generate(market_data)
            sig_out = {
                "symbol": signal.get("symbol", ""),
                "direction": signal.get("direction", "HOLD"),
                "confidence": signal.get("confidence", 0.0),
                "hexagram": signal.get("hexagram", {}),
                "status": "OK",
            }
        except Exception as e:
            sig_out = {"status": "ERROR", "error": str(e)}
            errors.append(f"signal: {e}")
            status = "PARTIAL"

        # Layer C: V15 execution
        try:
            exec_signal = {
                "symbol": market_data.get("symbol", ""),
                "direction": sig_out.get("direction", "HOLD"),
                "confidence": sig_out.get("confidence", 0.0),
                "entry_price": market_data.get("entry_price", market_data.get("close_price", 0.0)),
            }
            position = self._executor.execute_signal(exec_signal)
            execution = {"position": position, "status": position.get("status", "REJECTED")}
        except Exception as e:
            execution = {"status": "ERROR", "error": str(e)}
            errors.append(f"execution: {e}")
            status = "PARTIAL"

        # Layer D: Signal routing (already done via layers B+C, record result)
        try:
            routed = {
                "symbol": sig_out.get("symbol", ""),
                "direction": sig_out.get("direction", "HOLD"),
                "confidence": sig_out.get("confidence", 0.0),
                "position": execution.get("position", {}),
                "status": "OK",
            }
        except Exception as e:
            routed = {"status": "ERROR", "error": str(e)}
            errors.append(f"routing: {e}")
            status = "PARTIAL"

        # Layer E: Cognitive review (simulated trade result for review)
        try:
            # Create a simulated trade result for review
            trade_result = {
                "symbol": market_data.get("symbol", ""),
                "direction": sig_out.get("direction", "HOLD"),
                "entry_price": market_data.get("entry_price", 0.0),
                "exit_price": market_data.get("close_price", 0.0),
                "position_size": execution.get("position", {}).get("position_size", 0.0),
                "confidence": sig_out.get("confidence", 0.0),
                "hexagram": sig_out.get("hexagram", {}),
                "addon_count": 0,
                "hold_hours": 0.0,
                "exit_reason": "cycle_complete",
                "pnl_usdt": 0.0,
                "pnl_pct": 0.0,
            }
            review = self._reviewer.review(trade_result)
            review["status"] = "OK"
        except Exception as e:
            review = {"status": "ERROR", "error": str(e)}
            errors.append(f"review: {e}")
            status = "PARTIAL"

        # Check Bayesian trigger
        bayesian_triggered = self.check_bayesian_trigger()

        # Update tracking
        self._total_cycles += 1
        self._cycle_history.append({
            "cycle_id": cycle_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

        if errors:
            status = "FAILED" if status == "PARTIAL" and len(errors) >= 3 else status

        return {
            "cycle_id": cycle_id,
            "status": status,
            "selection": selection,
            "signal": sig_out,
            "execution": execution,
            "review": review,
            "bayesian_triggered": bayesian_triggered,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "errors": errors,
        }

    def check_bayesian_trigger(self) -> bool:
        """Check if Bayesian optimization should be triggered.

        Triggers:
            1. Consecutive losses >= 3
            2. No profit for >= 7 days
            3. Cross-month boundary (not yet implemented in mock)

        Returns:
            True if Bayesian optimization should be triggered.
        """
        triggered = False

        # Check consecutive losses
        if self._consecutive_losses >= BAYESIAN_LOSS_THRESHOLD:
            triggered = True

        # Check days since last profit
        if self._last_profit_date is not None:
            days_since = (datetime.utcnow() - self._last_profit_date).days
            if days_since >= BAYESIAN_DAYS_THRESHOLD:
                triggered = True

        if triggered:
            self._bayesian_optimizations += 1
            self._last_optimization_date = datetime.utcnow()
            # Reset consecutive losses after optimization
            self._consecutive_losses = 0

        return triggered

    def get_status(self) -> Dict[str, Any]:
        """Get current orchestrator status and metrics.

        Returns:
            {
                "total_cycles": int,
                "total_pnl": float,
                "win_rate": float,
                "consecutive_losses": int,
                "bayesian_optimizations": int,
                "last_optimization": str or None,
            }
        """
        total = self._wins + self._losses
        win_rate = self._wins / total if total > 0 else 0.0

        return {
            "total_cycles": self._total_cycles,
            "total_pnl": round(self._total_pnl, 4),
            "win_rate": round(win_rate, 4),
            "consecutive_losses": self._consecutive_losses,
            "bayesian_optimizations": self._bayesian_optimizations,
            "last_optimization": (
                self._last_optimization_date.isoformat() + "Z"
                if self._last_optimization_date else None
            ),
        }

    def record_trade_result(self, pnl_usdt: float) -> None:
        """Record a trade result for tracking.

        Args:
            pnl_usdt: Profit/loss in USDT.
        """
        self._total_pnl += pnl_usdt
        if pnl_usdt > 0:
            self._wins += 1
            self._consecutive_losses = 0
            self._last_profit_date = datetime.utcnow()
        else:
            self._losses += 1
            self._consecutive_losses += 1

    @property
    def coin_selector(self) -> CoinSelector:
        return self._coin_selector

    @property
    def signal_generator(self) -> YijingSignalGenerator:
        return self._signal_generator

    @property
    def executor(self) -> V15Executor:
        return self._executor

    @property
    def router(self) -> SignalRouter:
        return self._router

    @property
    def reviewer(self) -> CognitiveReviewer:
        return self._reviewer


# ---- Task 3: OrchestratorV2Node ----

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class OrchestratorV2Node(BaseNode):
    """OrchestratorV2 node wrapper for DreamOS orchestration.

    Wraps OrchestratorV2 into a BaseNode-compatible node,
    enabling it to participate in the DreamOS execution graph.
    """

    node_id: str = "ORCHESTRATOR_V2"
    name: str = "Orchestrator V2"
    description: str = "Hermes scheduling and Bayesian optimization layer"
    chain: str = "F"
    tags: list = ["trading", "orchestration", "hermes", "bayesian"]

    def __init__(self, use_hermes: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._orchestrator = OrchestratorV2(use_hermes=use_hermes)

    def execute_core(self, state: State) -> NodeResult:
        """Execute a full orchestration cycle and return NodeResult.

        Reads market data from state.market, calls OrchestratorV2.run_cycle(),
        and wraps the result into a NodeResult.
        """
        market_data = state.market or {}

        cycle_result = self._orchestrator.run_cycle(market_data)

        status = cycle_result.get("status", "FAILED")
        confidence = 0.7 if status == "COMPLETED" else 0.4

        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS if status in ("COMPLETED", "PARTIAL") else NodeStatus.FAILED,
            confidence=confidence,
            direction=cycle_result.get("signal", {}).get("direction", "HOLD"),
            outputs={
                "cycle_id": cycle_result.get("cycle_id", ""),
                "status": status,
                "selection": cycle_result.get("selection", {}),
                "signal": cycle_result.get("signal", {}),
                "execution": cycle_result.get("execution", {}),
                "review": cycle_result.get("review", {}),
                "bayesian_triggered": cycle_result.get("bayesian_triggered", False),
                "errors": cycle_result.get("errors", []),
                "source": "orchestrator-v2",
            },
        )
