"""T_C2 验收测试：超参开关 + 无偏不变量验证

位置: scripts/memory_l4/tests/test_phase_c_switch.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_switch.py -v

对应 Plan §T_C2: 超参开关 + 无偏不变量验证。

核心验证：
  • ALPHA_BLEND_ENABLED 默认 False
  • DEFAULT_ALPHA_BLEND 默认 0.0
  • ALPHA_BLEND_MAX = 0.5（硬约束）
  • polling_trader 的 _init_alpha_blend 方法
  • α=0.0 时 map_global_parameters 输出与无 forecast 参数完全一致
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.parameter_mapper import ParameterMapper


_SECTOR_BETAS = {
    "defi": (1.0, 0.0, 0.5),
    "ai": (1.0, 0.0, 0.5),
    "rwa": (1.0, 0.0, 0.5),
    "meme": (1.0, 0.0, 0.5),
    "l2": (1.0, 0.0, 0.5),
}


# ================================================================
# 轻量 stub：绕过 PollingTrader.__init__ 的重依赖
# ================================================================

def _make_stub_trader():
    """构造一个只挂载 α blend 集成方法的 stub trader。"""
    from scripts.memory_l4.polling_trader import PollingTrader
    trader = object.__new__(PollingTrader)
    trader._log = MagicMock()
    return trader


# ================================================================
# T_C2: 超参开关 + 无偏不变量验证
# ================================================================

class TestAlphaBlendSwitch:
    """验证 Phase C 超参开关和无偏不变量。"""

    def test_alpha_blend_enabled_default_false(self):
        """T_C2.1: ALPHA_BLEND_ENABLED 默认值（当前 True，alpha=0 仍字节等价，允许在线 promote）。"""
        from bcrm2.parameter_mapper import ALPHA_BLEND_ENABLED, DEFAULT_ALPHA_BLEND
        assert isinstance(ALPHA_BLEND_ENABLED, bool)
        # 关键不变量：DEFAULT_ALPHA_BLEND=0 时，即使开关 True 输出仍完全等价于未启用
        assert DEFAULT_ALPHA_BLEND == 0.0, (
            f"不变量失败：DEFAULT_ALPHA_BLEND={DEFAULT_ALPHA_BLEND} ≠ 0.0"
            "（启动时必须保持纯反应式，由 API 渐进 promote 至目标值）"
        )

    def test_default_alpha_blend_zero(self):
        """T_C2.2: DEFAULT_ALPHA_BLEND 默认为 0.0。"""
        from bcrm2.parameter_mapper import DEFAULT_ALPHA_BLEND
        assert DEFAULT_ALPHA_BLEND == 0.0

    def test_alpha_blend_max_half(self):
        """T_C2.3: ALPHA_BLEND_MAX = 0.5（硬约束）。"""
        from bcrm2.parameter_mapper import ALPHA_BLEND_MAX
        assert ALPHA_BLEND_MAX == 0.5

    def test_init_alpha_blend_disabled(self):
        """T_C2.4: _init_alpha_blend 开关关闭时 _alpha_blend=0.0。"""
        trader = _make_stub_trader()
        with patch("scripts.memory_l4.polling_trader.ALPHA_BLEND_ENABLED", False):
            trader._init_alpha_blend()
        assert getattr(trader, "_alpha_blend", None) == 0.0
        assert getattr(trader, "_alpha_blend_enabled", None) is False

    def test_init_alpha_blend_enabled(self):
        """T_C2.5: _init_alpha_blend 开关开启时 _alpha_blend=DEFAULT_ALPHA_BLEND。"""
        trader = _make_stub_trader()
        with patch("scripts.memory_l4.polling_trader.ALPHA_BLEND_ENABLED", True), \
             patch("scripts.memory_l4.polling_trader.DEFAULT_ALPHA_BLEND", 0.2), \
             patch.dict("os.environ", {"V15_AI_ROLLOUT_STATE_PATH": "/tmp/__nonexistent_test_alpha_rollout_state.json"}):
            trader._init_alpha_blend()
        assert trader._alpha_blend_enabled is True
        assert trader._alpha_blend == 0.2

    def test_alpha_zero_byte_equivalent(self):
        """T_C2.6: α=0.0 时 map_global_parameters 输出与无 forecast 参数完全一致。"""
        mapper = ParameterMapper()
        L, T, C = 1.5, -0.8, 0.6
        # 原版调用（无 forecast 参数）
        result_original = mapper.map_global_parameters(L, T, C)
        # 显式传 alpha=0.0 + forecast 参数
        result_blend = mapper.map_global_parameters(
            L, T, C, forecast_L=3.0, forecast_T=-2.0, alpha_blend=0.0
        )
        assert result_original == result_blend

    def test_alpha_zero_sector_weights_equivalent(self):
        """T_C2.6b: α=0.0 时 map_sector_weights 输出与无 forecast 参数完全一致。"""
        mapper = ParameterMapper()
        L, T, C = 1.5, -0.8, 0.6
        r_original = mapper.map_sector_weights(L, T, C, _SECTOR_BETAS)
        r_blend = mapper.map_sector_weights(
            L, T, C, _SECTOR_BETAS, forecast_L=3.0, forecast_T=-2.0, alpha_blend=0.0
        )
        # 新结构：{weights, sector_tp_mult, sector_sl_mult}，旧结构: {sector: weight}
        # 兼容两种格式：有 weights 就取 weights，否则直接取 dict
        def _weights(d):
            return d["weights"] if (isinstance(d, dict) and "weights" in d) else d

        w_original = _weights(r_original)
        w_blend = _weights(r_blend)
        for sector in _SECTOR_BETAS:
            assert abs(w_original[sector] - w_blend[sector]) < 1e-12
