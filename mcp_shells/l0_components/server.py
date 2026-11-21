#!/usr/bin/env python3
"""mcp_shells/l0_components/server.py — 59 域组件的只读 MCP 投影（P1）

把 `59-通用组件管理/components/*/component.yaml` 中标记
`mcp.expose: true` 且 `safety: read` + `output: json` 的动作投影成 MCP tools。

用法（MCP 客户端配置）:
    {"command": "python3", "args": ["mcp_shells/l0_components/server.py"]}

调试:
    python3 mcp_shells/l0_components/server.py --list
    python3 mcp_shells/l0_components/server.py --profile all --list

约束:
  - 只读默认：write 动作需 --allow-write + --principal + 调用参数 confirm=true；
  - 写动作执行后追加审计日志（DREAMBUDDY_AUDIT_LOG，默认 ~/.local/share/dreambuddy/audit/）；
  - 零业务逻辑：仅拼装 argv + 子进程执行，不 import 组件内部代码；
  - 参数 schema 唯一源是 component.yaml 的 actions[].params，未声明参数不投影。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("E_ENV：缺少 PyYAML（pip install pyyaml）", file=sys.stderr)
    raise SystemExit(2) from None

SERVER_NAME = "dreambuddy-components"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL = "2025-06-18"
SHELL_SOURCE = "l0.components.mcp"

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_DIR = REPO_ROOT / "59-通用组件管理" / "components"

_SHARED_DIR = Path(__file__).resolve().parents[1] / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
from envelope_wrap import wrap as _wrap  # noqa: E402

AUDIT_DEFAULT = Path.home() / ".local/share/dreambuddy/audit/components-mcp.jsonl"


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _skill_dir(component: Dict[str, Any]) -> Path:
    return Path(component["_dir"]) / (component.get("skill_dir") or "skill")


def load_components() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for manifest in sorted(COMPONENTS_DIR.glob("*/component.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        data["_dir"] = manifest.parent
        items.append(data)
    return items


def default_tool_name(component: Dict[str, Any], action: Dict[str, Any]) -> str:
    return "{}_{}".format(
        str(component.get("name", "")).replace("-", "_"),
        str(action.get("name", "")).replace("-", "_"),
    )


def _input_schema(action: Dict[str, Any], require_confirm: bool = False) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for param in action.get("params") or []:
        name = param["name"]
        kind = param.get("type", "string")
        prop: Dict[str, Any] = {"type": kind}
        if kind == "array":
            prop["items"] = {"type": "string"}
        if param.get("description"):
            prop["description"] = param["description"]
        if param.get("enum"):
            prop["enum"] = list(param["enum"])
        if "default" in param:
            prop["default"] = param["default"]
        properties[name] = prop
        if param.get("required"):
            required.append(name)
    if require_confirm:
        properties["confirm"] = {
            "type": "boolean",
            "description": "写动作人工授权：必须显式传 true，否则拒绝执行",
        }
        required.append("confirm")
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def build_tools(profile: str = "hot", allow_write: bool = False) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []
    for component in load_components():
        for action in component.get("actions") or []:
            mcp = action.get("mcp") or {}
            if not mcp.get("expose"):
                continue
            is_write = action.get("safety", "read") in {"write", "ui"}
            if action.get("safety") == "irreversible":
                continue
            if is_write and not allow_write:
                continue
            if action.get("output") != "json":
                print(
                    "[l0_components] skip {}.{}: output 必须为 json".format(
                        component.get("name"), action.get("name")
                    ),
                    file=sys.stderr,
                )
                continue
            tier = mcp.get("tier", "extended")
            if profile != "all" and tier != "hot":
                continue
            description = "{}（{}）".format(
                action.get("description") or component.get("summary", ""),
                component.get("name", ""),
            )
            if action.get("when_to_use"):
                description += " 适用：{}".format(action["when_to_use"])
            if action.get("not_for"):
                description += " 不适用：{}".format(action["not_for"])
            tools.append(
                {
                    "name": mcp.get("name") or default_tool_name(component, action),
                    "description": description,
                    "when_to_use": action.get("when_to_use", ""),
                    "not_for": action.get("not_for", ""),
                    "inputSchema": _input_schema(action, require_confirm=is_write),
                    "annotations": {
                        "readOnlyHint": not is_write,
                        "destructiveHint": is_write,
                        "idempotentHint": not is_write,
                        "openWorldHint": True,
                    },
                    "_component": component,
                    "_action": action,
                    "_write": is_write,
                }
            )
    return tools


def find_tool(tools: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for tool in tools:
        if tool["name"] == name:
            return tool
    raise RpcError(-32602, "unknown tool: {}".format(name))


def _stringify(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(_stringify(item) for item in value)
    return str(value)


def build_argv(tool: Dict[str, Any], arguments: Dict[str, Any]) -> List[str]:
    component = tool["_component"]
    action = tool["_action"]
    declared = {p["name"]: p for p in action.get("params") or []}
    unknown = sorted(set(arguments) - set(declared))
    if unknown:
        raise RpcError(-32602, "unknown argument(s): {}".format(", ".join(unknown)))

    argv: List[str] = []
    for param in action.get("params") or []:
        name = param["name"]
        if name in arguments and arguments[name] is not None:
            value = arguments[name]
        elif "default" in param:
            value = param["default"]
        elif param.get("required"):
            raise RpcError(-32602, "missing required argument: {}".format(name))
        else:
            continue

        flag = param.get("flag")
        if not flag:
            argv.append(_stringify(value))
        elif param.get("type") == "boolean":
            if bool(value):
                argv.append(flag)
        else:
            argv.extend([flag, _stringify(value)])

    script = _skill_dir(component) / str(action["script"])
    if not script.is_file():
        raise RpcError(-32603, "script not found: {}".format(script))
    argv = [sys.executable, str(script)] + list(action.get("args") or []) + argv
    if action.get("output") == "json":
        argv.append("--json")
    return argv


def _error_payload(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _audit_write(
    principal: str,
    tool_name: str,
    arguments: Dict[str, Any],
    argv: List[str],
    exit_code: int,
    duration_ms: int,
) -> None:
    path = Path(os.environ.get("DREAMBUDDY_AUDIT_LOG", str(AUDIT_DEFAULT))).expanduser()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "principal": principal,
        "tool": tool_name,
        "arguments": {
            key: value if isinstance(value, (int, float, bool)) else str(value)[:200]
            for key, value in arguments.items()
        },
        "argv": [str(item)[:200] for item in argv[1:]],
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        print("[l0_components] audit write failed: {}".format(exc), file=sys.stderr)


def run_tool(
    tool: Dict[str, Any],
    arguments: Dict[str, Any],
    timeout: int,
    principal: str = "",
) -> Dict[str, Any]:
    is_write = bool(tool.get("_write"))
    if is_write:
        if not principal:
            return _error_payload("E_MANDATE：写动作需要 --principal 或 DREAMBUDDY_PRINCIPAL")
        if arguments.get("confirm") is not True:
            return _error_payload("E_CONFIRM：写动作必须显式传 confirm=true")
        arguments = {key: value for key, value in arguments.items() if key != "confirm"}

    try:
        argv = build_argv(tool, arguments)
    except RpcError as exc:
        return _error_payload(exc.message)

    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(tool["_component"]["_dir"]),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - started) * 1000)
        if is_write:
            _audit_write(principal, tool["name"], arguments, argv, -1, duration_ms)
        return _error_payload("E_TIMEOUT：动作执行超过 {}s".format(timeout))

    duration_ms = int((time.time() - started) * 1000)
    if is_write:
        _audit_write(principal, tool["name"], arguments, argv, proc.returncode, duration_ms)

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    parsed: Optional[Any] = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None

    is_error = proc.returncode != 0
    payload: Any = parsed if parsed is not None else (stdout or stderr or "(empty output)")
    envelope = _wrap(
        payload,
        SHELL_SOURCE,
        degraded=is_error,
        error_code="unavailable" if is_error else "",
        meta={
            "tool": tool["name"],
            "principal": principal,
            "duration_ms": duration_ms,
        },
    )
    if is_error and stderr:
        envelope["meta"]["stderr"] = stderr[-1000:]
    text = (
        json.dumps(envelope, ensure_ascii=False, indent=2) if parsed is not None else str(payload)
    )
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": envelope,
        "isError": is_error,
    }


def _response(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(
    req: Dict[str, Any],
    tools: List[Dict[str, Any]],
    timeout: int,
    principal: str = "",
) -> Optional[Dict[str, Any]]:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method and str(method).startswith("notifications/"):
        return None
    if method == "initialize":
        return _response(
            req_id,
            {
                "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _response(req_id, {})
    if method == "tools/list":
        public = [
            {key: value for key, value in tool.items() if not key.startswith("_")} for tool in tools
        ]
        return _response(req_id, {"tools": public})
    if method == "tools/call":
        try:
            tool = find_tool(tools, str(params.get("name") or ""))
            return _response(
                req_id, run_tool(tool, params.get("arguments") or {}, timeout, principal)
            )
        except RpcError as exc:
            return _error(req_id, exc.code, exc.message)
    return _error(req_id, -32601, "method not found: {}".format(method))


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="59 域组件只读 MCP 投影")
    parser.add_argument("--profile", choices=["hot", "all"], default="hot")
    parser.add_argument("--list", action="store_true", help="打印工具清单后退出")
    parser.add_argument("--timeout", type=int, default=120, help="单次动作超时秒数")
    parser.add_argument(
        "--allow-write", action="store_true", help="投影写动作（仍需 confirm + principal）"
    )
    parser.add_argument(
        "--principal",
        default=os.environ.get("DREAMBUDDY_PRINCIPAL", ""),
        help="写动作调用主体；也可用 DREAMBUDDY_PRINCIPAL",
    )
    args = parser.parse_args(argv)

    tools = build_tools(args.profile, allow_write=args.allow_write)
    if args.list:
        print(
            json.dumps(
                [{k: v for k, v in tool.items() if not k.startswith("_")} for tool in tools],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    _configure_stdio()
    print(
        "[l0_components] {} tools (profile={})".format(len(tools), args.profile),
        file=sys.stderr,
        flush=True,
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            resp = _error(None, -32700, "parse error")
        else:
            try:
                resp = handle(req, tools, args.timeout, args.principal)
            except Exception as exc:  # 兜底：协议层不崩
                resp = _error(req.get("id"), -32603, "internal error: {}".format(exc))
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
