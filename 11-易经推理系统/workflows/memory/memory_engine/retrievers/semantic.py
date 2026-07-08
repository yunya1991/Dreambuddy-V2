import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _build_case_docs(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    case_id = str(case.get("case_id") or "").strip()
    if not case_id:
        return []

    docs: List[Dict[str, Any]] = []
    intent = case.get("intent") or {}
    review = case.get("review") or {}

    fields = [
        ("intent.question", str(intent.get("question") or "")),
        ("review.summary", str(review.get("summary") or "")),
    ]
    for field_name, text in fields:
        payload = text.strip()
        if not payload:
            continue
        docs.append(
            {
                "id": f"{case_id}:{field_name}",
                "kind": "case",
                "text": payload,
                "refs": {"case_id": case_id, "field": field_name},
            }
        )

    for idx, lesson in enumerate(review.get("lessons") or []):
        payload = str(lesson or "").strip()
        if not payload:
            continue
        docs.append(
            {
                "id": f"{case_id}:review.lessons[{idx}]",
                "kind": "case",
                "text": payload,
                "refs": {"case_id": case_id, "field": "review.lessons"},
            }
        )
    return docs


def _build_distill_docs(distill: Dict[str, Any]) -> List[Dict[str, Any]]:
    distill_id = str(distill.get("distill_id") or "").strip()
    if not distill_id:
        return []

    docs: List[Dict[str, Any]] = []
    claim = str(distill.get("claim") or "").strip()
    if claim:
        docs.append(
            {
                "id": f"{distill_id}:claim",
                "kind": "distill",
                "text": claim,
                "refs": {"distill_id": distill_id, "field": "claim"},
            }
        )

    for idx, rule in enumerate(distill.get("actionable_rules") or []):
        payload = str(rule or "").strip()
        if not payload:
            continue
        docs.append(
            {
                "id": f"{distill_id}:actionable_rules[{idx}]",
                "kind": "distill",
                "text": payload,
                "refs": {"distill_id": distill_id, "field": "actionable_rules"},
            }
        )
    return docs


def build_semantic_docs(cases: List[Dict[str, Any]], distills: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    for case in cases:
        docs.extend(_build_case_docs(case))
    for distill in distills:
        docs.extend(_build_distill_docs(distill))
    return docs


def write_vector_artifacts(
    vector_dir: Path,
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    index_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    vector_dir.mkdir(parents=True, exist_ok=True)
    docs = build_semantic_docs(cases, distills)

    build_ts = datetime.now().astimezone().isoformat(timespec="seconds")
    docs_path = vector_dir / "docs.jsonl"
    docs_lines = [json.dumps(item, ensure_ascii=False) for item in docs]
    docs_path.write_text("\n".join(docs_lines) + ("\n" if docs_lines else ""), encoding="utf-8")

    feature_version = str((index_metadata or {}).get("feature_version") or "v0.1")
    source_snapshot_ts = str((index_metadata or {}).get("snapshot_ts") or build_ts)
    index_id = f"memory_l4:{feature_version}:{source_snapshot_ts}"

    manifest = {
        "version": "v0.1",
        "build_ts": build_ts,
        "source_snapshot_ts": source_snapshot_ts,
        "feature_version": feature_version,
        "index_id": index_id,
        "docs_count": len(docs),
        "docs_file": "docs.jsonl",
        "doc_fields": {
            "case": ["intent.question", "review.summary", "review.lessons"],
            "distill": ["claim", "actionable_rules"],
        },
        "embedding": {
            "provider": "local-placeholder",
            "model": "not-configured",
        },
    }
    manifest_path = vector_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "vector_dir": str(vector_dir),
        "docs_count": len(docs),
        "docs_path": str(docs_path),
        "manifest_path": str(manifest_path),
    }


def _tokenize(text: str) -> List[str]:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return []
    for ch in [",", ".", ";", ":", "!", "?", "\n", "\t", "(", ")", "[", "]", "{", "}", "，", "。", "；", "：", "！", "？"]:
        lowered = lowered.replace(ch, " ")
    return [t for t in lowered.split(" ") if t]


def retrieve_semantic(
    context: Dict[str, Any],
    topk: int,
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    vector_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    query_tokens = set(_tokenize(str(context.get("query_text") or "")))
    if not query_tokens:
        return []

    docs: List[Dict[str, Any]] = []
    vector_source: Dict[str, str] = {"kind": "memory_fallback"}
    if vector_dir is not None:
        docs, vector_source = load_semantic_docs(vector_dir)
    if not docs:
        docs = build_semantic_docs(cases, distills)
        vector_source = {"kind": "memory_fallback"}
    scored: List[Dict[str, Any]] = []
    for doc in docs:
        text = str(doc.get("text") or "").lower()
        if not text:
            continue
        overlap = 0
        for token in query_tokens:
            if token and token in text:
                overlap += 1
        if overlap <= 0:
            continue
        score = float(overlap) / float(max(len(query_tokens), 1))
        scored.append(
            {
                "id": str(doc.get("id") or ""),
                "kind": str(doc.get("kind") or ""),
                "score": round(score, 4),
                "refs": doc.get("refs") or {},
                "matched_text": str(doc.get("text") or ""),
                "vector_source": dict(vector_source),
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[: int(topk)]


def load_semantic_docs(vector_dir: Path) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    base = Path(vector_dir)
    docs_file = "docs.jsonl"
    manifest_path = base / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            docs_file_value = str((manifest or {}).get("docs_file") or "").strip()
            if docs_file_value:
                docs_file = docs_file_value
        except Exception:
            pass

    docs_path = base / docs_file
    if not docs_path.exists():
        return [], {"kind": "vector_index", "docs_file": docs_file, "vector_dir": str(base)}
    out: List[Dict[str, Any]] = []
    for ln in docs_path.read_text(encoding="utf-8").splitlines():
        line = ln.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out, {"kind": "vector_index", "docs_file": docs_file, "vector_dir": str(base)}
