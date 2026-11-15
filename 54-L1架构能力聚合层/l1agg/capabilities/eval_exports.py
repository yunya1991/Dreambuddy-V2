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

MODULE_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REGISTRY_FILE = os.path.join(MODULE_ROOT, "data", "relationship_registry.db")
REPORTS_DIR = os.path.join(MODULE_ROOT, "reports", "discovery")

CAPABILITY_RECOMMEND = "D-K01"
CAPABILITY_DISCOVERY = "D-K02"
INTENT_RECOMMEND = "relationship_recommend"
INTENT_DISCOVERY = "discovery_query"

METRIC_GATE = 250
TOP_N = 3
DEFAULT_DISCOVERY_TOP = 20
_REPORT_DIR = re.compile(r"^\d{8}-\d{4}$")

_RECOMMEND_SQL = """
SELECT eval_id, method, transform, target, horizon, n, rank_ic, icir,
       p_adj, stability, status, eval_at, data_version
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


def recommend_relationship(
    *,
    db_path: Optional[str] = None,
    target: str = "",
    horizon: int = 1,
    top: int = TOP_N,
    capability_id: str = CAPABILITY_RECOMMEND,
    intent: str = INTENT_RECOMMEND,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """按 (target, horizon) 从注册表取 Top N 关系强度；不重算、不写库。"""
    if not str(target).strip():
        raise ValueError("target 必填（如 BTC / SP500）")
    if int(horizon) <= 0:
        raise ValueError("horizon 必须是正整数")
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
    answer = (
        f"历史 {top_n} 个样本上，{top_row.get('method')} 与该目标的关系强度 "
        f"|RankIC|={abs(ic):.4f}（p_adj={p_text}，评估于 {str(top_row.get('eval_at') or '')[:10]}）{note}。"
    )

    items: List[Dict[str, Any]] = []
    for row in rows:
        row_ic = _num(row.get("rank_ic")) or 0.0
        items.append(
            {
                "eval_id": row.get("eval_id"),
                "method": row.get("method"),
                "transform": row.get("transform"),
                "horizon": int(row.get("horizon") or 0),
                "n": int(row.get("n") or 0),
                "rank_ic": row_ic,
                "abs_rank_ic": abs(row_ic),
                "p_adj": _num(row.get("p_adj")),
                "stability": _num(row.get("stability")),
                "status": row.get("status"),
                "eval_at": row.get("eval_at"),
                "data_version": row.get("data_version"),
            }
        )

    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"target": target, "horizon": int(horizon), "top": limit},
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
        return {"name": name, "manifest": manifest, "findings": findings}
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
