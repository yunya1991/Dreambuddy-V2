"""C8 事件互通：`job_runs` 终态 → 认知 record（同进程回调，`external_id=run_id` 幂等）。

硬约束（SPEC-L0 §3.2 组件② / §6 P2 C8）：
  - 默认不建跨库 outbox：run 落库后同进程回调，一次写；
  - `external_id = run_id`，重复执行/重启不产生重复记忆（G0-8 已备唯一索引）；
  - 只经 Memory / Event port，禁止直连认知库；
  - FAIL-OPEN：认知侧异常只告警，已成功的 run 不回滚。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, Optional

from ..ports import EventPort, MemoryPort

logger = logging.getLogger("l0.scheduling.event_bridge")

# 只有终态才回调认知；running/pending/missed_run 不产生记忆
TERMINAL_STATES = ("succeeded", "failed", "timeout", "dead")


def memory_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """C8 开关：显式 `JOB_RUNS_MEMORY` 优先；未设时仅云端（PG 后端）默认开启。

    本地默认关闭——认知权威库在云端，本地只保留只读镜像（禁止本地直写）。
    """
    source = os.environ if env is None else env
    flag = str(source.get("JOB_RUNS_MEMORY") or "").strip()
    if flag:
        return flag == "1"
    return source.get("DATA_CENTER_BACKEND") == "postgres"


def run_event_content(row: Dict[str, Any]) -> str:
    """把 run 行转成可被 recall 的一句话（task_key/run_id/state 必须在正文里）。"""
    duration = float(row.get("finished_at", 0) or 0) - float(row.get("started_at", 0) or 0)
    parts = [
        "[L0调度][job_runs]",
        f"task_key={row.get('task_key', '')}",
        f"run_id={row.get('run_id', '')}",
        f"window={row.get('logical_window', '')}",
        f"state={row.get('state', '')}",
        f"duration={duration:.1f}s",
    ]
    if row.get("error"):
        parts.append(f"error={row['error']}")
    return " ".join(parts)


class JobRunEventBridge:
    """run 终态回调：写一条认知记忆（幂等键=run_id）。"""

    def __init__(
        self,
        memory: Optional[MemoryPort] = None,
        *,
        event: Optional[EventPort] = None,
    ) -> None:
        self.memory = memory
        self.event = event

    def on_terminal(self, row: Dict[str, Any], *, source: str = "l0.scheduler") -> Dict[str, Any]:
        state = str(row.get("state", ""))
        if self.memory is None:
            return {"recorded": False, "skipped": True, "error_code": ""}
        if state not in TERMINAL_STATES:
            return {"recorded": False, "skipped": True, "error_code": ""}
        run_id = str(row.get("run_id") or row.get("id") or "")
        try:
            memory_id = self.memory.record(
                run_event_content(row),
                tags=["L0调度", "job_runs", str(row.get("task_key", "")), state],
                source=source,
                external_id=run_id,
            )
            return {
                "recorded": True,
                "skipped": False,
                "memory_id": memory_id,
                "error_code": "",
            }
        except Exception as exc:  # FAIL-OPEN：认知失败不得回滚已成功的 run
            logger.warning(
                "C8 事件互通：认知 record 失败（FAIL-OPEN）: %s: %s", type(exc).__name__, exc
            )
            self._alert(row, exc)
            return {
                "recorded": False,
                "skipped": False,
                "error_code": "memory_record_failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }

    def _alert(self, row: Dict[str, Any], exc: Exception) -> None:
        if self.event is None:
            return
        try:
            self.event.publish(
                "scheduling.memory_record_failed",
                {
                    "run_id": str(row.get("run_id") or row.get("id") or ""),
                    "task_key": str(row.get("task_key", "")),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception:  # FAIL-OPEN：告警失败不影响主流程
            logger.debug("C8 事件互通：告警发布失败", exc_info=True)
