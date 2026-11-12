"""Reference Ledger — T-G13 调研参考账本 + 外源免疫 + gap 去重

SPEC-33-G §2.13 / G-G12：
  - 字段：ref_id/source/url/license/stack_fit/adapt_cost/capability/evidence/gap_id/usable
  - license=unknown 或 GPL 系进入闭源产品 → usable=false，只可参考思路
  - stack_fit < 0.4 → 只可参考思路，不得直接移植
  - 缺少 evidence.how_verified → 不算证据
  - 同一 gap_id 重复调研命中缓存，不重复消耗探索预算
  - usable 由本账本计算，调用方自报值一律忽略

工程约束：纯标准库；append-only JSONL；读坏行跳过（FAIL-OPEN）；契约违约抛错。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_SOURCES = ("github", "paper", "blog", "internal")
VALID_ADAPT_COST = ("S", "M", "L")
MIN_STACK_FIT = 0.4
GPL_FAMILY = ("GPL-2.0", "GPL-3.0", "AGPL-3.0")
LICENSE_ALIASES = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "bsd-3-clause": "BSD-3-Clause",
    "mpl-2.0": "MPL-2.0",
    "gpl-2.0": "GPL-2.0",
    "gpl-3.0": "GPL-3.0",
    "agpl-3.0": "AGPL-3.0",
}


class ReferenceError(ValueError):
    """Reference 契约违约（缺字段 / 非法取值 / 重复 ref_id）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReferenceError(message)


def normalize_license(value: Any) -> str:
    text = str(value or "").strip().lower()
    return LICENSE_ALIASES.get(text, "unknown")


class ReferenceLedger:
    """`reference/references.jsonl`：外源方案的准入与 gap 缓存。"""

    def __init__(self, root: str | Path, *, closed_source: bool = True):
        self.root = Path(root)
        self.closed_source = closed_source

    @property
    def ledger_path(self) -> Path:
        return self.root / "references.jsonl"

    # ---------------------------------------------------------------- 写

    def record(self, reference: Dict[str, Any]) -> Dict[str, Any]:
        reference = dict(reference or {})
        ref_id = str(reference.get("ref_id") or "").strip()
        _require(bool(ref_id), "ref_id is required")
        _require(bool(str(reference.get("source") or "").strip()), "source is required")
        source = str(reference["source"]).strip().lower()
        _require(source in VALID_SOURCES, f"source must be one of {VALID_SOURCES}")

        adapt_cost = str(reference.get("adapt_cost") or "").strip().upper()
        _require(adapt_cost in VALID_ADAPT_COST, f"adapt_cost must be one of {VALID_ADAPT_COST}")
        capability = str(reference.get("capability") or "").strip()
        _require(bool(capability), "capability is required")
        gap_id = str(reference.get("gap_id") or "").strip()
        _require(bool(gap_id), "gap_id is required")

        evidence = reference.get("evidence")
        _require(isinstance(evidence, dict), "evidence must be an object")
        how_verified = str(evidence.get("how_verified") or "").strip()

        try:
            stack_fit = float(reference.get("stack_fit"))
        except (TypeError, ValueError) as exc:
            raise ReferenceError("stack_fit must be a number in [0, 1]") from exc
        _require(0.0 <= stack_fit <= 1.0, "stack_fit must be in [0, 1]")

        license_name = normalize_license(reference.get("license"))
        existing = self.list()
        _require(
            all(item.get("ref_id") != ref_id for item in existing),
            f"duplicate ref_id: {ref_id}",
        )
        cache_hit = any(item.get("gap_id") == gap_id for item in existing)

        reasons: List[str] = []
        if license_name == "unknown":
            reasons.append("license_unknown")
        elif license_name in GPL_FAMILY and self.closed_source:
            reasons.append("gpl_closed_source")
        if stack_fit < MIN_STACK_FIT:
            reasons.append("low_stack_fit")
        if not how_verified:
            reasons.append("missing_how_verified")

        record: Dict[str, Any] = {
            "ref_id": ref_id,
            "source": source,
            "url": str(reference.get("url") or ""),
            "license": license_name,
            "stack_fit": stack_fit,
            "adapt_cost": adapt_cost,
            "capability": capability,
            "evidence": {
                "what": str(evidence.get("what") or ""),
                "how_verified": how_verified,
            },
            "gap_id": gap_id,
            "usable": not reasons,
            "blocked_reasons": reasons,
            "cache_hit": cache_hit,
        }
        self._append(record)
        return record

    # ---------------------------------------------------------------- 读

    def list(self) -> List[Dict[str, Any]]:
        if not self.ledger_path.is_file():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                loaded = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                rows.append(loaded)
        return rows

    def get(self, ref_id: str) -> Optional[Dict[str, Any]]:
        for item in self.list():
            if item.get("ref_id") == ref_id:
                return item
        return None

    def candidates(self, *, gap_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """仅 usable 的 Reference，按 stack_fit 降序（可移植候选）。"""
        rows = [
            item
            for item in self.list()
            if item.get("usable") is True and (not gap_id or item.get("gap_id") == gap_id)
        ]
        rows.sort(key=lambda item: (-float(item.get("stack_fit") or 0.0), item.get("ref_id") or ""))
        return rows

    def lookup_gap(self, gap_id: str) -> Dict[str, Any]:
        refs = [item for item in self.list() if item.get("gap_id") == gap_id]
        return {
            "gap_id": gap_id,
            "cached": bool(refs),
            "ref_ids": [item.get("ref_id") for item in refs],
            "usable_ref_ids": [item.get("ref_id") for item in refs if item.get("usable") is True],
        }

    def should_explore(self, gap_id: str) -> bool:
        """命中缓存即不再消耗探索预算。"""
        return not self.lookup_gap(gap_id)["cached"]

    # ---------------------------------------------------------------- 内部

    def _append(self, record: Dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
