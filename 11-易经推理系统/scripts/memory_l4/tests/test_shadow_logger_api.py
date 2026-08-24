"""T_B6 验收测试：/api/shadow/report API

位置: scripts/memory_l4/tests/test_shadow_logger_api.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_shadow_logger_api.py -v

对应 Plan §T_B6: /api/shadow/report API。

测试策略：
  1. 直接测试 get_shadow_report() 函数（不启动 HTTP server）
  2. 通过检查 data_server_fixed.py 源码确认路由已注册
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

# data_server_fixed.py 在 11-易经推理系统 根目录
DATA_SERVER_DIR = Path(__file__).resolve().parents[2]
if str(DATA_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_SERVER_DIR))


# ================================================================
# T_B6: /api/shadow/report API
# ================================================================

class TestShadowLoggerAPI:
    """验证 /api/shadow/report API。"""

    def test_get_shadow_report_function_exists(self):
        """T_B6.1: get_shadow_report 函数存在。"""
        import data_server_fixed
        assert hasattr(data_server_fixed, "get_shadow_report")
        assert callable(data_server_fixed.get_shadow_report)

    def test_route_registered(self):
        """T_B6.2: 路由 /api/shadow/report 已注册在 do_GET 中。"""
        import data_server_fixed
        import inspect
        # 读取 do_GET 源码，确认包含 /api/shadow/report 路由
        src = inspect.getsource(data_server_fixed.Handler.do_GET)
        assert "/api/shadow/report" in src

    def test_disabled_returns_ok_false(self):
        """T_B6.3: SHADOW_LOGGER_ENABLED=False 时返回 ok=False。"""
        from data_server_fixed import get_shadow_report
        with patch("data_server_fixed.SHADOW_LOGGER_ENABLED", False):
            result = get_shadow_report("BTC", days=7)
        assert result["ok"] is False
        assert "error" in result

    def test_enabled_returns_report(self):
        """T_B6.4: 开关开启时返回 ok=True 和 report 结构。"""
        from data_server_fixed import get_shadow_report

        # mock ShadowLogger
        mock_logger = MagicMock()
        expected_report = {
            "symbol": "BTC",
            "days": 7,
            "total_records": 5,
            "param_diff_stats": {
                "L": {"mean_diff": 0.1, "std_diff": 0.05, "max_diff": 0.3},
                "T": {"mean_diff": 0.02, "std_diff": 0.01, "max_diff": 0.1},
            },
            "would_change_decision": {
                "direction_changes": 1,
                "threshold_changes": 2,
                "position_changes": 1,
            },
            "direction_consistency": 0.8,
            "regime_distribution": {"TREND_UP_STRONG": 3, "RANGE_BOUND": 2},
        }
        mock_logger.get_comparison_report.return_value = expected_report

        with patch("data_server_fixed.SHADOW_LOGGER_ENABLED", True), \
             patch("data_server_fixed._get_shadow_logger", return_value=mock_logger):
            result = get_shadow_report("BTC", days=7)

        assert result["ok"] is True
        assert "report" in result
        assert result["report"] == expected_report
        mock_logger.get_comparison_report.assert_called_once_with("BTC", 7)

    def test_exception_returns_error(self):
        """T_B6.5: 内部异常时返回 ok=False 和 error 信息。"""
        from data_server_fixed import get_shadow_report

        with patch("data_server_fixed.SHADOW_LOGGER_ENABLED", True), \
             patch("data_server_fixed._get_shadow_logger",
                   side_effect=RuntimeError("DB connection failed")):
            result = get_shadow_report("BTC", days=7)

        assert result["ok"] is False
        assert "error" in result
        assert "DB connection failed" in result["error"]
