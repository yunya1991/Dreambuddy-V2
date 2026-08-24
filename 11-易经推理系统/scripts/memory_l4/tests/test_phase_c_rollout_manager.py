"""T_C6 验收测试：渐进上线管理器（phase_c_rollout_manager.py）

位置: scripts/memory_l4/tests/test_phase_c_rollout_manager.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_rollout_manager.py -v

对应 Plan §T_C6: 渐进上线管理器。

核心验证：
  • RolloutManager 类可实例化
  • 初始 α=0.0
  • promote 提升 α（步长 0.1，上限 0.5）
  • rollback 降低 α
  • α 达到上限后不再提升
  • α=0 时 rollback 保持 0（不下穿）
  • 持久化状态（保存/加载）
  • get_status 返回完整状态
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))


# ================================================================
# T_C6: 渐进上线管理器
# ================================================================

class TestRolloutManager:
    """验证 RolloutManager 类。"""

    def test_class_importable(self, tmp_path):
        """T_C6.1: RolloutManager 类可实例化。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        assert mgr is not None
        assert mgr.current_alpha == 0.0

    def test_initial_alpha_zero(self, tmp_path):
        """T_C6.2: 初始 α=0.0。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        assert mgr.current_alpha == 0.0
        assert mgr.target_alpha == 0.5

    def test_promote_increases_alpha(self, tmp_path):
        """T_C6.3: promote 提升 α（步长 0.1，上限 0.5）。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        assert mgr.current_alpha == 0.0

        mgr.promote()
        assert mgr.current_alpha == 0.1

        mgr.promote()
        assert mgr.current_alpha == 0.2

    def test_rollback_decreases_alpha(self, tmp_path):
        """T_C6.4: rollback 降低 α。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        mgr.promote()  # 0.1
        mgr.promote()  # 0.2
        mgr.promote()  # 0.3

        mgr.rollback()
        assert mgr.current_alpha == 0.2

    def test_alpha_max_cap(self, tmp_path):
        """T_C6.5: α 达到上限后不再提升。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        # 连续 promote 7 次（应该到 0.5 封顶）
        for _ in range(7):
            mgr.promote()
        assert mgr.current_alpha == 0.5

    def test_rollback_at_zero_stays_zero(self, tmp_path):
        """T_C6.6: α=0 时 rollback 保持 0（不下穿）。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        assert mgr.current_alpha == 0.0
        mgr.rollback()
        assert mgr.current_alpha == 0.0

    def test_state_persistence(self, tmp_path):
        """T_C6.7: 持久化状态（保存/加载）。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        state_path = tmp_path / "rollout.json"

        mgr1 = RolloutManager(state_path=state_path)
        mgr1.promote()  # 0.1
        mgr1.promote()  # 0.2
        mgr1.save()

        mgr2 = RolloutManager(state_path=state_path)
        mgr2.load()
        assert mgr2.current_alpha == 0.2

    def test_get_status_structure(self, tmp_path):
        """T_C6.8: get_status 返回完整状态。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        mgr.promote()

        status = mgr.get_status()
        assert "current_alpha" in status
        assert "target_alpha" in status
        assert "history" in status
        assert "is_complete" in status
        assert status["current_alpha"] == 0.1
        assert status["is_complete"] is False

    def test_is_complete_when_target_reached(self, tmp_path):
        """T_C6.9: α 达到 target 时 is_complete=True。"""
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager
        mgr = RolloutManager(state_path=tmp_path / "rollout.json")
        for _ in range(5):
            mgr.promote()
        assert mgr.current_alpha == 0.5
        assert mgr.is_complete is True
