"""SARIF 2.1.0 输出适配层（SPEC-33-F §2.8 / T-F10）。

只归一 REA 已有的 cognitive_debt、规则违例与 known_gaps，不调用外部工具。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
DEFAULT_SARIF_DIR = Path(__file__).resolve().parents[1] / "reflection_data" / "sarif"

_GATE_LEVELS = {"pass": "note", "review": "warning", "reject": "error"}
_SEVERITY_LEVELS = {
    "error": "error",
    "fatal": "error",
    "warning": "warning",
    "warn": "warning",
    "notify": "note",
    "note": "note",
    "none": "note",
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, dict):
            return converted
    return {}


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _relative_uri(path: Any, target: str) -> str:
    text = str(path or "").strip()
    if not text:
        return "."
    source = Path(text).expanduser()
    if source.is_absolute() and target:
        root = Path(target).expanduser()
        if root.is_file():
            root = root.parent
        try:
            return source.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return Path(os.path.relpath(source, root)).as_posix()
    normalized = text.replace(os.sep, "/")
    return normalized[2:] if normalized.startswith("./") else normalized


def _location(path: Any, line: Any, column: Any, target: str) -> dict[str, Any]:
    physical: dict[str, Any] = {"artifactLocation": {"uri": _relative_uri(path, target)}}
    start_line = _positive_int(line)
    if start_line is not None:
        region: dict[str, int] = {"startLine": start_line}
        start_column = _positive_int(column)
        if start_column is not None:
            region["startColumn"] = start_column
        physical["region"] = region
    return {"physicalLocation": physical}


def _level(value: Any, default: str) -> str:
    normalized = str(value or "").strip().lower()
    return _GATE_LEVELS.get(normalized) or _SEVERITY_LEVELS.get(normalized) or default


def _result(
    rule_id: Any,
    message: Any,
    level: str,
    path: Any,
    line: Any,
    column: Any,
    target: str,
) -> dict[str, Any]:
    rule = str(rule_id or "rea-finding")
    return {
        "ruleId": rule,
        "level": level,
        "message": {"text": str(message or rule)},
        "locations": [_location(path, line, column, target)],
    }


def _result_sort_key(result: dict[str, Any]) -> tuple[Any, ...]:
    physical = result["locations"][0]["physicalLocation"]
    region = physical.get("region") or {}
    return (
        result["ruleId"],
        physical["artifactLocation"]["uri"],
        region.get("startLine", 0),
        region.get("startColumn", 0),
        result["message"]["text"],
    )


def build_sarif(payload: dict[str, Any], *, target: str | None = None) -> dict[str, Any]:
    """把 REA 审计/分析 payload 转为可 JSON 序列化的 SARIF 2.1.0。"""
    root = str(target or payload.get("target") or "")
    results: list[dict[str, Any]] = []

    for raw_debt in payload.get("cognitive_debt") or []:
        debt = _as_dict(raw_debt)
        evidence = _as_dict(debt.get("evidence"))
        provenance = _as_dict(evidence.get("provenance"))
        rule_id = debt.get("id") or debt.get("type") or "cognitive-debt"
        gate = (
            debt.get("gate_decision")
            or provenance.get("gate_decision")
            or payload.get("gate_decision")
            or "review"
        )
        results.append(
            _result(
                rule_id,
                debt.get("description") or evidence.get("result"),
                _level(gate, "warning"),
                provenance.get("file"),
                provenance.get("line"),
                provenance.get("column"),
                root,
            )
        )

    for finding in payload.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        results.append(
            _result(
                finding.get("rule") or finding.get("rule_id"),
                finding.get("message"),
                _level(finding.get("gate_decision") or finding.get("severity"), "note"),
                finding.get("file"),
                finding.get("line"),
                finding.get("column"),
                root,
            )
        )

    for raw_evidence in payload.get("evidence") or []:
        evidence = _as_dict(raw_evidence)
        provenance = _as_dict(evidence.get("provenance"))
        if provenance.get("analysis") not in {"rules_scan", "rules_engine"}:
            continue
        results.append(
            _result(
                provenance.get("rule") or provenance.get("rule_id"),
                evidence.get("result"),
                _level(
                    provenance.get("gate_decision") or provenance.get("severity"),
                    "note",
                ),
                provenance.get("file"),
                provenance.get("line"),
                provenance.get("column"),
                root,
            )
        )

    seen_gaps: set[str] = set()
    for raw_gap in payload.get("known_gaps") or []:
        gap = str(raw_gap)
        if gap in seen_gaps:
            continue
        seen_gaps.add(gap)
        results.append(_result("known-gap", gap, "note", ".", None, None, root))

    results.sort(key=_result_sort_key)
    rule_ids = sorted({result["ruleId"] for result in results})
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "33-REA",
                        "rules": [{"id": rule_id} for rule_id in rule_ids],
                    }
                },
                "results": results,
            }
        ],
    }


def write_sarif(
    snapshot_id: str,
    payload: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
    target: str | None = None,
) -> Path:
    """将快照对应的 SARIF 落盘，返回 artifact 路径。"""
    directory = Path(output_dir) if output_dir is not None else DEFAULT_SARIF_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot_id}.sarif"
    report = build_sarif(payload, target=target)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
