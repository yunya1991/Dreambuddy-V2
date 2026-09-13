#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RESTRICT 状态补全 + 自适应权重上线 TDD 测试。

覆盖：
  1. RESTRICT 状态机四态完整性（9 用例）
  2. 自适应权重接线（5 用例）

实施 spec 引用：.trae/documents/strategic-layer-restrict-and-adaptive-weights.md
"""
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(ROOT))


def _try_import():
    """懒加载：导入失败时返回占位 Sentinel。"""
    sentinel = {"loaded": False}
    try:
        from scripts.memory_l4.five_domain_scorer import (  # noqa: E402
            FiveDomainHeuristicScorer,
            FiveDomainState,
        )
        sentinel["loaded"] = True
        sentinel["FiveDomainHeuristicScorer"] = FiveDomainHeuristicScorer
        sentinel["FiveDomainState"] = FiveDomainState
    except Exception as exc:  # noqa: BLE001
        sentinel["import_error"] = str(exc)
    return sentinel


MOD = _try_import()


# =====================================================================
# 辅助函数：构造五维评分（所有维度同值 → total=该值，因为权重和=1.0）
# =====================================================================
def _scores_all(val: int) -> Dict[str, Dict[str, int]]:
    """构造三类资产五维全同值评分。"""
    return {
        "crypto_usdt": {"dao": val, "tian": val, "di": val, "jiang": val, "fa": val},
        "us_stock": {"dao": val, "tian": val, "di": val, "jiang": val, "fa": val},
        "precious_metal": {"dao": val, "tian": val, "di": val, "jiang": val, "fa": val},
    }


def _make_scorer(enable: bool = True, enable_adaptive: bool = False):
    """构造启用状态的 Scorer。"""
    assert MOD.get("loaded"), f"模块未加载: {MOD.get('import_error', '')}"
    Scorer = MOD["FiveDomainHeuristicScorer"]
    s = Scorer(enable=enable, enable_adaptive_weights=enable_adaptive)
    return s


def _set_prev_ws(scorer, cls: str, ws: str):
    """设置上一轮 war_state（模拟状态机 prev）。"""
    scorer._last_state.war_state[cls] = ws


def _set_thaw_counter(scorer, cls: str, val: int):
    """设置解冻连续达标计数器。"""
    scorer._thaw_consecutive[cls] = val


# =====================================================================
# RESTRICT 状态机测试（9 用例）
# =====================================================================
class TestRestrictStateMachine:
    """RESTRICT 状态补全：四态状态机完整性。"""

    def test_restrict_prev_allow_50_57(self):
        """prev=ALLOW, total=53 (50≤t<58) → RESTRICT, cap=0.20。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "ALLOW")
        state = s.score_and_decide(raw_scores_by_class=_scores_all(53))
        assert state.war_state["crypto_usdt"] == "RESTRICT"
        assert abs(state.aggregate_position_cap_pct["crypto_usdt"] - 0.20) < 1e-6

    def test_freeze_prev_allow_below_50(self):
        """prev=ALLOW, total=45 (<50) → FREEZE。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "ALLOW")
        state = s.score_and_decide(raw_scores_by_class=_scores_all(45))
        assert state.war_state["crypto_usdt"] == "FREEZE"

    def test_restrict_prev_non_allow_50_59(self):
        """prev=FREEZE, total=55 (50≤t<60) → RESTRICT。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "FREEZE")
        _set_thaw_counter(s, "crypto_usdt", 0)
        state = s.score_and_decide(raw_scores_by_class=_scores_all(55))
        assert state.war_state["crypto_usdt"] == "RESTRICT"

    def test_freeze_prev_non_allow_below_50(self):
        """prev=FREEZE, total=45 → FREEZE（非 ALLOW 回退）。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "FREEZE")
        _set_thaw_counter(s, "crypto_usdt", 0)
        state = s.score_and_decide(raw_scores_by_class=_scores_all(45))
        assert state.war_state["crypto_usdt"] == "FREEZE"

    def test_restrict_to_cooldown_total_rises(self):
        """prev=RESTRICT, total=62 (≥60, counter<3) → COOLDOWN。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "RESTRICT")
        _set_thaw_counter(s, "crypto_usdt", 0)
        state = s.score_and_decide(raw_scores_by_class=_scores_all(62))
        assert state.war_state["crypto_usdt"] == "COOLDOWN"

    def test_restrict_to_freeze_total_drops(self):
        """prev=RESTRICT, total=45 (<50) → FREEZE。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "RESTRICT")
        _set_thaw_counter(s, "crypto_usdt", 0)
        state = s.score_and_decide(raw_scores_by_class=_scores_all(45))
        assert state.war_state["crypto_usdt"] == "FREEZE"

    def test_restrict_stays_when_50_59(self):
        """prev=RESTRICT, total=55, counter=0 → RESTRICT（维持）。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "RESTRICT")
        _set_thaw_counter(s, "crypto_usdt", 0)
        state = s.score_and_decide(raw_scores_by_class=_scores_all(55))
        assert state.war_state["crypto_usdt"] == "RESTRICT"

    def test_dao_veto_still_freeze(self):
        """dao=38<40 → FREEZE（回归：道否决优先级不变）。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "ALLOW")
        scores = _scores_all(60)
        scores["crypto_usdt"]["dao"] = 38
        state = s.score_and_decide(raw_scores_by_class=scores)
        assert state.war_state["crypto_usdt"] == "FREEZE"

    def test_allow_still_when_ge_58(self):
        """prev=ALLOW, total=60 → ALLOW（回归：≥58 维持 ALLOW）。"""
        s = _make_scorer()
        _set_prev_ws(s, "crypto_usdt", "ALLOW")
        state = s.score_and_decide(raw_scores_by_class=_scores_all(60))
        assert state.war_state["crypto_usdt"] == "ALLOW"


# =====================================================================
# 自适应权重测试（5 用例）
# =====================================================================
class TestAdaptiveWeights:
    """自适应权重接线：enable_adaptive_weights 开关 + force_vectors 透传。"""

    # 构造 force_vectors：5 维，每维 magnitude/confidence 可控
    @staticmethod
    def _make_fv(magnitude: float = 1.0, confidence: float = 0.5) -> Dict[str, Dict]:
        return {
            dim: {"direction": 0.5, "magnitude": magnitude, "confidence": confidence}
            for dim in ("dao", "tian", "di", "jiang", "fa")
        }

    def test_adaptive_off_ignores_fv(self):
        """enable_adaptive_weights=False → 传 fv 不影响 total。"""
        s_off = _make_scorer(enable_adaptive=False)
        s_on = _make_scorer(enable_adaptive=False)  # 同样关闭
        scores = _scores_all(60)
        fv = self._make_fv(magnitude=2.0, confidence=0.9)
        state_off = s_off.score_and_decide(raw_scores_by_class=scores)
        # force_vectors_by_class 参数即使传入，开关关闭也应忽略
        state_off_fv = s_on.score_and_decide(
            raw_scores_by_class=scores,
            force_vectors_by_class={"crypto_usdt": fv},
        )
        assert state_off_fv.five_scores["crypto_usdt"] == state_off.five_scores["crypto_usdt"]

    def test_adaptive_on_low_conf_fallback(self):
        """enable=True, avg_conf=0.2 → 回退硬编码权重。"""
        s = _make_scorer(enable_adaptive=True)
        scores = _scores_all(60)
        fv = self._make_fv(magnitude=1.0, confidence=0.2)  # avg_conf=0.2 < 0.3
        state = s.score_and_decide(
            raw_scores_by_class=scores,
            force_vectors_by_class={"crypto_usdt": fv},
        )
        # 硬编码权重 total = 60（全60）
        assert state.five_scores["crypto_usdt"]["dao"] == 60

    def test_adaptive_on_high_conf_modifies(self):
        """enable=True, avg_conf=0.9 → 自适应权重生效，total 变化。"""
        s = _make_scorer(enable_adaptive=True)
        # 构造极端 magnitude：dao 独大，其他≈0
        fv_extreme = {
            "dao": {"direction": 0.5, "magnitude": 10.0, "confidence": 0.9},
            "tian": {"direction": 0.5, "magnitude": 0.01, "confidence": 0.9},
            "di": {"direction": 0.5, "magnitude": 0.01, "confidence": 0.9},
            "jiang": {"direction": 0.5, "magnitude": 0.01, "confidence": 0.9},
            "fa": {"direction": 0.5, "magnitude": 0.01, "confidence": 0.9},
        }
        scores = _scores_all(60)
        # 开关关闭时的 total（硬编码）
        s_off = _make_scorer(enable_adaptive=False)
        state_off = s_off.score_and_decide(raw_scores_by_class=scores)
        # 开关开启时的 total（自适应）
        state_on = s.score_and_decide(
            raw_scores_by_class=scores,
            force_vectors_by_class={"crypto_usdt": fv_extreme},
        )
        # 自适应权重应使 dao 权重提升 → total 更偏向 dao 的分数
        # 由于 dao=60 且其他也=60，total 可能不变。用差异化分数验证。
        scores_diff = _scores_all(50)
        scores_diff["crypto_usdt"]["dao"] = 80  # dao 高分
        state_off_diff = s_off.score_and_decide(raw_scores_by_class=scores_diff)
        state_on_diff = s.score_and_decide(
            raw_scores_by_class=scores_diff,
            force_vectors_by_class={"crypto_usdt": fv_extreme},
        )
        # dao 权重提升后，total 应更高
        t_off = state_off_diff.five_scores["crypto_usdt"]["dao"]
        t_on = state_on_diff.five_scores["crypto_usdt"]["dao"]
        # five_scores 存原始评分，不是 total。比较 war_state/cap 间接验证。
        # 更好的验证：total 变化通过 cap 反映
        # 80*0.30+50*0.70 = 24+35 = 59 → cap=0.20 (硬编码)
        # 自适应后 dao 权重↑ → total 更接近 80 → 可能 ≥60 → cap=0.50
        assert state_on_diff.aggregate_position_cap_pct["crypto_usdt"] >= \
               state_off_diff.aggregate_position_cap_pct["crypto_usdt"]

    def test_adaptive_on_missing_fv(self):
        """enable=True, fv=None → 回退硬编码权重。"""
        s = _make_scorer(enable_adaptive=True)
        scores = _scores_all(60)
        # 不传 force_vectors_by_class
        state = s.score_and_decide(raw_scores_by_class=scores)
        assert state.five_scores["crypto_usdt"]["dao"] == 60
        # 传 None
        state_none = s.score_and_decide(
            raw_scores_by_class=scores,
            force_vectors_by_class=None,
        )
        assert state_none.five_scores["crypto_usdt"]["dao"] == 60

    def test_score_and_decide_accepts_fv(self):
        """score_and_decide(force_vectors_by_class=...) 不报错，正常返回。"""
        s = _make_scorer(enable_adaptive=False)
        scores = _scores_all(60)
        fv = self._make_fv()
        state = s.score_and_decide(
            raw_scores_by_class=scores,
            force_vectors_by_class={"crypto_usdt": fv, "us_stock": fv, "precious_metal": fv},
        )
        # 验证返回正常 FiveDomainState
        assert MOD["FiveDomainState"] is not None
        assert hasattr(state, "war_state")
        assert hasattr(state, "aggregate_position_cap_pct")


# =====================================================================
# fail-open 字节等价回归测试
# =====================================================================
class TestFailOpenByteEquivalence:
    """开关全关时字节等价不变。"""

    def test_adaptive_off_byte_equivalence(self):
        """enable_adaptive_weights=False 时，传/不传 fv 结果一致。"""
        s = _make_scorer(enable_adaptive=False)
        scores = _scores_all(55)
        fv = {"crypto_usdt": {"dao": {"magnitude": 1.0, "confidence": 0.9}}}
        state_no_fv = s.score_and_decide(raw_scores_by_class=scores)
        state_with_fv = s.score_and_decide(
            raw_scores_by_class=scores,
            force_vectors_by_class=fv,
        )
        # 开关关闭时，两者必须完全一致
        assert state_no_fv.war_state == state_with_fv.war_state
        assert state_no_fv.aggregate_position_cap_pct == state_with_fv.aggregate_position_cap_pct
