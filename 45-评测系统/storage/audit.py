# -*- coding: utf-8 -*-
"""
audit.py — 门禁执行审计日志（P3-5）
====================================
职责（PLAN P3-5 验收 / SPEC §12 审计规则）：
- append-only JSONL：每次门禁裁决留痕（申请 / 执行 / 判定 / 放行或拦截）
- 按 eval_id / kind 查询，最新在前，供「全链路审计可查」
- 不做删除与改写：审计文件只追加（trim 属运维期策略，不在代码内静默裁剪）

与报告证据链（`storage/repo.py` EvidenceRow）分工：
- 报告证据链：评测评测项与证据（谁被评、评了什么）
- 本审计：门禁裁决（谁在什么模式下放行/拦截、依据哪张凭证）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from storage.repo import zulu

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_PATH = (
    Path(__file__).resolve().parent.parent / "artifacts" / "audit" / "enforcement.jsonl"
)


class AuditLog:
    """追加式门禁审计日志。"""

    def __init__(
        self,
        path: str | Path = DEFAULT_AUDIT_PATH,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def path(self) -> Path:
        return self._path

    def append(self, record: dict[str, Any]) -> dict[str, Any]:
        """追加一条审计记录（补 `at` 时间戳），返回落盘后的记录。"""
        entry = dict(record)
        entry.setdefault("at", zulu(self._clock()))
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        logger.info(
            "gate audit kind=%s eval_id=%s decision=%s mode=%s",
            entry.get("kind"),
            entry.get("eval_id"),
            entry.get("decision"),
            entry.get("mode"),
        )
        return entry

    def query(
        self,
        eval_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """按 eval_id / kind 过滤，最新在前；文件不存在返回空。"""
        if not self._path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if eval_id is not None and obj.get("eval_id") != eval_id:
                continue
            if kind is not None and obj.get("kind") != kind:
                continue
            rows.append(obj)
        rows.reverse()
        return rows[: max(1, limit)]
