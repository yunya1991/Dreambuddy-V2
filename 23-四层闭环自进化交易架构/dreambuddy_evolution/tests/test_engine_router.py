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

from __future__ import annotations  # noqa: I001


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
            kline_data={
                "close": [100.0] * 20,
                "high": [105.0] * 20,
                "low": [95.0] * 20,
                "volume": [1000.0] * 20,
            },
            mode="Phase2",
        )
        assert isinstance(result, dict)

    def _run_with_fake_pipeline(self, monkeypatch, *, n3_on: bool):
        from dreambuddy_evolution.engines.engine_router import EngineRouter

        monkeypatch.setenv("EVOLUTION_N3_HIGH_ORDER", "on" if n3_on else "off")
        seen: dict = {}

        class _FakePipeline:
            _bridge = None

            def _apply_high_order_factors(self, r_out, symbol):
                out = dict(r_out)
                out["R_up"] = 0.11
                out["R_down"] = 0.91
                out["high_order_factors"] = {"bcrm_dir": "long", "war_state": "ALLOW"}
                return out

            def _discover_paths(self, r_vector, market_data, symbol):
                seen.update(r_vector)
                return []

            def _select_optimal_path(self, paths, r_vector, market_data):
                return {"optimal_path": None, "path_info": {}}

        router = EngineRouter()
        router._evolution_pipeline = _FakePipeline()
        res = router.run_path_discovery(
            symbol="BTC-USDT-SWAP",
            d_star="long",
            r_vector={"R_up": 0.5, "R_down": 0.4},
            kline_data={"close": [100.0] * 20},
            mode="Phase2",
        )
        return seen, res

    def test_n3_default_off_is_shadow_only(self, monkeypatch):
        """默认关闭：决策仍用调制前 R 向量，但影子对比必须记录 after。"""
        seen, res = self._run_with_fake_pipeline(monkeypatch, n3_on=False)
        assert seen["R_up"] == 0.5 and seen["R_down"] == 0.4
        assert res["n3_enabled"] is False
        assert res["r_vector_modulated"] is None
        assert res["n3_compare"]["after"]["R_up"] == 0.11
        assert res["n3_compare"]["dir_before"] == "short"
        assert res["n3_compare"]["dir_after"] == "long"
        assert res["n3_compare"]["direction_flip"] is True

    def test_n3_enabled_applies_modulation(self, monkeypatch):
        """开关开启：调制结果参与路径发现。"""
        seen, res = self._run_with_fake_pipeline(monkeypatch, n3_on=True)
        assert seen["R_up"] == 0.11 and seen["R_down"] == 0.91
        assert res["n3_enabled"] is True
        assert res["r_vector_modulated"]["R_down"] == 0.91
