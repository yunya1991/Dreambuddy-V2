# -*- coding: utf-8 -*-
"""D-E18 资金流向导图（SPEC-54-L1交易层 §4.5，P0-5）。

定位：把**已入库的**资金流事实（`etf_flow` / `derivatives_spot` 净流入代理 /
`funding_rate`）投影成 T3 `graph`，只做投影与排序，不读库、不做统计推断。

硬边界：
  - 边字段严格 5 键 `{src,dst,kind,weight,p_adj}`（B-LT2）；`kind="flow"`；
  - `weight = min(1, |flow_z| / 3)`、`p_adj = null`（flow 不做显著性检验，不伪造 p 值）；
  - 流水明细旁挂 `dataset.meta.flows[]`，以 `edge_index` 关联；
  - `direction` 语义固定**相对 src**：`net_out_of_src` / `net_into_src`；
  - **无流数据不伪造边**（LT-G7）：降级 `corr`-only 导图 + `meta.reason="flow_unavailable"`，
    连 `corr` 也没有则 `ok=false / status=empty`；
  - `flow` 边按 `|flow_z|` 降序取 TopK，`p_adj` 恒 `null`。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..technical import CAVEAT
from .envelope import STATUS_GOOD, STATUS_PARTIAL, build, quality, quality_for, unavailable
from .overview import (
    MAX_EDGES,
    MAX_NODES,
    validate_graph_dataset,
)
from .overview import (
    build_graph as build_corr_graph,
)

CAPABILITY = "D-E18"
INTENT_FLOW = "data_insight"
SPEC_VERSION = "1.0"

DIRECTIONS: Tuple[str, ...] = ("net_out_of_src", "net_into_src")
DEFAULT_DIRECTION = "net_out_of_src"
FLOW_WEIGHT_SCALE = 3.0
DEFAULT_TOPK = 20
DEFAULT_WINDOW = 5

EDGE_KEYS = ("src", "dst", "kind", "weight", "p_adj")


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _node_id(raw: Any) -> str:
    return str(raw or "").strip()


def _derive_nodes(edges: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """由边端点派生节点（端点必须存在，否则校验器抛错）。"""
    nodes: List[Dict[str, str]] = []
    seen = set()
    for edge in edges:
        for key in ("src", "dst"):
            node_id = str(edge[key])
            if node_id in seen:
                continue
            seen.add(node_id)
            label = node_id.split(":", 1)[-1]
            nodes.append(
                {
                    "id": node_id,
                    "label": label,
                    "group": "class" if node_id.startswith("class:") else "asset",
                }
            )
    return nodes


def flow_edges(
    flows: Sequence[Mapping[str, Any]],
    *,
    topk: int = DEFAULT_TOPK,
    window: int = DEFAULT_WINDOW,
) -> Dict[str, Any]:
    """把资金流事实转成 `flow` 边 + `meta.flows[]`（不伪造、不改校验器口径）。"""
    candidates: List[Dict[str, Any]] = []
    flags: List[str] = []
    skipped = 0
    for row in flows or ():
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        src = _node_id(row.get("src"))
        dst = _node_id(row.get("dst"))
        flow_z = _finite(row.get("flow_z"))
        if not src or not dst or src == dst or flow_z is None:
            skipped += 1
            continue
        direction = str(row.get("direction") or DEFAULT_DIRECTION)
        if direction not in DIRECTIONS:
            direction = DEFAULT_DIRECTION
            flags.append(f"direction_defaulted:{src}->{dst}")
        candidates.append(
            {
                "src": src,
                "dst": dst,
                "flow_z": flow_z,
                "flow_usdt": _finite(row.get("flow_usdt")) or 0.0,
                "window": int(row.get("window") or window),
                "direction": direction,
            }
        )
    if skipped:
        flags.append(f"flow_rows_skipped:{skipped}")

    candidates.sort(key=lambda item: (-abs(item["flow_z"]), item["src"], item["dst"]))
    kept = candidates[: int(topk)]
    if len(candidates) > len(kept):
        flags.append(f"flow_edges_truncated:{len(candidates) - len(kept)}")

    edges: List[Dict[str, Any]] = []
    flows_meta: List[Dict[str, Any]] = []
    for index, item in enumerate(kept):
        edges.append(
            {
                "src": item["src"],
                "dst": item["dst"],
                "kind": "flow",
                "weight": round(min(1.0, abs(item["flow_z"]) / FLOW_WEIGHT_SCALE), 6),
                "p_adj": None,
            }
        )
        flows_meta.append(
            {
                "edge_index": index,
                "flow_usdt": round(float(item["flow_usdt"]), 2),
                "flow_z": round(float(item["flow_z"]), 6),
                "window": item["window"],
                "direction": item["direction"],
            }
        )
    return {"edges": edges, "flows": flows_meta, "flags": flags}


def flow_block(
    flows: Sequence[Mapping[str, Any]],
    *,
    nodes: Optional[Sequence[Mapping[str, Any]]] = None,
    corr_block: Optional[Mapping[str, Any]] = None,
    topk: int = DEFAULT_TOPK,
    window: int = DEFAULT_WINDOW,
) -> Dict[str, Any]:
    """产 D-E18 能力块：有流数据 → `flow` 边；无流数据 → `corr`-only 降级。"""
    projected = flow_edges(flows or (), topk=topk, window=window)
    edges = projected["edges"]
    flags = list(projected["flags"])

    if not edges:
        corr = build_corr_graph(blocks={"D-E05": corr_block}) if corr_block else None
        if corr is None:
            return {
                "gate": "empty",
                "methods": [],
                "reason": "flow_unavailable",
                "nodes": [],
                "edges": [],
                "meta": {"flows": [], "reason": "flow_unavailable"},
                "flags": sorted(set(flags + ["flow_unavailable", "corr_unavailable"])),
            }
        dataset = dict(corr["dataset"])
        dataset["meta"] = {"flows": [], "reason": "flow_unavailable"}
        visual = dict(corr)
        visual["dataset"] = dataset
        visual["source_capability"] = CAPABILITY
        visual["title"] = (
            f"D-E18 资金流缺数据·共振网络降级（{len(dataset['nodes'])} 节点 / {len(dataset['edges'])} 边）"[
                :60
            ]
        )
        validate_graph_dataset(dataset)
        return {
            "gate": "ok",
            "status": "corr_only",
            "methods": ["D-E05"],
            "reason": "flow_unavailable",
            "nodes": dataset["nodes"],
            "edges": dataset["edges"],
            "meta": {"flows": [], "reason": "flow_unavailable"},
            "visual": visual,
            "flags": sorted(set(flags + ["flow_unavailable"])),
        }

    if nodes is not None:
        node_rows = [
            {
                "id": _node_id(node.get("id")),
                "label": str(node.get("label") or node.get("id")),
                "group": str(node.get("group") or "asset"),
            }
            for node in nodes
            if isinstance(node, Mapping) and _node_id(node.get("id"))
        ]
        known = {node["id"] for node in node_rows}
        missing = [edge for edge in edges if edge["src"] not in known or edge["dst"] not in known]
        if missing:
            flags.append(f"endpoint_missing:{len(missing)}")
            edges = [edge for edge in edges if edge["src"] in known and edge["dst"] in known]
            projected["flows"] = [
                dict(item, edge_index=index)
                for index, item in enumerate(projected["flows"][: len(edges)])
            ]
    else:
        node_rows = _derive_nodes(edges)

    if not edges:
        return {
            "gate": "empty",
            "methods": [],
            "reason": "flow_edges_dropped",
            "nodes": node_rows[:MAX_NODES],
            "edges": [],
            "meta": {"flows": [], "reason": "flow_edges_dropped"},
            "flags": sorted(set(flags + ["flow_edges_dropped"])),
        }

    nodes_out = node_rows[:MAX_NODES]
    kept_ids = {node["id"] for node in nodes_out}
    edges = [edge for edge in edges if edge["src"] in kept_ids and edge["dst"] in kept_ids]
    edges = edges[:MAX_EDGES]
    flows_out = [
        dict(item, edge_index=index) for index, item in enumerate(projected["flows"][: len(edges)])
    ]
    dataset = {
        "nodes": nodes_out,
        "edges": edges,
        "meta": {"flows": flows_out, "reason": None},
    }
    validate_graph_dataset(dataset)
    truncated = len(node_rows) > MAX_NODES or len(projected["flows"]) > len(edges)
    visual = {
        "kind": "graph",
        "spec_version": SPEC_VERSION,
        "title": f"D-E18 资金流向导图（{len(nodes_out)} 节点 / {len(edges)} flow 边）"[:60],
        "source_capability": CAPABILITY,
        "n_scope": "global",
        "dataset": dataset,
        "encodings": {"group": "group", "weight": "weight", "kind": "kind"},
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": bool(truncated),
    }
    return {
        "gate": "ok",
        "status": "flow",
        "methods": ["I36"],
        "reason": None,
        "nodes": nodes_out,
        "edges": edges,
        "meta": dataset["meta"],
        "visual": visual,
        "truncated": bool(truncated),
        "flags": sorted(set(flags)),
    }


def flow_graph(
    flows: Sequence[Mapping[str, Any]],
    *,
    nodes: Optional[Sequence[Mapping[str, Any]]] = None,
    corr_block: Optional[Mapping[str, Any]] = None,
    topk: int = DEFAULT_TOPK,
    window: int = DEFAULT_WINDOW,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """D-E18 信封：`graph` 图 + `meta.flows[]`；无流数据降级 `corr`-only。"""
    block = flow_block(flows, nodes=nodes, corr_block=corr_block, topk=topk, window=window)
    if block.get("gate") != "ok":
        return unavailable(
            capability=CAPABILITY,
            intent=INTENT_FLOW,
            reason="资金流与共振网络均无可用数据（不伪造边）",
            trace_id=trace_id,
        )

    corr_only = block.get("status") == "corr_only"
    sample_n = len(block["meta"]["flows"])
    edge_n = len(block["edges"])
    if corr_only:
        q = quality(
            status=STATUS_PARTIAL,
            sample_n=edge_n,
            degraded_reason="flow_unavailable",
            sources=["market.correlation"],
            align_method="utc_daily_close",
            timezone="UTC",
        )
    else:
        q = quality_for(
            sample_n,
            min_n=1,
            sources=["etf_flow"],
            align_method="utc_daily_close",
            timezone="UTC",
        )
        if q["status"] != STATUS_GOOD:
            q = quality(
                status=STATUS_PARTIAL,
                sample_n=sample_n,
                degraded_reason=q.get("degraded_reason") or "flow_degraded",
                sources=["etf_flow"],
                align_method="utc_daily_close",
                timezone="UTC",
            )

    if corr_only:
        answer = (
            f"资金流导图降级为 corr-only：DFlow 数据缺失（样本不足），"
            f"仅展示 {len(block['nodes'])} 节点 / {edge_n} 条相关性边，未伪造流向。"
            "历史统计，不代表未来。"
        )
    else:
        answer = (
            f"资金流向导图：{len(block['nodes'])} 节点 / {edge_n} 条 flow 边"
            f"（按 |flow_z| 降序取 TopK，窗口 {window}，权重=min(1,|z|/3)）。"
            "历史统计，不代表未来。"
        )

    payload = {
        "capabilities": {CAPABILITY: block},
        "params": {"topk": int(topk), "window": int(window)},
    }
    return build(
        capability=CAPABILITY,
        intent=INTENT_FLOW,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=block["visual"],
    )


__all__ = [
    "CAPABILITY",
    "DEFAULT_DIRECTION",
    "DEFAULT_TOPK",
    "DEFAULT_WINDOW",
    "DIRECTIONS",
    "EDGE_KEYS",
    "FLOW_WEIGHT_SCALE",
    "INTENT_FLOW",
    "flow_block",
    "flow_edges",
    "flow_graph",
]
