"""Case Ledger — T-G12 迭代即案例（结构化契约 + 完成硬门禁）

SPEC-33-G §2.12：
  - §2.12.1 Case 契约：goal / hypotheses / changes / verification / outcome / defects / lessons / policy_id / evidence_refs
  - §2.12.2 入库硬门禁：字段完整率 100%，缺字段即失败；Case 不入库不算完成
  - §2.12.3 从 Case 到涌现：按 module × change_type × defect_type 聚类

工程约束：纯标准库；append-only JSONL；失败一律抛 CaseContractError（硬门禁，非 FAIL-OPEN）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REQUIRED_FIELDS = (
    "case_id",
    "iteration_id",
    "goal",
    "hypotheses",
    "changes",
    "verification",
    "outcome",
    "defects",
    "lessons",
    "policy_id",
    "evidence_refs",
    "created_at",
)


class CaseContractError(ValueError):
    """Case 契约不完整或不合法（硬门禁）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CaseContractError(message)


def validate_case(case: Any) -> Dict[str, Any]:
    """校验 Case 字段完整率 100%；返回原对象。"""
    _require(isinstance(case, dict), "case must be an object")
    for field in REQUIRED_FIELDS:
        _require(field in case, f"missing field: {field}")

    for field in ("case_id", "iteration_id", "goal", "created_at"):
        _require(
            isinstance(case[field], str) and case[field].strip() != "",
            f"field {field} must be a non-empty string",
        )

    hypotheses = case["hypotheses"]
    _require(
        isinstance(hypotheses, list) and bool(hypotheses), "hypotheses must be a non-empty list"
    )
    for item in hypotheses:
        _require(isinstance(item, dict), "hypothesis must be an object")
        _require(bool(str(item.get("claim") or "").strip()), "hypothesis missing claim")
        _require(bool(str(item.get("falsifier") or "").strip()), "hypothesis missing falsifier")

    changes = case["changes"]
    _require(isinstance(changes, dict), "changes must be an object")
    for field in ("files", "loc"):
        _require(isinstance(changes.get(field), int), f"changes.{field} must be an integer")
    _require(
        isinstance(changes.get("modules"), list) and bool(changes["modules"]),
        "changes.modules must be a non-empty list",
    )
    _require(changes.get("level") in ("L1", "L2", "L3"), "changes.level must be L1|L2|L3")

    verification = case["verification"]
    _require(isinstance(verification, dict), "verification must be an object")
    for field in ("tests", "passed", "duration_s"):
        _require(
            isinstance(verification.get(field), (int, float))
            and not isinstance(verification.get(field), bool),
            f"verification.{field} must be a number",
        )
    _require(isinstance(verification.get("gates"), list), "verification.gates must be a list")

    outcome = case["outcome"]
    _require(isinstance(outcome, dict), "outcome must be an object")
    for field in ("accepted", "reverted"):
        _require(isinstance(outcome.get(field), bool), f"outcome.{field} must be boolean")
    _require(outcome.get("reviewer") in ("auto", "human"), "outcome.reviewer must be auto|human")

    for field in ("defects", "lessons", "evidence_refs"):
        _require(isinstance(case[field], list), f"field {field} must be a list")

    _require(
        case["policy_id"] is None or isinstance(case["policy_id"], str),
        "policy_id must be a string or null",
    )
    return case


class CaseStore:
    """Case 账本（JSONL）。按 iteration_id 覆盖写入，保证一次迭代一条。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def add(self, case: Dict[str, Any]) -> Dict[str, Any]:
        validate_case(case)
        cases = [c for c in self._read_all() if c.get("iteration_id") != case["iteration_id"]]
        cases.append(dict(case))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n".join(json.dumps(c, ensure_ascii=False, sort_keys=True) for c in cases)
        self.path.write_text(body + "\n", encoding="utf-8")
        return dict(case)

    def exists(self, iteration_id: str) -> bool:
        return self.get(iteration_id) is not None

    def get(self, iteration_id: str) -> Optional[Dict[str, Any]]:
        for case in self._read_all():
            if case.get("iteration_id") == iteration_id:
                return case
        return None

    def all(self) -> List[Dict[str, Any]]:
        return self._read_all()

    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def require_case(iteration_id: str, store: CaseStore) -> Dict[str, Any]:
    """完成流程硬门禁：本次迭代必须有结构化 Case。"""
    case = store.get(iteration_id)
    if case is None:
        raise CaseContractError(f"本次迭代未产生结构化 Case，不算完成: {iteration_id}")
    return case


def case_to_outcome(case: Dict[str, Any]) -> Dict[str, Any]:
    """把 Case 映射为 verify 的 outcome 参数（§2.12.2 自动 verify）。"""
    validate_case(case)
    verification = case["verification"]
    outcome = case["outcome"]
    return {
        "accepted": outcome["accepted"],
        "tests_pass": verification["passed"] == verification["tests"],
        "reverted": outcome["reverted"],
    }
