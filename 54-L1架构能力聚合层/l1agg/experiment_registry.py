# -*- coding: utf-8 -*-
"""T7-2b 实验注册表统一视图（SPEC-20261116 §5.8.3）。

核对结论（只读）：48 侧**没有** SQLite `experiments` 表——实验结果是文件态
（`48-涌现架构/experiments/*/results/*.json`），裁决汇总在
`48-涌现架构/metrics/verdict_dashboard.json`。因此不做跨库 UNION，
改为「54 预注册表 + 48 裁决文件 → 派生只读视图」：

  - 两源各自写入，视图只读；
  - 视图按 `unit` 分组固定（period / session），**禁止跨 unit 聚合**；
  - `arm_scheme` / `verdict_scheme` 必填，防止两种 A/B 语义混用。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

SCHEMA_VERSION = "1.0"
UNIFIED_FIELDS = (
    "experiment_id",
    "unit",
    "arm_scheme",
    "endpoint",
    "n",
    "status",
    "verdict",
    "verdict_scheme",
    "reason",
    "generated_at",
    "provenance",
)
UNITS = ("period", "session")
ARM_SCHEMES = {"period": "aba_v1", "session": "abcd_2x2_v1"}
VERDICT_SCHEMES = {"period": "stat_relation_v1", "session": "d3_online_ab_v1"}
VERDICTS = ("candidate", "verified", "rejected", "falsified", "insufficient_data")


def _iso(moment: Optional[datetime] = None) -> str:
    return (
        (moment or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat(timespec="seconds")
    )


def from_prereg(row: Mapping[str, Any], *, generated_at: Optional[str] = None) -> Dict[str, Any]:
    """54 期级预注册 → 统一记录。"""
    verdict = row.get("verdict")
    return {
        "experiment_id": row.get("experiment_id"),
        "unit": "period",
        "arm_scheme": row.get("arm_scheme") or ARM_SCHEMES["period"],
        "endpoint": row.get("endpoint") or "excess_hit",
        "n": int(row.get("periods_observed") or 0),
        "status": row.get("status") or "preregistered",
        "verdict": verdict,
        "verdict_scheme": VERDICT_SCHEMES["period"] if verdict else None,
        "reason": row.get("reason_code"),
        "generated_at": generated_at or _iso(),
        "provenance": "experiment_prereg.db",
    }


def from_emergence(
    entry: Mapping[str, Any], *, generated_at: Optional[str] = None
) -> Dict[str, Any]:
    """48 verdict_dashboard 条目 → 统一记录（会话级）。"""
    return {
        "experiment_id": entry.get("run_id"),
        "unit": "session",
        "arm_scheme": ARM_SCHEMES["session"],
        "endpoint": "time_to_correct_action",
        "n": int(entry.get("n") or entry.get("n_sessions") or 0),
        "status": "closed",
        "verdict": entry.get("verdict"),
        "verdict_scheme": VERDICT_SCHEMES["session"],
        "reason": entry.get("reason"),
        "generated_at": generated_at or _iso(),
        "provenance": entry.get("evidence"),
    }


def load_emergence_dashboard(path: str) -> List[Dict[str, Any]]:
    """只读 48 裁决看板；缺失/损坏一律返回空（FAIL-OPEN）。"""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            document = json.load(fh) or {}
    except (OSError, ValueError):
        return []
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = from_emergence(entry)
        record["generated_at"] = str(document.get("generated_at") or record["generated_at"])
        out.append(record)
    return out


def _check(record: Mapping[str, Any]) -> Optional[str]:
    if not record.get("experiment_id"):
        return "missing_experiment_id"
    unit = record.get("unit")
    if unit not in UNITS:
        return "invalid_unit"
    if record.get("arm_scheme") != ARM_SCHEMES[unit]:
        return "arm_scheme_mismatch"
    verdict = record.get("verdict")
    if verdict is not None:
        if verdict not in VERDICTS:
            return "invalid_verdict"
        if record.get("verdict_scheme") != VERDICT_SCHEMES[unit]:
            return "verdict_scheme_mismatch"
    return None


def build_registry(
    prereg_rows: Iterable[Mapping[str, Any]],
    emergence_entries: Iterable[Mapping[str, Any]],
    *,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """合并两源，产出只读统一视图；非法记录进 `skipped`，不静默丢弃。"""
    stamp = generated_at or _iso()
    merged: Dict[tuple, Dict[str, Any]] = {}
    skipped: List[Dict[str, Any]] = []
    for row in prereg_rows:
        record = from_prereg(row, generated_at=stamp)
        reason = _check(record)
        if reason:
            skipped.append(
                {"source": "period", "experiment_id": record.get("experiment_id"), "reason": reason}
            )
            continue
        merged[(record["unit"], str(record["experiment_id"]))] = record
    for record in emergence_entries:
        reason = _check(record)
        if reason:
            skipped.append(
                {
                    "source": "session",
                    "experiment_id": record.get("experiment_id"),
                    "reason": reason,
                }
            )
            continue
        merged[(record["unit"], str(record["experiment_id"]))] = record
    records = sorted(merged.values(), key=lambda item: (item["unit"], str(item["experiment_id"])))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": stamp,
        "record_count": len(records),
        "records": records,
        "skipped": skipped,
    }


def summarize(document: Mapping[str, Any]) -> Dict[str, Any]:
    """按 unit 分组统计；**不输出跨 unit 合计**（防止把期数和会话数相加）。"""
    groups: Dict[str, Dict[str, Any]] = {
        unit: {"unit": unit, "total": 0, "verdicts": {}} for unit in UNITS
    }
    for record in document.get("records") or []:
        group = groups.get(str(record.get("unit")))
        if group is None:
            continue
        group["total"] += 1
        verdict = record.get("verdict") or "pending"
        group["verdicts"][verdict] = group["verdicts"].get(verdict, 0) + 1
    return {"units": [groups[unit] for unit in UNITS], "cross_unit_total": None}


def write_registry(document: Mapping[str, Any], path: str) -> Dict[str, Any]:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for record in document.get("records") or []:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return {"ok": True, "written": len(document.get("records") or []), "path": path}


def read_registry(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    out.append(item)
    except (OSError, ValueError):
        return []
    return out
