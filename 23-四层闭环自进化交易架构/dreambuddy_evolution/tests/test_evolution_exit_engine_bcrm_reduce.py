"""BCRM2.0 反向信号触发 partial_close 减仓 TDD 测试

测试覆盖：
- 规则 2b：BCRM2.0 高置信度反向信号 → partial_close（分批减仓）
- 置信度分层：0.85-0.95→30%, 0.95-0.99→50%, ≥0.99+BDSM一致→70%
- FAIL-OPEN：信号缺失/过期/同向 → 不触发（落回后续规则）
- outcome 标签：external_signal_reduce → PARTIAL_REDUCE
- ReflectionEngine：PARTIAL_REDUCE 冷启动 ess_delta=0

硬约束（来自计划）：
- BCRM2.0 反向信号 = 持仓 long 但 bcrm_reverse_dir=short（或反之）
- 信号新鲜度：ts 未超 30min（BCRM_REVERSE_STALE_SEC=1800）
- 减仓幅度 ±0.01 ess_delta（软信号，幅度减半）
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
# 规则 2b：BCRM2.0 反向信号 → partial_close 减仓
# ============================================================================

class TestBCRMReverseReduce:
    """BCRM2.0 反向信号触发分批减仓测试"""

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
    def bcrm_reverse_context(self):
        """BCRM2.0 高置信度反向信号 context 基础模板

        持仓 long + BCRM2.0 方向 short + 置信度 0.91 → 应触发 30% 减仓
        """
        return {
            "symbol": "SKHYNIX", "inst_id": "SKHYNIX-USDT-SWAP", "pos_side": "long",
            "entry_price": 1292.0, "current_price": 1376.0,
            "upl": 23.82, "upl_ratio": 0.065,  # +6.5%
            "position_age_sec": 4131 * 60,  # 68h 超时
            "r_vector": {"R_up": 0.6, "R_down": 0.3, "R_smooth": 0.5},
            "ess": 0.6, "ftc_track": "exploit", "regime": "ranging",
            "atr_pct": 0.02, "tier": "standard",
            "current_sl_px": 1228.0, "current_tp_px": 1447.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": False,
            # BCRM2.0 反向信号字段
            "bcrm_reverse_dir": "short",  # 持仓 long，BCRM2.0 看空 → 反向
            "bcrm_reverse_conf": 0.91,
            "bcrm_reverse_ts": time.time(),  # 新鲜
            "bdsm_direction_constraint": "",
        }

    def test_bcrm_reverse_high_conf_triggers_partial_close_30pct(self, engine, bcrm_reverse_context):
        """置信度 0.91（0.85-0.95 档）→ partial_close 30%"""
        decision = engine.decide(bcrm_reverse_context)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.30
        assert "external_signal_reduce" in decision.reason

    def test_bcrm_reverse_very_high_conf_50pct(self, engine, bcrm_reverse_context):
        """置信度 0.96（0.95-0.99 档）→ partial_close 50%"""
        ctx = dict(bcrm_reverse_context)
        ctx["bcrm_reverse_conf"] = 0.96
        decision = engine.decide(ctx)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.50

    def test_bcrm_reverse_extreme_conf_bdsm_consistent_70pct(self, engine, bcrm_reverse_context):
        """置信度 0.995 + BDSM SHORT_ONLY 方向一致 → partial_close 70%"""
        ctx = dict(bcrm_reverse_context)
        ctx["bcrm_reverse_conf"] = 0.995
        ctx["bdsm_direction_constraint"] = "SHORT_ONLY"  # 与 BCRM2.0 看空一致
        decision = engine.decide(ctx)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.70

    def test_bcrm_conf_below_threshold_no_reduce(self, engine, bcrm_reverse_context):
        """置信度 0.80 < 0.85 阈值 → 不触发减仓（落回后续规则）"""
        ctx = dict(bcrm_reverse_context)
        ctx["bcrm_reverse_conf"] = 0.80
        decision = engine.decide(ctx)
        # 不应是 external_signal_reduce 的 partial_close
        assert not ("external_signal_reduce" in (decision.reason or ""))

    def test_bcrm_signal_missing_fail_open(self, engine, bcrm_reverse_context):
        """context 无 bcrm 字段 → 不触发（FAIL-OPEN）"""
        ctx = dict(bcrm_reverse_context)
        ctx.pop("bcrm_reverse_dir", None)
        ctx.pop("bcrm_reverse_conf", None)
        ctx.pop("bcrm_reverse_ts", None)
        # 应正常返回决策（不抛异常）
        decision = engine.decide(ctx)
        assert decision is not None
        assert "external_signal_reduce" not in (decision.reason or "")

    def test_bcrm_signal_stale_fail_open(self, engine, bcrm_reverse_context):
        """ts 超 30min → 不触发（FAIL-OPEN）"""
        ctx = dict(bcrm_reverse_context)
        ctx["bcrm_reverse_ts"] = time.time() - 2000  # 33min 前
        decision = engine.decide(ctx)
        assert "external_signal_reduce" not in (decision.reason or "")

    def test_bcrm_direction_same_side_no_reduce(self, engine, bcrm_reverse_context):
        """持仓 long + BCRM2.0 方向 long（同向）→ 不触发减仓"""
        ctx = dict(bcrm_reverse_context)
        ctx["bcrm_reverse_dir"] = "long"  # 同向
        ctx["bcrm_reverse_conf"] = 0.91
        decision = engine.decide(ctx)
        assert "external_signal_reduce" not in (decision.reason or "")

    def test_bcrm_reverse_short_position(self, engine, bcrm_reverse_context):
        """持仓 short + BCRM2.0 方向 long → 反向 → 应触发减仓"""
        ctx = dict(bcrm_reverse_context)
        ctx["pos_side"] = "short"
        ctx["bcrm_reverse_dir"] = "long"  # 持仓 short，BCRM2.0 看多 → 反向
        ctx["bcrm_reverse_conf"] = 0.91
        decision = engine.decide(ctx)
        assert decision.action == "partial_close"
        assert decision.params.get("partial_pct") == 0.30


# ============================================================================
# outcome 标签提取：external_signal_reduce → PARTIAL_REDUCE
# ============================================================================

class TestOutcomeExtractionPartialReduce:
    """从 reason 提取 PARTIAL_REDUCE outcome 标签"""

    def test_outcome_extraction_partial_reduce(self):
        """reason 含 external_signal_reduce → outcome=PARTIAL_REDUCE"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        reason = "evolution_exit:partial_close:external_signal_reduce_conf0.91"
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason=reason, okx_algo_triggered=False, pnl=10.0, pos_side="long",
        )
        assert outcome == "PARTIAL_REDUCE"

    def test_outcome_extraction_standard_partial_tp_not_partial_reduce(self):
        """标准 partial_tp（非 external_signal_reduce）→ 不应是 PARTIAL_REDUCE"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        reason = "evolution_exit:partial_close:batch1_r1_pct50%"
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason=reason, okx_algo_triggered=False, pnl=10.0, pos_side="long",
        )
        assert outcome != "PARTIAL_REDUCE"


# ============================================================================
# ReflectionEngine：PARTIAL_REDUCE 冷启动中性
# ============================================================================

class TestReflectionPartialReduceColdStart:
    """ReflectionEngine.apply_reward 对 PARTIAL_REDUCE 的冷启动处理"""

    def test_reflection_partial_reduce_cold_start_neutral(self):
        """冷启动（样本 < 20）→ ess_delta=0"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        # PARTIAL_REDUCE 冷启动：ess_delta 应为 0
        result = engine.apply_reward(
            cs=0.8,  # 高 CS
            outcome="PARTIAL_REDUCE",
            cluster_id="bcrm_reverse_cluster",
            ess_id="exit_track_1",
            gmax=1.0,
        )
        assert result.get("ess_delta") == 0.0
        assert result.get("gmax_mult") == 1.0


# ============================================================================
# 规则 2b 冷却期：BCRM2.0 反向信号减仓 4H 冷却
# ============================================================================

class TestBCRMReverseReduceCooldown:
    """BCRM2.0 反向信号减仓 4H 冷却期测试

    问题背景（SKHYNIX 案例，2026-09-09）：
    - 47 分钟内被连续减仓 7 次（每次 30%），仓位从 100% → 8.2%
    - 但股价全程 +6% 盈利，绝对盈亏从 21U 缩到 3.7U
    - 系统在摧毁一个盈利仓位

    冷却期规则：
    - 首次触发减仓 → 记录 ts
    - 冷却期内（< 4H）→ 跳过规则 2b，落回后续规则
    - 冷却期后（≥ 4H）→ 可以再次触发减仓
    - 冷却期按 symbol 独立（多仓位互不干扰）
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
    def bcrm_reverse_context(self):
        """BCRM2.0 高置信度反向信号 context 基础模板"""
        return {
            "symbol": "SKHYNIX", "inst_id": "SKHYNIX-USDT-SWAP", "pos_side": "long",
            "entry_price": 1292.0, "current_price": 1376.0,
            "upl": 23.82, "upl_ratio": 0.065,
            "position_age_sec": 4131 * 60,
            "r_vector": {"R_up": 0.6, "R_down": 0.3, "R_smooth": 0.5},
            "ess": 0.6, "ftc_track": "exploit", "regime": "ranging",
            "atr_pct": 0.02, "tier": "standard",
            "current_sl_px": 1228.0, "current_tp_px": 1447.0,
            "okx_algo_triggered": False,
            "has_stronger_signal": False,
            "bcrm_reverse_dir": "short",
            "bcrm_reverse_conf": 0.91,
            "bcrm_reverse_ts": time.time(),
            "bdsm_direction_constraint": "",
        }

    def test_first_trigger_no_cooldown(self, engine, bcrm_reverse_context):
        """首次触发 → 应正常 partial_close（无冷却期阻挡）"""
        decision = engine.decide(bcrm_reverse_context)
        assert decision.action == "partial_close"
        assert "external_signal_reduce" in decision.reason

    def test_second_trigger_within_4h_skipped(self, engine, bcrm_reverse_context):
        """4H 内第二次触发 → 跳过（落回后续规则，不触发 external_signal_reduce）"""
        # 首次触发
        first = engine.decide(bcrm_reverse_context)
        assert first.action == "partial_close"
        # 立即第二次触发（< 4H 冷却期内）
        second = engine.decide(bcrm_reverse_context)
        # 不应再触发 external_signal_reduce 的 partial_close
        assert "external_signal_reduce" not in (second.reason or "")

    def test_second_trigger_after_4h_allowed(self, engine, bcrm_reverse_context):
        """4H 后第二次触发 → 可以再次触发减仓"""
        # 首次触发
        first = engine.decide(bcrm_reverse_context)
        assert first.action == "partial_close"
        # 模拟 4H+1 秒后再次触发：手动推进冷却时间戳
        assert hasattr(engine, "_last_bcrm_reduce_ts"), "engine 必须有 _last_bcrm_reduce_ts 字典"
        # 推进 4H+1s
        _now = time.time()
        engine._last_bcrm_reduce_ts["SKHYNIX"] = _now - (4 * 3600 + 1)
        # 第二次触发
        second = engine.decide(bcrm_reverse_context)
        assert second.action == "partial_close"
        assert "external_signal_reduce" in second.reason

    def test_cooldown_isolated_per_symbol(self, engine, bcrm_reverse_context):
        """冷却期按 symbol 独立：SKHYNIX 在冷却期，PUMP 仍可触发"""
        # SKHYNIX 首次触发
        skhynix_ctx = dict(bcrm_reverse_context)
        skhynix_ctx["symbol"] = "SKHYNIX"
        first = engine.decide(skhynix_ctx)
        assert first.action == "partial_close"
        # PUMP 首次触发（与 SKHYNIX 不同 symbol）
        pump_ctx = dict(bcrm_reverse_context)
        pump_ctx["symbol"] = "PUMP"
        pump_ctx["bcrm_reverse_conf"] = 0.91
        second = engine.decide(pump_ctx)
        # PUMP 不受 SKHYNIX 冷却期影响
        assert second.action == "partial_close"
        assert "external_signal_reduce" in second.reason

    def test_cooldown_does_not_block_other_rules(self, engine, bcrm_reverse_context):
        """冷却期内不触发规则 2b，但后续规则（trailing/adjust/hold）正常工作"""
        # 首次触发减仓
        first = engine.decide(bcrm_reverse_context)
        assert first.action == "partial_close"
        # 第二次：冷却期内，应落回后续规则
        # 此 context upl_ratio=0.065 > BREAK_EVEN_ARM_PCT(0.03)，应触发 adjust_sl_tp 或 trailing
        second = engine.decide(bcrm_reverse_context)
        # 不应是 external_signal_reduce
        assert "external_signal_reduce" not in (second.reason or "")
        # 应是其他正常决策（hold/adjust_sl_tp/trailing）
        assert second.action in ("hold", "adjust_sl_tp", "trailing")
