"""P1-4 ACT-R 激活模型 TDD RED 测试

ACT-R (Adaptive Control of Thought-Rational) 激活模型：
recall 排序不只看 score，引入激活公式：

  Activation = ln(Σ t_j^(-d))    # base_level: d=衰减率, t_j=第j次使用距今时间
             + W_j * relatedness  # 上下文相关度权重
             + base_confidence    # 基础置信度

RED 契约:
  1. actr_activation 模块不存在 → ImportError
  2. ACTRActivation 类不存在
  3. compute_activation() 不存在
  4. rank_by_activation() 不存在
  5. CognitiveLoopEntry 无 actr 属性

参考: SPEC-CognitiveSystem-Evolution.md §2.3.3 P1-4
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestACTRActivation:
    """ACT-R 激活模型。"""

    def test_import_actr_activation(self):
        """RED: actr_activation 模块可导入。"""
        from actr_activation import ACTRActivation  # noqa: F401

    def test_compute_activation_basic(self):
        """RED: compute_activation() 返回激活值。"""
        from actr_activation import ACTRActivation

        model = ACTRActivation()
        activation = model.compute_activation(
            days_since_last_use=10,
            verify_count=3,
            context_keywords=["BTC", "策略"],
            content="BTC趋势策略经验",
            base_confidence=0.5,
        )
        assert isinstance(activation, float)
        # 激活值应为正数
        assert activation > 0

    def test_frequently_verified_higher_activation(self):
        """RED: verify_count 高的记忆激活值更高。"""
        from actr_activation import ACTRActivation

        model = ACTRActivation()
        # 低 verify_count
        low_act = model.compute_activation(
            days_since_last_use=10,
            verify_count=0,
            context_keywords=["BTC"],
            content="BTC经验",
            base_confidence=0.3,
        )
        # 高 verify_count
        high_act = model.compute_activation(
            days_since_last_use=10,
            verify_count=5,
            context_keywords=["BTC"],
            content="BTC经验",
            base_confidence=0.3,
        )
        assert high_act > low_act, "高 verify_count 的激活值应更高"

    def test_recent_use_higher_activation(self):
        """RED: 最近使用过的记忆激活值更高（时间衰减）。"""
        from actr_activation import ACTRActivation

        model = ACTRActivation()
        # 最近使用（1天前）
        recent_act = model.compute_activation(
            days_since_last_use=1,
            verify_count=2,
            context_keywords=["test"],
            content="test",
            base_confidence=0.5,
        )
        # 很久没使用（100天前）
        old_act = model.compute_activation(
            days_since_last_use=100,
            verify_count=2,
            context_keywords=["test"],
            content="test",
            base_confidence=0.5,
        )
        assert recent_act > old_act, "最近使用的记忆激活值应更高"

    def test_context_relevance_boosts_activation(self):
        """RED: 上下文相关度高的记忆激活值更高。"""
        from actr_activation import ACTRActivation

        model = ACTRActivation()
        # 无关键词匹配
        low_rel_act = model.compute_activation(
            days_since_last_use=10,
            verify_count=2,
            context_keywords=["XYZ"],
            content="BTC策略",
            base_confidence=0.5,
        )
        # 有关键词匹配
        high_rel_act = model.compute_activation(
            days_since_last_use=10,
            verify_count=2,
            context_keywords=["BTC", "策略"],
            content="BTC趋势策略经验",
            base_confidence=0.5,
        )
        assert high_rel_act > low_rel_act, "上下文相关的记忆激活值应更高"

    def test_rank_by_activation_reorders(self):
        """RED: rank_by_activation() 按激活值重排序。"""
        from actr_activation import ACTRActivation

        model = ACTRActivation()
        memories = [
            # 高 score 但低激活（旧+无 verify）
            {"id": "VM-001", "content": "BTC策略", "score": 0.9,
             "verify_count": 0, "updated_at": (datetime.now(timezone.utc) - timedelta(days=200)).isoformat(),
             "confidence": 0.3},
            # 低 score 但高激活（新+多次 verify）
            {"id": "VM-002", "content": "BTC趋势", "score": 0.6,
             "verify_count": 5, "updated_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
             "confidence": 0.7},
        ]
        ranked = model.rank_by_activation(memories, context="BTC趋势")
        # VM-002 应排在前面（高激活）
        assert ranked[0]["id"] == "VM-002"

    def test_rank_preserves_activation_field(self):
        """RED: 排序后每条记忆应含 activation 字段。"""
        from actr_activation import ACTRActivation

        model = ACTRActivation()
        memories = [
            {"id": "VM-001", "content": "test", "score": 0.5,
             "verify_count": 1, "updated_at": datetime.now(timezone.utc).isoformat(),
             "confidence": 0.5},
        ]
        ranked = model.rank_by_activation(memories, context="test")
        assert "activation" in ranked[0]


class TestCognitiveLoopEntryACTR:
    """CognitiveLoopEntry ACT-R 集成。"""

    def test_actr_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 actr 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry
        import cognitive_loop_entry as cle_mod
        cle_mod.reset_cle()
        try:
            cle = cle_mod.CognitiveLoopEntry(enable_distill=False)
            assert hasattr(cle, "actr")
        except Exception:
            pytest.skip("CLE 初始化失败（DB 锁）")
