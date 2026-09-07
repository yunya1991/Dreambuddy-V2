"""test_cognitive_bridge.py — CognitiveBridge 单元测试
覆盖: recall_similar, record_trade, verify_prediction, record_ripple, enabled=False FO
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.adapters.cognitive_bridge import CognitiveBridge


class MockCognitiveLoopEntry:
    """模拟 CognitiveLoopEntry"""

    def __init__(self):
        self.records = []
        self.verified = []

    def recall(self, context, top_k=5, min_quality="C"):
        return [
            {"id": "VM-001", "content": "[trade] TP profit=0.05", "score": 0.85, "quality_level": "A"},
            {"id": "VM-002", "content": "[trade] SL loss=-0.03", "score": 0.70, "quality_level": "B"},
        ]

    def record(self, content, quality_level="C", confidence=0.3, tags=None, source="trae", **kwargs):
        mid = f"VM-{len(self.records)}"
        self.records.append({"id": mid, "content": content})
        return mid

    def verify(self, memory_id, success=True):
        self.verified.append({"id": memory_id, "success": success})
        return {"memory_id": memory_id, "success": success, "new_confidence": 0.6}


class TestCognitiveBridge:

    def test_disabled_returns_neutral(self):
        """enabled=False → recall 返回中性值"""
        bridge = CognitiveBridge(enabled=False)
        result = bridge.recall_similar({"R_up": 0.3, "R_down": 0.7}, "long")
        assert result["cbr_sim"] == 0.5
        assert result["cbr_top1_outcome"] == "NEUTRAL"

    def test_disabled_record_returns_none(self):
        """enabled=False → record 返回 None"""
        bridge = CognitiveBridge(enabled=False)
        assert bridge.record_trade({}, {}) is None
        assert bridge.record_ripple({}) is None
        assert bridge.verify_prediction("VM-001", True) is None

    def test_recall_similar(self):
        """recall_similar 从认知库检索相似案例"""
        bridge = CognitiveBridge(enabled=True)
        bridge._entry = MockCognitiveLoopEntry()  # 注入 mock
        result = bridge.recall_similar({"R_up": 0.3, "R_down": 0.7}, "long")

        assert result["cbr_sim"] == 0.85
        assert result["cbr_top1_id"] == "VM-001"
        # content 含 "TP" → outcome=TP
        assert result["cbr_top1_outcome"] == "TP"

    def test_recall_empty(self):
        """认知库无结果 → 中性降级"""
        class EmptyEntry:
            def recall(self, *a, **kw):
                return []

        bridge = CognitiveBridge(enabled=True)
        bridge._entry = EmptyEntry()
        result = bridge.recall_similar({}, "long")
        assert result["cbr_sim"] == 0.5
        assert result["cbr_top1_outcome"] == "NEUTRAL"

    def test_record_trade(self):
        """record_trade 记录交易经验"""
        bridge = CognitiveBridge(enabled=True)
        bridge._entry = MockCognitiveLoopEntry()
        mid = bridge.record_trade(
            {"symbol": "BTC", "level0_dstar": "long"},
            {"real_outcome": "TP", "cs": 0.8, "pnl_pct": 0.05},
        )
        assert mid is not None
        assert mid.startswith("VM-")
        assert len(bridge._entry.records) == 1

    def test_verify_prediction(self):
        """verify_prediction 更新置信度"""
        bridge = CognitiveBridge(enabled=True)
        bridge._entry = MockCognitiveLoopEntry()
        result = bridge.verify_prediction("VM-001", success=True)
        assert result is not None
        assert result["success"] is True
        assert len(bridge._entry.verified) == 1

    def test_record_ripple(self):
        """record_ripple 记录涟漪原型"""
        bridge = CognitiveBridge(enabled=True)
        bridge._entry = MockCognitiveLoopEntry()
        mid = bridge.record_ripple({
            "symbol": "BTC", "ri": 0.78,
            "r_vector": {"R_up": 0.3, "R_down": 0.7},
            "duration_hours": 25,
        })
        assert mid is not None
        assert "ripple" in bridge._entry.records[0]["content"]

    def test_entry_load_fail_fo(self, tmp_path):
        """CognitiveLoopEntry 加载失败 → FO 降级"""
        bridge = CognitiveBridge(db_path=str(tmp_path / "nonexistent.db"), enabled=True)
        # 不注入 mock，_get_entry 会失败 → 返回 None
        result = bridge.recall_similar({}, "long")
        assert result["cbr_sim"] == 0.5
        assert result["cbr_top1_outcome"] == "NEUTRAL"

    def test_extract_outcome_tp(self):
        """_extract_outcome: content 含 TP → TP"""
        assert CognitiveBridge._extract_outcome({"content": "[trade] TP profit=0.05"}) == "TP"

    def test_extract_outcome_sl(self):
        """_extract_outcome: content 含 SL → SL"""
        assert CognitiveBridge._extract_outcome({"content": "[trade] SL loss=-0.03"}) == "SL"

    def test_extract_outcome_neutral(self):
        """_extract_outcome: 无 TP/SL → NEUTRAL"""
        assert CognitiveBridge._extract_outcome({"content": "some random text"}) == "NEUTRAL"
