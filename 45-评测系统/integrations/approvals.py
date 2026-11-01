# -*- coding: utf-8 -*-
"""
approvals.py — 27 审批凭证适配器（P3-4）
=========================================
职责（PLAN P3-4 验收 / SPEC §7 边界表「策略上线需双凭证」）：
- 读取 27-策略治理审批系统的审批台账（JSONL：`{id, decision, ts}`，ts 为毫秒）
- 语义与 27 一致：`decision ∈ {approve, approved, ok, pass, yes}` 且在有效期内才算通过
- 台账路径由 `EVAL_APPROVALS_LOG` 指定；未配置或不可读 → 一律不通过（fail-closed）

按文件契约读取而非 import 27 内部函数：45 与 27 不产生代码耦合，
27 侧只需保证台账字段不变（`id` / `decision` / `ts`）。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

APPROVED_DECISIONS = ("approve", "approved", "ok", "pass", "yes")
DEFAULT_MAX_AGE_MS = 86400_000  # 与 27 `_approval_ok` 一致：24h


class ApprovalChecker:
    """27 审批台账查询器（可注入路径/时钟，便于测试与部署）。"""

    def __init__(
        self,
        path: str | Path | None = None,
        now_ms: Callable[[], int] | None = None,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
    ) -> None:
        self._path = Path(path) if path is not None else _env_path()
        self._now_ms = now_ms or _now_ms
        self._max_age_ms = max_age_ms

    @property
    def path(self) -> Path | None:
        return self._path

    def __call__(self, approval_id: str) -> bool:
        return self.is_approved(approval_id)

    def is_approved(self, approval_id: str) -> bool:
        """审批存在、decision 通过且未超过有效期 → True；任何异常 → False。"""
        aid = str(approval_id or "").strip()
        if not aid or self._path is None or not self._path.is_file():
            return False
        try:
            obj = self._lookup(aid)
        except Exception as exc:  # noqa: BLE001 — 台账损坏按未通过
            logger.warning("审批台账读取失败（fail-closed）: %s", exc)
            return False
        if obj is None:
            return False
        if str(obj.get("decision") or "").strip().lower() not in APPROVED_DECISIONS:
            return False
        try:
            ts = int(obj.get("ts") or 0)
        except (TypeError, ValueError):
            return False
        if ts <= 0:
            return False
        return (self._now_ms() - ts) <= self._max_age_ms

    def _lookup(self, approval_id: str) -> dict[str, Any] | None:
        """倒序扫描台账，取最新一条同 id 记录（后写覆盖先写）。"""
        assert self._path is not None
        for line in reversed(self._path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and str(obj.get("id") or "").strip() == approval_id:
                return obj
        return None


def _env_path() -> Path | None:
    raw = os.environ.get("EVAL_APPROVALS_LOG", "").strip()
    return Path(raw) if raw else None


def _now_ms() -> int:
    return int(time.time() * 1000)
