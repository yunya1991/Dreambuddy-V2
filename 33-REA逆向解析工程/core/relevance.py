"""外部源价值评分（SPEC-33-E T-E6 / Q3）。

设计边界：
  - 打分由宿主 LLM 产出，本模块只做门禁与落库，**不调用模型**。
  - 只有 `gate=pass` 的分数才写入 `relevance_score`；未过 gate 的分数直接丢弃。
  - 外部源文件损坏或结构不符时 FAIL-OPEN：不写入、不覆盖、返回 known_gaps。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


def _source_id(item: dict[str, Any]) -> str:
    raw = item.get("source_id") or item.get("id") or ""
    return str(raw).strip()


def apply_relevance_scores(
    sources: Iterable[Any],
    scores: Iterable[Any],
) -> dict[str, Any]:
    """按门禁把打分合并进源列表（纯内存，不落盘）。"""
    merged = [dict(item) for item in sources if isinstance(item, dict)]
    by_id = {_source_id(item): item for item in merged if _source_id(item)}
    updated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in scores:
        if not isinstance(raw, dict):
            rejected.append({"source_id": "", "reason": "打分为非对象"})
            continue
        source_id = _source_id(raw)
        gate = str(raw.get("gate") or "unknown")
        score = raw.get("relevance_score")
        if source_id not in by_id:
            rejected.append({"source_id": source_id, "reason": "源未登记"})
            continue
        if gate != "pass":
            rejected.append({"source_id": source_id, "reason": f"gate={gate}，未经裁判不得写入"})
            continue
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not 0.0 <= float(score) <= 1.0
        ):
            rejected.append({"source_id": source_id, "reason": f"分数越界或非数值: {score!r}"})
            continue
        value = round(float(score), 3)
        by_id[source_id]["relevance_score"] = value
        updated.append({"source_id": source_id, "relevance_score": value})

    return {
        "sources": merged,
        "updated": updated,
        "rejected": rejected,
        "known_gaps": [f"{item['source_id'] or '-'}: {item['reason']}" for item in rejected],
    }


def write_relevance_scores(path: Path | str, report: dict[str, Any]) -> dict[str, Any]:
    """把已过门禁的分数写回外部源文件（原子替换，失败不破坏原文件）。"""
    updated = report.get("updated") or []
    if not updated:
        return {"written": 0, "known_gaps": []}

    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "written": 0,
            "known_gaps": [f"外部源文件不可读或损坏，未写入: {type(exc).__name__}: {exc}"],
        }
    entries = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return {
            "written": 0,
            "known_gaps": ["外部源文件结构不含 sources 列表，未写入"],
        }

    by_id = {
        _source_id(item): item for item in entries if isinstance(item, dict) and _source_id(item)
    }
    written = 0
    for item in updated:
        entry = by_id.get(str(item.get("source_id")))
        if entry is None:
            continue
        entry["relevance_score"] = item["relevance_score"]
        written += 1
    if not written:
        return {"written": 0, "known_gaps": ["未匹配到可写条目"]}

    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return {"written": written, "known_gaps": []}
