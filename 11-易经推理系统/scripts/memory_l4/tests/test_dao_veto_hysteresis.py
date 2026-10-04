#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""道维度否决滞回带 TDD 测试。

问题：dao<40 一票否决绕过 war_state 滞回状态机，1 分阈值抖动导致
FREEZE/ALLOW 来回切换（dao=39→FREEZE, dao=40→正常）。

方案：为 dao_jv_fou_jue 引入双阈值滞回：
  - 冻结门槛 dao_freeze_score = 38：dao < 38 → 立即冻结
  - 解冻门槛 dao_thaw_score = 43：dao > 43 → 解冻
  - 滞回区间 [38, 43]：维持上一轮状态

验收标准：
  1. dao < 38 → dao_jv_fou_jue=True（无论上轮状态）
  2. dao > 43 → dao_jv_fou_jue=False（无论上轮状态）
  3. 38 ≤ dao ≤ 43 且上轮未冻结 → dao_jv_fou_jue=False
  4. 38 ≤ dao ≤ 43 且上轮已冻结 → dao_jv_fou_jue=True
  5. FAIL-OPEN：scorer 新建时 _dao_veto_frozen 默认为 False
"""
import sys
from pathlib import Path
from typing import Dict

import pytest

ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(ROOT))


def _try_import():
    sentinel = {"loaded": False}
    try:
        from scripts.memory_l4.five_domain_scorer import (  # noqa: E402
            FiveDomainHeuristicScorer,
        )
        sentinel["loaded"] = True
        sentinel["Scorer"] = FiveDomainHeuristicScorer
    except Exception as exc:  # noqa: BLE001
        sentinel["import_error"] = str(exc)
    return sentinel


MOD = _try_import()


def _scores_dao(dao_val: int, other: int = 80) -> Dict[str, Dict[str, int]]:
    """构造三类资产 dao=指定值，其余维度=80（确保 total 不触发 total 否决）。"""
    return {
        "crypto_usdt": {"dao": dao_val, "tian": other, "di": other, "jiang": other, "fa": other},
        "us_stock": {"dao": dao_val, "tian": other, "di": other, "jiang": other, "fa": other},
        "precious_metal": {"dao": dao_val, "tian": other, "di": other, "jiang": other, "fa": other},
    }


def _make_scorer(enable: bool = True):
    assert MOD.get("loaded"), f"模块未加载: {MOD.get('import_error', '')}"
    return MOD["Scorer"](enable=enable)


def _set_dao_frozen(scorer, cls: str, frozen: bool):
    """设置上一轮道否决冻结状态。"""
    scorer._dao_veto_frozen[cls] = frozen


# =====================================================================
# 道否决滞回带测试
# =====================================================================
class TestDaoVetoHysteresis:
    """dao_jv_fou_jue 双阈值滞回：冻结门槛38 / 解冻门槛43。"""

    def test_below_freeze_threshold_always_freeze(self):
        """dao=37 (<38) → dao_jv_fou_jue=True，无论上轮状态。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", False)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(37))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is True

    def test_above_thaw_threshold_always_thaw(self):
        """dao=44 (>43) → dao_jv_fou_jue=False，无论上轮状态。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", True)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(44))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is False

    def test_hysteresis_band_not_frozen_stays_not_frozen(self):
        """dao=40 (区间内, 上轮未冻结) → dao_jv_fou_jue=False。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", False)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(40))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is False

    def test_hysteresis_band_frozen_stays_frozen(self):
        """dao=40 (区间内, 上轮已冻结) → dao_jv_fou_jue=True（维持冻结）。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", True)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(40))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is True

    def test_boundary_freeze_threshold_38_not_frozen(self):
        """dao=38 (=冻结门槛, 上轮未冻结) → 不冻结（<38 才冻结）。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", False)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(38))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is False

    def test_boundary_thaw_threshold_43_frozen(self):
        """dao=43 (=解冻门槛, 上轮已冻结) → 保持冻结（>43 才解冻）。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", True)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(43))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is True

    def test_no_threshold_chatter_37_to_40(self):
        """dao=37 触发冻结 → dao=40 仍在滞回区间不立即解冻（防抖动核心用例）。"""
        s = _make_scorer()
        # 第一轮：dao=37 (<38) 触发冻结
        _set_dao_frozen(s, "crypto_usdt", False)
        state1 = s.score_and_decide(raw_scores_by_class=_scores_dao(37))
        assert state1.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is True
        # 第二轮：dao=40 仍在滞回区间 [38,43]，应保持冻结
        state2 = s.score_and_decide(raw_scores_by_class=_scores_dao(40))
        assert state2.dimension_veto_flags["crypto_usdt"]["dao_jv_fou_jue"] is True

    def test_fail_open_default_not_frozen(self):
        """FAIL-OPEN：新建 scorer 的 _dao_veto_frozen 默认 False。"""
        s = _make_scorer()
        assert s._dao_veto_frozen["crypto_usdt"] is False
        assert s._dao_veto_frozen["us_stock"] is False
        assert s._dao_veto_frozen["precious_metal"] is False

    def test_dao_xiao_40_unchanged(self):
        """dao_xiao_40 旗标保持原 <40 逻辑（不受滞回带影响）。"""
        s = _make_scorer()
        _set_dao_frozen(s, "crypto_usdt", False)
        state = s.score_and_decide(raw_scores_by_class=_scores_dao(39))
        assert state.dimension_veto_flags["crypto_usdt"]["dao_xiao_40"] is True
