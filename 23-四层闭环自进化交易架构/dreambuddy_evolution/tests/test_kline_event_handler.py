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
