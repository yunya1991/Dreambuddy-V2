"""
L3 自修复: 灰度与回滚 — 版本化节点注册表单测
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.core.compute.canary_registry import (
    VersionedNodeRegistry, NodeVersion, CanaryStatus, CanaryDecision,
)


def make_mock_node(node_id, version):
    node = MagicMock()
    node.node_id = node_id
    node.version = version
    return node


class TestNodeVersion:
    """NodeVersion 数据模型测试"""

    def test_record_call_success(self):
        nv = NodeVersion("A1", "1.0.0", MagicMock())
        nv.record_call(True, 100.0, 0.8)
        assert nv.total_calls == 1
        assert nv.success_count == 1
        assert nv.failure_count == 0
        assert nv.success_rate == 1.0
        assert nv.avg_duration_ms == 100.0
        assert nv.avg_confidence == 0.8

    def test_record_call_failure(self):
        nv = NodeVersion("A1", "1.0.0", MagicMock())
        nv.record_call(False, 200.0, 0.3)
        assert nv.failure_count == 1
        assert nv.error_rate == 1.0

    def test_mixed_calls(self):
        nv = NodeVersion("A1", "1.0.0", MagicMock())
        nv.record_call(True, 100, 0.8)
        nv.record_call(True, 200, 0.9)
        nv.record_call(False, 300, 0.2)
        assert nv.total_calls == 3
        assert nv.success_rate == pytest.approx(0.6667, abs=0.01)
        assert nv.avg_duration_ms == pytest.approx(200.0)
        assert nv.avg_confidence == pytest.approx(0.6333, abs=0.01)

    def test_zero_calls_metrics(self):
        nv = NodeVersion("A1", "1.0.0", MagicMock())
        assert nv.success_rate == 0.0
        assert nv.avg_duration_ms == 0.0
        assert nv.avg_confidence == 0.0
        assert nv.error_rate == 0.0

    def test_to_dict(self):
        nv = NodeVersion("A1", "1.0.0", MagicMock(), is_canary=True, traffic_ratio=0.1)
        nv.record_call(True, 100, 0.8)
        d = nv.to_dict()
        assert d["node_id"] == "A1"
        assert d["version"] == "1.0.0"
        assert d["is_canary"] is True
        assert d["traffic_ratio"] == 0.1
        assert d["total_calls"] == 1
        assert d["success_rate"] == 1.0


class TestVersionedNodeRegistryRegister:
    """注册测试"""

    def test_register_stable(self):
        reg = VersionedNodeRegistry()
        node = make_mock_node("A1", "1.0.0")
        nv = reg.register_version("A1", "1.0.0", node)
        assert nv.is_canary is False
        assert nv.status == CanaryStatus.PROMOTED

    def test_register_canary(self):
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0.0"))
        nv = reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1.0"), traffic_ratio=0.1, is_canary=True)
        assert nv.is_canary is True
        assert nv.traffic_ratio == 0.1
        assert nv.status == CanaryStatus.CANARY

    def test_register_duplicate_overwrites(self):
        reg = VersionedNodeRegistry()
        n1 = make_mock_node("A1", "1.0.0")
        n2 = make_mock_node("A1", "1.0.0")
        reg.register_version("A1", "1.0.0", n1)
        reg.register_version("A1", "1.0.0", n2)
        versions = reg.get_versions("A1")
        assert len(versions) == 1


class TestVersionedNodeRegistrySelect:
    """流量切分测试"""

    def test_single_version(self):
        """只有一个版本 → 直接返回"""
        reg = VersionedNodeRegistry()
        node = make_mock_node("A1", "1.0.0")
        reg.register_version("A1", "1.0.0", node)
        selected = reg.select("A1")
        assert selected is node

    def test_canary_traffic_split(self):
        """灰度切分：90% 稳定版, 10% 灰度版"""
        reg = VersionedNodeRegistry()
        stable = make_mock_node("A1", "1.0.0")
        canary = make_mock_node("A1", "1.1.0")
        reg.register_version("A1", "1.0.0", stable)
        reg.register_version("A1", "1.1.0-canary", canary, traffic_ratio=0.1, is_canary=True)

        # 模拟 100 次选择
        stable_count = 0
        canary_count = 0
        for _ in range(100):
            selected = reg.select("A1")
            if selected is stable:
                stable_count += 1
            elif selected is canary:
                canary_count += 1

        # 灰度比例大约 10%（允许 ±10% 偏差）
        assert canary_count > 0
        ratio = canary_count / 100
        assert 0.0 < ratio < 0.25

    def test_aborted_version_not_selected(self):
        """已回滚版本不被选择"""
        reg = VersionedNodeRegistry()
        stable = make_mock_node("A1", "1.0.0")
        canary = make_mock_node("A1", "1.1.0")
        reg.register_version("A1", "1.0.0", stable)
        canary_nv = reg.register_version("A1", "1.1.0-canary", canary, traffic_ratio=0.5, is_canary=True)
        canary_nv.status = CanaryStatus.ABORTED

        # 只应选到稳定版
        for _ in range(20):
            assert reg.select("A1") is stable

    def test_unknown_node_returns_none(self):
        """未注册节点返回 None"""
        reg = VersionedNodeRegistry()
        assert reg.select("NONEXIST") is None


class TestCanaryEvaluation:
    """灰度评估测试"""

    def test_insufficient_data(self):
        """样本不足 → insufficient_data"""
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1"), traffic_ratio=0.1, is_canary=True)
        # 只记录 5 次（< MIN_SAMPLE_SIZE=10）
        for _ in range(5):
            reg.record_result("A1", "1.1.0-canary", True, 100, 0.8)
        decision = reg.evaluate_canary("A1")
        assert decision.action == "insufficient_data"
        assert "样本不足" in decision.reason

    def test_promote_on_good_metrics(self):
        """灰度指标达标 → promote"""
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1"), traffic_ratio=0.1, is_canary=True)

        # 稳定版记录
        for _ in range(20):
            reg.record_result("A1", "1.0.0", True, 150, 0.75)

        # 灰度版记录（更好）
        for _ in range(10):
            reg.record_result("A1", "1.1.0-canary", True, 100, 0.85)

        decision = reg.evaluate_canary("A1")
        assert decision.action == "promote"
        assert "达标" in decision.reason

    def test_rollback_on_high_error_rate(self):
        """灰度错误率过高 → rollback"""
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1"), traffic_ratio=0.1, is_canary=True)

        # 稳定版 100% 成功
        for _ in range(20):
            reg.record_result("A1", "1.0.0", True, 100, 0.8)

        # 灰度版 70% 成功（30% 错误率，比稳定版高 30%）
        for _ in range(7):
            reg.record_result("A1", "1.1.0-canary", True, 100, 0.8)
        for _ in range(3):
            reg.record_result("A1", "1.1.0-canary", False, 100, 0.3)

        decision = reg.evaluate_canary("A1")
        assert decision.action == "rollback"
        assert "错误率" in decision.reason

    def test_rollback_on_confidence_drop(self):
        """灰度置信度下降 → rollback"""
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1"), traffic_ratio=0.1, is_canary=True)

        # 稳定版高置信度
        for _ in range(20):
            reg.record_result("A1", "1.0.0", True, 100, 0.9)

        # 灰度版置信度骤降
        for _ in range(10):
            reg.record_result("A1", "1.1.0-canary", True, 100, 0.5)

        decision = reg.evaluate_canary("A1")
        assert decision.action == "rollback"
        assert "置信度" in decision.reason

    def test_rollback_on_slow_duration(self):
        """灰度耗时大增 → rollback"""
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1"), traffic_ratio=0.1, is_canary=True)

        # 稳定版 100ms
        for _ in range(20):
            reg.record_result("A1", "1.0.0", True, 100, 0.8)

        # 灰度版 200ms（+100%，超过 20% 阈值）
        for _ in range(10):
            reg.record_result("A1", "1.1.0-canary", True, 200, 0.8)

        decision = reg.evaluate_canary("A1")
        assert decision.action == "rollback"
        assert "耗时" in decision.reason

    def test_no_canary_returns_none(self):
        """无灰度版本 → None"""
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        assert reg.evaluate_canary("A1") is None

    def test_unknown_node_returns_none(self):
        """未知节点 → None"""
        reg = VersionedNodeRegistry()
        assert reg.evaluate_canary("NONEXIST") is None


class TestRegistryQuery:
    """查询接口测试"""

    def test_get_versions(self):
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("A1", "1.1.0-canary", make_mock_node("A1", "1.1"), traffic_ratio=0.1, is_canary=True)
        versions = reg.get_versions("A1")
        assert len(versions) == 2

    def test_status_all(self):
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.register_version("B1", "1.0.0", make_mock_node("B1", "1.0"))
        status = reg.status()
        assert "A1" in status
        assert "B1" in status

    def test_reset_metrics(self):
        reg = VersionedNodeRegistry()
        reg.register_version("A1", "1.0.0", make_mock_node("A1", "1.0"))
        reg.record_result("A1", "1.0.0", True, 100, 0.8)
        assert reg.get_versions("A1")[0]["total_calls"] == 1
        reg.reset_metrics("A1")
        assert reg.get_versions("A1")[0]["total_calls"] == 0


class TestCanaryDecision:
    """决策结果测试"""

    def test_to_dict(self):
        d = CanaryDecision(
            action="promote",
            reason="指标达标",
            stable_version="1.0.0",
            canary_version="1.1.0",
        )
        result = d.to_dict()
        assert result["action"] == "promote"
        assert result["stable_version"] == "1.0.0"
        assert result["canary_version"] == "1.1.0"
        assert "decided_at" in result
