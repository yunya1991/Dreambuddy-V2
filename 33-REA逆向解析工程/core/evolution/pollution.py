"""Pollution Rollback — T-G8 记忆污染回滚

SPEC-33-G §2.6：
  1. 按 policy_id / change_id 检索生效期间写入的 Case / Evidence
  2. 标记 tainted=true（不删除，保留审计）
  3. recall 对 tainted 降权 ×0.3，且不作规则候选依据
  4. 由 tainted Case 触发的 verify 升级回退到上一等级
  5. 产出 pollution_report.json

工程约束：纯标准库；标记为追加字段，不删除历史；报告落盘。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

RECALL_WEIGHT_TAINTED = 0.3
QUALITY_ORDER = ("S", "A", "B", "C", "D")


class PollutionRollback:
    """标记 tainted、提供降权与 verify 等级回退；不做物理删除。"""

    def __init__(self, *, case_store: Any = None, evidence_path: Optional[str | Path] = None):
        self.case_store = case_store
        self.evidence_path = Path(evidence_path) if evidence_path else None

    def rollback(
        self,
        *,
        policy_id: str,
        report_path: str | Path,
        change_id: str = "",
    ) -> Dict[str, Any]:
        cases_tainted = 0
        if self.case_store is not None:
            for case in self.case_store.all():
                if self._matches(case, policy_id, change_id) and not case.get("tainted"):
                    case["tainted"] = True
                    self.case_store.add(case)
                    cases_tainted += 1

        evidence_tainted = self._taint_jsonl(policy_id, change_id)
        report = {
            "policy_id": policy_id,
            "change_id": change_id,
            "cases_tainted": cases_tainted,
            "evidence_tainted": evidence_tainted,
            "recall_weight": RECALL_WEIGHT_TAINTED,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report

    @staticmethod
    def recall_weight(record: Dict[str, Any]) -> float:
        return RECALL_WEIGHT_TAINTED if record.get("tainted") else 1.0

    @staticmethod
    def rollback_quality(quality: str) -> str:
        if quality not in QUALITY_ORDER:
            return quality
        index = QUALITY_ORDER.index(quality)
        return QUALITY_ORDER[min(index + 1, len(QUALITY_ORDER) - 1)]

    @staticmethod
    def _matches(record: Dict[str, Any], policy_id: str, change_id: str) -> bool:
        if policy_id and record.get("policy_id") == policy_id:
            return True
        return bool(change_id) and record.get("change_id") == change_id

    def _taint_jsonl(self, policy_id: str, change_id: str) -> int:
        if self.evidence_path is None or not self.evidence_path.exists():
            return 0
        lines = self.evidence_path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        tainted = 0
        for record in records:
            if self._matches(record, policy_id, change_id) and not record.get("tainted"):
                record["tainted"] = True
                tainted += 1
        if tainted:
            tmp = self.evidence_path.with_suffix(self.evidence_path.suffix + ".tmp")
            body = "\n".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) for item in records
            )
            tmp.write_text(body + "\n", encoding="utf-8")
            os.replace(tmp, self.evidence_path)
        return tainted
