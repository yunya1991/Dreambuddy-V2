import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.memory_l4.query_similar import query_similar_cases


def load_index_data(default_path: Path) -> Optional[Dict[str, Any]]:
    if not default_path.exists():
        return None
    return json.loads(default_path.read_text(encoding="utf-8"))


def retrieve_structured(context: Dict[str, Any], topk: int, index_data: Optional[Dict[str, Any]], default_index_path: Path) -> List[Dict[str, Any]]:
    case_id = context.get("case_id")
    if not case_id:
        return []

    idx = index_data if index_data is not None else load_index_data(default_index_path)
    if idx is None:
        return []

    out = query_similar_cases(idx, case_id=str(case_id), topk=int(topk))
    results = out.get("results") or []

    items: List[Dict[str, Any]] = []
    for r in results:
        cid = r.get("case_id")
        if not cid:
            continue
        items.append(
            {
                "id": str(cid),
                "kind": "case",
                "score": float(r.get("similarity") or 0.0),
                "refs": {"case_id": str(cid)},
                "explain": r.get("explain"),
                "references": r.get("references")
            }
        )
    return items

