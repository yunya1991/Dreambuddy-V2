"""Mermaid 架构图与一页 wiki（SPEC-33-F T-F18）。

设计边界：
  - 内核零 LLM：只把快照既有结构确定性渲染成 Mermaid / Markdown。
  - 读者向内容由宿主 LLM 基于本模块输出与 Evidence 组织，本模块不写结论。
  - 节点/边/目录均排序后输出，同输入逐字节一致。
"""

from __future__ import annotations

from typing import Any

DEFAULT_MAX_NODES = 40
DEFAULT_MAX_EDGES = 80
DEFAULT_MAX_BYTES = 8_192
_MODULE_MERMAID = "flowchart LR"


def _nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("raw") or {}
    graph = raw.get("graph") or {}
    items = raw.get("modules") or graph.get("nodes") or []
    nodes = []
    for item in items:
        nodes.append(dict(item) if isinstance(item, dict) else {"name": str(item)})
    return nodes


def _edges(payload: dict[str, Any]) -> list[tuple[str, str]]:
    raw = payload.get("raw") or {}
    graph = raw.get("graph") or {}
    pairs: set[tuple[str, str]] = set()
    deps = raw.get("dependencies")
    if isinstance(deps, dict):
        for source, targets in deps.items():
            for target in targets or []:
                pairs.add((str(source), str(target)))
    adjacency = graph.get("adjacency")
    if isinstance(adjacency, dict):
        for source, targets in adjacency.items():
            for target in targets or []:
                pairs.add((str(source), str(target)))
    return sorted(pairs)


def _safe_id(name: str, used: dict[str, int]) -> str:
    base = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_") or "n"
    if not base[0].isalpha():
        base = f"n_{base}"
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}_{count}"


def _label(name: str, limit: int = 48) -> str:
    text = name.replace('"', "'").replace("\n", " ")
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def build_mermaid(
    payload: dict[str, Any],
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> dict[str, Any]:
    """把模块/依赖渲染成 Mermaid flowchart（按顶层目录分组）。"""
    nodes = _nodes(payload)
    edges = _edges(payload)
    known_gaps: list[str] = []
    if len(nodes) > max_nodes:
        known_gaps.append(f"节点超限，仅渲染前 {max_nodes}/{len(nodes)} 个")
        nodes = nodes[:max_nodes]

    names = [str(item.get("name") or item.get("path") or "") for item in nodes]
    selected = {name for name in names if name}
    used: dict[str, int] = {}
    ids = {name: _safe_id(name, used) for name in names if name}

    clusters: dict[str, list[str]] = {}
    for name in names:
        if not name:
            continue
        top = name.split("/", 1)[0] if "/" in name else "root"
        clusters.setdefault(top, []).append(name)

    lines = [_MODULE_MERMAID]
    cluster_ids: dict[str, int] = {}
    for cluster in sorted(clusters):
        lines.append(f"  subgraph {_safe_id('g_' + cluster, cluster_ids)}[{_label(cluster)}]")
        for name in sorted(clusters[cluster]):
            lines.append(f'    {ids[name]}["{_label(name)}"]')
        lines.append("  end")
    for item in nodes:
        if not item.get("name") and item.get("path"):
            name = str(item["path"])
            ids.setdefault(name, _safe_id(name, used))
            lines.append(f'  {ids[name]}["{_label(name)}"]')

    rendered_edges = [
        (source, target) for source, target in edges if source in selected and target in selected
    ]
    if len(rendered_edges) > max_edges:
        known_gaps.append(f"边超限，仅渲染前 {max_edges}/{len(rendered_edges)} 条")
        rendered_edges = rendered_edges[:max_edges]
    for source, target in rendered_edges:
        lines.append(f"  {ids[source]} --> {ids[target]}")

    return {
        "mermaid": "\n".join(lines) + "\n",
        "stats": {
            "nodes": len(ids),
            "edges": len(rendered_edges),
            "clusters": len(clusters),
            "source_nodes": len(_nodes(payload)),
            "source_edges": len(edges),
        },
        "known_gaps": known_gaps,
    }


def _degree(edges: list[tuple[str, str]]) -> dict[str, int]:
    degree: dict[str, int] = {}
    for _, target in edges:
        degree[target] = degree.get(target, 0) + 1
    return degree


def _truncate_lines(text: str, max_bytes: int) -> tuple[str, bool]:
    if len(text.encode("utf-8")) <= max_bytes:
        return text, False
    out: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        chunk = len(line.encode("utf-8"))
        if size + chunk > max_bytes:
            break
        out.append(line)
        size += chunk
    return "".join(out), True


def build_wiki(
    payload: dict[str, Any],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """渲染一页 Markdown wiki（确定性、只陈述结构事实）。"""
    raw = payload.get("raw") or {}
    target = str(payload.get("target") or "unknown")
    nodes = _nodes(payload)
    edges = _edges(payload)
    degree = _degree(edges)
    hubs = sorted(degree.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    cycles = raw.get("cycles") or (raw.get("graph") or {}).get("cycles") or []
    evidence = payload.get("evidence") or []
    known_gaps = [str(gap) for gap in (payload.get("known_gaps") or [])]

    lines = [
        f"# {target} 架构一页纸",
        "",
        "## 概览",
        "",
        f"- 模块：{len(nodes)}",
        f"- 依赖边：{len(edges)}",
        f"- 依赖环：{len(cycles)}",
        f"- Evidence：{len(evidence)}",
        "",
        "## 关键枢纽（被依赖 Top5）",
        "",
    ]
    if hubs:
        lines.extend(f"- `{name}` ← {count}" for name, count in hubs)
    else:
        lines.append("- （无入边数据）")
    lines.extend(
        [
            "",
            "## 层级分布",
            "",
        ]
    )
    distribution: dict[str, int] = {}
    for item in nodes:
        name = str(item.get("name") or item.get("path") or "")
        top = name.split("/", 1)[0] if "/" in name else "root"
        distribution[top] = distribution.get(top, 0) + 1
    for top in sorted(distribution):
        lines.append(f"- `{top}`：{distribution[top]} 个模块")
    lines.extend(["", "## Evidence 摘要", ""])
    if evidence:
        for item in evidence[:10]:
            provenance = (item or {}).get("provenance") or {}
            lines.append(
                f"- [{item.get('level', 'observation')}] {item.get('result', '')}"
                f" (confidence={item.get('confidence', '-')}, target={provenance.get('target', '-')})"
            )
    else:
        lines.append("- （快照无 Evidence）")
    lines.extend(["", "## 已知局限", ""])
    if known_gaps:
        lines.extend(f"- {gap}" for gap in known_gaps)
    else:
        lines.append("- （无）")
    lines.append("")

    markdown, truncated = _truncate_lines("\n".join(lines), max_bytes)
    gaps = list(known_gaps)
    if truncated:
        gaps.append(f"wiki 超出字节预算 {max_bytes}，已按行截断")
    return {
        "markdown": markdown,
        "stats": {
            "bytes": len(markdown.encode("utf-8")),
            "nodes": len(nodes),
            "edges": len(edges),
            "hubs": len(hubs),
            "evidence": len(evidence),
            "truncated": truncated,
        },
        "known_gaps": gaps,
    }


def build_diagram(payload: dict[str, Any], *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """同时产出 Mermaid 图与一页 wiki。"""
    mermaid = build_mermaid(payload)
    wiki = build_wiki(payload, max_bytes=max_bytes)
    return {
        "mermaid": mermaid["mermaid"],
        "wiki": wiki["markdown"],
        "stats": {"mermaid": mermaid["stats"], "wiki": wiki["stats"]},
        "known_gaps": list(mermaid["known_gaps"]) + list(wiki["known_gaps"]),
    }
