"""T_C7 验收测试：/api/alpha/status API

位置: scripts/memory_l4/tests/test_phase_c_alpha_status_api.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_alpha_status_api.py -v

对应 Plan §T_C7: /api/alpha/status API。

核心验证：
  • get_alpha_status 函数存在
  • 路由 /api/alpha/status 已注册
  • 开关关闭时返回 ok=False
  • 开关开启时返回 ok=True 和 status 结构
  • status 包含 current_alpha / target_alpha / is_complete
  • /api/alpha/promote 路由提升 α
  • /api/alpha/rollback 路由降低 α
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))


# ================================================================
# T_C7: /api/alpha/status API
# ================================================================

class TestAlphaStatusAPI:
    """验证 /api/alpha/status API。"""

    def test_get_alpha_status_function_exists(self):
        """T_C7.1: get_alpha_status 函数存在。"""
        # data_server_fixed.py 在 11-易经推理系统 目录
        sys.path.insert(0, str(THIS_DIR.parent.parent))
        from data_server_fixed import get_alpha_status
        assert callable(get_alpha_status)

    def test_route_registered(self):
        """T_C7.2: 路由 /api/alpha/status 已注册。"""
        import data_server_fixed
        # 检查源代码中是否包含路由定义
        import inspect
        source = inspect.getsource(data_server_fixed)
        assert "/api/alpha/status" in source
        assert "/api/alpha/promote" in source
        assert "/api/alpha/rollback" in source

    def test_disabled_returns_ok_false(self):
        """T_C7.3: 开关关闭时返回 ok=False。"""
        from data_server_fixed import get_alpha_status
        with patch("data_server_fixed.ALPHA_BLEND_ENABLED", False):
            result = get_alpha_status()
        assert result["ok"] is False
        assert "error" in result

    def test_enabled_returns_status(self):
        """T_C7.4: 开关开启时返回 ok=True 和 status 结构。"""
        from data_server_fixed import get_alpha_status
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager

        mock_mgr = MagicMock(spec=RolloutManager)
        mock_mgr.get_status.return_value = {
            "current_alpha": 0.2,
            "target_alpha": 0.5,
            "step": 0.1,
            "is_complete": False,
            "history_length": 2,
            "history": [],
        }

        with patch("data_server_fixed.ALPHA_BLEND_ENABLED", True), \
             patch("data_server_fixed._get_rollout_manager", return_value=mock_mgr):
            result = get_alpha_status()

        assert result["ok"] is True
        assert "status" in result
        assert result["status"]["current_alpha"] == 0.2
        assert result["status"]["target_alpha"] == 0.5
        assert result["status"]["is_complete"] is False

    def test_status_has_required_fields(self):
        """T_C7.5: status 包含 current_alpha / target_alpha / is_complete。"""
        from data_server_fixed import get_alpha_status
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager

        mock_mgr = MagicMock(spec=RolloutManager)
        mock_mgr.get_status.return_value = {
            "current_alpha": 0.3,
            "target_alpha": 0.5,
            "step": 0.1,
            "is_complete": False,
            "history_length": 3,
            "history": [],
        }

        with patch("data_server_fixed.ALPHA_BLEND_ENABLED", True), \
             patch("data_server_fixed._get_rollout_manager", return_value=mock_mgr):
            result = get_alpha_status()

        status = result["status"]
        assert "current_alpha" in status
        assert "target_alpha" in status
        assert "is_complete" in status

    def test_promote_route_calls_promote(self):
        """T_C7.6: /api/alpha/promote 路由提升 α。"""
        from data_server_fixed import promote_alpha
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager

        mock_mgr = MagicMock(spec=RolloutManager)
        mock_mgr.promote.return_value = 0.3
        mock_mgr.get_status.return_value = {"current_alpha": 0.3}

        with patch("data_server_fixed.ALPHA_BLEND_ENABLED", True), \
             patch("data_server_fixed._get_rollout_manager", return_value=mock_mgr):
            result = promote_alpha()

        assert result["ok"] is True
        assert result["new_alpha"] == 0.3
        mock_mgr.promote.assert_called_once()
        mock_mgr.save.assert_called_once()

    def test_rollback_route_calls_rollback(self):
        """T_C7.7: /api/alpha/rollback 路由降低 α。"""
        from data_server_fixed import rollback_alpha
        from bcrm2.scripts.phase_c_rollout_manager import RolloutManager

        mock_mgr = MagicMock(spec=RolloutManager)
        mock_mgr.rollback.return_value = 0.1
        mock_mgr.get_status.return_value = {"current_alpha": 0.1}

        with patch("data_server_fixed.ALPHA_BLEND_ENABLED", True), \
             patch("data_server_fixed._get_rollout_manager", return_value=mock_mgr):
            result = rollback_alpha()

        assert result["ok"] is True
        assert result["new_alpha"] == 0.1
        mock_mgr.rollback.assert_called_once()
        mock_mgr.save.assert_called_once()
