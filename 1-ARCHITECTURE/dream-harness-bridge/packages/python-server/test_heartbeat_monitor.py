"""
L2 自检测: DSH HeartbeatMonitor 单测
覆盖: subagent 心跳记录 / 心跳状态判定 / SubagentOutput 字段非空率 / 整体汇总
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

PYTHON_SERVER = Path(__file__).resolve().parent
sys.path.insert(0, str(PYTHON_SERVER))

from heartbeat_monitor import (
    DSHHeartbeatMonitor,
    SubagentHeartbeat,
    SubagentOutputStats,
    HeartbeatStatus,
    DSH_SUBAGENT_TYPES,
    record_dsh_anomaly_to_cognitive,
)


class TestSubagentHeartbeat:
    """单 subagent 心跳记录"""

    def test_record_call_updates_fields(self):
        """记录调用更新字段"""
        hb = SubagentHeartbeat(subagent_type="technical")
        hb.record_call(150.0, "ok")
        assert hb.total_calls == 1
        assert hb.error_count == 0
        assert hb.last_status == "ok"
        assert hb.last_call_duration_ms == 150.0
        assert hb.last_call_ts is not None

    def test_record_error_increments_error_count(self):
        """错误调用增加 error_count"""
        hb = SubagentHeartbeat(subagent_type="technical")
        hb.record_call(100.0, "ok")
        hb.record_call(200.0, "error")
        assert hb.total_calls == 2
        assert hb.error_count == 1

    def test_to_dict(self):
        """to_dict 输出完整字段"""
        hb = SubagentHeartbeat(subagent_type="technical")
        hb.record_call(100.0, "ok")
        d = hb.to_dict()
        assert d["subagent_type"] == "technical"
        assert d["total_calls"] == 1
        assert d["last_status"] == "ok"


class TestSubagentOutputStats:
    """SubagentOutput 字段统计"""

    def test_record_full_output(self):
        """完整 output 4 字段都非空"""
        stats = SubagentOutputStats()
        stats.record_output({
            "module": "technical",
            "summary": "test",
            "signals": [{"name": "RSI"}],
            "charts": [{"type": "line"}],
        })
        assert stats.total_outputs == 1
        assert stats.module_rate == 1.0
        assert stats.summary_rate == 1.0
        assert stats.signals_rate == 1.0
        assert stats.charts_rate == 1.0

    def test_record_empty_output(self):
        """空 output 各字段率为 0"""
        stats = SubagentOutputStats()
        stats.record_output({})
        assert stats.module_rate == 0.0
        assert stats.summary_rate == 0.0

    def test_partial_output(self):
        """部分字段非空"""
        stats = SubagentOutputStats()
        stats.record_output({"module": "technical", "summary": ""})
        assert stats.module_rate == 1.0
        assert stats.summary_rate == 0.0

    def test_zero_outputs_returns_zero(self):
        """无记录时比率为 0"""
        stats = SubagentOutputStats()
        assert stats.module_rate == 0.0


class TestDSHHeartbeatMonitorHeartbeats:
    """subagent 心跳状态判定"""

    def test_no_calls_all_dead(self):
        """无任何调用 → 全部 DEAD"""
        monitor = DSHHeartbeatMonitor()
        result = monitor.check_subagent_heartbeats()
        assert result["dead"] == len(DSH_SUBAGENT_TYPES)
        assert result["alive"] == 0

    def test_recent_call_alive(self):
        """最近调用 → ALIVE"""
        monitor = DSHHeartbeatMonitor()
        monitor.record_call("technical", 100.0, "ok")
        result = monitor.check_subagent_heartbeats()
        assert result["subagents"]["technical"]["status"] == "alive"
        assert result["alive"] >= 1

    def test_stale_call(self):
        """超时调用 → STALE"""
        monitor = DSHHeartbeatMonitor(stale_threshold_seconds=1)
        monitor.record_call("technical", 100.0, "ok")
        # 手动修改 last_call_ts 为 2 秒前
        monitor.heartbeats["technical"].last_call_ts = (
            datetime.utcnow() - timedelta(seconds=2)
        ).isoformat() + "Z"
        result = monitor.check_subagent_heartbeats()
        assert result["subagents"]["technical"]["status"] == "stale"

    def test_dead_call(self):
        """长时间未调用 → DEAD"""
        monitor = DSHHeartbeatMonitor(
            stale_threshold_seconds=1,
            dead_threshold_seconds=2,
        )
        monitor.record_call("technical", 100.0, "ok")
        monitor.heartbeats["technical"].last_call_ts = (
            datetime.utcnow() - timedelta(seconds=5)
        ).isoformat() + "Z"
        result = monitor.check_subagent_heartbeats()
        assert result["subagents"]["technical"]["status"] == "dead"

    def test_unknown_subagent_auto_created(self):
        """未知 subagent 自动创建心跳记录"""
        monitor = DSHHeartbeatMonitor()
        monitor.record_call("custom_agent", 100.0, "ok")
        assert "custom_agent" in monitor.heartbeats


class TestDSHHeartbeatMonitorOutputFields:
    """SubagentOutput 字段非空率检查"""

    def test_all_fields_above_threshold(self):
        """所有字段非空率达标"""
        monitor = DSHHeartbeatMonitor(min_field_non_empty_rate=0.9)
        for _ in range(10):
            monitor.record_output({
                "module": "m",
                "summary": "s",
                "signals": [{"name": "x"}],
                "charts": [{"type": "line"}],
            })
        result = monitor.check_output_field_non_empty_rate()
        assert result["all_above_threshold"] is True

    def test_some_fields_below_threshold(self):
        """部分字段非空率不达标"""
        monitor = DSHHeartbeatMonitor(min_field_non_empty_rate=0.9)
        for _ in range(10):
            monitor.record_output({
                "module": "m",
                "summary": "",   # summary 全空
                "signals": [{"name": "x"}],
                "charts": [{"type": "line"}],
            })
        result = monitor.check_output_field_non_empty_rate()
        assert result["all_above_threshold"] is False
        assert result["field_rates"]["summary"] == 0.0

    def test_no_outputs(self):
        """无 output 记录 → 所有率为 0"""
        monitor = DSHHeartbeatMonitor()
        result = monitor.check_output_field_non_empty_rate()
        assert result["total_outputs"] == 0
        assert result["all_above_threshold"] is True  # 空集合视为达标


class TestDSHHealthCheckSummary:
    """整体健康检查汇总"""

    def test_all_healthy(self):
        """心跳正常 + 字段达标 → healthy"""
        monitor = DSHHeartbeatMonitor()
        for subagent in DSH_SUBAGENT_TYPES:
            monitor.record_call(subagent, 100.0, "ok")
        for _ in range(5):
            monitor.record_output({
                "module": "m", "summary": "s",
                "signals": [{"name": "x"}], "charts": [{"type": "line"}],
            })
        report = monitor.run_health_check()
        assert report["overall_status"] == "healthy"

    def test_dead_subagent_unhealthy(self):
        """有 DEAD subagent → unhealthy"""
        monitor = DSHHeartbeatMonitor()
        # 只调用一个，其余 DEAD
        monitor.record_call("technical", 100.0, "ok")
        report = monitor.run_health_check()
        assert report["overall_status"] == "unhealthy"

    def test_stale_subagent_degraded(self):
        """有 STALE subagent（无 DEAD）→ degraded"""
        monitor = DSHHeartbeatMonitor(stale_threshold_seconds=1, dead_threshold_seconds=600)
        for subagent in DSH_SUBAGENT_TYPES:
            monitor.record_call(subagent, 100.0, "ok")
        # 把一个设为 stale
        monitor.heartbeats["technical"].last_call_ts = (
            datetime.utcnow() - timedelta(seconds=2)
        ).isoformat() + "Z"
        report = monitor.run_health_check()
        assert report["overall_status"] == "degraded"

    def test_report_contains_all_sections(self):
        """报告包含所有检查项"""
        monitor = DSHHeartbeatMonitor()
        report = monitor.run_health_check()
        assert "overall_status" in report
        assert "checked_at" in report
        assert "heartbeats" in report
        assert "output_fields" in report


class TestRecordDSHAnomaly:
    """DSH 异常记录到认知库"""

    def test_record_with_fn(self):
        mock_fn = MagicMock()
        record_dsh_anomaly_to_cognitive("technical 心跳丢失", record_fn=mock_fn)
        mock_fn.assert_called_once()
        args, kwargs = mock_fn.call_args
        assert "anomaly" in kwargs["tags"]
        assert "dsh" in kwargs["tags"]

    def test_record_without_fn(self):
        record_dsh_anomaly_to_cognitive("test", record_fn=None)  # 不抛异常

    def test_record_fn_exception_silent(self):
        mock_fn = MagicMock(side_effect=RuntimeError("down"))
        record_dsh_anomaly_to_cognitive("test", record_fn=mock_fn)  # 不抛异常
