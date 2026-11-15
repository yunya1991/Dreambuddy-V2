# -*- coding: utf-8 -*-
"""统一能力结果信封（CapabilityResult）。

契约唯一事实源：`contracts/capability_result.schema.json`（SPEC-54 §5.3）。
本模块只做「组装 + 校验」，不做计算、不读库、不写库。

约束：
  - 顶层字段固定：`ok/capability/intent/answer/data/quality/trace_id`；
  - `quality` 只在顶层出现，`data` 内禁止嵌套 `quality`；
  - `answer` 禁止为空串；`quality.status != "good"` 时必须带降级说明；
  - 无法作答 → `ok=false`、`status=empty`，由 L1 转 L2（不伪造数据）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

STATUS_GOOD = "good"
STATUS_PARTIAL = "partial"
STATUS_EMPTY = "empty"

_INSUFFICIENT = "insufficient_samples"


def quality(
    *,
    status: str,
    sample_n: int = 0,
    span: Optional[Sequence[str]] = None,
    is_stale: bool = False,
    degraded_reason: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
    missing_rate: Optional[float] = None,
    align_method: Optional[str] = None,
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    if status not in (STATUS_GOOD, STATUS_PARTIAL, STATUS_EMPTY):
        raise ValueError(f"invalid quality.status: {status!r}")
    if status != STATUS_GOOD and not degraded_reason:
        raise ValueError("quality.status != good 时必须提供 degraded_reason")
    return {
        "status": status,
        "sample_n": int(sample_n),
        "span": list(span) if span else None,
        "is_stale": bool(is_stale),
        "degraded_reason": degraded_reason,
        "sources": list(sources) if sources is not None else [],
        "missing_rate": missing_rate,
        "align_method": align_method,
        "timezone": timezone,
    }


def quality_for(
    sample_n: int,
    *,
    min_n: int,
    span: Optional[Sequence[str]] = None,
    is_stale: bool = False,
    sources: Optional[Iterable[str]] = None,
    missing_rate: Optional[float] = None,
    align_method: Optional[str] = None,
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """按最小样本门禁自动定级：0 → empty，< min_n → partial，否则 good。"""
    if sample_n <= 0:
        return quality(
            status=STATUS_EMPTY,
            sample_n=0,
            span=span,
            is_stale=is_stale,
            degraded_reason="no_history",
            sources=sources,
            missing_rate=missing_rate,
            align_method=align_method,
            timezone=timezone,
        )
    if sample_n < min_n:
        return quality(
            status=STATUS_PARTIAL,
            sample_n=sample_n,
            span=span,
            is_stale=is_stale,
            degraded_reason=_INSUFFICIENT,
            sources=sources,
            missing_rate=missing_rate,
            align_method=align_method,
            timezone=timezone,
        )
    reason = "stale_data" if is_stale else None
    return quality(
        status=STATUS_PARTIAL if reason else STATUS_GOOD,
        sample_n=sample_n,
        span=span,
        is_stale=is_stale,
        degraded_reason=reason,
        sources=sources,
        missing_rate=missing_rate,
        align_method=align_method,
        timezone=timezone,
    )


# SPEC-54 §4.8 / ADR-V14：内部交易链路字段永不允许进入对外信封（递归扫描）。
_FORBIDDEN_DATA_KEYS = frozenset(
    {"signal", "order", "orders", "fill", "fills", "position", "positions", "comparison"}
)

# SPEC-54 §4.1 / §5 V-G3：图规格白名单与必填项（assembler 只校验、不产图）。
_VISUAL_KINDS = frozenset({"table", "series", "matrix", "tree", "graph"})
_VISUAL_REQUIRED = (
    "kind",
    "spec_version",
    "title",
    "source_capability",
    "n_scope",
    "dataset",
    "encodings",
    "quality_ref",
    "caveat",
    "truncated",
)
_MAX_ROWS = 500


def _check_visual(capability: str, visual: Mapping[str, Any]) -> Dict[str, Any]:
    """按 SPEC-54 §4.1 校验图规格；违规直接抛 ValueError（禁止静默降级）。"""
    if not isinstance(visual, Mapping):
        raise ValueError("visual 必须是 mapping")
    missing = [key for key in _VISUAL_REQUIRED if key not in visual]
    if missing:
        raise ValueError(f"visual 缺少字段: {missing}")
    if visual["kind"] not in _VISUAL_KINDS:
        raise ValueError(f"visual.kind 不在白名单: {visual['kind']!r}")
    if visual["spec_version"] != "1.0":
        raise ValueError(f"visual.spec_version 必须为 '1.0': {visual['spec_version']!r}")
    title = str(visual["title"]).strip()
    if not title or len(title) > 60:
        raise ValueError("visual.title 必须非空且不超过 60 字")
    if visual["source_capability"] != capability:
        raise ValueError("visual.source_capability 必须等于信封 capability（ADR-V2）")
    if visual["n_scope"] not in ("global", "per_row", "per_cell"):
        raise ValueError(f"visual.n_scope 非法: {visual['n_scope']!r}")
    if visual["quality_ref"] != "quality":
        raise ValueError("visual.quality_ref 必须为 'quality'")
    if not str(visual["caveat"]).strip():
        raise ValueError("visual.caveat 不可为空")
    if not isinstance(visual["truncated"], bool):
        raise ValueError("visual.truncated 必须是布尔值")
    dataset = visual["dataset"]
    if not isinstance(dataset, Mapping):
        raise ValueError("visual.dataset 必须是 mapping")
    if visual["kind"] == "table":
        if "columns" not in dataset or "rows" not in dataset:
            raise ValueError("table 必须提供 dataset.columns 与 dataset.rows")
        if len(dataset["rows"]) > _MAX_ROWS:
            raise ValueError(f"table.rows 超过上限 {_MAX_ROWS}")
    if visual["kind"] == "series":
        points = dataset.get("points")
        if not isinstance(points, Sequence) or not points:
            raise ValueError("series 必须提供非空 dataset.points")
        if len(points) > _MAX_ROWS:
            raise ValueError(f"series.points 超过上限 {_MAX_ROWS}")
        meta = dataset.get("meta")
        if not isinstance(meta, Mapping):
            raise ValueError("series 必须提供 dataset.meta（ADR-V9）")
        smoothing = meta.get("smoothing")
        if (
            not isinstance(smoothing, Mapping)
            or "method" not in smoothing
            or "window" not in smoothing
        ):
            raise ValueError("series.meta.smoothing 必须含 method/window（V-G8）")
        if "n" not in meta:
            raise ValueError("series.meta 必须含 n（V-G8）")
    if visual["kind"] == "tree":
        # B8 / V-G9：每叶可反查能力或 L0 序列，缺失必须显式降级
        from .overview import validate_tree_dataset

        validate_tree_dataset(dataset)
        encodings = visual.get("encodings")
        if (
            not isinstance(encodings, Mapping)
            or "label" not in encodings
            or "value" not in encodings
        ):
            raise ValueError("tree.encodings 必须含 label/value")
    if visual["kind"] == "graph":
        # ADR-V11：同一信封只 1 图，graph 只做 tree 叶子的下钻
        from .overview import validate_graph_dataset

        validate_graph_dataset(dataset)
        encodings = visual.get("encodings")
        if not isinstance(encodings, Mapping) or "group" not in encodings:
            raise ValueError("graph.encodings 必须含 group")
    return dict(visual)


def _internal_keys(node: Any) -> set:
    leaked: set = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            if isinstance(key, str) and key in _FORBIDDEN_DATA_KEYS:
                leaked.add(key)
            leaked |= _internal_keys(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            leaked |= _internal_keys(value)
    return leaked


def build(
    *,
    capability: str,
    intent: str,
    answer: str,
    data: Mapping[str, Any],
    quality_block: Mapping[str, Any],
    trace_id: Optional[str] = None,
    visual: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """组装并校验 CapabilityResult；契约违规直接抛 ValueError（禁止静默降级）。

    `visual=None` 时不写 `data["visual"]`（SPEC-54 §6 零回归路径）。
    """
    if not capability or not intent:
        raise ValueError("capability/intent 必填")
    text = (answer or "").strip()
    if not text:
        raise ValueError("answer 禁止为空串；无法作答请返回 ok=false + status=empty")
    if "quality" in data:
        raise ValueError("data 内禁止嵌套 quality（quality 固定顶层）")
    if "answer" in data:
        raise ValueError("data 内禁止嵌套 answer（answer 固定顶层）")
    payload = dict(data)
    if visual is not None:
        payload["visual"] = _check_visual(capability, visual)
    leaked = _internal_keys(payload)
    if leaked:
        raise ValueError(f"data 内禁止出现内部交易字段: {sorted(leaked)}")
    status = quality_block.get("status")
    if status not in (STATUS_GOOD, STATUS_PARTIAL, STATUS_EMPTY):
        raise ValueError(f"invalid quality.status: {status!r}")
    if status != STATUS_GOOD and "降级" not in text and "样本" not in text and "不足" not in text:
        raise ValueError("quality.status != good 时 answer 必须含降级说明")
    return {
        "ok": status != STATUS_EMPTY,
        "capability": capability,
        "intent": intent,
        "answer": text,
        "data": payload,
        "quality": dict(quality_block),
        "trace_id": trace_id,
    }


def unavailable(
    *,
    capability: str,
    intent: str,
    reason: str,
    data: Optional[Mapping[str, Any]] = None,
    sources: Optional[Iterable[str]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """干净交接：ok=false + status=empty，answer 说明原因但不给数值。"""
    text = f"暂无法给出该项统计：{reason}。样本或数据不足，不做推算（转 L2 处理）。"
    return build(
        capability=capability,
        intent=intent,
        answer=text,
        data=dict(data or {}),
        quality_block=quality(status=STATUS_EMPTY, degraded_reason=reason, sources=sources),
        trace_id=trace_id,
    )
