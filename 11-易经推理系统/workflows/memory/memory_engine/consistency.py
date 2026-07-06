import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_index_data(index_data: Optional[Dict[str, Any]], index_path: Path) -> Dict[str, Any]:
    if index_data is not None:
        return index_data
    if not index_path.exists():
        return {}
    return _load_json(index_path)


def _load_cases(cases: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if cases is not None:
        return cases
    return []


def _load_distills(distills: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if distills is not None:
        return distills
    return []


def _load_stats(stats: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return stats or {}


def _to_issue(code: str, entity_id: str, detail: str) -> Dict[str, str]:
    return {"code": code, "entity_id": entity_id, "detail": detail}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _memory_l4_schema_dir() -> Path:
    return _project_root() / ".workbuddy" / "memory_l4" / "schemas"


def _index_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": ["metadata", "case_features", "distill_features"],
        "properties": {
            "metadata": {
                "type": "object",
                "required": ["snapshot_ts", "feature_version", "weights"],
                "properties": {
                    "snapshot_ts": {"type": "string", "minLength": 1},
                    "feature_version": {"type": "string", "minLength": 1},
                    "weights": {
                        "type": "object",
                        "required": ["struct", "num", "strategy"],
                        "properties": {
                            "struct": {"type": "number"},
                            "num": {"type": "number"},
                            "strategy": {"type": "number"},
                        },
                    },
                },
            },
            "case_features": {"type": "object"},
            "distill_features": {"type": "object"},
        },
    }


def _is_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return True


def _resolve_ref(schema: Dict[str, Any], root: Dict[str, Any]) -> Dict[str, Any]:
    ref = str(schema.get("$ref") or "")
    if not ref.startswith("#/$defs/"):
        return {}
    key = ref.split("/")[-1]
    defs = root.get("$defs") or {}
    target = defs.get(key)
    return target if isinstance(target, dict) else {}


def _validate_schema_value(
    schema: Dict[str, Any],
    value: Any,
    path: str,
    root: Dict[str, Any],
    errors: List[str],
) -> None:
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        target = _resolve_ref(schema, root)
        if target:
            _validate_schema_value(target, value, path, root, errors)
        return

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        if not any(_is_type(value, t) for t in schema_type):
            errors.append(f"{path}: expected type in {schema_type}, got {type(value).__name__}")
            return
    elif isinstance(schema_type, str):
        if not _is_type(value, schema_type):
            errors.append(f"{path}: expected type {schema_type}, got {type(value).__name__}")
            return

    if "enum" in schema and value not in (schema.get("enum") or []):
        errors.append(f"{path}: value {value!r} not in enum")
    if "const" in schema and value != schema.get("const"):
        errors.append(f"{path}: value {value!r} != const {schema.get('const')!r}")

    if isinstance(value, str):
        min_len = schema.get("minLength")
        if isinstance(min_len, int) and len(value) < min_len:
            errors.append(f"{path}: string too short")

    if (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: value below minimum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: value above maximum")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: too few items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _validate_schema_value(item_schema, item, f"{path}[{i}]", root, errors)

    if isinstance(value, dict):
        props = schema.get("properties") or {}
        required = schema.get("required") or []
        for k in required:
            if k not in value:
                errors.append(f"{path}.{k}: missing required field")
        if schema.get("additionalProperties") is False and isinstance(props, dict):
            for k in value.keys():
                if k not in props:
                    errors.append(f"{path}.{k}: additional property not allowed")
        if isinstance(props, dict):
            for k, sub_schema in props.items():
                if k in value and isinstance(sub_schema, dict):
                    _validate_schema_value(sub_schema, value.get(k), f"{path}.{k}", root, errors)


def _collect_schema_errors(schema: Dict[str, Any], obj: Dict[str, Any], path: str) -> List[str]:
    errors: List[str] = []
    _validate_schema_value(schema, obj, path, schema, errors)
    return errors


def _collect_episode_ref_paths(case: Dict[str, Any]) -> List[str]:
    refs = (case.get("execution") or {}).get("episode_refs") or []
    out: List[str] = []
    for r in refs:
        p = str((r or {}).get("path") or "").strip()
        if p:
            out.append(p)
    return out


def _collect_case_coverage(cases: List[Dict[str, Any]], episodes_by_path: Dict[str, Dict[str, Any]]) -> Tuple[int, int, float]:
    """Compute episode coverage with partial credit.

    - Cases with no episode_refs are counted as covered (no expectation set).
    - Cases with refs get partial credit: resolved / total refs.
    - A case is fully covered when >= 50% of its refs resolve.
    """
    covered = 0
    total_weight = 0.0
    covered_weight = 0.0
    for c in cases:
        paths = _collect_episode_ref_paths(c)
        if not paths:
            # No refs declared yet — no penalty, count as covered.
            covered += 1
            total_weight += 1.0
            covered_weight += 1.0
            continue
        resolved = sum(1 for p in paths if p in episodes_by_path)
        ratio = float(resolved) / float(max(len(paths), 1))
        total_weight += 1.0
        covered_weight += ratio
        if ratio >= 0.5:
            covered += 1
    return covered, int(total_weight), round(covered_weight, 4)


def check_consistency_report(
    index_data: Optional[Dict[str, Any]],
    index_path: Path,
    cases: Optional[List[Dict[str, Any]]],
    distills: Optional[List[Dict[str, Any]]],
    stats: Optional[Dict[str, Any]],
    episodes_by_path: Optional[Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    resolved_episodes = episodes_by_path or {}
    case_list = _load_cases(cases)
    distill_list = _load_distills(distills)
    stats_data = _load_stats(stats)
    idx = _load_index_data(index_data, index_path)

    issues: List[Dict[str, str]] = []
    schema_issues = 0

    case_schema_path = _memory_l4_schema_dir() / "trade_case.schema.json"
    distill_schema_path = _memory_l4_schema_dir() / "distill.schema.json"
    stats_schema_path = _memory_l4_schema_dir() / "stats.schema.json"
    case_schema = _load_json(case_schema_path) if case_schema_path.exists() else {}
    distill_schema = _load_json(distill_schema_path) if distill_schema_path.exists() else {}
    stats_schema = _load_json(stats_schema_path) if stats_schema_path.exists() else {}

    case_ids: Set[str] = set()
    episode_ref_count = 0
    resolved_ref_count = 0
    for c in case_list:
        cid = str(c.get("case_id") or "").strip()
        if not cid:
            issues.append(_to_issue("CASE_MISSING_ID", "", "case_id is required"))
            continue
        if case_schema:
            errs = _collect_schema_errors(case_schema, c, "case")
            if errs:
                schema_issues += 1
                issues.append(_to_issue("CASE_SCHEMA_INVALID", cid, "; ".join(errs[:3])))
        case_ids.add(cid)
        for p in _collect_episode_ref_paths(c):
            episode_ref_count += 1
            if p in resolved_episodes:
                resolved_ref_count += 1
            else:
                issues.append(_to_issue("MISSING_EPISODE_REF", cid, p))

    for d in distill_list:
        did = str(d.get("distill_id") or "").strip()
        if not did:
            issues.append(_to_issue("DISTILL_MISSING_ID", "", "distill_id is required"))
            continue
        if distill_schema:
            errs = _collect_schema_errors(distill_schema, d, "distill")
            if errs:
                schema_issues += 1
                issues.append(_to_issue("DISTILL_SCHEMA_INVALID", did, "; ".join(errs[:3])))
        for cid in (d.get("supporting_case_ids") or []):
            case_id = str(cid or "").strip()
            if case_id and case_id not in case_ids:
                issues.append(_to_issue("DISTILL_SUPPORTING_CASE_NOT_FOUND", did, case_id))

    if stats_schema:
        errs = _collect_schema_errors(stats_schema, stats_data, "stats")
        if errs:
            schema_issues += 1
            issues.append(_to_issue("STATS_SCHEMA_INVALID", "stats", "; ".join(errs[:3])))

    stats_points = stats_data.get("points") or []
    for p in stats_points:
        if str(p.get("kind") or "") != "case":
            continue
        cid = str(p.get("id") or "").strip()
        if cid and cid not in case_ids:
            issues.append(_to_issue("STATS_CASE_NOT_FOUND", cid, "case point not found in cases"))

    if isinstance(idx, dict):
        index_errs = _collect_schema_errors(_index_schema(), idx, "index")
        if index_errs:
            schema_issues += 1
            issues.append(_to_issue("INDEX_SCHEMA_INVALID", "index", "; ".join(index_errs[:3])))

    index_case_features = (idx.get("case_features") or {}) if isinstance(idx, dict) else {}
    for cid in case_ids:
        if cid not in index_case_features:
            issues.append(_to_issue("CASE_NOT_INDEXED", cid, "missing in index.case_features"))
    for cid in index_case_features.keys():
        key = str(cid)
        if key not in case_ids:
            issues.append(_to_issue("INDEX_CASE_NOT_FOUND", key, "index points to missing case"))

    coverage_result = _collect_case_coverage(case_list, resolved_episodes)
    covered_cases, total_cases, covered_weight = coverage_result
    coverage_ratio = covered_weight / float(total_cases) if total_cases > 0 else 1.0

    return {
        "summary": {
            "case_count": len(case_ids),
            "distill_count": len(distill_list),
            "episode_ref_count": episode_ref_count,
            "episode_ref_resolved_count": resolved_ref_count,
            "episode_coverage_ratio": round(coverage_ratio, 4),
            "schema_issues_total": schema_issues,
            "issues_total": len(issues),
        },
        "issues": issues,
    }
