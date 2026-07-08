from pathlib import Path
from typing import Any, Dict, List, Optional

from workflows.memory.memory_engine.engine import MemoryEngine


def run_l4_failure_analysis(
    snapshot_ts: Optional[str] = None,
    episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
    output_dir: Optional[Path] = None,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for L4 failure analysis."""
    mem = engine or MemoryEngine()
    return mem.analyze_failure_memory(
        snapshot_ts=snapshot_ts,
        episodes_by_case_id=episodes_by_case_id,
        output_dir=output_dir,
    )


def run_l4_cross_market_migration(
    source_market: str,
    target_market: str,
    snapshot_ts: Optional[str] = None,
    episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
    output_dir: Optional[Path] = None,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for L4 cross-market migration."""
    mem = engine or MemoryEngine()
    return mem.analyze_cross_market_migration(
        snapshot_ts=snapshot_ts,
        source_market=source_market,
        target_market=target_market,
        episodes_by_case_id=episodes_by_case_id,
        output_dir=output_dir,
    )


def run_l4_graph_build(
    events: List[Dict[str, Any]],
    snapshot_ts: Optional[str] = None,
    output_dir: Optional[Path] = None,
    require_evidence_refs: bool = True,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for L4 graph build."""
    mem = engine or MemoryEngine()
    return mem.build_shared_memory_graph(
        snapshot_ts=snapshot_ts,
        events=events,
        output_dir=output_dir,
        require_evidence_refs=require_evidence_refs,
    )


def run_l4_meta_task_enqueue(
    risk_signals: List[Dict[str, Any]],
    migration_mappings: List[Dict[str, Any]],
    snapshot_ts: Optional[str] = None,
    output_dir: Optional[Path] = None,
    engine: Optional[MemoryEngine] = None,
) -> Dict[str, Any]:
    """Thin wrapper for L4 meta task enqueue."""
    mem = engine or MemoryEngine()
    return mem.enqueue_meta_learning_tasks(
        snapshot_ts=snapshot_ts,
        risk_signals=risk_signals,
        migration_mappings=migration_mappings,
        output_dir=output_dir,
    )
