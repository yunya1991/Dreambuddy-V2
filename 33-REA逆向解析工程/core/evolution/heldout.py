"""Held-out Governance — T-G6 分桶、保留池与季度冻结

SPEC-33-G §1 G-G6 / §2.11.4 L2-10 / §2.11.9 第 7 条：
  - ≥100 条，按 section 分桶
  - 30% 永久保留，只由人工换入换出
  - 季度冻结；同源生成或曾参与训练/提示的一律作废
  - 不进入任何 Agent 上下文：evaluation_items() 只返回非保留池

工程约束：纯标准库；硬门禁抛 HeldoutError（不是 FAIL-OPEN）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MIN_TOTAL = 100
RESERVED_RATIO = 0.3


class HeldoutError(ValueError):
    """held-out 数据集违约（硬门禁）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HeldoutError(message)


def validate_manifest(
    items: Any,
    *,
    sections: Iterable[str],
    min_total: int = MIN_TOTAL,
    reserved_ratio: float = RESERVED_RATIO,
) -> List[Dict[str, Any]]:
    """校验 held-out 清单：总量、分桶、人工来源、保留比例、上下文隔离。"""
    _require(isinstance(items, list), "items must be a list")
    _require(len(items) >= min_total, f"held-out requires >=100 items, got {len(items)}")

    allowed = set(sections)
    seen: set[str] = set()
    reserved = 0
    for item in items:
        _require(isinstance(item, dict), "held-out item must be an object")
        item_id = str(item.get("id") or "").strip()
        _require(bool(item_id), "held-out item must have id")
        _require(item_id not in seen, f"duplicate held-out id: {item_id}")
        seen.add(item_id)

        section = str(item.get("section") or "").strip()
        _require(section in allowed, f"section '{section}' not in allowed buckets")
        _require(item.get("source") == "human", "held-out source must be human")
        _require(not item.get("agent_context"), "held-out item leaked into agent_context")
        _require(isinstance(item.get("reserved"), bool), "held-out reserved must be boolean")
        reserved += int(item["reserved"])

    ratio = reserved / len(items)
    _require(
        ratio >= reserved_ratio,
        f"reserved pool must be >=30% (got {ratio:.0%})",
    )
    return items


class HeldoutStore:
    def __init__(
        self,
        path: str | Path,
        *,
        sections: Iterable[str],
        min_total: int = MIN_TOTAL,
        reserved_ratio: float = RESERVED_RATIO,
    ):
        self.path = Path(path)
        self.sections = set(sections)
        self.min_total = min_total
        self.reserved_ratio = reserved_ratio

    # ---------- 读写 ----------

    def save(self, items: List[Dict[str, Any]], *, quarter: str) -> Dict[str, Any]:
        validate_manifest(
            items,
            sections=self.sections,
            min_total=self.min_total,
            reserved_ratio=self.reserved_ratio,
        )
        manifest = self._load_or_default()
        manifest["quarter"] = quarter
        manifest["items"] = items
        self._write(manifest)
        return manifest

    def _load_or_default(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "quarter": "", "frozen_quarter": "", "items": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, manifest: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    @property
    def frozen_quarter(self) -> str:
        return str(self._load_or_default().get("frozen_quarter") or "")

    # ---------- 冻结与换入换出 ----------

    def freeze(self, quarter: str) -> Dict[str, Any]:
        _require(bool(quarter.strip()), "quarter is required")
        manifest = self._load_or_default()
        manifest["frozen_quarter"] = quarter
        self._write(manifest)
        return manifest

    def replace(
        self,
        reserved_id: str,
        new_item: Dict[str, Any],
        *,
        operator: str,
        quarter: str,
    ) -> Dict[str, Any]:
        """人工换入换出：只允许新季度、必须登记 operator、只替换保留池条目。"""
        _require(bool(str(operator or "").strip()), "operator is required for held-out replacement")
        frozen = self.frozen_quarter
        _require(
            not frozen or quarter != frozen,
            f"held-out is frozen for {quarter}; wait for a new quarter",
        )

        manifest = self._load_or_default()
        items = manifest.get("items") or []
        index = next((i for i, item in enumerate(items) if item.get("id") == reserved_id), None)
        _require(index is not None, f"reserved item not found: {reserved_id}")
        _require(items[index].get("reserved") is True, "only reserved pool items can be replaced")
        _require(new_item.get("reserved") is True, "replacement must enter reserved pool")

        items[index] = dict(new_item)
        manifest["items"] = items
        manifest["quarter"] = quarter
        manifest["frozen_quarter"] = quarter
        validate_manifest(
            items,
            sections=self.sections,
            min_total=self.min_total,
            reserved_ratio=self.reserved_ratio,
        )
        self._write(manifest)
        return manifest

    # ---------- 查询 ----------

    def evaluation_items(self) -> List[Dict[str, Any]]:
        """可进入评测的条目：保留池永久排除，避免进入任何 Agent 上下文。"""
        return [item for item in self._load_or_default().get("items", []) if not item["reserved"]]

    def bucket_stats(self) -> Dict[str, Dict[str, int]]:
        stats: Dict[str, Dict[str, int]] = {}
        for item in self._load_or_default().get("items", []):
            bucket = stats.setdefault(item["section"], {"total": 0, "reserved": 0})
            bucket["total"] += 1
            bucket["reserved"] += int(bool(item["reserved"]))
        return stats

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        for item in self._load_or_default().get("items", []):
            if item.get("id") == item_id:
                return item
        return None
