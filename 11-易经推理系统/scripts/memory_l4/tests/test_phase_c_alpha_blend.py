"""T_C1 验收测试：ParameterMapper α blend 增强

位置: scripts/memory_l4/tests/test_phase_c_alpha_blend.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_phase_c_alpha_blend.py -v

对应 Plan §T_C1: ParameterMapper α blend 增强。

核心验证：
  • alpha_blend=0.0 时字节等价（无偏不变量）
  • forecast_L=None 时不 blend
  • alpha_blend=1.0 时完全用 forecast
  • alpha_blend=0.5 时线性混合
  • map_sector_weights 同样支持
  • alpha_blend 超出 [0,1] 被 clip
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2.parameter_mapper import ParameterMapper


# ================================================================
# 测试 fixtures
# ================================================================

@pytest.fixture
def mapper() -> ParameterMapper:
    return ParameterMapper()


_SECTOR_BETAS = {
    "defi": (1.0, 0.0, 0.5),
    "ai": (1.0, 0.0, 0.5),
    "rwa": (1.0, 0.0, 0.5),
    "meme": (1.0, 0.0, 0.5),
    "l2": (1.0, 0.0, 0.5),
}


# ================================================================
# T_C1: ParameterMapper α blend 增强
# ================================================================

class TestAlphaBlend:
    """验证 ParameterMapper 的 α blend 功能。"""

    def test_alpha_zero_byte_equivalent(self, mapper):
        """T_C1.1: alpha_blend=0.0 时输出与原版完全一致（字节等价）。"""
        L, T, C = 2.0, 1.0, 0.8
        # 原版调用（无 forecast 参数）
        result_original = mapper.map_global_parameters(L, T, C)
        # Phase C 调用（forecast 参数但 alpha=0）
        result_blend = mapper.map_global_parameters(
            L, T, C, forecast_L=3.0, forecast_T=-1.0, alpha_blend=0.0
        )
        assert result_original == result_blend

    def test_forecast_none_no_blend(self, mapper):
        """T_C1.2: forecast_L=None 时不 blend（输出不变）。"""
        L, T, C = 2.0, 1.0, 0.8
        result_original = mapper.map_global_parameters(L, T, C)
        # forecast_L=None, alpha=0.5 → 不应 blend L
        result_blend = mapper.map_global_parameters(
            L, T, C, forecast_L=None, forecast_T=None, alpha_blend=0.5
        )
        assert result_original == result_blend

    def test_alpha_one_uses_forecast(self, mapper):
        """T_C1.3: alpha_blend=1.0 时 L 完全用 forecast_L。"""
        C = 0.8
        # reactive: L=2.0, forecast: L=3.0, alpha=1.0 → effective L=3.0
        result_forecast = mapper.map_global_parameters(
            2.0, 1.0, C, forecast_L=3.0, forecast_T=0.5, alpha_blend=1.0
        )
        # 等价于直接用 L=3.0, T=0.5
        result_direct = mapper.map_global_parameters(3.0, 0.5, C)
        assert result_forecast == result_direct

    def test_alpha_half_linear_blend(self, mapper):
        """T_C1.4: alpha_blend=0.5 时 L = 0.5*reactive + 0.5*forecast。"""
        C = 0.8
        # reactive: L=2.0, forecast: L=4.0, alpha=0.5 → effective L=3.0
        result_blend = mapper.map_global_parameters(
            2.0, 0.0, C, forecast_L=4.0, forecast_T=0.0, alpha_blend=0.5
        )
        # 等价于直接用 L=3.0
        result_direct = mapper.map_global_parameters(3.0, 0.0, C)
        assert result_blend == result_direct

    def test_sector_weights_alpha_blend(self, mapper):
        """T_C1.5: map_sector_weights 同样支持 α blend。"""
        L, T, C = 2.0, 1.0, 0.8
        # alpha=0 → 与原版一致
        r_original = mapper.map_sector_weights(L, T, C, _SECTOR_BETAS)
        r_blend = mapper.map_sector_weights(
            L, T, C, _SECTOR_BETAS,
            forecast_L=3.0, forecast_T=-1.0, alpha_blend=0.0
        )
        # 兼容新结构 {weights, sector_tp_mult, sector_sl_mult}
        def _w(d):
            return d["weights"] if (isinstance(d, dict) and "weights" in d) else d

        w_original = _w(r_original)
        w_blend = _w(r_blend)
        # 权重应完全一致
        for sector in _SECTOR_BETAS:
            assert abs(w_original[sector] - w_blend[sector]) < 1e-9

    def test_alpha_clip_out_of_range(self, mapper):
        """T_C1.6: alpha_blend 超出 [0,1] 被 clip。"""
        L, T, C = 2.0, 1.0, 0.8
        # alpha=-0.5 → clip 到 0.0 → 与原版一致
        result_neg = mapper.map_global_parameters(
            L, T, C, forecast_L=3.0, alpha_blend=-0.5
        )
        result_zero = mapper.map_global_parameters(L, T, C)
        assert result_neg == result_zero

        # alpha=1.5 → clip 到 1.0 → 完全用 forecast
        result_big = mapper.map_global_parameters(
            L, T, C, forecast_L=3.0, forecast_T=0.5, alpha_blend=1.5
        )
        result_one = mapper.map_global_parameters(
            L, T, C, forecast_L=3.0, forecast_T=0.5, alpha_blend=1.0
        )
        assert result_big == result_one

    def test_both_L_and_T_blend(self, mapper):
        """T_C1.7: forecast_L 和 forecast_T 同时 blend。"""
        C = 0.8
        # reactive: L=1.0, T=2.0; forecast: L=3.0, T=-2.0; alpha=0.5
        # → effective: L=2.0, T=0.0
        result_blend = mapper.map_global_parameters(
            1.0, 2.0, C, forecast_L=3.0, forecast_T=-2.0, alpha_blend=0.5
        )
        result_direct = mapper.map_global_parameters(2.0, 0.0, C)
        assert result_blend == result_direct
