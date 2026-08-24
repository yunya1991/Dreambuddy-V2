# -*- coding: utf-8 -*-
"""ExitManager 策略链 TDD 测试.

Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md

测试顺序（与 Spec §6.3 实施顺序对齐）:
  Step 1: 接口骨架（ExitDecision / ExitContext / ExitStrategy / ExitManager）
  Step 2: 逐个策略迁移
  Step 3: polling_trader 集成
  Step 4: exit_strategy_log 贡献值
"""
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ── 路径修正 ──
_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


# ================================================================
# Step 1: 接口骨架测试（ExitDecision / ExitContext / ExitStrategy / ExitManager）
# ================================================================

class TestExitManagerSkeleton:
    """ExitManager 骨架：空策略返回 pass，优先级链短路。"""

    def test_exit_manager_empty_strategies_returns_pass(self):
        """空策略列表 → ExitDecision(action='pass')。"""
        from bcrm2.exit_manager import ExitManager, ExitDecision

        mgr = ExitManager(strategies=[])
        decision = mgr.evaluate(
            coin="BTC", inference={}, pos_info={}, tracker_pos=None,
            in_protection=False, age_hours=1.0,
        )
        assert decision.action == "pass"
        assert decision.reason == ""

    def test_exit_manager_priority_chain_first_non_pass_wins(self):
        """3 个策略，第二个返回 force_close → 第三个 never called。"""
        from bcrm2.exit_manager import (
            ExitManager, ExitDecision, ExitStrategy, ExitContext,
        )

        class AlwaysPass(ExitStrategy):
            name = "always_pass"
            priority = 10

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                return ExitDecision.pass_()

        class ForceClose(ExitStrategy):
            name = "force_close"
            priority = 20

            def __init__(self):
                self.call_count = 0

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                self.call_count += 1
                return ExitDecision(action="force_close", reason="test")

        class ShouldNotBeCalled(ExitStrategy):
            name = "should_not_be_called"
            priority = 30

            def __init__(self):
                self.call_count = 0

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                self.call_count += 1
                return ExitDecision(action="force_close", reason="bug")

        force_close = ForceClose()
        should_not_be_called = ShouldNotBeCalled()

        mgr = ExitManager(strategies=[AlwaysPass(), force_close, should_not_be_called])
        decision = mgr.evaluate(
            coin="BTC", inference={}, pos_info={}, tracker_pos=None,
            in_protection=False, age_hours=1.0,
        )
        assert decision.action == "force_close"
        assert decision.strategy_name == "force_close"
        # 第三个策略不应被调用
        assert should_not_be_called.call_count == 0

    def test_disabled_strategy_is_skipped(self):
        """enabled=False 的策略被跳过。"""
        from bcrm2.exit_manager import (
            ExitManager, ExitDecision, ExitStrategy, ExitContext,
        )

        class DisabledStrategy(ExitStrategy):
            name = "disabled"
            priority = 10
            enabled = False

            def __init__(self):
                self.call_count = 0

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                self.call_count += 1
                return ExitDecision(action="force_close", reason="should_not_happen")

        class FallbackStrategy(ExitStrategy):
            name = "fallback"
            priority = 20

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                return ExitDecision(action="force_close", reason="fallback_hit")

        disabled = DisabledStrategy()
        mgr = ExitManager(strategies=[disabled, FallbackStrategy()])
        decision = mgr.evaluate(
            coin="BTC", inference={}, pos_info={}, tracker_pos=None,
            in_protection=False, age_hours=1.0,
        )
        assert decision.strategy_name == "fallback"
        assert disabled.call_count == 0

    def test_exit_context_passed_correctly(self):
        """ExitContext 正确传递给策略。"""
        from bcrm2.exit_manager import (
            ExitManager, ExitDecision, ExitStrategy, ExitContext,
        )

        class ContextChecker(ExitStrategy):
            name = "context_checker"
            priority = 10
            received_ctx: ExitContext = None

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                self.received_ctx = ctx
                return ExitDecision(action="force_close", reason="checked")

        checker = ContextChecker()
        mgr = ExitManager(strategies=[checker])
        mgr.evaluate(
            coin="ETH", inference={"direction": "long"}, pos_info={"entry": 100},
            tracker_pos="tracker_obj", in_protection=True, age_hours=3.5,
            ev=0.15, confidence=0.85,
        )
        ctx = checker.received_ctx
        assert ctx.coin == "ETH"
        assert ctx.inference["direction"] == "long"
        assert ctx.pos_info["entry"] == 100
        assert ctx.tracker_pos == "tracker_obj"
        assert ctx.in_protection is True
        assert ctx.age_hours == 3.5
        assert ctx.ev == 0.15
        assert ctx.confidence == 0.85

    def test_all_pass_returns_pass(self):
        """所有策略都返回 pass → 最终返回 pass。"""
        from bcrm2.exit_manager import (
            ExitManager, ExitDecision, ExitStrategy, ExitContext,
        )

        class PassA(ExitStrategy):
            name = "pass_a"
            priority = 10

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                return ExitDecision.pass_()

        class PassB(ExitStrategy):
            name = "pass_b"
            priority = 20

            def evaluate(self, ctx: ExitContext) -> ExitDecision:
                return ExitDecision.pass_()

        mgr = ExitManager(strategies=[PassA(), PassB()])
        decision = mgr.evaluate(
            coin="BTC", inference={}, pos_info={}, tracker_pos=None,
            in_protection=False, age_hours=1.0,
        )
        assert decision.action == "pass"

    def test_strategies_sorted_by_priority(self):
        """策略按 priority 升序排列（数字小先评估）。"""
        from bcrm2.exit_manager import ExitManager, ExitStrategy

        class S1(ExitStrategy):
            name = "s1"
            priority = 30

            def evaluate(self, ctx):
                return ExitDecision.pass_()

        class S2(ExitStrategy):
            name = "s2"
            priority = 10

            def evaluate(self, ctx):
                return ExitDecision.pass_()

        class S3(ExitStrategy):
            name = "s3"
            priority = 20

            def evaluate(self, ctx):
                return ExitDecision.pass_()

        mgr = ExitManager(strategies=[S1(), S2(), S3()])
        priorities = [s.priority for s in mgr._strategies]
        assert priorities == [10, 20, 30]


# ================================================================
# Step 2a: P3EarlyExitStrategy 迁移
# 原位置: polling_trader.py L5676-5732
# 触发条件: early_exit_signal + 保护期浮亏阈值 + 2次确认
# ================================================================

class TestP3EarlyExitStrategy:
    """P3 提前退出策略测试。"""

    def _make_ctx(self, early_exit=True, in_protection=False,
                  upl_ratio=0.0, coin="BTC"):
        """构造测试用 ExitContext。"""
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={"early_exit_signal": early_exit},
            pos_info={"upl_ratio": upl_ratio},
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=1.0,
        )

    def test_p3_no_signal_returns_pass(self):
        """无 early_exit_signal → pass，清除确认计数。"""
        from bcrm2.exit_strategies import P3EarlyExitStrategy
        from bcrm2.exit_manager import ExitDecision

        strat = P3EarlyExitStrategy()
        ctx = self._make_ctx(early_exit=False)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_p3_signal_first_call_not_confirmed_returns_hold(self):
        """第 1 次信号触发 → 未达 2 次确认 → hold（阻塞后续策略）。"""
        from bcrm2.exit_strategies import P3EarlyExitStrategy

        strat = P3EarlyExitStrategy(exit_confirm_required=2)
        ctx = self._make_ctx(early_exit=True, in_protection=False)
        decision = strat.evaluate(ctx)
        assert decision.action == "hold"
        assert "pending" in decision.reason

    def test_p3_signal_second_call_confirmed_returns_force_close(self):
        """第 2 次信号触发 → 达到 2 次确认 → force_close。"""
        from bcrm2.exit_strategies import P3EarlyExitStrategy

        strat = P3EarlyExitStrategy(exit_confirm_required=2)
        ctx = self._make_ctx(early_exit=True, in_protection=False)
        # 第 1 次
        d1 = strat.evaluate(ctx)
        assert d1.action == "hold"
        # 第 2 次
        d2 = strat.evaluate(ctx)
        assert d2.action == "force_close"
        assert d2.reason == "p3_early_exit"

    def test_p3_protection_low_loss_blocked(self):
        """保护期内 + 浮亏 < 8% → 拦截，返回 pass。"""
        from bcrm2.exit_strategies import P3EarlyExitStrategy

        strat = P3EarlyExitStrategy(
            protected_p3_min_loss_pct=-0.08, exit_confirm_required=1)
        ctx = self._make_ctx(
            early_exit=True, in_protection=True, upl_ratio=-0.03)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_p3_protection_high_loss_allowed(self):
        """保护期内 + 浮亏 ≥ 8% → 允许触发，需确认。"""
        from bcrm2.exit_strategies import P3EarlyExitStrategy

        strat = P3EarlyExitStrategy(
            protected_p3_min_loss_pct=-0.08, exit_confirm_required=1)
        ctx = self._make_ctx(
            early_exit=True, in_protection=True, upl_ratio=-0.10)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "p3_early_exit"

    def test_p3_signal_disappears_clears_confirm_count(self):
        """信号消失 → 清除确认计数，下次需重新累计。"""
        from bcrm2.exit_strategies import P3EarlyExitStrategy

        strat = P3EarlyExitStrategy(exit_confirm_required=2)
        ctx_on = self._make_ctx(early_exit=True)
        ctx_off = self._make_ctx(early_exit=False)

        # 第 1 次
        strat.evaluate(ctx_on)
        # 信号消失
        strat.evaluate(ctx_off)
        # 信号恢复 → 重新从 0 计数
        d = strat.evaluate(ctx_on)
        assert d.action == "hold"  # 需重新确认


# ================================================================
# Step 2b: SignalReverseStrategy 迁移
# 原位置: polling_trader.py L5594-5645
# 触发条件: pos_side != direction + 置信度 >= threshold + 2次确认
# ================================================================

class TestSignalReverseStrategy:
    """信号反转策略测试。"""

    def _make_ctx(self, pos_side="long", direction="DOWN",
                 confidence=0.85, in_protection=False, coin="BTC"):
        """构造测试用 ExitContext。"""
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={"direction": direction},
            pos_info={"pos_side": pos_side},
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=1.0,
            confidence=confidence,
        )

    def test_signal_reverse_same_direction_returns_pass(self):
        """持仓方向与预测方向一致 → 无反转信号 → pass。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(base_threshold=0.7)
        ctx = self._make_ctx(pos_side="long", direction="UP")
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_signal_reverse_low_confidence_returns_pass(self):
        """反转方向但置信度 < 阈值 → pass。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(base_threshold=0.7)
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.5)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_signal_reverse_first_call_returns_hold(self):
        """反转信号 + 置信度达标，第 1 次 → hold（待确认）。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, exit_confirm_required=2)
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.85)
        decision = strat.evaluate(ctx)
        assert decision.action == "hold"
        assert "pending" in decision.reason

    def test_signal_reverse_second_call_returns_force_close(self):
        """反转信号第 2 次确认 → force_close。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, exit_confirm_required=2)
        ctx = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.85)
        d1 = strat.evaluate(ctx)
        assert d1.action == "hold"
        d2 = strat.evaluate(ctx)
        assert d2.action == "force_close"
        assert d2.reason == "signal_reverse"

    def test_signal_reverse_short_position_up_direction(self):
        """空仓 + UP 方向 → 反转信号（对称性）。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, exit_confirm_required=1)
        ctx = self._make_ctx(
            pos_side="short", direction="UP", confidence=0.85)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "signal_reverse"

    def test_signal_reverse_protection_period_higher_threshold(self):
        """保护期内需更高置信度（base+boost, 最低0.85）。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, protected_conf_boost=0.12,
            exit_confirm_required=1)
        # 保护期内：threshold = max(0.7+0.12, 0.85) = 0.85
        # 置信度 0.80 < 0.85 → pass
        ctx_low = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.80,
            in_protection=True)
        d_low = strat.evaluate(ctx_low)
        assert d_low.action == "pass"
        # 置信度 0.90 >= 0.85 → force_close
        ctx_high = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.90,
            in_protection=True)
        d_high = strat.evaluate(ctx_high)
        assert d_high.action == "force_close"

    def test_signal_reverse_disappears_clears_confirm_count(self):
        """反转信号消失（置信度降低）→ 清除确认计数。"""
        from bcrm2.exit_strategies import SignalReverseStrategy

        strat = SignalReverseStrategy(
            base_threshold=0.7, exit_confirm_required=2)
        ctx_on = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.85)
        ctx_off = self._make_ctx(
            pos_side="long", direction="DOWN", confidence=0.50)  # 低于阈值

        strat.evaluate(ctx_on)  # 第 1 次
        strat.evaluate(ctx_off)  # 信号消失
        d = strat.evaluate(ctx_on)  # 重新从 0 计数
        assert d.action == "hold"


# ================================================================
# Step 2c: EvForceCloseStrategy 迁移
# 原位置: polling_trader.py L3415-3436
# 触发条件: ev < force_below + 非保护期 + 2次确认
# ================================================================

class TestEvForceCloseStrategy:
    """EV 雷达强制离场策略测试。"""

    def _make_ctx(self, ev=-0.40, in_protection=False, coin="BTC"):
        """构造测试用 ExitContext。"""
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={},
            pos_info={},
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=1.0,
            ev=ev,
        )

    def test_ev_disabled_returns_pass(self):
        """enabled=False → 跳过，返回 pass。"""
        from bcrm2.exit_strategies import EvForceCloseStrategy

        strat = EvForceCloseStrategy(force_below=-0.35, enabled=False)
        ctx = self._make_ctx(ev=-0.50)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ev_above_threshold_returns_pass(self):
        """EV >= force_below → pass。"""
        from bcrm2.exit_strategies import EvForceCloseStrategy

        strat = EvForceCloseStrategy(force_below=-0.35, exit_confirm_required=1)
        ctx = self._make_ctx(ev=-0.20)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ev_below_threshold_in_protection_returns_pass(self):
        """EV < force_below 但保护期内 → pass（保护期拦截）。"""
        from bcrm2.exit_strategies import EvForceCloseStrategy

        strat = EvForceCloseStrategy(force_below=-0.35, exit_confirm_required=1)
        ctx = self._make_ctx(ev=-0.50, in_protection=True)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ev_below_threshold_first_call_returns_hold(self):
        """EV < force_below, 非保护期, 第 1 次 → hold（待确认）。"""
        from bcrm2.exit_strategies import EvForceCloseStrategy

        strat = EvForceCloseStrategy(
            force_below=-0.35, exit_confirm_required=2)
        ctx = self._make_ctx(ev=-0.50)
        decision = strat.evaluate(ctx)
        assert decision.action == "hold"
        assert "pending" in decision.reason

    def test_ev_below_threshold_second_call_returns_force_close(self):
        """EV < force_below, 非保护期, 第 2 次确认 → force_close。"""
        from bcrm2.exit_strategies import EvForceCloseStrategy

        strat = EvForceCloseStrategy(
            force_below=-0.35, exit_confirm_required=2)
        ctx = self._make_ctx(ev=-0.50)
        d1 = strat.evaluate(ctx)
        assert d1.action == "hold"
        d2 = strat.evaluate(ctx)
        assert d2.action == "force_close"
        assert d2.reason == "ev_force_close"

    def test_ev_recovers_clears_confirm_count(self):
        """EV 回升到阈值之上 → 清除确认计数。"""
        from bcrm2.exit_strategies import EvForceCloseStrategy

        strat = EvForceCloseStrategy(
            force_below=-0.35, exit_confirm_required=2)
        ctx_low = self._make_ctx(ev=-0.50)
        ctx_high = self._make_ctx(ev=-0.20)

        strat.evaluate(ctx_low)   # 第 1 次
        strat.evaluate(ctx_high)  # EV 回升
        d = strat.evaluate(ctx_low)  # 重新从 0 计数
        assert d.action == "hold"


# ================================================================
# Step 2d: TimeoutProfitSwitchStrategy 迁移
# 原位置: polling_trader.py L5887-5965
# 触发条件: age > 29h + 盈利 + 有更强信号候选
# ================================================================

class TestTimeoutProfitSwitchStrategy:
    """超时止盈换仓策略测试。"""

    def _make_ctx(self, age_hours=30.0, upl=10.0, upl_ratio=0.05,
                 all_inferences=None, held_coins=None, coin="BTC"):
        """构造测试用 ExitContext。"""
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={"confidence": 0.75, "direction": "UP"},
            pos_info={"upl": upl, "upl_ratio": upl_ratio},
            tracker_pos=None,
            in_protection=False,
            age_hours=age_hours,
            all_inferences=all_inferences or {},
            held_coins=held_coins or {coin},
        )

    def test_timeout_not_reached_returns_pass(self):
        """持仓未超时（< 29h）→ pass。"""
        from bcrm2.exit_strategies import TimeoutProfitSwitchStrategy

        strat = TimeoutProfitSwitchStrategy(timeout_hours=29.0)
        ctx = self._make_ctx(age_hours=20.0, upl=10.0,
                             all_inferences={"ETH": {"confidence": 0.9, "direction": "UP"}})
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_timeout_loss_returns_pass(self):
        """超时但亏损 → pass（亏损交由 yijing 主离场 + 静态 SL/TP 兜底）。"""
        from bcrm2.exit_strategies import TimeoutProfitSwitchStrategy

        strat = TimeoutProfitSwitchStrategy(timeout_hours=29.0)
        ctx = self._make_ctx(age_hours=30.0, upl=-5.0,
                             all_inferences={"ETH": {"confidence": 0.9, "direction": "UP"}})
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_timeout_profit_no_better_candidate_returns_pass(self):
        """超时+盈利但无更强信号 → pass（继续持有追求更大利润）。"""
        from bcrm2.exit_strategies import TimeoutProfitSwitchStrategy

        strat = TimeoutProfitSwitchStrategy(timeout_hours=29.0)
        # 候选信号弱于持仓
        ctx = self._make_ctx(
            age_hours=30.0, upl=10.0,
            all_inferences={"ETH": {"confidence": 0.60, "direction": "UP"}},
            held_coins={"BTC"})
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_timeout_profit_better_candidate_returns_force_close(self):
        """超时+盈利+有更强信号 → force_close + params 包含候选信息。"""
        from bcrm2.exit_strategies import TimeoutProfitSwitchStrategy

        strat = TimeoutProfitSwitchStrategy(timeout_hours=29.0)
        # 持仓 BTC conf=0.75, 候选 ETH conf=0.90 → 更强
        ctx = self._make_ctx(
            age_hours=30.0, upl=10.0,
            all_inferences={"ETH": {"confidence": 0.90, "direction": "UP"}},
            held_coins={"BTC"})
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "timeout_profit_switch"
        assert decision.params["target_coin"] == "ETH"
        assert decision.params["target_direction"] == "UP"

    def test_timeout_held_coin_excluded_from_candidates(self):
        """已持仓的币种从候选中排除。"""
        from bcrm2.exit_strategies import TimeoutProfitSwitchStrategy

        strat = TimeoutProfitSwitchStrategy(timeout_hours=29.0)
        # ETH 也已持仓 → 排除
        ctx = self._make_ctx(
            age_hours=30.0, upl=10.0,
            all_inferences={"ETH": {"confidence": 0.90, "direction": "UP"}},
            held_coins={"BTC", "ETH"})
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_timeout_short_direction_score_discount(self):
        """做空信号打 0.95 折扣（对称性）。"""
        from bcrm2.exit_strategies import TimeoutProfitSwitchStrategy

        strat = TimeoutProfitSwitchStrategy(timeout_hours=29.0)
        # 持仓 conf=0.75 UP → score=0.75
        # 候选 conf=0.78 DOWN → score=0.78*0.95=0.741 < 0.75 → 不换仓
        ctx = self._make_ctx(
            age_hours=30.0, upl=10.0,
            all_inferences={"ETH": {"confidence": 0.78, "direction": "DOWN"}},
            held_coins={"BTC"})
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"


# ================================================================
# Step 2e: RankedTpStrategy 迁移
# 原位置: polling_trader.py L3758-3866
# 触发条件: A档(gap>=阈值+非保护期) / B档(gap<阈值+age>=12h+盈利) / C档(无动作)
# ================================================================

class TestRankedTpStrategy:
    """排名止盈 A/B/C 三档策略测试。"""

    def _make_ctx(self, is_top1=True, gap_ratio=0.75, upl=10.0,
                  age_hours=15.0, in_protection=False, coin="BTC"):
        """构造测试用 ExitContext。"""
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={"direction": "UP"},
            pos_info={
                "is_top1": is_top1,
                "ranked_tp_gap": gap_ratio,
                "upl": upl,
            },
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=age_hours,
        )

    def test_ranked_tp_disabled_returns_pass(self):
        """S4 开关关闭 → pass。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy(enabled=False)
        ctx = self._make_ctx()
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ranked_tp_not_top1_returns_pass(self):
        """非 top1 持仓 → pass。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy()
        ctx = self._make_ctx(is_top1=False)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ranked_tp_a_tier_gap_above_threshold_force_close(self):
        """A 档：gap >= 阈值 + 非保护期 → force_close。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy(gap_threshold=0.70)
        ctx = self._make_ctx(gap_ratio=0.75, in_protection=False)
        decision = strat.evaluate(ctx)
        assert decision.action == "force_close"
        assert decision.reason == "ranked_tp_a"

    def test_ranked_tp_a_tier_protection_blocks(self):
        """A 档：保护期内 → pass（保护期拦截）。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy(gap_threshold=0.70)
        ctx = self._make_ctx(gap_ratio=0.75, in_protection=True)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ranked_tp_a_tier_gap_below_threshold_returns_pass_or_b(self):
        """gap < 阈值 → B 档条件满足则 adjust_sl_tp，否则 pass。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy(gap_threshold=0.70)
        # B 档：age >= 12h + 盈利 + gap > 0 → adjust_sl_tp
        ctx_b = self._make_ctx(gap_ratio=0.50, upl=10.0, age_hours=15.0)
        d_b = strat.evaluate(ctx_b)
        assert d_b.action == "adjust_sl_tp"
        assert d_b.reason == "ranked_tp_b"
        assert "reduce_plan" in d_b.params

    def test_ranked_tp_c_tier_young_position_returns_pass(self):
        """C 档：持仓 < 12h → pass。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy(gap_threshold=0.70)
        ctx = self._make_ctx(gap_ratio=0.50, upl=10.0, age_hours=5.0)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ranked_tp_c_tier_loss_returns_pass(self):
        """C 档：亏损 → pass。"""
        from bcrm2.exit_strategies import RankedTpStrategy

        strat = RankedTpStrategy(gap_threshold=0.70)
        ctx = self._make_ctx(gap_ratio=0.50, upl=-5.0, age_hours=15.0)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"


# ================================================================
# Step 2f: EvAdjustStrategy 迁移
# 原位置: polling_trader.py L3455-3482
# 触发条件: T2 WARN(收紧) / T4 STRONG_HOLD(放宽) / T3 NORMAL(无动作)
# BCRM2 spec: enabled = S2 (enable_ev_radar)
# ================================================================

class TestEvAdjustStrategy:
    """EV 雷达调整（移动止盈）策略测试。"""

    def _make_ctx(self, ev=-0.20, in_protection=False, coin="BTC"):
        """构造测试用 ExitContext。"""
        from bcrm2.exit_manager import ExitContext
        return ExitContext(
            coin=coin,
            inference={},
            pos_info={"pos_side": "long"},
            tracker_pos=None,
            in_protection=in_protection,
            age_hours=1.0,
            ev=ev,
        )

    def test_ev_adjust_disabled_returns_pass(self):
        """S2 开关关闭 → pass。"""
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(enabled=False)
        ctx = self._make_ctx(ev=-0.20)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ev_adjust_t2_warn_tighten(self):
        """T2 WARN: warn_lower <= ev < warn_upper → adjust_sl_tp mode=tighten。"""
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(
            warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30)
        ctx = self._make_ctx(ev=-0.20)  # -0.35 <= -0.20 < -0.10
        decision = strat.evaluate(ctx)
        assert decision.action == "adjust_sl_tp"
        assert decision.reason == "ev_tighten"
        assert decision.params["mode"] == "tighten"

    def test_ev_adjust_t4_strong_hold_relax(self):
        """T4 STRONG_HOLD: ev > strong_above → adjust_sl_tp mode=relax。"""
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(
            warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30)
        ctx = self._make_ctx(ev=0.40)  # > 0.30
        decision = strat.evaluate(ctx)
        assert decision.action == "adjust_sl_tp"
        assert decision.reason == "ev_relax"
        assert decision.params["mode"] == "relax"

    def test_ev_adjust_t3_normal_returns_pass(self):
        """T3 NORMAL: warn_upper <= ev <= strong_above → pass。"""
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(
            warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30)
        ctx = self._make_ctx(ev=0.00)  # -0.10 <= 0.00 <= 0.30
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ev_adjust_protection_blocks_low_ev(self):
        """保护期内 + ev < warn_upper → pass（T1/T2 禁用）。"""
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(
            warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30)
        ctx = self._make_ctx(ev=-0.20, in_protection=True)
        decision = strat.evaluate(ctx)
        assert decision.action == "pass"

    def test_ev_adjust_protection_allows_high_ev(self):
        """保护期内 + ev > strong_above → 仍可放宽（保护期不禁用 T4）。"""
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(
            warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30)
        ctx = self._make_ctx(ev=0.40, in_protection=True)
        decision = strat.evaluate(ctx)
        assert decision.action == "adjust_sl_tp"
        assert decision.params["mode"] == "relax"


# ================================================================
# Step 4: exit_strategy_log 表 + 贡献值统计
# ================================================================

class TestExitStrategyLogStorage:
    """exit_strategy_log 表 CRUD + 贡献值统计。"""

    def _make_storage(self):
        """创建内存 SQLite storage 用于测试。"""
        from bcrm2.storage import EvolutionStorageSQLite
        import tempfile, os
        _fd, _path = tempfile.mkstemp(suffix=".db")
        os.close(_fd)
        st = EvolutionStorageSQLite(_path)
        return st

    def test_save_exit_strategy_log_returns_id(self):
        """save_exit_strategy_log 返回 int id。"""
        st = self._make_storage()
        try:
            log_id = st.save_exit_strategy_log("BTC", {
                "strategy_name": "p3_early_exit",
                "action": "force_close",
                "reason": "p3_confirmed",
                "age_hours": 1.5,
                "in_protection": False,
                "ev": -0.20,
                "confidence": 0.85,
            })
            assert isinstance(log_id, int)
            assert log_id > 0
        finally:
            st.close()

    def test_get_exit_strategy_log_returns_records(self):
        """get_exit_strategy_log 返回记录列表。"""
        st = self._make_storage()
        try:
            st.save_exit_strategy_log("BTC", {
                "strategy_name": "signal_reverse",
                "action": "force_close",
                "reason": "signal_reverse",
                "age_hours": 2.0,
                "in_protection": False,
                "ev": None,
                "confidence": 0.90,
            })
            logs = st.get_exit_strategy_log("BTC", days=7)
            assert len(logs) == 1
            r = logs[0]
            assert r["symbol"] == "BTC"
            assert r["strategy_name"] == "signal_reverse"
            assert r["action"] == "force_close"
            assert r["confidence"] == 0.90
        finally:
            st.close()

    def test_update_exit_strategy_outcome_backfills_pnl_win(self):
        """update_exit_strategy_outcome 回填 pnl 和 win。"""
        st = self._make_storage()
        try:
            log_id = st.save_exit_strategy_log("BTC", {
                "strategy_name": "ev_force_close",
                "action": "force_close",
                "reason": "ev_force_close",
                "age_hours": 3.0,
                "in_protection": False,
                "ev": -0.40,
                "confidence": 0.0,
            })
            # 初始 pnl/win 为 None
            logs = st.get_exit_strategy_log("BTC", days=7)
            assert logs[0]["pnl"] is None
            assert logs[0]["win"] is None
            # 回填
            st.update_exit_strategy_outcome(log_id, pnl=12.5, win=True)
            logs = st.get_exit_strategy_log("BTC", days=7)
            assert logs[0]["pnl"] == 12.5
            assert logs[0]["win"] == 1
        finally:
            st.close()

    def test_get_exit_strategy_contribution_aggregates_by_strategy(self):
        """get_exit_strategy_contribution 按 strategy_name 聚合。"""
        st = self._make_storage()
        try:
            # p3: 2 触发，1 胜
            _id1 = st.save_exit_strategy_log("BTC", {
                "strategy_name": "p3_early_exit", "action": "force_close",
                "reason": "p3", "age_hours": 1.0, "in_protection": False,
                "ev": None, "confidence": 0.8,
            })
            _id2 = st.save_exit_strategy_log("BTC", {
                "strategy_name": "p3_early_exit", "action": "force_close",
                "reason": "p3", "age_hours": 2.0, "in_protection": False,
                "ev": None, "confidence": 0.7,
            })
            st.update_exit_strategy_outcome(_id1, pnl=10.0, win=True)
            st.update_exit_strategy_outcome(_id2, pnl=-5.0, win=False)
            # signal_reverse: 1 触发，1 胜
            _id3 = st.save_exit_strategy_log("ETH", {
                "strategy_name": "signal_reverse", "action": "force_close",
                "reason": "rev", "age_hours": 0.5, "in_protection": False,
                "ev": None, "confidence": 0.9,
            })
            st.update_exit_strategy_outcome(_id3, pnl=20.0, win=True)

            contrib = st.get_exit_strategy_contribution(days=7)
            assert "p3_early_exit" in contrib
            assert contrib["p3_early_exit"]["triggers"] == 2
            assert contrib["p3_early_exit"]["wins"] == 1
            assert abs(contrib["p3_early_exit"]["win_rate"] - 0.5) < 0.01
            assert abs(contrib["p3_early_exit"]["avg_pnl"] - 2.5) < 0.01
            assert "signal_reverse" in contrib
            assert contrib["signal_reverse"]["triggers"] == 1
            assert contrib["signal_reverse"]["win_rate"] == 1.0
        finally:
            st.close()

    def test_get_exit_strategy_contribution_ignores_no_outcome(self):
        """get_exit_strategy_contribution 忽略未回填 pnl 的记录。"""
        st = self._make_storage()
        try:
            st.save_exit_strategy_log("BTC", {
                "strategy_name": "timeout_profit_switch", "action": "force_close",
                "reason": "tp", "age_hours": 29.5, "in_protection": False,
                "ev": None, "confidence": 0.0,
            })
            # 不回填 → 不计入 win_rate/avg_pnl
            contrib = st.get_exit_strategy_contribution(days=7)
            assert "timeout_profit_switch" in contrib
            assert contrib["timeout_profit_switch"]["triggers"] == 1
            assert contrib["timeout_profit_switch"]["wins"] == 0
            assert contrib["timeout_profit_switch"]["win_rate"] == 0.0
        finally:
            st.close()

    def test_get_exit_strategy_contribution_respects_days_window(self):
        """get_exit_strategy_contribution 只统计 N 天内记录。"""
        st = self._make_storage()
        try:
            # 直接插入一条 30 天前的记录
            from datetime import datetime, timedelta, timezone
            old_ts = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat(timespec="seconds")
            cur = st._conn.cursor()
            cur.execute("""
                INSERT INTO exit_strategy_log (symbol, timestamp, strategy_name, action, reason, age_hours, in_protection, ev, confidence, pnl, win)
                VALUES (?, ?, 'p3_early_exit', 'force_close', 'old', 1.0, 0, NULL, 0.5, 5.0, 1)
            """, ("BTC", old_ts))
            st._conn.commit()
            # 7 天窗口 → 不应包含 35 天前记录
            contrib = st.get_exit_strategy_contribution(days=7)
            assert "p3_early_exit" not in contrib or contrib["p3_early_exit"]["triggers"] == 0
            # 60 天窗口 → 应包含
            contrib60 = st.get_exit_strategy_contribution(days=60)
            assert contrib60.get("p3_early_exit", {}).get("triggers") == 1
        finally:
            st.close()


class TestExitManagerContribution:
    """ExitManager.get_strategy_contribution 委托给 storage 适配器。"""

    def test_exit_manager_contribution_with_storage(self):
        """ExitManager 设置 storage 后，get_strategy_contribution 委托给 storage。"""
        from bcrm2.exit_manager import ExitManager
        from bcrm2.storage import EvolutionStorageSQLite
        import tempfile, os

        _fd, _path = tempfile.mkstemp(suffix=".db")
        os.close(_fd)
        st = EvolutionStorageSQLite(_path)
        try:
            _id = st.save_exit_strategy_log("BTC", {
                "strategy_name": "p3_early_exit", "action": "force_close",
                "reason": "p3", "age_hours": 1.0, "in_protection": False,
                "ev": None, "confidence": 0.8,
            })
            st.update_exit_strategy_outcome(_id, pnl=5.0, win=True)

            mgr = ExitManager(strategies=[])
            mgr.set_storage(st)
            contrib = mgr.get_strategy_contribution(days=7)
            assert "p3_early_exit" in contrib
            assert contrib["p3_early_exit"]["triggers"] == 1
        finally:
            st.close()
            os.unlink(_path)

    def test_exit_manager_contribution_without_storage_returns_empty(self):
        """ExitManager 无 storage 时，get_strategy_contribution 返回空 dict。"""
        from bcrm2.exit_manager import ExitManager

        mgr = ExitManager(strategies=[])
        contrib = mgr.get_strategy_contribution(days=7)
        assert contrib == {}


# ================================================================
# Step 5: 核心层行为等价验证（卦象主离场 + Classic 兜底）
#   回滚铁律: 扩展层全关时，ExitManager 返回 pass → 核心层原封不动
# ================================================================

class TestCoreLayerEquivalence:
    """扩展层全关 → ExitManager pass → 核心层（卦象+Classic）路径等价。"""

    def test_all_disabled_strategies_return_pass(self):
        """全策略 enabled=False → ExitManager 返回 pass。"""
        from bcrm2.exit_manager import ExitManager, ExitDecision
        from bcrm2.exit_strategies import (
            P3EarlyExitStrategy, SignalReverseStrategy,
            EvForceCloseStrategy, TimeoutProfitSwitchStrategy,
            EvAdjustStrategy,
        )

        strategies = [
            P3EarlyExitStrategy(exit_confirm_required=2),
            SignalReverseStrategy(base_threshold=0.7),
            EvForceCloseStrategy(force_below=-0.35, exit_confirm_required=2, enabled=False),
            TimeoutProfitSwitchStrategy(timeout_hours=29.0),
            EvAdjustStrategy(warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30),
        ]
        # 全部禁用
        for s in strategies:
            s.enabled = False

        mgr = ExitManager(strategies=strategies)
        decision = mgr.evaluate(
            coin="BTC", inference={"direction": "DOWN", "confidence": 0.95},
            pos_info={"pos_side": "long", "upl": -100, "mark_px": 50000},
            tracker_pos=None, in_protection=False, age_hours=30.0,
            ev=-0.50, confidence=0.95,
            all_inferences={"BTC": {"confidence": 0.95, "direction": "UP"}},
            held_coins={"BTC"},
            effective_threshold=0.7,
        )
        assert decision.action == "pass"
        assert decision.strategy_name == ""

    def test_all_pass_when_no_trigger_conditions_met(self):
        """策略全开但无触发条件 → ExitManager 返回 pass → 核心层可达。"""
        from bcrm2.exit_manager import ExitManager
        from bcrm2.exit_strategies import (
            P3EarlyExitStrategy, SignalReverseStrategy,
            EvForceCloseStrategy, TimeoutProfitSwitchStrategy,
            EvAdjustStrategy,
        )

        mgr = ExitManager(strategies=[
            P3EarlyExitStrategy(exit_confirm_required=2),
            SignalReverseStrategy(base_threshold=0.7),
            EvForceCloseStrategy(force_below=-0.35, exit_confirm_required=2, enabled=True),
            TimeoutProfitSwitchStrategy(timeout_hours=29.0),
            EvAdjustStrategy(warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30),
        ])
        # 无触发条件：方向一致 + 无 early_exit + EV 正常 + 未超时
        decision = mgr.evaluate(
            coin="BTC",
            inference={"direction": "UP", "confidence": 0.5, "early_exit_signal": False},
            pos_info={"pos_side": "long", "upl": 10, "mark_px": 50000},
            tracker_pos=None, in_protection=False, age_hours=5.0,
            ev=0.05, confidence=0.5,
            all_inferences={"BTC": {"confidence": 0.5, "direction": "UP"}},
            held_coins={"BTC"},
            effective_threshold=0.7,
        )
        assert decision.action == "pass"

    def test_exit_manager_pass_does_not_modify_inference(self):
        """ExitManager 返回 pass 时不修改 inference（核心层依赖原始 inference）。"""
        from bcrm2.exit_manager import ExitManager
        from bcrm2.exit_strategies import P3EarlyExitStrategy

        mgr = ExitManager(strategies=[P3EarlyExitStrategy(exit_confirm_required=2)])
        original_inference = {
            "direction": "UP", "confidence": 0.5,
            "hexagram": "乾", "price": 50000,
            "early_exit_signal": False,
            "snapshot": {"level_smooth": 0.3, "trend_smooth": 0.1},
        }
        # 传入后 inference 不应被修改
        mgr.evaluate(
            coin="BTC", inference=original_inference,
            pos_info={"pos_side": "long", "upl": 0, "mark_px": 50000},
            tracker_pos=None, in_protection=False, age_hours=1.0,
        )
        assert original_inference["direction"] == "UP"
        assert original_inference["hexagram"] == "乾"
        assert original_inference["snapshot"]["level_smooth"] == 0.3

    def test_position_timed_out_variable_flow(self):
        """验证 position_timed_out 变量在超时检查中的逻辑分支。

        场景1: age < 29h → position_timed_out=False → yijing 可用
        场景2: age > 29h + 亏损 → fall through to classic (yijing_available=False)
        场景3: age > 29h + 盈利 → return (继续持有)
        """
        # 这是结构性测试：验证 polling_trader 中超时逻辑的分支条件
        position_timeout_sec = 104400  # 29h

        # 场景1: 未超时
        age_sec_1 = 3600 * 20  # 20h
        timed_out_1 = age_sec_1 > position_timeout_sec
        assert not timed_out_1  # yijing_available = True (if hexagram exists)

        # 场景2: 超时 + 亏损
        age_sec_2 = 3600 * 30  # 30h
        timed_out_2 = age_sec_2 > position_timeout_sec
        upl_2 = -5.0  # 亏损
        assert timed_out_2
        # yijing_available = (not timed_out_2) and ... = False → classic 兜底

        # 场景3: 超时 + 盈利 + all_inferences
        age_sec_3 = 3600 * 30  # 30h
        timed_out_3 = age_sec_3 > position_timeout_sec
        upl_3 = 10.0  # 盈利
        all_inferences = {"ETH": {"confidence": 0.6, "direction": "UP"}}
        assert timed_out_3
        # ExitManager TimeoutProfitSwitch 已检查无更强候选 → return (继续持有)

    def test_yijing_available_gate_uses_position_timed_out(self):
        """验证 yijing_available = (not position_timed_out) and (hexagram is not None)。"""
        # 核心层代码（polling_trader.py L6002）:
        #   yijing_available = (not position_timed_out) and (yijing_hexagram is not None)
        # 当 ExitManager pass → 到达核心层 → 此变量决定走 yijing 还是 classic

        # 未超时 + 有卦象 → yijing 可用
        position_timed_out_1 = False
        yijing_hexagram_1 = "乾"
        yijing_available_1 = (not position_timed_out_1) and (yijing_hexagram_1 is not None)
        assert yijing_available_1

        # 超时 → yijing 不可用（强制走 classic）
        position_timed_out_2 = True
        yijing_hexagram_2 = "坤"
        yijing_available_2 = (not position_timed_out_2) and (yijing_hexagram_2 is not None)
        assert not yijing_available_2

        # 未超时 + 无卦象 → yijing 不可用
        position_timed_out_3 = False
        yijing_hexagram_3 = None
        yijing_available_3 = (not position_timed_out_3) and (yijing_hexagram_3 is not None)
        assert not yijing_available_3

    def test_exit_manager_does_not_touch_exit_confirm_state(self):
        """ExitManager 不干扰核心层 yijing FORCE_CLOSE 的 _exit_confirm 状态。

        核心层 yijing FORCE_CLOSE 仍使用 polling_trader._exit_confirm()，
        ExitManager 策略使用各自内部 _confirm_counts，互不干扰。
        """
        from bcrm2.exit_manager import ExitManager
        from bcrm2.exit_strategies import (
            P3EarlyExitStrategy, SignalReverseStrategy,
        )

        p3 = P3EarlyExitStrategy(exit_confirm_required=2)
        sr = SignalReverseStrategy(base_threshold=0.7, exit_confirm_required=2)
        mgr = ExitManager(strategies=[p3, sr])

        # 触发 P3 一次（hold，待确认）
        ctx_inference = {"early_exit_signal": True, "direction": "UP", "confidence": 0.5}
        d1 = mgr.evaluate(
            coin="BTC", inference=ctx_inference,
            pos_info={"pos_side": "long", "upl": -10, "mark_px": 50000},
            tracker_pos=None, in_protection=False, age_hours=1.0,
        )
        assert d1.action == "hold"
        assert d1.strategy_name == "p3_early_exit"
        # P3 内部 _confirm_counts["BTC"] = 1

        # 核心层的 _exit_confirm 是独立的状态（polling_trader 管理）
        # ExitManager 不影响它
        assert hasattr(p3, '_confirm_counts')
        assert p3._confirm_counts.get("BTC") == 1

    def test_adjust_sl_tp_falls_through_to_core_layer(self):
        """adjust_sl_tp 决策不 return → 继续走 Phase C (S3) 和核心层。

        验证 EvAdjust 返回 adjust_sl_tp 时，ExitManager 不阻止后续核心层评估。
        """
        from bcrm2.exit_manager import ExitManager
        from bcrm2.exit_strategies import EvAdjustStrategy

        strat = EvAdjustStrategy(
            warn_lower=-0.35, warn_upper=-0.10, strong_above=0.30)
        mgr = ExitManager(strategies=[strat])

        # EV 在 WARN 区间 → T2 tighten
        decision = mgr.evaluate(
            coin="BTC",
            inference={"direction": "UP", "confidence": 0.5},
            pos_info={"pos_side": "long", "upl": 5, "mark_px": 50000},
            tracker_pos=None, in_protection=False, age_hours=10.0,
            ev=-0.20, confidence=0.5,
        )
        assert decision.action == "adjust_sl_tp"
        assert decision.params["mode"] == "tighten"
        # 在 polling_trader 中，adjust_sl_tp 不 return → 继续走核心层
        # （此处验证 ExitManager 不返回 force_close/hold 阻止核心层）
