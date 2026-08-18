#!/usr/bin/env python3
"""
通用风控引擎 - 单元测试
========================
测试三层风控体系的核心功能。
"""

import sys
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import unittest
from datetime import datetime, timezone

from core.context import (
    Signal,
    PositionState,
    MarketSnapshot,
    RiskContext,
    RiskCheckResult,
    PositionSizeResult,
    ExitResult,
    ExitAction,
    ExitPriority,
    Direction,
    ReasonCode,
)
from core.registry import RuleRegistry, RuleCategory
from core.engine import RiskEngine


class TestRiskContext(unittest.TestCase):
    """测试风控上下文"""

    def test_basic_context(self):
        ctx = RiskContext(total_equity=10000)
        self.assertEqual(ctx.total_equity, 10000)
        self.assertEqual(ctx.daily_drawdown_pct, 0.0)
        self.assertEqual(ctx.win_rate, 0.0)
        self.assertEqual(ctx.active_positions_count, 0)

    def test_daily_drawdown(self):
        ctx = RiskContext(total_equity=10000)
        ctx.update_equity(9000)
        self.assertAlmostEqual(ctx.daily_drawdown_pct, 0.10, places=4)

    def test_consecutive_losses(self):
        ctx = RiskContext(total_equity=10000)
        ctx.record_trade({"pnl": -100})
        ctx.record_trade({"pnl": -50})
        self.assertEqual(ctx.consecutive_losses, 2)
        self.assertEqual(ctx.total_trades, 2)

    def test_win_reset_daily(self):
        ctx = RiskContext(total_equity=10000)
        ctx.record_trade({"pnl": -100})
        ctx.update_equity(9500)
        ctx.reset_daily()
        self.assertEqual(ctx.consecutive_losses, 0)
        self.assertEqual(ctx.daily_pnl, 0.0)


class TestRuleRegistry(unittest.TestCase):
    """测试规则注册表"""

    def test_register_and_get(self):
        registry = RuleRegistry()

        def dummy_rule(signal, context, config, extra=None):
            return RiskCheckResult.pass_result()

        info = registry.register(
            name="test_rule",
            category=RuleCategory.GATE,
            handler=dummy_rule,
            priority=10,
            description="测试规则",
        )

        self.assertEqual(len(registry), 1)
        self.assertIn("test_rule", registry)
        self.assertEqual(registry.get_rule("test_rule").priority, 10)

    def test_priority_sorting(self):
        registry = RuleRegistry()

        def rule_a(signal, context, config, extra=None):
            return RiskCheckResult.pass_result()

        def rule_b(signal, context, config, extra=None):
            return RiskCheckResult.pass_result()

        registry.register("rule_low", RuleCategory.GATE, rule_a, priority=50)
        registry.register("rule_high", RuleCategory.GATE, rule_b, priority=10)

        rules = registry.get_rules(RuleCategory.GATE)
        self.assertEqual(rules[0].name, "rule_high")
        self.assertEqual(rules[1].name, "rule_low")

    def test_enable_disable(self):
        registry = RuleRegistry()

        def dummy(signal, context, config, extra=None):
            return RiskCheckResult.pass_result()

        registry.register("test_rule", RuleCategory.GATE, dummy, priority=10)

        self.assertTrue(registry.get_rule("test_rule").enabled)
        registry.disable("test_rule")
        self.assertFalse(registry.get_rule("test_rule").enabled)
        self.assertEqual(len(registry.get_enabled_rules(RuleCategory.GATE)), 0)
        registry.enable("test_rule")
        self.assertTrue(registry.get_rule("test_rule").enabled)

    def test_decorator_register(self):
        registry = RuleRegistry()

        @registry.register_gate("my_gate", priority=5)
        def my_gate(signal, context, config, extra=None):
            return RiskCheckResult.pass_result()

        self.assertIn("my_gate", registry)
        self.assertEqual(registry.get_rule("my_gate").priority, 5)


class TestRiskEngine(unittest.TestCase):
    """测试通用风控引擎"""

    def setUp(self):
        self.engine = RiskEngine({
            "gate": {
                "daily_drawdown_circuit_breaker": {"max_daily_drawdown_pct": 0.10},
                "concurrent_position_limit": {"max_concurrent_positions": 5},
                "consecutive_losses_limit": {"max_consecutive_losses": 5},
                "confidence_minimum": {"confidence_hard_min": 0.2, "confidence_soft_min": 0.4},
                "drawdown_warning_degrade": {"drawdown_warn_1": 0.05, "drawdown_warn_2": 0.08},
            },
            "position": {
                "risk_per_trade_pct": 0.02,
                "max_risk_per_trade_pct": 0.05,
                "max_position_pct": 0.25,
                "default_stop_pct": 0.03,
            },
            "exit": {
                "max_loss_stop": {"max_loss_pct": 0.10},
                "stop_loss_barrier": {"stop_method": "pct", "stop_loss_pct": 0.03},
                "take_profit_barrier": {"tp_method": "pct", "take_profit_pct": 0.06},
            },
        })
        self.engine.register_default_rules()

    def test_engine_initialization(self):
        self.assertIsNotNone(self.engine.pre_trade_gate)
        self.assertIsNotNone(self.engine.position_sizer)
        self.assertIsNotNone(self.engine.exit_engine)
        self.assertGreater(len(self.engine.registry), 0)

    def test_pre_trade_check_pass(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.pre_trade_check(signal, context)
        self.assertTrue(result.passed)
        self.assertEqual(result.reason_code, ReasonCode.PASS)

    def test_pre_trade_check_drawdown_circuit_breaker(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
        )
        context = RiskContext(total_equity=10000, max_daily_equity=10000)
        context.update_equity(8500)

        result = self.engine.pre_trade_check(signal, context)
        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, ReasonCode.HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER)

    def test_pre_trade_check_drawdown_warning_degrade(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
        )
        context = RiskContext(total_equity=10000, max_daily_equity=10000)
        context.update_equity(9300)

        result = self.engine.pre_trade_check(signal, context)
        self.assertTrue(result.passed)
        self.assertEqual(result.reason_code, ReasonCode.DEGRADE_DRAWDOWN_WARNING)
        self.assertLess(result.position_modifier, 1.0)

    def test_pre_trade_check_consecutive_losses(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
        )
        context = RiskContext(total_equity=10000, consecutive_losses=6)

        result = self.engine.pre_trade_check(signal, context)
        self.assertFalse(result.passed)
        self.assertEqual(result.reason_code, ReasonCode.HARD_FAIL_CONSECUTIVE_LOSSES)

    def test_calculate_position(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
            entry_price=50000,
            stop_loss_price=48500,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.calculate_position(signal, context)
        self.assertGreater(result.base_size_usdt, 0)
        self.assertGreater(result.risk_per_trade_usdt, 0)
        self.assertIsNotNone(result.position_tier)

    def test_calculate_position_with_modifier(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
            entry_price=50000,
            stop_loss_price=45000,
        )
        context = RiskContext(total_equity=100000)

        result_full = self.engine.calculate_position(signal, context, position_modifier=1.0)
        result_half = self.engine.calculate_position(signal, context, position_modifier=0.5)

        ratio = result_half.base_size_usdt / result_full.base_size_usdt
        self.assertAlmostEqual(ratio, 0.5, places=1)

    def test_check_exit_hold(self):
        position = PositionState(
            coin="BTC",
            side=Direction.LONG,
            entry_price=50000,
            current_price=50500,
            position_age_sec=3600,
            unrealized_pnl_pct=0.01,
            leverage=1.0,
            atr_pct=0.02,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.check_exit(position, context=context)
        self.assertEqual(result.action, ExitAction.HOLD)

    def test_check_exit_stop_loss(self):
        position = PositionState(
            coin="BTC",
            side=Direction.LONG,
            entry_price=50000,
            current_price=48000,
            position_age_sec=3600,
            unrealized_pnl_pct=-0.04,
            leverage=1.0,
            atr_pct=0.02,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.check_exit(position, context=context)
        self.assertEqual(result.action, ExitAction.CLOSE)
        self.assertEqual(result.priority, ExitPriority.P2_TRIPLE_BARRIER)

    def test_check_exit_max_loss(self):
        position = PositionState(
            coin="BTC",
            side=Direction.LONG,
            entry_price=50000,
            current_price=44000,
            position_age_sec=3600,
            unrealized_pnl_pct=-0.12,
            leverage=1.0,
            atr_pct=0.02,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.check_exit(position, context=context)
        self.assertEqual(result.action, ExitAction.CLOSE)
        self.assertEqual(result.priority, ExitPriority.P0_L0_HARD)

    def test_check_exit_take_profit(self):
        position = PositionState(
            coin="BTC",
            side=Direction.LONG,
            entry_price=50000,
            current_price=53500,
            position_age_sec=3600,
            unrealized_pnl_pct=0.07,
            leverage=1.0,
            atr_pct=0.02,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.check_exit(position, context=context)
        self.assertIn(result.action, [ExitAction.REDUCE, ExitAction.CLOSE])

    def test_full_pre_trade(self):
        signal = Signal(
            coin="BTC",
            direction=Direction.LONG,
            confidence=0.7,
            entry_price=50000,
            stop_loss_price=48500,
        )
        context = RiskContext(total_equity=10000)

        result = self.engine.full_pre_trade(signal, context)
        self.assertIn("check", result)
        self.assertIn("position", result)
        self.assertTrue(result["check"].passed)
        self.assertIsInstance(result["position"], PositionSizeResult)

    def test_list_rules(self):
        rules = self.engine.list_rules()
        self.assertIn("gate", rules)
        self.assertIn("position", rules)
        self.assertIn("exit", rules)
        self.assertGreater(len(rules["gate"]), 0)

    def test_get_status(self):
        context = RiskContext(total_equity=10000)
        status = self.engine.get_status(context)
        self.assertIn("total_equity", status)
        self.assertIn("daily_pnl", status)
        self.assertIn("rules_count", status)
        self.assertGreater(status["rules_count"], 0)


class TestPositionState(unittest.TestCase):
    """测试持仓状态"""

    def test_pnl_eff(self):
        pos = PositionState(
            coin="BTC",
            side=Direction.LONG,
            unrealized_pnl_pct=0.05,
            leverage=10.0,
        )
        self.assertAlmostEqual(pos.pnl_eff, 0.5, places=4)

    def test_is_long(self):
        pos_long = PositionState(coin="BTC", side=Direction.LONG)
        pos_short = PositionState(coin="BTC", side=Direction.SHORT)
        self.assertTrue(pos_long.is_long)
        self.assertFalse(pos_short.is_long)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestRiskContext))
    suite.addTests(loader.loadTestsFromTestCase(TestRuleRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestPositionState))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
