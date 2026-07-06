import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import artifacts_memory_l4_dir


def _default_graph_path() -> Path:
    return artifacts_memory_l4_dir() / "graph" / "graph.json"


def _edge_relation(event_type: str) -> str:
    if event_type == "memory_publish":
        return "published"
    if event_type == "memory_reference":
        return "referenced"
    if event_type == "meta_task_created":
        return "created_task"
    return "related"


def build_memory_graph(
    snapshot_ts: str,
    events: List[Dict[str, Any]],
    output_dir: Optional[Path] = None,
    require_evidence_refs: bool = True,
) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_nodes: Set[str] = set()
    seen_edges: Set[Tuple[str, str, str]] = set()
    dropped_edges: List[Dict[str, Any]] = []

    for ev in events or []:
        agent_id = str(ev.get("agent_id") or "unknown")
        payload = ev.get("payload") or {}
        memory_id = str(payload.get("memory_id") or "")
        memory_kind = str(payload.get("kind") or "memory_item")

        agent_node_id = f"agent:{agent_id}"
        if agent_node_id not in seen_nodes:
            nodes.append({"id": agent_node_id, "type": "agent", "label": agent_id})
            seen_nodes.add(agent_node_id)

        if memory_id:
            memory_node_id = f"{memory_kind}:{memory_id}"
            if memory_node_id not in seen_nodes:
                nodes.append({"id": memory_node_id, "type": memory_kind, "label": memory_id})
                seen_nodes.add(memory_node_id)
            relation = _edge_relation(str(ev.get("event_type") or ""))
            edge_key = (agent_node_id, memory_node_id, relation)
            if edge_key not in seen_edges:
                evidence_refs = payload.get("evidence_refs") or []
                if require_evidence_refs and not evidence_refs:
                    dropped_edges.append(
                        {
                            "source": agent_node_id,
                            "target": memory_node_id,
                            "relation": relation,
                            "reason": "missing_evidence_refs",
                            "ts": ev.get("ts"),
                        }
                    )
                    continue
                edges.append(
                    {
                        "source": agent_node_id,
                        "target": memory_node_id,
                        "relation": relation,
                        "ts": ev.get("ts"),
                        "evidence_refs": evidence_refs,
                    }
                )
                seen_edges.add(edge_key)

    payload = {
        "version": "v0.1",
        "snapshot_ts": snapshot_ts,
        "nodes": nodes,
        "edges": edges,
        "dropped_edges": dropped_edges,
    }
    graph_path = (Path(output_dir) / "graph.json") if output_dir is not None else _default_graph_path()
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    graph_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "graph_path": str(graph_path),
        "summary": {"nodes": len(nodes), "edges": len(edges), "dropped_edges": len(dropped_edges)},
    }
