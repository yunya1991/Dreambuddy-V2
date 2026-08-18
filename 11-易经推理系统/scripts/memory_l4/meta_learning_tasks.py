import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import artifacts_memory_l4_dir


def _default_tasks_dir() -> Path:
    return artifacts_memory_l4_dir() / "meta_learning"


def enqueue_meta_learning_tasks(
    snapshot_ts: str,
    risk_signals: List[Dict[str, Any]],
    migration_mappings: List[Dict[str, Any]],
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    tasks: List[Dict[str, Any]] = []
    for rs in risk_signals or []:
        rs_id = str(rs.get("risk_signal_id") or "unknown")
        tasks.append(
            {
                "task_id": f"ML_RS_{rs_id}",
                "task_type": "hypothesis_validation",
                "status": "pending",
                "priority": "high",
                "snapshot_ts": snapshot_ts,
                "inputs": {"risk_signal_id": rs_id, "confidence": rs.get("confidence")},
            }
        )
    for mp in migration_mappings or []:
        mp_id = str(mp.get("mapping_id") or "unknown")
        tasks.append(
            {
                "task_id": f"ML_MAP_{mp_id}",
                "task_type": "cross_market_backtest",
                "status": "pending",
                "priority": "medium",
                "snapshot_ts": snapshot_ts,
                "inputs": {"mapping_id": mp_id, "migration_confidence": mp.get("migration_confidence")},
            }
        )

    out_dir = Path(output_dir) if output_dir is not None else _default_tasks_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks_path = out_dir / "meta_tasks.jsonl"
    summary_path = out_dir / "summary.json"

    with tasks_path.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    summary = {
        "version": "v0.1",
        "snapshot_ts": snapshot_ts,
        "tasks_count": len(tasks),
        "risk_signal_tasks": len(risk_signals or []),
        "migration_tasks": len(migration_mappings or []),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"tasks_path": str(tasks_path), "summary_path": str(summary_path), "summary": summary}
