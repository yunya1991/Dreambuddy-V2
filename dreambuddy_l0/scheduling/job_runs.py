"""job_runs 记账（C9）：状态机 + 幂等 run key + missed_run + 保留策略。

硬约束：
  - 只经 L0-P 的 Store/Event port 落库，禁止直连 PG/SQLite；
  - run key = f"{task_key}@{logical_window}"，重启/时钟跳变后重复 run 被幂等拒绝；
  - 跨窗执行按窗口边界拆成多条 run；
  - 连续 3 窗无 run 发 scheduling.missing_run（同一 streak 只发一次）；
  - job_runs 保留 90 天；Store 无 delete 能力时 FAIL-OPEN 报 due 并发 prune_due 事件。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..ports import EventPort, MemoryPort, StorePort
from .event_bridge import JobRunEventBridge
from .registry import TaskRegistry, load_registry
from .windows import is_window_closed, split_segments, window_index, window_start

TABLE = "job_runs"


def run_key(task_key: str, logical_window: int) -> str:
    return f"{task_key}@{int(logical_window)}"


class JobRunRecorder:
    def __init__(
        self,
        *,
        store: StorePort,
        event: Optional[EventPort] = None,
        memory: Optional[MemoryPort] = None,
        registry: Optional[TaskRegistry] = None,
        table: str = TABLE,
        late_tolerance_sec: Optional[int] = None,
        retention_days: Optional[int] = None,
    ) -> None:
        self.store = store
        self.event = event
        # C8：终态同进程回调认知（external_id=run_id 幂等）；memory 为空时不回调
        self.bridge = JobRunEventBridge(memory=memory, event=event)
        self.registry = registry or load_registry()
        self.table = table
        self.tolerance_sec = (
            self.registry.late_tolerance_sec
            if late_tolerance_sec is None
            else int(late_tolerance_sec)
        )
        self.retention_days = (
            self.registry.retention_days if retention_days is None else int(retention_days)
        )

    # ── 单 run 状态机 ────────────────────────────────────────────────
    def begin(
        self,
        task_key: str,
        *,
        window: int,
        now: float,
        attempt: int = 1,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        spec = self.registry.get(task_key)
        if spec is None:
            raise ValueError(f"未注册的 task_key: {task_key}")
        rid = run_key(spec.task_key, window)
        row = {
            "id": rid,
            "run_id": rid,
            "task_key": spec.task_key,
            "logical_window": int(window),
            "state": "running",
            "attempts": int(attempt),
            "started_at": float(now),
            "heartbeat_at": float(now),
            "finished_at": 0.0,
            "error": "",
            "detail": detail or {},
        }
        # 首次尝试用幂等键防重复；重试是同一 run 的状态推进，不重复占幂等位
        ok = self.store.write(self.table, data=row, idempotency_key=rid if attempt <= 1 else "")
        row["persisted"] = bool(ok)
        if not ok:
            row["error_code"] = "store_unavailable"
        return row

    def enqueue(
        self,
        task_key: str,
        *,
        window: int,
        now: float,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """控制面排 job（C11）：state=pending，等数据面执行器认领，不得冒充 running。"""
        spec = self.registry.get(task_key)
        if spec is None:
            raise ValueError(f"未注册的 task_key: {task_key}")
        rid = run_key(spec.task_key, window)
        row = {
            "id": rid,
            "run_id": rid,
            "task_key": spec.task_key,
            "logical_window": int(window),
            "state": "pending",
            "attempts": 0,
            "started_at": float(now),
            "heartbeat_at": 0.0,
            "finished_at": 0.0,
            "error": "",
            "detail": detail or {},
        }
        ok = self.store.write(self.table, data=row, idempotency_key=rid)
        row["persisted"] = bool(ok)
        if not ok:
            row["error_code"] = "store_unavailable"
        return row

    def heartbeat(self, run_id: str, *, now: float) -> Optional[Dict[str, Any]]:
        row = self._find(run_id)
        if row is None:
            return None
        row = dict(row)
        row["heartbeat_at"] = float(now)
        self.store.write(self.table, data=row)
        return row

    def finish(
        self,
        run_id: str,
        *,
        now: float,
        state: str = "succeeded",
        error: str = "",
    ) -> Optional[Dict[str, Any]]:
        row = self._find(run_id)
        if row is None:
            return None
        row = dict(row)
        row["state"] = state
        row["finished_at"] = float(now)
        row["heartbeat_at"] = float(now)
        row["error"] = error
        self.store.write(self.table, data=row)
        # C8：落库后再回调（"已写状态、后写认知"），失败只告警不回滚
        row["bridge"] = self.bridge.on_terminal(row)
        return row

    def record_run(
        self,
        task_key: str,
        *,
        started_ts: float,
        finished_ts: Optional[float] = None,
        error: str = "",
        attempt: int = 1,
    ) -> List[Dict[str, Any]]:
        """记一次执行；跨窗自动拆分，每窗一条 run（幂等 run key）。"""
        spec = self.registry.get(task_key)
        if spec is None:
            raise ValueError(f"未注册的 task_key: {task_key}")
        end = float(started_ts if finished_ts is None else finished_ts)
        rows: List[Dict[str, Any]] = []
        state = "failed" if error else "succeeded"
        for idx, seg_start, seg_end in split_segments(float(started_ts), end, spec.window_sec):
            row = self.begin(task_key, window=idx, now=seg_start, attempt=attempt)
            rid = row["run_id"]
            done = self.finish(rid, now=seg_end, state=state, error=error)
            rows.append(done or row)
        return rows

    # ── missed_run 审计 ──────────────────────────────────────────────
    def audit(
        self, *, now_ts: float, since_ts: Optional[float] = None, host: str = ""
    ) -> Dict[str, Any]:
        """扫描已关闭但无 run 的窗口；连续 >=3 窗触发 missing_run 告警。

        host 非空时只审计该主机的任务（云端审计不得把 local 任务误判为缺失）。
        """
        try:
            missed: Dict[str, List[int]] = {}
            alerts = 0
            for spec in self.registry.list(enabled_only=True):
                if host and spec.host != host:
                    continue
                rows = self._query(filters={"task_key": spec.task_key})
                have = {
                    int(r.get("logical_window", -1)) for r in rows if r.get("state") != "missed_run"
                }
                now_idx = window_index(now_ts, spec.window_sec)
                if since_ts is not None:
                    start_idx = window_index(since_ts, spec.window_sec)
                elif have:
                    start_idx = max(have) + 1
                else:
                    start_idx = now_idx - self.registry.missed_streak_alert
                candidates: List[int] = []
                for idx in range(int(start_idx), now_idx + 1):
                    if not is_window_closed(
                        now_ts,
                        window_start(idx, spec.window_sec),
                        spec.window_sec,
                        self.tolerance_sec,
                    ):
                        continue
                    if idx in have:
                        continue
                    candidates.append(idx)
                    self._write_missed(spec.task_key, idx, spec.window_sec)
                if candidates:
                    missed[spec.task_key] = candidates
                    streak = self._streak(candidates)
                    if streak >= self.registry.missed_streak_alert:
                        self._publish_once(
                            "scheduling.missing_run",
                            {
                                "task_key": spec.task_key,
                                "windows": candidates,
                                "streak": streak,
                                "last_window": candidates[-1],
                                "dedupe_key": run_key(spec.task_key, candidates[-1]),
                            },
                        )
                        alerts += 1
            return {"degraded": False, "missed": missed, "alerts": alerts}
        except Exception as exc:  # FAIL-OPEN：审计失败不得阻断调度
            return {
                "degraded": True,
                "error_code": "audit_failed",
                "reason": f"{type(exc).__name__}: {exc}",
                "missed": {},
                "alerts": 0,
            }

    # ── 保留策略（90 天）─────────────────────────────────────────────
    def prune(self, *, now_ts: float, retention_days: Optional[int] = None) -> Dict[str, Any]:
        days = self.retention_days if retention_days is None else int(retention_days)
        cutoff = float(now_ts) - days * 86400
        rows = self._query(limit=5000)
        due = [
            str(r.get("run_id") or r.get("id"))
            for r in rows
            if float(r.get("started_at", 0) or 0) < cutoff and r.get("state") != "pruned"
        ]
        if not due:
            return {"due": 0, "deleted": 0, "error_code": ""}
        delete = getattr(self.store, "delete", None)
        if callable(delete):
            deleted = delete(self.table, ids=due)
            return {"due": len(due), "deleted": int(deleted), "error_code": ""}
        # 端口无删除能力：只报告到期条数并请求 adapter 侧压缩（禁止直连 DB）
        self._publish_once(
            "job_runs.prune_due",
            {"cutoff_ts": cutoff, "run_ids": due, "dedupe_key": f"prune:{int(cutoff)}"},
        )
        return {
            "due": len(due),
            "deleted": 0,
            "error_code": "port_delete_unavailable",
        }

    # ── 内部 ─────────────────────────────────────────────────────────
    def _query(
        self, *, filters: Optional[Dict[str, Any]] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        res = self.store.query(self.table, filters=filters, limit=limit) or {}
        return list(res.get("rows") or [])

    def _find(self, run_id: str) -> Optional[Dict[str, Any]]:
        rows = self._query(filters={"run_id": run_id}, limit=2)
        return rows[0] if rows else None

    def _write_missed(self, task_key: str, idx: int, window_sec: int) -> None:
        rid = run_key(task_key, idx)
        row = {
            "id": rid,
            "run_id": rid,
            "task_key": task_key,
            "logical_window": int(idx),
            "state": "missed_run",
            "attempts": 0,
            "started_at": window_start(idx, window_sec),
            "heartbeat_at": 0.0,
            "finished_at": 0.0,
            "error": "missing",
            "detail": {},
        }
        self.store.write(self.table, data=row, idempotency_key=rid)

    @staticmethod
    def _streak(windows: List[int]) -> int:
        streak = 1
        for prev, cur in zip(windows[::-1], windows[::-1][1:], strict=False):
            if prev - cur != 1:
                break
            streak += 1
        return streak

    def _publish_once(self, event_type: str, payload: Dict[str, Any]) -> bool:
        if self.event is None:
            return False
        key = payload.get("dedupe_key", "")
        if key:
            seen = self.event.consume(event_type=event_type, limit=200) or {}
            if any(
                (e.get("payload") or {}).get("dedupe_key") == key for e in seen.get("events") or []
            ):
                return False
        return self.event.publish(event_type, payload)
