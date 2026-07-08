"""L4 memory retrieval helper for A-series trading stages.

Each A-series stage calls this to query historical L4 memory references
before writing its artifact. Retrieval is non-blocking: if the index is
unavailable or any error occurs, an empty list is returned.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure scripts/ is on syspath for index_builder and query_similar
_SCRIPTS_ROOT = Path(__file__).resolve().parents[3]
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))


def _safe_retrieve(stage_id: str, payload: Dict[str, Any], topk: int) -> List[Dict[str, Any]]:
    """Internal retrieval logic (called inside a try/except by the public API)."""
    from scripts.memory_l4.index_builder import default_index_path, load_cases, load_distills, load_episodes_for_cases, build_index_data
    from scripts.memory_l4.query_similar import query_similar_cases, query_by_regime_and_outcome

    index_path = default_index_path()
    index_data = None

    if index_path.exists():
        import json
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index_data = None

    # Fallback: if no index file but cases exist, build in-memory index
    if index_data is None:
        cases = load_cases()
        if not cases:
            return []
        distills = load_distills()
        episodes = load_episodes_for_cases(cases)
        from datetime import datetime
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        index_data = build_index_data(ts, cases, distills, episodes)

    # Strategy 1: If case_id is available, do similarity search
    case_id = payload.get("case_id")
    if case_id and index_data and index_data.get("case_features"):
        feats = index_data.get("case_features", {})
        if str(case_id) in feats:
            try:
                sim_result = query_similar_cases(index_data, case_id=str(case_id), topk=topk)
                results = sim_result.get("results") or []
                if results:
                    return _format_refs(results)
            except KeyError:
                pass  # case_id not in index, fall through

    # Strategy 2: Fall back to regime-based query
    regime = payload.get("market_regime")
    if regime:
        regime_result = query_by_regime_and_outcome(regime, outcome=None, topk=topk)
        cases = regime_result.get("cases") or []
        if cases:
            return _format_regime_refs(cases)

    return []


def _format_refs(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format similarity search results into memory_refs."""
    refs = []
    for r in results:
        ref: Dict[str, Any] = {
            "case_id": r.get("case_id"),
            "similarity": r.get("similarity", 0.0),
            "kind": "case",
        }
        refs.append(ref)
    return refs


def _format_regime_refs(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format regime-based query results into memory_refs."""
    refs = []
    for c in cases:
        ref: Dict[str, Any] = {
            "case_id": c.get("case_id"),
            "kind": "case",
            "source": "regime_query",
        }
        refs.append(ref)
    return refs


def retrieve_memory_refs_for_stage(
    stage_id: str,
    payload: Dict[str, Any],
    topk: int = 3,
) -> List[Dict[str, Any]]:
    """Retrieve L4 memory references for an A-series trading stage.

    Args:
        stage_id: "A1", "A3", "A4", "A5", or "A9"
        payload: The stage input payload (contains regime, case_id, etc.)
        topk: Number of references to retrieve

    Returns:
        List of memory reference dicts. Empty list if index unavailable or
        retrieval fails (non-blocking).
    """
    # A1 is the first stage; nothing to look up yet
    if stage_id == "A1":
        return []

    try:
        return _safe_retrieve(stage_id, payload, topk)
    except Exception:
        return []
