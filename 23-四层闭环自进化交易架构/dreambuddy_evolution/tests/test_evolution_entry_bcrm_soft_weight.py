"""入场侧 BCRM2.0 反向信号分层治理 TDD 测试

对称于离场侧规则 2b（partial_close），形成开仓-离场学习闭环。

测试覆盖（设计文档 §6 测试计划）：
  Group 1 — 入场权重因子计算（entry_signal_governor.compute_bcrm_entry_weight_factor）
    1. conf≥0.95 + BDSM 方向一致 → 硬否决（veto=True, weight_factor=0）
    2. conf≥0.95（无 BDSM 一致）→ 软权重 ×0.3
    3. conf 0.85-0.95 → 软权重 ×0.5
    4. conf 0.80-0.85 → 软权重 ×0.7
    5. conf 0.85-0.95 + 缓存过期 → 放行（FAIL-OPEN, weight_factor=1.0）
    6. conf 0.85-0.95 + 缓存缺失 → 放行（FAIL-OPEN, weight_factor=1.0）

  Group 2 — 平仓 outcome 提取（TradeSettlementBridge._extract_outcome_from_reason）
    7. 平仓盈利 + weight_reduce_factor=0.5 → REDUCE_WEIGHT_PREMATURE
    8. 平仓亏损 + weight_reduce_factor=0.5 → REDUCE_WEIGHT_CORRECT
    9. weight_reduce_factor=1.0 → 正常 outcome（TP/SL，不触发 REDUCE_WEIGHT）

  Group 3 — ReflectionEngine 奖励路径（apply_reward for REDUCE_WEIGHT_*）
    10. 冷启动期（样本 < 20）→ ess_delta=0（中性，只收集不调整）
    11. 样本 ≥ 20 后 → ess_delta ±0.01

硬约束（来自设计文档 entry_bcrm_soft_weight_design.md）：
  - BCRM2.0 反向信号 = evo_dir=LONG 但 bcrm_dir=DOWN（或反之）
  - 信号新鲜度：ts 未超 30min（BCRM_REVERSE_STALE_SEC=1800）
  - 软权重幅度 ±0.01 ess_delta（软信号，幅度减半，与离场侧 PARTIAL_REDUCE 对齐）
  - ESS 双轨隔离：entry-track vs exit-track 独立计数
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
# Group 1: 入场权重因子计算
# ============================================================================

class TestEntryWeightFactor:
    """入场侧 BCRM2.0 反向信号分层治理：权重因子计算"""

    @pytest.fixture
    def base_params(self):
        """基础参数：evolution LONG vs BCRM2.0 DOWN（反向）"""
        _now = time.time()
        return {
            "bcrm_dir": "DOWN",       # BCRM2.0 看空
            "bcrm_conf": 0.91,        # 置信度 0.91（0.85-0.95 档）
            "bcrm_ts": _now,          # 新鲜
            "evo_dir": "LONG",        # evolution 看多 → 反向
            "bdsm_constraint": "",    # 无 BDSM 约束
            "now": _now,
        }

    def test_conf_ge_0_95_with_bdsm_consistent_hard_veto(self, base_params):
        """测试 1: conf≥0.95 + BDSM 方向一致 → 硬否决，不开仓"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["bcrm_conf"] = 0.96
        params["bdsm_constraint"] = "SHORT_ONLY"  # 与 BCRM DOWN 一致
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is True
        assert result.weight_factor == 0.0

    def test_conf_ge_0_95_without_bdsm_soft_weight_0_3(self, base_params):
        """测试 2: conf≥0.95（无 BDSM 一致）→ 软权重 ×0.3"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["bcrm_conf"] = 0.96
        params["bdsm_constraint"] = ""  # 无 BDSM 一致
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(0.3)
        assert result.bcrm_reverse_conf == pytest.approx(0.96)

    def test_conf_0_85_to_0_95_soft_weight_0_5(self, base_params):
        """测试 3: conf 0.85-0.95 → 仓位 ×0.5，TradeRecord 记录"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        result = compute_bcrm_entry_weight_factor(**base_params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(0.5)
        assert result.bcrm_reverse_conf == pytest.approx(0.91)

    def test_conf_0_80_to_0_85_soft_weight_0_7(self, base_params):
        """测试 4: conf 0.80-0.85 → 仓位 ×0.7"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["bcrm_conf"] = 0.82
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(0.7)
        assert result.bcrm_reverse_conf == pytest.approx(0.82)

    def test_conf_0_85_to_0_95_stale_cache_fail_open(self, base_params):
        """测试 5: conf 0.85-0.95 + 缓存过期 → 放行（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["bcrm_ts"] = params["now"] - 2000  # 33min 前 → 过期
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(1.0)
        assert result.bcrm_reverse_conf == pytest.approx(0.0)

    def test_conf_0_85_to_0_95_missing_cache_fail_open(self, base_params):
        """测试 6: conf 0.85-0.95 + 缓存缺失 → 放行（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["bcrm_dir"] = ""  # 缓存缺失
        params["bcrm_conf"] = 0.0
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(1.0)
        assert result.bcrm_reverse_conf == pytest.approx(0.0)

    def test_same_direction_no_intervention(self, base_params):
        """额外: BCRM2.0 同向（不反向）→ 不干预，weight_factor=1.0"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["bcrm_dir"] = "UP"  # 同向（evolution LONG vs BCRM UP）
        params["bcrm_conf"] = 0.91
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(1.0)
        assert result.bcrm_reverse_conf == pytest.approx(0.0)

    def test_short_position_reverse(self, base_params):
        """额外: 持仓 short + BCRM2.0 UP → 反向 → 软权重 ×0.5"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params)
        params["evo_dir"] = "SHORT"
        params["bcrm_dir"] = "UP"   # 持仓 short，BCRM UP → 反向
        params["bcrm_conf"] = 0.91
        result = compute_bcrm_entry_weight_factor(**params)
        assert result.veto is False
        assert result.weight_factor == pytest.approx(0.5)


# ============================================================================
# Group 2: 平仓 outcome 提取 — REDUCE_WEIGHT
# ============================================================================

class TestOutcomeExtractionReduceWeight:
    """从 weight_reduce_factor 提取 REDUCE_WEIGHT_PREMATURE / CORRECT outcome 标签"""

    def test_outcome_profit_with_reduce_weight_premature(self):
        """测试 7: 平仓盈利 + weight_reduce_factor=0.5 → REDUCE_WEIGHT_PREMATURE"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason="evolution_exit:force_close:okx_algo_triggered",
            okx_algo_triggered=False,
            pnl=10.0,
            pos_side="long",
            weight_reduce_factor=0.5,
        )
        assert outcome == "REDUCE_WEIGHT_PREMATURE"

    def test_outcome_loss_with_reduce_weight_correct(self):
        """测试 8: 平仓亏损 + weight_reduce_factor=0.5 → REDUCE_WEIGHT_CORRECT"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason="evolution_exit:force_close:okx_algo_triggered",
            okx_algo_triggered=False,
            pnl=-5.0,
            pos_side="long",
            weight_reduce_factor=0.5,
        )
        assert outcome == "REDUCE_WEIGHT_CORRECT"

    def test_outcome_normal_weight_factor_1(self):
        """测试 9: weight_reduce_factor=1.0 → 正常 outcome（不触发 REDUCE_WEIGHT）"""
        from dreambuddy_evolution.engines.trade_settlement_bridge import (
            TradeSettlementBridge,
        )
        outcome = TradeSettlementBridge._extract_outcome_from_reason(
            reason="",  # 空 reason → 退化为 pnl 推断
            okx_algo_triggered=False,
            pnl=10.0,
            pos_side="long",
            weight_reduce_factor=1.0,
        )
        assert outcome not in ("REDUCE_WEIGHT_PREMATURE", "REDUCE_WEIGHT_CORRECT")
        # 应退化为正常 TP
        assert outcome == "TP"


# ============================================================================
# Group 3: ReflectionEngine — REDUCE_WEIGHT 奖励路径
# ============================================================================

class TestReflectionReduceWeightReward:
    """ReflectionEngine.apply_reward 对 REDUCE_WEIGHT 的处理"""

    def test_reflection_reduce_weight_cold_start_neutral(self):
        """测试 10: 冷启动期（样本 < 20）→ ess_delta=0（中性，只收集不调整）"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        # REDUCE_WEIGHT_PREMATURE 冷启动：ess_delta 应为 0
        result = engine.apply_reward(
            cs=0.8,
            outcome="REDUCE_WEIGHT_PREMATURE",
            cluster_id="entry_track_cluster",
            ess_id="entry_track_1",
            gmax=1.0,
        )
        assert result.get("ess_delta") == 0.0
        assert result.get("gmax_mult") == 1.0

    def test_reflection_reduce_weight_warm_start_correct(self):
        """测试 11: 样本 ≥ 20 后 → REDUCE_WEIGHT_CORRECT → ess_delta +0.01"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        # 预设样本计数 ≥ 20（warm start）
        engine._reduce_weight_counter = {"entry_track_cluster|entry_track_1": 25}
        result = engine.apply_reward(
            cs=0.8,
            outcome="REDUCE_WEIGHT_CORRECT",
            cluster_id="entry_track_cluster",
            ess_id="entry_track_1",
            gmax=1.0,
        )
        assert result.get("ess_delta") == pytest.approx(0.01)


# ============================================================================
# Group 4: PatternDetector 形态因子接入 BCRM2.0 技术评估 (Phase 4.1)
# ============================================================================

class TestPatternFactorIntegration:
    """头肩顶 pattern_factor 接入入场权重治理测试

    pattern_factor < 0（头肩顶看跌）+ evo_dir=LONG → 额外降低 weight_factor
    pattern_factor >= 0 → 不干预
    默认 0.0 → 等价当前行为（向后兼容）
    """

    @pytest.fixture
    def base_params_same_dir(self):
        """基础参数：evolution LONG vs BCRM2.0 UP（同向，weight=1.0）"""
        _now = time.time()
        return {
            "bcrm_dir": "UP",
            "bcrm_conf": 0.91,
            "bcrm_ts": _now,
            "evo_dir": "LONG",
            "bdsm_constraint": "",
            "now": _now,
        }

    def test_pattern_bearish_long_reduces_weight(self, base_params_same_dir):
        """pattern_factor=-0.8(头肩顶看跌) + evo_dir=LONG → weight < 1.0"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params_same_dir)
        result = compute_bcrm_entry_weight_factor(pattern_factor=-0.8, **params)
        assert result.veto is False
        assert result.weight_factor < 1.0  # 被降权

    def test_pattern_neutral_no_change(self, base_params_same_dir):
        """pattern_factor=0.0 → 等价基线（weight=1.0）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params_same_dir)
        result = compute_bcrm_entry_weight_factor(pattern_factor=0.0, **params)
        assert result.weight_factor == pytest.approx(1.0)

    def test_pattern_bullish_no_penalty(self, base_params_same_dir):
        """pattern_factor=+0.5(头肩底看涨) + evo_dir=LONG → 不降权"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params_same_dir)
        result = compute_bcrm_entry_weight_factor(pattern_factor=0.5, **params)
        assert result.weight_factor == pytest.approx(1.0)

    def test_pattern_factor_default_backward_compat(self, base_params_same_dir):
        """不传 pattern_factor → 等价当前行为（向后兼容）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        result = compute_bcrm_entry_weight_factor(**base_params_same_dir)
        assert result.weight_factor == pytest.approx(1.0)

    def test_pattern_crash_fail_open(self, base_params_same_dir):
        """pattern_factor=None(异常) → weight_factor=1.0（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params_same_dir)
        result = compute_bcrm_entry_weight_factor(pattern_factor=None, **params)
        assert result.weight_factor == pytest.approx(1.0)

    def test_pattern_bearish_short_no_penalty(self, base_params_same_dir):
        """pattern_factor=-0.8 + evo_dir=SHORT → 不额外降权（只惩罚 LONG）"""
        from dreambuddy_evolution.engines.entry_signal_governor import (
            compute_bcrm_entry_weight_factor,
        )
        params = dict(base_params_same_dir)
        params["evo_dir"] = "SHORT"
        params["bcrm_dir"] = "DOWN"  # 同向
        result = compute_bcrm_entry_weight_factor(pattern_factor=-0.8, **params)
        # SHORT + 头肩顶看跌 = 同向，不额外降权
        assert result.weight_factor == pytest.approx(1.0)


# ============================================================================
# Group 3 (续): ReflectionEngine 奖励路径 — 补充测试
# ============================================================================

class TestReflectionReduceWeightExtra:
    """REDUCE_WEIGHT 额外场景"""

    def test_reflection_reduce_weight_warm_start_premature(self):
        """额外: 样本 ≥ 20 后 → REDUCE_WEIGHT_PREMATURE → ess_delta -0.01"""
        from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine
        engine = ReflectionEngine()
        engine._reduce_weight_counter = {"entry_track_cluster|entry_track_1": 25}
        result = engine.apply_reward(
            cs=-0.3,
            outcome="REDUCE_WEIGHT_PREMATURE",
            cluster_id="entry_track_cluster",
            ess_id="entry_track_1",
            gmax=1.0,
        )
        assert result.get("ess_delta") == pytest.approx(-0.01)
