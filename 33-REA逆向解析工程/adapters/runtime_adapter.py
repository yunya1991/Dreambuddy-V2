"""运行时观测适配：coverage.xml 与 OpenTelemetry JSON/JSONL。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.coverage_analyzer import analyze_coverage
from core.evidence import Evidence

_SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _relative_file(value: Any, root: Path) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute():
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
    while raw.startswith("./"):
        raw = raw[2:]
    return raw


def _node_candidates(node: str) -> set[str]:
    normalized = str(node).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if Path(normalized).suffix in _SOURCE_SUFFIXES:
        return {normalized}
    dotted = normalized.replace(".", "/")
    return {f"{dotted}.py", f"{dotted}/__init__.py"}


def _attribute(span: dict[str, Any], keys: tuple[str, ...]) -> Any:
    attributes = span.get("attributes") or {}
    if isinstance(attributes, dict):
        for key in keys:
            if key in attributes:
                return attributes[key]
    elif isinstance(attributes, list):
        for item in attributes:
            if not isinstance(item, dict) or item.get("key") not in keys:
                continue
            value = item.get("value")
            if isinstance(value, dict):
                for value_key in (
                    "stringValue",
                    "intValue",
                    "doubleValue",
                    "boolValue",
                ):
                    if value_key in value:
                        return value[value_key]
            return value
    return ""


def _status(span: dict[str, Any]) -> str:
    raw = span.get("status", 0)
    code = raw.get("code", 0) if isinstance(raw, dict) else raw
    normalized = str(code).upper()
    if code == 2 or normalized in {"2", "ERROR", "STATUS_CODE_ERROR"}:
        return "error"
    if code == 1 or normalized in {"1", "OK", "STATUS_CODE_OK"}:
        return "ok"
    return "unset"


def _normalize_span(span: dict[str, Any], root: Path) -> dict[str, Any]:
    return {
        "trace_id": str(span.get("traceId") or span.get("trace_id") or ""),
        "span_id": str(span.get("spanId") or span.get("span_id") or ""),
        "parent_span_id": str(span.get("parentSpanId") or span.get("parent_span_id") or ""),
        "name": str(span.get("name") or ""),
        "file": _relative_file(
            _attribute(span, ("code.file.path", "code.filepath", "code.file")),
            root,
        )
        or None,
        "function": str(_attribute(span, ("code.function.name", "code.function")) or "") or None,
        "status": _status(span),
        "start_time_unix_nano": str(
            span.get("startTimeUnixNano") or span.get("start_time_unix_nano") or ""
        ),
        "end_time_unix_nano": str(
            span.get("endTimeUnixNano") or span.get("end_time_unix_nano") or ""
        ),
    }


def _extract_spans(payload: Any) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        for key in ("resourceSpans", "resource_spans", "scopeSpans", "scope_spans", "spans"):
            if key in value:
                walk(value[key])
                return
        if "span" in value:
            walk(value["span"])
            return
        if "name" in value and ("spanId" in value or "span_id" in value or "attributes" in value):
            spans.append(value)

    walk(payload)
    return spans


def _load_otel(path: Path, root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"OTel 报告不可读: {path}: {exc}"]
    payloads: list[Any] = []
    errors: list[str] = []
    try:
        payloads = [json.loads(text)]
    except json.JSONDecodeError:
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError as exc:
                errors.append(f"OTel JSONL line {line_number}: {exc.msg}")
    spans = [
        _normalize_span(span, root) for payload in payloads for span in _extract_spans(payload)
    ]
    spans.sort(
        key=lambda span: (
            span["trace_id"],
            span["span_id"],
            span["name"],
            span["file"] or "",
            span["function"] or "",
        )
    )
    return spans, errors


def _append_gap(report: dict[str, Any], gap: str) -> None:
    if gap and gap not in report["known_gaps"]:
        report["known_gaps"].append(gap)


def scan_runtime(
    target: str,
    *,
    otel_path: str | None = None,
    static_nodes: list[str] | None = None,
) -> dict[str, Any]:
    """对账静态模块与真实覆盖/span；未观测不等于不存在。"""
    requested = Path(target).expanduser()
    root = requested if requested.is_dir() else requested.parent
    coverage_path = root / "coverage.xml"
    try:
        raw_coverage = analyze_coverage(str(root))
    except (OSError, ValueError) as exc:
        raw_coverage = {
            "files": [],
            "line_rate": 0.0,
            "branch_rate": 0.0,
            "summary": f"coverage.xml 解析失败: {exc}",
            "evidence": [
                Evidence(
                    result=f"coverage.xml 解析失败: {exc}",
                    provenance={"file": str(coverage_path), "engine": "coverage_xml"},
                    known_gaps=["覆盖率字段格式错误，未采用该报告的数值"],
                    level="unknown",
                )
            ],
        }
    coverage_available = coverage_path.is_file() and not any(
        item.level == "unknown" for item in raw_coverage["evidence"]
    )

    coverage_files: list[dict[str, Any]] = []
    zero_coverage: list[dict[str, Any]] = []
    for item in raw_coverage["files"]:
        lines = item.get("lines") or []
        total = len(lines)
        uncovered = sum(line.get("hits", 0) == 0 for line in lines)
        summary = {
            "module": _relative_file(item.get("filename"), root),
            "line_rate": item.get("line_rate", 0.0),
            "branch_rate": item.get("branch_rate", 0.0),
            "covered_lines": total - uncovered,
            "uncovered_lines": uncovered,
            "total_lines": total,
        }
        coverage_files.append(summary)
        if total and uncovered == total:
            zero_coverage.append(
                {
                    "module": summary["module"],
                    "line_rate": summary["line_rate"],
                    "uncovered_lines": uncovered,
                    "total_lines": total,
                }
            )
    coverage_files.sort(key=lambda item: item["module"])
    zero_coverage.sort(key=lambda item: item["module"])

    report: dict[str, Any] = {
        "section": "runtime",
        "target": str(root),
        "degraded": not coverage_available,
        "coverage": {
            "available": coverage_available,
            "line_rate": raw_coverage["line_rate"] if coverage_available else None,
            "branch_rate": raw_coverage["branch_rate"] if coverage_available else None,
            "summary": raw_coverage["summary"],
            "files": coverage_files,
        },
        "zero_coverage_modules": zero_coverage,
        "spans": [],
        "reconciled_nodes": [],
        "evidence": [item.to_dict() for item in raw_coverage["evidence"]],
        "known_gaps": [],
    }
    for evidence in report["evidence"]:
        for gap in evidence.get("known_gaps") or []:
            _append_gap(report, gap)

    otel_errors: list[str] = []
    if otel_path:
        report["spans"], otel_errors = _load_otel(Path(otel_path).expanduser(), root)
        report["degraded"] = report["degraded"] or bool(otel_errors)
        for gap in otel_errors:
            _append_gap(report, gap)
        otel_evidence = Evidence(
            result=(
                f"OpenTelemetry 输入不可用: {'; '.join(otel_errors)}"
                if otel_errors
                else f"OpenTelemetry 解析 {len(report['spans'])} 个 span"
            ),
            provenance={
                "analysis": "otel_spans",
                "file": str(otel_path),
                "format": "json_or_jsonl",
            },
            known_gaps=otel_errors
            or ["span 仅覆盖输入报告的时间窗与已埋点路径，未埋点不代表未执行"],
            level="unknown" if otel_errors and not report["spans"] else "observation",
        ).to_dict()
        report["evidence"].append(otel_evidence)
        for gap in otel_evidence["known_gaps"]:
            _append_gap(report, gap)

    coverage_by_file = {item["module"]: item for item in coverage_files}
    spans_by_file: dict[str, list[dict[str, Any]]] = {}
    for span in report["spans"]:
        if span["file"]:
            spans_by_file.setdefault(span["file"], []).append(span)

    for node in sorted(set(static_nodes or [])):
        candidates = _node_candidates(node)
        coverage_matches = [item for path, item in coverage_by_file.items() if path in candidates]
        span_matches = [
            span for path, spans in spans_by_file.items() if path in candidates for span in spans
        ]
        observed = any(item["covered_lines"] > 0 for item in coverage_matches) or bool(span_matches)
        if observed:
            status = "confirmed"
        elif coverage_matches:
            status = "contradicted"
        else:
            status = "unobserved"
        sources = []
        if coverage_matches:
            sources.append("coverage")
        if span_matches:
            sources.append("otel")
        report["reconciled_nodes"].append(
            {
                "node": node,
                "status": status,
                "observed": observed,
                "sources": sources,
                "files": sorted(
                    {item["module"] for item in coverage_matches}
                    | {span["file"] for span in span_matches}
                ),
                "span_count": len(span_matches),
                "error_span_count": sum(span["status"] == "error" for span in span_matches),
            }
        )

    if coverage_available or otel_path:
        reconciliation_gap = (
            "contradicted 仅表示静态节点在 coverage.xml 中所有行 hits=0；"
            "这说明本次测试未执行，不证明生产环境不可达"
        )
        _append_gap(report, reconciliation_gap)
        _append_gap(report, "无覆盖且无 span 的静态节点标为 unobserved，不推断其不存在")
        report["evidence"].append(
            Evidence(
                result=(
                    "运行时对账: "
                    f"{sum(n['status'] == 'confirmed' for n in report['reconciled_nodes'])} confirmed, "
                    f"{sum(n['status'] == 'contradicted' for n in report['reconciled_nodes'])} contradicted, "
                    f"{sum(n['status'] == 'unobserved' for n in report['reconciled_nodes'])} unobserved"
                ),
                provenance={
                    "analysis": "runtime_reconciliation",
                    "coverage_available": coverage_available,
                    "otel_spans": len(report["spans"]),
                },
                known_gaps=[reconciliation_gap],
                level="derivation",
            ).to_dict()
        )
    return report
