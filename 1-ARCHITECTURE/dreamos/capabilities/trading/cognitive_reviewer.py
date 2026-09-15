"""E-series cognitive reviewer — trade result review and cognitive injection.

Core responsibility:
    1. Receive trade execution results (open/close/pnl)
    2. Review and analyze trade decision quality
    3. Extract cognitive lessons (lessons learned)
    4. Persist lessons for future retrieval
    5. Provide cognitive context for runtime injection into subsequent decisions

Integration:
    - Input: V15Executor trade results
    - Output: Cognitive review with assessment, score, lessons
    - Injection: get_cognitive_context() feeds back into signal generation
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json


@dataclass
class TradeLesson:
    """Represents a cognitive lesson extracted from a trade."""

    lesson_id: str
    category: str  # timing / direction / risk / addon / exit
    description: str
    symbol: str
    trade_pnl: float
    confidence_at_entry: float
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "category": self.category,
            "description": self.description,
            "symbol": self.symbol,
            "trade_pnl": self.trade_pnl,
            "confidence_at_entry": self.confidence_at_entry,
            "created_at": self.created_at,
        }


class CognitiveLoopEntry:
    """Statistical model for cognitive loop analysis.

    Provides rigorous statistical metrics to complement the Bayesian
    confidence adjustment in get_cognitive_context().

    Metrics:
        - Expected value E[PnL] and standard deviation σ
        - Sharpe-like ratio (risk-adjusted return)
        - Maximum drawdown (peak-to-trough decline)
        - Wilson score interval for win rate (lower/upper bound)
        - Profit factor (gross profit / gross loss)
        - Consecutive loss streak tracking
        - Kelly criterion fraction (optimal bet size)

    Design:
        - Incremental update: O(1) per new observation
        - No external dependencies (pure Python math/statistics)
        - Complements Bayesian model: statistics describe, Bayes predicts
    """

    def __init__(self) -> None:
        # --- Sufficient statistics for incremental update ---
        self._n: int = 0
        self._sum_pnl: float = 0.0
        self._sum_pnl_sq: float = 0.0  # For variance: Σ(x²)
        self._wins: int = 0
        self._losses: int = 0
        self._gross_profit: float = 0.0
        self._gross_loss: float = 0.0
        self._peak: float = 0.0  # Running peak for drawdown
        self._max_drawdown: float = 0.0
        self._cumulative: float = 0.0  # Running cumulative PnL
        self._consecutive_losses: int = 0
        self._max_consecutive_losses: int = 0
        self._pnl_history: List[float] = []  # Bounded history for Sharpe
        self._max_history: int = 50  # Rolling window size

    def update(self, pnl_usdt: float) -> None:
        """Incrementally update statistics with a new PnL observation."""
        self._n += 1
        self._sum_pnl += pnl_usdt
        self._sum_pnl_sq += pnl_usdt * pnl_usdt
        self._cumulative += pnl_usdt

        # Win/loss tracking
        if pnl_usdt > 0:
            self._wins += 1
            self._gross_profit += pnl_usdt
            self._consecutive_losses = 0
        elif pnl_usdt < 0:
            self._losses += 1
            self._gross_loss += abs(pnl_usdt)
            self._consecutive_losses += 1
            self._max_consecutive_losses = max(
                self._max_consecutive_losses, self._consecutive_losses
            )

        # Drawdown tracking
        if self._cumulative > self._peak:
            self._peak = self._cumulative
        drawdown = self._peak - self._cumulative
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown

        # Bounded history for rolling Sharpe
        self._pnl_history.append(pnl_usdt)
        if len(self._pnl_history) > self._max_history:
            self._pnl_history.pop(0)

    @property
    def expected_value(self) -> float:
        """E[PnL] = Σ(x) / n"""
        return self._sum_pnl / self._n if self._n > 0 else 0.0

    @property
    def std_dev(self) -> float:
        """σ = sqrt(E[x²] - E[x]²)"""
        if self._n < 2:
            return 0.0
        mean = self._sum_pnl / self._n
        variance = (self._sum_pnl_sq / self._n) - (mean * mean)
        return max(0.0, variance) ** 0.5

    @property
    def sharpe_ratio(self) -> float:
        """Risk-adjusted return: E[PnL] / σ (per-trade Sharpe)."""
        sigma = self.std_dev
        if sigma < 1e-9:
            return 0.0
        return self.expected_value / sigma

    @property
    def max_drawdown(self) -> float:
        """Maximum peak-to-trough decline in cumulative PnL."""
        return self._max_drawdown

    @property
    def win_rate(self) -> float:
        """Observed win rate = wins / n."""
        return self._wins / self._n if self._n > 0 else 0.0

    @property
    def win_rate_wilson_lower(self) -> float:
        """Wilson score interval lower bound (95% confidence).

        More conservative than naive win_rate for small samples.
        Formula: (p + z²/2n - z√(p(1-p)/n + z²/4n²)) / (1 + z²/n)
        where z = 1.96 for 95% CI.
        """
        if self._n == 0:
            return 0.0
        z = 1.96
        n = self._n
        p = self.win_rate
        denom = 1 + z * z / n
        numerator = p + z * z / (2 * n) - z * (
            p * (1 - p) / n + z * z / (4 * n * n)
        ) ** 0.5
        return max(0.0, numerator / denom)

    @property
    def profit_factor(self) -> float:
        """Gross profit / gross loss. >1.0 = profitable system."""
        if self._gross_loss < 1e-9:
            return float('inf') if self._gross_profit > 1e-9 else 0.0
        return self._gross_profit / self._gross_loss

    @property
    def kelly_fraction(self) -> float:
        """Kelly criterion: f* = (b·p - q) / b

        where p = win_rate, q = 1-p, b = avg_win/avg_loss.
        Capped to [0, 0.25] for safety (quarter-Kelly).
        """
        if self._n < 5 or self._losses == 0 or self._wins == 0:
            return 0.0
        p = self.win_rate
        q = 1 - p
        avg_win = self._gross_profit / self._wins
        avg_loss = self._gross_loss / self._losses
        if avg_loss < 1e-9:
            return 0.25
        b = avg_win / avg_loss
        kelly = (b * p - q) / b
        return max(0.0, min(0.25, kelly))  # Quarter-Kelly cap

    @property
    def consecutive_losses(self) -> int:
        """Current consecutive loss streak."""
        return self._consecutive_losses

    @property
    def max_consecutive_losses(self) -> int:
        """Historical maximum consecutive loss streak."""
        return self._max_consecutive_losses

    def to_dict(self) -> Dict[str, Any]:
        """Export all statistical metrics as a dictionary."""
        return {
            "sample_size": self._n,
            "expected_value": round(self.expected_value, 4),
            "std_dev": round(self.std_dev, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "win_rate": round(self.win_rate, 4),
            "win_rate_wilson_lower": round(self.win_rate_wilson_lower, 4),
            "profit_factor": (
                round(self.profit_factor, 4)
                if self.profit_factor != float('inf')
                else 999.0
            ),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
        }


class CognitiveReviewer:
    """Cognitive reviewer for trade result analysis and lesson extraction.

    Reviews completed trades, extracts cognitive lessons, and provides
    runtime cognitive context for injecting into subsequent trading decisions.
    """

    def __init__(self, lessons_filepath: Optional[str] = None):
        """Initialize the cognitive reviewer.

        Args:
            lessons_filepath: Optional path to persist lessons JSON file.
        """
        self._lessons: List[TradeLesson] = []
        self._lessons_filepath = lessons_filepath
        self._review_count = 0
        self._total_pnl = 0.0
        self._stats_model = CognitiveLoopEntry()  # Statistical model for cognitive loop

    def review(self, trade_result: Dict[str, Any]) -> Dict[str, Any]:
        """Review a completed trade and produce cognitive assessment.

        Args:
            trade_result: Dict with symbol, direction, entry/exit price,
                pnl_usdt, pnl_pct, confidence, hexagram, addon_count,
                hold_hours, exit_reason.

        Returns:
            {
                "symbol": "BTC",
                "assessment": "GOOD" | "NEUTRAL" | "BAD",
                "score": 0.0-1.0,
                "lessons": [lesson, ...],
                "pnl_usdt": float,
                "pnl_pct": float,
                "review_id": str,
                "timestamp": str,
            }
        """
        symbol = trade_result.get("symbol", "")
        pnl_usdt = trade_result.get("pnl_usdt", 0.0)
        pnl_pct = trade_result.get("pnl_pct", 0.0)
        confidence = trade_result.get("confidence", 0.5)
        addon_count = trade_result.get("addon_count", 0)
        hold_hours = trade_result.get("hold_hours", 0.0)
        exit_reason = trade_result.get("exit_reason", "")
        direction = trade_result.get("direction", "LONG")

        # Update tracking
        self._review_count += 1
        self._total_pnl += pnl_usdt
        self._stats_model.update(pnl_usdt)  # Update statistical model

        # Compute assessment score
        score = self._compute_score(pnl_pct, confidence, addon_count, hold_hours, exit_reason)

        # Determine assessment
        if score >= 0.65:
            assessment = "GOOD"
        elif score >= 0.40:
            assessment = "NEUTRAL"
        else:
            assessment = "BAD"

        # Extract lessons
        lessons = self.extract_lessons(trade_result, assessment, score)

        # Store lessons
        for lesson in lessons:
            self._lessons.append(lesson)

        return {
            "symbol": symbol,
            "assessment": assessment,
            "score": round(score, 4),
            "lessons": [l.to_dict() for l in lessons],
            "pnl_usdt": pnl_usdt,
            "pnl_pct": pnl_pct,
            "review_id": f"review-{self._review_count:04d}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    def extract_lessons(
        self, trade_result: Dict[str, Any], assessment: str, score: float,
    ) -> List[TradeLesson]:
        """Extract cognitive lessons from a trade result.

        Args:
            trade_result: The trade result dict.
            assessment: GOOD / NEUTRAL / BAD.
            score: Review score 0-1.

        Returns:
            List of TradeLesson objects.
        """
        lessons: List[TradeLesson] = []
        symbol = trade_result.get("symbol", "")
        pnl_usdt = trade_result.get("pnl_usdt", 0.0)
        confidence = trade_result.get("confidence", 0.5)
        addon_count = trade_result.get("addon_count", 0)
        hold_hours = trade_result.get("hold_hours", 0.0)
        exit_reason = trade_result.get("exit_reason", "")
        now = datetime.utcnow().isoformat() + "Z"

        # Lesson: timeout exit with max addons
        if "timeout" in exit_reason.lower() and addon_count >= 3:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-timeout",
                category="exit",
                description=f"Timeout exit with {addon_count} addons on {symbol}: "
                           f"consider tighter entry criteria or earlier cut",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # Lesson: low confidence trade resulted in loss
        if pnl_usdt < 0 and confidence < 0.55:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-lowconf",
                category="direction",
                description=f"Low confidence ({confidence:.2f}) trade on {symbol} "
                           f"resulted in loss ({pnl_usdt:.2f} USDT): "
                           f"raise minimum confidence threshold",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # Lesson: high confidence trade won
        # F-2 fix (2026-08-16): 0.70→0.50, 与执行门禁 MIN_CONFIDENCE 对齐,
        # 确保所有过门禁的盈利单都能沉淀正向经验(原0.70高于旧公式天花板0.6,
        # 正向lesson结构性不可达; F-1修复后新天花板0.85, 0.50=执行门禁值)
        if pnl_usdt > 0 and confidence >= 0.50:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-goodentry",
                category="direction",
                description=f"High confidence ({confidence:.2f}) trade on {symbol} "
                           f"profited ({pnl_usdt:.2f} USDT): "
                           f"maintain entry criteria quality",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # Lesson: excessive holding time
        if hold_hours > 30 and pnl_usdt < 0:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-holdtime",
                category="timing",
                description=f"Excessive hold time ({hold_hours:.1f}h) on {symbol} "
                           f"with negative PnL: consider earlier exit signals",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # Lesson: addon strategy failure
        if addon_count > 0 and pnl_usdt < 0:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-addon",
                category="addon",
                description=f"Addon strategy ({addon_count} addons) on {symbol} "
                           f"failed with {pnl_usdt:.2f} USDT loss: "
                           f"review addon entry conditions",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # ── T0-T5 交易认知体系增强规则（10个）──

        # T3: 波动率风控 — C5 熔断检测
        pnl_pct = trade_result.get("pnl_pct", 0.0)
        if abs(pnl_pct) >= 0.15:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-c5vol",
                category="risk",
                description=f"C5熔断触发: {symbol} 单次亏损 {pnl_pct:.1%} >= 15%: "
                           f"立即平仓+反思闭环，禁止补仓摊平",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T3: 连败风控 — 连续3次亏损
        consecutive_losses = trade_result.get("consecutive_losses", 0)
        if consecutive_losses >= 3:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-c5loss",
                category="risk",
                description=f"C5熔断触发: {symbol} 连续{consecutive_losses}次亏损: "
                           f"降低confidence+触发冷却期，进入反思闭环",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T2: 止损纪律 — 无止损或止损放宽
        stop_loss_set = trade_result.get("stop_loss_set", True)
        stop_loss_widened = trade_result.get("stop_loss_widened", False)
        if not stop_loss_set or stop_loss_widened:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-sl discipline",
                category="risk",
                description=f"止损纪律违规: {symbol} "
                           f"{'无止损设置' if not stop_loss_set else '止损被放宽'}: "
                           f"无止损=禁止开仓，止损只能收紧不能放宽",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T2: 资金管理 — 可用资金不足
        available_pct = trade_result.get("available_balance_pct", 1.0)
        if available_pct < 0.20:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-capital",
                category="capital",
                description=f"资金管理告警: {symbol} 可用资金仅 {available_pct:.0%}: "
                           f"限制仓位，只允许P1侦察仓(10-15%)",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T2: 验证前置 — 未通过验证
        validated = trade_result.get("validated", True)
        practice_count = trade_result.get("practice_count", 2)
        if not validated or practice_count < 2:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-validate",
                category="validation",
                description=f"验证前置未通过: {symbol} "
                           f"实践次数={practice_count}(<2): "
                           f"只允许P1侦察仓，禁止大仓执行",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T0+T4: 趋势跟踪 — MA方向不一致
        ma_trend_consistent = trade_result.get("ma_trend_consistent", True)
        if not ma_trend_consistent:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-trend",
                category="trend",
                description=f"趋势不一致: {symbol} MA5/MA10/MA20方向冲突: "
                           f"降低confidence，T4 Level 1.5告警",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T2+T4: 离场纪律 — 离场层命中
        exit_layer = trade_result.get("exit_layer", 0)
        if exit_layer > 0:
            layer_names = {1: "技术离场", 2: "风险事件", 3: "情报联动", 4: "强制审计"}
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-exit",
                category="exit",
                description=f"四层离场链命中: {symbol} Layer{exit_layer}({layer_names.get(exit_layer, '?')}): "
                           f"立即离场，记录离场原因",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T5: 纸上谈兵检测 — 无实际执行
        skill_executed = trade_result.get("skill_executed", True)
        if not skill_executed:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-paper",
                category="execution",
                description=f"纸上谈兵检测: {symbol} 仅分析未实际执行: "
                           f"禁止进入大仓阶段，C8强制试探未满足",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T1: 情景证伪 — 证伪条件触发
        scenario_invalidated = trade_result.get("scenario_invalidated", False)
        if scenario_invalidated:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-falsify",
                category="strategy",
                description=f"情景证伪: {symbol} S1/S2/S3某情景证伪条件触发: "
                           f"调整strategy_directive，重新评估方向",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        # T5: 回滚机制 — P&L回撤>3%
        pnl_drawdown = trade_result.get("pnl_drawdown", 0.0)
        if pnl_drawdown > 0.03:
            lessons.append(TradeLesson(
                lesson_id=f"lesson-{self._review_count:04d}-rollback",
                category="rollback",
                description=f"回滚机制触发: {symbol} P&L回撤 {pnl_drawdown:.1%} > 3%: "
                           f"回滚到上一个稳定状态，进入观察期",
                symbol=symbol,
                trade_pnl=pnl_usdt,
                confidence_at_entry=confidence,
                created_at=now,
            ))

        return lessons

    def get_cognitive_context(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get cognitive context for runtime injection into trading decisions.

        Args:
            symbol: Optional symbol filter for lessons.

        Returns:
            {
                "total_reviews": int,
                "total_pnl": float,
                "win_rate": float,
                "recent_lessons": [lesson, ...],
                "symbol_lessons": [lesson, ...] if symbol provided,
                "confidence_adjustment": float,  # -0.1 to +0.1
            }
        """
        # Filter lessons by symbol if provided
        relevant_lessons = self._lessons
        if symbol:
            relevant_lessons = [l for l in self._lessons if l.symbol == symbol]

        # Compute win rate
        winning = sum(1 for l in self._lessons if l.trade_pnl > 0)
        total = len(self._lessons)
        win_rate = winning / total if total > 0 else 0.0

        # ===== Bayesian confidence adjustment (Beta-Binomial conjugate model) =====
        # Replaces naive linear PnL mapping with rigorous Bayesian posterior.
        #
        # Model:
        #   alpha = 1 + wins    (pseudo-count + observed successes)
        #   beta  = 1 + losses  (pseudo-count + observed failures)
        #   posterior_mean = alpha / (alpha + beta)  ← E[P(success)]
        #
        # Integration with T-series cognitive framework:
        #   - T3 Risk Gatekeeper: consecutive losses ≥3 triggers circuit breaker
        #   - T5 Meta-Reflection: exponential forgetting (half-life 30d)
        #   - Mapping: (posterior - 0.5) × 0.2 → [-0.1, +0.1]
        #
        import math

        recent = self._lessons[-20:] if len(self._lessons) > 20 else self._lessons

        # --- Step 1: Beta-Binomial sufficient statistics ---
        wins = sum(1 for l in recent if l.trade_pnl > 0)
        losses = sum(1 for l in recent if l.trade_pnl < 0)
        alpha = 1 + wins   # Beta prior α (uninformative: Beta(1,1))
        beta_param = 1 + losses  # Beta prior β
        posterior_mean = alpha / (alpha + beta_param)  # E[P(success)]

        # --- Step 2: Exponential forgetting (T5 observation period) ---
        # ff = exp(-ln2 × age / half_life), forgotten = ff × posterior + (1-ff) × 0.5
        # Half-life: 30 days (C-level memory, fast adaptation to regime change)
        _FORGET_LAMBDA = math.log(2)
        _HALF_LIFE_SECS = 30 * 86400.0  # 30 days in seconds
        now = datetime.now()

        forgotten_posteriors = []
        for l in recent:
            try:
                created = datetime.fromisoformat(l.created_at)
                age_secs = max(0.0, (now - created).total_seconds())
            except (ValueError, TypeError):
                age_secs = 0.0
            if _HALF_LIFE_SECS > 0:
                ff = math.exp(-_FORGET_LAMBDA * age_secs / _HALF_LIFE_SECS)
                ff = max(0.0, min(1.0, ff))
            else:
                ff = 1.0
            # Per-lesson posterior: win→1.0, loss→0.0, flat→0.5
            obs = 1.0 if l.trade_pnl > 0 else (0.0 if l.trade_pnl < 0 else 0.5)
            forgotten_posteriors.append(ff * obs + (1.0 - ff) * 0.5)

        # Weighted average of forgotten posteriors
        if forgotten_posteriors:
            bayesian_estimate = sum(forgotten_posteriors) / len(forgotten_posteriors)
        else:
            bayesian_estimate = 0.5

        # Blend global Beta posterior with per-lesson forgotten estimate
        blended = 0.5 * posterior_mean + 0.5 * bayesian_estimate

        # --- Step 3: T3 circuit breaker (consecutive losses ≥3) ---
        consecutive_losses = 0
        for l in reversed(recent):
            if l.trade_pnl < 0:
                consecutive_losses += 1
            else:
                break
        circuit_breaker_penalty = 0.0
        if consecutive_losses >= 3:
            # T3 熔断: scale penalty with consecutive loss count
            circuit_breaker_penalty = -0.05 * min(1.0, consecutive_losses / 5.0)

        # --- Step 4: Map to [-0.1, +0.1] range ---
        # (blended - 0.5) × 0.2 maps [0,1] → [-0.1, +0.1]
        confidence_adjustment = (blended - 0.5) * 0.2 + circuit_breaker_penalty
        confidence_adjustment = max(-0.1, min(0.1, confidence_adjustment))

        return {
            "total_reviews": self._review_count,
            "total_pnl": round(self._total_pnl, 4),
            "win_rate": round(win_rate, 4),
            "recent_lessons": [l.to_dict() for l in recent],
            "symbol_lessons": [l.to_dict() for l in relevant_lessons[-5:]] if symbol else [],
            "confidence_adjustment": round(confidence_adjustment, 4),
            "statistics": self._stats_model.to_dict(),
        }

    def load_lessons(self, filepath: Optional[str] = None) -> int:
        """Load lessons from the persistence file (startup recovery).

        Complements persist_lessons(): restores in-memory lessons and the
        cumulative counters after a process restart. Dedupes by lesson_id
        so repeated loads are safe.

        Args:
            filepath: Path to lessons file. Uses init path if not provided.

        Returns:
            Number of lessons newly loaded (0 if file missing/corrupt).
        """
        path = filepath or self._lessons_filepath
        if not path or not Path(path).exists():
            return 0
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return 0

        existing_ids = {l.lesson_id for l in self._lessons}
        loaded = 0
        for ld in data.get("lessons", []):
            if not isinstance(ld, dict):
                continue
            lid = str(ld.get("lesson_id", ""))
            if not lid or lid in existing_ids:
                continue
            self._lessons.append(TradeLesson(
                lesson_id=lid,
                category=str(ld.get("category", "")),
                description=str(ld.get("description", "")),
                symbol=str(ld.get("symbol", "")),
                trade_pnl=float(ld.get("trade_pnl", 0.0) or 0.0),
                confidence_at_entry=float(ld.get("confidence_at_entry", 0.5) or 0.5),
                created_at=str(ld.get("created_at", "")),
            ))
            existing_ids.add(lid)
            loaded += 1

        # 恢复累计计数器：仅在本实例尚未产生过 review 时以文件为准
        # (文件由 persist_lessons 每轮落盘，是跨重启的权威累计值)
        if self._review_count == 0:
            self._review_count = int(data.get("total_reviews", 0) or 0)
            self._total_pnl = float(data.get("total_pnl", 0.0) or 0.0)

        return loaded

    def persist_lessons(self, filepath: Optional[str] = None) -> None:
        """Persist all lessons to a JSON file.

        Args:
            filepath: Path to output file. Uses init path if not provided.
        """
        path = filepath or self._lessons_filepath
        if not path:
            return

        data = {
            "lessons": [l.to_dict() for l in self._lessons],
            "total_reviews": self._review_count,
            "total_pnl": self._total_pnl,
            "persisted_at": datetime.utcnow().isoformat() + "Z",
        }

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _compute_score(
        self, pnl_pct: float, confidence: float,
        addon_count: int, hold_hours: float, exit_reason: str,
    ) -> float:
        """Compute review score from trade metrics.

        Score components:
            - PnL percentage (weight: 0.50)
            - Confidence alignment (weight: 0.20)
            - Addon efficiency (weight: 0.15)
            - Hold time efficiency (weight: 0.15)
        """
        # PnL component: map pnl_pct to 0-1 range
        # Positive pnl → high score, negative → low score
        pnl_score = max(0.0, min(1.0, 0.5 + pnl_pct * 5))

        # Confidence alignment: did high confidence lead to profit?
        if pnl_pct > 0 and confidence >= 0.6:
            conf_score = 0.9
        elif pnl_pct < 0 and confidence < 0.5:
            conf_score = 0.6  # Low confidence loss is somewhat expected
        elif pnl_pct < 0 and confidence >= 0.7:
            conf_score = 0.2  # High confidence loss is bad signal
        else:
            conf_score = 0.5

        # Addon efficiency: fewer addons with profit is better
        if pnl_pct > 0:
            addon_score = max(0.3, 1.0 - addon_count * 0.2)
        else:
            addon_score = max(0.1, 0.5 - addon_count * 0.1)

        # Hold time efficiency: shorter holds with profit are better
        if hold_hours <= 12:
            time_score = 0.9
        elif hold_hours <= 24:
            time_score = 0.7
        elif hold_hours <= 30:
            time_score = 0.5
        else:
            time_score = 0.3

        score = (
            pnl_score * 0.50 +
            conf_score * 0.20 +
            addon_score * 0.15 +
            time_score * 0.15
        )

        return max(0.0, min(1.0, score))

    @property
    def lessons(self) -> List[TradeLesson]:
        """Get all stored lessons."""
        return self._lessons

    @property
    def stats(self) -> Dict[str, Any]:
        """Get reviewer statistics including CognitiveLoopEntry metrics."""
        return {
            "total_reviews": self._review_count,
            "total_pnl": self._total_pnl,
            "total_lessons": len(self._lessons),
            "statistics": self._stats_model.to_dict(),
        }


# ---- Task 3: CognitiveReviewerNode ----

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class CognitiveReviewerNode(BaseNode):
    """CognitiveReviewer node wrapper for DreamOS orchestration.

    Wraps CognitiveReviewer into a BaseNode-compatible node,
    enabling it to participate in the DreamOS execution graph.
    """

    node_id: str = "COGNITIVE_REVIEW"
    name: str = "Cognitive Reviewer"
    description: str = "Review trade results and extract cognitive lessons"
    chain: str = "E"
    tags: list = ["trading", "cognitive", "review", "learning"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reviewer = CognitiveReviewer()

    def execute_core(self, state: State) -> NodeResult:
        """Execute cognitive review and return NodeResult.

        Reads trade result from state.market, calls CognitiveReviewer.review(),
        and wraps the result into a NodeResult.
        """
        trade_result = state.market or {}

        review = self._reviewer.review(trade_result)

        assessment = review.get("assessment", "NEUTRAL")
        score = review.get("score", 0.5)

        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=score,
            direction=trade_result.get("direction", "HOLD"),
            outputs={
                "symbol": review.get("symbol", ""),
                "assessment": assessment,
                "score": score,
                "lessons": review.get("lessons", []),
                "pnl_usdt": review.get("pnl_usdt", 0.0),
                "pnl_pct": review.get("pnl_pct", 0.0),
                "review_id": review.get("review_id", ""),
                "statistics": self._reviewer.stats.get("statistics", {}),
                "source": "cognitive-review",
            },
        )
