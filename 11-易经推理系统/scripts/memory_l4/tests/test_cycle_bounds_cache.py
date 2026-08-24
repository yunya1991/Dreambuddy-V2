"""T3 验收测试：边界缓存 _get_cycle_bounds()（T_CB7）

位置: scripts/memory_l4/tests/test_cycle_bounds_cache.py
运行: cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4 && python -m pytest tests/test_cycle_bounds_cache.py -v

对应 Spec §3bis.5.5 边界参数缓存策略 + §3bis.9 T_CB7。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add bcrm2 to sys.path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from bcrm2 import morph_cycle_predictor as mcp
from bcrm2.morph_cycle_predictor import MorphCyclePredictor, _CYCLE_BOUNDS_CACHE


def _make_predictor() -> MorphCyclePredictor:
    """构造 MorphCyclePredictor 实例（绕过 __init__ 的 storage 依赖）。"""
    return MorphCyclePredictor.__new__(MorphCyclePredictor)


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个测试前清理模块级缓存，避免测试间状态泄漏。"""
    _CYCLE_BOUNDS_CACHE.clear()
    yield
    _CYCLE_BOUNDS_CACHE.clear()


# ================================================================
# T_CB7: 边界缓存命中
# ================================================================

class TestCycleBoundsCacheHit:
    """验证同日同 symbol 多次 predict 时，_interp_cycle_bounds 只计算 1 次。"""

    def test_cache_hit_same_t_rel(self):
        """相同 t_rel 第二次调用应命中缓存，_interp_cycle_bounds 不重复计算。"""
        p = _make_predictor()
        # 构造一个 mock cycle_4y dict
        cycle_4y = {"t_rel_current": 486.0}

        # 计数器：拦截 _interp_cycle_bounds 调用次数
        call_count = {"n": 0}
        original = p._interp_cycle_bounds

        def counting_interp(t_rel):
            call_count["n"] += 1
            return original(t_rel)

        p._interp_cycle_bounds = counting_interp

        # 第一次调用：未命中缓存，触发计算
        b1 = p._get_cycle_bounds("BTCUSDT", cycle_4y)
        assert call_count["n"] == 1

        # 第二次调用：t_rel 相同，应命中缓存
        b2 = p._get_cycle_bounds("BTCUSDT", cycle_4y)
        assert call_count["n"] == 1, "第二次调用不应重复计算 _interp_cycle_bounds"

        # 两次返回的 bounds 应相同
        assert b1 == b2

    def test_cache_returns_valid_bounds_structure(self):
        """缓存返回的 bounds 包含所有必需字段。"""
        p = _make_predictor()
        cycle_4y = {"t_rel_current": 200.0}
        b = p._get_cycle_bounds("BTCUSDT", cycle_4y)

        required = {"t_rel_current", "phase_hint", "level_lo", "level_hi",
                    "level_mean", "amplitude_cap", "decay_strength"}
        assert set(b.keys()) == required

    def test_cache_per_symbol_isolated(self):
        """不同 symbol 的缓存相互隔离。"""
        p = _make_predictor()
        cycle_btc = {"t_rel_current": 486.0}
        cycle_eth = {"t_rel_current": 200.0}

        b_btc = p._get_cycle_bounds("BTCUSDT", cycle_btc)
        b_eth = p._get_cycle_bounds("ETHUSDT", cycle_eth)

        # 不同 symbol、不同 t_rel → 不同 phase_hint
        assert b_btc["phase_hint"] == "顶点"
        assert b_eth["phase_hint"] == "上升"


class TestCycleBoundsCacheInvalidation:
    """验证 t_rel 变化时缓存失效，重新计算。"""

    def test_cache_invalidation_on_t_rel_change(self):
        """t_rel 变化时缓存失效，_interp_cycle_bounds 重新计算。"""
        p = _make_predictor()

        call_count = {"n": 0}
        original = p._interp_cycle_bounds

        def counting_interp(t_rel):
            call_count["n"] += 1
            return original(t_rel)

        p._interp_cycle_bounds = counting_interp

        # 第一次：t_rel=486
        b1 = p._get_cycle_bounds("BTCUSDT", {"t_rel_current": 486.0})
        assert call_count["n"] == 1

        # 第二次：t_rel 变为 200，缓存应失效
        b2 = p._get_cycle_bounds("BTCUSDT", {"t_rel_current": 200.0})
        assert call_count["n"] == 2, "t_rel 变化应触发重新计算"

        # 两次结果不同
        assert b1["phase_hint"] == "顶点"
        assert b2["phase_hint"] == "上升"

    def test_cache_update_to_new_t_rel(self):
        """t_rel 变化后，新缓存条目生效，再次相同 t_rel 命中新缓存。"""
        p = _make_predictor()

        call_count = {"n": 0}
        original = p._interp_cycle_bounds

        def counting_interp(t_rel):
            call_count["n"] += 1
            return original(t_rel)

        p._interp_cycle_bounds = counting_interp

        # t_rel=486 → 计算
        p._get_cycle_bounds("BTCUSDT", {"t_rel_current": 486.0})
        assert call_count["n"] == 1

        # t_rel=200 → 重新计算
        p._get_cycle_bounds("BTCUSDT", {"t_rel_current": 200.0})
        assert call_count["n"] == 2

        # t_rel=200 再次 → 命中新缓存
        p._get_cycle_bounds("BTCUSDT", {"t_rel_current": 200.0})
        assert call_count["n"] == 2, "更新后的缓存应被命中"
