# -*- coding: utf-8 -*-
"""probes.py — 会话内工具调用探针（不改生产代码）

职责（SPEC §5.1）:
  1. JsonlRecorder: 统一证据落盘（out/evidence.jsonl）。
  2. patch_bridge(): monkeypatch `core.dsh_frontend_bridge.call_tool`，
     record 每次 {ts, shell_id, tool, entry, trace_id, ok, latency_ms, error_code}。
     进程退出/显式 unpatch 即还原，不写入生产代码。
  3. mcp_stdio_call(): 拉起 mcp_shells/*/server.py，走 initialize → tools/list →
     tools/call（P2 入口），返回统一信封 + 原始 JSON。

约定:
  - 本模块只读生产代码，不产生副作用（除 patch 期间）。
  - shell_id 解析顺序: in-process（tool 即 shell_id）→ 47 registry tool→shell 映射。
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"
EVALS_DIR = Path(__file__).resolve().parent
OUT_DIR = EVALS_DIR / "out"


# ── 通用工具 ─────────────────────────────────────────────────────────


def gen_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def load_registry(registry_path: Path = DEFAULT_REGISTRY) -> Dict[str, Any]:
    import yaml

    with open(registry_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def tool_to_shell(registry_path: Path = DEFAULT_REGISTRY) -> Dict[str, str]:
    """47 registry → {tool_name: shell_id}。"""
    doc = load_registry(registry_path)
    out: Dict[str, str] = {}
    for spec in doc.get("shells") or []:
        if not isinstance(spec, dict):
            continue
        sid = spec.get("shell_id")
        if not sid:
            continue
        for t in spec.get("tools") or []:
            if isinstance(t, dict) and t.get("name"):
                out[str(t["name"])] = str(sid)
    return out


# ── JSONL 记录器 ─────────────────────────────────────────────────────


class JsonlRecorder:
    """线程内追加写 JSONL；每条自动补 ts。"""

    def __init__(self, path: Optional[Path] = None, *, reset: bool = True):
        self.path = Path(path) if path else OUT_DIR / "evidence.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reset or not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def write(self, record: Dict[str, Any]) -> None:
        rec = {"ts": now_iso(), **record}
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class ProbeSession:
    """一次评测会话：绑定 scenario_id/entry，并记录工具调用。"""

    def __init__(self, recorder: JsonlRecorder, scenario_id: str, entry: str):
        self.recorder = recorder
        self.scenario_id = scenario_id
        self.entry = entry
        self.trace_id = gen_trace_id()
        self.tool_calls: List[Dict[str, Any]] = []

    def record_call(
        self,
        *,
        shell_id: str,
        tool: str,
        ok: bool,
        latency_ms: float,
        error_code: str = "",
        trace_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        call = {
            "shell_id": shell_id,
            "tool": tool,
            "ok": bool(ok),
            "latency_ms": round(latency_ms, 3),
            "error_code": error_code,
            "trace_id": trace_id or self.trace_id,
        }
        if extra:
            call.update(extra)
        self.tool_calls.append(call)
        self.recorder.write(
            {
                "scenario_id": self.scenario_id,
                "entry": self.entry,
                "kind": "tool_call",
                **call,
            }
        )

    def tool_pair_set(self) -> set:
        return {f"{c['shell_id']}:{c['tool']}" for c in self.tool_calls}


# ── bridge 探针（P1 / P1b）──────────────────────────────────────────


def patch_bridge(
    session: ProbeSession,
    *,
    role_override: Optional[str] = None,
) -> Callable[[], None]:
    """monkeypatch dsh_frontend_bridge.call_tool，返回还原函数。

    注意: 仅影响进程内调用；call_handler 内部对全局 call_tool 的引用会命中补丁。
    """
    core_dir = str(REPO_ROOT / "34-前端应用训练系统" / "core")
    if core_dir not in sys.path:
        sys.path.insert(0, core_dir)
    pkg_root = str(REPO_ROOT / "34-前端应用训练系统")
    if pkg_root not in sys.path:
        sys.path.insert(0, pkg_root)

    import core.dsh_frontend_bridge as bridge  # type: ignore

    original = bridge.call_tool
    inprocess = set(getattr(bridge, "IN_PROCESS_HANDLERS", {}) or {})
    tmap = tool_to_shell()

    def _probe_call_tool(role, tool, args=None, *, trace_id=None, bypass_gate=True):
        t0 = time.perf_counter()
        effective_role = role_override or role
        try:
            envelope = original(
                effective_role,
                tool,
                args,
                trace_id=trace_id or session.trace_id,
                bypass_gate=bypass_gate,
            )
        except Exception as exc:  # 兜底：探针不得击穿调用
            session.record_call(
                shell_id=tool if tool in inprocess else tmap.get(tool, "?"),
                tool=tool,
                ok=False,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                error_code=f"probe_exception:{type(exc).__name__}",
                trace_id=trace_id,
            )
            raise
        latency = (time.perf_counter() - t0) * 1000.0
        shell_id = tool if tool in inprocess else tmap.get(tool, "?")
        session.record_call(
            shell_id=shell_id,
            tool=tool,
            ok=bool(envelope.get("ok")),
            latency_ms=latency,
            error_code=str(envelope.get("error_code") or ""),
            trace_id=trace_id or session.trace_id,
            extra={"degraded": bool((envelope.get("meta") or {}).get("degraded"))},
        )
        return envelope

    bridge.call_tool = _probe_call_tool  # type: ignore[assignment]

    def unpatch() -> None:
        bridge.call_tool = original  # type: ignore[assignment]

    return unpatch


# ── P2: MCP stdio 客户端 ────────────────────────────────────────────


class StdioShellClient:
    """最小 MCP stdio 客户端：initialize → tools/list → tools/call。

    每次调用使用独立子进程，避免壳内状态跨场景串扰。
    """

    def __init__(self, server_path: Path, *, cwd: Optional[Path] = None, timeout: float = 60.0):
        self.server_path = Path(server_path)
        self.cwd = Path(cwd) if cwd else REPO_ROOT
        self.timeout = timeout
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()

    # -- 内部 ------------------------------------------------------
    def _request(self, req: Dict[str, Any], proc: subprocess.Popen) -> Dict[str, Any]:
        assert proc.stdin
        proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        try:
            line = self._lines.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError(f"no response for {req.get('method')} in {self.timeout}s") from None
        if line is None:
            raise RuntimeError(f"shell closed stdout for {req.get('method')}")
        return json.loads(line)

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout
            for line in proc.stdout:
                self._lines.put(line)
        except Exception:
            pass
        finally:
            self._lines.put(None)

    def _spawn(self) -> subprocess.Popen:
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", str(REPO_ROOT))
        proc = subprocess.Popen(
            [sys.executable, str(self.server_path)],
            cwd=str(self.cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
        return proc

    @staticmethod
    def _decode(resp: Dict[str, Any]) -> Dict[str, Any]:
        if "error" in resp:
            return {"ok": False, "data": None, "error_code": "rpc_error", "meta": resp["error"]}
        result = resp.get("result") or {}
        content = result.get("content") or []
        text = content[0].get("text") if content else ""
        try:
            envelope = json.loads(text)
        except Exception:
            envelope = {"ok": not result.get("isError", False), "data": text}
        if not isinstance(envelope, dict):
            envelope = {"ok": True, "data": envelope}
        envelope.setdefault("ok", not result.get("isError", False))
        return envelope

    # -- 公共 ------------------------------------------------------
    def list_tools(self) -> List[Dict[str, Any]]:
        proc = self._spawn()
        try:
            self._request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "evals-probe", "version": "0.1"},
                    },
                },
                proc,
            )
            resp = self._request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, proc)
            return ((resp.get("result") or {}).get("tools")) or []
        finally:
            self._close(proc)

    def call(self, tool: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        proc = self._spawn()
        try:
            self._request(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "evals-probe", "version": "0.1"},
                    },
                },
                proc,
            )
            resp = self._request(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": args or {}},
                },
                proc,
            )
            return self._decode(resp)
        finally:
            self._close(proc)

    @staticmethod
    def _close(proc: subprocess.Popen) -> None:
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def mcp_stdio_call(
    server_path: Path,
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    *,
    cwd: Optional[Path] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    return StdioShellClient(server_path, cwd=cwd, timeout=timeout).call(tool, args)


def mcp_stdio_list_tools(
    server_path: Path, *, cwd: Optional[Path] = None, timeout: float = 60.0
) -> List[Dict[str, Any]]:
    return StdioShellClient(server_path, cwd=cwd, timeout=timeout).list_tools()


__all__ = [
    "DEFAULT_REGISTRY",
    "EVALS_DIR",
    "OUT_DIR",
    "JsonlRecorder",
    "ProbeSession",
    "StdioShellClient",
    "gen_trace_id",
    "load_registry",
    "mcp_stdio_call",
    "mcp_stdio_list_tools",
    "now_iso",
    "patch_bridge",
    "tool_to_shell",
]
