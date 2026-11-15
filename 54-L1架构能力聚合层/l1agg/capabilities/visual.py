# -*- coding: utf-8 -*-
"""图规格生产者（SPEC-54-统计图表化能力 §4.2 / §4.3 / §6）。

职责：把**已算好的**能力块投影成 `visual` 规格；前端零统计。
本模块是纯函数，不读库、不写库、不做统计。

门禁（SPEC §5）：
  - V-G1：`quality.status == "empty"` 不产图；
  - V-G2：来源能力块 `gate != "ok"` 不产图；
  - V-G3：`kind` 白名单 + `spec_version="1.0"`；
  - V-G4：行数上限 500，超出截断并标 `truncated=True`；
  - V-G7：`L1_VISUAL_ENABLED=0` 全量不产图（零回归兜底）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Optional

from ..technical import CAVEAT
from .manifest import manifest as _load_manifest

SPEC_VERSION = "1.0"
KINDS = ("table", "series", "matrix", "tree", "graph")
MAX_ROWS = 500

# D-E12 对齐切片固定 8 列（SPEC §4.3 / V-AC5）
ALIGNMENT_COLUMNS: List[Dict[str, str]] = [
    {"key": "asset", "label": "资产", "type": "string"},
    {"key": "start_value", "label": "期初值", "type": "number"},
    {"key": "end_value", "label": "期末值", "type": "number"},
    {"key": "ret", "label": "区间收益", "type": "percent"},
    {"key": "n_obs", "label": "有效观测", "type": "number"},
    {"key": "stale_ratio", "label": "陈旧占比", "type": "percent"},
    {"key": "first_date", "label": "首个观测", "type": "date"},
    {"key": "last_date", "label": "末个观测", "type": "date"},
]

# 方法审计矩阵的 6 类检查（l1agg/eval/harness.py 六检，顺序固定）
AUDIT_CHECKS = ("meta", "gate", "determinism", "synthetic", "null", "reference")

# T2 斜率表固定 6 列（SPEC §4.2；`hac_corrected=false` 必须显示）
SLOPE_COLUMNS: List[Dict[str, str]] = [
    {"key": "window", "label": "窗口", "type": "number"},
    {"key": "slope", "label": "对数斜率/日", "type": "number"},
    {"key": "se", "label": "标准误", "type": "number"},
    {"key": "t", "label": "t 值", "type": "number"},
    {"key": "r2", "label": "R²", "type": "number"},
    {"key": "hac_corrected", "label": "HAC 校正", "type": "string"},
]

# D-E17 类别看板固定 19 列（SPEC §4.4，顺序不可变）
CLASS_BOARD_COLUMNS: List[Dict[str, str]] = [
    {"key": "class", "label": "类别", "type": "string"},
    {"key": "symbol", "label": "标的", "type": "string"},
    {"key": "label", "label": "名称", "type": "string"},
    {"key": "role", "label": "角色", "type": "string"},
    {"key": "last", "label": "最新值", "type": "number"},
    {"key": "ret_20", "label": "20日收益", "type": "percent"},
    {"key": "ret_60", "label": "60日收益", "type": "percent"},
    {"key": "ret_120", "label": "120日收益", "type": "percent"},
    {"key": "ret_250", "label": "250日收益", "type": "percent"},
    {"key": "vol_60", "label": "60日波动", "type": "number"},
    {"key": "mdd", "label": "最大回撤", "type": "percent"},
    {"key": "adx14", "label": "ADX14", "type": "number"},
    {"key": "corr_to_leader_90d", "label": "90日龙头相关", "type": "number"},
    {"key": "lights_ref", "label": "点亮引用", "type": "string"},
    {"key": "lit_n", "label": "点亮数", "type": "number"},
    {"key": "warm_n", "label": "预热点数", "type": "number"},
    {"key": "n", "label": "有效观测", "type": "number"},
    {"key": "stale_ratio", "label": "陈旧占比", "type": "percent"},
    {"key": "status", "label": "状态", "type": "string"},
]

_MODULE_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


def enabled() -> bool:
    """V-G7：`L1_VISUAL_ENABLED=0/false/no/off` 时全量停用。"""
    raw = os.environ.get("L1_VISUAL_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _quality_status(quality_block: Optional[Mapping[str, Any]]) -> str:
    return str((quality_block or {}).get("status") or "")


def _degraded_reason(quality_block: Optional[Mapping[str, Any]]) -> str:
    return str((quality_block or {}).get("degraded_reason") or "degraded")


def _table(
    *,
    title: str,
    source_capability: str,
    columns: List[Dict[str, str]],
    rows: List[Dict[str, Any]],
    n_scope: str,
    groups: Optional[List[str]] = None,
) -> Dict[str, Any]:
    truncated = len(rows) > MAX_ROWS
    return {
        "kind": "table",
        "spec_version": SPEC_VERSION,
        "title": title,
        "source_capability": source_capability,
        "n_scope": n_scope,
        "dataset": {
            "columns": [dict(col) for col in columns],
            "rows": [dict(row) for row in rows[:MAX_ROWS]],
            "groups": list(groups or []),
        },
        "encodings": {},
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": truncated,
    }


def _table_with_degrade(
    *,
    title: str,
    source_capability: str,
    columns: List[Dict[str, str]],
    rows: List[Dict[str, Any]],
    n_scope: str,
    quality_block: Optional[Mapping[str, Any]],
    groups: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """V-AC6：`quality.status != good` 时首列必须是 `degraded_reason`。"""
    if _quality_status(quality_block) == "good":
        return _table(
            title=title,
            source_capability=source_capability,
            columns=columns,
            rows=rows,
            n_scope=n_scope,
            groups=groups,
        )
    reason = _degraded_reason(quality_block)
    marked = [{"degraded_reason": reason, **row} for row in rows]
    first = {"key": "degraded_reason", "label": "降级原因", "type": "string"}
    return _table(
        title=title,
        source_capability=source_capability,
        columns=[first] + list(columns),
        rows=marked,
        n_scope=n_scope,
        groups=groups,
    )


def _series(
    *,
    title: str,
    source_capability: str,
    points: List[Dict[str, Any]],
    meta: Dict[str, Any],
    encodings: Optional[Dict[str, str]] = None,
    n_scope: str = "global",
) -> Dict[str, Any]:
    """T2 曲线规格；V-G8 要求 `meta.smoothing{method,window}` 与 `meta.n` 必填。"""
    return {
        "kind": "series",
        "spec_version": SPEC_VERSION,
        "title": title,
        "source_capability": source_capability,
        "n_scope": n_scope,
        "dataset": {
            "points": [dict(point) for point in points[:MAX_ROWS]],
            "meta": dict(meta),
        },
        "encodings": dict(encodings or {"x": "date", "y": "value"}),
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": len(points) > MAX_ROWS,
    }


def _alignment_table(
    block: Mapping[str, Any], quality_block: Optional[Mapping[str, Any]]
) -> Dict[str, Any]:
    rows = [dict(row) for row in block.get("window_rows") or ()]
    window = str(block.get("window") or "")
    title = f"D-E12 对齐切片（{len(rows)} 资产 / {window}）"[:60]
    return _table_with_degrade(
        title=title,
        source_capability="D-E12",
        columns=ALIGNMENT_COLUMNS,
        rows=rows,
        n_scope="per_row",
        quality_block=quality_block,
        groups=["asset"],
    )


def _drawdown_series(
    block: Mapping[str, Any], quality_block: Optional[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """D-E10 → T2 曲线：`y` 为回撤幅度（0..mdd），首点 0、末点=current_drawdown、max=mdd。"""
    path = block.get("drawdown_path") or []
    points = []
    for index, row in enumerate(path):
        value = row.get("drawdown")
        if value is None:
            continue
        x = row.get("date")
        points.append({"x": x if x is not None else index, "y": value})
    if not points:
        return None
    meta = {
        "smoothing": {"method": "none", "window": 1},
        "unit": "ratio",
        "n": int((quality_block or {}).get("sample_n") or len(path)),
    }
    title = f"D-E10 回撤路径（{len(points)} 点 / MDD {block.get('mdd')}）"[:60]
    return _series(
        title=title,
        source_capability="D-E10",
        points=points,
        meta=meta,
        encodings={"x": "date", "y": "drawdown"},
    )


def _trend_series(
    block: Mapping[str, Any], quality_block: Optional[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """D-E15 → T2 曲线：`y`=原始价格、`smoothed`=EMA26（中周期），平滑口径写入 `meta`。"""
    smoothed = block.get("smoothed") or []
    prices = block.get("prices") or []
    if not smoothed or len(prices) != len(smoothed):
        return None
    points = []
    for index, row in enumerate(smoothed):
        x = row.get("date")
        points.append(
            {
                "x": x if x is not None else index,
                "y": prices[index],
                "smoothed": row.get("ema26"),
            }
        )
    meta = {
        "smoothing": {"method": "EMA", "window": 26},
        "unit": "price",
        "n": int((block.get("meta") or {}).get("n") or len(smoothed)),
        "periods": [12, 26, 50],
        "slope_windows": list((block.get("meta") or {}).get("windows") or ()),
    }
    title = f"D-E15 价格与 EMA26 平滑（{len(points)} 点）"[:60]
    return _series(
        title=title,
        source_capability="D-E15",
        points=points,
        meta=meta,
        encodings={"x": "date", "y": "price", "smoothed": "ema26"},
    )


def _aggregate_series(
    block: Mapping[str, Any], quality_block: Optional[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """D-E16 → T2 曲线：`y`=加权聚合值（rebased 100），逐点带成员值与覆盖度。"""
    points: List[Dict[str, Any]] = []
    for row in block.get("points") or ():
        value = row.get("agg")
        if value is None:
            continue
        points.append(
            {
                "x": row.get("date"),
                "y": value,
                "agg": value,
                "smoothed": row.get("ema26"),
                "members": dict(row.get("members") or {}),
                "coverage_ratio": row.get("coverage_ratio"),
                "partial_members": bool(row.get("partial_members")),
            }
        )
    if not points:
        return None
    meta = dict(block.get("meta") or {})
    meta["smoothing"] = dict(meta.get("smoothing") or {"method": "EMA", "window": 26})
    meta["unit"] = str(meta.get("unit") or "rebased_index")
    meta["n"] = int(meta.get("n") or len(points))
    title = f"D-E16 加权聚合曲线（{len(points)} 点 / {len(meta.get('members') or [])} 成员）"[:60]
    return _series(
        title=title,
        source_capability="D-E16",
        points=points,
        meta=meta,
        encodings={"x": "date", "y": "agg", "members": "members"},
    )


def _class_board_table(
    block: Mapping[str, Any], quality_block: Optional[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """D-E17 → T1 表格：固定 19 列；任一标的不达标时首列追加 `degraded_reason`。"""
    rows = [dict(row) for row in block.get("rows") or ()]
    if not rows:
        return None
    columns = [dict(col) for col in CLASS_BOARD_COLUMNS]
    if any(str(row.get("status")) != "available" for row in rows):
        columns = [{"key": "degraded_reason", "label": "降级原因", "type": "string"}] + columns
        rows = [
            {
                "degraded_reason": row.get("degraded_reason"),
                **{key: value for key, value in row.items() if key != "degraded_reason"},
            }
            for row in rows
        ]
    else:
        rows = [
            {key: value for key, value in row.items() if key != "degraded_reason"} for row in rows
        ]
    classes = {str(row.get("class")) for row in rows}
    title = f"D-E17 类别看板（{len(rows)} 标的 / {len(classes)} 类）"[:60]
    return _table(
        title=title,
        source_capability="D-E17",
        columns=columns,
        rows=rows,
        n_scope="per_row",
        groups=["class", "role"],
    )


_PRODUCERS = {
    "D-E10": _drawdown_series,
    "D-E12": _alignment_table,
    "D-E15": _trend_series,
    "D-E16": _aggregate_series,
    "D-E17": _class_board_table,
}


def build_visual(
    *,
    capability: str,
    data: Mapping[str, Any],
    quality_block: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """按能力 ID 产图；任何门禁不满足一律返回 None（FAIL-OPEN，不伪造图）。"""
    if not enabled():
        return None
    if _quality_status(quality_block) == "empty":
        return None
    producer = _PRODUCERS.get(capability)
    if producer is None:
        return None
    block = (data.get("capabilities") or {}).get(capability)
    if not isinstance(block, Mapping) or block.get("gate") != "ok":
        return None
    visual = producer(block, quality_block)
    if visual is None:
        return None
    if visual["kind"] not in KINDS or visual["spec_version"] != SPEC_VERSION:
        return None
    return visual


def slope_table(block: Mapping[str, Any]) -> Dict[str, Any]:
    """D-E15 斜率表（T2 `table`，固定 6 列；空窗口保留 null，不隐藏）。"""
    rows = []
    for row in block.get("slope_table") or ():
        rows.append(
            {
                "window": row.get("window"),
                "slope": row.get("slope"),
                "se": row.get("se"),
                "t": row.get("t"),
                "r2": row.get("r2"),
                "hac_corrected": row.get("hac_corrected"),
            }
        )
    return {
        "columns": [dict(col) for col in SLOPE_COLUMNS],
        "rows": rows[:MAX_ROWS],
        "groups": ["window"],
    }


# ---------------- T1 元表（数据集级，无信封；供报告/制品消费） ----------------


def capability_table() -> Dict[str, Any]:
    """能力清单表：一行一个能力出口（manifest 为唯一事实源）。"""
    rows = []
    for cap in _load_manifest().capabilities:
        rows.append(
            {
                "id": cap.id,
                "intent": cap.intent,
                "mode": cap.mode,
                "visibility": cap.visibility,
                "methods": ",".join(cap.methods),
                "n_methods": len(cap.methods),
                "min_n": cap.min_n,
            }
        )
    columns = [
        {"key": "id", "label": "能力 ID", "type": "string"},
        {"key": "intent", "label": "意图", "type": "string"},
        {"key": "mode", "label": "模式", "type": "string"},
        {"key": "visibility", "label": "可见性", "type": "string"},
        {"key": "methods", "label": "方法", "type": "string"},
        {"key": "n_methods", "label": "方法数", "type": "number"},
        {"key": "min_n", "label": "最小样本", "type": "number"},
    ]
    return {
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "groups": ["intent", "mode", "visibility"],
    }


def method_audit_table(path: Optional[str] = None) -> Dict[str, Any]:
    """方法审计矩阵表：METHOD_LIBRARY 全量方法 × 6 检查（复用 `docs/method_audit.json`，零新增采集）。"""
    target = path or os.path.join(_MODULE_ROOT, "docs", "method_audit.json")
    with open(target, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    rows = []
    for item in report.get("methods") or ():
        cells = {chk["name"]: chk for chk in item.get("checks") or () if isinstance(chk, Mapping)}
        row: Dict[str, Any] = {"method_id": str(item.get("method_id"))}
        for name in AUDIT_CHECKS:
            check = cells.get(name)
            if check is None:
                row[name] = "missing"
            elif check.get("skipped"):
                row[name] = "n/a"
            else:
                row[name] = "pass" if check.get("passed") else "fail"
        rows.append(row)
    columns = [{"key": "method_id", "label": "方法 ID", "type": "string"}]
    columns += [{"key": name, "label": name, "type": "string"} for name in AUDIT_CHECKS]
    return {"columns": columns, "rows": rows[:MAX_ROWS], "groups": []}
