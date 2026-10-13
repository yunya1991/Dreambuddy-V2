#!/usr/bin/env python3
"""W5 洗盘三层防御回测脚本 — 验证准确性。

回测维度:
  1. WashoutTriggerGate 准确性: 4 场景（washout/无涨幅/无回撤/低于MA200）
  2. WashoutFeatureExtractor 准确性: washout pattern vs weakness pattern 特征差异
  3. WashoutHoldStrategy 准确性: 5 种 label×confidence 组合的 action
  4. P3EarlyExit washout 抑制准确性: conf≥0.80 抑制 / conf<0.80 不抑制 / WEAKNESS 不抑制
  5. TrailingStopStrategy peak ratchet 准确性: arm/break_even/pass 三档
  6. FAIL-OPEN 安全性: enable=False / detector=None / 异常
  7. 全链路集成: ExitManager 链序 P3(10)→WashoutHold(15)→TrailingStop(70)

运行: python3 -m pytest tests/backtest_w5_washout.py -v -p no:warnings
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector, WashoutLabel, WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_trigger_gate import WashoutTriggerGate  # noqa: E402
from scripts.memory_l4.bcrm2.washout_features import WashoutFeatureExtractor  # noqa: E402
from scripts.memory_l4.bcrm2.exit_strategies import (  # noqa: E402
    P3EarlyExitStrategy, WashoutHoldStrategy, TrailingStopStrategy,
)
from scripts.memory_l4.bcrm2.exit_manager import ExitContext, ExitDecision  # noqa: E402


# ============================================================
# 合成数据工厂
# ============================================================
def _make_ohlcv(
    n_days: int = 250,
    start_price: float = 100.0,
    trend: float = 0.001,
    volatility: float = 0.02,
    pullback_pct: float = 0.0,
    pullback_start: int = -10,
    seed: int = 42,
) -> pd.DataFrame:
    """生成合成 OHLCV 日线数据。

    Args:
        n_days: 总天数（默认 250 确保 MA200 可算）
        start_price: 起始价格
        trend: 每日漂移（正=上涨趋势）
        volatility: 日波动率
        pullback_pct: 回撤比例（从 peak 回撤 pullback_pct）
        pullback_start: 回撤开始位置（负索引，-10=最后10天回撤）
        seed: 随机种子
    """
    rng = np.random.RandomState(seed)
    returns = rng.normal(trend, volatility, n_days)
    prices = [start_price]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    prices = np.array(prices[1:])

    # 应用回撤
    if pullback_pct > 0 and pullback_start < 0:
        peak_idx = n_days + pullback_start
        peak = prices[peak_idx] * (1 + abs(pullback_pct) * 0.5)
        # 在 peak 之后逐步回撤
        for i in range(peak_idx, n_days):
            frac = (i - peak_idx) / max(1, n_days - peak_idx)
            prices[i] = peak * (1 - pullback_pct * frac)

    high = prices * (1 + rng.uniform(0.001, 0.01, n_days))
    low = prices * (1 - rng.uniform(0.001, 0.01, n_days))
    volume = rng.uniform(1000, 5000, n_days)

    dates = pd.date_range("2025-01-01", periods=n_days, freq="1h")
    return pd.DataFrame({
        "open": prices,
        "high": high,
        "low": low,
        "close": prices,
        "volume": volume,
    }, index=dates)


def _make_washout_pattern() -> pd.DataFrame:
    """洗盘 pattern: 上涨后回调，缩量回调，支撑守住，价格在 MA200 之上。

    特征期望:
      - trigger_gate.should_activate = True（runup≥15%, drawdown≥5%, above MA200）
      - volume_ratio_20d < 0.8（缩量）
      - support_holds_count >= 1
    """
    n = 250
    rng = np.random.RandomState(123)
    # 前 220 天温和上涨（构建 MA200 基础）
    prices = np.cumprod(1 + rng.normal(0.002, 0.015, n))
    prices = prices * 100 / prices[0]

    # 最后 35 天: 从 prices[215] 基础上涨 20% 到 peak，再回撤 7%
    ramp_start = n - 35  # index 215
    base = float(prices[ramp_start])
    peak_val = base * 1.20  # 20% 涨幅确保 runup > 15%
    # ramp up: 215→230 线性涨到 peak
    for i in range(ramp_start, n - 10):
        frac = (i - ramp_start) / (n - 10 - ramp_start)
        prices[i] = base + (peak_val - base) * frac
    # pullback 7%: 最后 10 天从 peak 回撤
    for i in range(n - 10, n):
        frac = (i - (n - 10)) / 10.0
        prices[i] = peak_val * (1 - 0.07 * frac)

    # 缩量: 最后 10 天 volume 减半
    volume = rng.uniform(2000, 4000, n)
    volume[-10:] *= 0.5

    high = prices * 1.005
    low = prices * 0.995
    # swing low 守住: 制造两个递高的 swing low（回调中支撑守住）
    # swing 1: index n-20 处低点
    low[n - 20] = prices[n - 20] * 0.985
    low[n - 19] = prices[n - 19] * 0.988
    low[n - 18] = prices[n - 18] * 0.990
    # swing 2: index n-10 处更高低点
    low[n - 10] = prices[n - 10] * 0.990  # 比 swing 1 高
    low[n - 9] = prices[n - 9] * 0.992
    low[n - 8] = prices[n - 8] * 0.994

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_weakness_pattern() -> pd.DataFrame:
    """真弱势 pattern: 上涨后回调，放量下破，支撑破位。

    特征期望:
      - trigger_gate.should_activate = True（仍满足触发条件）
      - volume_ratio_20d > 1.5（放量）
      - support_holds_count = 0（破支撑）
    """
    n = 250
    rng = np.random.RandomState(456)
    prices = np.cumprod(1 + rng.normal(0.002, 0.015, n))
    prices = prices * 100 / prices[0]

    # 最后 35 天: 涨 20% 后放量下破 10%
    ramp_start = n - 35
    base = float(prices[ramp_start])
    peak_val = base * 1.22
    for i in range(ramp_start, n - 10):
        frac = (i - ramp_start) / (n - 10 - ramp_start)
        prices[i] = base + (peak_val - base) * frac
    # 放量下破 10%
    for i in range(n - 10, n):
        frac = (i - (n - 10)) / 10.0
        prices[i] = peak_val * (1 - 0.10 * frac)

    # 放量: 最后 10 天 volume 翻倍
    volume = rng.uniform(2000, 4000, n)
    volume[-10:] *= 2.0

    high = prices * 1.005
    low = prices * 0.995
    # 支撑破位: low 逐步走低
    for i in range(n - 8, n):
        low[i] = low[i] * 0.998

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_no_trigger_pattern() -> pd.DataFrame:
    """无触发 pattern: 震荡，无 15% 涨幅，不满足触发条件。"""
    n = 250
    rng = np.random.RandomState(789)
    # 纯震荡，无趋势
    prices = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = prices * 1.005
    low = prices * 0.995
    volume = rng.uniform(2000, 4000, n)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_below_ma200_pattern() -> pd.DataFrame:
    """低于 MA200 pattern: 有涨幅有回撤但价格在 MA200 之下。"""
    n = 250
    rng = np.random.RandomState(321)
    # 前 100 天大涨，后 150 天持续下跌到 MA200 之下
    prices = np.zeros(n)
    prices[:100] = np.cumprod(1 + rng.normal(0.005, 0.01, 100)) * 100
    prices[100:] = prices[99] * np.cumprod(1 + rng.normal(-0.003, 0.01, 150))
    high = prices * 1.005
    low = prices * 0.995
    volume = rng.uniform(2000, 4000, n)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


# ============================================================
# Mock Classifier — 根据特征映射 WASHOUT / WEAKNESS
# ============================================================
class MockWashoutClassifier:
    """根据特征模拟分类器判定。

    判定规则（模拟 W4 KNN/Bayesian）:
      - volume_ratio_20d < 0.8（缩量回调） → WASHOUT (conf=0.85)
      - volume_ratio_20d > 1.5（放量下破） → WEAKNESS (conf=0.75)
      - 其他 → UNKNOWN (conf=0.0)
    """

    def predict(self, features: Dict[str, float]) -> Optional[WashoutVerdict]:
        vol_ratio = features.get("volume_ratio_20d", 1.0)

        if vol_ratio < 0.8:
            return WashoutVerdict(
                label=WashoutLabel.WASHOUT,
                confidence=0.85,
                trigger_activated=True,
                feature_snapshot=features,
                reason="mock_washout_low_volume_pullback",
                timestamp="",
            )
        if vol_ratio > 1.5:
            return WashoutVerdict(
                label=WashoutLabel.WEAKNESS,
                confidence=0.75,
                trigger_activated=True,
                feature_snapshot=features,
                reason="mock_weakness_high_volume_breakdown",
                timestamp="",
            )
        return WashoutVerdict.unknown()


def _make_ctx(
    coin: str = "BTC",
    inference: Optional[Dict] = None,
    pos_info: Optional[Dict] = None,
    in_protection: bool = False,
    age_hours: float = 10.0,
) -> ExitContext:
    """构造 ExitContext。"""
    return ExitContext(
        coin=coin,
        inference=inference or {},
        pos_info=pos_info or {},
        tracker_pos=None,
        in_protection=in_protection,
        age_hours=age_hours,
    )


# ============================================================
# 回测用例
# ============================================================
class TestWashoutTriggerGateAccuracy(unittest.TestCase):
    """回测 1: Trigger Gate 准确性 — 4 场景。"""

    def test_washout_pattern_triggers(self):
        df = _make_washout_pattern()
        gate = WashoutTriggerGate()
        self.assertTrue(gate.should_activate(df),
                        "洗盘 pattern 应满足触发条件")

    def test_no_runup_does_not_trigger(self):
        df = _make_no_trigger_pattern()
        gate = WashoutTriggerGate()
        self.assertFalse(gate.should_activate(df),
                         "无涨幅 pattern 不应触发")

    def test_below_ma200_does_not_trigger(self):
        df = _make_below_ma200_pattern()
        gate = WashoutTriggerGate()
        self.assertFalse(gate.should_activate(df),
                         "低于 MA200 不应触发")

    def test_insufficient_data_does_not_trigger(self):
        df = _make_washout_pattern().iloc[:20]
        gate = WashoutTriggerGate()
        self.assertFalse(gate.should_activate(df),
                         "数据不足不应触发")


class TestWashoutFeatureExtractorAccuracy(unittest.TestCase):
    """回测 2: 特征提取准确性 — washout vs weakness 特征差异。"""

    def test_washout_pattern_features(self):
        df = _make_washout_pattern()
        macro = {"oi_series": None, "btc_close": None}
        ext = WashoutFeatureExtractor()
        feats = ext.extract_all(df, macro)

        # 洗盘 pattern: 缩量
        self.assertLess(
            feats.get("volume_ratio_20d", 1.0), 0.8,
            f"洗盘 pattern volume_ratio 应 < 0.8, 实际={feats.get('volume_ratio_20d')}"
        )
        # 振幅特征存在
        self.assertIn("atr_compress_ratio", feats)
        # 区间位置存在
        self.assertIn("cycle_position_365d", feats)

    def test_weakness_pattern_features(self):
        df = _make_weakness_pattern()
        macro = {"oi_series": None, "btc_close": None}
        ext = WashoutFeatureExtractor()
        feats = ext.extract_all(df, macro)

        # 真弱势 pattern: 放量
        self.assertGreater(
            feats.get("volume_ratio_20d", 1.0), 1.5,
            f"真弱势 pattern volume_ratio 应 > 1.5, 实际={feats.get('volume_ratio_20d')}"
        )

    def test_feature_extraction_fail_open_on_none(self):
        ext = WashoutFeatureExtractor()
        feats = ext.extract_all(None, None)
        self.assertEqual(feats, {},
                         "None 输入应返回空 dict（FAIL-OPEN）")

    def test_all_13_features_present(self):
        """所有 13 维特征在正常数据下都应该出现。"""
        df = _make_washout_pattern()
        macro = {"oi_series": None, "btc_close": None}
        ext = WashoutFeatureExtractor()
        feats = ext.extract_all(df, macro)
        expected_keys = {
            "volume_ratio_20d", "support_holds_count", "atr_compress_ratio",
            "oi_change_rate_7d", "cycle_position_365d", "rebound_ratio_5d",
            "news_negative_score", "btc_correlation_30d",
            "oi_price_quadrant", "funding_rate_zscore",
            "cvd_price_divergence", "ofi_std_20d",
            "wyckoff_climax_stage",
        }
        self.assertEqual(set(feats.keys()), expected_keys,
                         f"特征 key 不匹配: 缺={expected_keys - set(feats.keys())}")


class TestWashoutDetectorAccuracy(unittest.TestCase):
    """回测 3: WashoutDetector 端到端准确性。"""

    def test_disabled_returns_unknown(self):
        det = WashoutDetector(enable=False)
        df = _make_washout_pattern()
        v = det.run("BTC", df, {})
        self.assertEqual(v.label, WashoutLabel.UNKNOWN)
        self.assertFalse(v.trigger_activated)

    def test_washout_pattern_detected_as_washout(self):
        """注入 mock classifier → washout pattern 判定为 WASHOUT。"""
        ext = WashoutFeatureExtractor()
        clf = MockWashoutClassifier()
        det = WashoutDetector(
            enable=True, classifier=clf, feature_extractor=ext
        )
        df = _make_washout_pattern()
        v = det.run("BTC", df, {})
        self.assertEqual(v.label, WashoutLabel.WASHOUT,
                         f"washout pattern 应判定为 WASHOUT, 实际={v.label}")
        self.assertGreaterEqual(v.confidence, 0.80,
                                f"WASHOUT 置信度应 >= 0.80, 实际={v.confidence}")
        self.assertTrue(v.trigger_activated)

    def test_weakness_pattern_detected_as_weakness(self):
        """注入 mock classifier → weakness pattern 判定为 WEAKNESS。"""
        ext = WashoutFeatureExtractor()
        clf = MockWashoutClassifier()
        det = WashoutDetector(
            enable=True, classifier=clf, feature_extractor=ext
        )
        df = _make_weakness_pattern()
        v = det.run("BTC", df, {})
        self.assertEqual(v.label, WashoutLabel.WEAKNESS,
                         f"weakness pattern 应判定为 WEAKNESS, 实际={v.label}")
        self.assertGreaterEqual(v.confidence, 0.70)

    def test_no_trigger_returns_unknown(self):
        """无触发 pattern → trigger_activated=False。"""
        ext = WashoutFeatureExtractor()
        clf = MockWashoutClassifier()
        det = WashoutDetector(
            enable=True, classifier=clf, feature_extractor=ext
        )
        df = _make_no_trigger_pattern()
        v = det.run("BTC", df, {})
        self.assertEqual(v.label, WashoutLabel.UNKNOWN)
        self.assertFalse(v.trigger_activated)

    def test_exception_returns_unknown(self):
        """异常输入 → FAIL-OPEN 返回 unknown。"""
        det = WashoutDetector(enable=True)
        v = det.run("BTC", "not_a_dataframe", {})
        self.assertEqual(v.label, WashoutLabel.UNKNOWN)
        self.assertFalse(v.trigger_activated)


class TestWashoutHoldStrategyAccuracy(unittest.TestCase):
    """回测 4: WashoutHoldStrategy 三分支准确性。"""

    def _make_det_with_verdict(self, verdict: WashoutVerdict):
        """构造一个 run() 始终返回指定 verdict 的 detector。"""
        det = MagicMock()
        det.run = MagicMock(return_value=verdict)
        return det

    def test_washout_label_returns_hold(self):
        v = WashoutVerdict(
            label=WashoutLabel.WASHOUT, confidence=0.85,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        strat = WashoutHoldStrategy(washout_detector=self._make_det_with_verdict(v))
        ctx = _make_ctx(age_hours=10)
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "hold")
        self.assertIn("washout", d.reason)

    def test_weakness_high_conf_returns_force_close(self):
        v = WashoutVerdict(
            label=WashoutLabel.WEAKNESS, confidence=0.75,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        strat = WashoutHoldStrategy(washout_detector=self._make_det_with_verdict(v))
        ctx = _make_ctx()
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "force_close")
        self.assertIn("weakness", d.reason)

    def test_weakness_low_conf_returns_pass(self):
        v = WashoutVerdict(
            label=WashoutLabel.WEAKNESS, confidence=0.65,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        strat = WashoutHoldStrategy(washout_detector=self._make_det_with_verdict(v))
        ctx = _make_ctx()
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "pass")

    def test_unknown_returns_pass(self):
        strat = WashoutHoldStrategy(
            washout_detector=self._make_det_with_verdict(WashoutVerdict.unknown())
        )
        ctx = _make_ctx()
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "pass")

    def test_none_detector_returns_pass(self):
        """detector=None → pass（开关关断字节等价）。"""
        strat = WashoutHoldStrategy(washout_detector=None)
        ctx = _make_ctx()
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "pass")

    def test_washout_timeout_48h_still_hold(self):
        """超过 48h 的 washout hold → 仍 hold（但 reason 标记 timeout）。"""
        v = WashoutVerdict(
            label=WashoutLabel.WASHOUT, confidence=0.85,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        strat = WashoutHoldStrategy(washout_detector=self._make_det_with_verdict(v))
        ctx = _make_ctx(age_hours=50.0)
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "hold")
        self.assertIn("timeout", d.reason)


class TestP3EarlyExitWashoutSuppression(unittest.TestCase):
    """回测 5: P3EarlyExit washout 抑制准确性。"""

    def _make_ctx_with_p3_signal(self, upl: float = -0.10) -> ExitContext:
        return _make_ctx(
            inference={"early_exit_signal": True},
            pos_info={"upl_ratio": upl},
            in_protection=True,
        )

    def test_washout_high_conf_suppresses_p3_exit(self):
        """WASHOUT + conf≥0.80 → 抑制 P3 退出（返回 hold）。"""
        v = WashoutVerdict(
            label=WashoutLabel.WASHOUT, confidence=0.85,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        det = MagicMock()
        det.run = MagicMock(return_value=v)
        strat = P3EarlyExitStrategy(
            exit_confirm_required=2,
            washout_detector=det,
        )
        ctx = self._make_ctx_with_p3_signal()
        # 触发 2 次以通过确认
        d1 = strat.evaluate(ctx)
        d2 = strat.evaluate(ctx)
        self.assertEqual(d2.action, "hold")
        self.assertIn("suppressed_by_washout", d2.reason)

    def test_washout_low_conf_does_not_suppress(self):
        """WASHOUT + conf<0.80 → 不抑制（走原 P3 force_close）。"""
        v = WashoutVerdict(
            label=WashoutLabel.WASHOUT, confidence=0.75,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        det = MagicMock()
        det.run = MagicMock(return_value=v)
        strat = P3EarlyExitStrategy(
            exit_confirm_required=2,
            washout_detector=det,
        )
        ctx = self._make_ctx_with_p3_signal()
        strat.evaluate(ctx)  # confirm 1
        d = strat.evaluate(ctx)  # confirm 2 → force_close
        self.assertEqual(d.action, "force_close")

    def test_weakness_does_not_suppress_p3(self):
        """WEAKNESS → 不抑制 P3（force_close）。"""
        v = WashoutVerdict(
            label=WashoutLabel.WEAKNESS, confidence=0.90,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        det = MagicMock()
        det.run = MagicMock(return_value=v)
        strat = P3EarlyExitStrategy(
            exit_confirm_required=2,
            washout_detector=det,
        )
        ctx = self._make_ctx_with_p3_signal()
        strat.evaluate(ctx)
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "force_close")

    def test_none_detector_uses_original_p3(self):
        """detector=None → 走原 P3 逻辑。"""
        strat = P3EarlyExitStrategy(
            exit_confirm_required=2, washout_detector=None
        )
        ctx = self._make_ctx_with_p3_signal()
        strat.evaluate(ctx)
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "force_close")


class TestTrailingStopStrategyAccuracy(unittest.TestCase):
    """回测 6: TrailingStop peak ratchet 准确性。"""

    def test_loss_returns_pass(self):
        strat = TrailingStopStrategy()
        ctx = _make_ctx(pos_info={"upl_ratio": -0.02})
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "pass")

    def test_small_profit_below_break_even_returns_pass(self):
        strat = TrailingStopStrategy(break_even_pct=0.02)
        ctx = _make_ctx(pos_info={"upl_ratio": 0.01})
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "pass")

    def test_profit_at_break_even_returns_adjust(self):
        strat = TrailingStopStrategy(break_even_pct=0.02)
        ctx = _make_ctx(pos_info={"upl_ratio": 0.025})
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "adjust_sl_tp")
        self.assertIn("break_even", d.reason)

    def test_profit_at_trailing_arm_returns_trailing(self):
        strat = TrailingStopStrategy(trailing_arm_pct=0.04)
        ctx = _make_ctx(pos_info={"upl_ratio": 0.05})
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "adjust_sl_tp")
        self.assertIn("trailing", d.reason)

    def test_peak_ratchet_only_goes_up(self):
        """peak 只升不降：先涨到 5%，再跌到 3%，peak 仍为 5%。"""
        strat = TrailingStopStrategy(trailing_arm_pct=0.04)
        # 第一次 upl=5% → peak=5%, trailing 模式
        ctx1 = _make_ctx(pos_info={"upl_ratio": 0.05})
        d1 = strat.evaluate(ctx1)
        self.assertEqual(d1.action, "adjust_sl_tp")
        self.assertEqual(d1.params["peak"], 0.05)
        # 第二次 upl=3% → peak 仍 5%，仍 trailing
        ctx2 = _make_ctx(pos_info={"upl_ratio": 0.03})
        d2 = strat.evaluate(ctx2)
        self.assertEqual(d2.action, "adjust_sl_tp")
        self.assertEqual(d2.params["peak"], 0.05,
                         "peak 应保持 5%（只升不降）")

    def test_reset_peak_after_close(self):
        """平仓后 reset_peak → 下次开仓不继承旧 peak。"""
        strat = TrailingStopStrategy(trailing_arm_pct=0.04)
        ctx1 = _make_ctx(coin="BTC", pos_info={"upl_ratio": 0.05})
        strat.evaluate(ctx1)
        self.assertEqual(strat._peak_upl["BTC"], 0.05)
        strat.reset_peak("BTC")
        self.assertNotIn("BTC", strat._peak_upl)

    def test_per_coin_isolation(self):
        """per-coin peak 隔离：BTC peak 不影响 ETH。"""
        strat = TrailingStopStrategy(trailing_arm_pct=0.04)
        ctx_btc = _make_ctx(coin="BTC", pos_info={"upl_ratio": 0.06})
        strat.evaluate(ctx_btc)
        ctx_eth = _make_ctx(coin="ETH", pos_info={"upl_ratio": 0.01})
        d_eth = strat.evaluate(ctx_eth)
        # ETH upl=1% < break_even → pass
        self.assertEqual(d_eth.action, "pass")
        self.assertEqual(strat._peak_upl["BTC"], 0.06)
        self.assertEqual(strat._peak_upl["ETH"], 0.01)


class TestFailOpenSafety(unittest.TestCase):
    """回测 7: FAIL-OPEN 安全性。"""

    def test_detector_disabled_returns_unknown(self):
        det = WashoutDetector(enable=False)
        v = det.run("BTC", _make_washout_pattern(), {})
        self.assertFalse(v.trigger_activated)
        self.assertEqual(v.label, WashoutLabel.UNKNOWN)

    def test_washout_hold_detector_none_passes(self):
        strat = WashoutHoldStrategy(washout_detector=None)
        d = strat.evaluate(_make_ctx())
        self.assertEqual(d.action, "pass")

    def test_washout_hold_exception_passes(self):
        det = MagicMock()
        det.run = MagicMock(side_effect=RuntimeError("boom"))
        strat = WashoutHoldStrategy(washout_detector=det)
        d = strat.evaluate(_make_ctx())
        self.assertEqual(d.action, "pass")

    def test_p3_exception_uses_original_logic(self):
        det = MagicMock()
        det.run = MagicMock(side_effect=RuntimeError("boom"))
        strat = P3EarlyExitStrategy(
            exit_confirm_required=2, washout_detector=det
        )
        ctx = _make_ctx(
            inference={"early_exit_signal": True},
            pos_info={"upl_ratio": -0.10},
            in_protection=True,
        )
        strat.evaluate(ctx)
        d = strat.evaluate(ctx)
        self.assertEqual(d.action, "force_close")

    def test_trigger_gate_exception_returns_false(self):
        gate = WashoutTriggerGate()
        self.assertFalse(gate.should_activate(None))
        self.assertFalse(gate.should_activate("not_df"))


class TestFullChainIntegration(unittest.TestCase):
    """回测 8: 全链路集成 — P3(10) → WashoutHold(15) → TrailingStop(70)。"""

    def _build_chain(
        self,
        washout_det: Optional[object] = None,
    ) -> List:
        """构建与 polling_trader 一致的策略链。"""
        return [
            P3EarlyExitStrategy(exit_confirm_required=2, washout_detector=washout_det),
            WashoutHoldStrategy(washout_detector=washout_det),
            TrailingStopStrategy(),
        ]

    def test_washout_suppresses_p3_and_hold(self):
        """全链路: WASHOUT+conf≥0.80 → P3 被抑制 → WashoutHold hold。"""
        v = WashoutVerdict(
            label=WashoutLabel.WASHOUT, confidence=0.85,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        det = MagicMock()
        det.run = MagicMock(return_value=v)
        chain = self._build_chain(washout_det=det)

        ctx = _make_ctx(
            inference={"early_exit_signal": True},
            pos_info={"upl_ratio": -0.10},
            in_protection=True,
        )
        # P3 第一次：confirm 1
        d = chain[0].evaluate(ctx)
        self.assertEqual(d.action, "hold")
        self.assertIn("pending", d.reason)
        # P3 第二次：confirm 2 → 应被 washout 抑制
        d = chain[0].evaluate(ctx)
        self.assertEqual(d.action, "hold")
        self.assertIn("suppressed_by_washout", d.reason)

        # WashoutHold → hold
        d = chain[1].evaluate(ctx)
        self.assertEqual(d.action, "hold")

    def test_weakness_triggers_force_close_in_chain(self):
        """全链路: WEAKNESS+conf≥0.70 → WashoutHold force_close。"""
        v = WashoutVerdict(
            label=WashoutLabel.WEAKNESS, confidence=0.75,
            trigger_activated=True, feature_snapshot={},
            reason="test", timestamp="",
        )
        det = MagicMock()
        det.run = MagicMock(return_value=v)
        chain = self._build_chain(washout_det=det)

        ctx = _make_ctx(pos_info={"upl_ratio": 0.01})
        # P3 无信号 → pass
        d = chain[0].evaluate(ctx)
        self.assertEqual(d.action, "pass")
        # WashoutHold → force_close
        d = chain[1].evaluate(ctx)
        self.assertEqual(d.action, "force_close")

    def test_trailing_stop_in_chain_when_profit(self):
        """全链路: 无 washout 信号 + 盈利 → TrailingStop adjust_sl_tp。"""
        chain = self._build_chain(washout_det=None)
        ctx = _make_ctx(pos_info={"upl_ratio": 0.05})
        # P3 pass
        self.assertEqual(chain[0].evaluate(ctx).action, "pass")
        # WashoutHold pass (detector=None)
        self.assertEqual(chain[1].evaluate(ctx).action, "pass")
        # TrailingStop → trailing
        d = chain[2].evaluate(ctx)
        self.assertEqual(d.action, "adjust_sl_tp")
        self.assertIn("trailing", d.reason)

    def test_disabled_chain_full_pass(self):
        """开关关断时全链路 pass（字节等价）。"""
        chain = self._build_chain(washout_det=None)
        ctx = _make_ctx(pos_info={"upl_ratio": -0.01})
        for s in chain:
            d = s.evaluate(ctx)
            self.assertEqual(d.action, "pass",
                             f"{s.name} 应返回 pass, 实际={d.action}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
