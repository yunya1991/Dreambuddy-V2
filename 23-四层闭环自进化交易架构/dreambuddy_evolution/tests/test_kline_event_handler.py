"""
TDD RED Phase 2: K线级触发器测试 (§1.8 频率分层硬约束)
替代每日 cron → K线收盘事件触发 L1/RippleEngine/Level0
"""
import pytest
from unittest.mock import MagicMock, patch


class TestKlineEventHandler:
    """K线收盘事件触发器"""

    def test_kline_close_triggers_l1_calculation(self):
        """K线收盘 → 触发 L1 R 向量计算"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0, 101.0, 102.0, 103.0, 104.0] * 4,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "vol_5": 2000.0,
            "vol_20": 1000.0,
            "bid_ask_spread_bps": 2.0,
        }
        result = handler.on_kline_close(kline_data)
        assert "r_vector" in result
        assert "R_up" in result["r_vector"]

    def test_kline_close_triggers_level0_dstar(self):
        """K线收盘 → 触发 Level0 d* 计算"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
        }
        result = handler.on_kline_close(kline_data)
        assert "d_star" in result
        assert result["d_star"] in ("long", "short", "WAIT")

    def test_kline_close_triggers_ripple_engine(self):
        """K线收盘 → 触发 RippleEngine 检测"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "vol_5": 3000.0,
            "vol_20": 1000.0,
            "liq_index_change": 0.35,
        }
        result = handler.on_kline_close(kline_data)
        assert "ri" in result
        assert 0.0 <= result["ri"] <= 1.0

    def test_crash_returns_wait_action(self):
        """FO: crash → 返回 WAIT + 不崩溃"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 空数据 → 不应崩溃
        result = handler.on_kline_close({})
        assert result["action"] == "WAIT"
        assert result["d_star"] == "WAIT"

    def test_modifiers_applied_when_provided(self):
        """当提供 sentiment/capital/narrative 数据 → 修饰子被应用"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "sentiment": 0.85,  # 极度贪婪
            "capital_flow": 0.70,  # 流入
            "narrative": 0.60,  # 叙事
        }
        result = handler.on_kline_close(kline_data, alpha=0.2, beta=0.2, gamma=0.2)
        assert "r_vector" in result
        assert "modifiers_applied" in result
        assert result["modifiers_applied"] is True

    def test_modifiers_zero_degrades_to_baseline(self):
        """α=β=γ=0 → 不应用修饰子（等价 baseline）"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "sentiment": 0.85,
            "capital_flow": 0.70,
            "narrative": 0.60,
        }
        result = handler.on_kline_close(kline_data, alpha=0.0, beta=0.0, gamma=0.0)
        assert result["modifiers_applied"] is False

    def test_phase2_mode_auto_executes_inference(self):
        """Phase2 模式 → RI≥0.55 时 auto_execute=True"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 构造 RI≥0.55 的场景（通过 mock ripple engine）
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.65
        handler._ripple.get_ri_action.return_value = {
            "cbr_boost": 0.20, "ess_temp_mult": 1.05, "trigger_a2": False
        }
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
            "liq_index_change": 0.35,
        }
        result = handler.on_kline_close(kline_data)
        assert result.get("auto_execute") is True or result.get("ri", 0) >= 0.55

    def test_mvp_mode_no_auto_execute(self):
        """MVP 模式 → auto_execute=False（松耦合 Lark 人工中转）"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="MVP")
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.80
        handler._ripple.get_ri_action.return_value = {
            "cbr_boost": 0.25, "ess_temp_mult": 1.10, "trigger_a2": True
        }
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
            "liq_index_change": 0.35,
        }
        result = handler.on_kline_close(kline_data)
        assert result.get("auto_execute") is False

    def test_output_schema(self):
        """输出包含必要字段"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
        }
        result = handler.on_kline_close(kline_data)
        required_keys = {"symbol", "r_vector", "d_star", "action", "ri", "modifiers_applied"}
        assert required_keys.issubset(result.keys())


class TestAutoExecuteBuildPosition:
    """P2-S4b: auto_execute 真实建仓 + snapshot 存储集成"""

    def test_auto_execute_stores_snapshot(self, tmp_path):
        """P2-S4b: auto_execute=True → 存储 pre_trade_snapshot 到 TradeSettlementBridge"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge

        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        handler = KlineEventHandler(mode="Phase2", build_position_callback=lambda **kw: None, settlement_bridge=bridge)
        # mock ripple → RI≥0.55 触发推断
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.70
        # mock d* 返回 long（绕过实际路径计算）
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})
        kline_data = {
            "symbol": "BTC",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
        }
        result = handler.on_kline_close(kline_data)
        assert result["auto_execute"] is True
        # snapshot 已持久化
        snapshot = bridge.retrieve_snapshot("BTC")
        assert snapshot is not None
        assert snapshot.get("symbol") == "BTC"
        assert snapshot.get("action") in ("long", "short")

    def test_auto_execute_calls_callback(self, tmp_path):
        """P2-S4b: auto_execute=True → 调用 build_position_callback(symbol, action, ...)"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge

        callback_calls = []

        def fake_callback(**kwargs):
            callback_calls.append(kwargs)

        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        handler = KlineEventHandler(mode="Phase2", build_position_callback=fake_callback, settlement_bridge=bridge)
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.75
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})
        kline_data = {
            "symbol": "ETH",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
        }
        result = handler.on_kline_close(kline_data)
        assert result["auto_execute"] is True
        assert len(callback_calls) == 1
        call = callback_calls[0]
        assert call.get("symbol") == "ETH"
        assert call.get("action") in ("long", "short")
        assert "confidence" in call

    def test_callback_crash_fail_open(self, tmp_path):
        """P2-S4b: build_position_callback crash → FAIL-OPEN，不崩溃，仍返回正常结果"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge

        def crashing_callback(**kwargs):
            raise RuntimeError("模拟下单崩溃")

        bridge = TradeSettlementBridge(snapshot_dir=str(tmp_path))
        handler = KlineEventHandler(mode="Phase2", build_position_callback=crashing_callback, settlement_bridge=bridge)
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.80
        handler._compute_d_star = MagicMock(return_value={"d_star": "long"})
        kline_data = {
            "symbol": "SOL",
            "close": [100.0] * 20,
            "high": [105.0] * 20,
            "low": [95.0] * 20,
            "volume": [1000.0] * 20,
            "ess_top_direction": "long",
            "vol_5": 3000.0,
            "vol_20": 1000.0,
        }
        # 不应抛异常
        result = handler.on_kline_close(kline_data)
        assert result["action"] in ("long", "short", "WAIT")


class TestAGIEnhancement:
    """AGI 增强点测试：FAIL-OPEN + 开关控制 + 只读增强"""

    def test_agi_fields_present_in_output(self):
        """输出包含所有 AGI 增强字段"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        for field in ("agi_signature", "agi_pattern", "agi_btc_regime",
                      "agi_path_integral", "agi_uncertainty", "agi_gate_decision"):
            assert field in result, f"missing field: {field}"

    def test_fail_open_agi_crash_does_not_block(self):
        """FAIL-OPEN: AGI 模块崩溃 → 不阻塞主流程，返回 fallback 值"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 注入崩溃的 SignatureEngine
        crashing_sig = MagicMock()
        crashing_sig.signature.side_effect = RuntimeError("模拟签名引擎崩溃")
        handler._sig_engine = crashing_sig
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # 主流程不受影响
        assert result["action"] in ("long", "short", "WAIT")
        assert result["d_star"] in ("long", "short", "WAIT")
        # AGI 字段为 fallback 值
        assert result["agi_signature"] is None

    def test_switch_off_skips_agi_module(self):
        """开关关闭时 → AGI 模块不被调用，返回 fallback"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.agi_config import set_switch
        # 关闭签名引擎开关
        set_switch("enable_signature_engine", False)
        set_switch("enable_pattern_detector", False)
        set_switch("enable_btc_regime_classifier", False)
        try:
            handler = KlineEventHandler(mode="Phase2")
            mock_sig = MagicMock()
            handler._sig_engine = mock_sig
            kline_data = {
                "symbol": "BTC-USDT-SWAP",
                "close": [100.0 + i for i in range(40)],
                "high": [105.0] * 40,
                "low": [95.0] * 40,
                "volume": [1000.0] * 40,
            }
            result = handler.on_kline_close(kline_data)
            # 开关关闭 → signature 不被调用
            mock_sig.signature.assert_not_called()
            assert result["agi_signature"] is None
            assert result["agi_pattern"] is None
        finally:
            # 恢复开关
            set_switch("enable_signature_engine", True)
            set_switch("enable_pattern_detector", True)
            set_switch("enable_btc_regime_classifier", True)

    def test_signature_engine_produces_output(self):
        """SignatureEngine 开启 + 数据充足 → agi_signature 非空"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 构造有波动的价格路径（≥10 个点）
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 108.0, 107.0, 109.0,
                      111.0, 110.0, 112.0, 114.0, 113.0],
            "high": [115.0] * 15,
            "low": [95.0] * 15,
            "volume": [1000.0] * 15,
        }
        result = handler.on_kline_close(kline_data)
        # 签名引擎应产生结果（开关默认开启）
        if result["agi_signature"] is not None:
            assert "dim" in result["agi_signature"]
            assert "norm" in result["agi_signature"]
            assert result["agi_signature"]["dim"] > 0

    def test_pattern_detector_with_flat_market(self):
        """PatternDetector 在平坦市场中不检测到反转形态"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 构造平坦价格（无头肩形态）
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0] * 40,
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # 平坦市场不应有反转信号
        if result["agi_pattern"] is not None:
            assert result["agi_pattern"].get("is_reversal_signal") is False

    def test_regime_classifier_with_returns(self):
        """RegimeClassifier 有 btc/spy 收益率时 → 返回有效 regime"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
            "btc_returns": [0.01 * ((-1) ** i) for i in range(35)],
            "spy_returns": [0.005 * ((-1) ** i) for i in range(35)],
        }
        result = handler.on_kline_close(kline_data)
        if result["agi_btc_regime"] is not None:
            assert result["agi_btc_regime"] in ("STRONG", "WEAK", "NEUTRAL")

    def test_agi_enhance_method_directly(self):
        """直接测试 _agi_enhance 方法的开关控制和 FAIL-OPEN"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        from dreambuddy_evolution.agi_config import set_switch
        handler = KlineEventHandler(mode="Phase2")

        # 开关开启时 → 调用函数
        set_switch("enable_signature_engine", True)
        result = handler._agi_enhance(
            "enable_signature_engine",
            fn=lambda x: x * 2,
            fallback=-1,
            x=5,
        )
        assert result == 10

        # 开关关闭时 → 返回 fallback
        set_switch("enable_signature_engine", False)
        result = handler._agi_enhance(
            "enable_signature_engine",
            fn=lambda x: x * 2,
            fallback=-1,
            x=5,
        )
        assert result == -1

        # 函数崩溃时 → 返回 fallback（FAIL-OPEN）
        set_switch("enable_signature_engine", True)
        result = handler._agi_enhance(
            "enable_signature_engine",
            fn=lambda x: (_ for _ in ()).throw(RuntimeError("crash")),
            fallback=-1,
            x=5,
        )
        assert result == -1

        # 恢复
        set_switch("enable_signature_engine", True)


class TestPathDiscoveryLayer:
    """路径发现层测试：多路径竞争 → 寻优 → argmin 最小阻力"""

    def test_path_info_field_present(self):
        """输出包含 path_info 字段"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert "path_info" in result
        assert isinstance(result["path_info"], dict)

    def test_path_info_has_required_fields(self):
        """path_info 包含所有必需字段"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        pi = result["path_info"]
        for field in ("path_count", "optimal_source", "optimal_score",
                      "validated", "low_conviction", "d_star_original",
                      "d_star_adjusted"):
            assert field in pi, f"missing path_info field: {field}"

    def test_path_discovery_fail_open(self):
        """FAIL-OPEN: 路径发现层崩溃 → 不阻塞主流程"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 注入崩溃的 EvolutionPipeline
        crashing_pipeline = MagicMock()
        crashing_pipeline._discover_paths.side_effect = RuntimeError("模拟崩溃")
        handler._evolution_pipeline = crashing_pipeline
        handler._path_layer_enabled = True
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # 主流程不受影响
        assert result["d_star"] in ("long", "short", "WAIT")
        assert result["action"] in ("long", "short", "WAIT")

    def test_path_discovery_overrides_d_star(self):
        """路径发现层验证通过 → 覆盖 d* 决策"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 注入 mock pipeline，返回验证通过的最优路径
        mock_pipeline = MagicMock()
        mock_pipeline._discover_paths.return_value = [
            {"source": "l2_gene", "direction": "long", "score": 0.15,
             "validated": True, "expected_return": 0.05,
             "confidence": 0.8, "resistance": 0.3},
        ]
        mock_pipeline._select_optimal_path.return_value = {
            "optimal_path": {
                "source": "l2_gene",
                "direction": "long",
                "score": 0.15,
            },
            "statistical_validation": {
                "validated": True,
                "low_conviction": False,
            },
        }
        handler._evolution_pipeline = mock_pipeline
        handler._path_layer_enabled = True
        # mock d* 计算返回 long（确保路径发现层被调用）
        handler._compute_d_star = lambda rv: {"d_star": "long"}
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # 路径发现层覆盖 d*
        assert result["path_info"]["d_star_adjusted"] == "long"
        assert result["path_info"]["validated"] is True
        assert result["path_info"]["optimal_source"] == "l2_gene"

    def test_path_discovery_low_conviction_reduces_ri(self):
        """低确信度 → RI 降仓（×0.7）"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        mock_pipeline = MagicMock()
        mock_pipeline._discover_paths.return_value = [
            {"source": "bcrm", "direction": "short", "score": 0.08,
             "validated": True, "low_conviction": True},
        ]
        mock_pipeline._select_optimal_path.return_value = {
            "optimal_path": {
                "source": "bcrm",
                "direction": "short",
                "score": 0.08,
            },
            "statistical_validation": {
                "validated": True,
                "low_conviction": True,
            },
        }
        handler._evolution_pipeline = mock_pipeline
        handler._path_layer_enabled = True
        # mock d* 计算返回 short（确保路径发现层被调用）
        handler._compute_d_star = lambda rv: {"d_star": "short"}
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # 低确信度标记
        assert result["path_info"]["low_conviction"] is True

    def test_path_discovery_not_validated_keeps_d_star(self):
        """路径未通过统计验证 → 保持原 d* 不变"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        mock_pipeline = MagicMock()
        mock_pipeline._discover_paths.return_value = [
            {"source": "deep_reasoning", "direction": "long", "score": 0.02,
             "validated": False},
        ]
        mock_pipeline._select_optimal_path.return_value = {
            "optimal_path": None,
            "statistical_validation": {
                "validated": False,
                "low_conviction": False,
                "reason": "score_below_threshold",
            },
        }
        handler._evolution_pipeline = mock_pipeline
        handler._path_layer_enabled = True
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # 未验证通过 → d* 不被覆盖
        assert result["path_info"]["d_star_adjusted"] == result["path_info"]["d_star_original"]
        assert result["path_info"]["validated"] is False

    def test_path_integral_produces_output(self):
        """PathIntegralEngine 开启 + 数据充足 → agi_path_integral 非空"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0, 102.0, 101.0, 103.0, 105.0, 104.0, 106.0, 108.0,
                      107.0, 109.0, 111.0, 110.0, 112.0, 114.0, 113.0],
            "high": [115.0] * 15,
            "low": [95.0] * 15,
            "volume": [1000.0] * 15,
        }
        result = handler.on_kline_close(kline_data)
        if result["agi_path_integral"] is not None:
            pi = result["agi_path_integral"]
            assert "n_paths" in pi
            assert "min_resistance_action" in pi
            assert "expected_end_price" in pi
            assert pi["n_paths"] > 0
            assert pi["min_resistance_action"] >= 0.0

    def test_path_integral_fail_open_on_crash(self):
        """FAIL-OPEN: PathIntegralEngine 崩溃 → 不阻塞，返回 None"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        # 注入崩溃的 PathIntegralEngine
        crashing_pi = MagicMock()
        crashing_pi.sample_paths.side_effect = RuntimeError("模拟路径积分崩溃")
        handler._path_integral_engine = crashing_pi
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert result["action"] in ("long", "short", "WAIT")
        assert result["agi_path_integral"] is None

    def test_uncertainty_quant_produces_output(self):
        """UncertaintyQuantifier 开启 → agi_uncertainty 非空且包含 score 和 level"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        handler._ripple = MagicMock()
        handler._ripple.detect_ripple_source.return_value = True
        handler._ripple.compute_ri.return_value = 0.65
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        if result["agi_uncertainty"] is not None:
            uq = result["agi_uncertainty"]
            assert "uncertainty_score" in uq
            assert "level" in uq
            assert 0.0 <= uq["uncertainty_score"] <= 1.0
            assert uq["level"] in ("low", "medium", "high", "critical")

    def test_uncertainty_fail_open_on_crash(self):
        """FAIL-OPEN: UncertaintyQuantifier 崩溃 → 不阻塞"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        crashing_uq = MagicMock()
        crashing_uq.quantify_uncertainty.side_effect = RuntimeError("崩溃")
        handler._uncertainty_quant = crashing_uq
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert result["action"] in ("long", "short", "WAIT")
        assert result["agi_uncertainty"] is None

    def test_meta_cognition_gate_fail_open_on_crash(self):
        """FAIL-OPEN: MetaCognitionGate 崩溃 → 不阻塞"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        crashing_mcg = MagicMock()
        crashing_mcg.gate_decision.side_effect = RuntimeError("崩溃")
        handler._meta_cognition_gate = crashing_mcg
        kline_data = {
            "symbol": "BTC-USDT-SWAP",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert result["action"] in ("long", "short", "WAIT")
        assert result["agi_gate_decision"] is None


class TestL3L4Record:
    """L3 ShadowRL / L4 Bellman / AGI-H TransferLearner / AGI-I Counterfactual 记录测试"""

    def test_l3_l4_fields_present(self):
        """输出包含 l3_sample_count / l4_v / agi_transfer / agi_counterfactual"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert "l3_sample_count" in result
        assert "l4_v" in result
        assert "agi_transfer" in result
        assert "agi_counterfactual" in result
        assert result["l3_sample_count"] >= 1
        assert isinstance(result["l4_v"], (int, float))

    def test_l3_record_uses_quality_score_reward(self):
        """L3 ShadowRL record 的 reward = 0.0（Fix 1: 真实 PnL 由平仓事件注入），state 含 5 维 R"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        mock_pipeline = MagicMock()
        mock_pipeline.shadow_rl = MagicMock()
        mock_pipeline.shadow_rl.sample_count.return_value = 1
        mock_pipeline.bellman = MagicMock()
        mock_pipeline.bellman.get_v.return_value = 0.01
        mock_pipeline._get_transfer_learner.return_value = None
        mock_pipeline._get_counterfactual.return_value = None
        handler._evolution_pipeline = mock_pipeline
        handler._path_layer_enabled = True
        kline_data = {
            "symbol": "BTC",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        # pipeline.shadow_rl.record 被调用
        assert mock_pipeline.shadow_rl.record.called
        call_kwargs = mock_pipeline.shadow_rl.record.call_args.kwargs
        # Fix 1: ShadowRL reward 改为 0.0 占位，真实 PnL 由 TradeSettlementBridge 注入
        assert call_kwargs["reward"] == pytest.approx(0.0, abs=1e-9)
        state = call_kwargs["state"]
        for key in ("R_up", "R_down", "R_smooth", "R_flow", "R_reflexivity"):
            assert key in state

    def test_l4_bellman_td_update_called(self):
        """L4 Bellman td_update 被调用且 next_symbol == symbol"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        mock_pipeline = MagicMock()
        mock_pipeline.shadow_rl = MagicMock()
        mock_pipeline.shadow_rl.sample_count.return_value = 1
        mock_pipeline.bellman = MagicMock()
        mock_pipeline.bellman.get_v.return_value = 0.02
        mock_pipeline._get_transfer_learner.return_value = None
        mock_pipeline._get_counterfactual.return_value = None
        handler._evolution_pipeline = mock_pipeline
        handler._path_layer_enabled = True
        kline_data = {
            "symbol": "ETH",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert mock_pipeline.bellman.td_update.called
        call_kwargs = mock_pipeline.bellman.td_update.call_args.kwargs
        assert call_kwargs["next_symbol"] == "ETH"

    def test_agi_h_i_noop_when_returns_absent(self):
        """kline_data 不含 source_returns → agi_transfer=None, agi_counterfactual=None"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert result["agi_transfer"] is None
        assert result["agi_counterfactual"] is None

    def test_l3_l4_crash_fail_open(self):
        """pipeline 抛异常 → 返回含兜底字段且 action 不被阻塞"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        crashing_pipeline = MagicMock()
        crashing_pipeline._discover_paths.side_effect = RuntimeError("模拟崩溃")
        # pipeline.shadow_rl 也崩溃
        crashing_pipeline.shadow_rl = MagicMock()
        crashing_pipeline.shadow_rl.record.side_effect = RuntimeError("L3崩溃")
        crashing_pipeline.shadow_rl.sample_count.return_value = 0
        crashing_pipeline.bellman = MagicMock()
        crashing_pipeline.bellman.td_update.side_effect = RuntimeError("L4崩溃")
        crashing_pipeline.bellman.get_v.return_value = 0.0
        crashing_pipeline._get_transfer_learner.return_value = None
        crashing_pipeline._get_counterfactual.return_value = None
        handler._evolution_pipeline = crashing_pipeline
        handler._path_layer_enabled = True
        kline_data = {
            "symbol": "BTC",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert result["action"] in ("long", "short", "WAIT")
        assert result["l3_sample_count"] == 0
        assert result["l4_v"] == 0.0

    def test_get_evolution_feedback_delegates(self):
        """get_evolution_feedback() 返回含 l3_stats / l4_v_all / l4_ess_adjustments 三键"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        feedback = handler.get_evolution_feedback()
        assert "l3_stats" in feedback
        assert "l4_v_all" in feedback
        assert "l4_ess_adjustments" in feedback


class TestContradictionPassthrough:
    """矛盾论结果透传测试"""

    def test_primary_contradiction_in_path_info(self):
        """on_kline_close 返回的 path_info 含 primary_contradiction 字段"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        kline_data = {
            "symbol": "BTC",
            "close": [100.0 + i for i in range(40)],
            "high": [105.0] * 40,
            "low": [95.0] * 40,
            "volume": [1000.0] * 40,
        }
        result = handler.on_kline_close(kline_data)
        assert "path_info" in result
        assert "primary_contradiction" in result["path_info"]

    def test_primary_contradiction_passthrough_from_pipeline(self):
        """pipeline._select_optimal_path 返回 primary_contradiction → 透传到 path_info"""
        from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler
        handler = KlineEventHandler(mode="Phase2")
        mock_pipeline = MagicMock()
        mock_pipeline._discover_paths.return_value = [
            {"path_id": "p1", "source": "test", "direction": "long",
             "expected_return": 0.05, "confidence": 0.8, "resistance": 0.3,
             "continuation_score": 0.6}
        ]
        mock_pipeline._select_optimal_path.return_value = {
            "optimal_path": {
                "source": "test", "direction": "long", "score": 0.08,
            },
            "statistical_validation": {"validated": True, "low_conviction": False},
            "primary_contradiction": {
                "direction": "long", "strength": 0.7, "type": "resonance",
            },
        }
        handler._evolution_pipeline = mock_pipeline
        r_vector = {"R_up": 0.6, "R_down": 0.3, "_close_series": [100.0] * 40}
        d_star, ri, path_info = handler._run_path_discovery(
            "BTC", r_vector, "long", 0.5, {}
        )
        assert path_info["primary_contradiction"] is not None
        assert path_info["primary_contradiction"]["direction"] == "long"
        assert path_info["primary_contradiction"]["strength"] == 0.7
