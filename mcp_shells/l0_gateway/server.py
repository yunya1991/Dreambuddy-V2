#!/usr/bin/env python3
"""mcp_shells/l0_gateway/server.py — L0 角色能力网关（P1）

单条 mcp.json 接入：
    python3 mcp_shells/l0_gateway/server.py --role research

行为：
  - tools/list 精确等于 registry `worker_roles[role].tools`（≤10），
    不是整壳工具面；
  - tools/call 越权工具 → ok=false, error_code=forbidden；
  - 写工具（requires_mandate=true）在 Worker 角色下一律 forbidden（ADR-9/H7）；
  - 内部复用 34-core `ShellHandleManager`（单壳复用 / 健康检查 / 重拉）。

硬约束：
  - 网关不新增工具、不改写信封业务字段；只做角色裁剪 + 壳路由 + 治理元数据；
  - 角色配置非法（未知角色 / 工具未映射 / 含写工具）→ 启动即失败；
  - stdio JSON-RPC 2.0，按需拉起，不常驻。
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_CORE_DIR = _REPO_ROOT / "34-前端应用训练系统"
if str(_CORE_DIR) not in sys.path:
    sys.path.insert(0, str(_CORE_DIR))

from core.shell_handles import ShellHandleManager  # noqa: E402
from core.ssh_shell_launcher import ssh_launcher  # noqa: E402
from core.stdio_shell_launcher import stdio_launcher  # noqa: E402

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import (  # noqa: E402
    SERVER_VERSION,
    load_registry_doc,
    negotiate_protocol_version,
)

GATEWAY_SOURCE = "l0.gateway.mcp"
REGISTRY_DEFAULT = _REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"

_CATALOG_HOT_ONLY_ENV = "REA_CATALOG_HOT_ONLY"
_CATALOG_HOT_BUDGET_BYTES = 8_192
_CATALOG_FAMILY_BUDGET_BYTES = 4_096
_ENGINEER_HOT_TOOLS = frozenset(
    {
        "submit_rea_analyze",
        "poll_rea_analyze",
        "submit_rea_trace",
        "poll_rea_trace",
        "submit_rea_compare",
        "poll_rea_compare",
        "get_rea_snapshot",
        "rea_audit",
        "get_rea_methodology",
        "recall",
    }
)


def _compact_schema(value: Any) -> Any:
    """移除 schema 文档性描述，保留类型、约束、必填项等调用语义。"""
    if isinstance(value, dict):
        return {key: _compact_schema(item) for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [_compact_schema(item) for item in value]
    return value


def _catalog_family(name: str) -> str:
    if name.startswith(("cancel_rea_", "rea_cancel_")):
        return "cancel"
    if name.startswith("rea_"):
        return name[len("rea_") :].split("_", 1)[0] or "other"
    return "other"


def _catalog_response_bytes(req_id: Any, result: Dict[str, Any]) -> int:
    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
    return len(json.dumps(response, ensure_ascii=False).encode("utf-8"))


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _write(resp: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


class L0Gateway:
    """角色能力投影：registry role → 精确工具白名单 + 壳路由。"""

    def __init__(
        self,
        doc: Dict[str, Any],
        role: str,
        manager: Any,
        *,
        server_name: Optional[str] = None,
    ):
        self.doc = doc
        self.role = role
        self.manager = manager
        self.server_name = server_name or f"l0-gateway-{role}"

        roles = doc.get("worker_roles") or {}
        role_spec = roles.get(role)
        if not isinstance(role_spec, dict):
            available = ", ".join(sorted(roles)) or "（无）"
            raise ValueError(f"未知角色 {role!r}；可用角色: {available}")

        self.role_tools = [str(t) for t in (role_spec.get("tools") or [])]
        self.role_shells = [str(s) for s in (role_spec.get("shells") or [])]
        self._shells = {
            s["shell_id"]: s
            for s in (doc.get("shells") or [])
            if isinstance(s, dict) and s.get("shell_id")
        }

        self._tool_to_shell: Dict[str, str] = {}
        self._write_tools: set[str] = set()
        for sid in self.role_shells:
            shell = self._shells.get(sid)
            if shell is None:
                raise ValueError(f"角色 {role!r} 引用的壳未登记: {sid}")
            for tool in shell.get("tools") or []:
                if not isinstance(tool, dict) or not tool.get("name"):
                    continue
                name = str(tool["name"])
                if name in self.role_tools:
                    self._tool_to_shell[name] = sid
                if tool.get("requires_mandate") is True:
                    self._write_tools.add(name)

        unmapped = [t for t in self.role_tools if t not in self._tool_to_shell]
        if unmapped:
            raise ValueError(f"角色 {role!r} 的工具未映射到壳: {unmapped}")

        write_in_role = [t for t in self.role_tools if t in self._write_tools]
        if write_in_role:
            raise ValueError(
                f"角色 {role!r} 含写工具，违反 Worker 只读（ADR-9/H7）: {write_in_role}"
            )

        self._tools: Optional[List[Dict[str, Any]]] = None

    def agent_card(self) -> Dict[str, Any]:
        """轻量 Agent Card（initialize 时随 serverInfo._meta 下发）。"""
        tools = []
        for sid in self.role_shells:
            for tool in self._shells[sid].get("tools") or []:
                if isinstance(tool, dict) and tool.get("name") in self.role_tools:
                    tools.append({"name": tool["name"], "read_only": True})
        return {
            "schema_version": "1.0-agent-card",
            "name": self.server_name,
            "role": self.role,
            "protocol": {"name": "mcp", "transport": "stdio"},
            "capabilities": {
                "tools": tools,
                "tool_count": len(self.role_tools),
                "read_only": True,
            },
        }

    # -- 工具面 -----------------------------------------------------------

    def load_tools(self) -> List[Dict[str, Any]]:
        """按角色白名单组装 tools/list；描述/schema 从各壳实时获取。"""
        if self._tools is not None:
            return self._tools

        tools: List[Dict[str, Any]] = []
        for sid in self.role_shells:
            shell = self._shells[sid]
            role_tools = [
                t
                for t in (shell.get("tools") or [])
                if isinstance(t, dict) and t.get("name") in self.role_tools
            ]
            if not role_tools:
                continue

            actual: Dict[str, Dict[str, Any]] = {}
            handle = None
            try:
                handle = self.manager.get_handle(sid)
            except Exception as exc:
                handle = None
                print(f"[l0-gateway] WARN {sid} 拉起异常: {exc}", file=sys.stderr)
            if handle is None:
                print(
                    f"[l0-gateway] WARN {sid} 无法拉起，tools/list 使用注册表定义降级",
                    file=sys.stderr,
                )
            if handle is not None and hasattr(handle, "shell"):
                try:
                    actual = {
                        t["name"]: t
                        for t in handle.shell.list_tools()
                        if isinstance(t, dict) and t.get("name")
                    }
                except Exception as exc:
                    print(f"[l0-gateway] WARN {sid} tools/list 失败: {exc}", file=sys.stderr)

            for tool in role_tools:
                name = str(tool["name"])
                live = actual.get(name) or {}
                tools.append(
                    {
                        "name": name,
                        "description": live.get("description", ""),
                        "inputSchema": live.get("inputSchema")
                        or {"type": "object", "properties": {}},
                        "annotations": tool.get("annotations") or live.get("annotations") or {},
                    }
                )

            if actual:
                missing = [str(t["name"]) for t in role_tools if t["name"] not in actual]
                if missing:
                    print(f"[l0-gateway] WARN {sid} 未返回工具: {missing}", file=sys.stderr)

        self._tools = tools
        return tools

    def load_catalog(self, params: Dict[str, Any], req_id: Any) -> Dict[str, Any]:
        """engineer 热/冷目录投影；完整工具面仍由 load_tools 保持供调用路由使用。"""
        tools = self.load_tools()
        cold = [t for t in tools if str(t["name"]) not in _ENGINEER_HOT_TOOLS]
        families = sorted({_catalog_family(str(t["name"])) for t in cold})
        requested_family = str(params.get("family") or "").strip()

        if requested_family:
            result = {
                "tools": [t for t in cold if _catalog_family(str(t["name"])) == requested_family],
                "family": requested_family,
                "families": families,
                "trimmed": [],
            }
            return self._fit_catalog(req_id, result, _CATALOG_FAMILY_BUDGET_BYTES)

        projected = []
        for tool in tools:
            name = str(tool["name"])
            if name in _ENGINEER_HOT_TOOLS:
                item = dict(tool)
                item["inputSchema"] = _compact_schema(tool.get("inputSchema") or {})
                projected.append(item)
            else:
                projected.append(
                    {
                        "name": name,
                        "description": tool.get("description", ""),
                        "family": _catalog_family(name),
                    }
                )
        result = {"tools": projected, "families": families, "trimmed": []}
        return self._fit_catalog(req_id, result, _CATALOG_HOT_BUDGET_BYTES)

    @staticmethod
    def _fit_catalog(
        req_id: Any,
        result: Dict[str, Any],
        budget_bytes: int,
    ) -> Dict[str, Any]:
        """从尾部裁剪条目直至整个 JSON-RPC 响应满足预算，并保留 trimmed 留痕。"""
        while result["tools"] and _catalog_response_bytes(req_id, result) > budget_bytes:
            removed = result["tools"].pop()
            result["trimmed"].append(str(removed["name"]))
        return result

    # -- 请求处理 ---------------------------------------------------------

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = req.get("method", "")
        req_id = req.get("id")

        if method == "initialize":
            params = req.get("params") or {}
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": negotiate_protocol_version(requested),
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.server_name,
                        "version": SERVER_VERSION,
                        "_meta": {"agent_card": self.agent_card()},
                    },
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            params = req.get("params") or {}
            if self.role == "engineer" and os.environ.get(_CATALOG_HOT_ONLY_ENV, "1") != "0":
                result = self.load_catalog(params, req_id)
            else:
                result = {"tools": self.load_tools()}
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        if method == "tools/call":
            params = req.get("params") or {}
            name = str(params.get("name", ""))
            arguments = params.get("arguments") or {}
            meta = params.get("_meta") or {}
            trace_id = meta.get("trace_id") if isinstance(meta, dict) else None
            envelope = self._call(name, arguments, trace_id=trace_id)
            text = json.dumps(envelope, ensure_ascii=False)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": not bool(envelope.get("ok", False)),
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _call(
        self,
        name: str,
        arguments: Dict[str, Any],
        *,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if name not in self.role_tools:
            return wrap(
                None,
                GATEWAY_SOURCE,
                degraded=True,
                error_code="forbidden",
                trace_id=trace_id or "",
                meta={
                    "role": self.role,
                    "reason": f"tool {name!r} not in role {self.role!r}",
                },
            )

        if name in self._write_tools:
            return wrap(
                None,
                GATEWAY_SOURCE,
                degraded=True,
                error_code="forbidden",
                trace_id=trace_id or "",
                meta={
                    "role": self.role,
                    "reason": "worker role is read-only (ADR-9/H7)",
                },
            )

        sid = self._tool_to_shell[name]
        handle = None
        try:
            handle = self.manager.get_handle(sid)
        except Exception:
            handle = None
        if handle is None:
            return wrap(
                None,
                GATEWAY_SOURCE,
                degraded=True,
                error_code="unavailable",
                trace_id=trace_id or "",
                meta={"role": self.role, "shell_id": sid, "reason": "shell unavailable"},
            )

        try:
            envelope = handle.call(name, arguments)
        except Exception as exc:
            # HC-6: 传输层失败 → 重拉壳重试一次
            try:
                handle = self.manager.get_handle(sid, force_new=True)
            except Exception:
                handle = None
            if handle is None:
                return wrap(
                    None,
                    GATEWAY_SOURCE,
                    degraded=True,
                    error_code="shell_degraded",
                    trace_id=trace_id or "",
                    meta={"role": self.role, "shell_id": sid, "reason": str(exc)},
                )
            try:
                envelope = handle.call(name, arguments)
            except Exception as retry_exc:
                return wrap(
                    None,
                    GATEWAY_SOURCE,
                    degraded=True,
                    error_code="shell_degraded",
                    trace_id=trace_id or "",
                    meta={
                        "role": self.role,
                        "shell_id": sid,
                        "reason": str(retry_exc),
                        "original": str(exc),
                    },
                )

        if not isinstance(envelope, dict):
            envelope = wrap(envelope, GATEWAY_SOURCE, trace_id=trace_id or "")
        meta = envelope.setdefault("meta", {})
        if isinstance(meta, dict):
            meta.setdefault("gateway_role", self.role)
            meta.setdefault("shell_id", sid)
            if trace_id:
                meta.setdefault("trace_id", trace_id)
        return envelope


def _local_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """本地 stdio 统一用网关自身的解释器，避免 registry 的 `python3`
    在 Windows/多解释器机器上指向错误环境；ssh-stdio 壳在无 ssh_host
    时按本地 stdio 拉起。"""
    out = dict(spec)
    if out.get("transport") == "ssh-stdio":
        out["transport"] = "stdio"
    cmd = str(out.get("shell_cmd") or "")
    parts = cmd.split()
    if "{path}" in cmd and parts and parts[0] in ("python", "python3", "py"):
        out["shell_cmd"] = f"{shlex.quote(sys.executable)} {{path}}"
    return out


def build_manager(
    registry_path: Path,
    *,
    ssh_host: Optional[str] = None,
    call_timeout: float = 30.0,
) -> ShellHandleManager:
    def launcher(spec: Dict[str, Any]) -> Any:
        if spec.get("transport") == "ssh-stdio" and ssh_host:
            return ssh_launcher(spec, ssh_host=ssh_host, call_timeout=call_timeout)
        return stdio_launcher(_local_spec(spec), call_timeout=call_timeout)

    return ShellHandleManager(
        registry_path=str(registry_path),
        launcher=launcher,
        flags={"enable_shell_handles": True},
    )


def run(gateway: L0Gateway) -> None:
    _configure_stdio()
    gateway.load_tools()  # 启动即校验角色工具映射；壳不可用只降级不阻断
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            )
            continue
        if not isinstance(req, dict):
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            )
            continue
        resp = gateway.handle_request(req)
        if resp is not None:
            _write(resp)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="L0 角色能力网关（P1）")
    parser.add_argument("--role", required=True)
    parser.add_argument("--registry", default=str(REGISTRY_DEFAULT))
    parser.add_argument("--ssh-host", default=None)
    parser.add_argument("--call-timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    # 子壳统一 UTF-8 stdio（MCP 协议面），Windows 默认 GBK 会破坏中文信封
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    try:
        doc = load_registry_doc(Path(args.registry))
        manager = build_manager(
            Path(args.registry),
            ssh_host=args.ssh_host,
            call_timeout=args.call_timeout,
        )
        gateway = L0Gateway(doc, args.role, manager)
    except Exception as exc:
        print(f"ERR: {exc}", file=sys.stderr)
        return 2

    try:
        run(gateway)
    finally:
        try:
            manager.close_all()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
