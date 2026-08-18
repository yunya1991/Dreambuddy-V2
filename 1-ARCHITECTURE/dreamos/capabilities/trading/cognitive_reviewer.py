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

        # Compute confidence adjustment based on recent performance
        recent = self._lessons[-10:] if len(self._lessons) > 10 else self._lessons
        recent_pnl = sum(l.trade_pnl for l in recent)
        if recent_pnl > 0:
            confidence_adjustment = min(0.1, recent_pnl / 1000.0)
        elif recent_pnl < 0:
            confidence_adjustment = max(-0.1, recent_pnl / 1000.0)
        else:
            confidence_adjustment = 0.0

        return {
            "total_reviews": self._review_count,
            "total_pnl": round(self._total_pnl, 4),
            "win_rate": round(win_rate, 4),
            "recent_lessons": [l.to_dict() for l in recent],
            "symbol_lessons": [l.to_dict() for l in relevant_lessons[-5:]] if symbol else [],
            "confidence_adjustment": round(confidence_adjustment, 4),
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
        """Get reviewer statistics."""
        return {
            "total_reviews": self._review_count,
            "total_pnl": self._total_pnl,
            "total_lessons": len(self._lessons),
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
                "source": "cognitive-review",
            },
        )
