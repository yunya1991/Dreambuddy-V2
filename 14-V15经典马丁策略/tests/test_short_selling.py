#!/usr/bin/env python3
"""
多空方向控制机制 — 测试套件
验证：
1. DirectionGate 三状态模型（LONG_PREFERRED / SHORT_ALLOWED / LONG_ONLY_FORCE）
2. 做空开仓/加仓/止盈/止损/平仓执行逻辑（Mock客户端）
3. strategy_params SHORT 方向止损逻辑
4. 向后兼容（V15_ALLOW_SHORT=false 时行为不变）
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

from direction_gate import (
    DirectionGate, MarketRegime, TradeDirection, GateResult,
    evaluate_direction, reset_gate,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. DirectionGate 三状态模型测试
# ═══════════════════════════════════════════════════════════════════════

class TestDirectionGateStates(unittest.TestCase):
    """DirectionGate 核心状态判断（MA128 + BTC风向标模型）"""

    def setUp(self):
        reset_gate()
        self.gate = DirectionGate(allow_short=True, buffer_pct=0.01)

    def test_long_preferred_price_above_daily_ma128(self):
        """BTC做空闸门未打开 → LONG_PREFERRED，只做多（默认保守）"""
        r = self.gate.evaluate(
            current_price=65000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[64000, 63500, 63000],
            btc_short_enabled=False,
        )
        self.assertEqual(r.regime, MarketRegime.LONG_PREFERRED)
        self.assertTrue(r.long_enabled)
        self.assertFalse(r.short_enabled)
        self.assertEqual(r.allowed_direction, TradeDirection.LONG_ONLY)

    def test_short_allowed_btc_gate_open_above_weekly(self):
        """BTC做空闸门打开 + 在周MA200上方 → SHORT_ALLOWED，允许做空"""
        r = self.gate.evaluate(
            current_price=58000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[59000, 58500, 58000],
            btc_short_enabled=True,
        )
        self.assertEqual(r.regime, MarketRegime.SHORT_ALLOWED)
        self.assertTrue(r.long_enabled)
        self.assertTrue(r.short_enabled)
        self.assertEqual(r.allowed_direction, TradeDirection.BOTH)

    def test_long_only_force_at_weekly_ma200(self):
        """跌至周线MA200 → LONG_ONLY_FORCE，强制做多"""
        r = self.gate.evaluate(
            current_price=54000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[54500, 54000, 53500],
            btc_short_enabled=True,
        )
        self.assertEqual(r.regime, MarketRegime.LONG_ONLY_FORCE)
        self.assertTrue(r.long_enabled)
        self.assertFalse(r.short_enabled)
        self.assertEqual(r.allowed_direction, TradeDirection.LONG_ONLY)

    def test_allow_short_false_always_long(self):
        """全局开关关闭 → 永远只做多"""
        gate = DirectionGate(allow_short=False)
        r = gate.evaluate(
            current_price=58000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[59000, 58500, 58000],
            btc_short_enabled=True,
        )
        self.assertEqual(r.regime, MarketRegime.LONG_PREFERRED)
        self.assertFalse(r.short_enabled)
        self.assertTrue(r.long_enabled)


class TestDirectionGateEdgeCases(unittest.TestCase):
    """DirectionGate 边界情况（MA128 + BTC风向标模型）"""

    def setUp(self):
        reset_gate()

    def test_data_insufficient_defaults_long(self):
        """MA数据不足 → 保守只做多"""
        gate = DirectionGate(allow_short=True)
        r = gate.evaluate(current_price=65000, daily_ma128=None, weekly_ma200=None)
        self.assertEqual(r.regime, MarketRegime.LONG_PREFERRED)
        self.assertFalse(r.short_enabled)

    def test_daily_ma128_none_only(self):
        """只有日MA128为None → 保守只做多（MA数据不足分支）"""
        gate = DirectionGate(allow_short=True)
        r = gate.evaluate(current_price=65000, daily_ma128=None, weekly_ma200=55000)
        self.assertEqual(r.regime, MarketRegime.LONG_PREFERRED)
        self.assertFalse(r.short_enabled)

    def test_buffer_zone_at_weekly_ma200(self):
        """周MA200缓冲带避免临界点频繁切换"""
        gate = DirectionGate(allow_short=True, buffer_pct=0.01)
        weekly_ma200 = 55000
        weekly_buffer = weekly_ma200 * 0.01  # 550

        # 刚好在周MA200+buffer内 → 强制做多（LONG_ONLY_FORCE）
        r = gate.evaluate(
            current_price=55400, daily_ma128=60000, weekly_ma200=weekly_ma200,
            recent_daily_closes=[55600, 55500, 55400],  # 最近收盘价55400 < 55550(=55000+550)
            btc_short_enabled=True,
        )
        self.assertEqual(r.regime, MarketRegime.LONG_ONLY_FORCE)
        self.assertFalse(r.short_enabled)

    def test_btc_gate_closed_always_long(self):
        """BTC做空闸门关闭 → 永远只做多（即便价格低于日MA128）"""
        gate = DirectionGate(allow_short=True)
        r = gate.evaluate(
            current_price=58000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[59000, 58500, 58000],
            btc_short_enabled=False,  # 闸门关闭
        )
        self.assertEqual(r.regime, MarketRegime.LONG_PREFERRED)
        self.assertFalse(r.short_enabled)

    def test_falls_back_no_recent_closes_uses_current(self):
        """无recent_daily_closes时回退到current_price判断周线位置"""
        gate = DirectionGate(allow_short=True)
        r = gate.evaluate(
            current_price=58000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=None,
            btc_short_enabled=True,
        )
        # 58000 > 周MA200(55000)+buffer(550) → 不在周线缓冲带内 → SHORT_ALLOWED
        self.assertEqual(r.regime, MarketRegime.SHORT_ALLOWED)
        self.assertTrue(r.short_enabled)

    def test_valid_breakdown_3_days_close_below_ma128(self):
        """_check_valid_breakdown: 连续3日收盘价低于MA128 → 有效跌破"""
        gate = DirectionGate(allow_short=True)
        self.assertTrue(gate._check_valid_breakdown(
            [61000, 60500, 59000, 58500, 58000], 60000
        ))
        self.assertFalse(gate._check_valid_breakdown(
            [61000, 60500, 60100], 60000  # 只有2日低于
        ))
        self.assertFalse(gate._check_valid_breakdown(
            [59000, 58000], 60000  # 不足3日
        ))


class TestGateResultDict(unittest.TestCase):
    """GateResult.to_dict() 序列化"""

    def test_to_dict_contains_all_fields(self):
        gate = DirectionGate(allow_short=True)
        r = gate.evaluate(current_price=65000, daily_ma128=60000, weekly_ma200=55000,
                          btc_short_enabled=False)
        d = r.to_dict()
        self.assertIn("regime", d)
        self.assertIn("allowed_direction", d)
        self.assertIn("short_enabled", d)
        self.assertIn("long_enabled", d)
        self.assertIn("daily_ma128", d)
        self.assertIn("weekly_ma200", d)
        self.assertIn("current_price", d)
        self.assertIn("reason", d)
        self.assertIn("price_vs_daily_ma128", d)
        self.assertIn("price_vs_weekly_ma200", d)

    def test_to_dict_short_enabled_true(self):
        gate = DirectionGate(allow_short=True)
        r = gate.evaluate(current_price=58000, daily_ma128=60000, weekly_ma200=55000,
                          btc_short_enabled=True)
        d = r.to_dict()
        self.assertTrue(d["short_enabled"])
        self.assertTrue(d["long_enabled"])


# ═══════════════════════════════════════════════════════════════════════
# 2. 做空执行逻辑测试（Mock OKX 客户端）
# ═══════════════════════════════════════════════════════════════════════

class TestShortPositionExecution(unittest.TestCase):
    """做空开仓/加仓/止盈/止损执行逻辑"""

    def setUp(self):
        """搭建 Mock 客户端和状态"""
        self.mock_client = MagicMock()
        self.mock_client.place_order.return_value = {"ok": True, "data": {"ordId": "test123"}}
        self.mock_client._get.return_value = {
            "code": "0", "data": [{"lotSz": "1", "ctVal": "0.01"}]
        }
        self.state = {
            "positions": {},
            "total_trades": 0,
            "total_wins": 0,
            "daily_pnl": 0.0,
            "consecutive_losses": 0,
        }

    def _make_short_decision(self, conf=75):
        """构造做空信号决策"""
        return {
            "action": "OPEN_BEAR",
            "confidence": conf,
            "vol_mult": 1.0,
            "reasons": ["测试做空信号"],
        }

    def _make_long_decision(self, conf=75):
        """构造做多信号决策"""
        return {
            "action": "OPEN_BULL",
            "confidence": conf,
            "vol_mult": 1.0,
            "reasons": ["测试做多信号"],
        }

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.LEVERAGE', 5.0)
    @patch('v15_trader.MAX_ADDONS', 3)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    @patch('v15_trader.calc_lot_sz', return_value=10)
    @patch('capital_manager.calculate_per_coin_allocation')
    def test_open_short_position_uses_sell_and_short_side(
        self, mock_alloc, mock_lot, mock_info, mock_params
    ):
        """做空开仓应使用 side=sell, pos_side=short"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 60000,
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 65000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": False,
            "daily_ma200": 65000,
            "daily_ema200": None,
            "weekly_ma200": 55000,
            "weekly_ema200": None,
            "above_daily_ma200": False,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 59000,
            "last_weekly_close": 58000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": {"direction": "BEAR_TREND"},
            "klines_4h": None,
        }
        mock_alloc.return_value = {
            "allowed": True,
            "base_usd": 100,
            "per_coin_budget": 500,
            "addon1_usd": 80,
            "addon2_usd": 60,
            "addon3_usd": 40,
            "adjustments": {"strength_mult": 1.0, "conf_mult": 1.0, "vol_adjust": 1.0,
                           "combined_mult": 1.0, "elder_ray_direction": "BEAR_TREND",
                           "elder_ray_ema_trend": "N/A", "elder_ray_strength": 0},
        }

        decision = self._make_short_decision(conf=75)
        result = v15_trader.execute_open_position(
            self.mock_client, "BTC", decision, self.state
        )

        self.assertTrue(result)
        # 验证下单参数：做空用 sell + short
        # execute_open_position 现在会挂 1 张开仓单 + 3 档加仓网格预挂单
        self.assertGreaterEqual(self.mock_client.place_order.call_count, 1)
        open_call = self.mock_client.place_order.call_args_list[0]
        self.assertEqual(open_call[1]["side"], "sell")
        self.assertEqual(open_call[1]["pos_side"], "short")

        # 验证持仓状态记录了方向
        pos = self.state["positions"]["BTC"]
        self.assertEqual(pos["direction"], "SHORT")

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.LEVERAGE', 5.0)
    @patch('v15_trader.MAX_ADDONS', 3)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    @patch('v15_trader.calc_lot_sz', return_value=10)
    @patch('capital_manager.calculate_capital_allocation')
    def test_addon_short_triggers_on_price_rise(
        self, mock_capital, mock_lot, mock_info, mock_params
    ):
        """做空加仓：价格上涨时触发（反向马丁）"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 64800,  # 价格从60000涨到64800（涨8%）
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 65000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": False,
            "daily_ma200": 65000,
            "daily_ema200": None,
            "weekly_ma200": 55000,
            "weekly_ema200": None,
            "above_daily_ma200": False,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 59000,
            "last_weekly_close": 58000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": None,
            "klines_4h": None,
        }
        mock_capital.return_value = {
            "recommendations": {"allow_addon": True},
            "single_position_cost": {"base_usd": 100},
        }

        pos = {
            "inst_id": "BTC-USDT-SWAP",
            "direction": "SHORT",
            "entry_price": 60000,
            "open_price": 60000,
            "sz": 10,
            "addons": 0,
            "vol_mult": 1.0,
            "addon1_usd": 80,
            "addon2_usd": 60,
            "addon3_usd": 40,
        }

        result = v15_trader.execute_addon(self.mock_client, "BTC", pos, self.state)

        self.assertTrue(result)
        # 做空加仓用 sell + short
        call_kwargs = self.mock_client.place_order.call_args
        self.assertEqual(call_kwargs[1]["side"], "sell")
        self.assertEqual(call_kwargs[1]["pos_side"], "short")
        self.assertEqual(pos["addons"], 1)

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    def test_addon_short_skipped_when_price_not_rising(
        self, mock_info, mock_params
    ):
        """做空加仓：价格未上涨到加仓间距时跳过"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 62000,  # 只涨了3.3%，未到8%间距
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 65000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": False,
            "daily_ma200": 65000,
            "daily_ema200": None,
            "weekly_ma200": 55000,
            "weekly_ema200": None,
            "above_daily_ma200": False,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 59000,
            "last_weekly_close": 58000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": None,
            "klines_4h": None,
        }

        pos = {
            "inst_id": "BTC-USDT-SWAP",
            "direction": "SHORT",
            "entry_price": 60000,
            "open_price": 60000,
            "sz": 10,
            "addons": 0,
            "vol_mult": 1.0,
            "addon1_usd": 80,
            "addon2_usd": 60,
            "addon3_usd": 40,
        }

        with patch('capital_manager.calculate_capital_allocation') as mock_cap:
            mock_cap.return_value = {
                "recommendations": {"allow_addon": True},
                "single_position_cost": {"base_usd": 100},
            }
            result = v15_trader.execute_addon(self.mock_client, "BTC", pos, self.state)

        self.assertFalse(result)
        self.mock_client.place_order.assert_not_called()

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    def test_take_profit_short_uses_buy_side(
        self, mock_info, mock_params
    ):
        """做空止盈：价格下跌到止盈线，用 buy+short 平仓"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 57000,  # 从60000跌到57000，跌5% > 4%止盈
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 65000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": False,
            "daily_ma200": 65000,
            "daily_ema200": None,
            "weekly_ma200": 55000,
            "weekly_ema200": None,
            "above_daily_ma200": False,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 59000,
            "last_weekly_close": 58000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": None,
            "klines_4h": None,
        }

        pos = {
            "inst_id": "BTC-USDT-SWAP",
            "direction": "SHORT",
            "entry_price": 60000,
            "open_price": 60000,
            "sz": 10,
            "addons": 0,
        }
        self.state["positions"]["BTC"] = pos

        result = v15_trader.check_take_profit(self.mock_client, "BTC", pos, self.state)

        self.assertTrue(result)
        call_kwargs = self.mock_client.place_order.call_args
        # 做空平仓用 buy + short
        self.assertEqual(call_kwargs[1]["side"], "buy")
        self.assertEqual(call_kwargs[1]["pos_side"], "short")
        self.assertEqual(self.state["total_wins"], 1)
        self.assertNotIn("BTC", self.state["positions"])

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    def test_stop_loss_short_uses_buy_side(
        self, mock_info, mock_params
    ):
        """做空止损：止损触发，用 buy+short 平仓"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 66000,
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 65000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": True,  # 止损触发
            "daily_ma200": 65000,
            "daily_ema200": None,
            "weekly_ma200": 55000,
            "weekly_ema200": None,
            "above_daily_ma200": False,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 59000,
            "last_weekly_close": 58000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": None,
            "klines_4h": None,
        }

        pos = {
            "inst_id": "BTC-USDT-SWAP",
            "direction": "SHORT",
            "entry_price": 60000,
            "open_price": 60000,
            "sz": 10,
            "addons": 0,
        }
        self.state["positions"]["BTC"] = pos

        result = v15_trader.check_take_profit(self.mock_client, "BTC", pos, self.state)

        self.assertTrue(result)
        call_kwargs = self.mock_client.place_order.call_args
        self.assertEqual(call_kwargs[1]["side"], "buy")
        self.assertEqual(call_kwargs[1]["pos_side"], "short")
        self.assertEqual(self.state["consecutive_losses"], 1)


class TestLongBackwardCompatibility(unittest.TestCase):
    """做多方向向后兼容性验证"""

    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.place_order.return_value = {"ok": True, "data": {}}
        self.state = {"positions": {}, "total_trades": 0, "total_wins": 0,
                      "daily_pnl": 0.0, "consecutive_losses": 0}

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.LEVERAGE', 5.0)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    @patch('v15_trader.calc_lot_sz', return_value=10)
    @patch('capital_manager.calculate_per_coin_allocation')
    def test_open_long_uses_buy_and_long_side(
        self, mock_alloc, mock_lot, mock_info, mock_params
    ):
        """做多开仓仍使用 side=buy, pos_side=long"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 60000,
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 55000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": False,
            "daily_ma200": 55000,
            "daily_ema200": None,
            "weekly_ma200": 50000,
            "weekly_ema200": None,
            "above_daily_ma200": True,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 61000,
            "last_weekly_close": 60000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": {"direction": "BULL_TREND"},
            "klines_4h": None,
        }
        mock_alloc.return_value = {
            "allowed": True,
            "base_usd": 100,
            "per_coin_budget": 500,
            "addon1_usd": 80,
            "addon2_usd": 60,
            "addon3_usd": 40,
            "adjustments": {"strength_mult": 1.0, "conf_mult": 1.0, "vol_adjust": 1.0,
                           "combined_mult": 1.0, "elder_ray_direction": "BULL_TREND",
                           "elder_ray_ema_trend": "N/A", "elder_ray_strength": 0},
        }

        decision = {"action": "OPEN_BULL", "confidence": 75, "vol_mult": 1.0, "reasons": []}
        result = v15_trader.execute_open_position(self.mock_client, "BTC", decision, self.state)

        self.assertTrue(result)
        # execute_open_position 现在会挂 1 张开仓单 + 3 档加仓网格预挂单
        self.assertGreaterEqual(self.mock_client.place_order.call_count, 1)
        open_call = self.mock_client.place_order.call_args_list[0]
        self.assertEqual(open_call[1]["side"], "buy")
        self.assertEqual(open_call[1]["pos_side"], "long")

        pos = self.state["positions"]["BTC"]
        self.assertEqual(pos["direction"], "LONG")

    @patch('v15_trader._get_dynamic_params')
    @patch('v15_trader.AUTO_EXECUTE', True)
    @patch('v15_trader.get_contract_info', return_value=(1, 0.01))
    def test_take_profit_long_uses_sell_side(
        self, mock_info, mock_params
    ):
        """做多止盈仍使用 side=sell, pos_side=long"""
        import v15_trader

        mock_params.return_value = {
            "current_price": 63000,  # 从60000涨到63000，涨5% > 4%止盈
            "take_profit_pct": 0.04,
            "addon_pct": 0.08,
            "stop_loss_price": 55000,
            "stop_loss_pct": 8.0,
            "stop_loss_type": "日MA200",
            "stop_loss_triggered": False,
            "daily_ma200": 55000,
            "daily_ema200": None,
            "weekly_ma200": 50000,
            "weekly_ema200": None,
            "above_daily_ma200": True,
            "above_daily_ema200": None,
            "above_weekly_ma200": True,
            "above_weekly_ema200": None,
            "last_daily_close": 61000,
            "last_weekly_close": 60000,
            "volatility": {"take_profit_pct": 4, "addon_pct": 8},
            "elder_ray": None,
            "klines_4h": None,
        }

        pos = {
            "inst_id": "BTC-USDT-SWAP",
            "direction": "LONG",
            "entry_price": 60000,
            "open_price": 60000,
            "sz": 10,
            "addons": 0,
        }
        self.state["positions"]["BTC"] = pos

        result = v15_trader.check_take_profit(self.mock_client, "BTC", pos, self.state)

        self.assertTrue(result)
        call_kwargs = self.mock_client.place_order.call_args
        self.assertEqual(call_kwargs[1]["side"], "sell")
        self.assertEqual(call_kwargs[1]["pos_side"], "long")


# ═══════════════════════════════════════════════════════════════════════
# 3. strategy_params SHORT 方向止损逻辑测试
# ═══════════════════════════════════════════════════════════════════════

class TestShortStopLossLogic(unittest.TestCase):
    """做空方向止损逻辑验证"""

    def test_short_stop_loss_above_current_price(self):
        """做空止损线在价格上方"""
        from strategy_params import get_dynamic_stop_loss

        result = get_dynamic_stop_loss(
            direction="SHORT",
            current_price=60000,
            daily_ma200=65000,
            daily_ema200=64000,
            weekly_ma200=55000,
            weekly_ema200=54000,
            last_daily_close=59000,
            last_weekly_close=58000,
        )
        # 止损线应在价格上方（选择距离最近的上方均线）
        self.assertIsNotNone(result["stop_loss_price"])
        self.assertGreater(result["stop_loss_price"], 60000)
        # 64000（日EMA200）比65000（日MA200）更近
        self.assertEqual(result["stop_loss_price"], 64000)
        self.assertEqual(result["stop_type"], "日EMA200")

    def test_short_stop_loss_triggered_when_close_above(self):
        """做空止损触发：收盘价 >= 止损线"""
        from strategy_params import get_dynamic_stop_loss

        result = get_dynamic_stop_loss(
            direction="SHORT",
            current_price=60000,
            daily_ma200=65000,
            daily_ema200=64000,
            weekly_ma200=55000,
            weekly_ema200=54000,
            last_daily_close=64500,  # 收盘价超过日EMA200(64000)
            last_weekly_close=58000,
        )
        self.assertTrue(result["is_triggered"])

    def test_short_stop_loss_not_triggered_when_close_below(self):
        """做空止损未触发：收盘价 < 止损线"""
        from strategy_params import get_dynamic_stop_loss

        result = get_dynamic_stop_loss(
            direction="SHORT",
            current_price=60000,
            daily_ma200=65000,
            daily_ema200=64000,
            weekly_ma200=55000,
            weekly_ema200=54000,
            last_daily_close=63500,  # 收盘价未超过日EMA200(64000)
            last_weekly_close=58000,
        )
        self.assertFalse(result["is_triggered"])

    def test_short_stop_loss_all_ma_below_triggered(self):
        """做空：所有均线都在价格下方 → 无条件止损"""
        from strategy_params import get_dynamic_stop_loss

        result = get_dynamic_stop_loss(
            direction="SHORT",
            current_price=70000,
            daily_ma200=65000,
            daily_ema200=64000,
            weekly_ma200=55000,
            weekly_ema200=54000,
            last_daily_close=69000,
            last_weekly_close=68000,
        )
        self.assertTrue(result["is_triggered"])
        self.assertEqual(result["stop_type"], "ABOVE_ALL_MA")


# ═══════════════════════════════════════════════════════════════════════
# 4. 方向状态转移完整性测试
# ═══════════════════════════════════════════════════════════════════════

class TestStateTransitions(unittest.TestCase):
    """多空状态转移场景测试（MA128 + BTC风向标模型）"""

    def setUp(self):
        reset_gate()
        self.gate = DirectionGate(allow_short=True)

    def test_transition_long_to_short_allowed(self):
        """从做多优先转为允许做空（BTC做空闸门打开）"""
        # 第1步：BTC做空闸门关闭 → LONG_PREFERRED
        r1 = self.gate.evaluate(
            current_price=65000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[64000, 63500, 63000],
            btc_short_enabled=False,
        )
        self.assertEqual(r1.regime, MarketRegime.LONG_PREFERRED)
        self.assertFalse(r1.short_enabled)

        # 第2步：BTC做空闸门打开 → SHORT_ALLOWED
        r2 = self.gate.evaluate(
            current_price=58000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[59000, 58500, 58000],
            btc_short_enabled=True,
        )
        self.assertEqual(r2.regime, MarketRegime.SHORT_ALLOWED)
        self.assertTrue(r2.short_enabled)

    def test_transition_short_to_long_only_force(self):
        """从允许做空转为强制做多（跌至周MA200）"""
        r = self.gate.evaluate(
            current_price=54000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[54500, 54000, 53500],
            btc_short_enabled=True,
        )
        self.assertEqual(r.regime, MarketRegime.LONG_ONLY_FORCE)
        self.assertFalse(r.short_enabled)
        self.assertTrue(r.long_enabled)

    def test_transition_recovery_to_long_preferred(self):
        """恢复到做多优先（BTC做空闸门关闭）"""
        # BTC做空闸门关闭 → LONG_PREFERRED
        r = self.gate.evaluate(
            current_price=62000, daily_ma128=60000, weekly_ma200=55000,
            recent_daily_closes=[61500, 61000, 60500],
            btc_short_enabled=False,
        )
        self.assertEqual(r.regime, MarketRegime.LONG_PREFERRED)
        self.assertFalse(r.short_enabled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
