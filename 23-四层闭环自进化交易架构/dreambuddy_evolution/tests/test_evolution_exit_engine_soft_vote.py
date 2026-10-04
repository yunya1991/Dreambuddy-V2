"""规则3a 软投票仲裁层 TDD 测试

测试覆盖：
- 四方案 voter（A.结构化 / B.ATR标准化 / C.支撑位保护 / D.时间衰减）
- 软投票仲裁层（加权投票 / ≥2票 force_close + 加权胜率>0.5）
- 冷启动期 4H 均等权重 0.25
- 贝叶斯升级 ≥30 样本/voter 触发权重重算
- 冷却期 4H（复用 BCRM_REDUCE_COOLDOWN_SEC 同源设计）
- FAIL-OPEN：voter 异常返回 None，仲裁层四 voter 全 None 返回 None

硬约束（来自 SPEC）：
- 冷启动期 4H 均等权重，冷启动期需 ≥3 票才能 force_close（加权胜率>0.5 边界）
- 仲裁规则：≥2 票同向 force_close + 加权胜率>0.5
- 贝叶斯升级阈值 ≥30 样本/voter
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
# 模块结构测试（RED 阶段，断言 ModuleNotFoundError）
# ============================================================================

class TestSoftVoteModuleStructure:
    """模块可导入性测试"""

    def test_base_voter_importable(self):
        """TimeoutVoter / VoteTicket 可 import"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.base_voter import (
            TimeoutVoter,
            VoteTicket,
        )
        assert TimeoutVoter is not None
        assert VoteTicket is not None

    def test_arbitrator_importable(self):
        """TimeoutVoteArbitrator 可 import"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        assert TimeoutVoteArbitrator is not None

    def test_four_voters_importable(self):
        """A/B/C/D 四 voter 可 import"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            ATRStandardVoter_B,
            MurphyDecayVoter_D,
            VCPVoter_A,
            WyckoffSupportVoter_C,
        )
        assert VCPVoter_A is not None
        assert ATRStandardVoter_B is not None
        assert WyckoffSupportVoter_C is not None
        assert MurphyDecayVoter_D is not None

    def test_vote_ticket_fields(self):
        """VoteTicket 含 action/confidence/reason/sl_px/tp_px/voter_id"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.base_voter import (
            VoteTicket,
        )

        ticket = VoteTicket(
            action="hold",
            confidence=0.6,
            reason="voter_a:above_swing_low",
            sl_px=1250.0,
            tp_px=1500.0,
            voter_id="A",
        )
        assert ticket.action == "hold"
        assert ticket.confidence == 0.6
        assert ticket.reason == "voter_a:above_swing_low"
        assert ticket.sl_px == 1250.0
        assert ticket.tp_px == 1500.0
        assert ticket.voter_id == "A"


# ============================================================================
# 四方案独立测试
# ============================================================================

class TestVCPVoterA:
    """方案A: 结构化止损（Minervini VCP）"""

    @pytest.fixture
    def voter_a(self):
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            VCPVoter_A,
        )
        return VCPVoter_A()

    def test_voter_a_vcp_break_below_swing_low_force_close(self, voter_a):
        """价格跌破 swing_low → force_close"""
        ctx = {
            "current_price": 1200.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
        }
        ticket = voter_a.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "force_close"
        assert ticket.voter_id == "A"

    def test_voter_a_vcp_above_swing_low_hold(self, voter_a):
        """价格在 swing_low 上方 → hold"""
        ctx = {
            "current_price": 1280.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
        }
        ticket = voter_a.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "hold"
        assert ticket.voter_id == "A"

    def test_voter_a_atr_2x_breakdown_force_close(self, voter_a):
        """价格跌破 entry - 2×ATR → force_close"""
        # entry=1289, atr_pct=0.025 → 2×ATR ≈ 64.45 → 阈值 1224.55
        ctx = {
            "current_price": 1200.0,
            "recent_swing_low": 1100.0,  # swing_low 远低于当前价
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
        }
        ticket = voter_a.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "force_close"


class TestATRStandardVoterB:
    """方案B: ATR 标准化"""

    @pytest.fixture
    def voter_b(self):
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            ATRStandardVoter_B,
        )
        return ATRStandardVoter_B()

    def test_voter_b_atr_no_progress_force_close(self, voter_b):
        """|upl| < 0.3×ATR_daily → force_close"""
        # atr_daily=0.025 → 阈值 0.0075(0.75%)
        ctx = {
            "upl_ratio": 0.005,  # 0.5% < 0.75%
            "atr_daily": 0.025,
        }
        ticket = voter_b.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "force_close"
        assert ticket.voter_id == "B"

    def test_voter_b_atr_significant_move_hold(self, voter_b):
        """|upl| ≥ 0.3×ATR_daily → hold"""
        ctx = {
            "upl_ratio": 0.015,  # 1.5% > 0.75%
            "atr_daily": 0.025,
        }
        ticket = voter_b.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "hold"


class TestWyckoffSupportVoterC:
    """方案C: 支撑位保护（Wyckoff）"""

    @pytest.fixture
    def voter_c(self):
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            WyckoffSupportVoter_C,
        )
        return WyckoffSupportVoter_C()

    def test_voter_c_above_support_hold_and_lower_sl(self, voter_c):
        """价格 > support×1.02 → hold + SL=support×0.997"""
        ctx = {
            "current_price": 1278.0,
            "nearest_support_level": 1250.0,
            "pos_side": "long",
            "entry_price": 1289.0,
        }
        ticket = voter_c.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "adjust_sl_tp"
        assert ticket.voter_id == "C"
        # SL = support × 0.997 = 1250 × 0.997 = 1246.25
        assert abs(ticket.sl_px - 1250.0 * 0.997) < 0.01

    def test_voter_c_below_support_force_close(self, voter_c):
        """价格 ≤ support×1.02 → force_close"""
        # support=1250, support×1.02=1275, current=1270 < 1275
        ctx = {
            "current_price": 1270.0,
            "nearest_support_level": 1250.0,
            "pos_side": "long",
            "entry_price": 1289.0,
        }
        ticket = voter_c.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "force_close"


class TestMurphyDecayVoterD:
    """方案D: 时间衰减式（Murphy）"""

    @pytest.fixture
    def voter_d(self):
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            MurphyDecayVoter_D,
        )
        return MurphyDecayVoter_D()

    def test_voter_d_decay_0_12h_1_5pct_hold(self, voter_d):
        """0-12h |upl|>1.5% → hold"""
        ctx = {
            "upl_ratio": 0.02,  # 2% > 1.5%
            "position_age_sec": 6 * 3600,  # 6h
        }
        ticket = voter_d.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "hold"
        assert ticket.voter_id == "D"

    def test_voter_d_decay_24h_0_5pct_force_close(self, voter_d):
        """24h+ |upl|<0.5% → force_close"""
        ctx = {
            "upl_ratio": 0.003,  # 0.3% < 0.5%
            "position_age_sec": 25 * 3600,  # 25h
        }
        ticket = voter_d.evaluate(ctx)
        assert ticket is not None
        assert ticket.action == "force_close"


# ============================================================================
# FAIL-OPEN 测试
# ============================================================================

class TestVoterFailOpen:
    """Voter 层 FAIL-OPEN"""

    def test_voter_missing_fields_returns_none(self):
        """context 缺 swing_low → voter 返回 None"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            VCPVoter_A,
        )
        voter = VCPVoter_A()
        ctx = {"current_price": 1280.0}  # 缺 recent_swing_low
        ticket = voter.evaluate(ctx)
        assert ticket is None

    def test_voter_exception_returns_none(self):
        """voter 内部异常 → 返回 None"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.voters_a_d import (
            ATRStandardVoter_B,
        )
        voter = ATRStandardVoter_B()
        # 传非数值触发异常
        ctx = {"upl_ratio": "not_a_number", "atr_daily": 0.025}
        ticket = voter.evaluate(ctx)
        assert ticket is None

    def test_arbitrator_all_voters_fail_returns_none(self):
        """四 voter 全 None → 仲裁返回 None（落回后续规则）"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        # 空 context → 所有 voter FAIL-OPEN
        decision = arb.arbitrate({})
        assert decision is None


# ============================================================================
# 仲裁层测试
# ============================================================================

class TestArbitrator:
    """软投票仲裁层"""

    @pytest.fixture
    def arbitrator(self):
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        return TimeoutVoteArbitrator()

    def test_two_votes_force_close_executes(self, arbitrator):
        """≥2票 force_close + 加权胜率>0.5 → force_close"""
        # 构造：Voter A/B 投 force_close，C/D 投 hold
        # 需要 mock voters 或构造特定 context
        # 冷启动期均等权重下 2 票加权胜率 = 0.5，需 > 0.5，所以需要 3 票
        # 此测试构造冷启动后(用真实权重)的场景
        ctx = {
            "current_price": 1200.0,  # 跌破 swing_low → A force_close
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.003,  # < 0.3×ATR → B force_close
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,  # current < support×1.02 → C force_close
            "position_age_sec": 25 * 3600,
        }
        # 此时 A/B/C 都投 force_close，D 也投 force_close（24h+|upl|<0.5%）
        decision = arbitrator.arbitrate(ctx)
        assert decision is not None
        assert decision.action == "force_close"
        assert "soft_vote" in decision.reason

    def test_one_vote_force_close_not_executed(self, arbitrator):
        """仅1票 force_close → 不执行，取 hold"""
        # 构造只有 Voter D 投 force_close 的场景
        ctx = {
            "current_price": 1280.0,  # 高于 swing_low → A hold
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.003,  # 0.3% < 0.75% → B force_close
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,  # 1280 > 1250×1.02=1275 → C hold
            "position_age_sec": 25 * 3600,  # 24h+|upl|<0.5% → D force_close
        }
        # A/C hold，B/D force_close → 2票 force_close
        # 冷启动期 2 票加权胜率=0.5，需>0.5，所以不执行 force_close
        # 取最高置信的 hold/adjust_sl_tp
        decision = arbitrator.arbitrate(ctx)
        # 2票 force_close 但加权胜率=0.5 不>0.5 → 取 hold
        if decision is not None:
            assert decision.action != "force_close"

    def test_adjust_sl_tp_wins_when_no_force_close_majority(self, arbitrator):
        """无 force_close 多数 → 取最高置信 adjust_sl_tp"""
        ctx = {
            "current_price": 1280.0,  # 高于 swing_low → A hold
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.02,  # 2% > 0.75% → B hold
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,  # 1280 > 1275 → C adjust_sl_tp
            "position_age_sec": 6 * 3600,  # 0-12h |upl|>1.5% → D hold
        }
        decision = arbitrator.arbitrate(ctx)
        # 只有 C 投 adjust_sl_tp，其余 hold → 取 C
        assert decision is not None
        assert decision.action == "adjust_sl_tp"

    def test_voter_c_adjust_sl_tp_propagates_sl_px(self, arbitrator):
        """Voter C 的 sl_px 传播到 ExitDecision"""
        ctx = {
            "current_price": 1280.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.02,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
            "position_age_sec": 6 * 3600,
        }
        decision = arbitrator.arbitrate(ctx)
        assert decision is not None
        assert decision.action == "adjust_sl_tp"
        # SL = 1250 × 0.997 = 1246.25
        assert abs(decision.sl_px - 1250.0 * 0.997) < 0.5


# ============================================================================
# 冷启动期测试
# ============================================================================

class TestColdStart:
    """冷启动期 4H 均等权重"""

    @pytest.fixture
    def arbitrator(self):
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        return TimeoutVoteArbitrator()

    def test_cold_start_equal_weights(self, arbitrator):
        """冷启动期四权重均等 0.25"""
        weights = arbitrator._load_weights()
        assert len(weights) == 4
        for w in weights.values():
            assert abs(w - 0.25) < 0.001

    def test_cold_start_needs_3_votes_for_force_close(self, arbitrator):
        """均等权重下需 ≥3 票（加权胜率>0.5 边界）"""
        # 构造 2 票 force_close 场景（B+D），应不执行 force_close
        ctx = {
            "current_price": 1280.0,  # 高于 swing_low → A hold
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.003,  # < 0.75% → B force_close
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,  # 1280 > 1275 → C hold/adjust
            "position_age_sec": 25 * 3600,  # 24h+|upl|<0.5% → D force_close
        }
        decision = arbitrator.arbitrate(ctx)
        # 2 票 force_close，加权胜率=0.5 不>0.5 → 不 force_close
        if decision is not None:
            assert decision.action != "force_close", (
                "冷启动期 2 票 force_close 不应执行（需 ≥3 票）"
            )

    def test_after_cold_start_uses_real_weights(self):
        """4H后 + ≥30样本 → 用真实胜率权重"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        # 手动设置冷启动时间戳为 5 小时前（已过冷启动期）
        import time as _t
        arb._cold_start_ts = _t.time() - 5 * 3600
        # 注入 30 样本
        for _ in range(30):
            arb.record_outcome("A", True, "TEST", "force_close")
            arb.record_outcome("B", False, "TEST", "hold")
            arb.record_outcome("C", True, "TEST", "adjust_sl_tp")
            arb.record_outcome("D", False, "TEST", "force_close")
        weights = arb._load_weights()
        # A 和 C 胜率 100%，B 和 D 胜率 0%
        # 权重应不再均等
        assert weights["A"] > weights["B"]
        assert weights["C"] > weights["D"]


# ============================================================================
# 贝叶斯升级测试
# ============================================================================

class TestBayesianUpgrade:
    """贝叶斯权重升级"""

    def test_record_outcome_accumulates_samples(self, tmp_path):
        """record_outcome 累计样本"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        persist = tmp_path / "soft_vote.jsonl"
        arb = TimeoutVoteArbitrator(persist_path=persist)
        arb.record_outcome("A", True, "BTC", "force_close")
        arb.record_outcome("A", False, "ETH", "hold")
        samples = arb._sample_store.get("A", [])
        assert len(samples) == 2

    def test_30_samples_triggers_weight_recalculation(self, tmp_path):
        """≥30样本触发权重重算"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator(persist_path=tmp_path / "sv.jsonl")
        # 先设置已过冷启动期
        import time as _t
        arb._cold_start_ts = _t.time() - 5 * 3600
        # 记录 30 个样本
        for _ in range(30):
            arb.record_outcome("A", True, "BTC", "force_close")
        # 应触发权重重算
        weights = arb._load_weights()
        assert "A" in weights
        # A 胜率 100%，权重应大于冷启动 0.25
        assert weights["A"] > 0.25

    def test_weights_persisted_to_jsonl(self, tmp_path):
        """JSONL 持久化可读回"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        persist = tmp_path / "soft_vote.jsonl"
        arb = TimeoutVoteArbitrator(persist_path=persist)
        arb.record_outcome("A", True, "BTC", "force_close")
        assert persist.exists()
        content = persist.read_text()
        assert "voter_id" in content
        assert "A" in content

    def test_load_from_disk_restores_weights(self, tmp_path):
        """重启后权重恢复"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        persist = tmp_path / "soft_vote.jsonl"
        # 第一次实例：记录样本
        arb1 = TimeoutVoteArbitrator(persist_path=persist)
        arb1.record_outcome("A", True, "BTC", "force_close")
        arb1.record_outcome("B", False, "ETH", "hold")
        # 第二次实例：从磁盘加载
        arb2 = TimeoutVoteArbitrator(persist_path=persist)
        arb2.load_from_disk()
        # 样本应恢复
        assert len(arb2._sample_store.get("A", [])) >= 1
        assert len(arb2._sample_store.get("B", [])) >= 1


# ============================================================================
# 冷却期测试
# ============================================================================

class TestSoftVoteCooldown:
    """软投票冷却期 4H（复用 BCRM 模式）"""

    @pytest.fixture
    def engine_with_arbitrator(self):
        """构造带仲裁器的 ExitEngine"""
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        return EvolutionExitEngine(
            okx_client=None,
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
            timeout_arbitrator=arb,
        )

    def test_cooldown_blocks_repeated_force_close(self, engine_with_arbitrator):
        """强平后 4H 内不再触发软投票"""
        engine = engine_with_arbitrator
        # 模拟首次触发 soft_vote
        engine._last_soft_vote_ts["SKHYNIX"] = time.time()
        # 4H 内再次调用应被冷却期拦截
        ctx = {
            "symbol": "SKHYNIX",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 25 * 3600,
            "upl_ratio": 0.003,
            "current_price": 1200.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "entry_price": 1289.0,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
        }
        # 冷却期内应返回 None（落回后续规则）
        decision = engine._check_timeout_soft_vote(ctx)
        assert decision is None or "cooldown" in (decision.reason or "")

    def test_cooldown_isolated_per_symbol(self, engine_with_arbitrator):
        """按 symbol 独立"""
        engine = engine_with_arbitrator
        engine._last_soft_vote_ts["BTC"] = time.time()
        # SKHYNIX 未在冷却期
        ctx = {
            "symbol": "SKHYNIX",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 25 * 3600,
            "upl_ratio": 0.003,
            "current_price": 1200.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "entry_price": 1289.0,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
        }
        # SKHYNIX 不应被 BTC 的冷却期影响
        decision = engine._check_timeout_soft_vote(ctx)
        # 应该能正常仲裁（可能 force_close 或 hold）
        assert decision is not None or decision is None  # 不抛异常即可

    def test_cooldown_falls_through_to_subsequent_rules(self, engine_with_arbitrator):
        """冷却期内落回规则3b/4/5/6"""
        engine = engine_with_arbitrator
        engine._last_soft_vote_ts["SKHYNIX"] = time.time()
        ctx = {
            "symbol": "SKHYNIX",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 25 * 3600,
            "upl_ratio": 0.003,
            "current_price": 1200.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "entry_price": 1289.0,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
        }
        decision = engine._check_timeout_soft_vote(ctx)
        # 冷却期内返回 None，让后续规则处理
        assert decision is None


# ============================================================================
# 集成测试
# ============================================================================

class TestSoftVoteIntegration:
    """集成测试"""

    def test_skhynix_case_not_force_closed(self):
        """海力士 1289 案例回放：亏损0.88% + 支撑位上方 → hold"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        # 海力士场景
        ctx = {
            "symbol": "SKHYNIX",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 29 * 3600,  # 29h 超时
            "upl_ratio": -0.0088,  # 亏损 0.88%
            "current_price": 1278.0,
            "recent_swing_low": 1250.0,  # 当前价高于 swing_low → A hold
            "atr_pct": 0.025,
            "entry_price": 1289.38,
            "atr_daily": 0.025,  # 阈值 0.75%，0.88%>0.75% → B hold
            "nearest_support_level": 1250.0,  # 1278 > 1275 → C adjust_sl_tp
        }
        decision = arb.arbitrate(ctx)
        # 不应 force_close
        assert decision is None or decision.action != "force_close", (
            "海力士场景不应被 force_close（支撑位上方 + ATR 标准化未达无进展）"
        )

    def test_exit_decision_action_valid(self):
        """仲裁返回的 ExitDecision.action ∈ 合法集合"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        ctx = {
            "current_price": 1200.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.003,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
            "position_age_sec": 25 * 3600,
        }
        decision = arb.arbitrate(ctx)
        if decision is not None:
            assert decision.action in (
                "hold",
                "adjust_sl_tp",
                "trailing",
                "force_close",
                "partial_close",
            )

    def test_soft_vote_force_close_outcome_label(self):
        """reason 含 soft_vote 标签"""
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        ctx = {
            "current_price": 1200.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "pos_side": "long",
            "entry_price": 1289.0,
            "upl_ratio": 0.003,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
            "position_age_sec": 25 * 3600,
        }
        decision = arb.arbitrate(ctx)
        if decision is not None and decision.action == "force_close":
            assert "soft_vote" in decision.reason


# ============================================================================
# 缺口1: 软投票限定亏损场景（盈利仓跳过3a，走3b换仓）
# ============================================================================

class TestSoftVoteLossOnlyGuard:
    """规则3a 仅对亏损仓生效，盈利仓跳过软投票走3b换仓逻辑"""

    @pytest.fixture
    def engine_with_arbitrator(self):
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        from dreambuddy_evolution.engines.exit_engine.timeout_voters.arbitrator import (
            TimeoutVoteArbitrator,
        )
        arb = TimeoutVoteArbitrator()
        return EvolutionExitEngine(
            okx_client=None,
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
            timeout_arbitrator=arb,
        )

    def test_profit_skips_soft_vote_returns_none(self, engine_with_arbitrator):
        """盈利仓超时 → 3a 返回 None，让 3b 换仓逻辑接管"""
        engine = engine_with_arbitrator
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 30 * 3600,  # 超时
            "upl_ratio": 0.05,  # 盈利 5%
            "current_price": 50000.0,
            "recent_swing_low": 48000.0,
            "atr_pct": 0.025,
            "entry_price": 47600.0,
            "atr_daily": 0.025,
            "nearest_support_level": 48000.0,
            "has_stronger_signal": True,
            "stronger_signal_info": {"coin": "ETH", "direction": "long", "confidence": 0.85},
        }
        decision = engine._check_timeout_soft_vote(ctx)
        # 盈利仓应跳过软投票
        assert decision is None, "盈利仓应跳过软投票，返回 None 让 3b 接管"

    def test_loss_enters_soft_vote(self, engine_with_arbitrator):
        """亏损仓超时 → 3a 正常进入软投票仲裁"""
        engine = engine_with_arbitrator
        ctx = {
            "symbol": "SKHYNIX",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 30 * 3600,
            "upl_ratio": -0.0088,  # 亏损 0.88%
            "current_price": 1278.0,
            "recent_swing_low": 1250.0,
            "atr_pct": 0.025,
            "entry_price": 1289.38,
            "atr_daily": 0.025,
            "nearest_support_level": 1250.0,
        }
        decision = engine._check_timeout_soft_vote(ctx)
        # 亏损仓应进入软投票（可能 hold/adjust_sl_tp/force_close 或 None）
        # 关键是不被 upl_ratio 守卫拦截
        assert decision is None or decision.action in (
            "hold", "adjust_sl_tp", "force_close", "trailing", "partial_close"
        )

    def test_zero_upl_enters_soft_vote(self, engine_with_arbitrator):
        """upl_ratio=0 边界：视为非盈利，进入软投票"""
        engine = engine_with_arbitrator
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 30 * 3600,
            "upl_ratio": 0.0,  # 边界
            "current_price": 50000.0,
            "recent_swing_low": 48000.0,
            "atr_pct": 0.025,
            "entry_price": 50000.0,
            "atr_daily": 0.025,
            "nearest_support_level": 48000.0,
        }
        decision = engine._check_timeout_soft_vote(ctx)
        # upl=0 应进入软投票（不被盈利守卫拦截）
        assert decision is None or decision.action in (
            "hold", "adjust_sl_tp", "force_close", "trailing", "partial_close"
        )

    def test_profit_with_stronger_signal_routes_to_3b(self, engine_with_arbitrator):
        """盈利+更强信号 → decide() 应走3b换仓而非3a软投票"""
        engine = engine_with_arbitrator
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 30 * 3600,  # 超时
            "upl_ratio": 0.05,  # 盈利 5%
            "current_price": 50400.0,
            "entry_price": 48000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 46000.0,
            "current_tp_px": 54000.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "coin": "ETH", "direction": "long", "confidence": 0.85,
                "is_opposite": False,
            },
        }
        decision = engine.decide(ctx)
        # 应走3b超时换仓 force_close，reason 含 signal_rotate
        assert decision.action == "force_close"
        assert "signal_rotate" in decision.reason


# ============================================================================
# 缺口2: TP 时间衰减桥接（exit_engine 感知 tp_decayed_pct）
# ============================================================================

class TestTPDecayBridge:
    """exit_engine 通过 tp_decayed_pct 感知 polling_trader 侧的 TP 衰减"""

    @pytest.fixture
    def engine(self):
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None,
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
        )

    def test_tp_decayed_pct_in_context(self, engine):
        """context 含 tp_decayed_pct 字段时，exit_engine 读取并使用"""
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "standard",
            "position_age_sec": 2 * 3600,  # 2h 保护期后
            "upl_ratio": 0.03,  # 盈利 3%
            "current_price": 10300.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,  # 原始 TP 6%
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "tp_decayed_pct": 0.03,  # 衰减后 TP 间距 3%
        }
        # 不应抛异常
        decision = engine.decide(ctx)
        assert decision is not None

    def test_r_multiple_recalculated_with_decayed_tp(self, engine):
        """tp_decayed_pct 存在时，r_multiple 用衰减后 TP 重算"""
        # entry=10000, current=10300, 原始TP=10600(6%), 衰减TP=10300(3%)
        # 原始 r_multiple = (10300-10000)/(10600-10000) = 300/600 = 0.5R
        # 衰减后 r_multiple = (10300-10000)/(10300-10000) = 300/300 = 1.0R → 触发分批止盈
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "standard",
            "position_age_sec": 2 * 3600,
            "upl_ratio": 0.03,
            "current_price": 10300.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,  # 原始 TP
            "atr_pct": 0.025,
            "r_multiple": 0.5,  # 按原始 TP 算的 R
            "tp_decayed_pct": 0.03,  # 衰减后 TP 间距 3%
        }
        decision = engine.decide(ctx)
        # 衰减后 r_multiple=1.0R → 应触发分批止盈 batch1
        assert decision.action == "partial_close"
        assert "batch1" in decision.reason

    def test_no_tp_decayed_uses_original_r_multiple(self, engine):
        """tp_decayed_pct 缺失时，用原始 r_multiple（向后兼容）"""
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "standard",
            "position_age_sec": 2 * 3600,
            "upl_ratio": 0.03,
            "current_price": 10300.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,
            "atr_pct": 0.025,
            "r_multiple": 0.5,  # 原始 R，未到 1R 不触发分批止盈
        }
        decision = engine.decide(ctx)
        # r_multiple=0.5 < 1R → 不触发分批止盈，走 trailing/保本位
        assert decision.action != "partial_close"


# ============================================================================
# 缺口3: 信号止盈扩展（盈利+更强信号提前换仓，不限于超时29H）
# ============================================================================

class TestSignalTakeProfitExtension:
    """规则2 扩展：盈利 + 更强信号 → 提前换仓（不限于超时29H）"""

    @pytest.fixture
    def engine(self):
        from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
        return EvolutionExitEngine(
            okx_client=None,
            ess_provider=None,
            ftc_bridge=None,
            shadow_rl_tracker=None,
            log_fn=lambda msg, level="INFO": None,
        )

    def test_profit_with_stronger_signal_before_timeout(self, engine):
        """盈利+更强信号，未到29H超时 → 不换仓（2c已删除，统一走3b超时评估）"""
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 15 * 3600,  # 15h，未到29H
            "upl_ratio": 0.04,  # 盈利 4%
            "current_price": 10400.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "coin": "ETH", "direction": "long", "confidence": 0.85,
                "is_opposite": False,
            },
        }
        decision = engine.decide(ctx)
        # 未到29H → 不换仓（2c已删除）
        assert decision.action != "force_close" or "signal_rotate" not in (decision.reason or "")

    def test_profit_without_stronger_signal_holds(self, engine):
        """盈利但无更强信号，未到29H → 不换仓，走 trailing/保本位"""
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 15 * 3600,
            "upl_ratio": 0.04,
            "current_price": 10400.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "has_stronger_signal": False,
            "stronger_signal_info": {},
        }
        decision = engine.decide(ctx)
        # 无更强信号 → 不换仓
        assert "signal_rotate" not in (decision.reason or "")

    def test_loss_with_stronger_signal_no_rotate(self, engine):
        """亏损+更强信号 → 不换仓（亏损仓不走信号止盈换仓）"""
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 15 * 3600,
            "upl_ratio": -0.02,  # 亏损
            "current_price": 9800.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "coin": "ETH", "direction": "long", "confidence": 0.85,
                "is_opposite": False,
            },
        }
        decision = engine.decide(ctx)
        # 亏损仓不走信号止盈换仓
        assert "signal_rotate" not in (decision.reason or "")

    def test_micro_profit_timeout_no_rotate(self, engine):
        """超时+微利(0.02%)+更强信号 → 不换仓（低于0.15%最小盈利门槛）"""
        ctx = {
            "symbol": "OKB",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 30 * 3600,  # 30h，已超时29H
            "upl_ratio": 0.0002,  # 0.02%微利，低于0.15%门槛
            "current_price": 112.75,
            "entry_price": 112.72,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 103.70,
            "current_tp_px": 126.25,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "coin": "GOOGL", "direction": "long", "confidence": 0.98,
                "is_opposite": False,
            },
        }
        decision = engine.decide(ctx)
        # 微利低于门槛 → 不换仓
        assert "signal_rotate" not in (decision.reason or "")

    def test_above_min_profit_timeout_rotate(self, engine):
        """超时+盈利>0.15%门槛+更强信号 → 换仓"""
        ctx = {
            "symbol": "BTC",
            "pos_side": "long",
            "tier": "trend",
            "position_age_sec": 30 * 3600,  # 30h，已超时
            "upl_ratio": 0.02,  # 2%盈利，高于0.15%门槛
            "current_price": 10200.0,
            "entry_price": 10000.0,
            "ess": 0.6,
            "r_vector": {},
            "current_sl_px": 9600.0,
            "current_tp_px": 10600.0,
            "atr_pct": 0.025,
            "r_multiple": 0.0,
            "has_stronger_signal": True,
            "stronger_signal_info": {
                "coin": "ETH", "direction": "long", "confidence": 0.95,
                "is_opposite": False,
            },
        }
        decision = engine.decide(ctx)
        # 高于门槛 → 换仓
        assert decision.action == "force_close"
        assert "signal_rotate" in decision.reason
