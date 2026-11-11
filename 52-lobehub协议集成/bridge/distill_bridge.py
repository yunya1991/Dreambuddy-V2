#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 3 — 蒸馏桥（distill bridge）。

流向（SPEC §7.4 + R6 + R3，硬约束）：
  3.1 协议层侧产物（outbox.jsonl，append-only）
    → 本桥进程（校验 + R6 quality 映射）
    → L0 cognition MCP 壳（stdio JSON-RPC，record 工具）
    → 35 认知库。

边界：
  - 桥自身禁止任何 DB 直连，只调 cognition 壳；
  - 桥调壳时 env 固定 COGNITIVE_MCP_WRITE_ENABLED=true +
    COGNITIVE_MCP_DEFAULT_PRINCIPAL=orchestrator（R3），仅覆盖写相关 env；
  - 代码层强制工具白名单：仅放行 record/verify（allowlist 断言）。

用法：
  python3 distill_bridge.py --once          # 处理一批后退出（幂等，游标续跑）

仅标准库依赖。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("distill_bridge")

BRIDGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BRIDGE_DIR.parents[1]

DEFAULT_OUTBOX = BRIDGE_DIR / "outbox.jsonl"
DEFAULT_CURSOR = BRIDGE_DIR / ".cursor"

# server 路径与基础 env 同 lobehub_frontend profile（/tmp/lobehub_frontend_profile.json）。
DEFAULT_COMMAND = "/opt/anaconda3/bin/python3"
DEFAULT_ARGS = [
    str(REPO_ROOT / "4-MEMORY" / "9-工具与接口" / "cognitive_mcp_server.py"),
]
BASE_ENV = {
    "PYTHONPATH": str(REPO_ROOT),
    "PYTHONIOENCODING": "utf-8",
}
# R3：桥 = orchestrator 主体，仅覆盖写相关的 3 个 env
# （MODE: local→ssh 解除 D5 本地只读；WRITE_ENABLED 授予写 scope；PRINCIPAL 注入授权主体）。
WRITE_ENV_OVERRIDES = {
    "COGNITIVE_MCP_MODE": "ssh",
    "COGNITIVE_MCP_WRITE_ENABLED": "true",
    "COGNITIVE_MCP_DEFAULT_PRINCIPAL": "orchestrator",
}

# R3 工具白名单：桥只允许调这两个工具（代码层强制断言）。
ALLOWED_TOOLS = frozenset({"record", "verify"})

# R6 quality 映射表（缺失/未知类型拒绝写入，fail-closed）。
R6_QUALITY_MAP = {
    "expertise_canon": "B",
    "expertise_candidate": "C",
    "debate_winner": "B",
    "debate_loser": "D",
    "session_summary": "C",
}

CONTENT_MAX_CHARS = 300
REQUIRED_TAG = "protocol-bridge"
PROTOCOL_VERSION = "2024-11-05"
REQUEST_TIMEOUT_SEC = 30


class BridgeValidationError(Exception):
    """outbox 条目不合规（fail-closed：跳过并记日志）。"""


class BridgeTransportError(Exception):
    """stdio 链路错误（不重试该批，保留游标等待下次）。"""


def validate_entry(entry: Any) -> dict[str, Any]:
    """校验单条 outbox 条目，返回规范化后的 dict；不合规抛 BridgeValidationError。"""
    if not isinstance(entry, dict):
        raise BridgeValidationError("entry_not_dict")
    etype = entry.get("type")
    if etype not in R6_QUALITY_MAP:
        raise BridgeValidationError(f"unknown_type:{etype!r}")
    content = entry.get("content")
    if not isinstance(content, str) or not content.strip():
        raise BridgeValidationError("content_empty")
    if len(content) > CONTENT_MAX_CHARS:
        raise BridgeValidationError(f"content_too_long:{len(content)}>{CONTENT_MAX_CHARS}")
    tags = entry.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list) or REQUIRED_TAG not in tags:
        raise BridgeValidationError("missing_protocol_bridge_tag")
    source_ref = entry.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise BridgeValidationError("missing_source_ref")
    bridge_ts = entry.get("bridge_ts")
    if not isinstance(bridge_ts, str) or not bridge_ts.strip():
        raise BridgeValidationError("missing_bridge_ts")
    return {
        "type": etype,
        "content": content.strip(),
        "tags": [str(t) for t in tags],
        "source_ref": source_ref.strip(),
        "bridge_ts": bridge_ts.strip(),
    }


class StdioMcpShell:
    """cognition MCP 壳的 stdio JSON-RPC 客户端（仅标准库，懒启动）。

    协议流程：initialize → notifications/initialized → tools/call。
    工具白名单（R3）：call_tool 仅放行 ALLOWED_TOOLS，其余直接 AssertionError。
    """

    def __init__(
        self,
        command: str = DEFAULT_COMMAND,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = list(args) if args is not None else list(DEFAULT_ARGS)
        merged = dict(BASE_ENV)
        merged.update(WRITE_ENV_OVERRIDES)
        if env:
            merged.update(env)
        self._env = merged
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 1

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        full_env = dict(os.environ)
        full_env.update(self._env)
        self._proc = subprocess.Popen(
            [self._command, *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=full_env,
        )
        self._handshake()

    def _handshake(self) -> None:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "distill-bridge", "version": "0.1.0"},
            },
        )
        if not isinstance(result, dict) or not result.get("serverInfo", {}).get("name"):
            raise BridgeTransportError("mcp_initialize_invalid_response")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _read_response(self, rid: int) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            # 顺序批处理：readline 阻塞读，跳过非 JSON 行与无关消息直到命中本请求 id
            line = self._proc.stdout.readline()
            if not line:
                raise BridgeTransportError("mcp_process_eof")
            line = line.strip()
            if not line.startswith("{"):
                continue  # 忽略非 JSON 警告行
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != rid:
                continue  # 忽略服务端 notification / 其他响应
            if "error" in msg and msg["error"]:
                raise BridgeTransportError(f"mcp_rpc_error:{msg['error'].get('message')}")
            return msg.get("result") or {}

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        rid = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        return self._read_response(rid)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调壳工具。R3 白名单断言：仅 record/verify 放行。"""
        assert name in ALLOWED_TOOLS, f"tool_not_allowed:{name!r} (R3 allowlist=record/verify)"
        self._ensure_started()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            text = "".join(
                c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)
            )
            raise BridgeTransportError(f"mcp_tool_error:{text[:200]}")
        return result

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def __enter__(self) -> "StdioMcpShell":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def build_record_arguments(entry: dict[str, Any]) -> dict[str, Any]:
    """R6 映射 + 必填字段 → cognition record 工具参数。"""
    quality = R6_QUALITY_MAP[entry["type"]]
    return {
        "content": entry["content"],
        "quality_level": quality,
        "tags": ",".join(entry["tags"]),
        "source": "protocol-bridge",
        "external_id": f"bridge:{entry['source_ref']}",
    }


def _read_cursor(cursor_path: Path) -> int:
    try:
        return max(0, int(cursor_path.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        return 0


def _write_cursor(cursor_path: Path, line_no: int) -> None:
    cursor_path.write_text(f"{line_no}\n", encoding="utf-8")


def process_outbox(
    outbox_path: Path,
    cursor_path: Path,
    shell_factory: Callable[[], Any] = StdioMcpShell,
) -> dict[str, int]:
    """处理 outbox 一批（从游标之后开始），返回统计。幂等：游标外行不重写。

    - 校验失败（fail-closed）：跳过该行、记日志、游标照常推进（毒丸不阻塞队列）；
    - 传输错误：中止本批，游标停在最后成功行，下次重跑续传。
    """
    stats = {"processed": 0, "written": 0, "skipped": 0, "errors": 0}
    if not outbox_path.exists():
        logger.info("outbox 不存在，无待处理条目: %s", outbox_path)
        return stats

    cursor = _read_cursor(cursor_path)
    shell = None
    try:
        with outbox_path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                if line_no <= cursor:
                    continue
                stats["processed"] += 1
                raw = raw.strip()
                if not raw:
                    _write_cursor(cursor_path, line_no)
                    continue
                try:
                    entry = validate_entry(json.loads(raw))
                except (json.JSONDecodeError, BridgeValidationError) as e:
                    stats["skipped"] += 1
                    logger.warning("跳过不合规条目 line=%d: %s", line_no, e)
                    _write_cursor(cursor_path, line_no)
                    continue
                if shell is None:
                    shell = shell_factory()
                try:
                    shell.call_tool("record", build_record_arguments(entry))
                except (BridgeTransportError, AssertionError) as e:
                    stats["errors"] += 1
                    logger.error("写壳失败 line=%d（游标停在 %d）: %s", line_no, line_no - 1, e)
                    break  # 不推进游标，下次重跑续传
                stats["written"] += 1
                _write_cursor(cursor_path, line_no)
                logger.info(
                    "已蒸馏 line=%d type=%s quality=%s source_ref=%s",
                    line_no,
                    entry["type"],
                    R6_QUALITY_MAP[entry["type"]],
                    entry["source_ref"],
                )
    finally:
        if shell is not None and hasattr(shell, "close"):
            shell.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="52 Phase 3 蒸馏桥：outbox → cognition record")
    parser.add_argument("--once", action="store_true", help="处理一批后退出（当前唯一模式）")
    parser.add_argument(
        "--outbox",
        type=Path,
        default=Path(os.environ.get("BRIDGE_OUTBOX_PATH", str(DEFAULT_OUTBOX))),
    )
    parser.add_argument("--cursor", type=Path, default=DEFAULT_CURSOR)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    stats = process_outbox(args.outbox, args.cursor)
    logger.info("批次完成: %s", stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
