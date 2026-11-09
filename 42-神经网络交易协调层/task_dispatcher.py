#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4-1: 计算任务调度器 Dispatcher（SPEC-M3 §1.1）。

职责：计算任务编排（非参数下发、非下单，42"协调而非执行"红线）。

Task schema:
  task_id, trigger: "macro_led"|"micro_led"|"routine",
  symbol, reason, priority: P0|P1|P2,
  requester, targets: [...], ttl_sec, created_at, deadline_at,
  state: queued|running|done|expired|failed

特性：
  - 持久化 42/runtime/dispatch_tasks.jsonl（追加写，可审计）
  - 同一标的同时只允许一个 running 任务（去重合并，新任务继承剩余 TTL）
  - 优先级 P0 > P1 > P2；P0/P1 到达时 P2 让渡
  - P2 饥饿防护：滑动 24h 窗口 P2 时间片 ≥ 60%，低于下限暂停新 P1
  - salience 配额：每源每 4h ≤ 2 次 P1 触发
  - fail-open：调度器故障不抛异常，返回空列表

用法：
  from task_dispatcher import TaskDispatcher
  d = TaskDispatcher()
  task = d.submit(symbol="BTC/USDT", trigger="macro_led", priority="P0", requester="40-cycle")
  queued = d.list_queued()
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

_42_ROOT = os.path.dirname(os.path.abspath(__file__))
_DISPATCH_PATH = os.path.join(_42_ROOT, "runtime", "dispatch_tasks.jsonl")

# 优先级
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
VALID_PRIORITIES = set(PRIORITY_ORDER)
VALID_TRIGGERS = {"macro_led", "micro_led", "routine"}

# P2 饥饿防护（SPEC-M3 §1.1 评审增补）
P2_MIN_TIMESHARE = 0.60  # P2 保底 60% 时间片
P2_WINDOW_HOURS = 24.0  # 滑动 24h 窗口
P2_MIN_SAMPLE = 5  # 任务数不足时不强制 P2 下限（避免小样本误杀）
P2_MEASURE_SEC = 3600.0  # 每个 P2 任务计 1h 时间片（简化计量）

# salience 配额（SPEC-M3 §1.1 评审增补）
SALIENCE_QUOTA = 2  # 每源每 4h ≤ 2 次 P1
SALIENCE_WINDOW_HOURS = 4.0

# 默认 TTL
DEFAULT_TTL_SEC = 300  # P1 任务 5min
P0_TTL_SEC = 600  # P0 龙头任务 10min
P2_TTL_SEC = 1800  # P2 例行 30min


@dataclass
class Task:
    task_id: str
    trigger: str
    symbol: str
    reason: str
    priority: str
    requester: str
    targets: list[str]
    ttl_sec: int
    created_at: str
    deadline_at: str
    state: str = "queued"
    salience_source: str | None = None  # P1 触发源（用于配额）

    def to_dict(self) -> dict:
        return asdict(self)


class TaskDispatcher:
    """计算任务调度器。fail-open：所有方法不抛异常。"""

    def __init__(self, dispatch_path: str | None = None):
        self.path = dispatch_path or _DISPATCH_PATH
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _load_tasks(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        raw: list[dict] = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception:  # noqa: BLE001
            return []
        # 按 task_id 去重，保留最新状态（append-only 更新语义）
        latest: dict[str, dict] = {}
        for t in raw:
            tid = t.get("task_id")
            if tid:
                latest[tid] = t
        return list(latest.values())

    def _append_task(self, task: dict) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(task, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _active_tasks(self, symbol: str) -> list[dict]:
        """该标的当前非终态任务（queued/running）。"""
        now = self._now()
        active = []
        for t in self._load_tasks():
            if t.get("symbol") != symbol:
                continue
            state = t.get("state")
            if state not in ("queued", "running"):
                continue
            deadline = t.get("deadline_at")
            if deadline:
                try:
                    if datetime.fromisoformat(deadline.replace("Z", "+00:00")) < now:
                        continue  # 已过期
                except (ValueError, TypeError):
                    pass
            active.append(t)
        return active

    # ── salience 配额 ──────────────────────────────────────────

    def _salience_count(self, source: str) -> int:
        """该源在 SALIENCE_WINDOW 内的 P1 触发次数。"""
        if not source:
            return 0
        now = self._now()
        window_start = now - timedelta(hours=SALIENCE_WINDOW_HOURS)
        count = 0
        for t in self._load_tasks():
            if t.get("salience_source") != source:
                continue
            if t.get("priority") != "P1":
                continue
            try:
                ts = datetime.fromisoformat(str(t.get("created_at", "")).replace("Z", "+00:00"))
                if ts >= window_start:
                    count += 1
            except (ValueError, TypeError):
                continue
        return count

    def salience_available(self, source: str) -> bool:
        """该源是否还有 P1 配额。"""
        return self._salience_count(source) < SALIENCE_QUOTA

    # ── P2 时间片统计 ─────────────────────────────────────────

    def _p2_timeshare(self) -> float:
        """滑动窗口内 P2 任务时间片占比（简化：P2 任务数 / 总任务数）。"""
        now = self._now()
        window_start = now - timedelta(hours=P2_WINDOW_HOURS)
        total = 0
        p2 = 0
        for t in self._load_tasks():
            try:
                ts = datetime.fromisoformat(str(t.get("created_at", "")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if ts < window_start:
                continue
            total += 1
            if t.get("priority") == "P2":
                p2 += 1
        return (p2 / total) if total > 0 else 1.0

    def p2_yield_allowed(self) -> bool:
        """P2 时间片是否仍在保底之上（决定是否允许新 P1 抢占）。

        任务数 < P2_MIN_SAMPLE 时不强制下限（小样本统计无意义）。
        """
        now = self._now()
        window_start = now - timedelta(hours=P2_WINDOW_HOURS)
        total = 0
        p2 = 0
        for t in self._load_tasks():
            try:
                ts = datetime.fromisoformat(str(t.get("created_at", "")).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if ts < window_start:
                continue
            total += 1
            if t.get("priority") == "P2":
                p2 += 1
        if total < P2_MIN_SAMPLE:
            return True
        return (p2 / total) >= P2_MIN_TIMESHARE

    # ── 提交任务 ──────────────────────────────────────────────

    def submit(
        self,
        symbol: str,
        trigger: str,
        priority: str,
        requester: str,
        reason: str = "",
        targets: list[str] | None = None,
        ttl_sec: int | None = None,
        salience_source: str | None = None,
    ) -> Task | None:
        """提交一个计算任务。fail-open 返回 None。

        去重：同标的已有 queued/running 任务 → 不重复提交，返回已有任务。
        salience 配额：P1 任务若源配额耗尽 → 拒绝。
        P2 让渡：P0/P1 提交时检查 P2 时间片，低于下限则拒绝新 P1（P0 不受限）。
        """
        try:
            if priority not in VALID_PRIORITIES:
                return None
            if trigger not in VALID_TRIGGERS:
                trigger = "routine"

            # 去重：同标的已有活跃任务
            active = self._active_tasks(symbol)
            if active:
                # 返回优先级最高的活跃任务（去重合并）
                active.sort(key=lambda t: PRIORITY_ORDER.get(t.get("priority", "P2"), 9))
                existing = active[0]
                return Task(**{k: existing[k] for k in Task.__dataclass_fields__ if k in existing})

            # salience 配额（仅 P1）
            if (
                priority == "P1"
                and salience_source
                and not self.salience_available(salience_source)
            ):
                return None

            # P2 让渡：新 P1 需检查 P2 时间片
            if priority == "P1" and not self.p2_yield_allowed():
                return None

            now = self._now()
            if ttl_sec is None:
                ttl_sec = {"P0": P0_TTL_SEC, "P1": DEFAULT_TTL_SEC, "P2": P2_TTL_SEC}[priority]
            deadline = now + timedelta(seconds=ttl_sec)

            task = Task(
                task_id=f"task_{uuid.uuid4().hex[:12]}",
                trigger=trigger,
                symbol=symbol,
                reason=reason,
                priority=priority,
                requester=requester,
                targets=targets or [],
                ttl_sec=ttl_sec,
                created_at=now.isoformat(),
                deadline_at=deadline.isoformat(),
                state="queued",
                salience_source=salience_source,
            )
            self._append_task(task.to_dict())
            return task
        except Exception:  # noqa: BLE001
            return None

    # ── 查询 ─────────────────────────────────────────────────

    def list_queued(self, priority: str | None = None) -> list[Task]:
        """列出 queued 状态任务，按优先级排序。"""
        now = self._now()
        result: list[Task] = []
        for t in self._load_tasks():
            if t.get("state") != "queued":
                continue
            if priority and t.get("priority") != priority:
                continue
            deadline = t.get("deadline_at")
            if deadline:
                try:
                    if datetime.fromisoformat(deadline.replace("Z", "+00:00")) < now:
                        continue
                except (ValueError, TypeError):
                    pass
            try:
                result.append(Task(**{k: t[k] for k in Task.__dataclass_fields__ if k in t}))
            except Exception:  # noqa: BLE001
                continue
        result.sort(key=lambda t: PRIORITY_ORDER.get(t.priority, 9))
        return result

    def update_state(self, task_id: str, state: str) -> bool:
        """更新任务状态（通过追加一条同 task_id 的状态记录实现，读取时取最新）。"""
        if state not in ("queued", "running", "done", "expired", "failed"):
            return False
        try:
            for t in self._load_tasks():
                if t.get("task_id") == task_id:
                    updated = dict(t)
                    updated["state"] = state
                    updated["updated_at"] = self._now().isoformat()
                    self._append_task(updated)
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False


if __name__ == "__main__":
    d = TaskDispatcher()
    # 演示：提交一个 P0 龙头任务
    t = d.submit(
        symbol="BTC/USDT",
        trigger="macro_led",
        priority="P0",
        requester="40-cycle",
        reason="F_macro threshold crossed",
        targets=["11-bcrm-tactical", "11-bdsm", "11-washout"],
    )
    print(json.dumps(t.to_dict() if t else {"submitted": False}, ensure_ascii=False, indent=2))
    queued = d.list_queued()
    print(f"queued tasks: {len(queued)}")
