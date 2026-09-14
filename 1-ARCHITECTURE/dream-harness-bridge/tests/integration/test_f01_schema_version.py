#!/usr/bin/env python3
"""F-01: IPC 契约版本化 — Python 侧测试

测试目标:
1. 每个 IPC 响应含 schema_version
2. 版本握手响应正确
3. semver 兼容性检查
4. 缺少 schema_version 的请求被拒绝

来源: SPEC v0.3 七补.1 F-01
"""

import json
import sys
import os
import pytest

# 添加 sdk 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "packages", "python-server"))

from sdk.protocol_server import (
    create_protocol_server,
    ProtocolHandshakeError,
    CURRENT_SCHEMA_VERSION,
)


class TestF01SchemaVersion:
    """F-01: schema_version 字段"""

    def test_build_response_contains_schema_version(self):
        server = create_protocol_server()
        resp = server.build_response(ok=True, result={"data": "test"})
        assert "schema_version" in resp
        assert resp["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_build_handshake_response_contains_schema_version(self):
        server = create_protocol_server()
        resp = server.build_handshake_response()
        assert "schema_version" in resp
        assert resp["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_schema_version_is_semver(self):
        server = create_protocol_server()
        resp = server.build_response(ok=True, result="test")
        import re
        assert re.match(r"^\d+\.\d+\.\d+$", resp["schema_version"])

    def test_response_contains_message_type(self):
        server = create_protocol_server()
        resp = server.build_response(ok=True, result="test")
        assert resp["message_type"] == "response"

    def test_response_contains_id(self):
        server = create_protocol_server()
        resp = server.build_response(ok=True, result="test")
        assert "id" in resp

    def test_response_contains_timestamp(self):
        server = create_protocol_server()
        resp = server.build_response(ok=True, result="test")
        assert "timestamp" in resp


class TestF01Compatibility:
    """F-01: semver 兼容性检查"""

    def test_major_different_incompatible(self):
        server = create_protocol_server("1.0.0")
        assert server.check_compatibility("2.0.0") is False

    def test_minor_different_compatible(self):
        server = create_protocol_server("1.0.0")
        assert server.check_compatibility("1.1.0") is True

    def test_patch_different_compatible(self):
        server = create_protocol_server("1.0.0")
        assert server.check_compatibility("1.0.5") is True

    def test_same_version_compatible(self):
        server = create_protocol_server("1.0.0")
        assert server.check_compatibility("1.0.0") is True

    def test_invalid_version_incompatible(self):
        server = create_protocol_server("1.0.0")
        assert server.check_compatibility("invalid") is False


class TestF01Handshake:
    """F-01: 版本握手"""

    def test_handshake_compatible(self):
        server = create_protocol_server("1.0.0")
        handshake_req = json.dumps({
            "schema_version": "1.0.0",
            "message_type": "handshake_request",
            "id": "test-id",
        })
        resp = server.handle_handshake(handshake_req)
        assert resp["ok"] is True
        assert resp["compatible"] is True

    def test_handshake_incompatible_major(self):
        server = create_protocol_server("1.0.0")
        handshake_req = json.dumps({
            "schema_version": "2.0.0",
            "message_type": "handshake_request",
            "id": "test-id",
        })
        resp = server.handle_handshake(handshake_req)
        assert resp["ok"] is False
        assert resp["compatible"] is False
        assert resp["error"]["code"] == "VERSION_MISMATCH"


class TestF01ParseRequest:
    """F-01: 请求解析"""

    def test_parse_valid_request(self):
        server = create_protocol_server()
        raw = json.dumps({
            "schema_version": "1.0.0",
            "message_type": "request",
            "method": "execute_node",
            "params": {"node_id": "C1"},
            "id": "test-id",
        })
        req = server.parse_request(raw)
        assert req["schema_version"] == "1.0.0"
        assert req["method"] == "execute_node"

    def test_parse_missing_schema_version_raises(self):
        server = create_protocol_server()
        raw = json.dumps({
            "message_type": "request",
            "method": "execute_node",
            "params": {},
            "id": "test-id",
        })
        with pytest.raises(ProtocolHandshakeError) as exc_info:
            server.parse_request(raw)
        assert exc_info.value.code == "MISSING_SCHEMA_VERSION"

    def test_parse_invalid_json_raises(self):
        server = create_protocol_server()
        with pytest.raises(ProtocolHandshakeError) as exc_info:
            server.parse_request("not a json")
        assert exc_info.value.code == "INVALID_JSON"

    def test_parse_non_object_raises(self):
        server = create_protocol_server()
        with pytest.raises(ProtocolHandshakeError) as exc_info:
            server.parse_request(json.dumps([1, 2, 3]))
        assert exc_info.value.code == "INVALID_FORMAT"


class TestF02ConstraintPassed:
    """F-02: constraint_passed 字段（Python 侧前置）"""

    def test_build_response_with_constraint_passed(self):
        server = create_protocol_server()
        resp = server.build_response(
            ok=True,
            result={"trade": "executed"},
            opts={"constraint_passed": True},
        )
        assert resp.get("constraint_passed") is True

    def test_build_response_without_constraint_passed(self):
        server = create_protocol_server()
        resp = server.build_response(ok=True, result={"data": "recall"})
        assert "constraint_passed" not in resp or resp.get("constraint_passed") is None
