#!/usr/bin/env python3
"""W5 洗盘入场信号准确性回测 — 验证"作为入场信号不夠准"的结论。

回测设计:
  - 模拟在 WashoutDetector 判定 WASHOUT 的时点开多仓
  - 测量前向收益（1h/4h/24h/48h 后的价格变化）
  - 构造真假洗盘混合场景:
    * 真洗盘: 缩量回调后价格回升 → LONG 盈利
    * 假洗盘: 缩量回调但价格继续下跌 → LONG 亏损
  - 计算: 胜率、平均收益、最大回撤、误判率
  - 结论: 当前基于 volume_ratio 的 mock classifier 无法区分真假洗盘

运行: python3 -m pytest tests/test_w5_washout_entry_accuracy.py -v -p no:warnings
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
from scripts.memory_l4.bcrm2.washout_trigger_gate import WashoutTriggerGate  # noqa: E402
from scripts.memory_l4.bcrm2.washout_features import WashoutFeatureExtractor  # noqa: E402


# ============================================================
# Mock Classifier — 同 backtest 文件中的 volume_ratio 规则
# ============================================================
class MockWashoutClassifier:
    """volume_ratio < 0.8 → WASHOUT; > 1.5 → WEAKNESS; else UNKNOWN."""

    def predict(self, features: Dict[str, float]) -> Optional[WashoutVerdict]:
        vol_ratio = features.get("volume_ratio_20d", 1.0)
        if vol_ratio < 0.8:
            return WashoutVerdict(
                label=WashoutLabel.WASHOUT, confidence=0.85,
                trigger_activated=True, feature_snapshot=features,
                reason="mock_washout_low_volume", timestamp="",
            )
        if vol_ratio > 1.5:
            return WashoutVerdict(
                label=WashoutLabel.WEAKNESS, confidence=0.75,
                trigger_activated=True, feature_snapshot=features,
                reason="mock_weakness_high_volume", timestamp="",
            )
        return WashoutVerdict.unknown()


# ============================================================
# 合成场景工厂 — 真假洗盘混合
# ============================================================
def _make_true_washout(seed: int, n_forward: int = 48) -> pd.DataFrame:
    """真洗盘: 上涨→缩量回调→价格回升。

    检测点（最后一根 bar）后 n_forward 根 bar 价格回升。
    如果在检测点开多仓 → 盈利。
    """
    n = 250 + n_forward
    rng = np.random.RandomState(seed)
    # 前 215 bar 温和上涨
    prices = np.cumprod(1 + rng.normal(0.002, 0.015, n))
    prices = prices * 100 / prices[0]

    # 215→240 涨 20% 到 peak
    ramp_start = 215
    base = float(prices[ramp_start])
    peak_val = base * 1.20
    for i in range(ramp_start, 240):
        frac = (i - ramp_start) / (240 - ramp_start)
        prices[i] = base + (peak_val - base) * frac

    # 240→250 缩量回调 7%（检测点 = bar 249）
    for i in range(240, 250):
        frac = (i - 240) / 10.0
        prices[i] = peak_val * (1 - 0.07 * frac)

    # 250→250+n_forward 价格回升（真洗盘特征）
    recovery_start = prices[249]
    for i in range(250, 250 + n_forward):
        # 回升至 peak 的 95-100%
        target = peak_val * rng.uniform(0.95, 1.0)
        frac = (i - 250) / n_forward
        prices[i] = recovery_start + (target - recovery_start) * frac
        # 加少量噪音
        prices[i] *= (1 + rng.normal(0, 0.005))

    volume = rng.uniform(2000, 4000, n)
    volume[240:250] *= 0.5  # 回调缩量

    high = prices * 1.005
    low = prices * 0.995

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_false_washout(seed: int, n_forward: int = 48) -> pd.DataFrame:
    """假洗盘: 上涨→缩量回调→价格继续下跌。

    检测点（最后一根 bar）后 n_forward 根 bar 价格继续下跌。
    如果在检测点开多仓 → 亏损。
    与真洗盘的唯一区别: 前向价格走势不同。
    """
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

    # 缩量回调 7%
    for i in range(240, 250):
        frac = (i - 240) / 10.0
        prices[i] = peak_val * (1 - 0.07 * frac)

    # 250→250+n_forward 价格继续下跌（假洗盘特征）
    decline_start = prices[249]
    for i in range(250, 250 + n_forward):
        # 继续下跌 5-15%
        decline_target = decline_start * rng.uniform(0.85, 0.95)
        frac = (i - 250) / n_forward
        prices[i] = decline_start + (decline_target - decline_start) * frac
        prices[i] *= (1 + rng.normal(0, 0.005))

    volume = rng.uniform(2000, 4000, n)
    volume[240:250] *= 0.5  # 同样缩量（假洗盘迷惑性）

    high = prices * 1.005
    low = prices * 0.995

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


def _make_normal_pullback(seed: int, n_forward: int = 48) -> pd.DataFrame:
    """普通回调（非洗盘）: 上涨→缩量回调→横盘。

    检测点后价格横盘震荡，无明确方向。
    """
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

    # 横盘震荡
    sideways_start = prices[249]
    for i in range(250, 250 + n_forward):
        prices[i] = sideways_start * (1 + rng.normal(0, 0.01))

    volume = rng.uniform(2000, 4000, n)
    volume[240:250] *= 0.5

    high = prices * 1.005
    low = prices * 0.995

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": high, "low": low,
        "close": prices, "volume": volume,
    }, index=dates)


# ============================================================
# 入场信号回测引擎
# ============================================================
class EntryBacktestResult:
    """入场信号回测结果。"""
    def __init__(self, scenario: str, detected_label: str,
                 detected_confidence: float, forward_returns: Dict[str, float],
                 entry_price: float, is_true_washout: bool,
                 long_profitable: Optional[bool] = None):
        self.scenario = scenario
        self.detected_label = detected_label
        self.detected_confidence = detected_confidence
        self.forward_returns = forward_returns
        self.entry_price = entry_price
        self.is_true_washout = is_true_washout
        self.long_profitable = long_profitable


def run_entry_backtest(
    df: pd.DataFrame,
    detector: WashoutDetector,
    horizons: List[int] = None,
    is_true_washout: bool = False,
    scenario: str = "",
) -> EntryBacktestResult:
    """在检测点（bar 249）模拟洗盘检测 + 开多仓。

    Args:
        df: 完整 OHLCV（含前向 bar）
        detector: WashoutDetector 实例
        horizons: 前向时间窗口列表
        is_true_washout: 是否为真洗盘场景
        scenario: 场景名称

    Returns:
        EntryBacktestResult
    """
    if horizons is None:
        horizons = [1, 4, 24, 48]

    # 在检测点（bar 249）截取数据运行检测器
    detection_df = df.iloc[:250]
    macro = {}
    verdict = detector.run("BTC", detection_df, macro)

    # 检测点的价格
    entry_price = float(df["close"].iloc[249])

    # 计算前向收益
    forward_returns = {}
    for h in horizons:
        idx = 249 + h
        if idx < len(df):
            future_price = float(df["close"].iloc[idx])
            forward_returns[f"{h}h"] = (future_price / entry_price - 1.0)

    # 如果检测为 WASHOUT 且开多仓，是否盈利（24h 前向）
    long_profitable = None
    if verdict.label == WashoutLabel.WASHOUT:
        ret_24h = forward_returns.get("24h", 0.0)
        long_profitable = ret_24h > 0.0

    return EntryBacktestResult(
        scenario=scenario,
        detected_label=verdict.label.value,
        detected_confidence=verdict.confidence,
        forward_returns=forward_returns,
        entry_price=entry_price,
        is_true_washout=is_true_washout,
        long_profitable=long_profitable,
    )


def run_batch_backtest(
    n_scenarios: int = 20,
    detector: WashoutDetector = None,
) -> List[EntryBacktestResult]:
    """批量运行真假洗盘回测。

    每种场景生成 n_scenarios 个样本，共 3*n_scenarios 个结果。
    """
    if detector is None:
        ext = WashoutFeatureExtractor()
        clf = MockWashoutClassifier()
        detector = WashoutDetector(
            enable=True, classifier=clf, feature_extractor=ext
        )

    results: List[EntryBacktestResult] = []

    # 真洗盘场景
    for i in range(n_scenarios):
        seed = 1000 + i
        df = _make_true_washout(seed)
        r = run_entry_backtest(
            df, detector, is_true_washout=True, scenario="true_washout"
        )
        results.append(r)

    # 假洗盘场景
    for i in range(n_scenarios):
        seed = 2000 + i
        df = _make_false_washout(seed)
        r = run_entry_backtest(
            df, detector, is_true_washout=False, scenario="false_washout"
        )
        results.append(r)

    # 普通回调场景
    for i in range(n_scenarios):
        seed = 3000 + i
        df = _make_normal_pullback(seed)
        r = run_entry_backtest(
            df, detector, is_true_washout=False, scenario="normal_pullback"
        )
        results.append(r)

    return results


def summarize_results(results: List[EntryBacktestResult]) -> Dict:
    """汇总回测结果。"""
    # 只看被检测为 WASHOUT 的场景（即会触发入场信号的场景）
    washout_detected = [r for r in results if r.detected_label == "washout"]

    total_detected = len(washout_detected)
    true_positive = sum(1 for r in washout_detected if r.is_true_washout and r.long_profitable)
    false_positive = sum(1 for r in washout_detected if not r.is_true_washout and not r.long_profitable)
    # 误判: 检测为 WASHOUT 但实际不是真洗盘
    misclassified = sum(1 for r in washout_detected if not r.is_true_washout)
    # 真洗盘漏判: 是真洗盘但未检测为 WASHOUT
    total_true = sum(1 for r in results if r.is_true_washout)
    true_detected = sum(1 for r in washout_detected if r.is_true_washout)
    missed = total_true - true_detected

    # 前向收益统计（仅 WASHOUT 检测的场景）
    if washout_detected:
        avg_24h = np.mean([r.forward_returns.get("24h", 0.0) for r in washout_detected])
        avg_48h = np.mean([r.forward_returns.get("48h", 0.0) for r in washout_detected])
        win_count = sum(1 for r in washout_detected if r.forward_returns.get("24h", 0.0) > 0)
        win_rate = win_count / total_detected if total_detected > 0 else 0.0
    else:
        avg_24h = avg_48h = win_rate = 0.0

    return {
        "total_scenarios": len(results),
        "washout_detected": total_detected,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "misclassified_as_washout": misclassified,
        "missed_true_washout": missed,
        "avg_24h_return": avg_24h,
        "avg_48h_return": avg_48h,
        "win_rate_24h": win_rate,
        "false_positive_rate": misclassified / total_detected if total_detected > 0 else 0.0,
        "miss_rate": missed / total_true if total_true > 0 else 0.0,
    }


# ============================================================
# 回测用例
# ============================================================
class TestWashoutEntrySignalAccuracy(unittest.TestCase):
    """回测: 洗盘检测作为入场信号的准确性。"""

    @classmethod
    def setUpClass(cls):
        cls.detector = WashoutDetector(
            enable=True,
            classifier=MockWashoutClassifier(),
            feature_extractor=WashoutFeatureExtractor(),
        )
        cls.results = run_batch_backtest(n_scenarios=20, detector=cls.detector)
        cls.summary = summarize_results(cls.results)

    def test_true_washout_detected_as_washout(self):
        """真洗盘场景应该被检测为 WASHOUT。"""
        true_results = [r for r in self.results if r.is_true_washout]
        detected = [r for r in true_results if r.detected_label == "washout"]
        detection_rate = len(detected) / len(true_results) if true_results else 0
        print(f"\n[真洗盘检测率] {len(detected)}/{len(true_results)} = {detection_rate:.1%}")
        self.assertGreater(detection_rate, 0.5,
                           "真洗盘检测率应 > 50%")

    def test_false_washout_also_detected_as_washout(self):
        """假洗盘场景也会被检测为 WASHOUT（误判）。

        这是关键问题: 假洗盘和真洗盘在检测点（bar 249）的特征完全相同
        （都是缩量回调），detector 无法区分。只有前向价格走势不同。
        """
        false_results = [r for r in self.results
                         if r.scenario == "false_washout"]
        false_detected = [r for r in false_results
                          if r.detected_label == "washout"]
        false_detection_rate = (len(false_detected) / len(false_results)
                                if false_results else 0)
        print(f"\n[假洗盘误判率] {len(false_detected)}/{len(false_results)} "
              f"= {false_detection_rate:.1%}")
        # 假洗盘也会被高比例检测为 WASHOUT → 证明入场信号不夠准
        self.assertGreater(false_detection_rate, 0.5,
                           "假洗盘应被高比例误判为 WASHOUT（证明入场信号不夠准）")

    def test_entry_signal_win_rate(self):
        """如果以 WASHOUT 检测为入场信号开多仓，胜率应 < 60%。"""
        s = self.summary
        print(f"\n[入场信号回测汇总]")
        print(f"  总场景数: {s['total_scenarios']}")
        print(f"  WASHOUT 检测数: {s['washout_detected']}")
        print(f"  误判为 WASHOUT 的假洗盘: {s['misclassified_as_washout']}")
        print(f"  漏判的真洗盘: {s['missed_true_washout']}")
        print(f"  24h 平均收益: {s['avg_24h_return']:.4f}")
        print(f"  48h 平均收益: {s['avg_48h_return']:.4f}")
        print(f"  24h 胜率: {s['win_rate_24h']:.1%}")
        print(f"  误判率 (假阳性率): {s['false_positive_rate']:.1%}")
        print(f"  漏判率: {s['miss_rate']:.1%}")

        # 胜率 < 60% → 不适合作为入场信号
        self.assertLess(s["win_rate_24h"], 0.60,
                        f"24h 胜率 {s['win_rate_24h']:.1%} < 60%，"
                        "不适合作为入场信号")

    def test_false_positive_rate_high(self):
        """误判率（假洗盘被检测为 WASHOUT）应 > 50%。"""
        s = self.summary
        self.assertGreater(s["false_positive_rate"], 0.50,
                            f"误判率 {s['false_positive_rate']:.1%} > 50%，"
                            "证明 detector 无法区分真假洗盘")

    def test_forward_returns_comparison(self):
        """真洗盘 vs 假洗盘的前向收益差异。

        真洗盘: 24h 前向收益应为正（价格回升）
        假洗盘: 24h 前向收益应为负（价格继续下跌）
        但 detector 在检测点无法预知这个差异 → 入场信号不夠准。
        """
        true_results = [r for r in self.results if r.is_true_washout]
        false_results = [r for r in self.results
                         if r.scenario == "false_washout"]

        true_24h = np.mean([r.forward_returns.get("24h", 0.0)
                           for r in true_results])
        false_24h = np.mean([r.forward_returns.get("24h", 0.0)
                            for r in false_results])

        print(f"\n[前向收益对比]")
        print(f"  真洗盘 24h 平均收益: {true_24h:.4f}")
        print(f"  假洗盘 24h 平均收益: {false_24h:.4f}")

        # 真洗盘前向收益 > 假洗盘（验证合成数据正确性）
        self.assertGreater(true_24h, false_24h,
                           "真洗盘前向收益应 > 假洗盘")
        # 但 detector 在检测点无法区分 → 不适合入场

    def test_detector_cannot_distinguish_at_detection_point(self):
        """核心验证: 在检测点（bar 249），真假洗盘的特征完全相同。

        volume_ratio_20d 在真假洗盘中几乎一致（都是缩量回调）。
        detector 基于检测点的特征判定，无法预知前向走势。
        """
        ext = WashoutFeatureExtractor()
        true_df = _make_true_washout(1000).iloc[:250]
        false_df = _make_false_washout(2000).iloc[:250]

        true_feats = ext.extract_all(true_df, {})
        false_feats = ext.extract_all(false_df, {})

        true_vol = true_feats.get("volume_ratio_20d", 1.0)
        false_vol = false_feats.get("volume_ratio_20d", 1.0)

        print(f"\n[检测点特征对比]")
        print(f"  真洗盘 volume_ratio: {true_vol:.4f}")
        print(f"  假洗盘 volume_ratio: {false_vol:.4f}")
        print(f"  差异: {abs(true_vol - false_vol):.4f}")

        # 两者 volume_ratio 都 < 0.8（缩量），detector 都会判定为 WASHOUT
        self.assertLess(true_vol, 0.8, "真洗盘应缩量")
        self.assertLess(false_vol, 0.8, "假洗盘也应缩量（迷惑性）")

        # detector 对两者输出相同的 WASHOUT 判定
        v_true = self.detector.run("BTC", true_df, {})
        v_false = self.detector.run("BTC", false_df, {})
        self.assertEqual(v_true.label, WashoutLabel.WASHOUT)
        self.assertEqual(v_false.label, WashoutLabel.WASHOUT,
                         "假洗盘也被检测为 WASHOUT → 入场信号不夠准")

    def test_conclusion_defensive_only(self):
        """结论: 洗盘检测应仅作为防御层（离场侧），不作为入场信号。"""
        s = self.summary
        print(f"\n{'='*60}")
        print(f"[最终结论]")
        print(f"  入场信号 24h 胜率: {s['win_rate_24h']:.1%}")
        print(f"  误判率: {s['false_positive_rate']:.1%}")
        print(f"  漏判率: {s['miss_rate']:.1%}")
        print(f"  结论: 胜率 < 60%，误判率 > 50%")
        print(f"  → 洗盘检测不适合作为入场信号")
        print(f"  → 应仅作为防御层（离场侧 hold/force_close）")
        print(f"{'='*60}")

        # 胜率不达标 + 误判率高 → 不适合入场
        self.assertTrue(
            s["win_rate_24h"] < 0.60 or s["false_positive_rate"] > 0.50,
            "洗盘检测作为入场信号: 胜率低/误判率高 → 仅作防御层"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
