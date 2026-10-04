"""Evolution 反向信号触发 partial_close 减仓 TDD 测试（规则 2d）

测试覆盖：
- 规则 2d：evolution 反向信号（has_stronger_signal+is_opposite）+ 亏损态 → partial_close
- 亏损分档：-3%→30%, -5%→50%, -8%→force_close
- FAIL-OPEN：无更强信号/非反向/盈利/保护期内 → 不触发（落回后续规则）
- 冷却期：减仓后 4H 内不再触发（按 symbol 独立）
- outcome 标签：evolution_reverse_reduce → PARTIAL_REDUCE

问题背景（PONS 案例，2026-09-28 Spec 缺陷A）：
- PONS 持仓约 9.6h，多次出现 BTC short conf=1.000 src=evolution（反向）
  → has_stronger_signal=True，但始终 hold
- 亏损 -3%~-4.5% 徘徊未触发离场
- 根因：规则2b 只评估 BCRM2.0 反向信号，不评估 evolution 反向信号
- 规则3b 需要 29h 超时才评估 has_stronger_signal，PONS 9.6h 远未达到
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# 确保 dreambuddy_evolution 包可被 import
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ============================================================================
# 规则 2d：evolution 反向信号 → partial_close 减仓
# ============================================================================

class TestEvolutionReverseReduce:
    """evolution 反向信号触发分批减仓测试

    触发条件：
    - has_stronger_signal=True
    - stronger_signal_info.is_opposite=True
    - upl_ratio < 0（亏损态）
    - position_age_sec > PROTECTION_PERIOD_SEC（1h 保护期后）
    """

    @pytest.fixture
    def engine(self):
        """构造 EvolutionExitEngine 实例（mock 依赖）"""
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None,
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
        )

    @pytest.fixture
    def evolution_reverse_context(self):
        """evolution 反向信号 context 基础模板

        模拟 PONS 案例：持仓 long + BTC short conf=1.0 src=evolution（反向）
        + 亏损 -4% + 持仓 9.6h → 应触发 30% 减仓
        """
        return {
            "symbol": "PONS", "inst_id": "PONS-USDT-SWAP", "pos_side": "long",
            "entry_price": 100.0, "current_price": 96.0,
            "upl": -4.0, "upl_ratio": -0.04,  # 亏损 4%
            "position_age_sec": 9.6 * 3600,  # 9.6h（超过保护期 1h，远未达 29h 超时）
            "r_vector": {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5},
            "ess": 0.6, "ftc_track": "exploit", "regime": "ranging",
            "atr_pct": 0.02, "tier": "standard",
            "current_sl_px": 92.0, "current_tp_px": 108.0,
            "okx_algo_triggered": False,
            # evolution 反向信号字段
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "is_opposite": True,  # 反向信号
                "coin": "BTC",
                "direction": "short",  # 持仓 long，BTC short → 反向
                "confidence": 1.0,
                "src": "evolution",
            },
            # BCRM2.0 反向信号字段清空（避免规则 2b 先触发）
            "bcrm_reverse_dir": "",
            "bcrm_reverse_conf": 0.0,
            "bcrm_reverse_ts": 0.0,
            "bdsm_direction_constraint": "",
        }

    def test_evolution_reverse_triggers_partial_close_30pct(self, engine, evolution_reverse_context):
        """亏损 -4%（-3%~-5% 档）→ partial_close 30%"""
        decision = engine.decide(evolution_reverse_context)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.30
        assert "evolution_reverse_reduce" in decision.reason

    def test_evolution_reverse_loss_5pct_triggers_50pct(self, engine, evolution_reverse_context):
        """亏损 -5.5%（-5%~-8% 档）→ partial_close 50%"""
        ctx = dict(evolution_reverse_context)
        ctx["upl_ratio"] = -0.055
        decision = engine.decide(ctx)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.50
        assert "evolution_reverse_reduce" in decision.reason

    def test_evolution_reverse_loss_8pct_force_close(self, engine, evolution_reverse_context):
        """亏损 -8.5%（≥-8% 档）→ force_close（全平）"""
        ctx = dict(evolution_reverse_context)
        ctx["upl_ratio"] = -0.085
        decision = engine.decide(ctx)
        assert decision.action == "force_close"
        assert "evolution_reverse_reduce" in decision.reason

    def test_no_stronger_signal_fail_open(self, engine, evolution_reverse_context):
        """has_stronger_signal=False → 不触发（落回后续规则）"""
        ctx = dict(evolution_reverse_context)
        ctx["has_stronger_signal"] = False
        decision = engine.decide(ctx)
        assert "evolution_reverse_reduce" not in (decision.reason or "")

    def test_not_opposite_fail_open(self, engine, evolution_reverse_context):
        """is_opposite=False（同向信号）→ 不触发减仓"""
        ctx = dict(evolution_reverse_context)
        ctx["stronger_signal_info"] = {
            "is_opposite": False,
            "coin": "BTC",
            "direction": "long",  # 持仓 long，BTC long → 同向
            "confidence": 1.0,
            "src": "evolution",
        }
        decision = engine.decide(ctx)
        assert "evolution_reverse_reduce" not in (decision.reason or "")

    def test_profit_not_trigger(self, engine, evolution_reverse_context):
        """upl_ratio > 0（盈利态）→ 不触发 evolution 反向减仓（走 trailing/保本位）"""
        ctx = dict(evolution_reverse_context)
        ctx["upl_ratio"] = 0.05  # 盈利 5%
        ctx["current_price"] = 105.0
        decision = engine.decide(ctx)
        assert "evolution_reverse_reduce" not in (decision.reason or "")

    def test_zero_loss_not_trigger(self, engine, evolution_reverse_context):
        """upl_ratio = 0.0（持平）→ 不触发（需要严格亏损态 upl_ratio < 0）"""
        ctx = dict(evolution_reverse_context)
        ctx["upl_ratio"] = 0.0
        decision = engine.decide(ctx)
        assert "evolution_reverse_reduce" not in (decision.reason or "")

    def test_protection_period_blocks_trigger(self, engine, evolution_reverse_context):
        """position_age_sec < 1h（保护期内）→ 被规则 1 hold，不触发规则 2d"""
        ctx = dict(evolution_reverse_context)
        ctx["position_age_sec"] = 30 * 60  # 30min，保护期内
        decision = engine.decide(ctx)
        assert decision.action == "hold"
        assert "protection_period" in decision.reason
        assert "evolution_reverse_reduce" not in decision.reason

    def test_stronger_signal_info_missing_fail_open(self, engine, evolution_reverse_context):
        """stronger_signal_info 缺失 → 不触发（FAIL-OPEN）"""
        ctx = dict(evolution_reverse_context)
        ctx["stronger_signal_info"] = None
        decision = engine.decide(ctx)
        assert "evolution_reverse_reduce" not in (decision.reason or "")

    def test_short_position_evolution_reverse_triggers(self, engine, evolution_reverse_context):
        """持仓 short + BTC long conf=1.0（反向）+ 亏损 → partial_close 30%"""
        ctx = dict(evolution_reverse_context)
        ctx["pos_side"] = "short"
        ctx["stronger_signal_info"] = {
            "is_opposite": True,
            "coin": "BTC",
            "direction": "long",  # 持仓 short，BTC long → 反向
            "confidence": 1.0,
            "src": "evolution",
        }
        decision = engine.decide(ctx)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.30
        assert "evolution_reverse_reduce" in decision.reason


# ============================================================================
# outcome 标签提取：evolution_reverse_reduce → PARTIAL_REDUCE
# ============================================================================

class TestOutcomeExtractionEvolutionReduce:
    """从 reason 提取 PARTIAL_REDUCE outcome 标签（evolution_reverse_reduce 源）"""

    def test_outcome_extraction_evolution_reduce(self):
        """reason 含 evolution_reverse_reduce → outcome=PARTIAL_REDUCE"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        reason = "evolution_exit:partial_close:evolution_reverse_reduce_conf1.00_loss-4%"
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason=reason, okx_algo_triggered=False, pnl=-4.0, pos_side="long",
        )
        assert outcome == "PARTIAL_REDUCE"

    def test_outcome_extraction_evolution_force_close(self):
        """reason 含 evolution_reverse_reduce + force_close → outcome=PARTIAL_REDUCE"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        reason = "evolution_exit:force_close:evolution_reverse_reduce_conf1.00_loss-8.5%"
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason=reason, okx_algo_triggered=False, pnl=-8.5, pos_side="long",
        )
        assert outcome == "PARTIAL_REDUCE"


# ============================================================================
# 规则 2d 冷却期：evolution 反向信号减仓 4H 冷却
# ============================================================================

class TestEvolutionReverseReduceCooldown:
    """evolution 反向信号减仓 4H 冷却期测试

    冷却期规则：
    - 首次触发减仓 → 记录 ts 到 _last_evolution_reduce_ts
    - 冷却期内（< 4H）→ 跳过规则 2d，落回后续规则
    - 冷却期后（≥ 4H）→ 可以再次触发减仓
    - 冷却期按 symbol 独立（与 _last_bcrm_reduce_ts 独立，互不干扰）
    """

    @pytest.fixture
    def engine(self):
        """构造 EvolutionExitEngine 实例（mock 依赖）"""
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None,
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
        )

    @pytest.fixture
    def evolution_reverse_context(self):
        """evolution 反向信号 context 基础模板"""
        return {
            "symbol": "PONS", "inst_id": "PONS-USDT-SWAP", "pos_side": "long",
            "entry_price": 100.0, "current_price": 96.0,
            "upl": -4.0, "upl_ratio": -0.04,
            "position_age_sec": 9.6 * 3600,
            "r_vector": {"R_up": 0.5, "R_down": 0.5, "R_smooth": 0.5},
            "ess": 0.6, "ftc_track": "exploit", "regime": "ranging",
            "atr_pct": 0.02, "tier": "standard",
            "current_sl_px": 92.0, "current_tp_px": 108.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "is_opposite": True,
                "coin": "BTC",
                "direction": "short",
                "confidence": 1.0,
                "src": "evolution",
            },
            "bcrm_reverse_dir": "",
            "bcrm_reverse_conf": 0.0,
            "bcrm_reverse_ts": 0.0,
            "bdsm_direction_constraint": "",
        }

    def test_engine_has_evolution_reduce_cooldown_dict(self, engine):
        """engine 必须有 _last_evolution_reduce_ts 字典字段（独立于 _last_bcrm_reduce_ts）"""
        assert hasattr(engine, "_last_evolution_reduce_ts"), \
            "engine 必须有 _last_evolution_reduce_ts 字典字段"
        assert engine._last_evolution_reduce_ts != engine._last_bcrm_reduce_ts or \
            id(engine._last_evolution_reduce_ts) != id(engine._last_bcrm_reduce_ts), \
            "_last_evolution_reduce_ts 必须独立于 _last_bcrm_reduce_ts"

    def test_first_trigger_no_cooldown(self, engine, evolution_reverse_context):
        """首次触发 → 应正常 partial_close（无冷却期阻挡）"""
        decision = engine.decide(evolution_reverse_context)
        assert decision.action == "partial_close"
        assert "evolution_reverse_reduce" in decision.reason

    def test_second_trigger_within_4h_skipped(self, engine, evolution_reverse_context):
        """4H 内第二次触发 → 跳过（落回后续规则，不触发 evolution_reverse_reduce）"""
        # 首次触发
        first = engine.decide(evolution_reverse_context)
        assert first.action == "partial_close"
        assert "evolution_reverse_reduce" in first.reason
        # 立即第二次触发（< 4H 冷却期内）
        second = engine.decide(evolution_reverse_context)
        # 不应再触发 evolution_reverse_reduce 的 partial_close
        assert "evolution_reverse_reduce" not in (second.reason or "")

    def test_second_trigger_after_4h_allowed(self, engine, evolution_reverse_context):
        """4H 后第二次触发 → 可以再次触发减仓"""
        # 首次触发
        first = engine.decide(evolution_reverse_context)
        assert first.action == "partial_close"
        # 推进 4H+1 秒
        _now = time.time()
        engine._last_evolution_reduce_ts["PONS"] = _now - (4 * 3600 + 1)
        # 第二次触发
        second = engine.decide(evolution_reverse_context)
        assert second.action == "partial_close"
        assert "evolution_reverse_reduce" in second.reason

    def test_cooldown_isolated_per_symbol(self, engine, evolution_reverse_context):
        """冷却期按 symbol 独立：PONS 在冷却期，RIVER 仍可触发"""
        # PONS 首次触发
        first = engine.decide(evolution_reverse_context)
        assert first.action == "partial_close"
        # RIVER 首次触发（与 PONS 不同 symbol）
        river_ctx = dict(evolution_reverse_context)
        river_ctx["symbol"] = "RIVER"
        second = engine.decide(river_ctx)
        # RIVER 不受 PONS 冷却期影响
        assert second.action == "partial_close"
        assert "evolution_reverse_reduce" in second.reason

    def test_evolution_cooldown_independent_from_bcrm_cooldown(self, engine, evolution_reverse_context):
        """evolution 冷却期独立于 BCRM 冷却期：BCRM 减仓后不阻挡 evolution 减仓"""
        # 先设置 BCRM 冷却期（模拟规则 2b 刚减仓过）
        _now = time.time()
        engine._last_bcrm_reduce_ts["PONS"] = _now  # BCRM 冷却期内
        # evolution 反向信号应仍能触发（冷却期独立）
        decision = engine.decide(evolution_reverse_context)
        assert decision.action == "partial_close"
        assert "evolution_reverse_reduce" in decision.reason

    def test_cooldown_does_not_block_other_rules(self, engine, evolution_reverse_context):
        """冷却期内不触发规则 2d，但后续规则正常工作"""
        # 首次触发减仓
        first = engine.decide(evolution_reverse_context)
        assert first.action == "partial_close"
        # 第二次：冷却期内，应落回后续规则
        second = engine.decide(evolution_reverse_context)
        # 不应是 evolution_reverse_reduce
        assert "evolution_reverse_reduce" not in (second.reason or "")
        # 应是其他正常决策
        assert second.action in ("hold", "adjust_sl_tp", "trailing", "partial_close", "force_close")
