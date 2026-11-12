"""假设契约与 PoE 门禁（SPEC-33-E §2.2 / §2.3）。

设计边界（硬约束）：
  - 本模块**不调用任何大模型**，只做契约校验、静态复核与门禁判定。
  - 假设由宿主模型产出，进入本模块后按 falsifier / target_refs / PoE 打分定级。
  - 门禁复用 core.ai_audit 的公式与阈值，不新增权重。

等级规则（§2.7）：
  - refs 全部命中且 gate=pass → derivation（可写 B）
  - 部分命中或 gate=review     → inference（可写 C）
  - 无命中 / 缺 falsifier      → unknown（不写）
"""

from __future__ import annotations

from typing import Any, Iterable

from .ai_audit import _gate_decision, compute_poe_score

REQUIRED_FIELDS = ("hypothesis_id", "claim", "target_refs", "falsifier")
VALID_LEVELS = ("observation", "derivation", "inference", "unknown")
_SOURCE_EXTS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")


def _strip_ext(path: str) -> str:
    """去掉源码扩展名：Python 图节点是模块名（server），假设引用常带 .py。"""
    for ext in _SOURCE_EXTS:
        if path.endswith(ext):
            return path[: -len(ext)]
    return path


def validate_hypothesis(hypothesis: dict[str, Any]) -> list[str]:
    """校验假设契约，返回错误列表（空列表即合法）。"""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        value = hypothesis.get(field)
        if value is None or (isinstance(value, (str, list)) and not value):
            errors.append(f"缺少必填字段 {field}")
    refs = hypothesis.get("target_refs")
    if refs is not None and not isinstance(refs, list):
        errors.append("target_refs 必须为数组")
    falsifier = hypothesis.get("falsifier")
    if isinstance(falsifier, str) and len(falsifier.strip()) < 8:
        errors.append("falsifier 过于笼统（<8 字符），无法证伪")
    return errors


def _normalize_ref(raw: Any) -> str:
    return str(raw).strip().replace("\\", "/").lstrip("./")


def _semantic_ref_hits(
    raw: Any,
    graph_nodes: list[str],
    semantic_locations: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """把外部语言服务返回的文件位置映射回既有静态图节点。"""
    locations = (
        semantic_locations.get(str(raw)) or semantic_locations.get(_normalize_ref(raw)) or []
    )
    hits: list[dict[str, Any]] = []
    for location in locations:
        if not isinstance(location, dict) or not location.get("file"):
            continue
        file_path = _normalize_ref(location["file"])
        file_stem = _strip_ext(file_path)
        dotted = file_stem.replace("/", ".")
        matched = sorted(
            {
                str(node)
                for node in graph_nodes
                if (
                    lambda n: (
                        n == file_path
                        or n.endswith("/" + file_path)
                        or _strip_ext(n) == file_stem
                        or _strip_ext(n).endswith("/" + file_stem)
                        or _strip_ext(n).replace("/", ".") == dotted
                        or _strip_ext(n).replace("/", ".").endswith("." + dotted)
                    )
                )(str(node).replace("\\", "/"))
            }
        )
        for node in matched:
            hits.append({**location, "node": node})
    return hits


def resolve_target_refs_detailed(
    refs: Iterable[Any],
    graph_nodes: Iterable[str],
    *,
    semantic_locations: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """把 target_refs 对齐到静态图节点，并区分精确命中与目录级命中。

    Returns:
        {"resolved": [ref...], "directory_hits": {ref: [node...]}, "unresolved": [ref...]}
    """
    nodes = list(graph_nodes)
    stems = {_strip_ext(n) for n in nodes}
    resolved: list[str] = []
    directory_hits: dict[str, list[str]] = {}
    lsp_hits: dict[str, list[dict[str, Any]]] = {}
    unresolved: list[str] = []
    for raw in refs:
        ref = _normalize_ref(raw)
        if not ref:
            continue
        if ref in nodes:
            resolved.append(ref)
            continue
        if any(n.endswith("/" + ref) or n.endswith("." + ref) for n in nodes):
            resolved.append(ref)
            continue
        # 扩展名归一：ref=server.py → 命中 Python 模块节点 server
        stem = _strip_ext(ref)
        hit = False
        if "/" in stem:
            tail = stem.rsplit("/", 1)[-1]
            hit = tail in nodes or any(s.endswith("/" + stem) for s in stems)
        elif stem in nodes:
            hit = True
        if hit:
            resolved.append(ref)
            continue
        # SPEC-F P-F03：目录前缀展开（ref 是某节点路径前缀 → 该目录下所有节点命中）
        prefix = ref.rstrip("/")
        expanded = sorted(n for n in nodes if n.startswith(prefix + "/"))
        if expanded:
            resolved.append(ref)
            directory_hits[ref] = expanded
            continue
        semantic_hits = _semantic_ref_hits(raw, nodes, semantic_locations or {})
        if semantic_hits:
            resolved.append(ref)
            lsp_hits[ref] = semantic_hits
            continue
        unresolved.append(ref)
    result = {"resolved": resolved, "directory_hits": directory_hits, "unresolved": unresolved}
    if semantic_locations is not None:
        result["lsp_hits"] = lsp_hits
    return result


def resolve_target_refs(refs: Iterable[Any], graph_nodes: Iterable[str]) -> list[str]:
    """把 target_refs 对齐到静态图节点（支持完整路径/路径后缀/点分模块名/目录前缀）。"""
    return resolve_target_refs_detailed(refs, graph_nodes)["resolved"]


def audit_hypothesis(
    hypothesis: dict[str, Any],
    graph_nodes: Iterable[str],
    *,
    semantic_locations: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """单条假设的门禁判定：契约 → 静态/可选符号复核 → PoE 打分 → gate。"""
    errors = validate_hypothesis(hypothesis)
    if errors:
        return {
            "hypothesis_id": hypothesis.get("hypothesis_id") or "H-unknown",
            "gate": "reject",
            "poe_score": 0.0,
            "evidence_chain_score": 0.0,
            "resolved_refs": [],
            "unresolved_refs": list(hypothesis.get("target_refs") or []),
            "level": "unknown",
            "reasons": errors,
        }

    refs = list(hypothesis.get("target_refs") or [])
    detail = resolve_target_refs_detailed(refs, graph_nodes, semantic_locations=semantic_locations)
    resolved = detail["resolved"]
    directory_hits = detail["directory_hits"]
    lsp_hits = detail.get("lsp_hits") or {}
    unresolved = detail["unresolved"]
    ratio = len(resolved) / len(refs) if refs else 0.0

    # 证据链 = 引用命中率；覆盖 = 全命中 1.0，否则按命中率打折；复杂度 = 改动面
    evidence_chain = round(ratio, 3)
    coverage = 1.0 if ratio >= 1.0 else round(0.6 * ratio, 3)
    cost = hypothesis.get("cost") or {}
    touched = int(cost.get("files_touched") or len(refs) or 1)
    complexity = min(1.0, touched / 20.0)

    poe_score = compute_poe_score(
        evidence_chain_score=evidence_chain,
        coverage_score=coverage,
        complexity_penalty=complexity,
    )
    gate = _gate_decision(poe_score, evidence_chain)

    reasons: list[str] = [
        f"target_refs 命中 {len(resolved)}/{len(refs)}",
        f"poe_score={poe_score:.3f}, evidence_chain={evidence_chain:.3f}",
    ]
    if ratio <= 0.0:
        # §2.3：无任何静态复核证据 → 最高 review，禁止 pass
        gate = "review"
        reasons.append("无静态复核证据（target_refs 全部未命中图节点），封顶 review")
    if directory_hits:
        # SPEC-F P-F03：目录不构成精确定位 → 最高 review
        if gate == "pass":
            gate = "review"
        expanded_total = sum(len(v) for v in directory_hits.values())
        reasons.append(
            f"目录级引用未精确定位: {', '.join(sorted(directory_hits))}"
            f"（展开 {expanded_total} 个节点），封顶 review"
        )
    if lsp_hits:
        reasons.append(f"语言服务符号命中: {', '.join(sorted(lsp_hits))}")
    if unresolved:
        reasons.append(f"未定位引用: {', '.join(unresolved[:5])}")

    if gate == "pass" and ratio >= 1.0:
        level = "derivation"
    elif gate in ("pass", "review") and ratio > 0.0:
        level = "inference"
    else:
        level = "unknown"

    result = {
        "hypothesis_id": hypothesis["hypothesis_id"],
        "claim": hypothesis.get("claim"),
        "gate": gate,
        "poe_score": round(poe_score, 3),
        "evidence_chain_score": evidence_chain,
        "resolved_refs": resolved,
        "unresolved_refs": unresolved,
        "level": level,
        "reasons": reasons,
    }
    if semantic_locations is not None:
        result["lsp_hits"] = lsp_hits
    return result


def audit_hypotheses(
    hypotheses: list[dict[str, Any]],
    graph_nodes: Iterable[str],
    *,
    semantic_locations: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """批量门禁；空输入返回空列表（由调用方补 known_gaps）。"""
    nodes = list(graph_nodes)
    return [
        audit_hypothesis(h, nodes, semantic_locations=semantic_locations)
        for h in hypotheses
        if isinstance(h, dict)
    ]


def build_write_hint(results: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """按 §2.7 生成认知写入建议（只给建议，不写库）。"""
    write: list[dict[str, Any]] = []
    skip: list[dict[str, Any]] = []
    for item in results:
        gate = item.get("gate")
        level = item.get("level")
        if gate == "reject" or level == "unknown":
            skip.append(
                {
                    "hypothesis_id": item.get("hypothesis_id"),
                    "reason": "gate=reject 或无静态复核证据，按 §2.7 禁止写入",
                }
            )
            continue
        quality = "B" if gate == "pass" else "C"
        write.append(
            {
                "hypothesis_id": item.get("hypothesis_id"),
                "quality_level": quality,
                "content": f"[REA审核][{target}] {item.get('claim')}",
                "basis": item.get("reasons"),
            }
        )
    return {"write": write, "skip": skip}
