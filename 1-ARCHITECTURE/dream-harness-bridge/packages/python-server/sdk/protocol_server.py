"""F-01: IPC 契约版本化 — Python 侧 Protocol Server SDK

职责:
1. 构建 IPC 响应（自动注入 schema_version）
2. 解析 IPC 请求（验证 schema_version）
3. 版本握手响应
4. semver 兼容性检查

来源: SPEC v0.3 七补.1 F-01
调研: A3 契约式设计 + A6 跨语言通信
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


CURRENT_SCHEMA_VERSION = "1.0.0"


class ProtocolHandshakeError(Exception):
    """版本握手失败"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


@dataclass
class IPCRequest:
    schema_version: str
    message_type: str  # "request" | "handshake_request"
    method: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@dataclass
class IPCResponse:
    schema_version: str
    message_type: str  # "response" | "handshake_response"
    ok: bool = True
    result: Optional[Any] = None
    error: Optional[dict[str, str]] = None
    constraint_passed: Optional[bool] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": self.schema_version,
            "message_type": self.message_type,
            "ok": self.ok,
            "id": self.id,
            "timestamp": self.timestamp,
        }
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
        if self.constraint_passed is not None:
            d["constraint_passed"] = self.constraint_passed
        return d


class ProtocolServer:
    """Python 侧 IPC 协议 server SDK"""

    def __init__(self, version: str = CURRENT_SCHEMA_VERSION):
        self.server_version = version

    def build_response(
        self,
        ok: bool,
        result: Any,
        opts: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """构建 IPC 响应（自动注入 schema_version）"""
        response = IPCResponse(
            schema_version=self.server_version,
            message_type="response",
            ok=ok,
            result=result if ok else None,
            error=result if not ok and isinstance(result, dict) else None,
            constraint_passed=opts.get("constraint_passed") if opts else None,
            id=opts.get("id", str(uuid.uuid4())) if opts else str(uuid.uuid4()),
        )
        return response.to_dict()

    def build_handshake_response(self) -> dict[str, Any]:
        """构建握手响应"""
        return {
            "schema_version": self.server_version,
            "message_type": "handshake_response",
            "ok": True,
            "server_version": self.server_version,
            "id": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def parse_request(self, raw_message: str) -> dict[str, Any]:
        """解析 IPC 请求（验证 schema_version）

        缺少 schema_version → 抛出 ProtocolHandshakeError
        """
        try:
            parsed = json.loads(raw_message)
        except json.JSONDecodeError:
            raise ProtocolHandshakeError("INVALID_JSON", "IPC 请求不是合法 JSON")

        if not isinstance(parsed, dict):
            raise ProtocolHandshakeError("INVALID_FORMAT", "IPC 请求不是对象")

        if "schema_version" not in parsed:
            raise ProtocolHandshakeError(
                "MISSING_SCHEMA_VERSION",
                "IPC 请求缺少 schema_version 字段（F-01 契约要求）",
            )

        return parsed

    def check_compatibility(self, client_version: str) -> bool:
        """semver 兼容性检查

        MAJOR 不同 = 不兼容
        MINOR/PATCH 不同 = 兼容
        """
        try:
            client_major = int(client_version.split(".")[0])
            server_major = int(self.server_version.split(".")[0])
            return client_major == server_major
        except (ValueError, IndexError):
            return False

    def handle_handshake(self, raw_message: str) -> dict[str, Any]:
        """处理握手请求"""
        try:
            req = self.parse_request(raw_message)
            client_version = req.get("schema_version", "unknown")
            req_id = req.get("id", str(uuid.uuid4()))
            compatible = self.check_compatibility(client_version)

            resp = self.build_handshake_response()
            resp["id"] = req_id
            resp["compatible"] = compatible
            if not compatible:
                resp["ok"] = False
                resp["error"] = {
                    "code": "VERSION_MISMATCH",
                    "message": f"版本不兼容: client={client_version} server={self.server_version}",
                }
            return resp
        except ProtocolHandshakeError as e:
            return {
                "schema_version": self.server_version,
                "message_type": "handshake_response",
                "ok": False,
                "error": {"code": e.code, "message": e.message},
                "id": str(uuid.uuid4()),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }


def create_protocol_server(version: str = CURRENT_SCHEMA_VERSION) -> ProtocolServer:
    """工厂函数：创建 ProtocolServer 实例"""
    return ProtocolServer(version=version)
