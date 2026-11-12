# -*- coding: utf-8 -*-
"""P0-D3 Worker 拉起器（W1 MVP → W2 恢复与超时）。

定位（PROPOSAL-P0-D3 §4.1/§4.5/§4.6）：
  Router 只写 `dsh_worker_inbox.jsonl`；本模块增量消费 inbox、执行 mandate、
  把结果 append 到 `dsh_worker_receipts.jsonl`，由 Router 下一轮回执消费。

W2 能力：
  - offset 持久化 + 半行不消费 + 文件截断自愈
  - 心跳续租（10s）与租约（30s）；过期 claim 回收后重试
  - 退避重试 5/20/60s ±20% jitter，最多 3 次；**中间重试不写回执**
  - task_timeout（默认 300s，角色可覆盖）+ max_task_duration（30min 硬上限）
  - 失败分类：工具异常/超时/租约丢失 → retryable；未知角色/契约错误 → manual
  - 坏行 FAIL-OPEN；已回执 Ticket 跳过（重放防护）

硬约束：
  - 拉起器**禁止写** `dsh_tickets.jsonl`（SSoT 只归 Router）
  - 写入 Router 的 `failed` 必须是**终态回执**；中间重试只记本地 attempt
  - 主循环仅在无增量时休眠（默认 500ms），不忙轮询（G3）
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import random
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .worker_roles import RolePolicy

_INBOX_REL_PATH = os.path.join("34-前端应用训练系统", "dsh_worker_inbox.jsonl")
_RECEIPTS_REL_PATH = os.path.join("34-前端应用训练系统", "dsh_worker_receipts.jsonl")
_STATE_REL_PATH = os.path.join("34-前端应用训练系统", ".worker_launcher")

_CST = timezone(timedelta(hours=8))
_DEFAULT_BACKOFF = (5.0, 20.0, 60.0)

Executor = Callable[[Dict[str, Any]], Dict[str, Any]]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, _CST).isoformat(timespec="seconds")


def _default_root() -> str:
    # core/ -> 34-.../ -> 仓库根
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class WorkerLauncher:
    """单进程 Worker 拉起器（W2：恢复与超时）。"""

    def __init__(
        self,
        root: Optional[str] = None,
        roles: Optional[Dict[str, Any]] = None,
        executor: Optional[Executor] = None,
        *,
        worker_ids: Optional[Set[str]] = None,
        clock: Callable[[], float] = time.time,
        max_attempts: int = 3,
        backoff: Tuple[float, ...] = _DEFAULT_BACKOFF,
        jitter_ratio: float = 0.2,
        heartbeat_interval: float = 10.0,
        lease_ttl: float = 30.0,
        task_timeout: float = 300.0,
        max_task_duration: float = 1800.0,
        heartbeat_enabled: bool = True,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.root = str(root or _default_root())
        self.inbox_path = os.path.join(self.root, _INBOX_REL_PATH)
        self.receipts_path = os.path.join(self.root, _RECEIPTS_REL_PATH)
        self.state_dir = os.path.join(self.root, _STATE_REL_PATH)
        self.offset_path = os.path.join(self.state_dir, "offset.json")
        self.claims_path = os.path.join(self.state_dir, "claims.json")
        self.roles = roles or {}
        self.policy = RolePolicy(self.roles)
        self.executor = executor
        self.worker_ids = set(worker_ids) if worker_ids is not None else None
        self.clock = clock
        self.max_attempts = max(1, int(max_attempts))
        self.backoff = tuple(float(x) for x in backoff) or _DEFAULT_BACKOFF
        self.jitter_ratio = max(0.0, float(jitter_ratio))
        self.heartbeat_interval = max(0.01, float(heartbeat_interval))
        self.lease_ttl = max(0.02, float(lease_ttl))
        self.task_timeout = max(0.01, float(task_timeout))
        self.max_task_duration = max(0.0, float(max_task_duration))
        self.heartbeat_enabled = bool(heartbeat_enabled)
        self._rng = rng or random.Random()

    # ---------- 主循环 ----------

    def run_once(self, now: Optional[float] = None) -> Dict[str, Any]:
        """消费一次：恢复过期 claim → 纳入新派单 → 执行到期任务。FAIL-OPEN。"""
        stats: Dict[str, Any] = {
            "consumed": 0,
            "skipped": 0,
            "executed": 0,
            "receipts": 0,
            "failed": 0,
            "retried": 0,
            "recovered": 0,
            "timeouts": 0,
            "bad_lines": 0,
            "errors": [],
        }
        ts = float(now if now is not None else self.clock())
        try:
            items, new_offset, bad_lines, head = self._read_new()
        except Exception as exc:  # 读失败 → 本轮不推进 offset
            stats["errors"].append("read_inbox: %s" % exc)
            return stats
        stats["bad_lines"] = bad_lines
        stats["consumed"] = len(items)

        receipted = self._receipted_ids()

        # 新派单：判权 → 违规直接终态回执（不占 claim）
        accepted: List[Dict[str, Any]] = []
        for item in items:
            ticket_id = str(item.get("ticket_id") or "")
            if not ticket_id or ticket_id in receipted:
                stats["skipped"] += 1
                continue
            violation = self._role_violation(item)
            if violation:
                self._emit(
                    item, "failed", "manual", {"reason": "role_violation", "summary": violation}
                )
                stats["receipts"] += 1
                stats["failed"] += 1
                continue
            accepted.append(item)

        # 恢复过期 claim + 入队新派单 + 取到期任务（单次事务）
        try:
            due = self._prepare(accepted, receipted, ts, stats)
        except Exception as exc:
            stats["errors"].append("prepare_claims: %s" % exc)
            return stats

        # 执行
        for entry in due:
            try:
                self._execute(entry, ts, stats)
            except Exception as exc:  # 单任务异常不拖垮守护进程
                stats["errors"].append("execute %s: %s" % (entry.get("ticket_id"), exc))

        try:
            self._save_offset(new_offset, head)
        except Exception as exc:
            stats["errors"].append("save_offset: %s" % exc)
        return stats

    def run_forever(
        self,
        poll_interval: float = 0.5,
        stop: Optional[Any] = None,
        on_pass: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """常驻循环。仅在无增量时休眠，避免忙轮询（G3）。"""
        interval = max(0.05, float(poll_interval))
        while not (stop is not None and getattr(stop, "is_set", lambda: False)()):
            stats = self.run_once()
            if on_pass is not None:
                on_pass(stats)
            idle = stats["consumed"] == 0 and stats["receipts"] == 0 and stats["executed"] == 0
            if idle:
                time.sleep(interval)

    # ---------- claim 状态机 ----------

    def _prepare(
        self,
        accepted: List[Dict[str, Any]],
        receipted: Set[str],
        now: float,
        stats: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        def mutate(data: Dict[str, Any]) -> List[Dict[str, Any]]:
            for tid in list(data.keys()):
                entry = data[tid]
                if tid in receipted:  # 已被别处回执 → 清理
                    data.pop(tid, None)
                    continue
                if entry.get("state") != "running":
                    continue
                if float(entry.get("lease_until") or 0) >= now:
                    continue
                # 心跳丢失 / 进程崩溃：租约过期 → 回收重试
                entry["state"] = "retry_pending"
                entry["lease_until"] = None
                entry["next_retry_at"] = now
                stats["recovered"] += 1

            for item in accepted:
                tid = str(item["ticket_id"])
                if tid in data:
                    stats["skipped"] += 1
                    continue
                data[tid] = {
                    "ticket_id": tid,
                    "assignment": dict(item),
                    "attempt": 0,
                    "state": "pending",
                    "first_started_at": None,
                    "next_retry_at": now,
                    "lease_until": None,
                }

            due: List[Dict[str, Any]] = []
            for entry in data.values():
                if entry.get("state") not in ("pending", "retry_pending"):
                    continue
                if float(entry.get("next_retry_at") or 0) > now:
                    continue
                entry["state"] = "running"
                entry["lease_until"] = now + self.lease_ttl
                due.append(dict(entry))
            return due

        return self._with_claims(mutate)

    def _execute(self, entry: Dict[str, Any], now: float, stats: Dict[str, Any]) -> None:
        item = entry.get("assignment") or {}
        ticket_id = str(entry.get("ticket_id"))
        attempt = int(entry.get("attempt") or 0) + 1
        first_started = entry.get("first_started_at")
        first_started = float(first_started) if first_started else now

        # 30min 硬上限：不再重试，转人工
        if now - first_started > self.max_task_duration:
            self._emit(
                item,
                "failed",
                "manual",
                {"reason": "timeout", "summary": "max_task_duration exceeded"},
            )
            stats["receipts"] += 1
            stats["failed"] += 1
            self._finish(ticket_id, terminal=True, stats=stats)
            return

        stats["executed"] += 1
        heartbeat = self._start_heartbeat(ticket_id)
        try:
            kind, payload = self._run_with_timeout(item, self._role_timeout(item))
        finally:
            heartbeat.stop()

        if kind == "timeout":
            stats["timeouts"] += 1
            self._retry_or_exhaust(
                item,
                ticket_id,
                attempt,
                first_started,
                now,
                "timeout",
                "task exceeded %ss" % self._role_timeout(item),
                stats,
            )
            return
        if kind == "error":
            self._retry_or_exhaust(
                item, ticket_id, attempt, first_started, now, "runtime_error", str(payload), stats
            )
            return

        result = payload if isinstance(payload, dict) else {}
        status = str(result.get("status") or "").lower()
        evidence = result.get("evidence")
        evidence = dict(evidence) if isinstance(evidence, dict) else {}

        if status == "done":
            self._emit(item, "done", None, evidence, attempts=attempt)
            stats["receipts"] += 1
            self._finish(ticket_id, terminal=True, stats=stats)
            return
        if status == "failed":
            failure_class = str(result.get("failure_class") or "manual").lower()
            evidence.setdefault("reason", "runtime_error")
            if failure_class == "retryable":
                self._retry_or_exhaust(
                    item,
                    ticket_id,
                    attempt,
                    first_started,
                    now,
                    evidence["reason"],
                    evidence.get("summary", ""),
                    stats,
                )
                return
            self._emit(item, "failed", "manual", evidence, attempts=attempt)
            stats["receipts"] += 1
            stats["failed"] += 1
            self._finish(ticket_id, terminal=True, stats=stats)
            return

        # 未知 status = 契约错误，不重试
        evidence.setdefault("reason", "runtime_error")
        evidence.setdefault("summary", "executor returned unknown status: %r" % status)
        self._emit(item, "failed", "manual", evidence, attempts=attempt)
        stats["receipts"] += 1
        stats["failed"] += 1
        self._finish(ticket_id, terminal=True, stats=stats)

    def _retry_or_exhaust(
        self,
        item: Dict[str, Any],
        ticket_id: str,
        attempt: int,
        first_started: float,
        now: float,
        reason: str,
        summary: str,
        stats: Dict[str, Any],
    ) -> None:
        if attempt >= self.max_attempts:
            self._emit(
                item,
                "failed",
                "manual",
                {
                    "reason": reason,
                    "summary": (
                        "%s (retry exhausted after %d attempts)" % (summary, attempt)
                    ).strip(),
                },
                attempts=attempt,
            )
            stats["receipts"] += 1
            stats["failed"] += 1
            self._finish(ticket_id, terminal=True, stats=stats)
            return
        next_retry = now + self._backoff_for(attempt)
        stats["retried"] += 1
        self._finish(
            ticket_id,
            terminal=False,
            stats=stats,
            patch={
                "attempt": attempt,
                "state": "retry_pending",
                "lease_until": None,
                "next_retry_at": next_retry,
                "first_started_at": first_started,
            },
        )

    def _backoff_for(self, attempt: int) -> float:
        base = self.backoff[min(max(attempt, 1) - 1, len(self.backoff) - 1)]
        if self.jitter_ratio <= 0:
            return base
        return base * self._rng.uniform(1.0 - self.jitter_ratio, 1.0 + self.jitter_ratio)

    def _finish(
        self,
        ticket_id: str,
        *,
        terminal: bool,
        stats: Dict[str, Any],
        patch: Optional[Dict[str, Any]] = None,
    ) -> None:
        def mutate(data: Dict[str, Any]) -> None:
            if terminal or ticket_id not in data:
                data.pop(ticket_id, None)
                return
            entry = data[ticket_id]
            entry.update(patch or {})

        try:
            self._with_claims(mutate)
        except Exception as exc:
            stats["errors"].append("finish_claim: %s" % exc)

    def _with_claims(self, mutate: Callable[[Dict[str, Any]], Any]) -> Any:
        os.makedirs(self.state_dir, exist_ok=True)
        lock_path = self.claims_path + ".lock"
        with open(lock_path, "a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = self._load_json(self.claims_path, {})
                result = mutate(data)
                self._save_json(self.claims_path, data)
                return result
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    # ---------- 心跳 / 超时 ----------

    def _start_heartbeat(self, ticket_id: str) -> "_Heartbeat":
        return _Heartbeat(self, ticket_id) if self.heartbeat_enabled else _Heartbeat.disabled()

    def _role_timeout(self, item: Dict[str, Any]) -> float:
        cfg = self.roles.get(str(item.get("role") or "")) or {}
        try:
            return float(cfg.get("task_timeout") or self.task_timeout)
        except (TypeError, ValueError):
            return self.task_timeout

    def _run_with_timeout(self, item: Dict[str, Any], timeout: float) -> Tuple[str, Any]:
        """返回 ("ok", result) / ("timeout", None) / ("error", exc)。"""
        box: Dict[str, Any] = {}

        def target() -> None:
            try:
                box["result"] = self.executor(dict(item)) if self.executor else {}
            except Exception as exc:  # 交给主线程归类
                box["error"] = exc

        worker = threading.Thread(target=target, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return "timeout", None
        if "error" in box:
            return "error", box["error"]
        return "ok", box.get("result")

    # ---------- inbox 增量 ----------

    def _load_state(self) -> Dict[str, Any]:
        data = self._load_json(self.offset_path, {})
        return data if isinstance(data, dict) else {}

    def _save_offset(self, offset: int, head: str = "") -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        self._save_json(self.offset_path, {"offset": int(offset), "head": head})

    def _read_new(self):
        """返回 (完整行记录, 新 offset, 坏行数, 头部指纹)；末行无换行则不消费。"""
        state = self._load_state()
        try:
            offset = max(0, int(state.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        if not os.path.exists(self.inbox_path):
            return [], offset, 0, str(state.get("head") or "")
        size = os.path.getsize(self.inbox_path)
        with open(self.inbox_path, "rb") as f:
            head_bytes = f.read(64)
        head = hashlib.sha1(head_bytes).hexdigest() if head_bytes else ""
        stored_head = state.get("head")
        # 文件被截断/轮转/替换 → 从头重读（仅比较 size 会漏掉等长替换）
        if (stored_head is not None and stored_head != head) or size < offset:
            offset = 0
        with open(self.inbox_path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
        if not chunk:
            return [], offset, 0, head

        parts = chunk.split(b"\n")
        leftover = parts.pop()  # 最后一段可能是不完整行
        consumed = len(chunk) - len(leftover)

        items, bad = [], 0
        for raw in parts:
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw.decode("utf-8"))
            except Exception:
                bad += 1
                continue
            if isinstance(rec, dict):
                items.append(rec)
            else:
                bad += 1
        return items, offset + consumed, bad, head

    def _receipted_ids(self) -> Set[str]:
        ids: Set[str] = set()
        try:
            if not os.path.exists(self.receipts_path):
                return ids
            with open(self.receipts_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(rec, dict) and rec.get("ticket_id"):
                        ids.add(str(rec["ticket_id"]))
        except Exception:
            return ids
        return ids

    # ---------- 判权 ----------

    def _role_violation(self, item: Dict[str, Any]) -> Optional[str]:
        worker_id = str(item.get("worker_id") or "")
        if self.worker_ids is not None and worker_id not in self.worker_ids:
            return "worker_id %r not in local roster" % worker_id
        role = str(item.get("role") or "")
        mandate = item.get("mandate") if isinstance(item.get("mandate"), dict) else {}
        requested = item.get("tools") or mandate.get("tools")
        if requested is not None and not isinstance(requested, (list, tuple, set)):
            return "tools must be a list, got %r" % type(requested).__name__
        return self.policy.check(role, requested)

    # ---------- 回执 ----------

    def _emit(
        self,
        item: Dict[str, Any],
        status: str,
        failure_class: Optional[str],
        evidence: Dict[str, Any],
        attempts: int = 1,
    ) -> None:
        self._append_receipt(self._build(item, status, failure_class, evidence, attempts))

    def _build(
        self,
        item: Dict[str, Any],
        status: str,
        failure_class: Optional[str],
        evidence: Dict[str, Any],
        attempts: int = 1,
    ) -> Dict[str, Any]:
        ts = float(self.clock())
        return {
            "ticket_id": str(item.get("ticket_id") or ""),
            "status": status,
            "failure_class": failure_class if status == "failed" else None,
            "evidence": evidence,
            "attempts": attempts,
            "next_retry_at": None,
            "at": _iso(ts),
            "receipt_id": "rc-%s" % uuid.uuid4().hex,
            "worker_id": item.get("worker_id"),
            "trace_id": item.get("trace_id"),
        }

    def _append_receipt(self, receipt: Dict[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self.receipts_path), exist_ok=True)
            with open(self.receipts_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False

    # ---------- JSON 读写 ----------

    @staticmethod
    def _load_json(path: str, default: Any) -> Any:
        try:
            if not os.path.exists(path):
                return default
            with open(path, encoding="utf-8") as f:
                value = json.load(f)
            return value if isinstance(value, type(default)) else default
        except Exception:
            return default

    @staticmethod
    def _save_json(path: str, value: Any) -> bool:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True


class _Heartbeat:
    """心跳续租线程：每 interval 把 running claim 的 lease_until 推后。"""

    def __init__(self, launcher: WorkerLauncher, ticket_id: str) -> None:
        self._launcher = launcher
        self._ticket_id = ticket_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()

    @classmethod
    def disabled(cls) -> "_Heartbeat":
        hb = cls.__new__(cls)
        hb._stop = threading.Event()
        hb._thread = None
        return hb

    def _beat(self) -> None:
        launcher = self._launcher

        def mutate(data: Dict[str, Any]) -> None:
            entry = data.get(self._ticket_id)
            if entry and entry.get("state") == "running":
                entry["lease_until"] = float(launcher.clock()) + launcher.lease_ttl

        while not self._stop.wait(launcher.heartbeat_interval):
            try:
                launcher._with_claims(mutate)
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)


class DshCliExecutor:
    """方案 A 降级执行器：每个 assignment 起一个 `dsh` 子进程。

    仅限 sandbox / 本地开发；生产必须走单运行时多会话（D1 方案 B），
    否则连接数随任务数增长，违背 G2。
    """

    def __init__(
        self, profile: str = "sandbox", dsh_bin: str = "dsh", timeout: float = 300.0
    ) -> None:
        self.profile = profile
        self.dsh_bin = dsh_bin
        self.timeout = float(timeout)

    def __call__(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        mandate = assignment.get("mandate") if isinstance(assignment.get("mandate"), dict) else {}
        goal = str(mandate.get("goal") or assignment.get("external_ref") or "").strip()
        started = time.time()
        try:
            proc = subprocess.run(
                [self.dsh_bin, "--profile", self.profile, goal],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "failure_class": "retryable",
                "evidence": {"reason": "timeout", "summary": "task exceeded %ss" % self.timeout},
            }
        duration_ms = int((time.time() - started) * 1000)
        output = (proc.stdout or "").strip()
        error = (proc.stderr or "").strip()
        if proc.returncode == 0:
            return {
                "status": "done",
                "evidence": {"summary": output[-500:], "duration_ms": duration_ms},
            }
        return {
            "status": "failed",
            "failure_class": "retryable",
            "evidence": {
                "reason": "tool_error",
                "summary": (error or output)[-500:],
                "duration_ms": duration_ms,
            },
        }
