# -*- coding: utf-8 -*-
"""D3 执行器：方案 B（单运行时多会话）。

一个 DSH 进程承载一整批 assignment 的 child session，而不是每个 assignment
拉一个进程（方案 A）。调用链：

    InProcessSessionExecutor.run_batch(items)
        → 写 batch_input.json
        → dsh --profile <p> --patch host.patch.yml   （一个进程）
        → 插件 tools/dsh_session_host 创建 1 个根 agent + K 个 child session
        → 写 batch_output.json，进程退出
        → 读回结果，映射成拉起器既有的 result 契约

结果契约与 `DshCliExecutor` 一致：
    {"status": "done", "evidence": {...}}
    {"status": "failed", "failure_class": "retryable|manual", "evidence": {...}}
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional

_TOOLS_REL = os.path.join("34-前端应用训练系统", "tools")
_HOST_PKG = "dsh-plugin-d3-session-host"
_STUB_PKG = "dsh-plugin-stub-llm"


class InProcessSessionExecutor:
    """把一批 assignment 交给同一个 DSH 运行时并发执行。"""

    def __init__(
        self,
        root: Optional[str] = None,
        *,
        dsh_home: Optional[str] = None,
        profile: str = "sandbox",
        patches: Optional[Iterable[str]] = None,
        dsh_bin: str = "dsh",
        timeout: float = 600.0,
        max_concurrency: int = 8,
        model_provider: Optional[str] = None,
        model_name: Optional[str] = None,
        install_plugins: bool = True,
        popen: Any = subprocess.Popen,
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.root = os.path.abspath(
            root or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
        self.dsh_home = os.path.abspath(
            dsh_home
            or os.path.join(self.root, "1-ARCHITECTURE", "dream-harness-bridge", ".dsh-home")
        )
        self.profile = profile
        self.patches = list(
            patches or [os.path.join(self.root, _TOOLS_REL, "dsh_session_host", "host.patch.yml")]
        )
        self.dsh_bin = dsh_bin
        self.timeout = float(timeout)
        self.max_concurrency = int(max_concurrency)
        self.model_provider = model_provider or os.environ.get("D3_MODEL_PROVIDER")
        self.model_name = model_name or os.environ.get("D3_MODEL_NAME")
        self.install_plugins = install_plugins
        self._popen = popen
        self._env = dict(env or {})
        self.last_host_pid: Optional[int] = None

    # ---------- 对外 ----------

    def run_batch(self, assignments: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """执行一批 assignment，返回 {ticket_id: result}。"""
        items = [self._to_task(a) for a in assignments if str(a.get("ticket_id") or "")]
        if not items:
            return {}
        if self.install_plugins:
            self._install_plugins()

        state_dir = os.path.join(self.root, "34-前端应用训练系统", ".worker_launcher")
        os.makedirs(state_dir, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix="d3host-", dir=state_dir)
        in_path = os.path.join(workdir, "batch_input.json")
        out_path = os.path.join(workdir, "batch_output.json")
        with open(in_path, "w", encoding="utf-8") as handle:
            json.dump(items, handle, ensure_ascii=False)

        env = dict(os.environ)
        env.update(self._env)
        env["DSH_HOME"] = self.dsh_home
        env["D3_BATCH_INPUT"] = in_path
        env["D3_BATCH_OUTPUT"] = out_path
        env["D3_HOST_MAX"] = str(max(1, self.max_concurrency))
        if self.model_provider:
            env["D3_MODEL_PROVIDER"] = self.model_provider
        if self.model_name:
            env["D3_MODEL_NAME"] = self.model_name

        cmd = [self.dsh_bin, "--profile", self.profile]
        for patch in self.patches:
            cmd.extend(["--patch", patch])
        cmd.append("D3-HOST")

        started = time.time()
        try:
            proc = self._popen(
                cmd,
                cwd=self.root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.last_host_pid = getattr(proc, "pid", None)
            try:
                _, stderr = proc.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, stderr = proc.communicate()
                return self._all_failed(
                    items, "timeout", "session host exceeded %ss" % self.timeout
                )

            if not os.path.exists(out_path):
                summary = (stderr or "").strip()[-1500:] or "session host produced no output"
                return self._all_failed(items, "retryable", summary)

            try:
                with open(out_path, encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError) as exc:
                return self._all_failed(items, "retryable", "bad batch output: %s" % exc)

            if "__host_error__" in payload:
                return self._all_failed(items, "retryable", str(payload["__host_error__"]))

            elapsed_ms = int((time.time() - started) * 1000)
            results: Dict[str, Dict[str, Any]] = {}
            for task in items:
                ticket_id = task["ticket_id"]
                result = payload.get(ticket_id)
                if isinstance(result, dict) and result.get("status"):
                    results[ticket_id] = self._normalize(result, elapsed_ms)
                else:
                    results[ticket_id] = {
                        "status": "failed",
                        "failure_class": "retryable",
                        "evidence": {"reason": "tool_error", "summary": "no result for ticket"},
                    }
            return results
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def __call__(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        """兼容拉起器的单任务 executor 接口。"""
        ticket_id = str(assignment.get("ticket_id") or "")
        return self.run_batch([assignment]).get(
            ticket_id,
            {
                "status": "failed",
                "failure_class": "retryable",
                "evidence": {"reason": "tool_error", "summary": "empty assignment"},
            },
        )

    # ---------- 内部 ----------

    @staticmethod
    def _to_task(assignment: Dict[str, Any]) -> Dict[str, Any]:
        mandate = assignment.get("mandate") if isinstance(assignment.get("mandate"), dict) else {}
        goal = mandate.get("goal") or assignment.get("goal") or ""
        task = {
            "ticket_id": str(assignment.get("ticket_id") or ""),
            "role": str(assignment.get("role") or ""),
            "goal": str(goal),
        }
        timeout = assignment.get("task_timeout") or mandate.get("task_timeout")
        if timeout:
            task["timeout_ms"] = int(float(timeout) * 1000)
        for key in ("provider", "model"):
            if assignment.get(key):
                task[key] = assignment[key]
        return task

    @staticmethod
    def _normalize(result: Dict[str, Any], elapsed_ms: int) -> Dict[str, Any]:
        evidence = result.get("evidence")
        evidence = dict(evidence) if isinstance(evidence, dict) else {}
        evidence.setdefault("duration_ms", result.get("duration_ms", elapsed_ms))
        # session host 的观测字段随证据回传，便于对账「一个进程多个会话」。
        for key in ("pid", "session_id"):
            if result.get(key) is not None:
                evidence[key] = result[key]
        normalized: Dict[str, Any] = {"status": result.get("status"), "evidence": evidence}
        if result.get("failure_class"):
            normalized["failure_class"] = result["failure_class"]
        return normalized

    def _install_plugins(self) -> None:
        target = os.path.join(self.dsh_home, "profiles", self.profile, "node_modules")
        os.makedirs(target, exist_ok=True)
        for name, source in (
            (_HOST_PKG, os.path.join(self.root, _TOOLS_REL, "dsh_session_host")),
            (_STUB_PKG, os.path.join(self.root, _TOOLS_REL, "a7_probe", "stub_llm_plugin")),
        ):
            if not os.path.isdir(source):
                continue
            dest = os.path.join(target, name)
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(source, dest)

    @staticmethod
    def _all_failed(
        items: List[Dict[str, Any]], failure_class: str, summary: str
    ) -> Dict[str, Dict[str, Any]]:
        return {
            task["ticket_id"]: {
                "status": "failed",
                "failure_class": failure_class,
                "evidence": {"reason": "tool_error", "summary": summary},
            }
            for task in items
        }
