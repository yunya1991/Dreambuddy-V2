"""P3-7 Transactive Memory 索引 TDD RED 测试

借鉴 arXiv:2606.19911 交互记忆理论。现状痛点：247 SKILL 无"谁擅长什么"
的 agent profile —— 任务路由时不清楚哪个 agent/SKILL 擅长哪个领域。

核心机制（谁擅长什么 → 路由）:
  1. register_expert(domain, agent_id, confidence) — 注册 agent profile
  2. who_knows(domain) — 查询某领域按置信度排序的专家列表（任务路由）
  3. record_outcome(domain, agent_id, success) — 执行结果强化：
     成功上调置信度，失败下调（强化学习式 profile 更新）
  4. get_profile(agent_id) — 查询 agent 擅长领域 profile

RED 契约:
  1. transactive_memory 模块不存在 → ImportError
  2. TransactiveMemory 类不存在
  3. CognitiveLoopEntry 无 transactive_memory 属性

参考: SPEC-CognitiveSystem-Evolution.md §1.3 + §4.3 P3-7
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestRegisterAndQuery:
    """注册与查询（谁擅长什么）。"""

    def test_import_transactive_memory(self):
        """RED: transactive_memory 模块可导入。"""
        from transactive_memory import TransactiveMemory  # noqa: F401

    def test_register_and_who_knows(self):
        """RED: 注册专家后 who_knows 能查到。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("技术分析", "trend-skill", confidence=0.9)

        experts = tm.who_knows("技术分析")
        assert len(experts) == 1
        assert experts[0]["agent_id"] == "trend-skill"
        assert experts[0]["confidence"] == 0.9

    def test_who_knows_ranked_by_confidence(self):
        """RED: 多专家按置信度降序排序（路由取最优）。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("宏观", "macro-skill", confidence=0.6)
        tm.register_expert("宏观", "fed-skill", confidence=0.95)

        experts = tm.who_knows("宏观")
        assert experts[0]["agent_id"] == "fed-skill"
        assert experts[1]["agent_id"] == "macro-skill"

    def test_who_knows_unknown_domain_empty(self):
        """RED: 未注册领域 → 空列表（FAIL-OPEN 不报错）。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        assert tm.who_knows("不存在的领域") == []

    def test_register_failopen_invalid(self):
        """RED: 无效注册（None/空 agent_id）→ 跳过不抛异常。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert(None, "some-agent")
        tm.register_expert("domain", None)
        tm.register_expert("domain", "")  # 空 ID
        assert tm.who_knows("domain") == []


class TestOutcomeReinforcement:
    """执行结果强化（profile 随成败更新）。"""

    def test_success_raises_confidence(self):
        """RED: 成功 → 置信度上调。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("链上分析", "onchain-skill", confidence=0.5)
        tm.record_outcome("链上分析", "onchain-skill", success=True)

        experts = tm.who_knows("链上分析")
        assert experts[0]["confidence"] > 0.5

    def test_failure_lowers_confidence(self):
        """RED: 失败 → 置信度下调。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("链上分析", "onchain-skill", confidence=0.5)
        tm.record_outcome("链上分析", "onchain-skill", success=False)

        experts = tm.who_knows("链上分析")
        assert experts[0]["confidence"] < 0.5

    def test_confidence_bounded(self):
        """RED: 多次成功/失败后置信度保持在 [0, 1]。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("高频", "hft-skill", confidence=0.99)
        for _ in range(20):
            tm.record_outcome("高频", "hft-skill", success=True)
        assert tm.who_knows("高频")[0]["confidence"] <= 1.0

        tm.register_expert("低频", "bad-skill", confidence=0.01)
        for _ in range(20):
            tm.record_outcome("低频", "bad-skill", success=False)
        assert tm.who_knows("低频")[0]["confidence"] >= 0.0

    def test_record_outcome_unknown_agent_failopen(self):
        """RED: 未知 agent 的 outcome → FAIL-OPEN 忽略不抛异常。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.record_outcome("任何领域", "ghost-agent", success=True)  # 不应抛异常


class TestProfile:
    """agent profile 查询。"""

    def test_get_profile(self):
        """RED: get_profile 返回 agent 擅长领域列表。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("技术分析", "multi-skill", confidence=0.8)
        tm.register_expert("宏观", "multi-skill", confidence=0.6)

        profile = tm.get_profile("multi-skill")
        domains = {p["domain"] for p in profile}
        assert "技术分析" in domains
        assert "宏观" in domains

    def test_get_profile_unknown_agent(self):
        """RED: 未知 agent → 空列表。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        assert tm.get_profile("ghost") == []

    def test_stats(self):
        """RED: stats 返回注册统计。"""
        from transactive_memory import TransactiveMemory

        tm = TransactiveMemory()
        tm.register_expert("A", "s1", confidence=0.5)
        tm.register_expert("B", "s2", confidence=0.5)

        stats = tm.stats()
        assert stats["domains"] == 2
        assert stats["agents"] == 2
        assert stats["expertise_entries"] == 2


class TestCognitiveLoopEntryIntegration:
    """CognitiveLoopEntry P3-7 集成点。"""

    def test_transactive_memory_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 transactive_memory 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "transactive_memory" in src
        assert "TransactiveMemory" in src
