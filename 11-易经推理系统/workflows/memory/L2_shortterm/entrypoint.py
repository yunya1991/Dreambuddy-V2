from typing import Any, Dict, List, Optional

from workflows.memory.memory_engine.engine import MemoryEngine


def run_l2_shortterm_feedback(
    events: List[Dict[str, Any]],
    context: Optional[Dict[str, Any]] = None,
    unrealized_discount: float = 0.7,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for shortterm feedback update."""
    mem = engine or MemoryEngine()
    return mem.update_bandit_from_episodes(
        events=events,
        context=context,
        unrealized_discount=unrealized_discount,
    )


def run_l2_shortterm_health_check(engine: Optional[MemoryEngine] = None) -> Dict[str, Any]:
    """Thin wrapper for shortterm consistency and health check."""
    mem = engine or MemoryEngine()
    report = mem.check_consistency()
    score = mem.get_health_score()
    return {
        "consistency_report": report,
        "health_score": score,
    }
