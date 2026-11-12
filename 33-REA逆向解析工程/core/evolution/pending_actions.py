"""Pending Actions — T-G10 无 LLM 降级通道账本

SPEC-33-G §2.9：
  1. 触发照常计算，proposal 落 `policy/proposals/pending/`
  2. analyze / trace / rea_audit 信封带 `pending_actions[]`
  3. get_rea_snapshot(section=evolution) 返回待办（含 diff 与回滚点）
  4. TRAE workflow 启动即读，非空则提示

工程约束：纯标准库；本地 JSON 落盘；读失败一律 FAIL-OPEN（返回空待办，不阻断主链路）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VALID_LEVELS = ("L1", "L2", "L3")
DEFAULT_LIMIT = 20
ENVELOPE_LIMIT = 10


class PendingActionError(ValueError):
    """待办提案契约违约（缺字段/非法层级）。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PendingActionError(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PendingActionStore:
    """`policy/proposals/pending/` 账本：无 AI 模式下人工审批的唯一入口。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @property
    def pending_dir(self) -> Path:
        return self.root / "proposals" / "pending"

    def enqueue(
        self,
        proposal: Dict[str, Any],
        *,
        diff: str = "",
        rollback_point: str,
        target: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """登记待人工审批的 proposal（含 diff 与回滚点）。"""
        proposal = proposal or {}
        proposal_id = str(proposal.get("proposal_id") or "").strip()
        _require(bool(proposal_id), "proposal_id is required")
        level = str(proposal.get("level") or "").strip()
        _require(level in VALID_LEVELS, f"level must be one of {VALID_LEVELS}")
        trigger = str(proposal.get("trigger") or "").strip()
        _require(bool(trigger), "trigger is required")
        claim = str(proposal.get("claim") or "").strip()
        _require(bool(claim), "claim is required")
        _require(bool(str(proposal.get("falsifier") or "").strip()), "falsifier is required")
        _require(bool(str(rollback_point or "").strip()), "rollback_point is required")

        record: Dict[str, Any] = {
            "proposal_id": proposal_id,
            "level": level,
            "trigger": trigger,
            "claim": claim,
            "falsifier": proposal.get("falsifier"),
            "expected_effect": proposal.get("expected_effect", ""),
            "proposer_model": proposal.get("proposer_model", ""),
            "diff": diff or "",
            "rollback_point": rollback_point,
            "target": target,
            "status": "pending",
            "approve": f"approve_policy.py --id {proposal_id}",
            "created_at": _now(),
            "metadata": dict(metadata or {}),
        }
        self._write_json(self.pending_dir / f"{proposal_id}.json", record)
        return record

    def get(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        path = self.pending_dir / f"{proposal_id}.json"
        if not path.is_file():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return loaded if isinstance(loaded, dict) else None

    def actions(self, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """待办列表（新→旧），字段可直接进 MCP 信封 / snapshot。"""
        records: List[Dict[str, Any]] = []
        if self.pending_dir.is_dir():
            for path in sorted(self.pending_dir.glob("*.json")):
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(loaded, dict) and loaded.get("status") == "pending":
                    records.append(loaded)
        records.sort(
            key=lambda item: (str(item.get("created_at") or ""), item.get("proposal_id") or "")
        )
        records.reverse()
        if limit is not None:
            records = records[: max(0, int(limit))]
        return [self._summary(record) for record in records]

    def count(self) -> int:
        return len(self.actions(limit=None))

    @staticmethod
    def _summary(record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "proposal_id": record.get("proposal_id"),
            "level": record.get("level"),
            "trigger": record.get("trigger"),
            "claim": record.get("claim"),
            "falsifier": record.get("falsifier"),
            "expected_effect": record.get("expected_effect"),
            "diff": record.get("diff"),
            "rollback_point": record.get("rollback_point"),
            "target": record.get("target"),
            "state": record.get("status"),
            "approve": record.get("approve"),
            "created_at": record.get("created_at"),
        }

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
