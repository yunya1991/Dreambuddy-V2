"""
L2 自检测: DreamOS HealthChecker 单测
覆盖: 节点注册表完整性 / Budget 余量 / Reflector 异常率 / 整体状态汇总 / 认知库记录
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.core.compute.health_checker import (
    DreamOSHealthChecker,
    HealthStatus,
    HealthCheckResult,
    SystemHealthReport,
    record_anomaly_to_cognitive,
)


def make_mock_node(node_id, validate_error=None):
    node = MagicMock()
    node.node_id = node_id
    node.validate.return_value = validate_error
    return node


def make_mock_registry(nodes):
    reg = MagicMock()
    reg.list_nodes.return_value = nodes
    return reg


class TestNodeRegistryIntegrity:
    """节点注册表完整性检查"""

    def test_all_nodes_valid(self):
        """全部节点有效 → HEALTHY"""
        nodes = [make_mock_node("A1"), make_mock_node("A2")]
        checker = DreamOSHealthChecker(node_registry=make_mock_registry(nodes))
        result = checker.check_node_registry_integrity()
        assert result.status == HealthStatus.HEALTHY
        assert result.details["valid"] == 2

    def test_some_nodes_invalid(self):
        """部分节点无效 → DEGRADED"""
        nodes = [
            make_mock_node("A1", validate_error=None),
            make_mock_node("A2", validate_error="依赖缺失"),
        ]
        checker = DreamOSHealthChecker(node_registry=make_mock_registry(nodes))
        result = checker.check_node_registry_integrity()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["valid"] == 1

    def test_all_nodes_invalid(self):
        """全部节点无效 → UNHEALTHY"""
        nodes = [
            make_mock_node("A1", validate_error="err1"),
            make_mock_node("A2", validate_error="err2"),
        ]
        checker = DreamOSHealthChecker(node_registry=make_mock_registry(nodes))
        result = checker.check_node_registry_integrity()
        assert result.status == HealthStatus.UNHEALTHY

    def test_empty_registry(self):
        """空注册表 → UNHEALTHY"""
        checker = DreamOSHealthChecker(node_registry=make_mock_registry([]))
        result = checker.check_node_registry_integrity()
        assert result.status == HealthStatus.UNHEALTHY
        assert "无任何节点" in result.message

    def test_no_registry_configured(self):
        """未配置注册表 → DEGRADED"""
        checker = DreamOSHealthChecker()
        result = checker.check_node_registry_integrity()
        assert result.status == HealthStatus.DEGRADED
        assert result.details["configured"] is False

    def test_validate_exception(self):
        """validate 抛异常 → 计入无效"""
        node = make_mock_node("A1")
        node.validate.side_effect = RuntimeError("boom")
        checker = DreamOSHealthChecker(node_registry=make_mock_registry([node]))
        result = checker.check_node_registry_integrity()
        assert result.status == HealthStatus.UNHEALTHY
        assert "validate异常" in result.details["invalid"][0]


class TestBudgetRemaining:
    """Budget 余量检查"""

    def test_budget_sufficient(self):
        """预算充足 → HEALTHY"""
        checker = DreamOSHealthChecker(budget_getter=lambda: 5000.0, min_budget_threshold=1000.0)
        result = checker.check_budget_remaining()
        assert result.status == HealthStatus.HEALTHY

    def test_budget_low(self):
        """预算不足 → DEGRADED"""
        checker = DreamOSHealthChecker(budget_getter=lambda: 500.0, min_budget_threshold=1000.0)
        result = checker.check_budget_remaining()
        assert result.status == HealthStatus.DEGRADED

    def test_budget_depleted(self):
        """预算耗尽 → UNHEALTHY"""
        checker = DreamOSHealthChecker(budget_getter=lambda: 0.0, min_budget_threshold=1000.0)
        result = checker.check_budget_remaining()
        assert result.status == HealthStatus.UNHEALTHY

    def test_budget_negative(self):
        """预算为负 → UNHEALTHY"""
        checker = DreamOSHealthChecker(budget_getter=lambda: -100.0, min_budget_threshold=1000.0)
        result = checker.check_budget_remaining()
        assert result.status == HealthStatus.UNHEALTHY

    def test_no_budget_getter(self):
        """未配置 budget_getter → DEGRADED"""
        checker = DreamOSHealthChecker()
        result = checker.check_budget_remaining()
        assert result.status == HealthStatus.DEGRADED


class TestReflectorAnomalyRate:
    """Reflector 异常率检查"""

    def test_no_anomalies(self):
        """无异常 → HEALTHY"""
        history = [{"status": "success", "confidence": 0.8} for _ in range(10)]
        checker = DreamOSHealthChecker(reflector_history_getter=lambda: history)
        result = checker.check_reflector_anomaly_rate()
        assert result.status == HealthStatus.HEALTHY
        assert result.details["anomalies"] == 0

    def test_high_anomaly_rate(self):
        """异常率超阈值 → UNHEALTHY"""
        history = [
            {"status": "error"},
            {"status": "error"},
            {"status": "error"},
            {"status": "success"},
        ]
        checker = DreamOSHealthChecker(
            reflector_history_getter=lambda: history,
            reflector_anomaly_rate_threshold=0.3,
        )
        result = checker.check_reflector_anomaly_rate()
        assert result.status == HealthStatus.UNHEALTHY
        assert result.details["anomaly_rate"] == 0.75

    def test_low_confidence_counts_as_anomaly(self):
        """confidence < 0.3 计入异常"""
        history = [{"confidence": 0.2}, {"confidence": 0.1}]
        checker = DreamOSHealthChecker(reflector_history_getter=lambda: history)
        result = checker.check_reflector_anomaly_rate()
        assert result.details["anomalies"] == 2

    def test_empty_history(self):
        """无历史记录 → HEALTHY（系统刚启动）"""
        checker = DreamOSHealthChecker(reflector_history_getter=lambda: [])
        result = checker.check_reflector_anomaly_rate()
        assert result.status == HealthStatus.HEALTHY

    def test_window_size_limit(self):
        """只检查最近 N 条"""
        # 前 5 条异常，后 15 条正常，窗口大小 20 → 异常率 25% < 30% → HEALTHY
        history = [{"status": "error"}] * 5 + [{"status": "success"}] * 15
        checker = DreamOSHealthChecker(
            reflector_history_getter=lambda: history,
            reflector_window_size=20,
            reflector_anomaly_rate_threshold=0.3,
        )
        result = checker.check_reflector_anomaly_rate()
        assert result.status == HealthStatus.HEALTHY

    def test_no_reflector_getter(self):
        """未配置 → DEGRADED"""
        checker = DreamOSHealthChecker()
        result = checker.check_reflector_anomaly_rate()
        assert result.status == HealthStatus.DEGRADED


class TestSystemHealthReport:
    """整体状态汇总"""

    def test_all_healthy(self):
        """全部健康 → HEALTHY"""
        checker = DreamOSHealthChecker(
            node_registry=make_mock_registry([make_mock_node("A1")]),
            budget_getter=lambda: 5000.0,
            reflector_history_getter=lambda: [],
        )
        report = checker.run_all_checks()
        assert report.overall_status == HealthStatus.HEALTHY
        assert report.anomaly_count == 0

    def test_one_unhealthy(self):
        """有一个 UNHEALTHY → 整体 UNHEALTHY"""
        checker = DreamOSHealthChecker(
            node_registry=make_mock_registry([]),  # 空 → UNHEALTHY
            budget_getter=lambda: 5000.0,
            reflector_history_getter=lambda: [],
        )
        report = checker.run_all_checks()
        assert report.overall_status == HealthStatus.UNHEALTHY

    def test_one_degraded(self):
        """有一个 DEGRADED（无 UNHEALTHY）→ 整体 DEGRADED"""
        checker = DreamOSHealthChecker(
            node_registry=make_mock_registry([make_mock_node("A1")]),
            budget_getter=lambda: 500.0,  # DEGRADED
            reflector_history_getter=lambda: [],
        )
        report = checker.run_all_checks()
        assert report.overall_status == HealthStatus.DEGRADED

    def test_report_to_dict(self):
        """to_dict 输出可序列化"""
        checker = DreamOSHealthChecker()
        report = checker.run_all_checks()
        d = report.to_dict()
        assert "overall_status" in d
        assert "checks" in d
        assert "checked_at" in d


class TestRecordAnomaly:
    """异常记录到认知库"""

    def test_record_with_fn(self):
        """配置 record_fn 时调用"""
        mock_fn = MagicMock()
        anomaly = HealthCheckResult(
            name="budget_remaining",
            status=HealthStatus.UNHEALTHY,
            message="预算耗尽",
        )
        record_anomaly_to_cognitive(anomaly, record_fn=mock_fn)
        mock_fn.assert_called_once()
        args, kwargs = mock_fn.call_args
        assert "anomaly" in kwargs["tags"]
        assert "auto-detected" in kwargs["tags"]

    def test_record_without_fn(self):
        """未配置 record_fn 时仅日志（不抛异常）"""
        anomaly = HealthCheckResult(
            name="test", status=HealthStatus.DEGRADED, message="test"
        )
        # 不应抛异常
        record_anomaly_to_cognitive(anomaly, record_fn=None)

    def test_record_fn_exception_silent(self):
        """record_fn 抛异常时静默处理"""
        mock_fn = MagicMock(side_effect=RuntimeError("cognitive down"))
        anomaly = HealthCheckResult(name="test", status=HealthStatus.DEGRADED, message="t")
        record_anomaly_to_cognitive(anomaly, record_fn=mock_fn)
        # 不应抛异常
