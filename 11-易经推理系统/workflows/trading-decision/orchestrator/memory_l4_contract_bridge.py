from __future__ import annotations

import json
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_l4_entrypoint_module():
    root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return _load_module(root / "memory" / "L4_archive" / "entrypoint.py", "memory_l4_entrypoint")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_list(payload: Dict[str, Any], key: str) -> List[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be list")
    return value


def _load_mappings(migration_out: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = migration_out.get("mapping_table_path")
    if not path:
        return []
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    mappings = doc.get("mappings")
    if isinstance(mappings, list):
        return mappings
    return []


def run_trading_memory_l4_contract(payload: Dict[str, Any], output_dir: Optional[Path] = None) -> Dict[str, Any]:
    l4 = _load_l4_entrypoint_module()
    trace_id = str(payload.get("trace_id") or "")
    if not trace_id:
        raise ValueError("trace_id is required")

    memory_refs = _require_list(payload, "memory_refs")
    evidence_refs = _require_list(payload, "evidence_refs")
    memory_events = _require_list(payload, "memory_events")
    risk_signals = list(payload.get("risk_signals") or [])
    source_market = str(payload.get("source_market") or "CRYPTO")
    target_market = str(payload.get("target_market") or "HK")

    graph_out = l4.run_l4_graph_build(
        events=memory_events,
        output_dir=output_dir,
        require_evidence_refs=True,
    )
    migration_out = l4.run_l4_cross_market_migration(
        source_market=source_market,
        target_market=target_market,
        output_dir=output_dir,
    )
    mappings = _load_mappings(migration_out)
    meta_out = l4.run_l4_meta_task_enqueue(
        risk_signals=risk_signals,
        migration_mappings=mappings,
        output_dir=output_dir,
    )

    out = {
        "stage_id": "L4",
        "trace_id": trace_id,
        "constraint_version": str(payload.get("constraint_version") or "v0.1"),
        "memory_refs": memory_refs,
        "evidence_refs": evidence_refs,
        "producer": "workflows/memory/L4_archive",
        "schema_version": str(payload.get("schema_version") or "2.0"),
        "timestamp": _utc_iso(),
        "l4_outputs": {
            "graph": graph_out,
            "migration": migration_out,
            "meta": meta_out,
        },
    }
    return out
