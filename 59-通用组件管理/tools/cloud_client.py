#!/usr/bin/env python3
"""51/P5-2 云端只读出站客户端：JSON-RPC over HTTP MCP。

边界:
  - 只调用 `tools/list` 与只读 `tools/call`；写工具不进入白名单；
  - 令牌与 principal 只从环境读取，审计不落令牌；
  - 网关约定见 mcp_shells/l0_components/http_server.py（Bearer + X-Principal）。

用法:
    export DREAMBUDDY_CLOUD_BASE=http://127.0.0.1:8765/mcp
    export DREAMBUDDY_CLOUD_TOKEN=... DREAMBUDDY_CLOUD_PRINCIPAL=dreambuddy-cli
    python3 tools/cloud_client.py status
    python3 tools/cloud_client.py tools --refresh
    python3 tools/cloud_client.py call market_data_macro --args '{"series":"DGS10"}'
    python3 tools/cloud_client.py audit --tail 5
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_TIMEOUT = 30
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "dreambuddy-cli", "version": "1.0"}


class CloudError(RuntimeError):
    """统一的云端错误：code ∈ E_CLOUD_AUTH / E_CLOUD_DENIED / E_CLOUD_UNAVAILABLE / E_UNSUPPORTED。"""

    def __init__(self, code: str, message: str, status: Optional[int] = None):
        super().__init__("{}：{}".format(code, message))
        self.code = code
        self.status = status


def _home_file(name: str, env: str) -> Path:
    override = os.environ.get(env, "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".local/share/dreambuddy" / name


def cache_path() -> Path:
    return _home_file("cloud_tools.json", "DREAMBUDDY_CLOUD_CACHE")


def audit_path() -> Path:
    return _home_file("cloud_calls.jsonl", "DREAMBUDDY_CLOUD_AUDIT")


CLOUD_KEYS = (
    "DREAMBUDDY_CLOUD_BASE",
    "DREAMBUDDY_CLOUD_TOKEN",
    "DREAMBUDDY_CLOUD_TOKEN_FILE",
    "DREAMBUDDY_CLOUD_PRINCIPAL",
    "DREAMBUDDY_CLOUD_TIMEOUT",
    "DREAMBUDDY_CLOUD_CA",
    "DREAMBUDDY_CLOUD_SIGNING_KEY",
    "DREAMBUDDY_CLOUD_SIGNING_KEY_FILE",
)


def env_file_path() -> Path:
    override = os.environ.get("DREAMBUDDY_CLOUD_ENV", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".local/share/dreambuddy/cloud.env"


def load_env_file() -> None:
    """把本地 cloud.env 并入进程环境；已存在的环境变量优先，不覆盖。"""
    path = env_file_path()
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in CLOUD_KEYS:
            os.environ.setdefault(key, value.strip().strip("\"'"))


def signing_key() -> str:
    key = os.environ.get("DREAMBUDDY_CLOUD_SIGNING_KEY", "").strip()
    if key:
        return key
    key_file = os.environ.get("DREAMBUDDY_CLOUD_SIGNING_KEY_FILE", "").strip()
    if key_file:
        path = Path(os.path.expanduser(key_file))
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return ""


def config() -> Dict[str, Any]:
    load_env_file()
    base = os.environ.get("DREAMBUDDY_CLOUD_BASE", "").strip()
    token = os.environ.get("DREAMBUDDY_CLOUD_TOKEN", "").strip()
    token_file = os.environ.get("DREAMBUDDY_CLOUD_TOKEN_FILE", "").strip()
    if not token and token_file:
        path = Path(os.path.expanduser(token_file))
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
    principal = os.environ.get("DREAMBUDDY_CLOUD_PRINCIPAL", "").strip()
    try:
        timeout = int(os.environ.get("DREAMBUDDY_CLOUD_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    return {
        "base": base,
        "token": token,
        "token_configured": bool(token),
        "principal": principal,
        "timeout": timeout,
        "ca": os.environ.get("DREAMBUDDY_CLOUD_CA", "").strip(),
        "signing_key": signing_key(),
        "cache": str(cache_path()),
        "audit": str(audit_path()),
        "complete": bool(base and token and principal),
    }


def endpoint_url(base: str) -> str:
    base = base.rstrip("/")
    path = base.split("://", 1)[-1]
    if "/" not in path:
        return base + "/mcp"
    return base


def _post(
    payload: Dict[str, Any], conf: Dict[str, Any], extra_headers: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, Any]]:
    url = endpoint_url(conf["base"])
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": "Bearer {}".format(conf.get("token", "")),
            "X-Principal": conf["principal"],
            "User-Agent": "dreambuddy-cloud-client/1.0",
            **(extra_headers or {}),
        },
    )
    try:
        context = (
            ssl.create_default_context(cafile=conf["ca"])
            if conf.get("ca")
            else ssl.create_default_context()
        )
        with urllib.request.urlopen(request, timeout=conf["timeout"], context=context) as response:
            raw = response.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise CloudError("E_CLOUD_AUTH", "Bearer token 缺失或错误", exc.code) from exc
        if exc.code == 403:
            detail = exc.read(200).decode("utf-8", "replace")
            raise CloudError(
                "E_CLOUD_DENIED", "principal 无权调用（{}）".format(detail), exc.code
            ) from exc
        if exc.code >= 500:
            raise CloudError(
                "E_CLOUD_UNAVAILABLE", "网关 {} 错误".format(exc.code), exc.code
            ) from exc
        raise CloudError("E_CLOUD_UNAVAILABLE", "HTTP {}".format(exc.code), exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CloudError("E_CLOUD_UNAVAILABLE", "连接失败（{}）".format(exc)) from exc
    except json.JSONDecodeError as exc:
        raise CloudError("E_CLOUD_UNAVAILABLE", "响应不是合法 JSON") from exc


def _require_config() -> Dict[str, Any]:
    conf = config()
    if not conf["base"]:
        raise CloudError("E_CLOUD_AUTH", "未配置 DREAMBUDDY_CLOUD_BASE")
    if not conf["token_configured"]:
        raise CloudError("E_CLOUD_AUTH", "未配置 DREAMBUDDY_CLOUD_TOKEN / _TOKEN_FILE")
    if not conf["principal"]:
        raise CloudError("E_CLOUD_AUTH", "未配置 DREAMBUDDY_CLOUD_PRINCIPAL")
    return conf


def rpc(method: str, params: Optional[Dict[str, Any]] = None, request_id: int = 1) -> Any:
    conf = _require_config()
    response = _post(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, conf
    )
    if response is None:
        return None
    if "error" in response:
        error = response["error"] or {}
        code = error.get("code")
        message = str(error.get("message") or "")
        if code == -32601:
            raise CloudError("E_UNSUPPORTED", message or "云端未实现 {}".format(method))
        raise CloudError("E_CLOUD_UNAVAILABLE", "JSON-RPC {}：{}".format(code, message))
    return response.get("result")


def initialize() -> Dict[str, Any]:
    result = rpc(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        },
    )
    try:
        rpc("notifications/initialized", {}, request_id=0)
    except CloudError:
        pass
    return result or {}


def is_read_only(tool: Dict[str, Any]) -> bool:
    annotations = tool.get("annotations") or {}
    if annotations.get("readOnlyHint") is False:
        return False
    if annotations.get("destructiveHint") is True:
        return False
    return True


def _write_cache(tools: List[Dict[str, Any]], server: Dict[str, Any]) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base": config()["base"],
        "server": server,
        "tools": tools,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_cache() -> Dict[str, Any]:
    path = cache_path()
    if not path.is_file():
        return {"tools": [], "server": {}, "fetched_at": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"tools": [], "server": {}, "fetched_at": ""}
    return payload if isinstance(payload, dict) else {"tools": [], "server": {}, "fetched_at": ""}


def fetch_tools() -> List[Dict[str, Any]]:
    server = initialize()
    result = rpc("tools/list", {}, request_id=2) or {}
    tools = []
    for tool in result.get("tools") or []:
        entry = dict(tool)
        entry["write"] = not is_read_only(tool)
        tools.append(entry)
    _write_cache(tools, server)
    return tools


def tools(cache_only: bool = False, read_only: bool = True) -> List[Dict[str, Any]]:
    cached = read_cache()
    items = list(cached.get("tools") or [])
    if not items and not cache_only:
        try:
            items = fetch_tools()
        except CloudError:
            items = []
    return [item for item in items if not item.get("write")] if read_only else items


def _audit(entry: Dict[str, Any]) -> None:
    path = audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def call(tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    started = time.time()
    conf = config()
    entry: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": tool,
        "principal": conf["principal"],
        "args_sha256": hashlib.sha256(
            json.dumps(arguments or {}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16],
    }
    allowed = {item["name"] for item in tools()}
    if tool not in allowed:
        entry.update(
            ok=False, error="E_CLOUD_DENIED", latency_ms=int((time.time() - started) * 1000)
        )
        _audit(entry)
        raise CloudError(
            "E_CLOUD_DENIED", "{} 不在云端只读白名单（先 cloud tools --refresh）".format(tool)
        )
    try:
        result = rpc("tools/call", {"name": tool, "arguments": arguments or {}}, request_id=3) or {}
    except CloudError as exc:
        entry.update(ok=False, error=exc.code, latency_ms=int((time.time() - started) * 1000))
        _audit(entry)
        raise
    if result.get("isError"):
        message = _text_content(result) or "工具执行失败"
        entry.update(ok=False, error="E_TOOL", latency_ms=int((time.time() - started) * 1000))
        _audit(entry)
        raise CloudError("E_CLOUD_UNAVAILABLE", message)
    entry.update(ok=True, latency_ms=int((time.time() - started) * 1000))
    _audit(entry)
    return _decode_result(result)


def args_hash(arguments: Optional[Dict[str, Any]]) -> str:
    payload = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan_signature(signing_key: str, plan_id: str, tool: str, digest: str) -> str:
    message = "{}\n{}\n{}".format(plan_id, tool, digest).encode("utf-8")
    return hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def call_write(
    tool: str, arguments: Optional[Dict[str, Any]], plan_id: str, reason: str = ""
) -> Dict[str, Any]:
    conf = _require_config()
    if not conf.get("signing_key"):
        raise CloudError("E_CLOUD_AUTH", "未配置 DREAMBUDDY_CLOUD_SIGNING_KEY(_FILE)")
    entry: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tool": tool,
        "principal": conf["principal"],
        "plan_id": plan_id,
        "args_sha256": args_hash(arguments)[:16],
    }
    registered = {item["name"]: item for item in tools(read_only=False)}
    item = registered.get(tool)
    if not item or not item.get("write"):
        entry.update(ok=False, error="E_CLOUD_DENIED")
        _audit(entry)
        raise CloudError("E_CLOUD_DENIED", "{} 不是云端已登记写工具".format(tool))
    digest = args_hash(arguments)
    headers = {
        "X-Plan-Id": plan_id,
        "X-Args-Sha256": digest,
        "X-Plan-Signature": plan_signature(conf["signing_key"], plan_id, tool, digest),
    }
    started = time.time()
    try:
        result = (
            _post(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments or {}},
                },
                conf,
                extra_headers=headers,
            )
            or {}
        )
    except CloudError as exc:
        entry.update(ok=False, error=exc.code, latency_ms=int((time.time() - started) * 1000))
        _audit(entry)
        raise
    if "error" in result or result.get("isError"):
        message = (result.get("error") or {}).get("message") or _text_content(result)
        entry.update(ok=False, error="E_TOOL", latency_ms=int((time.time() - started) * 1000))
        _audit(entry)
        raise CloudError("E_CLOUD_UNAVAILABLE", message or "云端写执行失败")
    entry.update(ok=True, latency_ms=int((time.time() - started) * 1000))
    _audit(entry)
    payload = _decode_result(result.get("result") or result)
    payload.setdefault("_meta", {})["plan_id"] = plan_id
    return payload


def _text_content(result: Dict[str, Any]) -> str:
    for item in result.get("content") or []:
        if item.get("type") == "text":
            return str(item.get("text") or "")
    return ""


def _decode_result(result: Dict[str, Any]) -> Dict[str, Any]:
    text = _text_content(result)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"ok": True, "data": text}
    if isinstance(payload, dict):
        payload.setdefault("_meta", {})["route"] = "cloud"
        return payload
    return {"ok": True, "data": payload, "_meta": {"route": "cloud"}}


def ca_path() -> Path:
    configured = os.environ.get("DREAMBUDDY_CLOUD_CA", "").strip()
    if configured:
        return Path(os.path.expanduser(configured))
    return Path.home() / ".local/share/dreambuddy/cloud-ca.pem"


def fetch_cert_pem(host: str, port: int = 443) -> str:
    """抓取服务端证书用于固定 CA；仅用于自建端点轮换后重新钉扎。"""
    context = ssl._create_unverified_context()
    with socket.create_connection((host, port), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return ssl.DER_cert_to_PEM_cert(tls.getpeercert(binary_form=True))


def save_ca(pem: str, out: Optional[Path] = None) -> Path:
    path = out or ca_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pem, encoding="utf-8")
    path.chmod(0o600)
    return path


def ca_update(host: str = "", out: Optional[Path] = None) -> Dict[str, Any]:
    conf = config()
    target = host or conf["base"].split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if not target:
        raise CloudError("E_CLOUD_AUTH", "无法推断证书主机，请传 --host")
    pem = fetch_cert_pem(target)
    path = save_ca(pem, out)
    return {
        "ok": True,
        "host": target,
        "path": str(path),
        "sha256": hashlib.sha256(pem.encode("utf-8")).hexdigest()[:16],
    }


def status_report() -> Dict[str, Any]:
    conf = config()
    cached = read_cache()
    return {
        "ok": conf["complete"],
        "base": conf["base"] or "未配置",
        "token": "已配置" if conf["token_configured"] else "未配置",
        "principal": conf["principal"] or "未配置",
        "signing_key": "已配置" if conf.get("signing_key") else "未配置",
        "cached_tools": len(cached.get("tools") or []),
        "fetched_at": cached.get("fetched_at") or "",
        "cache": conf["cache"],
        "audit": conf["audit"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="云端只读出站客户端（HTTP MCP）")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="配置与缓存状态（不联网）")
    p_tools = sub.add_parser("tools", help="列出云端只读工具")
    p_tools.add_argument("--refresh", action="store_true")
    p_tools.add_argument("--json", action="store_true")
    p_call = sub.add_parser("call", help="调用云端只读工具")
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}")
    p_write = sub.add_parser("write", help="为云端写工具创建待审批计划")
    p_write.add_argument("tool")
    p_write.add_argument("--args", default="{}")
    p_write.add_argument("--ttl", type=int, default=900)
    p_write.add_argument("--principal", default="")
    p_write.add_argument(
        "--confirm", action="store_true", help="注入 confirm=true（组件写动作必需）"
    )
    p_audit = sub.add_parser("audit", help="查看调用审计")
    p_audit.add_argument("--tail", type=int, default=10)
    p_ca = sub.add_parser("ca", help="证书固定（自签端点轮换后重新钉扎）")
    p_ca.add_argument("action", choices=["update"])
    p_ca.add_argument("--host", default="")
    p_ca.add_argument("--out", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "tools":
            items = fetch_tools() if args.refresh else tools(read_only=False)
            if args.json:
                print(json.dumps(items, ensure_ascii=False, indent=2))
            else:
                for item in items:
                    mark = "write" if item.get("write") else "read"
                    print(
                        "{:<32} {:<6} {}".format(
                            item.get("name", ""), mark, (item.get("description") or "")[:60]
                        )
                    )
                print("合计 {} 个工具（写工具需 plan/approve）".format(len(items)))
            return 0
        if args.cmd == "write":
            import plan as plan_mod

            try:
                payload_args = json.loads(args.args)
            except json.JSONDecodeError:
                print("E_INPUT：--args 不是合法 JSON", file=sys.stderr)
                return 2
            if not isinstance(payload_args, dict):
                print("E_INPUT：--args 必须是 JSON 对象", file=sys.stderr)
                return 2
            if not payload_args.get("confirm"):
                if args.confirm:
                    payload_args["confirm"] = True
                else:
                    print(
                        "E_CONFIRM：组件写动作需要 confirm=true；加 --confirm 自动注入",
                        file=sys.stderr,
                    )
                    return 2
            serialized = json.dumps(payload_args, ensure_ascii=False, sort_keys=True)
            principal = args.principal or os.environ.get("DREAMBUDDY_PRINCIPAL", "local-user")
            created = plan_mod.create(
                "cloud",
                args.tool,
                [serialized],
                principal=principal,
                endpoint="cloud",
                ttl=args.ttl,
                risk="write",
            )
            print(
                "已创建写计划 {}（cloud.{}，{} 秒内有效）；审批后执行：dreambuddy apply {} --allow-write".format(
                    created["plan_id"], args.tool, args.ttl, created["plan_id"]
                )
            )
            return 0
        if args.cmd == "call":
            payload = call(args.tool, json.loads(args.args))
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if payload.get("ok", True) else 1
        if args.cmd == "ca":
            report = ca_update(args.host, args.out)
            print(
                "已固定 {} 证书 → {}（sha256:{}）".format(
                    report["host"], report["path"], report["sha256"]
                )
            )
            return 0
        if args.cmd == "audit":
            path = audit_path()
            if not path.is_file():
                print("暂无审计（{}）".format(path))
                return 0
            lines = path.read_text(encoding="utf-8").splitlines()[-max(args.tail, 1) :]
            print("\n".join(lines))
            return 0
    except CloudError as exc:
        print(str(exc), file=sys.stderr)
        return {"E_CLOUD_AUTH": 2, "E_CLOUD_DENIED": 3}.get(exc.code, 1)
    except json.JSONDecodeError:
        print("E_INPUT：--args 不是合法 JSON", file=sys.stderr)
        return 2

    report = status_report()
    for key, value in report.items():
        print("{}: {}".format(key, value))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
