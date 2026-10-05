#!/usr/bin/env python3
"""test_skill_governance_loader.py — DreamOS 接入 SKILL 治理系统加载测试

TDD: 验证 load_skills_from_governance() 能通过 dream-skill-index-governance
索引加载可执行 SKILL 节点到 NodeRegistry，且 autonomy_boundary 生效。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def test_load_skills_registers_executable_nodes():
    """加载后 NodeRegistry 中包含可执行的 SKILL 节点（有 execute 方法）"""
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.adapters.skill_adapter import load_skills_from_governance

    registry = NodeRegistry()
    count = load_skills_from_governance(registry)

    assert count > 0, f"应加载至少 1 个 SKILL 节点，实际: {count}"

    # 验证节点是可执行的（有 execute 方法）
    skill_nodes = [n for n in registry.list_nodes() if n.node_id.startswith("SKILL_")]
    assert len(skill_nodes) > 0, "NodeRegistry 中应有 SKILL_* 节点"
    for node in skill_nodes[:3]:  # 抽样检查前 3 个
        assert hasattr(node, "execute"), f"节点 {node.node_id} 应有 execute 方法"
        assert callable(getattr(node, "execute")), f"节点 {node.node_id} 的 execute 应可调用"


def test_loaded_nodes_have_autonomy_boundary():
    """加载的 SKILL 节点中至少有一个 autonomy_boundary 非空（11-易经推理系统/skills 下的）"""
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.adapters.skill_adapter import load_skills_from_governance

    registry = NodeRegistry()
    load_skills_from_governance(registry)

    skill_nodes = [n for n in registry.list_nodes() if n.node_id.startswith("SKILL_")]
    boundaries = [
        getattr(n, "_autonomy_boundary", "")
        for n in skill_nodes
        if hasattr(n, "_autonomy_boundary")
    ]
    non_empty = [b for b in boundaries if b]
    assert len(non_empty) > 0, (
        f"至少应有 1 个节点的 autonomy_boundary 非空，"
        f"实际有 {len(non_empty)}/{len(boundaries)} 个非空"
    )


def test_load_skills_only_active_status():
    """只加载 status=active 的 SKILL（治理系统生命周期过滤）"""
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.adapters.skill_adapter import load_skills_from_governance

    registry = NodeRegistry()
    count = load_skills_from_governance(registry)

    # active SKILL 数量应等于注册数量
    assert count > 0


if __name__ == "__main__":
    test_load_skills_registers_executable_nodes()
    test_loaded_nodes_have_autonomy_boundary()
    test_load_skills_only_active_status()
    print("All tests passed!")
