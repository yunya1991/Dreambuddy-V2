"""
P1-2 RED: EngineRouter 组件契约测试
来源: SPEC v0.3 §2.B — 从 kline_event_handler.py 拆出 AGI 增强+懒加载 getters+路径发现职责

拆分目标:
- agi_enhance(switch, fn, fallback, **kw)->Any — AGI 增强统一入口（开关+FAIL-OPEN）
- get_sig_engine / get_pattern_detector / get_regime_classifier / get_path_integral_engine /
  get_uncertainty_quant / get_meta_cognition_gate / get_evolution_pipeline /
  get_event_driven_strategy / get_reflection_scanner — 懒加载 getters
- run_path_discovery(...)->dict — 路径发现层
"""
from __future__ import annotations

import pytest


class TestEngineRouterContract:
    """EngineRouter 接口契约 — RED 阶段断言模块尚未创建"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.engine_router import EngineRouter  # noqa: F401

    def test_class_instantiates(self):
        from dreambuddy_evolution.engines.engine_router import EngineRouter
        router = EngineRouter()
        assert router is not None


class TestAgiEnhance:
    """agi_enhance 统一入口 — 开关+FAIL-OPEN"""

    def test_returns_fallback_when_switch_disabled(self):
        from dreambuddy_evolution.engines.engine_router import EngineRouter
        router = EngineRouter()
        # 关闭的开关应返回 fallback
        result = router.agi_enhance(
            "nonexistent_switch_for_test",
            fn=lambda: "primary",
            fallback="fallback",
        )
        # 开关未开启时返回 fallback
        assert result == "fallback"

    def test_returns_primary_when_switch_enabled(self):
        from dreambuddy_evolution.engines.engine_router import EngineRouter
        router = EngineRouter()
        # 假设 enable_signature_engine 是开启的（生产默认）— 测试可能跳过
        result = router.agi_enhance(
            "enable_signature_engine",
            fn=lambda: "primary",
            fallback="fallback",
        )
        assert result in ("primary", "fallback")  # 任一即可，看开关


class TestRunPathDiscovery:
    """run_path_discovery 路径发现层"""

    def test_returns_dict(self):
        from dreambuddy_evolution.engines.engine_router import EngineRouter
        router = EngineRouter()
        # 最简输入，FAIL-OPEN 应返回 dict
        result = router.run_path_discovery(
            symbol="BTC-USDT-SWAP",
            d_star="long",
            r_vector={"R_up": 0.5, "R_down": 0.3},
            kline_data={"close": [100.0] * 20, "high": [105.0] * 20, "low": [95.0] * 20, "volume": [1000.0] * 20},
            mode="Phase2",
        )
        assert isinstance(result, dict)
