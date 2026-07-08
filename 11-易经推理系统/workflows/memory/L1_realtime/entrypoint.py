from typing import Any, Dict, Optional

from workflows.memory.memory_engine.engine import MemoryEngine


def run_l1_realtime_retrieval(
    context: Dict[str, Any],
    topk: int = 10,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for L1 realtime retrieval."""
    mem = engine or MemoryEngine()
    return mem.retrieve_for_decision(context=context, topk=topk)


def run_l1_realtime_relevance(
    context: Dict[str, Any],
    topk: int = 10,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for L1 relevance matrix."""
    mem = engine or MemoryEngine()
    return mem.build_relevance_matrix(context=context, topk=topk)
