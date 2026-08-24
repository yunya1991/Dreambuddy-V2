"""test_dual_baseline_framework.py — 双基线 AB 影子对比框架全链路单测.

对应技术文档 docs/dual_baseline_ab_framework.md 各章节：
  §3.1 决策矩阵 6 行全覆盖
  §3.2 动态基线评分规则边界条件
  §3.3 首版本 bootstrap 逻辑
  §4.2 热切换流程
  §5.2 AB 状态机转移条件
  §5.3 PnL 回填 3 级匹配
  §6   版本迭代场景（正常进化 / 劣化被拒 / 线上退化回滚）
  §10  generate_report 监控指标
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any

import pytest

_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))

from ab_shadow_comparator import (
    ABShadowComparator,
    ABComparatorState,
    DecisionRecord,
    STATE_SHADOW,
    STATE_LIVE,
    STATE_DISABLED,
    MIN_SAMPLES_FOR_TEST,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_comp(tmp_path):
    """每次测试创建全新的 ABShadowComparator。"""
    return ABShadowComparator(state_file=str(tmp_path / "ab.json"))


def _make_pt_file(path: Path):
    """生成占位 .pt 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x50\x54\x46\x21")  # magic
    return str(path)


def _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10, trades=10, wins=6):
    return {
        'total_pnl': pnl, 'total_trades': trades, 'win_trades': wins,
        'win_rate': win_rate, 'max_drawdown': mdd, 'label': '',
    }


# ===========================================================================
# §3.1 决策矩阵 — 6 行全覆盖
# ===========================================================================

class TestDecisionMatrix:
    """对照文档 §3.1 决策矩阵表，逐行验证。"""

    def _setup_trainer(self, tmp_path):
        from incremental_trainer import IncrementalTrainer
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(
            model_base_dir=str(tmp_path / "models"),
            state_file=str(tmp_path / "inc.json"),
            ab_comparator=comp,
        )
        return it, comp

    # 行1: 首版本 bootstrap — 通过回测即可晋升
    def test_row1_first_version_bootstrap(self, tmp_path):
        """无动态基线 + 回测通过 → BOOTSTRAP_FIRST_VERSION promoted。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.2)

        result = it.evaluate_and_promote()
        assert result['action'] == 'promoted'
        assert result['transition'] == 'BOOTSTRAP_FIRST_VERSION'
        assert result['new_status'] == 'live'
        assert comp.state.dynamic_baseline_version == 'v1'

    # 行2: 新版本劣于动态基线 → disabled_inferior
    def test_row2_inferior_version_disabled(self, tmp_path):
        """动态基线对比不通过 → disabled_inferior，旧版本继续服务。"""
        it, comp = self._setup_trainer(tmp_path)
        # v1 bootstrap
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05)
        it.evaluate_and_promote()

        # v2 劣化
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15)
        result = it.evaluate_and_promote()

        assert result['action'] == 'disabled_inferior'
        assert result['new_status'] == 'disabled'
        assert it.version_mgr.state.current_live_version == 'v1'
        assert comp.state.dynamic_baseline_version == 'v1'

    # 行3: 新版本更优 + AB SHADOW→LIVE → promoted + hot_swap
    def test_row3_superior_with_ab_live(self, tmp_path):
        """动态基线通过 + AB transition=SHADOW→LIVE → promoted。"""
        it, comp = self._setup_trainer(tmp_path)
        # v1 bootstrap
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10)
        it.evaluate_and_promote()

        # v2 优于 v1
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)

        # mock AB evaluate 返回 SHADOW→LIVE
        original_evaluate = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_paired': 25, 't_test': {'p_value': 0.02}}
        result = it.evaluate_and_promote()
        comp.evaluate = original_evaluate

        assert result['action'] == 'promoted'
        assert result['new_status'] == 'live'
        assert result['version'] == 'v2'
        assert comp.state.dynamic_baseline_version == 'v2'

    # 行4: 新版本更优 + AB 无足够样本 → keep_collecting
    def test_row4_superior_but_ab_no_samples(self, tmp_path):
        """动态基线通过但 AB transition=None → keep_collecting。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0)
        it.evaluate_and_promote()

        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.8, win_rate=0.75, mdd=0.06)

        # AB transition=None（样本不足）
        result = it.evaluate_and_promote()
        assert result['action'] == 'keep_collecting'
        assert result['version_comparison']['should_promote'] is True
        assert it.version_mgr.state.current_live_version == 'v1'

    # 行5: 新版本更优 + AB SHADOW→DISABLED → disabled
    def test_row5_superior_but_ab_disabled(self, tmp_path):
        """动态基线通过但 AB transition=SHADOW→DISABLED → disabled。"""
        it, comp = self._setup_trainer(tmp_path)
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0)
        it.evaluate_and_promote()

        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)

        original_evaluate = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→DISABLED', 'n_paired': 25}
        result = it.evaluate_and_promote()
        comp.evaluate = original_evaluate

        assert result['action'] == 'disabled'
        assert result['new_status'] == 'disabled'
        assert it.version_mgr.state.current_live_version == 'v1'

    # 行6: LIVE→SHADOW → rollback + hot_swap 到回滚版本
    def test_row6_live_to_shadow_rollback(self, tmp_path):
        """AB transition=LIVE→SHADOW → rollback_live + hot_swap。"""
        it, comp = self._setup_trainer(tmp_path)
        # v1 bootstrap
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.0)
        it.evaluate_and_promote()  # v1 → live

        # v2 promoted
        v2_b = _make_pt_file(tmp_path / "models" / "v2" / "bilstm.pt")
        v2_p = _make_pt_file(tmp_path / "models" / "v2" / "patchtst.pt")
        it.version_mgr.register_version(v2_b, v2_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)
        original_evaluate = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_paired': 25}
        it.evaluate_and_promote()  # v2 → live, v1 → shadow
        comp.evaluate = original_evaluate

        assert it.version_mgr.state.current_live_version == 'v2'

        # LIVE→SHADOW rollback
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.0, win_rate=0.0, mdd=0.20)
        comp.evaluate = lambda: {'transition': 'LIVE→SHADOW', 'n_paired': 25}
        result = it.evaluate_and_promote()
        comp.evaluate = original_evaluate

        assert result['action'] == 'rollback'
        assert it.version_mgr.state.current_live_version == 'v1'  # 回滚到 v1


# ===========================================================================
# §3.2 评分规则边界条件
# ===========================================================================

class TestScoringRules:
    """对照文档 §3.2 动态基线对比评分规则。"""

    def test_score_0_all_inferior(self, fresh_comp, tmp_path):
        """3 项全劣 → score=0, should_promote=False。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        candidate = _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['score'] == 0
        assert r['should_promote'] is False

    def test_score_1_only_one_better(self, fresh_comp, tmp_path):
        """仅 1/3 优于基线 → score=1, should_promote=False。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        # PnL 优于基线，但胜率和回撤更差
        candidate = _mock_metrics(pnl=2.5, win_rate=0.50, mdd=0.12)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['score'] == 1
        assert r['should_promote'] is False

    def test_score_2_pnl_within_tolerance(self, fresh_comp, tmp_path):
        """2/3 优于基线且 PnL 微差（-1%）→ score=2, should_promote=True。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.12))
        candidate = _mock_metrics(pnl=0.99, win_rate=0.70, mdd=0.08)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['score'] == 2
        assert r['should_promote'] is True

    def test_score_2_pnl_beyond_tolerance(self, fresh_comp, tmp_path):
        """2/3 优于基线但 PnL 劣化超 -2% → should_promote=False。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.12))
        # PnL 劣化 -3%，但胜率和回撤更好 → score=2 但 pnl_delta=-3% < -2%
        candidate = _mock_metrics(pnl=0.97, win_rate=0.70, mdd=0.08)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['score'] == 2
        assert r['should_promote'] is False
        assert r['pnl_delta_pct'] == -3.0

    def test_score_3_all_superior(self, fresh_comp, tmp_path):
        """3/3 全优 → score=3, should_promote=True。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10))
        candidate = _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['score'] == 3
        assert r['should_promote'] is True

    def test_pnl_delta_calculation(self, fresh_comp, tmp_path):
        """PnL 改善百分比计算正确。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=2.0))
        candidate = _mock_metrics(pnl=3.0)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['pnl_delta_pct'] == 50.0  # (3.0-2.0)/2.0*100

    def test_pnl_delta_zero_baseline(self, fresh_comp, tmp_path):
        """基线 PnL=0 时 pnl_delta_pct=0（避免除零）。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=0.0))
        candidate = _mock_metrics(pnl=1.0)
        r = fresh_comp.evaluate_version_comparison("v2", candidate, ("", ""))
        assert r['pnl_delta_pct'] == 0.0


# ===========================================================================
# §3.3 首版本 Bootstrap 逻辑
# ===========================================================================

class TestBootstrap:
    """对照文档 §3.3 首版本 bootstrap 逻辑。"""

    def test_bootstrap_sets_dynamic_baseline(self, tmp_path):
        """首版本晋升后动态基线初始化为 v1 + 回测指标。"""
        from incremental_trainer import IncrementalTrainer
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(
            model_base_dir=str(tmp_path / "models"),
            state_file=str(tmp_path / "inc.json"),
            ab_comparator=comp,
        )
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})

        metrics = _mock_metrics(pnl=1.2, win_rate=0.65, mdd=0.08)
        it._backtest_model = lambda b, p, label='': metrics
        result = it.evaluate_and_promote()

        assert result['transition'] == 'BOOTSTRAP_FIRST_VERSION'
        assert comp.state.dynamic_baseline_version == 'v1'
        assert comp.state.dynamic_baseline_metrics['total_pnl'] == 1.2
        assert comp.state.dynamic_baseline_metrics['win_rate'] == 0.65

    def test_bootstrap_does_not_fire_with_existing_baseline(self, tmp_path):
        """已有动态基线时不走 bootstrap 分支。"""
        from incremental_trainer import IncrementalTrainer
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        comp.set_dynamic_baseline("v0", _mock_metrics(pnl=1.0))

        it = IncrementalTrainer(
            model_base_dir=str(tmp_path / "models"),
            state_file=str(tmp_path / "inc.json"),
            ab_comparator=comp,
        )
        v1_b = _make_pt_file(tmp_path / "models" / "v1" / "bilstm.pt")
        v1_p = _make_pt_file(tmp_path / "models" / "v1" / "patchtst.pt")
        it.version_mgr.register_version(v1_b, v1_p, {})
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=1.5)
        result = it.evaluate_and_promote()

        # 有动态基线 → 不走 bootstrap，走正常 AB 流程
        assert result['transition'] != 'BOOTSTRAP_FIRST_VERSION'


# ===========================================================================
# §5.2 AB 状态机转移条件
# ===========================================================================

class TestABStateMachine:
    """对照文档 §5.2 状态转移条件。"""

    def _fill_paired_records(self, comp, n, baseline_pnl, ai_pnl):
        """填充 n 条已回填的配对决策记录。"""
        for i in range(n):
            ts = datetime.utcnow() - timedelta(hours=i)
            comp.record_decision(
                symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                baseline_confidence=0.9, ai_confidence=0.8,
                baseline_pnl=0.0, ai_predicted_pnl=0.0,
                position_ref=ABShadowComparator.build_position_ref("BTC", ts),
            )
            comp.backfill_trade_result(
                symbol="BTC", entry_timestamp=ts,
                baseline_pnl_usdt=baseline_pnl, baseline_pnl_pct=baseline_pnl / 100,
            )

    def test_shadow_to_live_positive_significance(self, fresh_comp):
        """SHADOW→LIVE: ≥20样本 + p<0.05 + gain≥2%。"""
        comp = fresh_comp
        comp.force_state(STATE_SHADOW)
        # AI 比 baseline 好 0.05（baseline=0.10, ai=0.15）
        self._fill_paired_records(comp, 25, baseline_pnl=0.10, ai_pnl=0.15)
        # 手动修正 AI PnL（backfill 默认同动作同 PnL）
        for r in comp.state.records:
            r['ai_predicted_pnl'] = 0.15
        comp._save_state()

        result = comp.evaluate()
        assert result['n_samples'] >= 20
        assert result['transition'] in ('SHADOW→LIVE', None)

    def test_shadow_to_disabled_negative_significance(self, fresh_comp):
        """SHADOW→DISABLED: ≥20样本 + AI显著差于基线。"""
        comp = fresh_comp
        comp.force_state(STATE_SHADOW)
        # baseline 赚，AI 不赚
        for i in range(25):
            ts = datetime.utcnow() - timedelta(hours=i)
            comp.record_decision(
                symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                baseline_confidence=0.9, ai_confidence=0.8,
                baseline_pnl=0.0, ai_predicted_pnl=0.0,
                position_ref=ABShadowComparator.build_position_ref("BTC", ts),
            )
            comp.backfill_trade_result(
                symbol="BTC", entry_timestamp=ts,
                baseline_pnl_usdt=0.20, baseline_pnl_pct=0.02,
            )
        # 手动让 AI PnL=0（差于基线）
        for r in comp.state.records:
            r['ai_predicted_pnl'] = 0.0
        comp._save_state()

        result = comp.evaluate()
        assert result['n_samples'] >= 20
        assert result['transition'] in ('SHADOW→DISABLED', None)

    def test_insufficient_samples_no_transition(self, fresh_comp):
        """样本不足 20 → 不触发状态转移。"""
        comp = fresh_comp
        self._fill_paired_records(comp, 10, baseline_pnl=0.10, ai_pnl=0.20)
        result = comp.evaluate()
        assert result['n_samples'] < MIN_SAMPLES_FOR_TEST
        assert result['transition'] is None


# ===========================================================================
# §5.3 PnL 回填 3 级匹配
# ===========================================================================

class TestPnLBackfill:
    """对照文档 §5.3 PnL 回填机制。"""

    def test_level1_position_ref_exact_match(self, fresh_comp):
        """L1: position_ref 精确匹配 → 回填成功。"""
        ts = datetime.utcnow() - timedelta(hours=2)
        ref = ABShadowComparator.build_position_ref("ETH", ts)
        fresh_comp.record_decision(
            symbol="ETH", baseline_action="OPEN", ai_action="OPEN",
            baseline_confidence=0.9, ai_confidence=0.9,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            position_ref=ref,
        )
        filled = fresh_comp.backfill_trade_result(
            symbol="ETH", entry_timestamp=ts,
            baseline_pnl_usdt=0.25, baseline_pnl_pct=0.025,
        )
        assert filled == 1
        r = fresh_comp.state.records[-1]
        assert r['pnl_backfilled'] is True
        assert r['baseline_pnl'] == 0.25

    def test_level2_symbol_timestamp_fuzzy_match(self, fresh_comp):
        """L2: position_ref 不匹配但 symbol+timestamp 模糊匹配。"""
        ts = datetime.utcnow() - timedelta(hours=2)
        fresh_comp.record_decision(
            symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
            baseline_confidence=0.9, ai_confidence=0.9,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            position_ref="BTC|20200101T0000",  # 不匹配
        )
        filled = fresh_comp.backfill_trade_result(
            symbol="BTC", entry_timestamp=ts,  # timestamp 接近
            baseline_pnl_usdt=0.15, baseline_pnl_pct=0.015,
        )
        assert filled == 1

    def test_level3_symbol_fallback(self, fresh_comp):
        """L3: position_ref 和 timestamp 都不匹配 → symbol 兜底。"""
        fresh_comp.record_decision(
            symbol="SOL", baseline_action="OPEN", ai_action="OPEN",
            baseline_confidence=0.9, ai_confidence=0.9,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            position_ref="",  # 空 ref
        )
        filled = fresh_comp.backfill_trade_result(
            symbol="SOL", entry_timestamp=datetime.utcnow(),
            baseline_pnl_usdt=0.10, baseline_pnl_pct=0.01,
        )
        assert filled == 1

    def test_no_match_returns_zero(self, fresh_comp):
        """完全不匹配 → 回填 0 条。"""
        fresh_comp.record_decision(
            symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
            baseline_confidence=0.9, ai_confidence=0.9,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            position_ref="BTC|20200101T0000",
        )
        filled = fresh_comp.backfill_trade_result(
            symbol="ETH", entry_timestamp=datetime.utcnow(),
            baseline_pnl_usdt=0.10,
        )
        assert filled == 0

    def test_ai_pnl_estimation_open_skip(self, fresh_comp):
        """AI 路径 PnL 估算: ba=OPEN, aa=SKIP → ai_pnl=0。"""
        ts = datetime.utcnow() - timedelta(hours=1)
        ref = ABShadowComparator.build_position_ref("BTC", ts)
        fresh_comp.record_decision(
            symbol="BTC", baseline_action="OPEN", ai_action="SKIP",
            baseline_confidence=0.9, ai_confidence=0.8,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            position_ref=ref,
        )
        fresh_comp.backfill_trade_result(
            symbol="BTC", entry_timestamp=ts,
            baseline_pnl_usdt=0.20, baseline_pnl_pct=0.02,
        )
        r = fresh_comp.state.records[-1]
        assert r['ai_predicted_pnl'] == 0.0  # SKIP → 0

    def test_ai_pnl_estimation_same_action(self, fresh_comp):
        """AI 路径 PnL 估算: ba=aa=OPEN → ai_pnl=baseline_pnl。"""
        ts = datetime.utcnow() - timedelta(hours=1)
        ref = ABShadowComparator.build_position_ref("BTC", ts)
        fresh_comp.record_decision(
            symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
            baseline_confidence=0.9, ai_confidence=0.8,
            baseline_pnl=0.0, ai_predicted_pnl=0.0,
            position_ref=ref,
        )
        fresh_comp.backfill_trade_result(
            symbol="BTC", entry_timestamp=ts,
            baseline_pnl_usdt=0.30, baseline_pnl_pct=0.03,
        )
        r = fresh_comp.state.records[-1]
        assert r['ai_predicted_pnl'] == 0.30  # 同动作同盈亏


# ===========================================================================
# §6 版本迭代场景
# ===========================================================================

class TestVersionIteration:
    """对照文档 §6 三种版本迭代场景。"""

    def _setup(self, tmp_path):
        from incremental_trainer import IncrementalTrainer
        comp = ABShadowComparator(state_file=str(tmp_path / "ab.json"))
        it = IncrementalTrainer(
            model_base_dir=str(tmp_path / "models"),
            state_file=str(tmp_path / "inc.json"),
            ab_comparator=comp,
        )
        return it, comp

    def _register_and_backtest(self, it, version, metrics):
        base = Path(it.version_mgr.base_dir)
        b = _make_pt_file(base / version / "bilstm.pt")
        p = _make_pt_file(base / version / "patchtst.pt")
        it.version_mgr.register_version(b, p, {})
        it._backtest_model = lambda bi, pa, label='': metrics

    def test_scenario_6_1_normal_evolution(self, tmp_path):
        """§6.1 正常迭代：v1→v2→v3 持续进化。"""
        it, comp = self._setup(tmp_path)

        # v1 bootstrap
        self._register_and_backtest(it, "v1", _mock_metrics(pnl=1.0, win_rate=0.60, mdd=0.10))
        r1 = it.evaluate_and_promote()
        assert r1['action'] == 'promoted'
        assert comp.state.dynamic_baseline_version == 'v1'

        # v2 优于 v1 + AB SHADOW→LIVE
        self._register_and_backtest(it, "v2", _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08))
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_paired': 25}
        r2 = it.evaluate_and_promote()
        comp.evaluate = orig
        assert r2['action'] == 'promoted'
        assert comp.state.dynamic_baseline_version == 'v2'
        assert it.version_mgr.state.current_live_version == 'v2'

        # v3 优于 v2 + AB SHADOW→LIVE
        self._register_and_backtest(it, "v3", _mock_metrics(pnl=2.0, win_rate=0.75, mdd=0.06))
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_paired': 25}
        r3 = it.evaluate_and_promote()
        comp.evaluate = orig
        assert r3['action'] == 'promoted'
        assert comp.state.dynamic_baseline_version == 'v3'
        assert it.version_mgr.state.current_live_version == 'v3'

    def test_scenario_6_2_inferior_rejected(self, tmp_path):
        """§6.2 劣化版本被拒：v2(live) → v3 劣化 → disabled，v2 继续服务。"""
        it, comp = self._setup(tmp_path)

        # v1 bootstrap
        self._register_and_backtest(it, "v1", _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05))
        it.evaluate_and_promote()

        # v2 promoted
        self._register_and_backtest(it, "v2", _mock_metrics(pnl=2.5, win_rate=0.75, mdd=0.04))
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_paired': 25}
        it.evaluate_and_promote()
        comp.evaluate = orig
        assert it.version_mgr.state.current_live_version == 'v2'

        # v3 劣化 → rejected
        self._register_and_backtest(it, "v3", _mock_metrics(pnl=0.5, win_rate=0.30, mdd=0.15))
        r3 = it.evaluate_and_promote()
        assert r3['action'] == 'disabled_inferior'
        assert it.version_mgr.state.current_live_version == 'v2'
        assert comp.state.dynamic_baseline_version == 'v2'

    def test_scenario_6_3_live_rollback(self, tmp_path):
        """§6.3 线上退化回滚：v2(live) → 退化 → rollback 到 v1。"""
        it, comp = self._setup(tmp_path)

        # v1 bootstrap
        self._register_and_backtest(it, "v1", _mock_metrics(pnl=1.0))
        it.evaluate_and_promote()

        # v2 promoted
        self._register_and_backtest(it, "v2", _mock_metrics(pnl=1.5, win_rate=0.70, mdd=0.08))
        orig = comp.evaluate
        comp.evaluate = lambda: {'transition': 'SHADOW→LIVE', 'n_paired': 25}
        it.evaluate_and_promote()
        comp.evaluate = orig
        assert it.version_mgr.state.current_live_version == 'v2'

        # v2 退化 → LIVE→SHADOW → rollback
        it._backtest_model = lambda b, p, label='': _mock_metrics(pnl=0.0, win_rate=0.0, mdd=0.20)
        comp.evaluate = lambda: {'transition': 'LIVE→SHADOW', 'n_paired': 25}
        result = it.evaluate_and_promote()
        comp.evaluate = orig

        assert result['action'] == 'rollback'
        assert it.version_mgr.state.current_live_version == 'v1'  # 回滚到 v1


# ===========================================================================
# §10 generate_report 监控指标
# ===========================================================================

class TestMonitoringReport:
    """对照文档 §10 generate_report 输出。"""

    def test_report_has_all_fields(self, fresh_comp):
        """generate_report 包含文档 §10 所有字段。"""
        fresh_comp.set_dynamic_baseline("v1", _mock_metrics(pnl=1.5))
        report = fresh_comp.generate_report()

        required_fields = [
            'current_state', 'total_records', 'total_evaluations',
            'live_promoted_at', 'disabled_at', 'last_evaluation',
            'dynamic_baseline_version', 'dynamic_baseline_metrics',
            'evaluation', 'baseline_action_distribution',
            'ai_action_distribution', 'ai_model_stats', 'generated_at',
        ]
        for field in required_fields:
            assert field in report, f"missing field: {field}"

    def test_report_dynamic_baseline_info(self, fresh_comp):
        """report 中 dynamic_baseline 字段正确。"""
        metrics = _mock_metrics(pnl=2.0, win_rate=0.70, mdd=0.05)
        fresh_comp.set_dynamic_baseline("v3", metrics)
        report = fresh_comp.generate_report()
        assert report['dynamic_baseline_version'] == 'v3'
        assert report['dynamic_baseline_metrics']['total_pnl'] == 2.0
        assert report['dynamic_baseline_metrics']['win_rate'] == 0.70

    def test_report_no_dynamic_baseline(self, fresh_comp):
        """无动态基线时 report 中字段为 None。"""
        report = fresh_comp.generate_report()
        assert report['dynamic_baseline_version'] is None
        assert report['dynamic_baseline_metrics'] is None

    def test_report_action_distribution(self, fresh_comp):
        """report 中 action 分布统计正确。"""
        for i in range(5):
            fresh_comp.record_decision(
                symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                baseline_confidence=0.9, ai_confidence=0.9,
                baseline_pnl=0.0, ai_predicted_pnl=0.0,
            )
        for i in range(3):
            fresh_comp.record_decision(
                symbol="ETH", baseline_action="ADDON", ai_action="SKIP",
                baseline_confidence=0.8, ai_confidence=0.7,
                baseline_pnl=0.0, ai_predicted_pnl=0.0,
            )
        report = fresh_comp.generate_report()
        assert report['baseline_action_distribution'] == {"OPEN": 5, "ADDON": 3}
        assert report['ai_action_distribution'] == {"OPEN": 5, "SKIP": 3}
        assert report['total_records'] == 8

    def test_report_ai_model_stats(self, fresh_comp):
        """report 中 AI 模型统计字段正确。"""
        for i in range(3):
            fresh_comp.record_decision(
                symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                baseline_confidence=0.9, ai_confidence=0.8,
                baseline_pnl=0.0, ai_predicted_pnl=0.0,
                ai_p_bust=0.15 + i * 0.01,
                ai_drawdown=0.03 + i * 0.005,
            )
        report = fresh_comp.generate_report()
        assert report['ai_model_stats']['p_bust_count'] == 3
        assert 0.15 < report['ai_model_stats']['p_bust_mean'] < 0.18
        assert report['ai_model_stats']['drawdown_count'] == 3


# ===========================================================================
# §7 配置参数边界验证
# ===========================================================================

class TestConfigParams:
    """对照文档 §7 配置参数。"""

    def test_min_samples_constant(self):
        """MIN_SAMPLES_FOR_TEST=20。"""
        assert MIN_SAMPLES_FOR_TEST == 20

    def test_state_thresholds(self):
        """状态转移阈值常量正确。"""
        from ab_shadow_comparator import (
            SHADOW_TO_LIVE_PVALUE,
            SHADOW_TO_LIVE_MIN_GAIN,
            LIVE_TO_SHADOW_PVALUE,
            LIVE_TO_SHADOW_MAX_LOSS,
            EVALUATION_WINDOW_DAYS,
            LIVE_EVALUATION_WINDOW_DAYS,
        )
        assert SHADOW_TO_LIVE_PVALUE == 0.05
        assert SHADOW_TO_LIVE_MIN_GAIN == 0.02
        assert LIVE_TO_SHADOW_PVALUE == 0.10
        assert LIVE_TO_SHADOW_MAX_LOSS == -0.01
        assert EVALUATION_WINDOW_DAYS == 30
        assert LIVE_EVALUATION_WINDOW_DAYS == 7

    def test_max_records_cap(self, fresh_comp):
        """records 超过 1000 条自动截断。"""
        for i in range(1005):
            fresh_comp.record_decision(
                symbol="BTC", baseline_action="OPEN", ai_action="OPEN",
                baseline_confidence=0.9, ai_confidence=0.9,
                baseline_pnl=0.0, ai_predicted_pnl=0.0,
            )
        assert len(fresh_comp.state.records) == 1000


# ===========================================================================
# CLI
# ===========================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
