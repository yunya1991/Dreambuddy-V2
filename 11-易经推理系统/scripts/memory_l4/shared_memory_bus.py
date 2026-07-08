import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.agent_acl import authorize
from scripts.memory_l4.paths import artifacts_memory_l4_dir


def _default_bus_path() -> Path:
    return artifacts_memory_l4_dir() / "shared_bus" / "events.jsonl"


def publish_shared_memory_event(
    snapshot_ts: str,
    agent_id: str,
    event_type: str,
    payload: Dict[str, Any],
    output_dir: Optional[Path] = None,
    acl_config: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    acl_decision = authorize(agent_id=agent_id, action="publish", acl_config=acl_config)
    if not acl_decision.get("allow"):
        return {
            "ok": False,
            "denied": True,
            "reason": str(acl_decision.get("reason") or "acl_denied"),
            "acl_decision": acl_decision,
            "bus_path": str((Path(output_dir) / "events.jsonl") if output_dir is not None else _default_bus_path()),
        }

    bus_path = (Path(output_dir) / "events.jsonl") if output_dir is not None else _default_bus_path()
    bus_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "version": "v0.1",
        "ts": snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds"),
        "agent_id": str(agent_id or "unknown"),
        "event_type": str(event_type or "unknown"),
        "payload": payload or {},
        "acl_decision": acl_decision,
    }
    with bus_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"ok": True, "bus_path": str(bus_path), "event": event, "acl_decision": acl_decision}


def read_shared_memory_events(
    bus_path: Optional[Path] = None,
    limit: int = 1000,
    agent_id: str = "",
    acl_config: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    acl_decision = authorize(agent_id=agent_id, action="read", acl_config=acl_config)
    if not acl_decision.get("allow"):
        return []

    p = Path(bus_path) if bus_path is not None else _default_bus_path()
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            out.append(json.loads(text))
        except Exception:
            continue
    if limit > 0:
        return out[-limit:]
    return out
