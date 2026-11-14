"""离场引擎止损单调性 / 保本水位 / 规则可达性 回归测试（2026-11-14 修复）

对应调查项：
  P0-1 trailing 止损非单调（回撤时 SL 跟着价格往下走）
  P0-2 规则5武装瞬间把规则6保本位退化
  P1-3 保本位不含手续费
  P0-4 规则3a 软投票定义但从未调用
  P0-5 规则4 分批止盈不可达（R 只由 TP 反算）
  P1-1 状态按 symbol 永久驻留

硬约束：所有 SL 更新必须单调（多头只升、空头只降）。
"""

from __future__ import annotations

import pytest

from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
from dreambuddy_evolution.engines.exit_engine.exit_strategy_params import (
    ExitStrategyParams,
)


def _engine(**params):
    """构造引擎；默认关闭 ATR 缩放，便于用固定 5% 回撤断言水位。"""
    params.setdefault("trailing_atr_mult", 0.0)
    return EvolutionExitEngine(
        log_fn=lambda m, lv="INFO": None, strategy_params=ExitStrategyParams(**params)
    )


def _ctx(**kw):
    base = {
        "symbol": "ETH",
        "inst_id": "ETH-USDT-SWAP",
        "pos_side": "long",
        "entry_price": 100.0,
        "current_price": 104.0,
        "upl_ratio": 0.04,
        "position_age_sec": 7200,
        "ess": 0.6,
        "r_vector": {},
        "tier": "standard",
        "atr_pct": 0.02,
        "current_sl_px": 96.0,
        "current_tp_px": 112.0,
        "okx_algo_triggered": False,
        "source_tag": "evolution",
    }
    base.update(kw)
    return base


class TestTrailingMonotonic:
    def test_trailing_sl_never_lowers_on_pullback(self):
        """P0-1: 8%→6%→4%→2.5% 缓慢回撤，SL 不得随之下调。

        用 10% 结构风险（SL=90）隔离规则4：1R=+10% 不会在 +8% 触发分批止盈。
        """
        engine = _engine()
        seq = [(0.08, 108.0), (0.06, 106.0), (0.04, 104.0), (0.025, 102.5)]
        sls = []
        for upl, px in seq:
            d = engine.decide(
                _ctx(
                    current_price=px,
                    upl_ratio=upl,
                    position_age_sec=7200,
                    current_sl_px=sls[-1] if sls else 90.0,
                )
            )
            assert d.action in ("trailing", "adjust_sl_tp", "hold")
            if d.sl_px:
                sls.append(float(d.sl_px))
            else:
                sls.append(sls[-1])
        # 单调不减
        for prev, cur in zip(sls, sls[1:], strict=False):
            assert cur >= prev - 1e-9, f"SL 被下调: {prev} -> {cur} (序列 {sls})"
        # 峰值 108 的 5% 回撤水位必须被守住
        assert sls[-1] >= 108.0 * 0.95 - 1e-6, f"最终 SL={sls[-1]} 低于峰值回撤水位"

    def test_trailing_uses_peak_price_not_current_price(self):
        """P0-1: 回撤到 104 时，SL 应基于 peak=108 定价，而非 104*0.95。"""
        engine = _engine()
        engine.decide(_ctx(current_price=108.0, upl_ratio=0.08, current_sl_px=90.0))
        d = engine.decide(_ctx(current_price=104.0, upl_ratio=0.04, current_sl_px=102.6))
        assert d.action == "trailing"
        assert d.sl_px >= 108.0 * 0.95 - 1e-6, f"应基于峰值定价, got {d.sl_px}"

    def test_short_trailing_sl_never_rises_on_pullback(self):
        """P0-1: 空头对称性 —— SL 只降不升。"""
        engine = _engine()
        sl = 110.0
        for upl, px in [(0.08, 92.0), (0.06, 94.0), (0.04, 96.0), (0.025, 97.5)]:
            d = engine.decide(
                _ctx(
                    pos_side="short",
                    entry_price=100.0,
                    current_price=px,
                    upl_ratio=upl,
                    current_sl_px=sl,
                    current_tp_px=88.0,
                )
            )
            if d.sl_px:
                assert float(d.sl_px) <= sl + 1e-9, f"空头 SL 被上调: {sl} -> {d.sl_px}"
                sl = float(d.sl_px)


class TestBreakEvenWaterline:
    def test_break_even_not_downgraded_by_trailing_arm(self):
        """P0-2: +2% 保本位后 +4% 武装 trailing，SL 不得低于保本水位。"""
        engine = _engine()
        d1 = engine.decide(_ctx(current_price=102.0, upl_ratio=0.02, current_sl_px=90.0))
        assert d1.action == "adjust_sl_tp"
        be_sl = float(d1.sl_px)
        assert be_sl >= 100.0
        d2 = engine.decide(_ctx(current_price=104.0, upl_ratio=0.04, current_sl_px=be_sl))
        assert d2.action == "trailing"
        assert float(d2.sl_px) >= be_sl - 1e-9, f"保本位被 trailing 退化: {be_sl} -> {d2.sl_px}"

    def test_break_even_includes_fee_buffer(self):
        """P1-3: 保本位必须覆盖双边手续费+滑点，SL 应略高于入场价。"""
        engine = _engine()
        d = engine.decide(_ctx(current_price=102.0, upl_ratio=0.02, current_sl_px=96.0))
        assert float(d.sl_px) > 100.0, f"保本位 {d.sl_px} 未覆盖手续费"

    def test_waterline_persists_after_price_falls_below_breakeven(self):
        """P0-2: 价格跌回 +0.5% 时，已建立的保本水位不得撤回。"""
        engine = _engine()
        d1 = engine.decide(_ctx(current_price=102.0, upl_ratio=0.02, current_sl_px=96.0))
        be_sl = float(d1.sl_px)
        d2 = engine.decide(_ctx(current_price=100.5, upl_ratio=0.005, current_sl_px=be_sl))
        assert float(d2.sl_px or be_sl) >= be_sl - 1e-9


class TestRuleReachability:
    def test_partial_tp_reachable_from_structural_risk(self):
        """P0-5: 无 r_multiple/tp_decayed_pct 时，用 entry-SL 结构风险算 R。"""
        engine = _engine()
        # 风险 4%（entry 100, SL 96），+4% → 1R
        d = engine.decide(_ctx(current_price=104.0, upl_ratio=0.04, current_sl_px=96.0))
        assert d.action == "partial_close", f"规则4 应可达, got {d.action}: {d.reason}"
        assert float((d.params or {}).get("partial_pct", 0)) > 0

    def test_partial_tp_second_batch_at_2r(self):
        """P0-5: +2R 触发第二批减仓（风险 4%，+8%）。"""
        engine = _engine()
        engine.decide(_ctx(current_price=104.0, upl_ratio=0.04, current_sl_px=96.0))
        d = engine.decide(_ctx(current_price=108.0, upl_ratio=0.08, current_sl_px=102.6))
        assert d.action == "partial_close"
        assert (d.params or {}).get("batch") == 2

    def test_soft_vote_is_wired_when_arbitrator_present(self):
        """P0-4: 注入 arbitrator 后，亏损超时仓必须走到软投票。"""

        class _Arb:
            def __init__(self):
                self.calls = 0

            def arbitrate(self, ctx):
                self.calls += 1
                from dreambuddy_evolution.engines.exit_engine.exit_decision import (
                    ExitDecision,
                )

                return ExitDecision(action="force_close", reason="soft_vote:test")

        arb = _Arb()
        engine = EvolutionExitEngine(log_fn=lambda m, lv="INFO": None, timeout_arbitrator=arb)
        d = engine.decide(
            _ctx(
                current_price=97.0,
                upl_ratio=-0.03,
                position_age_sec=30 * 3600,
                current_sl_px=96.0,
            )
        )
        assert arb.calls == 1, "规则3a 未被调用（死代码未接线）"
        assert d.action == "force_close"


class TestPositionStateLifecycle:
    def test_cleanup_position_resets_peak_and_partial_state(self):
        """P1-1: 同币二次开仓不得继承上一笔的 peak/partial 状态。"""
        engine = _engine()
        engine.decide(_ctx(current_price=108.0, upl_ratio=0.08))
        engine.cleanup_position("ETH", "long")
        # 新仓 +1%，不应被视为"已武装 trailing"
        d = engine.decide(_ctx(current_price=101.0, upl_ratio=0.01, position_age_sec=3600))
        assert d.action == "hold", f"新仓继承了旧 peak, got {d.action}: {d.reason}"

    def test_partial_tp_state_isolated_between_long_and_short(self):
        """P1-1: 同币多空双向持仓的 peak/partial 状态不得串扰。"""
        engine = _engine()
        engine.decide(_ctx(current_price=104.0, upl_ratio=0.04, pos_side="long"))
        d = engine.decide(
            _ctx(
                pos_side="short",
                current_price=103.0,
                upl_ratio=-0.03,
                current_sl_px=104.0,
                current_tp_px=88.0,
            )
        )
        # short 侧未持有 1R 盈利，不应触发 partial（规则4 状态不得复用 long 的批次）
        assert d.action != "partial_close" or (d.params or {}).get("batch") != 2


class TestChandelierRetrace:
    """P1-11: trailing 回撤距离随 ATR 缩放（Chandelier 口径）。

    回测证据（412 笔真实入场纯离场 A/B）：ATR×3 在 6/6 标的优于固定 5%。
    """

    def test_retrace_scales_with_atr(self):
        """atr=2%, mult=3 → 回撤 6%，SL = peak×(1−6%)。"""
        engine = _engine(trailing_atr_mult=3.0)
        d = engine.decide(
            _ctx(current_price=108.0, upl_ratio=0.08, current_sl_px=90.0, atr_pct=0.02)
        )
        assert d.action == "trailing"
        assert float(d.sl_px) == pytest.approx(108.0 * 0.94, rel=1e-6)
        assert (d.params or {}).get("trailing_retrace_pct") == pytest.approx(0.06)

    def test_retrace_clamped_to_floor_and_ceiling(self):
        """低波动钳到 3% 下限、高波动钳到 20% 上限。"""
        low = _engine(trailing_atr_mult=3.0).decide(
            _ctx(current_price=108.0, upl_ratio=0.08, current_sl_px=90.0, atr_pct=0.005)
        )
        assert (low.params or {}).get("trailing_retrace_pct") == pytest.approx(0.03)
        high = _engine(trailing_atr_mult=3.0).decide(
            _ctx(current_price=108.0, upl_ratio=0.08, current_sl_px=90.0, atr_pct=0.10)
        )
        assert (high.params or {}).get("trailing_retrace_pct") == pytest.approx(0.20)

    def test_falls_back_to_fixed_retrace_when_atr_missing(self):
        """atr_pct=0（缺失）时回退固定 trailing_retrace_pct。"""
        engine = _engine(trailing_atr_mult=3.0, trailing_retrace_pct=0.05)
        d = engine.decide(
            _ctx(current_price=108.0, upl_ratio=0.08, current_sl_px=90.0, atr_pct=0.0)
        )
        assert (d.params or {}).get("trailing_retrace_pct") == pytest.approx(0.05)
