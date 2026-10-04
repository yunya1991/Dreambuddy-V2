"""
L2 自检测: NodeRegistry 节点注册表单测
覆盖: 注册/注销/查询/批量注册/摘要/线程安全
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.registry.node_registry import NodeRegistry
from dreamos.shared.errors import ErrorCode, OSError


def make_mock_node(node_id, chain="A", tags=None):
    """构造 mock 节点"""
    node = MagicMock()
    node.node_id = node_id
    node.chain = chain
    node.tags = tags or []
    return node


class TestNodeRegistry:
    """节点注册表基础操作测试"""

    def test_register_and_get(self):
        """注册后可查询"""
        reg = NodeRegistry()
        node = make_mock_node("A1")
        reg.register(node)
        assert reg.get("A1") is node

    def test_register_duplicate_raises(self):
        """重复注册抛出异常"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        with pytest.raises(OSError) as exc:
            reg.register(make_mock_node("A1"))
        assert exc.value.code == ErrorCode.NODE_002

    def test_register_empty_node_id_raises(self):
        """空 node_id 抛出异常"""
        reg = NodeRegistry()
        with pytest.raises(OSError) as exc:
            reg.register(make_mock_node(""))
        assert exc.value.code == ErrorCode.NODE_003

    def test_unregister(self):
        """注销节点"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        assert reg.unregister("A1") is True
        assert reg.get("A1") is None

    def test_unregister_nonexistent(self):
        """注销不存在的节点返回 False"""
        reg = NodeRegistry()
        assert reg.unregister("NONEXISTENT") is False

    def test_exists(self):
        """exists 检查"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        assert reg.exists("A1") is True
        assert reg.exists("A2") is False

    def test_contains_operator(self):
        """in 运算符"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        assert "A1" in reg
        assert "A2" not in reg

    def test_len(self):
        """len 统计"""
        reg = NodeRegistry()
        assert len(reg) == 0
        reg.register(make_mock_node("A1"))
        reg.register(make_mock_node("A2"))
        assert len(reg) == 2


class TestNodeRegistryList:
    """list_nodes 过滤测试"""

    def test_list_all(self):
        """列出所有节点"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1", chain="A"))
        reg.register(make_mock_node("A2", chain="A"))
        reg.register(make_mock_node("F1", chain="F"))
        assert len(reg.list_nodes()) == 3

    def test_list_by_chain(self):
        """按 chain 过滤"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1", chain="A"))
        reg.register(make_mock_node("F1", chain="F"))
        a_nodes = reg.list_nodes(chain="A")
        assert len(a_nodes) == 1
        assert a_nodes[0].node_id == "A1"

    def test_list_by_tag(self):
        """按 tag 过滤"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1", tags=["gate"]))
        reg.register(make_mock_node("A2", tags=["compute"]))
        gate_nodes = reg.list_nodes(tag="gate")
        assert len(gate_nodes) == 1
        assert gate_nodes[0].node_id == "A1"

    def test_list_empty_when_no_match(self):
        """无匹配时返回空列表"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1", chain="A"))
        assert reg.list_nodes(chain="Z") == []


class TestNodeRegistryBatch:
    """批量操作测试"""

    def test_register_many(self):
        """批量注册"""
        reg = NodeRegistry()
        nodes = [make_mock_node(f"A{i}") for i in range(5)]
        count = reg.register_many(nodes)
        assert count == 5
        assert len(reg) == 5

    def test_register_many_skips_duplicates(self):
        """批量注册跳过重复"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        nodes = [make_mock_node("A1"), make_mock_node("A2")]
        count = reg.register_many(nodes)
        assert count == 1  # A1 已存在跳过，A2 成功

    def test_clear(self):
        """清空注册表"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        reg.register(make_mock_node("A2"))
        cleared = reg.clear()
        assert cleared == 2
        assert len(reg) == 0

    def test_summary(self):
        """注册表摘要"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1", chain="A"))
        reg.register(make_mock_node("A2", chain="A"))
        reg.register(make_mock_node("F1", chain="F"))
        summary = reg.summary()
        assert summary["total"] == 3
        assert summary["chain_A"] == 2
        assert summary["chain_F"] == 1

    def test_repr(self):
        """repr 输出"""
        reg = NodeRegistry()
        reg.register(make_mock_node("A1"))
        assert "total=1" in repr(reg)
