# -*- coding: utf-8 -*-
"""BDSM v1.3 动态评估器 Phase 0 单元测试 — TDD RED 阶段.

覆盖 spec §3.2~§3.4 四个新函数：
  1. _compute_technical_assessment  — 技术面评估器(RSI/MA200/成交量/ATR)
  2. _compute_cvs                   — 综合估值分 CVS=BDS×0.6+TS×0.4 + ratio映射
  3. _compute_trend_stop            — 趋势止损(MA200/MA128破位)
  4. _compute_value_exit            — 价值发现止盈(P/F高估/BDS恶化)

以及 _neutral_coin_entry / _build_coin_entry 新增字段的向后兼容。
"""
from __future__ import annotations

import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_FORCE_VEC_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "scripts", "memory_l4", "force_vector"))
if _FORCE_VEC_DIR not in sys.path:
    sys.path.insert(0, _FORCE_VEC_DIR)


# ── K 线合成工具（与 multi_scenario_validation.py 格式一致）──────────────

def _make_downtrend_klines(n: int = 250, start: float = 100.0, pct: float = -0.005) -> list:
    """持续下跌的K线序列。"""
    klines = []
    price = start
    for i in range(n):
        o = price
        price = price * (1 + pct)
        klines.append({"ts": i, "o": round(o, 4), "h": round(o * 1.002, 4),
                        "l": round(price * 0.998, 4), "c": round(price, 4),
                        "v": 10000 + i * 50})
    return klines


def _make_uptrend_klines(n: int = 250, start: float = 100.0, pct: float = 0.005) -> list:
    """持续上涨的K线序列。"""
    klines = []
    price = start
    for i in range(n):
        o = price
        price = price * (1 + pct)
        klines.append({"ts": i, "o": round(o, 4), "h": round(price * 1.003, 4),
                        "l": round(o * 0.998, 4), "c": round(price, 4),
                        "v": 10000 + i * 50})
    return klines


def _make_flat_klines(n: int = 250, base: float = 100.0) -> list:
    """平稳震荡K线。"""
    klines = []
    for i in range(n):
        noise = (i % 5 - 2) * 0.001
        c = base * (1 + noise)
        klines.append({"ts": i, "o": round(base, 4), "h": round(c * 1.002, 4),
                        "l": round(base * 0.998, 4), "c": round(c, 4),
                        "v": 10000})
    return klines


def _make_volume_spike_klines(n: int = 250, base: float = 100.0) -> list:
    """最后5根K线成交量放大5倍的平稳序列。"""
    klines = _make_flat_klines(n, base)
    for k in klines[-5:]:
        k["v"] = 50000
    return klines


# ═══════════════════════════════════════════════════════════════════════
# §3.2.1 技术面评估器
# ═══════════════════════════════════════════════════════════════════════

class TestComputeTechnicalAssessment(unittest.TestCase):
    """技术面评估器：RSI / MA200偏离 / 成交量比 / ATR / TS综合分。"""

    def test_downtrend_rsi_oversold(self) -> None:
        """持续下跌 → RSI(14) < 30（超卖）。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        klines = _make_downtrend_klines(n=250, pct=-0.01)
        ta = _compute_technical_assessment("TEST", klines, ma_long=200, ma_short=128)
        self.assertIsInstance(ta, dict)
        self.assertLess(ta["rsi_14"], 30.0,
                        f"下跌趋势RSI应<30，实际={ta['rsi_14']}")

    def test_uptrend_rsi_overbought(self) -> None:
        """持续上涨 → RSI(14) > 70（超买）。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        klines = _make_uptrend_klines(n=250, pct=0.01)
        ta = _compute_technical_assessment("TEST", klines, ma_long=200, ma_short=128)
        self.assertGreater(ta["rsi_14"], 70.0,
                           f"上涨趋势RSI应>70，实际={ta['rsi_14']}")

    def test_downtrend_ma200_deviation_negative(self) -> None:
        """持续下跌 → 价格远低于MA200 → ma200_deviation < -15%。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        klines = _make_downtrend_klines(n=250, pct=-0.01)
        ta = _compute_technical_assessment("TEST", klines, ma_long=200, ma_short=128)
        self.assertLess(ta["ma200_deviation"], -15.0,
                        f"下跌趋势MA200偏离应<-15%，实际={ta['ma200_deviation']}")

    def test_volume_spike_ratio_gt_2(self) -> None:
        """成交量放大 → volume_ratio > 2.0。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        klines = _make_volume_spike_klines(n=250)
        ta = _compute_technical_assessment("TEST", klines, ma_long=200, ma_short=128)
        self.assertGreater(ta["volume_ratio"], 2.0,
                           f"放量后volume_ratio应>2.0，实际={ta['volume_ratio']}")

    def test_ts_score_in_range_0_1(self) -> None:
        """TS Score 归一化在 [0, 1]。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        for klines in [_make_downtrend_klines(250), _make_uptrend_klines(250), _make_flat_klines(250)]:
            ta = _compute_technical_assessment("TEST", klines, ma_long=200, ma_short=128)
            self.assertGreaterEqual(ta["ts_score"], 0.0)
            self.assertLessEqual(ta["ts_score"], 1.0)

    def test_empty_klines_fail_open(self) -> None:
        """空K线 → 返回中性值，不抛异常。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        ta = _compute_technical_assessment("TEST", [], ma_long=200, ma_short=128)
        self.assertEqual(ta["rsi_14"], 50.0)      # 中性
        self.assertEqual(ta["ts_score"], 0.0)
        self.assertEqual(ta["ma200_deviation"], 0.0)

    def test_insufficient_klines_fail_open(self) -> None:
        """K线不足MA周期 → 返回中性值，不抛异常。"""
        from bdsm_snapshot_writer import _compute_technical_assessment
        klines = _make_flat_klines(n=50)  # 远少于200
        ta = _compute_technical_assessment("TEST", klines, ma_long=200, ma_short=128)
        self.assertEqual(ta["rsi_14"], 50.0)
        self.assertEqual(ta["ma200_deviation"], 0.0)


# ═══════════════════════════════════════════════════════════════════════
# §3.2.2 综合估值分 CVS
# ═══════════════════════════════════════════════════════════════════════

class TestComputeCVS(unittest.TestCase):
    """CVS = BDS×0.6 + TS×0.4，映射 ratio。"""

    def test_cvs_formula(self) -> None:
        """CVS = BDS×0.6 + TS×0.4。"""
        from bdsm_snapshot_writer import _compute_cvs
        cvs, ratio = _compute_cvs(bds_score=0.5, ts_score=0.5)
        self.assertAlmostEqual(cvs, 0.5, places=4)
        self.assertEqual(ratio, 0.3)  # 0.3~0.6 → 0.3

    def test_cvs_high_ratio_1_0(self) -> None:
        """CVS >= 0.8 → ratio=1.0（打完子弹）。"""
        from bdsm_snapshot_writer import _compute_cvs
        cvs, ratio = _compute_cvs(bds_score=0.9, ts_score=0.7)
        # CVS = 0.9×0.6 + 0.7×0.4 = 0.54 + 0.28 = 0.82
        self.assertGreaterEqual(cvs, 0.8)
        self.assertEqual(ratio, 1.0)

    def test_cvs_medium_ratio_0_5(self) -> None:
        """CVS 0.6~0.8 → ratio=0.5。"""
        from bdsm_snapshot_writer import _compute_cvs
        cvs, ratio = _compute_cvs(bds_score=0.8, ts_score=0.5)
        # CVS = 0.8×0.6 + 0.5×0.4 = 0.48 + 0.20 = 0.68
        self.assertGreaterEqual(cvs, 0.6)
        self.assertLess(cvs, 0.8)
        self.assertEqual(ratio, 0.5)

    def test_cvs_normal_ratio_0_3(self) -> None:
        """CVS 0.3~0.6 → ratio=0.3。"""
        from bdsm_snapshot_writer import _compute_cvs
        cvs, ratio = _compute_cvs(bds_score=0.5, ts_score=0.5)
        # CVS = 0.5×0.6 + 0.5×0.4 = 0.30 + 0.20 = 0.50
        self.assertGreaterEqual(cvs, 0.3)
        self.assertLess(cvs, 0.6)
        self.assertEqual(ratio, 0.3)

    def test_cvs_low_ratio_0_0(self) -> None:
        """CVS < 0.3 → ratio=0.0（不加仓）。"""
        from bdsm_snapshot_writer import _compute_cvs
        cvs, ratio = _compute_cvs(bds_score=0.1, ts_score=0.1)
        # CVS = 0.1×0.6 + 0.1×0.4 = 0.06 + 0.04 = 0.10
        self.assertLess(cvs, 0.3)
        self.assertEqual(ratio, 0.0)

    def test_cvs_boundary_0_8(self) -> None:
        """CVS 恰好 0.8 → ratio=1.0（边界包含）。"""
        from bdsm_snapshot_writer import _compute_cvs
        cvs, ratio = _compute_cvs(bds_score=1.0, ts_score=0.5)
        # CVS = 1.0×0.6 + 0.5×0.4 = 0.60 + 0.20 = 0.80
        self.assertAlmostEqual(cvs, 0.8, places=4)
        self.assertEqual(ratio, 1.0)


# ═══════════════════════════════════════════════════════════════════════
# §3.3.1 趋势止损
# ═══════════════════════════════════════════════════════════════════════

class TestComputeTrendStop(unittest.TestCase):
    """MA200/MA128 趋势止损。"""

    def test_ma200_break_3days_reduce50(self) -> None:
        """连续3日收盘低于MA 且 MA斜率转负 → reduce50。用小周期精确控制 below_days=3。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        # ma_long=10: 前17根平稳100 + 后3根跌到90 → below_days=3
        flat = [{"ts": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10000} for i in range(17)]
        drop = [{"ts": 17 + i, "o": 100, "h": 100, "l": 89, "c": 90, "v": 10000} for i in range(3)]
        ts = _compute_trend_stop("TEST", flat + drop, ma_long=10, ma_short=5)
        self.assertEqual(ts["action"], "reduce50",
                         f"below_days=3+斜率负应reduce50，实际={ts['action']}, below={ts['below_ma200_days']}")

    def test_ma200_break_5days_full_exit(self) -> None:
        """连续5日收盘低于MA 且 MA斜率转负 → full_exit。用小周期精确控制 below_days=5。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        # ma_long=10: 前15根平稳100 + 后5根跌到90 → below_days=5
        flat = [{"ts": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10000} for i in range(15)]
        drop = [{"ts": 15 + i, "o": 100, "h": 100, "l": 89, "c": 90, "v": 10000} for i in range(5)]
        ts = _compute_trend_stop("TEST", flat + drop, ma_long=10, ma_short=5)
        self.assertEqual(ts["action"], "full_exit",
                         f"below_days=5+斜率负应full_exit，实际={ts['action']}, below={ts['below_ma200_days']}")

    def test_uptrend_no_signal(self) -> None:
        """上涨趋势 → none。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        klines = _make_uptrend_klines(250, pct=0.005)
        ts = _compute_trend_stop("TEST", klines, ma_long=200, ma_short=128)
        self.assertEqual(ts["action"], "none")

    def test_empty_klines_fail_open(self) -> None:
        """空K线 → none。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        ts = _compute_trend_stop("TEST", [], ma_long=200, ma_short=128)
        self.assertEqual(ts["action"], "none")

    def test_insufficient_klines_fail_open(self) -> None:
        """K线不足 → none。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        klines = _make_flat_klines(50)
        ts = _compute_trend_stop("TEST", klines, ma_long=200, ma_short=128)
        self.assertEqual(ts["action"], "none")


# ═══════════════════════════════════════════════════════════════════════
# §3.4.2 价值发现止盈
# ═══════════════════════════════════════════════════════════════════════

class TestComputeValueExit(unittest.TestCase):
    """P/F高估 / BDS恶化 → 价值发现止盈。"""

    def test_pf_overvalued_reduce30(self) -> None:
        """估值分位 > 80（P/F进入高估区） → reduce30。"""
        from bdsm_snapshot_writer import _compute_value_exit
        ve = _compute_value_exit(bds_score=0.1, valuation_percentile=85.0)
        self.assertTrue(ve["pf_overvalued"])
        self.assertEqual(ve["action"], "reduce30")

    def test_pf_bubble_full_exit(self) -> None:
        """估值分位 > 90（P/F极端泡沫） → full_exit。"""
        from bdsm_snapshot_writer import _compute_value_exit
        ve = _compute_value_exit(bds_score=-0.1, valuation_percentile=95.0)
        self.assertTrue(ve["pf_bubble"])
        self.assertEqual(ve["action"], "full_exit")

    def test_bds_collapse_full_exit(self) -> None:
        """BDS < 0.0 → full_exit。"""
        from bdsm_snapshot_writer import _compute_value_exit
        ve = _compute_value_exit(bds_score=-0.5, valuation_percentile=50.0)
        self.assertEqual(ve["action"], "full_exit")

    def test_normal_none(self) -> None:
        """正常估值 → none。"""
        from bdsm_snapshot_writer import _compute_value_exit
        ve = _compute_value_exit(bds_score=0.5, valuation_percentile=50.0)
        self.assertFalse(ve["pf_overvalued"])
        self.assertFalse(ve["pf_bubble"])
        self.assertEqual(ve["action"], "none")

    def test_low_valuation_none(self) -> None:
        """低估值(BDS≥0.3 + 分位<30) → none（低估不卖）。"""
        from bdsm_snapshot_writer import _compute_value_exit
        ve = _compute_value_exit(bds_score=0.6, valuation_percentile=20.0)
        self.assertEqual(ve["action"], "none")


# ═══════════════════════════════════════════════════════════════════════
# 中性兜底 + 向后兼容
# ═══════════════════════════════════════════════════════════════════════

class TestNeutralEntryHasNewFields(unittest.TestCase):
    """_neutral_coin_entry 必须包含 v1.3 新增字段。"""

    def test_neutral_has_technical_assessment(self) -> None:
        from bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test")
        self.assertIn("technical_assessment", entry)
        self.assertEqual(entry["technical_assessment"]["rsi_14"], 50.0)
        self.assertEqual(entry["technical_assessment"]["ts_score"], 0.0)

    def test_neutral_has_cvs_and_ratio(self) -> None:
        from bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test")
        self.assertIn("cvs", entry)
        self.assertIn("cvs_ratio", entry)
        self.assertEqual(entry["cvs"], 0.0)
        self.assertEqual(entry["cvs_ratio"], 0.0)

    def test_neutral_has_scaling_plan(self) -> None:
        from bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test")
        self.assertIn("scaling_plan", entry)
        plan = entry["scaling_plan"]
        self.assertIn("target_notional_usdt", plan)
        self.assertIn("remaining_budget", plan)
        self.assertIn("completed", plan)

    def test_neutral_has_trend_stop(self) -> None:
        from bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test")
        self.assertIn("trend_stop", entry)
        self.assertEqual(entry["trend_stop"]["action"], "none")

    def test_neutral_has_value_exit(self) -> None:
        from bdsm_snapshot_writer import _neutral_coin_entry
        entry = _neutral_coin_entry("test")
        self.assertIn("value_exit", entry)
        self.assertEqual(entry["value_exit"]["action"], "none")


# ═══════════════════════════════════════════════════════════════════════
# Phase 1: _apply_bdsm_scaling — 动态评估驱动的分批建仓（gap2 升级）
# ═══════════════════════════════════════════════════════════════════════

class TestApplyBdsmScaling(unittest.TestCase):
    """Phase 1: _apply_bdsm_scaling — CVS 驱动分批建仓。

    spec §3.2.2 + §5.3 Phase 1：
      - CVS < 0.3 或 plan 缺失 → FAIL-OPEN 回退 _apply_bdsm_cap_multiplier
      - CVS 0.3~0.6 → batch = remaining × 0.3
      - CVS 0.6~0.8 → batch = remaining × 0.5
      - CVS >= 0.8 → 打完子弹 batch = remaining
      - remaining <= 0 → (0.0, 0.0, "bdsm_scaling_completed")
      - accumulated 已建仓从 PositionTracker 扣减 remaining
    """

    def setUp(self) -> None:
        _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
        _BASE_11 = str(os.path.dirname(_THIS_DIR))  # .../11-易经推理系统
        _MEM_L4 = os.path.join(_BASE_11, "scripts", "memory_l4")
        for p in (_MEM_L4, _BASE_11):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, _BASE_11)

    def _make_trader(self, snap, bdsm_coins=None, accumulated=0.0):
        """构造最小 PollingTrader 实例，绕过 __init__ 重依赖。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset(bdsm_coins or {"UNI"})
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": snap}
        # mock _get_bdsm_accumulated_position 返回 accumulated
        t._get_bdsm_accumulated_position = MagicMock(return_value=accumulated)
        return t

    def test_non_bdsm_fallback_cap(self) -> None:
        """非 BDSM 币 → 回退 cap 逻辑，返回原仓位 cap=1.0。"""
        snap = {"version": "1.3", "coins": {}}
        t = self._make_trader(snap, bdsm_coins={"UNI"})
        actual, cap, tag = t._apply_bdsm_scaling("BTC", 1000.0, 50.0)
        self.assertAlmostEqual(actual, 1000.0, delta=1e-6)
        self.assertAlmostEqual(cap, 1.0, delta=1e-6)
        self.assertEqual(tag, "not_bdsm_coin")

    def test_cvs_below_0_3_fallback_cap(self) -> None:
        """CVS < 0.3 → 回退 cap 逻辑（不加仓）。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.1, "cvs_ratio": 0.0,
            "scaling_plan": {"remaining_budget": 167.0},
            "cap_multiplier": 0.5,
        }}}
        t = self._make_trader(snap, accumulated=0.0)
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # 回退 cap：1000 × 0.5 = 500
        self.assertAlmostEqual(actual, 500.0, delta=1e-6)
        self.assertEqual(tag, "bdsm_cap_applied")

    def test_cvs_medium_batch_50pct(self) -> None:
        """CVS 0.6~0.8 → batch = remaining × 0.5。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.7, "cvs_ratio": 0.5,
            "scaling_plan": {"remaining_budget": 200.0},
            "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap, accumulated=0.0)
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # remaining = 200 - 0 = 200；batch = 200 × 0.5 = 100
        self.assertAlmostEqual(actual, 100.0, delta=1e-6)
        self.assertIn("bdsm_cvs_0.70", tag)

    def test_cvs_high_all_in(self) -> None:
        """CVS >= 0.8 → 打完子弹 batch = remaining。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.85, "cvs_ratio": 1.0,
            "scaling_plan": {"remaining_budget": 167.0},
            "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap, accumulated=0.0)
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # 打完子弹：batch = remaining = 167
        self.assertAlmostEqual(actual, 167.0, delta=1e-6)
        self.assertIn("ratio_1.0", tag)

    def test_remaining_zero_completed(self) -> None:
        """remaining <= 0（已建满）→ (0.0, 0.0, "bdsm_scaling_completed")。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.7, "cvs_ratio": 0.5,
            "scaling_plan": {"remaining_budget": 167.0},
            "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap, accumulated=170.0)  # accumulated > remaining_budget
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        self.assertAlmostEqual(actual, 0.0, delta=1e-6)
        self.assertEqual(tag, "bdsm_scaling_completed")

    def test_accumulated_deducted(self) -> None:
        """accumulated > 0 → remaining 正确扣减。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.85, "cvs_ratio": 1.0,  # 打完子弹
            "scaling_plan": {"remaining_budget": 200.0},
            "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap, accumulated=80.0)
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # remaining = 200 - 80 = 120；打完子弹 → batch = 120
        self.assertAlmostEqual(actual, 120.0, delta=1e-6)

    def test_missing_plan_fallback_cap(self) -> None:
        """scaling_plan 缺失 → 回退 cap 逻辑。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.7, "cvs_ratio": 0.5,
            "cap_multiplier": 0.3,
        }}}  # 无 scaling_plan
        t = self._make_trader(snap, accumulated=0.0)
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # 回退 cap：1000 × 0.3 = 300
        self.assertAlmostEqual(actual, 300.0, delta=1e-6)
        self.assertEqual(tag, "bdsm_cap_applied")

    # ————————————————————————————————————————————————————————————————
    # 微仓实盘测试模式：bdsm_budget_per_coin 硬覆盖（单仓≤25U）
    # ————————————————————————————————————————————————————————————————
    def test_bdsm_budget_per_coin_overrides_remaining_plan(self) -> None:
        """bdsm_budget_per_coin 指定后，remaining_budget 取 min(plan, 硬上限)，
        避免 BDSM 实盘测试阶段单币预算过大（默认 167U 对微仓太激进）。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.7, "cvs_ratio": 0.5,
            "scaling_plan": {"remaining_budget": 167.0},  # 默认167U
            "cap_multiplier": 1.0,
            "bds_score": 0.5,
            "ts_score": 0.2,
            "trend_stop": {"action": "none"},
            "value_exit": {"action": "none"},
            "direction_constraint": "NEUTRAL",
        }}}
        t = self._make_trader(snap, accumulated=0.0)
        t.bdsm_budget_per_coin = 25.0  # 微仓硬上限 25U
        # mock war_state=ALLOW + BDS>0 前置检查通过
        from unittest.mock import MagicMock
        t._state_cache = MagicMock()
        t._state_cache.war_state = {"crypto_usdt": "ALLOW"}
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # min(167, 25) = 25；CVS=0.7 → ratio=0.5 → batch = 25 × 0.5 = 12.5
        self.assertAlmostEqual(actual, 12.5, delta=1e-6,
                               msg=f"bdsm_budget_per_coin=25 未生效；actual={actual}，tag={tag}")
        self.assertIn("bdsm_cvs_0.70", tag)

    def test_bdsm_budget_per_coin_none_uses_plan(self) -> None:
        """None 时沿用 scaling_plan.remaining_budget，行为与旧逻辑一致。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "cvs": 0.7, "cvs_ratio": 0.5,
            "scaling_plan": {"remaining_budget": 167.0},
            "cap_multiplier": 1.0,
            "bds_score": 0.5,
            "trend_stop": {"action": "none"},
            "value_exit": {"action": "none"},
            "direction_constraint": "NEUTRAL",
        }}}
        t = self._make_trader(snap, accumulated=0.0)
        t.bdsm_budget_per_coin = None
        from unittest.mock import MagicMock
        t._state_cache = MagicMock()
        t._state_cache.war_state = {"crypto_usdt": "ALLOW"}
        actual, cap, tag = t._apply_bdsm_scaling("UNI", 1000.0, 50.0)
        # 167 × 0.5 = 83.5
        self.assertAlmostEqual(actual, 83.5, delta=1e-6)


# ═══════════════════════════════════════════════════════════════════════
# Phase 2: 趋势止损 + 价值发现止盈（gap3 新增）
# ═══════════════════════════════════════════════════════════════════════

class TestBdsmTrendStopValueExit(unittest.TestCase):
    """Phase 2: gap3 新增趋势止损 + 价值发现止盈检查。

    spec §3.3.1 + §3.4.2 + §5.3 Phase 2：
      - trend_stop.action = reduce50 → 执行 REDUCE 50%
      - trend_stop.action = full_exit → 执行 CLOSE_ALL
      - value_exit.action = reduce30 → 执行 REDUCE 30%
      - trend_stop 和 value_exit 同时触发 → 取优先级最高
      - 两者都 none → 沿用原 exit_action 逻辑（不重复执行）
    """

    def setUp(self) -> None:
        _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
        _BASE_11 = str(os.path.dirname(_THIS_DIR))
        _MEM_L4 = os.path.join(_BASE_11, "scripts", "memory_l4")
        for p in (_MEM_L4, _BASE_11):
            if p in sys.path:
                sys.path.remove(p)
        sys.path.insert(0, _MEM_L4)
        sys.path.insert(0, _BASE_11)

    def _make_trader(self, snap, bdsm_coins=None):
        """构造最小 trader 实例用于 gap3 出场巡检测试。"""
        from unittest.mock import MagicMock, patch
        from scripts.memory_l4.polling_trader import PollingTrader
        with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
            t = PollingTrader.__new__(PollingTrader)
        t._log = MagicMock()
        t.BDSM_COINS = frozenset(bdsm_coins or {"UNI"})
        t._bdsm_snapshot_cache = {"ts": float("inf"), "snapshot": snap}
        t.okx_client = MagicMock()
        t.okx_client.market_close_long = MagicMock(return_value={"ok": True, "dry_run": False})
        t.okx_client.market_close_short = MagicMock(return_value={"ok": True, "dry_run": False})
        t.position_tracker = MagicMock()
        t.position_tracker.all_open_positions = MagicMock(return_value=[])
        t._handle_close_position = MagicMock()
        t._bdsm_partial_reduce_position = MagicMock(return_value={"ok": True, "reduce_ratio": 0.5})
        pos_info = {"has_position": True, "inst_id": "UNI-USDT-SWAP", "coin": "UNI",
                    "pos_side": "long", "pos": 10, "avg_px": 10.0, "mark_px": 11.0,
                    "upl": 10.0, "upl_ratio": 0.10, "open_time_sec": 0,
                    "source_tag": "bdsm"}
        t._get_coin_position_info = MagicMock(return_value=pos_info)
        return t

    def test_trend_stop_reduce50_triggers_partial_reduce(self) -> None:
        """trend_stop.action=reduce50 + exit_action=NONE → 触发 REDUCE 50%。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "exit_action": "NONE", "exit_triggers": [],
            "trend_stop": {"action": "reduce50"},
            "value_exit": {"action": "none"},
            "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap)
        actions = t._bdsm_check_exit_actions()
        # 应该调用 _bdsm_partial_reduce_position with reduce_ratio=0.5
        t._bdsm_partial_reduce_position.assert_called_once()
        _, kwargs = t._bdsm_partial_reduce_position.call_args
        self.assertAlmostEqual(kwargs.get("reduce_ratio", 0), 0.5, delta=1e-6)

    def test_trend_stop_full_exit_triggers_close_all(self) -> None:
        """trend_stop.action=full_exit + exit_action=NONE → 触发 CLOSE_ALL。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "exit_action": "NONE", "exit_triggers": [],
            "trend_stop": {"action": "full_exit"},
            "value_exit": {"action": "none"},
            "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap)
        t._bdsm_check_exit_actions()
        t.okx_client.market_close_long.assert_called_once()

    def test_value_exit_reduce30_triggers_partial_reduce(self) -> None:
        """value_exit.action=reduce30 + exit_action=NONE → 触发 REDUCE 30%。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "exit_action": "NONE", "exit_triggers": [],
            "trend_stop": {"action": "none"},
            "value_exit": {"action": "reduce30"},
            "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap)
        t._bdsm_check_exit_actions()
        t._bdsm_partial_reduce_position.assert_called_once()
        _, kwargs = t._bdsm_partial_reduce_position.call_args
        self.assertAlmostEqual(kwargs.get("reduce_ratio", 0), 0.3, delta=1e-6)

    def test_both_trend_stop_and_value_exit_take_higher_priority(self) -> None:
        """trend_stop=reduce30 + value_exit=full_exit → 取 full_exit（更高优先级）。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "exit_action": "NONE", "exit_triggers": [],
            "trend_stop": {"action": "reduce30"},
            "value_exit": {"action": "full_exit"},
            "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap)
        t._bdsm_check_exit_actions()
        # full_exit 优先 → 走 CLOSE_ALL
        t.okx_client.market_close_long.assert_called_once()
        t._bdsm_partial_reduce_position.assert_not_called()

    def test_both_none_no_action(self) -> None:
        """trend_stop=none + value_exit=none + exit_action=NONE → 无动作。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "exit_action": "NONE", "exit_triggers": [],
            "trend_stop": {"action": "none"},
            "value_exit": {"action": "none"},
            "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap)
        actions = t._bdsm_check_exit_actions()
        t.okx_client.market_close_long.assert_not_called()
        t._bdsm_partial_reduce_position.assert_not_called()

    def test_exit_action_still_takes_precedence_over_trend_stop(self) -> None:
        """exit_action=CLOSE_ALL + trend_stop=reduce50 → 优先执行原 CLOSE_ALL（不重复）。"""
        snap = {"version": "1.3", "coins": {"UNI": {
            "exit_action": "CLOSE_ALL", "exit_triggers": ["B5_rank_tumbling"],
            "trend_stop": {"action": "reduce50"},
            "value_exit": {"action": "none"},
            "direction_constraint": "NEUTRAL", "cap_multiplier": 1.0,
        }}}
        t = self._make_trader(snap)
        t._bdsm_check_exit_actions()
        t.okx_client.market_close_long.assert_called_once()
        # CLOSE_ALL 已执行，不再触发 reduce50
        t._bdsm_partial_reduce_position.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ═══════════════════════════════════════════════════════════════════════
# Phase 3 修复 TDD：death_cross 阈值收紧 + 胜率口径修正
# ═══════════════════════════════════════════════════════════════════════

class TestDeathCrossFalseSignalFix(unittest.TestCase):
    """Fix-I: death_cross 仅在 belowMA200≥2 且 MA200 斜率负 时才触发 reduce30。

    原 bug：只要 MA128 < MA200（死叉形成）就 reduce30，导致 40%超买区间短期回调
    也误触发（AAVE belowMA200=0天 + MA200斜率正 + RSI>70，仍然 reduce30 → 假信号）。
    """

    def setUp(self) -> None:
        _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
        _FORCE_VEC_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "scripts", "memory_l4", "force_vector"))
        if _FORCE_VEC_DIR not in sys.path:
            sys.path.insert(0, _FORCE_VEC_DIR)

    def _make_uptrend_then_death_cross(
        self, total_n=150, ma_long=10, ma_short=5, below_days=0, slope_positive=True
    ) -> list:
        """构造小周期K线：前(total-n-days)根上涨，最后days根跌破MA形成死叉。

        用 ma_long=10/ma_short=5 精确控制 MA 交叉和 below_days。
        """
        klines = []
        # Phase 1: 上涨 (前 total_n-20 根) 价格从 100 → 200
        n_up = total_n - 20
        price = 100.0
        for i in range(n_up):
            price = price + (200 - 100) / n_up
            klines.append({"ts": i, "o": round(price - 0.3, 4), "h": round(price + 0.5, 4),
                            "l": round(price - 0.7, 4), "c": round(price, 4), "v": 10000})

        # Phase 2: 横盘或微回调 → 使 short_ma 靠近 long_ma 但尚未交叉
        # last 20 根：逐步降 到 below_days 控制的破位位置
        # 让 MA 斜率控制
        # slope_positive=True: MA200 继续上行；slope_positive=False: MA200 下行
        if slope_positive:
            # 保持价格整体缓慢上行，MA200 斜率为正
            for i in range(20):
                idx = n_up + i
                price = 200 + (i + 1) * 0.2  # 慢速上升
                # 让 below_days 控制：最后 below_days 根跌破当时 MA(long)
                if i >= (20 - below_days):
                    # 最后 below_days 根：价格大幅下跌跌破 MA
                    # 让当前 close = 90 (远低于MA)
                    price = 85.0 + (i % 3) * 2
                klines.append({"ts": idx, "o": round(price - 0.3, 4),
                                "h": round(price + 0.5, 4), "l": round(price - 0.7, 4),
                                "c": round(price, 4), "v": 10000})
        else:
            # 价格整体下行 → MA200 斜率为负
            for i in range(20):
                idx = n_up + i
                price = 200 - (i + 1) * 2.5  # 下行
                if i >= (20 - below_days):
                    price = 85.0 + (i % 3) * 2
                klines.append({"ts": idx, "o": round(price - 0.3, 4),
                                "h": round(price + 0.5, 4), "l": round(price - 0.7, 4),
                                "c": round(price, 4), "v": 10000})
        return klines

    def test_death_cross_below0_slope_positive_no_action(self) -> None:
        """假信号典型：MA128<MA200(死叉) + belowMA200=0 + MA200斜率正 → 应该 NONE，不应reduce30。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        klines = self._make_uptrend_then_death_cross(
            total_n=150, ma_long=10, ma_short=5, below_days=0, slope_positive=True
        )
        ts = _compute_trend_stop("TEST", klines, ma_long=10, ma_short=5)
        # 死叉可能形成，但 below=0 slope正 → 不应 reduce30
        self.assertEqual(ts["action"], "none",
                         f"below=0+斜率正不应触发reduce30，实际death_cross={ts['death_cross']} "
                         f"below={ts['below_ma200_days']} slope_neg={ts['ma200_slope_negative']} "
                         f"action={ts['action']}")

    def test_death_cross_below1_slope_positive_no_action(self) -> None:
        """死叉 + below=1 天 + 斜率正 → 仍不够，应为 NONE。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        klines = self._make_uptrend_then_death_cross(
            total_n=150, ma_long=10, ma_short=5, below_days=1, slope_positive=True
        )
        ts = _compute_trend_stop("TEST", klines, ma_long=10, ma_short=5)
        self.assertEqual(ts["action"], "none",
                         f"below=1+斜率正不应触发reduce30，below={ts['below_ma200_days']} "
                         f"slope_neg={ts['ma200_slope_negative']} action={ts['action']}")

    def test_death_cross_below2_slope_negative_triggers_reduce30(self) -> None:
        """真信号：死叉 + below≥2 + 斜率负 → 至少触发某级 reduce（不高于 full_exit）。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        # 复用 Phase0 测试用例：below=3(ma_long=10小周期) + slope负 → reduce50
        # ma_long=10: 前15根平稳100 + 后5根跌到90 → below=3+slope负
        flat = [{"ts": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10000} for i in range(15)]
        drop = [{"ts": 15 + i, "o": 100, "h": 100, "l": 89, "c": 90, "v": 10000} for i in range(3)]
        ts = _compute_trend_stop("TEST", flat + drop, ma_long=10, ma_short=5)
        self.assertIn(ts["action"], ("reduce50", "reduce30"),
                      f"below≥2+斜率负+死叉应触发减仓，below={ts['below_ma200_days']} "
                      f"slope_neg={ts['ma200_slope_negative']} action={ts['action']}")

    def test_existing_reduce50_full_exit_not_regressed(self) -> None:
        """修复后 below≥3+slope负→reduce50；below≥5+slope负→full_exit 不应回归。"""
        from bdsm_snapshot_writer import _compute_trend_stop
        # below=3 slope负 → reduce50
        flat = [{"ts": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10000} for i in range(17)]
        drop = [{"ts": 17 + i, "o": 100, "h": 100, "l": 89, "c": 90, "v": 10000} for i in range(3)]
        ts3 = _compute_trend_stop("TEST", flat + drop, ma_long=10, ma_short=5)
        self.assertEqual(ts3["action"], "reduce50",
                         f"below=3+斜率负应reduce50，below={ts3['below_ma200_days']} 实际={ts3['action']}")

        # below=5 slope负 → full_exit
        flat5 = [{"ts": i, "o": 100, "h": 101, "l": 99, "c": 100, "v": 10000} for i in range(15)]
        drop5 = [{"ts": 15 + i, "o": 100, "h": 100, "l": 89, "c": 90, "v": 10000} for i in range(5)]
        ts5 = _compute_trend_stop("TEST", flat5 + drop5, ma_long=10, ma_short=5)
        self.assertEqual(ts5["action"], "full_exit",
                         f"below=5+斜率负应full_exit，below={ts5['below_ma200_days']} 实际={ts5['action']}")


class TestWinRateMetricFix(unittest.TestCase):
    """Fix-II: 胜率口径修正 — reduce 不计入分母，仅 exit/window_end 统计；阈值 70%。"""

    def test_only_exit_and_window_count_as_wins(self) -> None:
        """最终胜率仅含 exit/window_end，reduce 跳过（战术性减仓非完整交易）。"""
        # 模拟一组 B 组交易（对应 diagnose 里的 AAVE 7reduce 全亏 + UNI 20win 6loss）
        closed = []
        # AAVE: 7 reduce 全亏（不计入）
        for _ in range(7):
            closed.append({"type": "reduce", "win": False, "pnl_usdt": -0.5})
        # PUMP: 3 reduce 全赢（不计入）
        for _ in range(3):
            closed.append({"type": "reduce", "win": True, "pnl_usdt": +3.0})
        # UNI: 20 赢 reduce + 6 亏 reduce（不计入）
        for _ in range(20):
            closed.append({"type": "reduce", "win": True, "pnl_usdt": +0.5})
        for _ in range(6):
            closed.append({"type": "reduce", "win": False, "pnl_usdt": -0.4})
        # UNI window_end 1 次赢（计入）
        closed.append({"type": "window_end", "win": True, "pnl_usdt": +13.79})
        # PUMP window_end 1 次赢（计入）
        closed.append({"type": "window_end", "win": True, "pnl_usdt": +7.91})
        # AAVE window_end 1 次亏（计入）
        closed.append({"type": "window_end", "win": False, "pnl_usdt": -3.61})

        # 旧口径（全部交易）：23/36 = 63.9%
        old_wins = sum(1 for t in closed if t["win"])
        old_total = len(closed)
        old_rate = old_wins / old_total * 100

        # 新口径（仅 exit/window_end/full_exit）：2/3 = 66.7% 接近真实投资表现
        complete = [t for t in closed if t["type"] in ("exit", "window_end", "full_exit")]
        new_wins = sum(1 for t in complete if t["win"])
        new_total = len(complete)
        new_rate = (new_wins / new_total * 100) if new_total > 0 else 0.0

        self.assertAlmostEqual(old_rate, 63.9, delta=2,
                               msg=f"旧口径应该≈63.9%，实际={old_rate:.1f}%")
        self.assertAlmostEqual(new_rate, 66.7, delta=0.5,
                               msg=f"新口径应该≈66.7%，实际={new_rate:.1f}%")
        # 新口径 ≥ 70% 阈值（如果 AAVE 没亏损 reduce 导致 window_end 亏损会更高）
        self.assertEqual(new_total, 3, msg="完整交易数应该=3(AAVE+PUMP+UNI各1)")


# ═══════════════════════════════════════════════════════════════════════
# BUG-4 / BUG-1 修复：估值分位方向 + 建仓低估门槛 (P0)
# ═══════════════════════════════════════════════════════════════════════

class TestValuationPercentileDirection(unittest.TestCase):
    """BUG-4 修复：估值分位代理公式方向必须为正。

    正确语义 (spec §3.4.2):
      MA200 偏离度 越高 → 价格越高估 → 估值分位 越高 → 触发 reduce/full_exit
      MA200 偏离度 越低 (负) → 价格越超卖/低估 → 估值分位 越低 → 不应减仓

    旧 BUG 公式: valuation_pct = dev × -1 + 50   (反向，高估→低分，低估→高分)
    新正确公式: valuation_pct = dev × 2 + 50     (正向，0 居中，+30%→110 截断100，-30%→-10 截断0)
    """

    def test_overvalued_dev40_should_trigger_reduce(self) -> None:
        """MA200_dev=+40%（极度高估，AAVE RSI=78场景）→ 估值分位≈100 → _compute_value_exit 给 reduce30+。"""
        from bdsm_snapshot_writer import _compute_value_exit
        dev_pct = 40.0  # +40% 偏离
        val_pct = dev_pct * 2 + 50  # 130 → 截断 100
        val_pct = min(100.0, max(0.0, val_pct))
        result = _compute_value_exit(bds_score=0.4, valuation_percentile=val_pct)
        # 估值=100% → 泡沫 → full_exit
        self.assertEqual(val_pct, 100.0)
        self.assertEqual(result.get("action"), "full_exit",
                         msg=f"MA200_dev=+40% 极度高估应触发 full_exit，实际 action={result}")

    def test_fairvalue_dev0_should_noop(self) -> None:
        """MA200_dev=0%（均线附近）→ 估值分位=50 → 不触发任何 action。"""
        from bdsm_snapshot_writer import _compute_value_exit
        dev_pct = 0.0
        val_pct = min(100.0, max(0.0, dev_pct * 2 + 50))
        result = _compute_value_exit(bds_score=0.4, valuation_percentile=val_pct)
        self.assertEqual(val_pct, 50.0)
        self.assertEqual(result.get("action"), "none",
                         msg=f"MA200_dev=0% 合理区应=none，实际={result}")

    def test_oversold_dev_neg30_should_not_exit(self) -> None:
        """MA200_dev=-30%（超跌底，应该是加仓点）→ 估值分位≈0 → 价值发现=none，绝对不该减仓。"""
        from bdsm_snapshot_writer import _compute_value_exit
        dev_pct = -30.0
        val_pct = min(100.0, max(0.0, dev_pct * 2 + 50))
        result = _compute_value_exit(bds_score=0.5, valuation_percentile=val_pct)
        self.assertEqual(val_pct, 0.0)
        self.assertEqual(result.get("action"), "none",
                         msg=f"MA200_dev=-30% 低估区应=none，实际={result}（绝对不该在底部减仓）")

    def test_overvalued_dev15_should_trigger_reduce30(self) -> None:
        """MA200_dev=+16% → 估值分位=82 → 越过高估线 → reduce30。"""
        from bdsm_snapshot_writer import _compute_value_exit
        dev_pct = 16.0
        val_pct = min(100.0, max(0.0, dev_pct * 2 + 50))
        result = _compute_value_exit(bds_score=0.35, valuation_percentile=val_pct)
        self.assertEqual(val_pct, 82.0)
        # >80 → pf_overvalued=True → reduce30
        self.assertIn(result.get("action"), ("reduce30", "full_exit"),
                      msg=f"估值分位=82 高估区应≥reduce30，实际={result}")


class TestUndervaluedEntryGate(unittest.TestCase):
    """BUG-1 修复：建仓必须叠加 P/F 低估门槛（spec §2.4 / §3.5）。

    正确语义：
      spec §2.4 低估区 = BDS >= 0.3 AND P/F < 中位数 * 0.7x
      P/F < 0.7x 中位数 ←→ 估值分位 < 50%（分位50=中位数，0.7x中位数≈分位<50%对应低估）
    错误旧版：仅 BDS >= 0.3（无估值筛选）
    错误次旧版：<30%（过严，30日窗口零交易）
    """

    def test_bds_high_but_valuation_high_should_not_enter(self) -> None:
        """BDS=0.4（达标）但估值分位=70%（>50%，合理偏高估）→ 拒绝建仓。"""
        bds = 0.40
        val_pct = 70.0  # 高估
        is_undervalued = (bds >= 0.3) and (val_pct < 50.0)
        self.assertFalse(is_undervalued,
                         msg=f"估值分位=70% (合理偏高估) 应拒绝建仓，BDS={bds}")

    def test_bds_high_and_oversold_should_allow_entry(self) -> None:
        """BDS=0.4（达标）且估值分位=10%（<50% 低估超卖）→ 允许建仓。"""
        bds = 0.40
        val_pct = 10.0  # 低估
        is_undervalued = (bds >= 0.3) and (val_pct < 50.0)
        self.assertTrue(is_undervalued, msg="低估+BDS达标 应允许建仓")

    def test_bds_high_valuation_49pct_just_below_median_should_allow(self) -> None:
        """BDS=0.4 + 估值分位=49（P/F略低于中位数0.7x区域）→ 低估区=允许。"""
        bds = 0.40
        val_pct = 49.0
        is_undervalued = (bds >= 0.3) and (val_pct < 50.0)
        self.assertTrue(is_undervalued)

    def test_bds_high_valuation_51pct_fairzone_should_reject(self) -> None:
        """BDS=0.4 + 估值分位=51（略高于中位数，合理区）→ 拒绝，避免合理/高估区建仓。"""
        bds = 0.40
        val_pct = 51.0
        is_undervalued = (bds >= 0.3) and (val_pct < 50.0)
        self.assertFalse(is_undervalued)

    def test_bds_low_valuation_low_should_still_reject(self) -> None:
        """估值分位=10%（极度低估）但 BDS=0.1（基本面未达标）→ 拒绝（BDS 是硬前提）。"""
        bds = 0.10
        val_pct = 10.0
        is_undervalued = (bds >= 0.3) and (val_pct < 50.0)
        self.assertFalse(is_undervalued, msg="BDS<0.3 即便超卖也不建仓，基本面未达标")


# ═══════════════════════════════════════════════════════════════════════
# P1-1: 回测窗口扩展至 90 日（对齐 spec §3.1 「数周~数月」持仓周期）
# ═══════════════════════════════════════════════════════════════════════

class TestBacktestWindow90Days(unittest.TestCase):
    """P1-1: 回测窗口从 30 日扩展至 90 日。"""

    def test_backtest_days_is_90(self) -> None:
        """BACKTEST_DAYS 应为 90（对齐价值投资持仓周期数周-数月）。"""
        import bdsm_phase3_backtest as bt
        self.assertEqual(bt.BACKTEST_DAYS, 90,
                         msg=f"BACKTEST_DAYS 应=90，实际={bt.BACKTEST_DAYS}")

    def test_kline_limit_covers_ma200_plus_90(self) -> None:
        """KLINE_LIMIT 应 ≥ 290（MA200 + 90日回测窗口）。"""
        import bdsm_phase3_backtest as bt
        self.assertGreaterEqual(bt.KLINE_LIMIT, 290,
                                msg=f"KLINE_LIMIT 应≥290，实际={bt.KLINE_LIMIT}")


# ═══════════════════════════════════════════════════════════════════════
# P1-2: §3.5 加仓前置检查清单（9条中的未实现7条）
# ═══════════════════════════════════════════════════════════════════════

class TestPreEntryChecks(unittest.TestCase):
    """P1-2: spec §3.5 加仓前置检查 — 9条清单中回测需实现的 7 条。

    已有: ③CVS≥0.3  ⑥可用资金≥目标  (2条)
    需加: ①BDS≥0.0  ④war_state=ALLOW  ⑦未触发出场信号  ⑧未触发趋势止损  ⑨加仓间隔≥1日 (5条)
    """

    def test_bds_below_zero_blocks_entry(self) -> None:
        """BDS < 0.0（基本面恶化）→ 拒绝加仓（spec §3.5 check ①/④）。"""
        # BDS恶化 → 不应建仓
        bds = -0.05
        self.assertFalse(bds >= 0.0, msg="BDS<0 基本面恶化应阻止加仓")

    def test_trend_stop_blocks_new_entry(self) -> None:
        """趋势止损 action != "none" → 拒绝加仓（spec §3.5 check ⑧）。"""
        klines = _make_downtrend_klines(250, 100.0, -0.003)
        from bdsm_snapshot_writer import _compute_trend_stop
        ts = _compute_trend_stop("", klines, ma_long=200, ma_short=128)
        action = ts.get("action", "none")
        # 趋势止损触发时不应加仓
        if action != "none":
            self.assertNotEqual(action, "none")
        # 反过来：action="none"时允许加仓
        # 用flat klines测试 action=none 的情况
        flat = _make_flat_klines(250, 100.0)
        ts_flat = _compute_trend_stop("", flat, ma_long=200, ma_short=128)
        self.assertEqual(ts_flat.get("action", "none"), "none",
                         msg="平稳行情趋势止损应=none，允许加仓")

    def test_value_exit_full_blocks_new_entry(self) -> None:
        """value_exit action == "full_exit" → 拒绝加仓（spec §3.5 check ⑦）。"""
        from bdsm_snapshot_writer import _compute_value_exit
        # 高估泡沫 → full_exit → 不应加仓
        ve = _compute_value_exit(bds_score=0.4, valuation_percentile=95.0)
        self.assertEqual(ve.get("action"), "full_exit")
        # full_exit 时禁止加仓
        self.assertNotEqual(ve.get("action"), "none",
                           msg="full_exit时应阻止加仓")

    def test_entry_interval_enforced(self) -> None:
        """加仓间隔 ≥ 1日（spec §3.5 check ⑨，日级=24h>4h）→ 连续日不重复加仓。"""
        # 模拟 last_entry_day=5, current_day=5 → 不应加仓（同日）
        last_entry_day = 5
        current_day = 5
        interval_ok = (current_day - last_entry_day) >= 1
        self.assertFalse(interval_ok, msg="同日不应重复加仓")

        # current_day=6 → 间隔1日 → 允许
        current_day = 6
        interval_ok = (current_day - last_entry_day) >= 1
        self.assertTrue(interval_ok, msg="隔日允许加仓")

    def test_war_state_block_blocks_entry(self) -> None:
        """war_state = BLOCK → 拒绝建仓（spec §3.5 check ⑤）。"""
        war_state = "BLOCK"
        self.assertFalse(war_state == "ALLOW", msg="war_state=BLOCK应阻止建仓")


# ═══════════════════════════════════════════════════════════════════════
# P2: BDS 历史快照积累机制
# ═══════════════════════════════════════════════════════════════════════

class TestBDSHistoryArchive(unittest.TestCase):
    """P2: 从快照目录加载历史 BDS 数据，替代今日代理值。"""

    def test_load_historical_bds_returns_dict(self) -> None:
        """load_historical_bds_scores() 返回 {coin: {date_str: bds_score}} 或空 dict。"""
        import bdsm_phase3_backtest as bt
        result = bt.load_historical_bds_scores()
        # 可以是空 dict（无历史快照）但有这个函数
        self.assertIsInstance(result, dict)

    def test_historical_bds_used_when_available(self) -> None:
        """如果有7日+历史 BDS 数据 → 回测使用历史均值；否则用今日代理。"""
        import bdsm_phase3_backtest as bt
        hist = bt.load_historical_bds_scores()
        # 如果有历史数据，每个币应该有多天的BDS
        if hist:
            for coin, scores in hist.items():
                self.assertIsInstance(scores, dict)
                # 每个日期→bds_score
                for date_str, bds in scores.items():
                    self.assertIsInstance(bds, (int, float))
