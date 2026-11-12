"""过 gate 结论的认知回写（SPEC-33-E T-E9）。

设计边界：
  - 内核不直连认知 MCP：只产出机读回写载荷（record + verify 参数）。
  - 写入开关关闭（`COGNITIVE_MCP_WRITE_ENABLED` 未开启）时状态为
    `suspended`，载荷保留给宿主，禁止伪造"已写入"。
  - 等级映射沿用 SPEC-D §2.6：observation/derivation → B；inference → C；
    reject/unknown/无 falsifier → 不写。
"""

from __future__ import annotations

import os
from typing import Any, Iterable

WRITE_ENV = "COGNITIVE_MCP_WRITE_ENABLED"
LEVEL_MAP = {"observation": "B", "derivation": "B", "inference": "C"}
SKIP_LEVELS = ("reject", "unknown")


def writeback_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.getenv(WRITE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _quality_for(gate: str, level: str, has_falsifier: bool) -> str | None:
    if gate in SKIP_LEVELS or not has_falsifier:
        return None
    if gate == "pass":
        return LEVEL_MAP.get(level, "B")
    if gate == "review":
        return "C"
    return None


def build_writeback_payload(items: Iterable[Any]) -> dict[str, Any]:
    """把假设/方案裁判结果转成 record + verify 机读载荷。"""
    writes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            skipped.append({"id": "", "reason": "条目非对象"})
            continue
        item_id = str(raw.get("hypothesis_id") or raw.get("plan_id") or "")
        gate = str(raw.get("gate") or "unknown")
        level = str(raw.get("level") or "hypothesis")
        has_falsifier = bool(raw.get("falsifier")) if "falsifier" in raw else True
        quality = _quality_for(gate, level, has_falsifier)
        content = str(raw.get("content") or raw.get("claim") or "")
        if quality is None or not content:
            skipped.append(
                {
                    "id": item_id,
                    "reason": (
                        "缺少可写内容" if not content else f"gate={gate}/level={level} 不可写"
                    ),
                }
            )
            continue
        writes.append(
            {
                "record": {
                    "content": content,
                    "quality_level": quality,
                    "level": level if level in LEVEL_MAP else "hypothesis",
                    "tags": "33-REA,rea_audit",
                    "external_id": item_id or None,
                },
                "verify": {"success": gate == "pass", "outcome": {"accepted": gate == "pass"}},
            }
        )
    return {
        "writes": writes,
        "skipped": skipped,
        "known_gaps": [f"{s['id']}: {s['reason']}" for s in skipped],
    }


def writeback_status(
    items: Iterable[Any],
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """返回回写状态：ready / suspended / nothing_to_write。"""
    payload = build_writeback_payload(items)
    if not payload["writes"]:
        return {
            "status": "nothing_to_write",
            "enabled": writeback_enabled(enabled),
            "writes": [],
            "skipped": payload["skipped"],
            "known_gaps": payload["known_gaps"],
        }
    if not writeback_enabled(enabled):
        return {
            "status": "suspended",
            "enabled": False,
            "writes": payload["writes"],
            "skipped": payload["skipped"],
            "known_gaps": payload["known_gaps"]
            + [f"{WRITE_ENV} 未开启：回写挂起，由宿主开启后按 writes 执行 record+verify"],
        }
    return {
        "status": "ready",
        "enabled": True,
        "writes": payload["writes"],
        "skipped": payload["skipped"],
        "known_gaps": payload["known_gaps"],
    }
