"""检索触发任务（C11）：检索命中 → 按 task_key 排 job。

硬约束：
  - 去重窗口内同一 ref 不重复排 job（经 Store port，幂等键 task_key:ref@window）；
  - task_key 并发上限以注册表 max_concurrency 为准（开放态 run 超限跳过）；
  - FAIL-OPEN：任何异常只标 degraded，不抛错、不阻断检索主流程；
  - 只经 Store/Event port 落库，禁止直连 PG/SQLite；
  - 跨界通知不启用（P3 事件表通过评审前），只写 job_runs 控制面。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from ..ports import StorePort
from .job_runs import JobRunRecorder
from .registry import TaskRegistry, load_registry
from .windows import window_index

TABLE = "search_triggers"

# 开放态（非终态）run 计入并发占用
OPEN_STATES = ("pending", "claimed", "running")


def _ref_token(ref: str) -> str:
    return hashlib.sha1(ref.encode("utf-8")).hexdigest()[:12]


class SearchJobTrigger:
    """统一检索命中 → 控制面排 job（pending）。一次命中最多产出 1 个可追踪 job。"""

    def __init__(
        self,
        *,
        store: StorePort,
        recorder: JobRunRecorder,
        registry: Optional[TaskRegistry] = None,
        mapping: Optional[List[Dict[str, str]]] = None,
        table: str = TABLE,
    ) -> None:
        self.store = store
        self.recorder = recorder
        self.registry = registry or recorder.registry or load_registry()
        self.mapping = (
            [dict(r) for r in mapping]
            if mapping is not None
            else list(self.registry.search_triggers)
        )
        self.table = table

    # ── 主入口 ─────────────────────────────────────────────────────────
    def on_search(self, result: Dict[str, Any], *, now: float) -> Dict[str, Any]:
        """处理一次 unified_search 信封；FAIL-OPEN，永不抛错。"""
        try:
            return self._on_search(result or {}, now=float(now))
        except Exception as exc:
            return {
                "degraded": True,
                "error_code": "trigger_failed",
                "reason": f"{type(exc).__name__}: {exc}",
                "triggered": [],
                "skipped": [],
            }

    # ── 内部 ───────────────────────────────────────────────────────────
    def _on_search(self, result: Dict[str, Any], *, now: float) -> Dict[str, Any]:
        if not result.get("ok", True):
            # 全降级/失败的检索信封不排 job（禁止把故障伪装成触发源）
            return {"degraded": False, "error_code": "", "triggered": [], "skipped": []}
        hits = (result.get("data") or {}).get("hits") or result.get("hits") or []
        triggered: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for hit in hits:
            ref = str((hit or {}).get("ref", ""))
            if not ref:
                continue
            task_key = self._match(ref)
            if task_key is None:
                skipped.append({"ref": ref, "reason": "no_mapping"})
                continue
            spec = self.registry.get(task_key)
            if spec is None or not spec.enabled:
                skipped.append({"ref": ref, "task_key": task_key, "reason": "task_unavailable"})
                continue
            window = window_index(now, spec.window_sec)
            dedupe = f"{task_key}:{_ref_token(ref)}@{window}"
            if self._already(dedupe):
                skipped.append({"ref": ref, "task_key": task_key, "reason": "duplicate"})
                continue
            if self._open_count(task_key) >= spec.max_concurrency:
                skipped.append({"ref": ref, "task_key": task_key, "reason": "concurrency_limit"})
                continue
            row = self.recorder.enqueue(
                task_key,
                window=window,
                now=now,
                detail={
                    "trigger": "search_hit",
                    "ref": ref,
                    "score": hit.get("score"),
                    "sources": hit.get("sources") or [],
                },
            )
            self.store.write(
                self.table,
                data={
                    "id": dedupe,
                    "dedupe_key": dedupe,
                    "task_key": task_key,
                    "ref": ref,
                    "logical_window": window,
                    "run_id": row["run_id"],
                    "created_at": now,
                },
                idempotency_key=dedupe,
            )
            triggered.append(
                {
                    "ref": ref,
                    "task_key": task_key,
                    "run_id": row["run_id"],
                    "persisted": bool(row.get("persisted", True)),
                }
            )
        return {
            "degraded": False,
            "error_code": "",
            "triggered": triggered,
            "skipped": skipped,
        }

    def _match(self, ref: str) -> Optional[str]:
        for rule in self.mapping:
            prefix = str(rule.get("match", ""))
            if prefix and ref.startswith(prefix):
                return str(rule.get("task_key"))
        return None

    def _already(self, dedupe_key: str) -> bool:
        res = self.store.query(self.table, filters={"dedupe_key": dedupe_key}, limit=2) or {}
        return bool(res.get("rows"))

    def _open_count(self, task_key: str) -> int:
        res = self.store.query(self.recorder.table, filters={"task_key": task_key}, limit=500) or {}
        return sum(1 for r in res.get("rows") or [] if r.get("state") in OPEN_STATES)
