# -*- coding: utf-8 -*-
"""评估层只读出口：D-K01 方法推荐 / D-K02 发现查询（SPEC-54 §14.7 / §15.6）。

纪律（§0.5.3 / ADR-V13）：
  - 本模块**只读预计算产物**（MERS 注册表 db / Discovery 报告 jsonl），
    不重算任何方法、不取数、不写库，排序与筛选只是投影；
  - 产物缺失一律 FAIL-OPEN 降级为 `empty`，不伪造推荐或候选；
  - 结论只陈述历史统计关系，禁止因果与预测措辞。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

from .envelope import (
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    quality,
    unavailable,
)
from .visual import CAVEAT, SPEC_VERSION

MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REGISTRY_FILE = os.path.join(MODULE_ROOT, "data", "relationship_registry.db")
REPORTS_DIR = os.path.join(MODULE_ROOT, "reports", "discovery")
ALGORITHM_REGISTRY_FILE = os.path.join(MODULE_ROOT, "config", "algorithm_registry.yaml")

CAPABILITY_RECOMMEND = "D-K01"
CAPABILITY_DISCOVERY = "D-K02"
INTENT_RECOMMEND = "relationship_recommend"
INTENT_DISCOVERY = "discovery_query"

METRIC_GATE = 250
TOP_N = 3
DEFAULT_DISCOVERY_TOP = 20
VIZ_KINDS = ("table", "matrix", "series", "graph")
_REPORT_DIR = re.compile(r"^\d{8}-\d{4}$")

_RECOMMEND_SQL = """
SELECT eval_id, method, transform, target, horizon, n, n_eff, rank_ic, icir,
       hit_rate, base_rate, excess_hit, hit_rate_lb, p_adj, stability,
       holdout_hit_rate, holdout_base_rate, holdout_agree, holdout_used_at,
       effect_bps, cost_bps, scope_json, perm_p, status, eval_at, data_version
  FROM relationship_eval
 WHERE target = ? AND horizon = ? AND gate_pass = 1
   AND status IN ('stable', 'candidate')
 ORDER BY ABS(rank_ic) DESC, n DESC
 LIMIT ?
"""


def _readonly_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # 过滤 NaN


def _scope(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _relation_map() -> Dict[str, str]:
    """method → 主 relation_type（只读 algorithm_registry，取 method_roles 首类）。"""
    try:
        import yaml

        with open(ALGORITHM_REGISTRY_FILE, "r", encoding="utf-8") as fh:
            registry = yaml.safe_load(fh) or {}
    except (OSError, ValueError, ImportError):
        return {}
    mapping: Dict[str, str] = {}
    for method, roles in (registry.get("method_roles") or {}).items():
        if isinstance(roles, (list, tuple)) and roles:
            mapping[str(method)] = str(roles[0])
    return mapping


def _visual_table(
    *,
    capability_id: str,
    items: List[Dict[str, Any]],
    status: str,
    degraded_reason: Optional[str],
) -> Dict[str, Any]:
    columns = [
        {"key": "relation_type", "label": "关系类", "type": "string"},
        {"key": "method", "label": "方法", "type": "string"},
        {"key": "transform", "label": "变换", "type": "string"},
        {"key": "horizon", "label": "期限", "type": "number"},
        {"key": "hit_rate", "label": "命中率", "type": "percent"},
        {"key": "base_rate", "label": "基线", "type": "percent"},
        {"key": "excess_hit", "label": "超额命中", "type": "percent"},
        {"key": "hit_rate_lb", "label": "Wilson下界", "type": "percent"},
        {"key": "n_eff", "label": "有效样本", "type": "number"},
        {"key": "p_adj", "label": "p_adj", "type": "number"},
        {"key": "effect_bps", "label": "效应(bps)", "type": "number"},
        {"key": "cost_bps", "label": "成本(bps)", "type": "number"},
        {"key": "perm_p", "label": "置换p", "type": "number"},
        {"key": "status", "label": "状态", "type": "string"},
    ]
    rows = [
        {
            "relation_type": item.get("relation_type"),
            "method": item.get("method"),
            "transform": item.get("transform"),
            "horizon": item.get("horizon"),
            "hit_rate": item.get("hit_rate"),
            "base_rate": item.get("base_rate"),
            "excess_hit": item.get("excess_hit"),
            "hit_rate_lb": item.get("hit_rate_lb"),
            "n_eff": item.get("n_eff"),
            "p_adj": item.get("p_adj"),
            "effect_bps": item.get("effect_bps"),
            "cost_bps": item.get("cost_bps"),
            "perm_p": item.get("perm_p"),
            "status": item.get("status"),
        }
        for item in items
    ]
    if status != STATUS_GOOD:
        reason = degraded_reason or "degraded"
        columns = [{"key": "degraded_reason", "label": "降级原因", "type": "string"}] + columns
        rows = [{"degraded_reason": reason, **row} for row in rows]
    return {
        "kind": "table",
        "spec_version": SPEC_VERSION,
        "title": "关系推荐卡片（历史统计）",
        "source_capability": capability_id,
        "n_scope": "per_row",
        "dataset": {"columns": columns, "rows": rows, "groups": []},
        "encodings": {},
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": False,
    }


def _visual_matrix(
    *,
    capability_id: str,
    path: str,
    target: str,
    relation_of: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    try:
        with _readonly_connect(path) as conn:
            records = [
                dict(row)
                for row in conn.execute(
                    "SELECT method, horizon, excess_hit, rank_ic FROM relationship_eval "
                    "WHERE target = ? AND gate_pass = 1 ORDER BY horizon",
                    (target,),
                )
            ]
    except sqlite3.Error:
        return None
    cells: Dict[str, Dict[int, float]] = {}
    horizons = sorted({int(row["horizon"]) for row in records})
    for row in records:
        value = _num(row.get("excess_hit"))
        if value is None:
            continue
        relation = relation_of.get(str(row.get("method"))) or "unmapped"
        bucket = cells.setdefault(relation, {})
        bucket[int(row["horizon"])] = max(bucket.get(int(row["horizon"]), value), value)
    if not cells or not horizons:
        return None
    row_labels = sorted(cells)
    values = [[cells[label].get(horizon) for horizon in horizons] for label in row_labels]
    return {
        "kind": "matrix",
        "spec_version": SPEC_VERSION,
        "title": "同类现象归纳（关系类 × 期限）",
        "source_capability": capability_id,
        "n_scope": "per_cell",
        "dataset": {
            "row_labels": row_labels,
            "col_labels": [f"h{horizon}" for horizon in horizons],
            "values": values,
            "horizons": horizons,
        },
        "encodings": {"row": "relation_type", "col": "horizon", "value": "excess_hit"},
        "quality_ref": "quality",
        "caveat": f"{CAVEAT}；单元格=门禁通过关系的最大超额命中率",
        "truncated": False,
    }


def _visual_series(
    *, capability_id: str, path: str, top: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    try:
        with _readonly_connect(path) as conn:
            records = [
                dict(row)
                for row in conn.execute(
                    "SELECT eval_at, rank_ic FROM relationship_eval "
                    "WHERE target = ? AND method = ? AND transform = ? AND horizon = ? "
                    "ORDER BY eval_at",
                    (
                        str(top.get("target")),
                        str(top.get("method")),
                        str(top.get("transform")),
                        int(top.get("horizon") or 0),
                    ),
                )
            ]
    except sqlite3.Error:
        return None
    points = [
        {"date": str(row["eval_at"])[:10], "value": _num(row["rank_ic"])}
        for row in records
        if _num(row.get("rank_ic")) is not None
    ]
    if len(points) < 2:
        return None
    return {
        "kind": "series",
        "spec_version": SPEC_VERSION,
        "title": "关系强度演化（RankIC）",
        "source_capability": capability_id,
        "n_scope": "global",
        "dataset": {
            "points": points,
            "meta": {
                "metric": "rank_ic",
                "n": len(points),
                "smoothing": {"method": "none", "window": 1},
            },
        },
        "encodings": {"x": "date", "y": "value"},
        "quality_ref": "quality",
        "caveat": CAVEAT,
        "truncated": False,
    }


def _visual_graph(
    *, capability_id: str, target: str, items: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    nodes = [{"id": f"target:{target}", "label": target, "group": "target"}]
    edges: List[Dict[str, Any]] = []
    seen = {f"target:{target}"}
    for item in items:
        method = str(item.get("method") or "")
        transform = str(item.get("transform") or "")
        if not method:
            continue
        method_id = f"method:{method}"
        if method_id not in seen:
            nodes.append({"id": method_id, "label": method, "group": "method"})
            seen.add(method_id)
        edges.append(
            {
                "src": method_id,
                "dst": f"target:{target}",
                "kind": "corr",
                "weight": item.get("abs_rank_ic"),
                "p_adj": item.get("p_adj"),
            }
        )
        if transform:
            transform_id = f"transform:{transform}"
            if transform_id not in seen:
                nodes.append({"id": transform_id, "label": transform, "group": "transform"})
                seen.add(transform_id)
            edges.append(
                {
                    "src": transform_id,
                    "dst": method_id,
                    "kind": "same_direction",
                    "weight": None,
                    "p_adj": None,
                }
            )
    if len(nodes) < 2:
        return None
    return {
        "kind": "graph",
        "spec_version": SPEC_VERSION,
        "title": "关系证据链（变换 → 方法 → 目标）",
        "source_capability": capability_id,
        "n_scope": "global",
        "dataset": {"nodes": nodes, "edges": edges},
        "encodings": {"group": "group"},
        "quality_ref": "quality",
        "caveat": f"{CAVEAT}；边权= |RankIC|，不代表因果",
        "truncated": False,
    }


def _recommend_visual(
    viz: str,
    *,
    capability_id: str,
    path: str,
    target: str,
    items: List[Dict[str, Any]],
    status: str,
    degraded_reason: Optional[str],
) -> Optional[Dict[str, Any]]:
    if viz == "table":
        return _visual_table(
            capability_id=capability_id,
            items=items,
            status=status,
            degraded_reason=degraded_reason,
        )
    if viz == "matrix":
        return _visual_matrix(
            capability_id=capability_id,
            path=path,
            target=target,
            relation_of=_relation_map(),
        )
    if viz == "series":
        return _visual_series(capability_id=capability_id, path=path, top=items[0] if items else {})
    if viz == "graph":
        return _visual_graph(capability_id=capability_id, target=target, items=items)
    return None


def recommend_relationship(
    *,
    db_path: Optional[str] = None,
    target: str = "",
    horizon: int = 1,
    top: int = TOP_N,
    viz: str = "table",
    capability_id: str = CAPABILITY_RECOMMEND,
    intent: str = INTENT_RECOMMEND,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """按 (target, horizon) 从注册表取 Top N 关系强度；不重算、不写库。"""
    if not str(target).strip():
        raise ValueError("target 必填（如 BTC / SP500）")
    if int(horizon) <= 0:
        raise ValueError("horizon 必须是正整数")
    viz = str(viz or "table")
    if viz not in VIZ_KINDS:
        raise ValueError(f"viz 必须是 {VIZ_KINDS} 之一")
    limit = max(1, min(int(top), TOP_N))
    path = db_path or REGISTRY_FILE

    if not os.path.isfile(path):
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="关系评估注册表尚未生成",
            sources=["registry.relationship_eval"],
            trace_id=trace_id,
        )

    try:
        with _readonly_connect(path) as conn:
            rows = [
                dict(row) for row in conn.execute(_RECOMMEND_SQL, (target, int(horizon), limit))
            ]
    except sqlite3.Error as exc:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason=f"关系评估注册表不可读（{type(exc).__name__}）",
            sources=["registry.relationship_eval"],
            trace_id=trace_id,
        )

    rows = [row for row in rows if _num(row.get("rank_ic")) is not None]
    if not rows:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="该目标与期限暂无通过门禁的评估",
            data={"params": {"target": target, "horizon": int(horizon), "top": limit}},
            sources=["registry.relationship_eval"],
            trace_id=trace_id,
        )

    top_row = rows[0]
    top_n = int(top_row.get("n") or 0)
    ic = _num(top_row["rank_ic"]) or 0.0
    p_adj = _num(top_row.get("p_adj"))
    stable = str(top_row.get("status")) == "stable"

    status = STATUS_GOOD if stable else STATUS_PARTIAL
    note = "" if stable else "（候选，尚未稳定，仅历史统计）"
    p_text = "未校正" if p_adj is None else f"{p_adj:.4f}"
    base_rate = _num(top_row.get("base_rate"))
    excess_hit = _num(top_row.get("excess_hit"))
    hit_text = ""
    if base_rate is not None and excess_hit is not None:
        hit_text = (
            f"；命中率 {float(_num(top_row.get('hit_rate')) or 0.0):.1%}"
            f"（基线 {base_rate:.1%}，超额 {excess_hit:+.1%}，"
            f"n_eff={int(top_row.get('n_eff') or 0)}）"
        )
    answer = (
        f"历史 {top_n} 个样本上，{top_row.get('method')} 与该目标的关系强度 "
        f"|RankIC|={abs(ic):.4f}（p_adj={p_text}，评估于 {str(top_row.get('eval_at') or '')[:10]}）"
        f"{hit_text}{note}。"
    )

    relation_of = _relation_map()
    items: List[Dict[str, Any]] = []
    for row in rows:
        row_ic = _num(row.get("rank_ic")) or 0.0
        items.append(
            {
                "eval_id": row.get("eval_id"),
                "relation_type": relation_of.get(str(row.get("method"))) or "unmapped",
                "method": row.get("method"),
                "transform": row.get("transform"),
                "target": row.get("target"),
                "horizon": int(row.get("horizon") or 0),
                "n": int(row.get("n") or 0),
                "n_eff": int(row.get("n_eff") or 0),
                "rank_ic": row_ic,
                "abs_rank_ic": abs(row_ic),
                "hit_rate": _num(row.get("hit_rate")),
                "base_rate": _num(row.get("base_rate")),
                "excess_hit": _num(row.get("excess_hit")),
                "hit_rate_lb": _num(row.get("hit_rate_lb")),
                "holdout_hit_rate": _num(row.get("holdout_hit_rate")),
                "holdout_base_rate": _num(row.get("holdout_base_rate")),
                "holdout_agree": bool(row.get("holdout_agree")),
                "holdout_used_at": row.get("holdout_used_at"),
                "effect_bps": _num(row.get("effect_bps")),
                "cost_bps": _num(row.get("cost_bps")),
                "perm_p": _num(row.get("perm_p")),
                "scope": _scope(row.get("scope_json")),
                "p_adj": _num(row.get("p_adj")),
                "stability": _num(row.get("stability")),
                "status": row.get("status"),
                "eval_at": row.get("eval_at"),
                "data_version": row.get("data_version"),
            }
        )

    visual = _recommend_visual(
        viz,
        capability_id=capability_id,
        path=path,
        target=target,
        items=items,
        status=status,
        degraded_reason=None if stable else "candidate_only",
    )

    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"target": target, "horizon": int(horizon), "top": limit, "viz": viz},
            "capabilities": {
                capability_id: {
                    "methods": sorted({str(row.get("method")) for row in rows}),
                    "n_gate": METRIC_GATE,
                    "rows": items,
                }
            },
        },
        quality_block=quality(
            status=status,
            sample_n=top_n,
            degraded_reason=None if stable else "candidate_only",
            sources=["registry.relationship_eval"],
            align_method="rank_ic_on_aligned_pairs",
            timezone="UTC",
        ),
        trace_id=trace_id,
        visual=visual,
    )


def _latest_report(root: str) -> Optional[Dict[str, Any]]:
    """取最新一期同时具备 manifest.json 与 findings.jsonl 的报告目录。"""
    try:
        names = sorted(
            (name for name in os.listdir(root) if _REPORT_DIR.match(name)),
            reverse=True,
        )
    except OSError:
        return None
    for name in names:
        directory = os.path.join(root, name)
        manifest_path = os.path.join(directory, "manifest.json")
        findings_path = os.path.join(directory, "findings.jsonl")
        if not (os.path.isfile(manifest_path) and os.path.isfile(findings_path)):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh) or {}
        except (OSError, ValueError):
            continue
        findings: List[Dict[str, Any]] = []
        try:
            with open(findings_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(item, dict):
                        findings.append(item)
        except OSError:
            continue
        patterns: List[Dict[str, Any]] = []
        patterns_path = os.path.join(directory, "patterns.json")
        if os.path.isfile(patterns_path):
            try:
                with open(patterns_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh) or {}
                if isinstance(loaded, dict) and isinstance(loaded.get("patterns"), list):
                    patterns = [item for item in loaded["patterns"] if isinstance(item, dict)]
            except (OSError, ValueError):
                patterns = []
        return {"name": name, "manifest": manifest, "findings": findings, "patterns": patterns}
    return None


def discovery_query(
    *,
    reports_dir: Optional[str] = None,
    top: int = DEFAULT_DISCOVERY_TOP,
    capability_id: str = CAPABILITY_DISCOVERY,
    intent: str = INTENT_DISCOVERY,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """只读最近一期 Discovery 报告，按 |RankIC| 排序返回候选；不重算、不扫描。"""
    limit = max(1, int(top))
    root = reports_dir or REPORTS_DIR
    report = _latest_report(root)
    if report is None:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="最近一期发现报告尚未生成",
            sources=["reports.discovery"],
            trace_id=trace_id,
        )

    manifest = report["manifest"]
    findings = [item for item in report["findings"] if _num(item.get("rank_ic")) is not None]
    findings.sort(key=lambda item: abs(_num(item.get("rank_ic")) or 0.0), reverse=True)
    picked = findings[:limit]

    items = []
    for item in picked:
        ic = _num(item.get("rank_ic")) or 0.0
        items.append(
            {
                "method": item.get("method"),
                "series": item.get("series") or item.get("dataset"),
                "transform": item.get("transform"),
                "target": item.get("target"),
                "horizon": item.get("horizon"),
                "n": int(item.get("n") or 0),
                "rank_ic": ic,
                "abs_rank_ic": abs(ic),
                "p_adj": _num(item.get("p_adj")),
                "stability": _num(item.get("stability")),
                "holdout_ic": _num(item.get("holdout_ic")),
                "status": "candidate",
            }
        )

    units = manifest.get("units") or manifest.get("n_units")
    if items:
        head = items[0]
        p_text = "未校正" if head["p_adj"] is None else f"{head['p_adj']:.4f}"
        answer = (
            f"最近一期发现：{head['method']} 作用于 {head['series']}（变换 {head['transform']}）"
            f"与 {head['target']} 的关系 |RankIC|={head['abs_rank_ic']:.4f}"
            f"（n={head['n']}，p_adj={p_text}，状态 candidate）。"
            f"共 {len(items)} 条候选，仅历史统计，不代表未来。"
        )
        status = STATUS_GOOD
        degraded = None
        sample_n = max(int(item["n"]) for item in items)
    else:
        answer = (
            f"最近一期发现（{report['name']}）FDR 校正后无候选：已扫描 {units if units is not None else '—'} 个评估单元，"
            "样本内无显著关系，不做推测。"
        )
        status = STATUS_PARTIAL
        degraded = "no_findings"
        sample_n = 0

    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"top": limit, "report": report["name"]},
            "capabilities": {
                capability_id: {
                    "methods": sorted({str(item.get("method")) for item in picked}),
                    "report": report["name"],
                    "space_hash": manifest.get("space_hash") or manifest.get("grid_hash"),
                    "data_version": manifest.get("data_version"),
                    "n_units": units,
                    "items": items,
                    "patterns": report.get("patterns") or [],
                }
            },
        },
        quality_block=quality(
            status=status,
            sample_n=sample_n,
            degraded_reason=degraded,
            sources=["reports.discovery"],
            align_method="rank_ic_on_aligned_pairs",
            timezone="UTC",
        ),
        trace_id=trace_id,
    )
