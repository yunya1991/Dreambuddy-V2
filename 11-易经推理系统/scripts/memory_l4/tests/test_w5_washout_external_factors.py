#!/usr/bin/env python3
"""W5 洗盘外部因子增强回测 — 验证加入 OI/funding/CVD 后防御准确率提升。

核心假设:
  真假洗盘在价格+成交量特征上无法区分（上一轮回测已证明），
  但链上/衍生品指标有本质差异:
    真洗盘: OI 温和下降（弱手离场，聪明钱吸收）+ funding 暂时偏负 + CVD 与价格背离
    假洗盘: OI 上升（新空头涌入）+ funding 深度负值 + CVD 与价格同步下行

回测对比:
  A) volume-only classifier: 仅用 volume_ratio → 无法区分真假洗盘
  B) enhanced classifier: volume + OI变化率 + CVD-价格相关性 + funding zscore
  测量防御准确率: correct hold (真洗盘→hold) + correct force_close (假洗盘→WEAKNESS→force_close)

运行: python3 -m pytest tests/test_w5_washout_external_factors.py -v -p no:warnings -s
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector, WashoutLabel, WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_features import WashoutFeatureExtractor  # noqa: E402


# ============================================================
# 两个 Classifier: volume-only vs enhanced
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


class EnhancedClassifier:
    """B) 多因子: volume + OI变化率 + CVD-价格相关性 + funding zscore.

    判定规则:
      真洗盘 (WASHOUT):
        - volume_ratio < 0.8 (缩量回调)
        - oi_change_rate_7d < -0.02 (OI 温和下降，弱手离场)
        - cvd_price_divergence < -0.1 (CVD 与价格背离，聪明钱吸收)
        → WASHOUT, conf=0.85

      假洗盘 (WEAKNESS):
        - volume_ratio < 0.8 (缩量回调，迷惑性)
        - oi_change_rate_7d > 0.03 (OI 上升，新空头涌入)
        - cvd_price_divergence > 0.2 (CVD 与价格同步下行)
        → WEAKNESS, conf=0.80

      混合信号 → UNKNOWN
    """

    def predict(self, features: Dict[str, float]) -> Optional[WashoutVerdict]:
        vol = features.get("volume_ratio_20d", 1.0)
        oi_rate = features.get("oi_change_rate_7d", 0.0)
        cvd_corr = features.get("cvd_price_divergence", 0.0)
        funding_z = features.get("funding_rate_zscore", 0.0)

        # 缩量回调场景下才进一步判定
        if vol < 0.8:
            # 真洗盘: OI 温和下降 + CVD 背离
            if oi_rate < -0.02 and cvd_corr < -0.1:
                return WashoutVerdict(
                    label=WashoutLabel.WASHOUT, confidence=0.85,
                    trigger_activated=True, feature_snapshot=features,
                    reason="enhanced_washout_oi_decline_cvd_divergence",
                    timestamp="",
                )
            # 假洗盘: OI 上升 + CVD 同步下行
            if oi_rate > 0.03 and cvd_corr > 0.2:
                return WashoutVerdict(
                    label=WashoutLabel.WEAKNESS, confidence=0.80,
                    trigger_activated=True, feature_snapshot=features,
                    reason="enhanced_weakness_oi_rise_cvd_sync",
                    timestamp="",
                )
            # funding 辅助: 深度负值倾向真弱势
            if funding_z < -2.5:
                return WashoutVerdict(
                    label=WashoutLabel.WEAKNESS, confidence=0.70,
                    trigger_activated=True, feature_snapshot=features,
                    reason="enhanced_weakness_deep_negative_funding",
                    timestamp="",
                )
            # 信号不足 → UNKNOWN
            return WashoutVerdict.unknown()

        # 放量 → WEAKNESS
        if vol > 1.5:
            return WashoutVerdict(
                label=WashoutLabel.WEAKNESS, confidence=0.75,
                trigger_activated=True, feature_snapshot=features,
                reason="enhanced_weakness_high_volume", timestamp="",
            )
        return WashoutVerdict.unknown()


# ============================================================
# 合成数据: OHLCV + macro_data (OI/funding/CVD)
# ============================================================
def _make_washout_ohlcv(seed: int, n_forward: int = 48) -> pd.DataFrame:
    """洗盘 pattern OHLCV（真/假共用，区别在 macro_data）。"""
    n = 250 + n_forward
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

    # 前向价格由具体场景设定（真/假分别设置）
    volume = rng.uniform(2000, 4000, n)
    volume[240:250] *= 0.5  # 缩量

    high = prices * 1.005
    low = prices * 0.995

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_true_washout_full(seed: int) -> tuple:
    """真洗盘: 价格回升 + OI 温和下降 + CVD 背离 + funding 暂时偏负。"""
    df = _make_washout_ohlcv(seed)
    n = len(df)
    prices = df["close"].values.copy()

    # 前向: 价格回升
    recovery_start = prices[249]
    peak_val = prices[239]
    rng = np.random.RandomState(seed + 1)
    for i in range(250, n):
        target = peak_val * rng.uniform(0.95, 1.0)
        frac = (i - 250) / (n - 250)
        prices[i] = recovery_start + (target - recovery_start) * frac
        prices[i] *= (1 + rng.normal(0, 0.005))
    df["close"] = prices
    df["open"] = prices
    df["high"] = prices * 1.005
    df["low"] = prices * 0.995

    # macro_data: 真洗盘特征
    # OI: 前 240 bar 稳定，240-250 温和下降 3%（弱手离场），250+ 回稳
    oi_base = 1e8
    oi_series = np.ones(n) * oi_base
    for i in range(240, 250):
        oi_series[i] = oi_base * (1 - 0.003 * (i - 240))  # 温和下降 3%
    for i in range(250, n):
        oi_series[i] = oi_base * 0.97 + rng.normal(0, oi_base * 0.001)  # 回稳

    # CVD: 与价格背离 → 上涨期间 CVD 下行（出货），回调期间 CVD 上行（吸收）
    # 整体构造为与 close 负相关
    cvd_base = 1e6
    cvd_series = cvd_base - prices[:n] * 5000 + rng.normal(0, 5000, n)
    cvd_series = np.maximum(cvd_series, 0)  # 不能为负

    # funding: 240-250 暂时偏负 (zscore ~ -1)，250+ 回正
    funding_series = np.ones(n) * 0.0001
    funding_series[240:250] = -0.0003 + rng.normal(0, 0.00005, 10)
    funding_series[250:] = 0.0001 + rng.normal(0, 0.00005, n - 250)

    macro_data = {
        "oi_series": oi_series.tolist(),
        "cvd_series": cvd_series.tolist(),
        "funding_rate_series": funding_series.tolist(),
    }
    return df, macro_data, True  # is_true_washout=True


def _make_false_washout_full(seed: int) -> tuple:
    """假洗盘: 价格继续下跌 + OI 上升 + CVD 同步下行 + funding 深度负值。"""
    df = _make_washout_ohlcv(seed)
    n = len(df)
    prices = df["close"].values.copy()

    # 前向: 价格继续下跌
    decline_start = prices[249]
    rng = np.random.RandomState(seed + 2)
    for i in range(250, n):
        decline_target = decline_start * 0.85
        frac = (i - 250) / (n - 250)
        prices[i] = decline_start + (decline_target - decline_start) * frac
        prices[i] *= (1 + rng.normal(0, 0.005))
    df["close"] = prices
    df["open"] = prices
    df["high"] = prices * 1.005
    df["low"] = prices * 0.995

    # macro_data: 假洗盘特征
    # OI: 240-250 上升 8%（新空头涌入），250+ 继续上升
    oi_base = 1e8
    oi_series = np.ones(n) * oi_base
    for i in range(240, n):
        oi_series[i] = oi_base * (1 + 0.008 * (i - 240))  # 上升 8%+

    # CVD: 与价格同步下行 → 正相关（价格跌 CVD 也跌 = 真弱势出货）
    cvd_base = 1e6
    cvd_series = cvd_base + prices[:n] * 5000 + rng.normal(0, 5000, n)

    # funding: 240+ 深度负值 (zscore ~ -3)
    funding_series = np.ones(n) * 0.0001
    funding_series[240:] = -0.0008 + rng.normal(0, 0.0001, n - 240)

    macro_data = {
        "oi_series": oi_series.tolist(),
        "cvd_series": cvd_series.tolist(),
        "funding_rate_series": funding_series.tolist(),
    }
    return df, macro_data, False  # is_true_washout=False


# ============================================================
# 防御准确率回测
# ============================================================
def run_defensive_backtest(
    scenarios: list,
    classifier,
    horizons: list = None,
) -> Dict:
    """回测防御准确率。

    对每个场景:
      1. 在检测点 (bar 249) 运行 detector
      2. 如果 WASHOUT → hold 决策
      3. 如果 WEAKNESS → force_close 决策
      4. 如果 UNKNOWN → pass（交后续策略）
      5. 用前向 24h 收益验证决策是否正确

    正确判定:
      真洗盘 + WASHOUT(hold) → 正确 (价格回升，hold 是对的)
      假洗盘 + WEAKNESS(force_close) → 正确 (价格下跌，离场是对的)
      真洗盘 + WEAKNESS → 错误 (误判为弱势，提前离场)
      假洗盘 + WASHOUT → 错误 (误判为洗盘，持有导致亏损)
    """
    if horizons is None:
        horizons = [24]

    ext = WashoutFeatureExtractor()
    detector = WashoutDetector(
        enable=True, classifier=classifier, feature_extractor=ext
    )

    correct = 0
    wrong = 0
    unknown = 0
    total = len(scenarios)

    true_washout_detected = 0
    false_washout_detected = 0
    true_washout_correct = 0
    false_washout_correct = 0

    for df, macro_data, is_true_washout in scenarios:
        # 在检测点截取（df 和 macro_data 都截断到 bar 249）
        detection_df = df.iloc[:250]
        detection_macro = {}
        for k, v in macro_data.items():
            if isinstance(v, list):
                detection_macro[k] = v[:250]
            elif isinstance(v, (np.ndarray, pd.Series)):
                detection_macro[k] = v[:250]
            else:
                detection_macro[k] = v
        verdict = detector.run("BTC", detection_df, detection_macro)

        # 前向 24h 收益
        entry_price = float(df["close"].iloc[249])
        future_price = float(df["close"].iloc[273])  # 24h later
        forward_return = future_price / entry_price - 1.0

        if verdict.label == WashoutLabel.WASHOUT:
            if is_true_washout:
                true_washout_detected += 1
                if forward_return > 0:
                    correct += 1
                    true_washout_correct += 1
                else:
                    wrong += 1
            else:
                false_washout_detected += 1
                if forward_return <= 0:
                    # hold 在下跌中是错误的
                    wrong += 1
                else:
                    correct += 1  # 价格意外回升

        elif verdict.label == WashoutLabel.WEAKNESS:
            if is_true_washout:
                # 真洗盘误判为弱势 → 错误（提前离场错过回升）
                wrong += 1
            else:
                # 假洗盘正确判为弱势 → 正确（离场避免亏损）
                false_washout_correct += 1
                correct += 1

        else:  # UNKNOWN
            unknown += 1

    accuracy = correct / total if total > 0 else 0
    # 排除 UNKNOWN 后的准确率（仅看有判定的场景）
    judged = correct + wrong
    accuracy_judged = correct / judged if judged > 0 else 0

    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "unknown": unknown,
        "accuracy": accuracy,
        "accuracy_judged": accuracy_judged,
        "true_washout_detected": true_washout_detected,
        "false_washout_detected": false_washout_detected,
        "true_washout_correct": true_washout_correct,
        "false_washout_correct": false_washout_correct,
        "judged_count": judged,
    }


# ============================================================
# 回测用例
# ============================================================
class TestExternalFactorEnhancement(unittest.TestCase):
    """对比 volume-only vs enhanced classifier 的防御准确率。"""

    @classmethod
    def setUpClass(cls):
        n_scenarios = 20
        cls.true_scenarios = [_make_true_washout_full(1000 + i)
                              for i in range(n_scenarios)]
        cls.false_scenarios = [_make_false_washout_full(2000 + i)
                               for i in range(n_scenarios)]
        cls.all_scenarios = cls.true_scenarios + cls.false_scenarios

    def test_volume_only_cannot_distinguish(self):
        """A) volume-only: 真假洗盘都缩量 → 都判为 WASHOUT → 假洗盘误判。"""
        results = run_defensive_backtest(
            self.all_scenarios, VolumeOnlyClassifier()
        )
        print(f"\n[A) volume-only classifier]")
        print(f"  总场景: {results['total']}")
        print(f"  正确: {results['correct']}, 错误: {results['wrong']}, "
              f"未知: {results['unknown']}")
        print(f"  准确率: {results['accuracy']:.1%}")
        print(f"  有判定准确率: {results['accuracy_judged']:.1%}")
        print(f"  真洗盘检测→WASHOUT: {results['true_washout_detected']}")
        print(f"  假洗盘误判→WASHOUT: {results['false_washout_detected']}")

        # 假洗盘应该全部被误判为 WASHOUT
        self.assertGreater(results["false_washout_detected"], 15,
                           "volume-only 应将大部分假洗盘误判为 WASHOUT")
        # 准确率应 < 60%（接近 50%，因为真假各半，真洗盘正确+假洗盘错误）
        self.assertLess(results["accuracy"], 0.60,
                        "volume-only 准确率应 < 60%")

    def test_enhanced_distinguishes_via_external_factors(self):
        """B) enhanced: OI/CVD/funding 区分真假洗盘 → 准确率大幅提升。"""
        results = run_defensive_backtest(
            self.all_scenarios, EnhancedClassifier()
        )
        print(f"\n[B) enhanced classifier (volume + OI + CVD + funding)]")
        print(f"  总场景: {results['total']}")
        print(f"  正确: {results['correct']}, 错误: {results['wrong']}, "
              f"未知: {results['unknown']}")
        print(f"  准确率: {results['accuracy']:.1%}")
        print(f"  有判定准确率: {results['accuracy_judged']:.1%}")
        print(f"  真洗盘正确→WASHOUT(hold): {results['true_washout_correct']}")
        print(f"  假洗盘正确→WEAKNESS(force_close): "
              f"{results['false_washout_correct']}")

        # 假洗盘不应再被误判为 WASHOUT
        self.assertLess(results["false_washout_detected"], 5,
                        "enhanced 应将大部分假洗盘正确判为 WEAKNESS")
        # 准确率应 > 70%
        self.assertGreater(results["accuracy"], 0.70,
                           "enhanced 准确率应 > 70%")

    def test_accuracy_improvement(self):
        """对比: enhanced 比 volume-only 准确率提升 > 20%。"""
        vol_results = run_defensive_backtest(
            self.all_scenarios, VolumeOnlyClassifier()
        )
        enh_results = run_defensive_backtest(
            self.all_scenarios, EnhancedClassifier()
        )

        improvement = enh_results["accuracy"] - vol_results["accuracy"]
        print(f"\n[准确率提升对比]")
        print(f"  volume-only: {vol_results['accuracy']:.1%} "
              f"({vol_results['correct']} correct)")
        print(f"  enhanced:    {enh_results['accuracy']:.1%} "
              f"({enh_results['correct']} correct)")
        print(f"  提升: {improvement:+.1%}")

        self.assertGreater(improvement, 0.20,
                           "enhanced 应比 volume-only 提升 > 20%")

    def test_external_factors_differentiate(self):
        """核心验证: 外部因子在检测点对真假洗盘有本质差异。"""
        ext = WashoutFeatureExtractor()

        true_df, true_macro, _ = self.true_scenarios[0]
        false_df, false_macro, _ = self.false_scenarios[0]

        true_detection_df = true_df.iloc[:250]
        false_detection_df = false_df.iloc[:250]
        # macro_data 同步截断到 bar 249
        true_det_macro = {k: v[:250] if isinstance(v, list) else v
                          for k, v in true_macro.items()}
        false_det_macro = {k: v[:250] if isinstance(v, list) else v
                           for k, v in false_macro.items()}

        true_feats = ext.extract_all(true_detection_df, true_det_macro)
        false_feats = ext.extract_all(false_detection_df, false_det_macro)

        print(f"\n[检测点外部因子对比]")
        print(f"  {'因子':<25} {'真洗盘':>10} {'假洗盘':>10} {'差异':>10}")
        for key in ["oi_change_rate_7d", "cvd_price_divergence",
                     "funding_rate_zscore", "oi_price_quadrant"]:
            tv = true_feats.get(key, 0)
            fv = false_feats.get(key, 0)
            print(f"  {key:<25} {tv:>10.4f} {fv:>10.4f} {abs(tv-fv):>10.4f}")

        # OI 变化率: 真洗盘 < 0 (下降), 假洗盘 > 0 (上升)
        self.assertLess(
            true_feats["oi_change_rate_7d"], 0,
            "真洗盘 OI 应下降"
        )
        self.assertGreater(
            false_feats["oi_change_rate_7d"], 0,
            "假洗盘 OI 应上升"
        )

        # CVD-价格相关性: 真洗盘 < 0 (背离), 假洗盘 > 0 (同步)
        self.assertLess(
            true_feats["cvd_price_divergence"], 0,
            "真洗盘 CVD 应与价格背离（负相关）"
        )
        self.assertGreater(
            false_feats["cvd_price_divergence"], 0,
            "假洗盘 CVD 应与价格同步（正相关）"
        )

    def test_conclusion(self):
        """结论: 加入外部因子可显著提升防御层准确率。"""
        vol_r = run_defensive_backtest(
            self.all_scenarios, VolumeOnlyClassifier()
        )
        enh_r = run_defensive_backtest(
            self.all_scenarios, EnhancedClassifier()
        )
        print(f"\n{'='*60}")
        print(f"[最终结论]")
        print(f"  volume-only 防御准确率: {vol_r['accuracy']:.1%}")
        print(f"  enhanced 防御准确率:   {enh_r['accuracy']:.1%}")
        print(f"  假洗盘误判数: {vol_r['false_washout_detected']} → "
              f"{enh_r['false_washout_detected']}")
        print(f"  关键外部因子: OI变化率 / CVD-价格相关性 / funding zscore")
        print(f"  → 防御层应接入外部因子辅助判断")
        print(f"{'='*60}")
        self.assertGreater(enh_r["accuracy"], vol_r["accuracy"],
                           "enhanced 应优于 volume-only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
