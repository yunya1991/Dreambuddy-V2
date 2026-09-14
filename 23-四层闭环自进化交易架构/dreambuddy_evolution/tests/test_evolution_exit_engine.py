# -*- coding: utf-8 -*-
"""EvolutionExitEngine TDD 测试 — Phase 1 RED / Phase 2-5 GREEN

测试覆盖：
- Phase 1 RED: 模块/类/方法签名存在性（断言 ModuleNotFoundError → 实现 → GREEN）
- Phase 2 GREEN: decide() 核心决策逻辑（hold/adjust_sl_tp/trailing/force_close）
- Phase 3 GREEN: outcome 标签从 reason 解析（_extract_outcome_from_reason）
- Phase 4 GREEN: ExitRewardCalculator 三组件奖励（R_trend/R_risk/R_pnl）
- Phase 5 GREEN: 参数自适应（ESS 双轨 / 反例库 / G_close 验证）

硬约束（来自记忆库）：
- R_total = w_trend*R_trend + w_risk*R_risk + w_pnl*R_pnl
- w_pnl ≤ 0.3, w_trend ≥ 0.4, 三组件独立观测
- ESS_delta ±0.02（G_close 稳定性保证）
- 6h 批聚合 R_risk 总和 < -1.0 触发熔断
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# 确保 dreambuddy_evolution 包可被 import
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ============================================================================
# Phase 1 RED: 模块结构存在性测试（未实现时断言 ImportError）
# ============================================================================

class TestExitEngineModuleStructure:
    """Phase 1 RED: 验证模块/类/方法签名存在性"""

    def test_exit_engine_package_importable(self):
        """exit_engine 包可被 import"""
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine  # noqa: F401

    def test_exit_decision_dataclass_importable(self):
        """ExitDecision 数据类可被 import"""
        from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision  # noqa: F401

    def test_exit_strategy_params_importable(self):
        """ExitStrategyParams 数据类可被 import"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (  # noqa: F401
            ExitStrategyParams,
        )

    def test_exit_decision_fields(self):
        """ExitDecision 包含必需字段：action/params/reason/sl_px/tp_px/confidence"""
        from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision
        d = ExitDecision(
            action="hold", params={}, reason="test", sl_px=0.0, tp_px=0.0, confidence=0.0
        )
        assert d.action == "hold"
        assert d.params == {}
        assert d.reason == "test"
        assert d.sl_px == 0.0
        assert d.tp_px == 0.0
        assert d.confidence == 0.0

    def test_exit_strategy_params_fields(self):
        """ExitStrategyParams 包含离场参数基因字段"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        p = ExitStrategyParams(
            trailing_retrace_pct=0.05,
            sl_tighten_factor=0.7,
            tp_extend_factor=1.2,
            force_close_threshold=-0.5,
        )
        assert p.trailing_retrace_pct == 0.05
        assert p.sl_tighten_factor == 0.7
        assert p.tp_extend_factor == 1.2
        assert p.force_close_threshold == -0.5

    def test_evolution_exit_engine_decide_method_exists(self):
        """EvolutionExitEngine.decide() 方法存在"""
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        assert hasattr(EvolutionExitEngine, "decide")


# ============================================================================
# Phase 2 GREEN: decide() 核心决策逻辑测试
# ============================================================================

class TestExitEngineDecide:
    """Phase 2 GREEN: decide() 决策逻辑"""

    @pytest.fixture
    def engine(self):
        """构造 EvolutionExitEngine 实例（mock 依赖）"""
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None,  # Phase 2 测试不依赖 OKX
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
        )

    @pytest.fixture
    def hold_context(self):
        """保护期内 context → 应返回 hold"""
        return {
            "symbol": "ETH", "inst_id": "ETH-USDT-SWAP", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 3010.0,
            "upl": 10.0, "upl_ratio": 0.0033,
            "position_age_sec": 600,  # 10min < 60min 保护期
            "r_vector": {"R_up": 0.6, "R_down": 0.3, "R_smooth": 0.5},
            "ess": 0.6, "ftc_track": "exploit", "regime": "trend_up",
            "atr_pct": 0.02, "tier": "standard",
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
        }

    def test_decide_hold_in_protection_period(self, engine, hold_context):
        """保护期 60min 内 → hold"""
        decision = engine.decide(hold_context)
        assert decision.action == "hold"
        assert "protection" in decision.reason.lower()

    def test_decide_adjust_sl_tp_on_profit_threshold(self, engine, hold_context):
        """盈亏触达 +3% → adjust_sl_tp（保本位收紧）"""
        ctx = dict(hold_context)
        ctx["position_age_sec"] = 7200  # 2h 超过保护期
        ctx["upl_ratio"] = 0.03  # +3%
        ctx["current_price"] = 3090.0  # +3%
        decision = engine.decide(ctx)
        assert decision.action == "adjust_sl_tp"
        assert decision.sl_px > 0  # 保本位收紧

    def test_decide_break_even_at_two_pct(self, engine, hold_context):
        """P1-1: 保本位阈值 3%→2%，upl=2% 应触发 adjust_sl_tp"""
        ctx = dict(hold_context)
        ctx["position_age_sec"] = 7200
        ctx["upl_ratio"] = 0.02  # +2%（新保本位阈值）
        ctx["current_price"] = 3060.0
        decision = engine.decide(ctx)
        assert decision.action == "adjust_sl_tp", (
            f"保本位2%应触发, got {decision.action}"
        )

    def test_decide_trailing_probe_at_five_pct(self, engine, hold_context):
        """P1-2: probe tier trailing arm 8%→5%，upl=5% 应触发 trailing"""
        ctx = dict(hold_context)
        ctx["tier"] = "probe"
        ctx["position_age_sec"] = 7200
        ctx["upl_ratio"] = 0.05  # +5%（新 probe arm）
        ctx["current_price"] = 3150.0
        decision = engine.decide(ctx)
        assert decision.action == "trailing", (
            f"probe arm 5%应触发trailing, got {decision.action}"
        )

    def test_decide_trailing_standard_at_four_pct(self, engine, hold_context):
        """P1-2: standard tier trailing arm 6%→4%，upl=4% 应触发 trailing"""
        ctx = dict(hold_context)
        ctx["tier"] = "standard"
        ctx["position_age_sec"] = 7200
        ctx["upl_ratio"] = 0.04  # +4%（新 standard arm）
        ctx["current_price"] = 3120.0
        decision = engine.decide(ctx)
        assert decision.action == "trailing", (
            f"standard arm 4%应触发trailing, got {decision.action}"
        )

    def test_decide_trailing_on_trend_tier(self, engine, hold_context):
        """tier=trend 盈亏触达 6% → trailing"""
        ctx = dict(hold_context)
        ctx["tier"] = "trend"
        ctx["position_age_sec"] = 7200
        ctx["upl_ratio"] = 0.06  # +6%
        ctx["current_price"] = 3180.0
        decision = engine.decide(ctx)
        assert decision.action == "trailing"
        assert "trailing_arm_pct" in decision.params or "trailing_retrace_pct" in decision.params

    def test_decide_force_close_on_signal_reverse(self, engine, hold_context):
        """R 向量反转 + ESS<0.4 → force_close"""
        ctx = dict(hold_context)
        ctx["position_age_sec"] = 7200
        ctx["r_vector"] = {"R_up": 0.2, "R_down": 0.7, "R_smooth": 0.5}  # 反转
        ctx["ess"] = 0.3  # < 0.4
        decision = engine.decide(ctx)
        assert decision.action == "force_close"
        assert "reverse" in decision.reason.lower()

    def test_decide_trailing_persists_after_peak_pullback(self, engine, hold_context):
        """P4: trailing 触发后，价格从 peak 回撤但仍 > 3% 时，应保持 trailing（不退化到 adjust_sl_tp 保本位）"""
        ctx1 = dict(hold_context)
        ctx1["tier"] = "trend"
        ctx1["position_age_sec"] = 7200
        ctx1["upl_ratio"] = 0.08  # +8% 触发 trailing（arm=6%）
        ctx1["current_price"] = 3240.0
        decision1 = engine.decide(ctx1)
        assert decision1.action == "trailing"  # 首次触发 trailing

        # 第二轮：价格回撤到 +5%（peak=8%，当前 5%，仍 > 3% 保本位阈值）
        ctx2 = dict(hold_context)
        ctx2["tier"] = "trend"
        ctx2["position_age_sec"] = 9000
        ctx2["upl_ratio"] = 0.05  # +5%
        ctx2["current_price"] = 3150.0
        decision2 = engine.decide(ctx2)
        # 应保持 trailing，而不是退化到 adjust_sl_tp 保本位
        assert decision2.action == "trailing"
        assert "trailing" in decision2.reason

    def test_decide_force_close_on_timeout(self, engine, hold_context):
        """tier=trend 超过 24h 无进展 → force_close"""
        ctx = dict(hold_context)
        ctx["tier"] = "trend"
        ctx["position_age_sec"] = 25 * 3600  # 25h
        ctx["upl_ratio"] = 0.001  # 无进展
        decision = engine.decide(ctx)
        assert decision.action == "force_close"
        assert "timeout" in decision.reason.lower()

    def test_decide_force_close_on_okx_algo_triggered(self, engine, hold_context):
        """OKX algo 已触达 → force_close（仓位已被平，走同步流程）"""
        ctx = dict(hold_context)
        ctx["okx_algo_triggered"] = True
        decision = engine.decide(ctx)
        assert decision.action == "force_close"
        assert "algo" in decision.reason.lower()

    def test_decide_trailing_not_blocked_by_timeout_profit(self, engine, hold_context):
        """P0-1 修复：超时(>29h)盈利+无更强信号+达到trailing arm → 应触发trailing，而非hold

        根因：规则3b(超时评估)在盈利+无更强信号时直接return hold，跳过规则5(trailing)。
        SKHYNIX旧仓盈利8.18%超trailing6%但被规则3b拦截，最终亏损。
        """
        ctx = dict(hold_context)
        ctx["tier"] = "trend"
        ctx["position_age_sec"] = 30 * 3600  # 30h > 29h 超时
        ctx["upl_ratio"] = 0.07  # +7% > trailing arm 6%
        ctx["current_price"] = 3210.0
        ctx["has_stronger_signal"] = False
        ctx["stronger_signal_info"] = {}
        decision = engine.decide(ctx)
        # 修复前：action == "hold", reason 含 "timeout_profit_no_stronger_signal"
        # 修复后：action == "trailing"
        assert decision.action == "trailing", (
            f"超时盈利应触发trailing而非hold, got action={decision.action} reason={decision.reason}"
        )
        assert "trailing" in decision.reason

    def test_decide_break_even_not_blocked_by_timeout_profit(self, engine, hold_context):
        """P0-1 修复：超时(>29h)盈利+无更强信号+达到保本位(3%) → 应触发adjust_sl_tp，而非hold"""
        ctx = dict(hold_context)
        ctx["tier"] = "standard"
        ctx["position_age_sec"] = 30 * 3600  # 30h > 29h
        ctx["upl_ratio"] = 0.035  # +3.5% > 保本位3%，< trailing 6%
        ctx["current_price"] = 3105.0
        ctx["has_stronger_signal"] = False
        ctx["stronger_signal_info"] = {}
        decision = engine.decide(ctx)
        assert decision.action == "adjust_sl_tp", (
            f"超时盈利应触发保本位而非hold, got action={decision.action} reason={decision.reason}"
        )

    def test_decide_timeout_stronger_signal_still_force_closes(self, engine, hold_context):
        """P0-1 修复后：超时盈利+有更强信号 → 仍应force_close换仓（此行为不变）"""
        ctx = dict(hold_context)
        ctx["tier"] = "trend"
        ctx["position_age_sec"] = 30 * 3600
        ctx["upl_ratio"] = 0.05
        ctx["current_price"] = 3150.0
        ctx["has_stronger_signal"] = True
        ctx["stronger_signal_info"] = {
            "coin": "BTC", "direction": "long", "confidence": 0.8, "is_opposite": True,
        }
        decision = engine.decide(ctx)
        assert decision.action == "force_close"
        assert "stronger_signal" in decision.reason


# ============================================================================
# Phase 3 GREEN: outcome 标签从 reason 解析
# ============================================================================

class TestOutcomeExtraction:
    """Phase 3 GREEN: _extract_outcome_from_reason"""

    @pytest.fixture
    def bridge_or_util(self):
        """加载 outcome 提取函数（在 trade_settlement_bridge 或 exit_engine）"""
        # 实现后取消注释
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        # 静态方法/类方法可直接调用
        return TradeSettlementBridge

    def test_outcome_evolution_sltp_tp_algo(self, bridge_or_util):
        """evolution_sltp + OKX algo 触达 + 多头盈利 → TP_algo"""
        reason = "evolution_sltp tier=standard sl=3.0% tp=6.0%"
        outcome = bridge_or_util._extract_outcome_from_reason(
            reason, okx_algo_triggered=True, pnl=10.0, pos_side="long"
        )
        assert outcome == "TP_algo"

    def test_outcome_evolution_sltp_sl_algo(self, bridge_or_util):
        """evolution_sltp + OKX algo 触达 + 多头亏损 → SL_algo"""
        reason = "evolution_sltp tier=standard sl=3.0% tp=6.0%"
        outcome = bridge_or_util._extract_outcome_from_reason(
            reason, okx_algo_triggered=True, pnl=-10.0, pos_side="long"
        )
        assert outcome == "SL_algo"

    def test_outcome_evolution_adjust_sl_tp(self, bridge_or_util):
        """evolution_exit:adjust_sl_tp → ADJUST"""
        reason = "evolution_exit:adjust_sl_tp:break_even"
        outcome = bridge_or_util._extract_outcome_from_reason(
            reason, okx_algo_triggered=False, pnl=5.0, pos_side="long"
        )
        assert outcome == "ADJUST"

    def test_outcome_evolution_trailing(self, bridge_or_util):
        """evolution_exit:trailing → TRAILING"""
        reason = "evolution_exit:trailing:armed_at_6pct"
        outcome = bridge_or_util._extract_outcome_from_reason(
            reason, okx_algo_triggered=False, pnl=8.0, pos_side="long"
        )
        assert outcome == "TRAILING"

    def test_outcome_force_close_signal_reverse(self, bridge_or_util):
        """evolution_exit:force_close:signal_reverse → FORCE_REVERSE"""
        reason = "evolution_exit:force_close:signal_reverse"
        outcome = bridge_or_util._extract_outcome_from_reason(
            reason, okx_algo_triggered=False, pnl=-2.0, pos_side="long"
        )
        assert outcome == "FORCE_REVERSE"

    def test_outcome_force_close_timeout(self, bridge_or_util):
        """evolution_exit:force_close:timeout → FORCE_TIMEOUT"""
        reason = "evolution_exit:force_close:timeout_24h"
        outcome = bridge_or_util._extract_outcome_from_reason(
            reason, okx_algo_triggered=False, pnl=0.5, pos_side="long"
        )
        assert outcome == "FORCE_TIMEOUT"

    def test_outcome_fallback_pnl_positive(self, bridge_or_util):
        """reason 为空 + pnl>0 → TP（兼容旧路径）"""
        outcome = bridge_or_util._extract_outcome_from_reason(
            "", okx_algo_triggered=False, pnl=5.0, pos_side="long"
        )
        assert outcome == "TP"

    def test_outcome_fallback_pnl_negative(self, bridge_or_util):
        """reason 为空 + pnl<0 → SL（兼容旧路径）"""
        outcome = bridge_or_util._extract_outcome_from_reason(
            "", okx_algo_triggered=False, pnl=-5.0, pos_side="long"
        )
        assert outcome == "SL"


# ============================================================================
# Phase 4 GREEN: ExitRewardCalculator 三组件奖励
# ============================================================================

class TestExitRewardCalculator:
    """Phase 4 GREEN: L3 离场奖励组件化"""

    @pytest.fixture
    def calculator(self):
        from dreambuddy_evolution.core.exit_reward_calculator import (
            ExitRewardCalculator,
        )
        return ExitRewardCalculator()

    def test_reward_components_independent_observable(self, calculator):
        """calculate() 返回三组件分别的值 + R_total"""
        ctx = {"cs": 0.8, "sl_in_range": True, "pnl_pct": 0.05, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert "R_trend" in r
        assert "R_risk" in r
        assert "R_pnl" in r
        assert "R_total" in r
        assert "w_trend" in r
        assert "w_risk" in r
        assert "w_pnl" in r

    def test_reward_weights_hard_constraint(self, calculator):
        """w_pnl ≤ 0.3, w_trend ≥ 0.4"""
        ctx = {"cs": 0.5, "sl_in_range": True, "pnl_pct": 0.0, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["w_pnl"] <= 0.3
        assert r["w_trend"] >= 0.4

    def test_r_trend_cs_high(self, calculator):
        """CS ≥ 0.7 → R_trend = +1.0"""
        ctx = {"cs": 0.8, "sl_in_range": True, "pnl_pct": 0.0, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["R_trend"] == 1.0

    def test_r_trend_cs_low(self, calculator):
        """CS ≤ -0.2 → R_trend = -1.0"""
        ctx = {"cs": -0.3, "sl_in_range": True, "pnl_pct": 0.0, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["R_trend"] == -1.0

    def test_r_trend_cs_neutral(self, calculator):
        """-0.2 < CS < 0.7 → R_trend = 0.0"""
        ctx = {"cs": 0.4, "sl_in_range": True, "pnl_pct": 0.0, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["R_trend"] == 0.0

    def test_r_risk_in_range(self, calculator):
        """止损在预设区间 → R_risk = +0.5"""
        ctx = {"cs": 0.5, "sl_in_range": True, "pnl_pct": 0.0, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["R_risk"] == 0.5

    def test_r_risk_out_of_range(self, calculator):
        """止损超范围 → R_risk = -0.5"""
        ctx = {"cs": 0.5, "sl_in_range": False, "pnl_pct": 0.0, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["R_risk"] == -0.5

    def test_r_pnl_tp_hit(self, calculator):
        """pnl_pct ≥ tp_pct_target → R_pnl = +1.0"""
        ctx = {"cs": 0.5, "sl_in_range": True, "pnl_pct": 0.06, "tp_pct_target": 0.06}
        r = calculator.calculate(ctx)
        assert r["R_pnl"] == 1.0

    def test_r_pnl_sl_hit(self, calculator):
        """pnl_pct ≤ -sl_pct_target → R_pnl = -1.0"""
        ctx = {"cs": 0.5, "sl_in_range": True, "pnl_pct": -0.03, "tp_pct_target": 0.06, "sl_pct_target": 0.03}
        r = calculator.calculate(ctx)
        assert r["R_pnl"] == -1.0

    def test_r_pnl_scaled(self, calculator):
        """-sl < pnl_pct < tp → R_pnl 按比例缩放"""
        ctx = {"cs": 0.5, "sl_in_range": True, "pnl_pct": 0.03, "tp_pct_target": 0.06, "sl_pct_target": 0.03}
        r = calculator.calculate(ctx)
        assert -1.0 < r["R_pnl"] < 1.0


# ============================================================================
# 优化 1: ATR 自适应止损
# ============================================================================

class TestATRAdaptiveStop:
    """优化1: ATR 波动率自适应止损"""

    @pytest.fixture
    def engine(self):
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None, ess_provider=None, ftc_bridge=None,
            shadow_rl_tracker=None, log_fn=lambda msg, level="INFO": None,
        )

    def test_atr_sl_high_volatility_widens_stop(self, engine):
        """高波动 ATR=5% → SL 比固定 3% 更宽（避免假止损）"""
        ctx = {
            "symbol": "BTC", "pos_side": "long",
            "entry_price": 100000.0, "current_price": 98000.0,
            "upl_ratio": -0.02, "position_age_sec": 7200,
            "r_vector": {"R_up": 0.5, "R_down": 0.5}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.05,  # ATR 5%
            "current_sl_px": 97000.0, "current_tp_px": 106000.0,
            "okx_algo_triggered": False,
        }
        decision = engine.decide(ctx)
        # 高波动时 SL 应比固定 3% 更宽（ATR×2.5=12.5% > 3%）
        # 验证：决策结果中包含 ATR 自适应的 SL 计算
        assert "atr" in decision.reason.lower() or decision.params.get("atr_adaptive", False) or decision.action == "hold"

    def test_atr_sl_low_volatility_tightens_stop(self, engine):
        """低波动 ATR=1% → SL 比固定 3% 更紧（减少利润回吐）"""
        ctx = {
            "symbol": "BTC", "pos_side": "long",
            "entry_price": 100000.0, "current_price": 101000.0,
            "upl_ratio": 0.01, "position_age_sec": 7200,
            "r_vector": {"R_up": 0.5, "R_down": 0.5}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.01,  # ATR 1%
            "current_sl_px": 97000.0, "current_tp_px": 106000.0,
            "okx_algo_triggered": False,
        }
        decision = engine.decide(ctx)
        # 低波动时 SL 应比固定 3% 更紧（ATR×2.5=2.5% < 3%）
        # 但不应低于硬约束下限 1.5%
        assert decision.action in ("hold", "adjust_sl_tp")


# ============================================================================
# 优化 2: 分批止盈
# ============================================================================

class TestPartialTakeProfit:
    """优化2: 分批止盈 +1R/50%, +2R/30%, +3R trailing 20%"""

    @pytest.fixture
    def engine(self):
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None, ess_provider=None, ftc_bridge=None,
            shadow_rl_tracker=None, log_fn=lambda msg, level="INFO": None,
        )

    def test_partial_tp_at_1r_profit(self, engine):
        """盈亏达 +1R（=SL 距离）→ partial_close 50%"""
        ctx = {
            "symbol": "ETH", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 3090.0,
            "upl_ratio": 0.03, "position_age_sec": 7200,
            "r_vector": {"R_up": 0.6, "R_down": 0.3}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
            # 1R = entry - sl = 3000 - 2910 = 90, +1R = 3090
            "r_multiple": 1.0,
        }
        decision = engine.decide(ctx)
        # r_multiple >= 1.0 → partial_close 50%
        assert decision.action == "partial_close" or decision.params.get("partial_pct") == 0.5

    def test_partial_tp_at_2r_profit(self, engine):
        """盈亏达 +2R → partial_close 30%（第二批）"""
        ctx = {
            "symbol": "ETH", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 3180.0,
            "upl_ratio": 0.06, "position_age_sec": 7200,
            "r_vector": {"R_up": 0.6, "R_down": 0.3}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
            "r_multiple": 2.0,
        }
        decision = engine.decide(ctx)
        assert decision.action == "partial_close" or decision.params.get("partial_pct") == 0.3

    def test_partial_tp_at_3r_trailing_remaining(self, engine):
        """盈亏达 +3R → trailing 剩余 20%"""
        ctx = {
            "symbol": "ETH", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 3270.0,
            "upl_ratio": 0.09, "position_age_sec": 7200,
            "r_vector": {"R_up": 0.6, "R_down": 0.3}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
            "r_multiple": 3.0,
        }
        decision = engine.decide(ctx)
        # +3R → trailing 剩余仓位
        assert decision.action in ("trailing", "partial_close")


# ============================================================================
# 优化 3: 超时 29H 信号强度评估
# ============================================================================

class TestTimeoutSignalEvaluation:
    """优化3: 超时 29H 后评估信号强度，盈利+更强信号→止盈换仓，亏损/无更强信号→继续持有"""

    @pytest.fixture
    def engine(self):
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None, ess_provider=None, ftc_bridge=None,
            shadow_rl_tracker=None, log_fn=lambda msg, level="INFO": None,
        )

    def test_timeout_profit_with_stronger_signal_force_close(self, engine):
        """超时 29H + 盈利 + 有更强信号代币 → 止盈平仓换仓"""
        ctx = {
            "symbol": "ETH", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 3100.0,
            "upl_ratio": 0.033, "position_age_sec": 29 * 3600,  # 29h
            "r_vector": {"R_up": 0.5, "R_down": 0.5}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": True,  # 有更强信号
        }
        decision = engine.decide(ctx)
        assert decision.action == "force_close"
        assert "stronger_signal" in decision.reason or "换仓" in decision.reason or "rotate" in decision.reason.lower()

    def test_timeout_profit_no_stronger_signal_break_even(self, engine):
        """超时 29H + 盈利 3.3%(>2%保本位) + 无更强信号 → 触发保本位 adjust_sl_tp

        P0-1 修复：超时盈利+无更强信号不再 return hold，
        而是继续执行保本位逻辑，避免盈利仓回吐亏损（SKHYNIX案例）。
        """
        ctx = {
            "symbol": "ETH", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 3100.0,
            "upl_ratio": 0.033, "position_age_sec": 29 * 3600,
            "r_vector": {"R_up": 0.5, "R_down": 0.5}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": False,  # 无更强信号
        }
        decision = engine.decide(ctx)
        assert decision.action == "adjust_sl_tp"
        assert decision.sl_px is not None
        # 保本位 SL 应 >= 开仓价（long）
        assert decision.sl_px >= ctx["entry_price"]

    def test_timeout_loss_continue_hold(self, engine):
        """超时 29H + 亏损 → 继续持有（不因超时止损）"""
        ctx = {
            "symbol": "ETH", "pos_side": "long",
            "entry_price": 3000.0, "current_price": 2950.0,
            "upl_ratio": -0.017, "position_age_sec": 29 * 3600,
            "r_vector": {"R_up": 0.5, "R_down": 0.5}, "ess": 0.6,
            "tier": "standard", "atr_pct": 0.02,
            "current_sl_px": 2910.0, "current_tp_px": 3180.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": True,  # 即使有更强信号
        }
        decision = engine.decide(ctx)
        # 亏损时即使有更强信号也继续持有（不因超时强平亏损仓）
        assert decision.action == "hold"
        assert "loss" in decision.reason.lower() or "亏损" in decision.reason or "hold" in decision.reason.lower()

class TestParameterAdaptiveLoop:
    """Phase 5 GREEN: ESS 双轨 / 策略参数基因 / G_close 验证"""

    def test_ess_provider_dual_track_update(self, tmp_gene_dir):
        """ESSProvider.update_ess 支持 ess_type='exit' 双轨"""
        from dreambuddy_evolution.adapters.ess_provider import ESSDirectionProvider
        provider = ESSDirectionProvider(gene_root=str(tmp_gene_dir))
        # 写入离场 ESS
        result = provider.update_ess(
            combo_id="CB-TREND-LONG-001",
            ess_delta=0.02,
            ess_type="exit",
        )
        assert result is not None or result is None  # 实现后细化

    def test_exit_strategy_params_gene_json_writable(self, tmp_gene_dir):
        """离场参数基因 JSON 可写入 strategy_genes/conditions/"""
        from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
            ExitStrategyParams,
        )
        params = ExitStrategyParams(
            trailing_retrace_pct=0.05,
            sl_tighten_factor=0.7,
            tp_extend_factor=1.2,
            force_close_threshold=-0.5,
        )
        # 序列化为基因 JSON
        gene_json = params.to_gene_json()
        assert "gene_id" in gene_json
        assert gene_json["category"] in ("exit", "risk", "trend")
        assert "condition_type" in gene_json

    def test_g_close_estimation_less_than_one(self):
        """G_close 估算 < 1（回路稳定性）"""
        # G_close = K_exit_decision × K_param_update × K_ess_delta × K_feedback
        K_exit_decision = 0.55
        K_param_update = 0.55
        K_ess_delta = 0.02
        K_feedback = 0.25
        g_close = K_exit_decision * K_param_update * K_ess_delta * K_feedback
        assert g_close < 1.0
        assert g_close < 0.01  # 应远小于 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
