"""T8 验收测试：storage 扩展 overshoot_hint 字段

位置: scripts/memory_l4/tests/test_cycle_bounds_storage.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_storage.py -v

对应 Spec §3bis.5.3 storage 扩展。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.storage import EvolutionStorageSQLite


@pytest.fixture
def tmp_storage(tmp_path) -> EvolutionStorageSQLite:
    """临时空 SQLite。"""
    db_path = tmp_path / "evo_test.db"
    storage = EvolutionStorageSQLite(db_path)
    yield storage
    storage.close()


# ================================================================
# T8: overshoot_hint 存储扩展
# ================================================================

class TestOvershootHintStorage:
    """验证 save_overshoot_hint / get_overshoot_hint 方法。"""

    def test_save_overshoot_hint_method_exists(self, tmp_storage):
        """storage 有 save_overshoot_hint 方法。"""
        assert hasattr(tmp_storage, "save_overshoot_hint")

    def test_get_overshoot_hint_method_exists(self, tmp_storage):
        """storage 有 get_overshoot_hint 方法。"""
        assert hasattr(tmp_storage, "get_overshoot_hint")

    def test_save_and_get_overshoot_hint(self, tmp_storage):
        """保存后能读取到 overshoot_hint。"""
        hint = {
            "reason": "overshoot_streak",
            "streak": 5,
            "need_anchor_correct": True,
            "detected_at": "2026-08-19T10:00:00+00:00",
        }
        tmp_storage.save_overshoot_hint("BTCUSDT", hint)

        loaded = tmp_storage.get_overshoot_hint("BTCUSDT")
        assert loaded is not None
        assert loaded["reason"] == "overshoot_streak"
        assert loaded["streak"] == 5
        assert loaded["need_anchor_correct"] is True

    def test_get_overshoot_hint_none_when_not_set(self, tmp_storage):
        """未设置时返回 None。"""
        result = tmp_storage.get_overshoot_hint("BTCUSDT")
        assert result is None

    def test_overshoot_hint_in_anchor_state(self, tmp_storage):
        """get_anchor_state 返回结果包含 overshoot_hint 字段。"""
        # 先保存 anchor_state
        tmp_storage.save_anchor_state(
            "BTCUSDT",
            anchor_overrides={"主升浪加速": {"t_rel": 170.0, "level": 1.0}},
            switch_from="均衡蓄力",
            switch_to="主升浪加速",
            switch_date="2026-08-19",
        )
        # 保存 overshoot_hint
        hint = {"reason": "overshoot_streak", "streak": 5, "need_anchor_correct": True}
        tmp_storage.save_overshoot_hint("BTCUSDT", hint)

        # get_anchor_state 应包含 overshoot_hint
        state = tmp_storage.get_anchor_state("BTCUSDT")
        assert state is not None
        assert "overshoot_hint" in state
        assert state["overshoot_hint"]["need_anchor_correct"] is True

    def test_overshoot_hint_overwrite(self, tmp_storage):
        """多次保存覆盖前值。"""
        hint1 = {"reason": "overshoot_streak", "streak": 3, "need_anchor_correct": False}
        tmp_storage.save_overshoot_hint("BTCUSDT", hint1)

        hint2 = {"reason": "overshoot_streak", "streak": 6, "need_anchor_correct": True}
        tmp_storage.save_overshoot_hint("BTCUSDT", hint2)

        loaded = tmp_storage.get_overshoot_hint("BTCUSDT")
        assert loaded["streak"] == 6
        assert loaded["need_anchor_correct"] is True

    def test_clear_overshoot_hint(self, tmp_storage):
        """clear_overshoot_hint 能清除 hint。"""
        hint = {"reason": "overshoot_streak", "streak": 5, "need_anchor_correct": True}
        tmp_storage.save_overshoot_hint("BTCUSDT", hint)

        tmp_storage.clear_overshoot_hint("BTCUSDT")

        assert tmp_storage.get_overshoot_hint("BTCUSDT") is None
