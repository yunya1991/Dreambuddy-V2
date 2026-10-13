#!/usr/bin/env python3
"""W5 洗盘入场信号回测（Enhanced 多因子版） — 验证外部因子提升后能否作为入场信号。

对比:
  A) volume-only classifier: 缩量→WASHOUT (无法区分真假洗盘)
  B) enhanced classifier: 缩量 + OI下降 + CVD背离 → WASHOUT (能区分真假洗盘)

入场策略: 当 classifier 判定为 WASHOUT 时开多仓，持有 24h/48h。

胜率阈值: ≥60% 可考虑接入入场信号流。

运行: python3 -m pytest tests/test_w5_washout_entry_signal_enhanced.py -v -p no:warnings -s
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector, WashoutLabel, WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_features import WashoutFeatureExtractor  # noqa: E402
from scripts.memory_l4.bcrm2.washout_classifier import EnhancedWashoutClassifier  # noqa: E402


# ============================================================
# Volume-only Classifier (对照组)
# ============================================================
class VolumeOnlyClassifier:
    """A) 仅用 volume_ratio: < 0.8 → WASHOUT, > 1.5 → WEAKNESS."""

    def predict(self, features: Dict[str, float]) -> Optional[WashoutVerdict]:
        vol = features.get("volume_ratio_20d", 1.0)
        if vol < 0.8:
            return WashoutVerdict(
                label=WashoutLabel.WASHOUT, confidence=0.85,
                trigger_activated=True, feature_snapshot=features,
                reason="vol_only_low_volume", timestamp="",
            )
        if vol > 1.5:
            return WashoutVerdict(
                label=WashoutLabel.WEAKNESS, confidence=0.75,
                trigger_activated=True, feature_snapshot=features,
                reason="vol_only_high_volume", timestamp="",
            )
        return WashoutVerdict.unknown()


# ============================================================
# 合成场景: OHLCV + macro_data
# ============================================================
def _make_ohlcv(seed: int, n: int = 298) -> pd.DataFrame:
    """基础 OHLCV (上涨 → 缩量回调)。"""
    rng = np.random.RandomState(seed)
    prices = np.cumprod(1 + rng.normal(0.002, 0.015, n))
    prices = prices * 100 / prices[0]

    ramp_start = 215
    base = float(prices[ramp_start])
    peak_val = base * 1.20
    for i in range(ramp_start, 240):
        frac = (i - ramp_start) / (240 - ramp_start)
        prices[i] = base + (peak_val - base) * frac

    for i in range(240, 250):
        frac = (i - 240) / 10.0
        prices[i] = peak_val * (1 - 0.07 * frac)

    volume = rng.uniform(2000, 4000, n)
    volume[240:250] *= 0.5  # 缩量

    high = prices * 1.005
    low = prices * 0.995

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_true_washout(seed: int) -> Tuple[pd.DataFrame, Dict]:
    """真洗盘: 价格回升 + OI 温和下降 + CVD 与价格背离。"""
    n = 298
    df = _make_ohlcv(seed, n)
    prices = df["close"].values.copy()
    rng = np.random.RandomState(seed + 1)

    # 前向: 价格回升
    recovery_start = prices[249]
    peak_val = prices[239]
    for i in range(250, n):
        target = peak_val * rng.uniform(0.95, 1.0)
        frac = (i - 250) / (n - 250)
        prices[i] = recovery_start + (target - recovery_start) * frac
        prices[i] *= (1 + rng.normal(0, 0.005))
    df["close"] = prices
    df["open"] = prices
    df["high"] = prices * 1.005
    df["low"] = prices * 0.995

    # macro_data: 真洗盘
    oi_base = 1e8
    oi_series = np.ones(n) * oi_base
    for i in range(240, 250):
        oi_series[i] = oi_base * (1 - 0.003 * (i - 240))
    for i in range(250, n):
        oi_series[i] = oi_base * 0.97 + rng.normal(0, oi_base * 0.001)

    # CVD 与价格背离 (负相关)
    cvd_series = 1e6 - prices * 5000 + rng.normal(0, 5000, n)
    cvd_series = np.maximum(cvd_series, 0)

    # funding 暂时偏负
    funding_series = np.ones(n) * 0.0001
    funding_series[240:250] = -0.0003 + rng.normal(0, 0.00005, 10)
    funding_series[250:] = 0.0001 + rng.normal(0, 0.00005, n - 250)

    return df, {
        "oi_series": oi_series.tolist(),
        "cvd_series": cvd_series.tolist(),
        "funding_rate_series": funding_series.tolist(),
    }


def _make_false_washout(seed: int) -> Tuple[pd.DataFrame, Dict]:
    """假洗盘: 价格继续下跌 + OI 上升 + CVD 与价格同步。"""
    n = 298
    df = _make_ohlcv(seed, n)
    prices = df["close"].values.copy()
    rng = np.random.RandomState(seed + 2)

    # 前向: 价格继续下跌
    decline_start = prices[249]
    for i in range(250, n):
        decline_target = decline_start * 0.85
        frac = (i - 250) / (n - 250)
        prices[i] = decline_start + (decline_target - decline_start) * frac
        prices[i] *= (1 + rng.normal(0, 0.005))
    df["close"] = prices
    df["open"] = prices
    df["high"] = prices * 1.005
    df["low"] = prices * 0.995

    # macro_data: 假洗盘
    oi_base = 1e8
    oi_series = np.ones(n) * oi_base
    for i in range(240, n):
        oi_series[i] = oi_base * (1 + 0.008 * (i - 240))

    # CVD 与价格同步下行 (正相关)
    cvd_series = 1e6 + prices * 5000 + rng.normal(0, 5000, n)

    # funding 深度负值
    funding_series = np.ones(n) * 0.0001
    funding_series[240:] = -0.0008 + rng.normal(0, 0.0001, n - 240)

    return df, {
        "oi_series": oi_series.tolist(),
        "cvd_series": cvd_series.tolist(),
        "funding_rate_series": funding_series.tolist(),
    }


# ============================================================
# 入场信号回测引擎
# ============================================================
def run_entry_backtest(
    scenarios: List[Tuple[pd.DataFrame, Dict]],
    classifier,
    horizons: List[int] = None,
) -> Dict:
    """以 classifier 判定为 WASHOUT 作为入场信号，回测胜率。

    入场: verdict.label == WASHOUT → 开多仓
    持有: horizon 小时后平仓
    收益: (future_price / entry_price - 1.0)
    """
    if horizons is None:
        horizons = [24, 48]

    ext = WashoutFeatureExtractor()
    detector = WashoutDetector(
        enable=True, classifier=classifier, feature_extractor=ext
    )

    entries = []
    for df, macro_data in scenarios:
        detection_df = df.iloc[:250]
        detection_macro = {
            k: v[:250] if isinstance(v, list) else v for k, v in macro_data.items()
        }
        verdict = detector.run("BTC", detection_df, detection_macro)

        if verdict.label == WashoutLabel.WASHOUT:
            entry_price = float(df["close"].iloc[249])
            forward_returns = {}
            for h in horizons:
                idx = 249 + h
                if idx < len(df):
                    future_price = float(df["close"].iloc[idx])
                    forward_returns[f"{h}h"] = future_price / entry_price - 1.0
            entries.append(forward_returns)

    n_entries = len(entries)
    if n_entries == 0:
        return {
            "n_entries": 0, "wins_24h": 0, "win_rate_24h": 0.0,
            "avg_return_24h": 0.0, "wins_48h": 0, "win_rate_48h": 0.0,
            "avg_return_48h": 0.0,
        }

    rets_24h = [e.get("24h", 0.0) for e in entries]
    rets_48h = [e.get("48h", 0.0) for e in entries]

    wins_24h = sum(1 for r in rets_24h if r > 0)
    wins_48h = sum(1 for r in rets_48h if r > 0)

    return {
        "n_entries": n_entries,
        "wins_24h": wins_24h,
        "win_rate_24h": wins_24h / n_entries,
        "avg_return_24h": float(np.mean(rets_24h)),
        "wins_48h": wins_48h,
        "win_rate_48h": wins_48h / n_entries,
        "avg_return_48h": float(np.mean(rets_48h)),
        "max_return": float(max(rets_24h)),
        "min_return": float(min(rets_24h)),
    }


# ============================================================
# 回测用例
# ============================================================
class TestWashoutEntrySignalEnhanced(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        n = 20
        true_scenarios = [_make_true_washout(1000 + i) for i in range(n)]
        false_scenarios = [_make_false_washout(2000 + i) for i in range(n)]
        cls.all_scenarios = true_scenarios + false_scenarios
        cls.ext = WashoutFeatureExtractor()

    def test_volume_only_entry_signal(self):
        """A) volume-only: 缩量都判为 WASHOUT → 假洗盘大量入场 → 低胜率。"""
        results = run_entry_backtest(
            self.all_scenarios, VolumeOnlyClassifier()
        )
        print(f"\n[A) volume-only 入场信号]")
        print(f"  入场次数: {results['n_entries']}/40")
        print(f"  24h 胜率: {results['win_rate_24h']:.1%} "
              f"({results['wins_24h']}/{results['n_entries']})")
        print(f"  24h 平均收益: {results['avg_return_24h']:.4f}")
        print(f"  48h 胜率: {results['win_rate_48h']:.1%}")
        print(f"  48h 平均收益: {results['avg_return_48h']:.4f}")

        # volume-only 胜率应 < 60% (假洗盘拖累)
        self.assertLess(results["win_rate_24h"], 0.60,
                        f"volume-only 24h 胜率 {results['win_rate_24h']:.1%} < 60%")

    def test_enhanced_entry_signal(self):
        """B) enhanced: OI+CVD 区分真假洗盘 → 高胜率。"""
        results = run_entry_backtest(
            self.all_scenarios, EnhancedWashoutClassifier()
        )
        print(f"\n[B) enhanced 入场信号]")
        print(f"  入场次数: {results['n_entries']}/40")
        print(f"  24h 胜率: {results['win_rate_24h']:.1%} "
              f"({results['wins_24h']}/{results['n_entries']})")
        print(f"  24h 平均收益: {results['avg_return_24h']:.4f}")
        print(f"  48h 胜率: {results['win_rate_48h']:.1%}")
        print(f"  48h 平均收益: {results['avg_return_48h']:.4f}")
        print(f"  最大单笔收益: {results['max_return']:.4f}")
        print(f"  最大单笔亏损: {results['min_return']:.4f}")

        # enhanced 胜率应 ≥ 60% (只有真洗盘入场)
        self.assertGreaterEqual(results["win_rate_24h"], 0.60,
                                f"enhanced 24h 胜率 {results['win_rate_24h']:.1%} ≥ 60%")

    def test_enhanced_beats_volume_only(self):
        """对比: enhanced 胜率比 volume-only 提升 > 20%。"""
        vol = run_entry_backtest(self.all_scenarios, VolumeOnlyClassifier())
        enh = run_entry_backtest(self.all_scenarios, EnhancedWashoutClassifier())

        improvement = enh["win_rate_24h"] - vol["win_rate_24h"]
        print(f"\n[胜率提升对比]")
        print(f"  volume-only 24h 胜率: {vol['win_rate_24h']:.1%} "
              f"({vol['wins_24h']}/{vol['n_entries']})")
        print(f"  enhanced    24h 胜率: {enh['win_rate_24h']:.1%} "
              f"({enh['wins_24h']}/{enh['n_entries']})")
        print(f"  提升: {improvement:+.1%}")

        self.assertGreater(improvement, 0.20,
                           "enhanced 应比 volume-only 胜率提升 > 20%")

    def test_entry_signal_accuracy_meets_threshold(self):
        """最终判定: enhanced 24h 胜率 ≥ 60% 且平均收益 > 0。"""
        results = run_entry_backtest(
            self.all_scenarios, EnhancedWashoutClassifier()
        )
        meets_win_rate = results["win_rate_24h"] >= 0.60
        meets_avg_return = results["avg_return_24h"] > 0.0

        print(f"\n{'='*60}")
        print(f"[入场信号可采用性判定]")
        print(f"  24h 胜率: {results['win_rate_24h']:.1%} "
              f"{'✅ ≥60%' if meets_win_rate else '❌ <60%'}")
        print(f"  24h 平均收益: {results['avg_return_24h']:.4f} "
              f"{'✅ >0' if meets_avg_return else '❌ ≤0'}")
        print(f"  入场次数: {results['n_entries']}")
        print(f"  结论: {'✅ 可接入入场信号流' if meets_win_rate and meets_avg_return else '❌ 不宜作为入场信号'}")
        print(f"{'='*60}")

        if meets_win_rate and meets_avg_return:
            self.assertTrue(True, "enhanced 入场信号达标")
        else:
            self.fail(
                f"入场信号不达标: 胜率={results['win_rate_24h']:.1%}, "
                f"平均收益={results['avg_return_24h']:.4f}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
