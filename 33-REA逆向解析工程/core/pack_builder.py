"""SPEC-33-F T-F12：从 analyze 快照生成确定性 Markdown 语料包。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_HEADER = "# REA Pack\n\n"


def _modules(raw: dict[str, Any]) -> list[str]:
    graph = raw.get("graph") or {}
    values = raw.get("modules") or graph.get("nodes") or []
    return sorted({str(value) for value in values if str(value).strip()})


def _source_path(payload: dict[str, Any], module: str) -> Path | None:
    target = Path(str(payload.get("target") or ""))
    if target.is_file():
        return target
    if not target.is_dir():
        return None
    relative = module.replace(".", "/") + ".py" if payload.get("language") == "python" else module
    candidate = (target / relative).resolve()
    try:
        candidate.relative_to(target.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _python_symbols(path: Path) -> list[dict[str, Any]]:
    from .python_analyzer import PythonAnalyzer

    analyzed = PythonAnalyzer().analyze(str(path))
    raw = analyzed.raw or {}
    symbols: list[dict[str, Any]] = []
    for item in raw.get("classes") or []:
        symbols.append({**item, "kind": "class"})
        for method in item.get("methods") or []:
            symbols.append(
                {
                    **method,
                    "name": f"{item.get('name')}.{method.get('name')}",
                    "kind": "method",
                }
            )
    symbols.extend({**item, "kind": "function"} for item in raw.get("functions") or [])
    return symbols


def _symbols(payload: dict[str, Any], module: str) -> list[dict[str, Any]]:
    raw = payload.get("raw") or {}
    file_symbols = raw.get("file_symbols") or {}
    symbols = [dict(item) for item in file_symbols.get(module) or []]
    symbols.extend(
        {**item, "kind": item.get("kind") or "component"}
        for item in raw.get("components") or []
        if item.get("file") == module
    )
    symbols.extend(
        {**item, "kind": "store"} for item in raw.get("stores") or [] if item.get("file") == module
    )
    if payload.get("language") == "python":
        path = _source_path(payload, module)
        if path is not None:
            symbols.extend(_python_symbols(path))
    return sorted(
        symbols,
        key=lambda item: (
            str(item.get("name") or item.get("symbol") or ""),
            str(item.get("kind") or "symbol"),
            int(item.get("line") or 0),
        ),
    )


def _format_symbol(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item.get("symbol") or "unnamed")
    kind = str(item.get("kind") or "symbol")
    line = int(item.get("line") or 0)
    suffix = f", line {line}" if line else ""
    return f"- `{name}` ({kind}{suffix})\n"


def _file_block(payload: dict[str, Any], module: str) -> str:
    raw = payload.get("raw") or {}
    graph = raw.get("graph") or {}
    adjacency = raw.get("dependencies")
    if not isinstance(adjacency, dict):
        adjacency = graph.get("adjacency") or {}
    dependencies = sorted({str(item) for item in adjacency.get(module) or []})

    lines = [f"## File: `{module}`\n\n", "### Symbols\n"]
    symbols = _symbols(payload, module)
    lines.extend(_format_symbol(item) for item in symbols)
    if not symbols:
        lines.append("- (none observed)\n")
    lines.append("\n### Dependencies\n")
    lines.extend(f"- `{item}`\n" for item in dependencies)
    if not dependencies:
        lines.append("- (none observed)\n")
    lines.append("\n")
    return "".join(lines)


def _utf8_prefix(text: str, budget: int) -> str:
    encoded = text.encode("utf-8")[:budget]
    return encoded.decode("utf-8", errors="ignore")


def build_pack(
    payload: dict[str, Any], *, budget_bytes: int = 32_768, cursor: int = 0
) -> dict[str, Any]:
    """按文件→符号→依赖拼接；仅保留预算内完整文件块。"""
    budget = max(0, int(budget_bytes))
    offset = max(0, int(cursor))
    modules = _modules(payload.get("raw") or {})
    total = len(modules)
    content = _HEADER
    included = 0
    for module in modules[offset:]:
        candidate = content + _file_block(payload, module)
        if len(candidate.encode("utf-8")) > budget:
            break
        content = candidate
        included += 1
    if len(content.encode("utf-8")) > budget:
        content = _utf8_prefix(content, budget)

    kept_through = min(offset + included, total)
    result: dict[str, Any] = {
        "section": "pack",
        "content": content,
        "content_bytes": len(content.encode("utf-8")),
        "budget_bytes": budget,
        "cursor": offset,
        "files_total": total,
        "files_included": included,
        "next_cursor": kept_through if included and kept_through < total else None,
    }
    if kept_through < total:
        result["trimmed"] = {"files": {"kept": kept_through, "total": total}}
    return result
