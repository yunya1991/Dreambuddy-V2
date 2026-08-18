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
from pathlib import Path
import json
import logging
import os
import uuid

logger = logging.getLogger(__name__)

from dreamos.capabilities.trading.coin_selector import CoinSelector
from dreamos.capabilities.trading.yijing_signal_generator import YijingSignalGenerator
from dreamos.capabilities.trading.v15_executor import V15Executor
from dreamos.capabilities.trading.signal_router import SignalRouter
from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewer


# Bayesian optimization trigger thresholds
BAYESIAN_LOSS_THRESHOLD = 3
BAYESIAN_DAYS_THRESHOLD = 7

# P1 状态持久化: 运行状态落盘,重启后自动恢复(不再失忆)
STATE_FILE = Path(__file__).resolve().parent.parent.parent / "cli" / "scheduler_data" / "orchestrator_v2_state.json"
_CYCLE_HISTORY_CAP = 200  # 历史记录上限,防止状态文件无限膨胀

# P1-2: E层认知记忆持久化文件 (lessons 跨重启不丢失)
LESSONS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "cognitive_lessons.json"


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
        # P2: 注入共享实例 —— 单账本/单PRNG,消除双实例状态漂移
        self._router = SignalRouter(
            use_hermes=use_hermes,
            seed=seed,
            executor=self._executor,
            signal_generator=self._signal_generator,
        )
        # P1-2: E层认知记忆 —— lessons 持久化 + 启动加载(重启不再失忆)
        self._reviewer = CognitiveReviewer(lessons_filepath=str(LESSONS_FILE))
        self._reviewer.load_lessons()

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

        # P1: 从磁盘恢复状态(如存在)
        self._load_state()

    # ── P1 状态持久化 ─────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """从 STATE_FILE 恢复运行状态。文件缺失/损坏时静默使用初始值。"""
        try:
            if not STATE_FILE.exists():
                return
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._total_cycles = int(data.get("total_cycles", 0))
            self._total_pnl = float(data.get("total_pnl", 0.0))
            self._wins = int(data.get("wins", 0))
            self._losses = int(data.get("losses", 0))
            self._consecutive_losses = int(data.get("consecutive_losses", 0))
            self._bayesian_optimizations = int(data.get("bayesian_optimizations", 0))
            self._cycle_history = list(data.get("cycle_history", []))[-_CYCLE_HISTORY_CAP:]
            for attr, key in (
                ("_last_profit_date", "last_profit_date"),
                ("_last_optimization_date", "last_optimization_date"),
            ):
                raw = data.get(key)
                if raw:
                    try:
                        setattr(self, attr, datetime.fromisoformat(str(raw).replace("Z", "")))
                    except ValueError:
                        setattr(self, attr, None)
            logger.info(
                f"OrchestratorV2 状态已恢复: cycles={self._total_cycles} "
                f"pnl={self._total_pnl:.4f} W/L={self._wins}/{self._losses} "
                f"source={STATE_FILE.name}"
            )
        except Exception as e:
            logger.warning(f"OrchestratorV2 状态恢复失败(使用初始值): {e}")

    def _save_state(self) -> None:
        """原子写入运行状态到 STATE_FILE (tmp+rename,防半截文件)。"""
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "total_cycles": self._total_cycles,
                "total_pnl": round(self._total_pnl, 6),
                "wins": self._wins,
                "losses": self._losses,
                "consecutive_losses": self._consecutive_losses,
                "bayesian_optimizations": self._bayesian_optimizations,
                "last_profit_date": self._last_profit_date.isoformat() if self._last_profit_date else None,
                "last_optimization_date": self._last_optimization_date.isoformat() if self._last_optimization_date else None,
                "cycle_history": self._cycle_history[-_CYCLE_HISTORY_CAP:],
                "saved_at": datetime.utcnow().isoformat() + "Z",
            }
            tmp_path = str(STATE_FILE) + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, STATE_FILE)
        except Exception as e:
            logger.warning(f"OrchestratorV2 状态落盘失败: {e}")

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

        # P1-1: E→B 认知注入 —— 周期开始时读取认知上下文
        # confidence_adjustment 由历史 lessons 的真实盈亏推导(-0.1~+0.1)
        cognitive_ctx: Dict[str, Any] = {}
        confidence_adjustment = 0.0
        try:
            cognitive_ctx = self._reviewer.get_cognitive_context(
                market_data.get("symbol")
            )
            confidence_adjustment = float(
                cognitive_ctx.get("confidence_adjustment", 0.0) or 0.0
            )
        except Exception as e:
            errors.append(f"cognitive_context: {e}")
            status = "PARTIAL"

        # Layer B+C+D: SignalRouter 真实接线（P2）
        # 单次 route() 内部完成: 易经信号生成(B) → V15执行(C) → 统一路由(D)
        # 共享注入的 generator/executor 实例: 单PRNG流 + 单账本, 无双重执行
        try:
            routed = self._router.route(market_data)
            sig_out = {
                "symbol": routed.get("symbol", ""),
                "direction": routed.get("direction", "HOLD"),
                "confidence": routed.get("confidence", 0.0),
                "hexagram": routed.get("hexagram", {}),
                "phase": routed.get("phase", ""),
                "risk_level": routed.get("risk_level", ""),
                "status": "OK",
            }
            position = routed.get("position", {})
            execution = {"position": position, "status": position.get("status", "REJECTED")}

            # P1-1: 将认知调整量注入 B层信号置信度 (保留原始值供审计)
            if confidence_adjustment:
                raw_conf = float(sig_out.get("confidence", 0.0))
                sig_out["confidence_raw"] = raw_conf
                sig_out["confidence"] = round(
                    max(0.0, min(1.0, raw_conf + confidence_adjustment)), 4
                )
            sig_out["cognitive_adjustment"] = confidence_adjustment
        except Exception as e:
            routed = {"status": "ERROR", "error": str(e)}
            sig_out = {"status": "ERROR", "error": str(e)}
            execution = {"status": "ERROR", "error": str(e)}
            errors.append(f"routing(B+C+D): {e}")
            status = "PARTIAL"

        # Layer E: 认知层 —— P1-3: 不再喂 pnl=0 伪造交易结果(自我欺骗已移除)
        # 真实盈亏审查由平仓路径回填: cli/auto_trader.run_exit_check_all()
        #   → record_real_exit() → reviewer.review(真实结果) + lessons 落盘
        # 本周期仅记录认知状态快照(供影子模式观察注入是否生效)
        try:
            review = {
                "status": "OK",
                "mode": "awaiting_real_feedback",
                "cognitive_context": {
                    "total_reviews": cognitive_ctx.get("total_reviews", 0),
                    "total_pnl": cognitive_ctx.get("total_pnl", 0.0),
                    "win_rate": cognitive_ctx.get("win_rate", 0.0),
                    "confidence_adjustment": confidence_adjustment,
                },
                "note": "真实盈亏审查由平仓回填路径 record_real_exit() 产生",
            }
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

        # P1: 周期结束落盘状态
        self._save_state()

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
        # P1: 交易结果落盘(真实平仓反馈入口)
        self._save_state()

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


# ---- P1-3: 真实平仓回填入口 (E层认知闭环接线) ----

def record_real_exit(trade_result: Dict[str, Any]) -> Dict[str, Any]:
    """P1-3: 真实平仓结果回填 —— E层认知闭环入口。

    由 cli/auto_trader.run_exit_check_all() 在真实持仓平仓后调用:
        1. CognitiveReviewer.review(真实结果) → assessment + lessons
        2. lessons 持久化到 LESSONS_FILE (供 P1-1 下轮注入)
        3. OrchestratorV2.record_trade_result(pnl) → W/L、累计PnL、
           连败计数(贝叶斯触发源) 落盘 STATE_FILE

    失败降级: 任何异常只记录日志,不向调用方抛出(不影响持仓管家主流程)。

    Args:
        trade_result: 含 symbol/direction/entry_price/exit_price/pnl_usdt/
            pnl_pct/exit_reason 等字段的交易结果 dict。

    Returns:
        review dict (含 assessment/score/lessons);失败时含 error 字段。
    """
    # Step 1: E层真实审查 + lessons 落盘
    try:
        reviewer = CognitiveReviewer(lessons_filepath=str(LESSONS_FILE))
        reviewer.load_lessons()
        review = reviewer.review(trade_result)
        reviewer.persist_lessons()
    except Exception as e:
        logger.warning(f"P1-3 E层真实审查失败: {e}")
        return {"status": "ERROR", "error": str(e)}

    # Step 2: F层状态更新 (W/L、累计PnL、连败计数)
    pnl_usdt = float(trade_result.get("pnl_usdt", 0.0) or 0.0)
    try:
        orch = OrchestratorV2()
        orch.record_trade_result(pnl_usdt)
        review["state_update"] = "OK"
    except Exception as e:
        logger.warning(f"P1-3 F层状态落盘失败: {e}")
        review["state_update"] = "FAILED"

    review["status"] = "OK"
    logger.info(
        f"P1-3 真实平仓回填: {trade_result.get('symbol', '?')} | "
        f"pnl={pnl_usdt:.4f} USDT | assessment={review.get('assessment')} | "
        f"lessons={len(review.get('lessons', []))}"
    )
    return review


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
