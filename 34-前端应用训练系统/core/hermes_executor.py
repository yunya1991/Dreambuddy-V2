# -*- coding: utf-8 -*-
"""P0-D3B Phase 3: HermesExecutor（外部执行内核接入）。

定位：不替换 Worker 契约，只在 `research` / `engineer` 角色上提供一个可插拔 executor。

硬约束（与 SPEC §5 对齐）：
  - H-1 不写 ticket / receipt / offset；
  - H-2/H-3 不调用写工具、不接交易/live；
  - H-4 工具面只经 47 MCP 壳（本层只做白名单审计）；
  - H-5 未在 53 `external_runtimes` 登记或未启用 → fail-closed；
  - H-7 无 trace / 无预算不执行；
  - H-8 evidence 限长，不落完整思维链。

默认关闭：53 登记的 `hermes.enabled=false` 时，本 executor 一律返回 failed/manual。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

import yaml

from core.worker_roles import WRITE_TOOLS, RolePolicy

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_RUNTIME_REGISTRY = os.path.join(_REPO_ROOT, "53-DSH插件模块", "external_runtimes.yaml")
DEFAULT_STATE_DIR = os.path.join(_REPO_ROOT, "34-前端应用训练系统", ".worker_launcher", "hermes")

MAX_EVIDENCE_BYTES = 32 * 1024
MAX_SUMMARY_CHARS = 2000
DEFAULT_BUDGET = {"max_turns": 12, "max_tokens": 60000, "timeout_s": 600.0}

#: 与云端 `hermes -z PROMPT` 对齐；`{prompt}` 由 transport 替换。
DEFAULT_HERMES_COMMAND = ("hermes", "-z", "{prompt}")

PROMPT_TEMPLATE = (
    "You are the Hermes executor inside a DSH worker ticket.\n"
    "Complete the mandate described by the TASK JSON at the end of this prompt.\n"
    "Hard rules:\n"
    "1. Read-only: never write files, never call write tools, never place or cancel orders.\n"
    "2. Stay inside mandate.tools; never invent tools outside that list.\n"
    "3. Never print secrets, tokens or full chain-of-thought.\n"
    "4. Reply with EXACTLY one JSON object and no other text, shaped as:\n"
    '{"status":"done","evidence":{"summary":"...","tool_calls":[{"name":"..."}],'
    '"artifacts":[]}}\n'
    "If you cannot complete the mandate reply "
    '{"status":"failed","failure_class":"retryable"|"manual",'
    '"evidence":{"summary":"..."}}.\n'
    "TASK JSON:\n%s"
)


def build_task_prompt(task: Dict[str, Any]) -> str:
    """把任务契约压成可直接喂给 `hermes -z` 的单个 prompt。"""
    return PROMPT_TEMPLATE % json.dumps(task, ensure_ascii=False)


def _default_command() -> Sequence[str]:
    raw = os.environ.get("hermes_executor_cmd") or os.environ.get("HERMES_EXECUTOR_CMD")
    if raw:
        return tuple(shlex.split(raw))
    return (os.environ.get("D3_HERMES_BIN") or "hermes", "-z", "{prompt}")


def _failed(failure_class: str, reason: str, summary: str, **extra: Any) -> Dict[str, Any]:
    evidence = {"reason": reason, "summary": str(summary)[:MAX_SUMMARY_CHARS]}
    evidence.update(extra)
    return {"status": "failed", "failure_class": failure_class, "evidence": evidence}


def load_external_runtimes(path: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with open(path or DEFAULT_RUNTIME_REGISTRY, encoding="utf-8") as handle:
            doc = yaml.safe_load(handle) or {}
    except Exception:
        return []
    items = doc.get("external_runtimes") if isinstance(doc, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def runtime_entry(
    runtime_id: str = "hermes", path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    for item in load_external_runtimes(path):
        if str(item.get("id") or "") == runtime_id:
            return item
    return None


class CliHermesTransport:
    """T1：CLI headless 传输。子进程 + 进程组 kill，避免僵尸执行。"""

    def __init__(
        self,
        command: Optional[Sequence[str]] = None,
        *,
        work_dir: Optional[str] = None,
        timeout: float = 600.0,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.command = tuple(command) if command else _default_command()
        self.work_dir = work_dir
        self.timeout = float(timeout)
        self.env = dict(env) if env is not None else None
        self._procs: Dict[str, subprocess.Popen] = {}

    def _export_task(self, task: Dict[str, Any]) -> str:
        directory = self.work_dir or tempfile.mkdtemp(prefix="hermes-task-")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "%s.task.json" % str(task.get("ticket_id") or "task"))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(task, handle, ensure_ascii=False)
        return path

    @staticmethod
    def _parse(stdout: str) -> Optional[Dict[str, Any]]:
        """兼容整段 JSON、```json 围栏、尾部说明文字三种输出形态。"""
        if not stdout or not stdout.strip():
            return None
        stripped = stdout.strip()
        candidates: List[str] = [stripped]
        fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S)
        if fence and fence.group(1).strip():
            candidates.append(fence.group(1).strip())
        start, end = stripped.find("{"), stripped.rfind("}")
        if 0 <= start < end:
            candidates.append(stripped[start : end + 1])
        candidates.extend(
            line
            for line in reversed([item.strip() for item in stripped.splitlines() if item.strip()])
        )
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
        return None

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        ticket_id = str(task.get("ticket_id") or "")
        needs_file = any("{task_file}" in part for part in self.command)
        task_file = self._export_task(task) if needs_file else ""
        prompt = build_task_prompt(task) if any("{prompt}" in part for part in self.command) else ""
        cmd = [
            part.replace("{prompt}", prompt).replace("{task_file}", task_file)
            for part in self.command
        ]
        budget = task.get("budget") if isinstance(task.get("budget"), dict) else {}
        timeout = float(budget.get("timeout_s") or self.timeout)
        started = time.time()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=self.env,
            )
        except Exception as exc:  # noqa: BLE001
            return _failed("retryable", "runtime_error", "spawn failed: %s" % exc)
        self._procs[ticket_id] = proc
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_group(proc)
            return _failed(
                "retryable",
                "timeout",
                "hermes exceeded %ss" % timeout,
                duration_ms=int((time.time() - started) * 1000),
            )
        finally:
            self._procs.pop(ticket_id, None)
        duration_ms = int((time.time() - started) * 1000)
        if proc.returncode != 0:
            return _failed(
                "retryable",
                "runtime_error",
                (stderr or stdout)[-MAX_SUMMARY_CHARS:],
                duration_ms=duration_ms,
            )
        parsed = self._parse(stdout or "")
        if parsed is None:
            return _failed(
                "retryable",
                "contract_error",
                "hermes returned non-JSON output",
                duration_ms=duration_ms,
            )
        parsed.setdefault("evidence", {})
        if isinstance(parsed["evidence"], dict):
            parsed["evidence"].setdefault("duration_ms", duration_ms)
        return parsed

    @staticmethod
    def _kill_group(proc: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def cancel(self, task_id: str) -> None:
        proc = self._procs.get(str(task_id))
        if proc is not None:
            self._kill_group(proc)


class HermesExecutor:
    """按 assignment 执行；失败一律结构化返回，不抛异常。"""

    def __init__(
        self,
        transport: Optional[Any] = None,
        *,
        roles: Optional[Dict[str, Any]] = None,
        runtime_registry: Optional[str] = None,
        state_dir: Optional[str] = None,
        profile: str = "sandbox",
        max_evidence_bytes: int = MAX_EVIDENCE_BYTES,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.transport = transport or CliHermesTransport()
        self.roles = roles or {}
        self.policy = RolePolicy(self.roles)
        self.runtime_registry = runtime_registry or DEFAULT_RUNTIME_REGISTRY
        self.state_dir = state_dir or DEFAULT_STATE_DIR
        self.profile = str(profile or "sandbox")
        self.max_evidence_bytes = int(max_evidence_bytes)
        self._clock = clock or time.time

    # ── 运行登记（H-5/H-6）────────────────────────────────────────────────
    def activation_error(self, role: str) -> Optional[str]:
        entry = runtime_entry("hermes", self.runtime_registry)
        if entry is None:
            return "runtime_not_registered"
        if not bool(entry.get("enabled")):
            return "runtime_disabled"
        allowed_roles = entry.get("allowed_roles") or []
        if role not in {str(item) for item in allowed_roles}:
            return "role_not_allowed"
        profiles = entry.get("permitted_profiles") or []
        if profiles and self.profile not in {str(item) for item in profiles}:
            return "profile_not_permitted"
        return None

    # ── 幂等 session ──────────────────────────────────────────────────────
    def _sessions_path(self) -> str:
        return os.path.join(self.state_dir, "ticket_sessions.json")

    def _load_sessions(self) -> Dict[str, str]:
        try:
            with open(self._sessions_path(), encoding="utf-8") as handle:
                data = json.load(handle)
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_session(self, ticket_id: str, session_id: str) -> None:
        if not ticket_id or not session_id:
            return
        sessions = self._load_sessions()
        sessions[ticket_id] = session_id
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self._sessions_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(sessions, handle, ensure_ascii=False)
            os.replace(tmp, self._sessions_path())
        except Exception:
            pass

    # ── 契约校验 ──────────────────────────────────────────────────────────
    def _contract_error(self, assignment: Dict[str, Any]) -> Optional[str]:
        role = str(assignment.get("role") or "")
        if not role:
            return "role_required"
        violation = self.policy.check(role)
        if violation:
            return violation
        if not str(assignment.get("ticket_id") or ""):
            return "ticket_id_required"
        if not str(assignment.get("trace_id") or ""):
            return "trace_id_required"
        mandate = assignment.get("mandate") if isinstance(assignment.get("mandate"), dict) else {}
        if not str(mandate.get("goal") or "").strip():
            return "mandate.goal_required"
        tools = mandate.get("tools")
        if not isinstance(tools, (list, tuple)) or not tools:
            return "mandate.tools_required"
        violation = self.policy.check(role, tools)
        if violation:
            return violation
        forbidden = sorted({str(t) for t in tools} & WRITE_TOOLS)
        if forbidden:
            return "write tool(s) forbidden: %s" % ",".join(forbidden)
        return None

    # ── evidence 约束（H-8）───────────────────────────────────────────────
    def _cap_evidence(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        data = dict(evidence)
        data["summary"] = str(data.get("summary") or "")[:MAX_SUMMARY_CHARS]
        while len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > self.max_evidence_bytes:
            if len(data["summary"]) > 200:
                data["summary"] = data["summary"][: len(data["summary"]) // 2]
                continue
            if "tool_calls" in data:
                data.pop("tool_calls")
                continue
            if "artifacts" in data:
                data.pop("artifacts")
                continue
            data["summary"] = data["summary"][:200]
            break
        return data

    def _audit_tools(self, role: str, evidence: Dict[str, Any]) -> Optional[str]:
        allowed = self.policy.allowed(role)
        if allowed is None:
            return "role %r not in worker_roles whitelist" % role
        calls = evidence.get("tool_calls")
        if not isinstance(calls, list):
            return None
        used = {
            str(item.get("name")) for item in calls if isinstance(item, dict) and item.get("name")
        }
        extra = sorted(used - allowed)
        if extra:
            return "tool(s) %s not allowed for role %r" % (",".join(extra), role)
        return None

    def __call__(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(assignment, dict):
            return _failed("manual", "contract_error", "assignment must be a mapping")
        role = str(assignment.get("role") or "")
        contract = self._contract_error(assignment)
        if contract:
            return _failed("manual", "contract_error", contract)
        activation = self.activation_error(role)
        if activation:
            return _failed("manual", "runtime_disabled", activation)

        ticket_id = str(assignment.get("ticket_id") or "")
        mandate = dict(assignment.get("mandate") or {})
        budget = dict(DEFAULT_BUDGET)
        if isinstance(mandate.get("budget"), dict):
            budget.update(
                {k: mandate["budget"][k] for k in DEFAULT_BUDGET if k in mandate["budget"]}
            )
        sessions = self._load_sessions()
        task = {
            "ticket_id": ticket_id,
            "role": role,
            "trace_id": str(assignment.get("trace_id") or ""),
            "session_id": sessions.get(ticket_id, ""),
            "mandate": mandate,
            "budget": budget,
            "profile": self.profile,
        }
        started = self._clock()
        try:
            raw = self.transport.execute(task)
        except Exception as exc:  # noqa: BLE001 - E-2
            return _failed("retryable", "runtime_error", "transport error: %s" % exc)
        if not isinstance(raw, dict):
            return _failed("manual", "contract_error", "transport returned non-dict")
        status = str(raw.get("status") or "").lower()
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        if status not in ("done", "failed"):
            return _failed("manual", "contract_error", "unknown status: %r" % status)

        if status == "failed":
            failure_class = str(raw.get("failure_class") or "manual").lower()
            if failure_class not in ("retryable", "manual"):
                failure_class = "manual"
            evidence.setdefault("executor", "hermes")
            evidence.setdefault("trace_id", task["trace_id"])
            evidence.setdefault("duration_ms", int((self._clock() - started) * 1000))
            return {
                "status": "failed",
                "failure_class": failure_class,
                "evidence": self._cap_evidence(evidence),
            }

        audit = self._audit_tools(role, evidence)
        if audit:
            return _failed("manual", "role_violation", audit)
        evidence["executor"] = "hermes"
        evidence.setdefault("trace_id", task["trace_id"])
        evidence.setdefault("duration_ms", int((self._clock() - started) * 1000))
        self._save_session(ticket_id, str(evidence.get("hermes_session_id") or ""))
        return {"status": "done", "evidence": self._cap_evidence(evidence)}


class ExecutorRouter:
    """按 role 路由到不同 executor；未命中或 canary 未通过回落默认。"""

    def __init__(
        self,
        executors: Dict[str, Any],
        *,
        role_executors: Optional[Dict[str, str]] = None,
        default: str = "dsh",
        canary_pct: int = 100,
    ) -> None:
        self.executors = dict(executors)
        self.role_executors = dict(role_executors or {})
        self.default = default
        self.canary_pct = max(0, min(100, int(canary_pct)))

    def __call__(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        role = str((assignment or {}).get("role") or "")
        target = self.role_executors.get(role, self.default)
        if target == "hermes" and not self._canary_pass((assignment or {}).get("ticket_id")):
            target = self.default
        executor = self.executors.get(target) or self.executors.get(self.default)
        if executor is None:
            return _failed("manual", "runtime_error", "no executor for role %r" % role)
        return executor(assignment)

    def _canary_pass(self, ticket_id: Any) -> bool:
        if self.canary_pct >= 100:
            return True
        if self.canary_pct <= 0:
            return False
        digest = hashlib.sha1(str(ticket_id or "").encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % 100
        return bucket < self.canary_pct


def build_executor_router(
    roles: Dict[str, Any],
    executors: Dict[str, Any],
    *,
    env: Optional[Dict[str, str]] = None,
    default: str = "dsh",
) -> Any:
    """按 SPEC §6.3 开关构建路由；关闭时直接返回默认 executor（字节等价）。"""
    values = os.environ if env is None else env
    enabled = str(
        values.get("enable_hermes_executor") or values.get("ENABLE_HERMES_EXECUTOR") or ""
    )
    if enabled.lower() not in ("1", "true", "yes", "on"):
        return executors.get(default)
    allowed_roles = {
        item.strip()
        for item in str(values.get("hermes_executor_roles") or "research,engineer").split(",")
        if item.strip()
    }
    mapping: Dict[str, str] = {}
    for role, config in (roles or {}).items():
        if not isinstance(config, dict):
            continue
        if str(config.get("executor") or "").lower() == "hermes" and role in allowed_roles:
            mapping[role] = "hermes"
    if not mapping or "hermes" not in executors:
        return executors.get(default)
    try:
        canary = int(values.get("hermes_executor_canary_pct") or 0)
    except (TypeError, ValueError):
        canary = 0
    return ExecutorRouter(
        executors,
        role_executors=mapping,
        default=default,
        canary_pct=canary,
    )
