# -*- coding: utf-8 -*-
"""T3 全景组合视图（SPEC-54-统计图表化能力 §4.5 / ADR-V11 / ADR-V13 / B8）。

职责：把**已算好的**多个能力块与**已取回的** L0 序列值投影成 `tree` / `graph`。
纯函数：不读库、不写库、不做统计、不新增口径（ADR-V13 零重算）。

B8 降级契约（V-G9）：
  - 能力叶：`meta.capability` 必须能在 manifest 反查，节点值等于来源块字段（±1e-9）；
  - 序列叶：`meta.series_id` 必须在 `SERIES_REGISTRY` 登记，且必带
    `proxy=true` / `unit` / `sign_flip`；`scope=crypto` 的序列禁止用于非加密资产；
  - 缺失节点：`value=None` + `meta.reason`（S5 未开放 / 门禁未过 / 字段为空）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..technical import CAVEAT
from .manifest import manifest as _load_manifest

SPEC_VERSION = "1.0"
COMPOSITE_CAPABILITY = "T3"
MAX_NODES = 300
MAX_EDGES = 2000
GRAPH_EDGE_KINDS = ("corr", "lead_lag", "same_direction", "flow")

# 加密资产白名单：只有这些资产允许使用加密巨鲸口径的资金净流（B8）
CRYPTO_SYMBOLS = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "DOGE",
        "ADA",
        "AVAX",
        "LINK",
        "DOT",
        "MATIC",
        "TRX",
        "LTC",
        "BCH",
        "TON",
        "SHIB",
        "UNI",
        "ATOM",
    }
)

# L0 序列登记表：未登记一律拒绝（禁止把其它指标冒充净流）
SERIES_REGISTRY: Dict[str, Dict[str, Any]] = {
    "exchanges_whales::whale_netflow_to_ex_usd": {
        "label": "巨鲸净流入交易所",
        "scope": "crypto",
        "unit": "亿美元",
        "proxy": True,
        # 落库口径为「转出-转入」，展示净流入需 ×(-1)
        "sign_flip": -1.0,
    },
}

# 静态叶规格：(叶 id, 标签, 能力 ID, 字段路径, 单位)
TREE_LAYOUT: Tuple[Tuple[str, str, Tuple[Tuple[str, str, str, Tuple[Any, ...], str], ...]], ...] = (
    (
        "forward",
        "前瞻性数据",
        (
            ("lead_lag", "领先滞后最优 lag", "D-E06", ("best_lag",), "bar"),
            ("lead_lag_ccf", "领先滞后最优 CCF", "D-E06", ("best_ccf",), "rho"),
            ("lead_lag_q", "领先滞后 BH-FDR q", "D-E06", ("best_q",), "q"),
            ("same_direction", "自然月同向率", "D-E11", ("cycle_alignment", "ratio"), "rate"),
            ("significance_t", "Newey-West t", "D-G22", ("newey_west", "t_nw"), "t"),
        ),
    ),
    (
        "resonance",
        "实时共振",
        (
            ("avg_abs_r", "平均 |ρ|", "D-E05", ("average_correlation", "avg_abs_r"), "rho"),
            ("top_pair_r", "Top1 相关 ρ", "D-E05", ("relationship_topk", "topk", 0, "r"), "rho"),
            ("top_pair_q", "Top1 BH-FDR q", "D-E05", ("relationship_topk", "topk", 0, "q"), "q"),
        ),
    ),
    (
        "performance",
        "跨资产表现",
        (
            ("mdd", "最大回撤 MDD", "D-E10", ("mdd",), "ratio"),
            ("current_drawdown", "当前回撤", "D-E10", ("current_drawdown",), "ratio"),
            ("crowding_score", "拥挤度 score", "D-A14", ("score",), "score"),
            ("crowding_percentile", "拥挤度分位", "D-A14", ("percentile",), "percent"),
        ),
    ),
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(value: Any) -> Optional[float]:
    return float(value) if _is_number(value) else None


def _dig(source: Any, path: Sequence[Any]) -> Any:
    """按路径取值；任一层缺失返回 None（不做默认值填补）。"""
    current = source
    for key in path:
        if isinstance(current, Mapping):
            if key not in current:
                return None
            current = current[key]
        elif isinstance(current, (list, tuple)):
            if not isinstance(key, int) or not -len(current) <= key < len(current):
                return None
            current = current[key]
        else:
            return None
    return current


def _known_capability(capability_id: str) -> bool:
    return any(cap.id == capability_id for cap in _load_manifest().capabilities)


def _leaf(
    *,
    node_id: str,
    label: str,
    value: Any = None,
    capability: Optional[str] = None,
    series_id: Optional[str] = None,
    proxy: Optional[bool] = None,
    unit: Optional[str] = None,
    sign_flip: Optional[float] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """构造叶节点并当场执行 B8 契约（非法来源直接抛 ValueError，不静默降级）。"""
    if not node_id or not label:
        raise ValueError("树节点 id/label 不可为空")
    meta: Dict[str, Any] = {}

    if capability is not None and series_id is not None:
        raise ValueError("叶节点不能同时声明 capability 与 series_id（B8）")

    if capability is not None:
        if not _known_capability(capability):
            raise ValueError(f"未知能力 ID，无法反查: {capability!r}")
        meta["capability"] = capability
        if unit:
            meta["unit"] = unit
    elif series_id is not None:
        spec = SERIES_REGISTRY.get(series_id)
        if spec is None:
            raise ValueError(f"未登记的 L0 序列，禁止进 T3: {series_id!r}")
        if spec.get("proxy") is not True:
            raise ValueError(f"序列 {series_id} 未标 proxy=true")
        if proxy is not True:
            raise ValueError(f"series_id 叶必须显式 proxy=true: {series_id}")
        if not unit or unit != spec.get("unit"):
            raise ValueError(f"series_id 叶 unit 必须为 {spec.get('unit')!r}: {series_id}")
        if sign_flip is None or float(sign_flip) != float(spec.get("sign_flip")):
            raise ValueError(
                f"series_id 叶 sign_flip 必须为 {spec.get('sign_flip')!r}: {series_id}"
            )
        meta.update(
            {"series_id": series_id, "proxy": True, "unit": unit, "sign_flip": float(sign_flip)}
        )
    else:
        if value is not None:
            raise ValueError("缺源节点必须 value=None（V-G9）")
        if not reason:
            raise ValueError("缺源节点必须给 meta.reason（V-G9）")

    if value is not None and not _is_number(value):
        raise ValueError(f"叶 value 必须是数值或 null: {node_id!r}")
    if value is None and not reason:
        raise ValueError(f"值为空的叶必须给 meta.reason: {node_id!r}")
    if reason:
        meta["reason"] = reason

    return {"id": node_id, "label": label, "value": value, "children": [], "meta": meta}


def _category(node_id: str, label: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"id": node_id, "label": label, "value": None, "children": children, "meta": {}}


def _missing_reason(block: Any, capability: str, path: Sequence[Any]) -> Optional[str]:
    dotted = ".".join(str(part) for part in path)
    if not isinstance(block, Mapping):
        return f"{capability} 未提供"
    if block.get("gate") != "ok":
        detail = block.get("reason") or block.get("degraded_reason")
        suffix = f"：{detail}" if detail else ""
        return f"{capability} 门禁未通过（gate={block.get('gate')}）{suffix}"
    return None if _number(_dig(block, path)) is not None else f"{capability}.{dotted} 为空"


def _alignment_children(blocks: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """D-E12 对齐切片：逐资产 `n_obs`，按行投影（零重算）。"""
    block = blocks.get("D-E12")
    rows = (
        list(block.get("window_rows") or ())
        if isinstance(block, Mapping) and block.get("gate") == "ok"
        else []
    )
    if not rows:
        return [
            _leaf(
                node_id="resonance.alignment",
                label="对齐切片有效观测",
                value=None,
                capability="D-E12",
                reason="D-E12 未提供或门禁未通过",
            )
        ]
    children = []
    for index, row in enumerate(rows):
        asset = str(row.get("asset") or f"#{index}")
        value = _number(row.get("n_obs"))
        children.append(
            _leaf(
                node_id=f"resonance.alignment.{index}",
                label=f"{asset} 有效观测",
                value=value,
                capability="D-E12",
                unit="obs",
                reason=None if value is not None else "D-E12 该资产 n_obs 为空",
            )
        )
    return children


def _flow_category(series_inputs: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    """资金流：只有加密巨鲸净流口径；缺失/越界一律 unavailable（B8）。"""
    if not series_inputs:
        return _category(
            "flow",
            "资金流",
            [
                _leaf(
                    node_id="flow.netflow",
                    label="资金净流（加密巨鲸口径）",
                    value=None,
                    reason="L0 序列未接入：资金净流仅加密巨鲸口径，其它资产无口径",
                )
            ],
        )
    children = []
    for index, item in enumerate(series_inputs):
        asset = str(item.get("asset") or "")
        series_id = str(item.get("series_id") or "")
        node_id = f"flow.{index}"
        spec = SERIES_REGISTRY.get(series_id)
        if spec is None:
            children.append(
                _leaf(
                    node_id=node_id,
                    label=f"{asset or '未知资产'} 资金净流",
                    value=None,
                    reason=f"未登记的 L0 序列：{series_id or '空'}",
                )
            )
            continue
        if spec.get("scope") == "crypto" and asset.upper() not in CRYPTO_SYMBOLS:
            children.append(
                _leaf(
                    node_id=node_id,
                    label=f"{asset} 资金净流",
                    value=None,
                    reason=f"{asset} 非加密资产，禁止使用加密巨鲸净流口径",
                )
            )
            continue
        raw = _number(item.get("value"))
        label = f"{asset} {spec['label']}"
        if raw is None:
            children.append(_leaf(node_id=node_id, label=label, value=None, reason="L0 序列无观测"))
            continue
        # sign_flip 是契约声明的展示换算，不是新增统计口径
        children.append(
            _leaf(
                node_id=node_id,
                label=label,
                value=raw * float(spec["sign_flip"]),
                series_id=series_id,
                proxy=True,
                unit=spec["unit"],
                sign_flip=spec["sign_flip"],
            )
        )
    return _category("flow", "资金流", children)


def _contradiction_category(blocks: Mapping[str, Any]) -> Dict[str, Any]:
    """主次矛盾：按 D-E05 TopK 的 ρ 原样排序投影（效应量，不加权、不合成）。"""
    block = blocks.get("D-E05")
    pairs = (
        list(_dig(block, ("relationship_topk", "topk")) or ()) if isinstance(block, Mapping) else []
    )
    children = []
    if not pairs:
        children.append(
            _leaf(
                node_id="contradiction.none",
                label="主次矛盾排序",
                value=None,
                capability="D-E05",
                reason="D-E05 TopK 未提供，无法排序",
            )
        )
    else:
        for index, pair in enumerate(pairs):
            weight = _number(pair.get("r"))
            children.append(
                _leaf(
                    node_id=f"contradiction.{index}",
                    label=f"{pair.get('a')}–{pair.get('b')} 相关强度",
                    value=weight,
                    capability="D-E05",
                    unit="rho",
                    reason=None if weight is not None else "D-E05 TopK 该对 ρ 为空",
                )
            )
    return _category("contradiction", "主次矛盾", children)


def _count_nodes(node: Mapping[str, Any]) -> int:
    return 1 + sum(_count_nodes(child) for child in node.get("children") or ())


def _trim(node: Dict[str, Any], budget: List[int]) -> Dict[str, Any]:
    budget[0] -= 1
    kept = []
    for child in node.get("children") or ():
        if budget[0] <= 0:
            break
        kept.append(_trim(child, budget))
    node["children"] = kept
    return node


def build_tree(
    *,
    blocks: Mapping[str, Any],
    as_of: Optional[str] = None,
    series_inputs: Optional[Sequence[Mapping[str, Any]]] = None,
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """T3 主图：根→类别→指标分层总览；每叶可反查能力 ID 或 L0 序列。"""
    root_children: List[Dict[str, Any]] = []
    for category_id, category_label, specs in TREE_LAYOUT:
        children: List[Dict[str, Any]] = []
        for leaf_id, label, capability, path, unit in specs:
            block = blocks.get(capability)
            value = _number(_dig(block, path))
            children.append(
                _leaf(
                    node_id=f"{category_id}.{leaf_id}",
                    label=label,
                    value=value,
                    capability=capability,
                    unit=unit,
                    reason=_missing_reason(block, capability, path),
                )
            )
        if category_id == "resonance":
            children.extend(_alignment_children(blocks))
        root_children.append(_category(category_id, category_label, children))

    root_children.append(_flow_category(series_inputs))
    root_children.append(_contradiction_category(blocks))
    root_children.append(
        _category(
            "relationship_recommend",
            "关系推荐",
            [
                _leaf(
                    node_id="relationship_recommend.s5",
                    label="S5 MERS 关系推荐",
                    value=None,
                    reason="S5 未开放",
                )
            ],
        )
    )

    root = {
        "id": "root",
        "label": f"全市场概览（{as_of}）" if as_of else "全市场概览",
        "value": None,
        "children": root_children,
        "meta": {},
    }
    truncated = _count_nodes(root) > MAX_NODES
    if truncated:
        root = _trim(root, [MAX_NODES])

    dataset = {"root": root}
    validate_tree_dataset(dataset)
    return {
        "kind": "tree",
        "spec_version": SPEC_VERSION,
        "title": (title or root["label"])[:60],
        "source_capability": COMPOSITE_CAPABILITY,
        "n_scope": "global",
        "dataset": dataset,
        "encodings": {"label": "label", "value": "value"},
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": truncated,
    }


def build_graph(
    *, blocks: Mapping[str, Any], title: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """T3 辅图：D-E05 共振网络（节点=资产，边=TopK 相关，kind 白名单）。"""
    block = blocks.get("D-E05")
    if not isinstance(block, Mapping) or block.get("gate") != "ok":
        return None
    names = [str(name) for name in _dig(block, ("matrix", "names")) or ()]
    if not names:
        return None
    nodes = [{"id": name, "label": name, "group": "asset"} for name in names[:MAX_NODES]]
    kept = {node["id"] for node in nodes}
    pairs = list(_dig(block, ("relationship_topk", "pairs")) or ())
    edges = []
    for pair in pairs:
        src = str(pair.get("a"))
        dst = str(pair.get("b"))
        if src not in kept or dst not in kept:
            continue
        edges.append(
            {
                "src": src,
                "dst": dst,
                "kind": "corr",
                "weight": _number(pair.get("r")),
                "p_adj": _number(pair.get("q")),
            }
        )
    truncated = len(names) > MAX_NODES or len(edges) > MAX_EDGES
    dataset = {"nodes": nodes, "edges": edges[:MAX_EDGES]}
    validate_graph_dataset(dataset)
    return {
        "kind": "graph",
        "spec_version": SPEC_VERSION,
        "title": (title or f"共振网络（{len(nodes)} 资产 / {len(dataset['edges'])} 边）")[:60],
        "source_capability": COMPOSITE_CAPABILITY,
        "n_scope": "global",
        "dataset": dataset,
        "encodings": {"group": "group"},
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": truncated,
    }


def _validate_leaf(node: Mapping[str, Any], path: str) -> None:
    meta = node["meta"]
    has_capability = "capability" in meta
    has_series = "series_id" in meta
    if has_capability and has_series:
        raise ValueError(f"叶不能同时声明 capability 与 series_id（B8）: {path}")
    if not has_capability and not has_series:
        if node["value"] is not None or not str(meta.get("reason") or "").strip():
            raise ValueError(f"缺源叶必须 value=null 且带 meta.reason（V-G9）: {path}")
        return
    if has_capability and not _known_capability(str(meta["capability"])):
        raise ValueError(f"叶的 capability 无法在 manifest 反查: {meta['capability']!r} @ {path}")
    if has_series:
        spec = SERIES_REGISTRY.get(str(meta["series_id"]))
        if spec is None:
            raise ValueError(f"叶的 series_id 未登记: {meta['series_id']!r} @ {path}")
        if meta.get("proxy") is not True:
            raise ValueError(f"series_id 叶必须 proxy=true（B8）: {path}")
        if not str(meta.get("unit") or "").strip():
            raise ValueError(f"series_id 叶必须带 unit（B8）: {path}")
        if meta.get("sign_flip") not in (-1.0, 1.0):
            raise ValueError(f"series_id 叶必须带 sign_flip ∈ {{-1,1}}（B8）: {path}")
    if node["value"] is None and not str(meta.get("reason") or "").strip():
        raise ValueError(f"值为空的叶必须带 meta.reason（V-G9）: {path}")
    if node["value"] is not None and not _is_number(node["value"]):
        raise ValueError(f"叶 value 必须是数值或 null: {path}")


def validate_tree_dataset(dataset: Mapping[str, Any]) -> None:
    """T3 tree 结构校验（V-G9 / V-AC11）；违规直接抛 ValueError。"""
    if not isinstance(dataset, Mapping) or not isinstance(dataset.get("root"), Mapping):
        raise ValueError("tree 必须提供 dataset.root")
    count = [0]

    def walk(node: Mapping[str, Any], path: str) -> None:
        for key in ("id", "label", "value", "children", "meta"):
            if key not in node:
                raise ValueError(f"tree 节点缺字段 {key}: {path}")
        if not isinstance(node["meta"], Mapping):
            raise ValueError(f"tree.meta 必须是 mapping: {path}")
        children = node["children"]
        if not isinstance(children, (list, tuple)):
            raise ValueError(f"tree.children 必须是数组: {path}")
        count[0] += 1
        if count[0] > MAX_NODES:
            raise ValueError(f"tree 节点超过上限 {MAX_NODES}")
        if not children:
            _validate_leaf(node, path)
            return
        seen = set()
        for child in children:
            if not isinstance(child, Mapping):
                raise ValueError(f"tree 子节点必须是 mapping: {path}")
            child_id = str(child.get("id"))
            if child_id in seen:
                raise ValueError(f"tree 同层节点 id 重复: {child_id}")
            seen.add(child_id)
            walk(child, f"{path}/{child_id}")

    walk(dataset["root"], str(dataset["root"].get("id")))


def validate_graph_dataset(dataset: Mapping[str, Any]) -> None:
    """T3 graph 结构校验（节点≤300、边≤2000、kind 白名单、端点必须存在）。"""
    if not isinstance(dataset, Mapping):
        raise ValueError("graph dataset 必须是 mapping")
    nodes = dataset.get("nodes")
    edges = dataset.get("edges")
    if not isinstance(nodes, (list, tuple)) or not nodes:
        raise ValueError("graph 必须提供非空 dataset.nodes")
    if len(nodes) > MAX_NODES:
        raise ValueError(f"graph.nodes 超过上限 {MAX_NODES}")
    if not isinstance(edges, (list, tuple)):
        raise ValueError("graph 必须提供 dataset.edges")
    if len(edges) > MAX_EDGES:
        raise ValueError(f"graph.edges 超过上限 {MAX_EDGES}")
    ids = []
    for node in nodes:
        if not isinstance(node, Mapping) or set(node) - {"id", "label", "group"}:
            raise ValueError("graph 节点字段只能是 id/label/group")
        if not isinstance(node.get("id"), str) or not node["id"]:
            raise ValueError("graph 节点 id 必须是非空字符串")
        if not isinstance(node.get("label"), str) or not node["label"]:
            raise ValueError("graph 节点 label 必须是非空字符串")
        if "group" in node and node["group"] is not None and not isinstance(node["group"], str):
            raise ValueError("graph 节点 group 必须是字符串或 null")
        ids.append(node["id"])
    if len(set(ids)) != len(ids):
        raise ValueError("graph 节点 id 必须唯一")
    known = set(ids)
    for edge in edges:
        if not isinstance(edge, Mapping) or set(edge) != {"src", "dst", "kind", "weight", "p_adj"}:
            raise ValueError("graph 边字段必须恰为 src/dst/kind/weight/p_adj")
        if edge["src"] not in known or edge["dst"] not in known:
            raise ValueError(f"graph 边端点不存在: {edge['src']}→{edge['dst']}")
        if edge["kind"] not in GRAPH_EDGE_KINDS:
            raise ValueError(f"graph.edge.kind 不在白名单: {edge['kind']!r}")
        for key in ("weight", "p_adj"):
            if edge[key] is not None and not _is_number(edge[key]):
                raise ValueError(f"graph.edge.{key} 必须是数值或 null")
