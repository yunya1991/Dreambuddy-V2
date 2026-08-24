"""T_B5 验收测试：polling_trader 集成 + 开关

位置: scripts/memory_l4/tests/test_shadow_logger_integration.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_shadow_logger_integration.py -v

对应 Plan §T_B5: polling_trader 集成 + 开关。

由于 PollingTrader 初始化依赖 OKX/BCRM 等重依赖，这里只测试 ShadowLogger
集成相关的轻量方法（_init_shadow_logger / _record_shadow_log），通过在
PollingTrader 子类中 stub 掉重依赖来隔离测试。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED


# ================================================================
# 轻量 stub：绕过 PollingTrader.__init__ 的重依赖
# ================================================================

def _make_stub_trader():
    """构造一个只挂载 ShadowLogger 集成方法的 stub trader。

    PollingTrader.__init__ 依赖 OKX/BCRM/Feishu 等，单元测试无法直接实例化。
    我们用 object.__new__ 创建空实例，再手动挂载需要的方法。
    """
    # 延迟导入，避免在模块加载阶段触发 polling_trader 的重依赖
    from scripts.memory_l4.polling_trader import PollingTrader

    trader = object.__new__(PollingTrader)
    # 挂载 _log（很多方法会调用）
    trader._log = MagicMock()
    return trader


# ================================================================
# T_B5: polling_trader 集成 + 开关
# ================================================================

class TestShadowLoggerIntegration:
    """验证 polling_trader 中 ShadowLogger 集成相关方法。"""

    def test_init_shadow_logger_method_exists(self):
        """T_B5.0: PollingTrader 有 _init_shadow_logger 方法。"""
        from scripts.memory_l4.polling_trader import PollingTrader
        assert hasattr(PollingTrader, "_init_shadow_logger")

    def test_record_shadow_log_method_exists(self):
        """T_B5.0b: PollingTrader 有 _record_shadow_log 方法。"""
        from scripts.memory_l4.polling_trader import PollingTrader
        assert hasattr(PollingTrader, "_record_shadow_log")

    def test_disabled_sets_shadow_logger_none(self):
        """T_B5.1: SHADOW_LOGGER_ENABLED=False 时 _shadow_logger 为 None。"""
        trader = _make_stub_trader()
        with patch("scripts.memory_l4.polling_trader.SHADOW_LOGGER_ENABLED", False):
            trader._init_shadow_logger()
        assert getattr(trader, "_shadow_logger", None) is None

    def test_record_shadow_log_noop_when_disabled(self):
        """T_B5.2: 开关关闭时 _record_shadow_log 不执行任何操作。"""
        trader = _make_stub_trader()
        trader._shadow_logger = None  # 模拟关闭状态

        # 不应抛异常，也不应调用任何方法
        trader._record_shadow_log("BTC", {"snapshot": {}}, {"direction": "LONG"})

        # _log 可能被调用，但不应有 shadow_logger 调用
        # (这里主要验证不抛异常)

    def test_record_shadow_log_calls_record_polling_when_enabled(self):
        """T_B5.3: 开关开启且 _shadow_logger 存在时调用 record_polling。"""
        trader = _make_stub_trader()
        mock_logger = MagicMock()
        trader._shadow_logger = mock_logger

        inference = {"snapshot": {"level_smooth": 0.5}}
        actual_params = {"direction": "LONG", "confidence": 0.8}

        with patch("scripts.memory_l4.polling_trader.SHADOW_LOGGER_ENABLED", True):
            trader._record_shadow_log("BTC", inference, actual_params)

        # 现在新增了 enable_inject / alpha_blend kwargs，兼容只看前 3 个位置参数
        assert mock_logger.record_polling.call_count == 1
        pos_args, kw_args = mock_logger.record_polling.call_args
        assert pos_args[:3] == ("BTC", inference, actual_params)
        assert "enable_inject" in kw_args
        assert "alpha_blend" in kw_args

    def test_record_shadow_log_swallows_exception(self):
        """T_B5.4: _record_shadow_log 异常时不影响主流程（不抛出）。"""
        trader = _make_stub_trader()
        mock_logger = MagicMock()
        mock_logger.record_polling.side_effect = RuntimeError("DB locked")
        trader._shadow_logger = mock_logger

        with patch("scripts.memory_l4.polling_trader.SHADOW_LOGGER_ENABLED", True):
            # 不应抛异常
            trader._record_shadow_log("BTC", {"snapshot": {}}, {"direction": "LONG"})

    def test_init_shadow_logger_failure_degrades_to_none(self):
        """T_B5.5: _init_shadow_logger 失败时降级为 None（不抛异常）。"""
        trader = _make_stub_trader()

        # 通过 patch 让 MorphCyclePredictor 构造抛异常（更可靠）
        with patch("scripts.memory_l4.polling_trader.SHADOW_LOGGER_ENABLED", True), \
             patch("scripts.memory_l4.bcrm2.morph_cycle_predictor.MorphCyclePredictor",
                   side_effect=RuntimeError("predictor init failed")):
            trader._init_shadow_logger()

        assert getattr(trader, "_shadow_logger", None) is None
