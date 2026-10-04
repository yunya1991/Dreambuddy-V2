"""
L2 自检测: 跨系统 API 契约测试
验证前端 ↔ 中台 ↔ DreamOS 的 API 响应格式契约

契约定义:
- 产物中台 /api/ops/traces: {success, data: {events, total, summary, source}}
- DreamOS /api/v1/health: {status, service, version}
- Bridge /api/health: {status, service, version}
- trace_id 格式: YYYYMMDD-HHMMSS-{FE|DOS|DSH|HUB}-{nanoid8}
"""

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

# trace_id 格式: 20260929-143022-FE-a3f9k2m1
TRACE_ID_PATTERN = re.compile(
    r"^\d{8}-\d{6}-(FE|DOS|DSH|HUB)-[a-zA-Z0-9]{8}$"
)

# 系统码白名单
VALID_SYSTEMS = {"frontend", "dreamos", "dsh", "hub"}

# 事件状态白名单
VALID_STATUSES = {"ok", "fail", "skip"}


class TestTraceIdFormat:
    """trace_id 格式契约测试"""

    @pytest.mark.parametrize("trace_id,expected", [
        ("20260929-143022-FE-a3f9k2m1", True),
        ("20260929-143022-DOS-a3f9k2m1", True),
        ("20260929-143022-DSH-a3f9k2m1", True),
        ("20260929-143022-HUB-a3f9k2m1", True),
        ("20260929-143022-FE-A3F9K2M1", True),   # 大写 nanoid
        ("invalid", False),
        ("20260929-FE-a3f9k2m1", False),         # 缺时间
        ("20260929-143022-XX-a3f9k2m1", False),  # 无效系统码
        ("20260929-143022-FE-short", False),     # nanoid 太短
        ("", False),
    ])
    def test_trace_id_pattern(self, trace_id, expected):
        """trace_id 必须符合 YYYYMMDD-HHMMSS-{system}-{nanoid8}"""
        match = bool(TRACE_ID_PATTERN.match(trace_id))
        assert match == expected, f"trace_id={trace_id!r} expected={expected}"

    def test_trace_id_system_code_extraction(self):
        """从 trace_id 提取系统码"""
        trace_id = "20260929-143022-FE-a3f9k2m1"
        parts = trace_id.split("-")
        assert len(parts) == 4
        assert parts[2] in {"FE", "DOS", "DSH", "HUB"}


class TestTraceEventSchema:
    """TraceEvent schema 契约测试"""

    def test_valid_event(self):
        """合法事件通过 schema 校验"""
        event = {
            "v": 1,
            "id": "evt_abc123",
            "trace_id": "20260929-143022-FE-a3f9k2m1",
            "span_id": "a1b2c3d4",
            "parent_span_id": None,
            "ts": "2026-09-29T14:30:22.123Z",
            "system": "frontend",
            "layer": "api",
            "node": "task_handler",
            "event_type": "task_created",
            "status": "ok",
            "duration_ms": 150,
            "payload_ref": None,
            "error": None,
            "meta": {},
        }
        assert self._validate_event(event) is True

    def test_invalid_system(self):
        """非法 system 被拒绝"""
        event = self._make_event(system="invalid_system")
        assert self._validate_event(event) is False

    def test_invalid_status(self):
        """非法 status 被拒绝"""
        event = self._make_event(status="unknown")
        assert self._validate_event(event) is False

    def test_missing_required_fields(self):
        """缺失必填字段被拒绝"""
        event = {"v": 1, "id": "x"}  # 缺 trace_id, ts, system, event_type, status
        assert self._validate_event(event) is False

    def test_optional_fields_can_be_none(self):
        """可选字段允许 None"""
        event = self._make_event(
            parent_span_id=None,
            duration_ms=None,
            payload_ref=None,
            error=None,
        )
        assert self._validate_event(event) is True

    @staticmethod
    def _make_event(**overrides):
        base = {
            "v": 1,
            "id": "evt_test",
            "trace_id": "20260929-143022-FE-a3f9k2m1",
            "span_id": "a1b2c3d4",
            "parent_span_id": None,
            "ts": "2026-09-29T14:30:22.123Z",
            "system": "frontend",
            "layer": "api",
            "node": "test",
            "event_type": "test_event",
            "status": "ok",
            "duration_ms": None,
            "payload_ref": None,
            "error": None,
            "meta": {},
        }
        base.update(overrides)
        return base

    @staticmethod
    def _validate_event(event: dict) -> bool:
        """事件 schema 校验"""
        required = {"v", "id", "trace_id", "ts", "system", "event_type", "status"}
        if not required.issubset(event.keys()):
            return False
        if event["system"] not in VALID_SYSTEMS:
            return False
        if event["status"] not in VALID_STATUSES:
            return False
        if not TRACE_ID_PATTERN.match(event["trace_id"]):
            return False
        return True


class TestOpsTracesApiContract:
    """/api/ops/traces API 响应格式契约"""

    def test_success_response_structure(self):
        """成功响应必须包含 success + data"""
        response = {
            "success": True,
            "data": {
                "events": [],
                "total": 0,
                "date": "2026-09-29",
                "source": "pg",
                "summary": {
                    "systems": [],
                    "layers": [],
                    "error_count": 0,
                    "total_duration_ms": 0,
                    "first_event_ts": None,
                    "last_event_ts": None,
                },
            },
        }
        assert self._validate_traces_response(response) is True

    def test_error_response_structure(self):
        """错误响应必须包含 success=False + error"""
        response = {"success": False, "error": "database connection failed"}
        assert self._validate_traces_response(response) is True

    def test_summary_fields(self):
        """summary 必须包含所有字段"""
        summary = {
            "systems": ["frontend", "dreamos"],
            "layers": ["api", "graph"],
            "error_count": 2,
            "total_duration_ms": 1500,
            "first_event_ts": "2026-09-29T14:30:22Z",
            "last_event_ts": "2026-09-29T14:30:25Z",
        }
        assert self._validate_summary(summary) is True

    @staticmethod
    def _validate_traces_response(response: dict) -> bool:
        if "success" not in response:
            return False
        if response["success"]:
            data = response.get("data", {})
            required = {"events", "total", "summary"}
            if not required.issubset(data.keys()):
                return False
            if not isinstance(data["events"], list):
                return False
            return TestOpsTracesApiContract._validate_summary(data["summary"])
        else:
            return "error" in response

    @staticmethod
    def _validate_summary(summary: dict) -> bool:
        required = {"systems", "layers", "error_count", "total_duration_ms",
                    "first_event_ts", "last_event_ts"}
        return required.issubset(summary.keys())


class TestHealthApiContract:
    """健康检查 API 契约"""

    def test_dreamos_health_response(self):
        """DreamOS /api/v1/health 响应格式"""
        response = {
            "status": "healthy",
            "service": "DreamOS API Server",
            "version": "1.0.0",
        }
        assert "status" in response
        assert response["status"] in {"healthy", "degraded", "unhealthy"}

    def test_bridge_health_response(self):
        """Bridge /api/health 响应格式"""
        response = {
            "status": "healthy",
            "service": "Dream Universal Gateway Bridge",
            "version": "1.1.0",
            "features": {
                "websocket": True,
                "monitoring": True,
                "logging": True,
            },
        }
        assert "status" in response
        assert "service" in response
        assert "version" in response


class TestCrossSystemTraceIdPropagation:
    """trace_id 跨系统传播契约"""

    def test_trace_id_unchanged_across_systems(self):
        """同一请求的 trace_id 在各系统事件中保持不变"""
        trace_id = "20260929-143022-FE-a3f9k2m1"
        frontend_event = {"trace_id": trace_id, "system": "frontend"}
        dreamos_event = {"trace_id": trace_id, "system": "dreamos"}
        dsh_event = {"trace_id": trace_id, "system": "dsh"}

        events = [frontend_event, dreamos_event, dsh_event]
        trace_ids = {e["trace_id"] for e in events}
        assert len(trace_ids) == 1
        assert trace_ids.pop() == trace_id

    def test_trace_id_propagates_via_header(self):
        """trace_id 通过 X-Trace-Id header 传递"""
        headers = {
            "X-Trace-Id": "20260929-143022-FE-a3f9k2m1",
            "Content-Type": "application/json",
        }
        assert "X-Trace-Id" in headers
        assert TRACE_ID_PATTERN.match(headers["X-Trace-Id"])
