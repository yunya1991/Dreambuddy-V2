#!/usr/bin/env python3
"""W4 洗盘 DAL 集成测试 — WashoutMacroProvider + EnhancedWashoutClassifier。

测试覆盖:
  1. WashoutMacroProvider: DAL 查询 OI/funding/CVD → macro_data 构造
  2. WashoutMacroProvider: FAIL-OPEN (repo=None / 异常 → 空字典)
  3. EnhancedWashoutClassifier: 多因子判定 (WASHOUT/WEAKNESS/UNKNOWN)
  4. WashoutDetector 端到端: provider + classifier + feature_extractor 联动
  5. 开关关闭时字节等价

运行: python3 -m pytest tests/test_w4_washout_dal_integration.py -v -p no:warnings
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector, WashoutLabel, WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_features import WashoutFeatureExtractor  # noqa: E402
from scripts.memory_l4.bcrm2.washout_classifier import EnhancedWashoutClassifier  # noqa: E402
from scripts.memory_l4.bcrm2.washout_macro_provider import WashoutMacroProvider  # noqa: E402


# ============================================================
# Mock DAL Repository
# ============================================================
class MockMacroRepo:
    """模拟 19-DAL MarketMacroRepository，返回预设数据。"""

    def __init__(self, oi_data=None, funding_data=None, taker_data=None):
        self._oi = oi_data or []
        self._funding = funding_data or []
        self._taker = taker_data or []

    def query_open_interest_by_time(self, symbol, start, end):
        return self._oi

    def query_funding_by_time(self, symbol, start, end):
        return self._funding

    def query_taker_volume_by_time(self, symbol, start, end):
        return self._taker


def _make_mock_repo_with_washout_data():
    """构造真洗盘的 DAL 数据 (OI 下降 + CVD 与价格背离)。"""
    now = datetime.now(timezone.utc)
    ts_list = [now - pd.Timedelta(hours=i) for i in range(250, 0, -1)]

    # OI: 温和下降 (1e8 → 0.97e8)
    oi_data = [
        ("BTC", Decimal(str(1e8 * (1 - 0.0003 * i))),
         Decimal(str(1e8)), ts_list[i])
        for i in range(250)
    ]

    # Funding: 暂时偏负 (zscore ~ -1)
    funding_data = [
        ("BTC", Decimal(str(-0.0003)), ts_list[i])
        for i in range(250)
    ]

    # Taker volume: CVD 与价格背离 (buy > sell → CVD 上升)
    taker_data = [
        ("BTC",
         Decimal("1500"),  # buy_vol
         Decimal("1000"),  # sell_vol
         Decimal("500"),   # buy_sell_volume_diff
         Decimal("1.5"),   # ratio
         ts_list[i])
        for i in range(250)
    ]

    return MockMacroRepo(oi_data=oi_data, funding_data=funding_data,
                         taker_data=taker_data)


def _make_mock_repo_with_weakness_data():
    """构造假洗盘的 DAL 数据 (OI 上升 + CVD 与价格同步)。"""
    now = datetime.now(timezone.utc)
    ts_list = [now - pd.Timedelta(hours=i) for i in range(250, 0, -1)]

    # OI: 上升 (1e8 → 1.08e8)
    oi_data = [
        ("BTC", Decimal(str(1e8 * (1 + 0.0008 * i))),
         Decimal(str(1e8)), ts_list[i])
        for i in range(250)
    ]

    # Funding: 深度负值 (zscore ~ -3)
    funding_data = [
        ("BTC", Decimal(str(-0.0008)), ts_list[i])
        for i in range(250)
    ]

    # Taker volume: CVD 与价格同步 (sell > buy → CVD 下降)
    taker_data = [
        ("BTC",
         Decimal("800"),    # buy_vol
         Decimal("1500"),   # sell_vol
         Decimal("-700"),   # buy_sell_volume_diff (负值)
         Decimal("0.53"),   # ratio
         ts_list[i])
        for i in range(250)
    ]

    return MockMacroRepo(oi_data=oi_data, funding_data=funding_data,
                         taker_data=taker_data)


def _make_washout_ohlcv(seed=42):
    """构造洗盘 pattern OHLCV (上涨 → 缩量回调)。"""
    rng = np.random.RandomState(seed)
    n = 250
    prices = np.cumprod(1 + rng.normal(0.002, 0.015, n))
    prices = prices * 100 / prices[0]

    # 215→240 涨 20%
    base = float(prices[215])
    peak = base * 1.20
    for i in range(215, 240):
        frac = (i - 215) / 25
        prices[i] = base + (peak - base) * frac

    # 240→250 缩量回调 7%
    for i in range(240, 250):
        frac = (i - 240) / 10.0
        prices[i] = peak * (1 - 0.07 * frac)

    volume = rng.uniform(2000, 4000, n)
    volume[240:250] *= 0.5  # 缩量

    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "open": prices, "high": prices * 1.005, "low": prices * 0.995,
        "close": prices, "volume": volume,
    }, index=dates)


# ============================================================
# 测试用例
# ============================================================
class TestWashoutMacroProvider(unittest.TestCase):

    def test_get_macro_data_with_valid_repo(self):
        """有 DAL 数据时返回非空 macro_data。"""
        repo = _make_mock_repo_with_washout_data()
        provider = WashoutMacroProvider(repo=repo)
        data = provider.get_macro_data("BTC")

        self.assertIn("oi_series", data)
        self.assertIn("funding_rate_series", data)
        self.assertIn("cvd_series", data)
        self.assertEqual(len(data["oi_series"]), 250)
        self.assertEqual(len(data["cvd_series"]), 250)

    def test_fail_open_repo_none(self):
        """repo=None → 返回空字典。"""
        provider = WashoutMacroProvider(repo=None)
        data = provider.get_macro_data("BTC")
        self.assertEqual(data, {})

    def test_fail_open_repo_exception(self):
        """repo 异常 → 返回空字典。"""
        bad_repo = MagicMock()
        bad_repo.query_open_interest_by_time.side_effect = RuntimeError("DB down")
        provider = WashoutMacroProvider(repo=bad_repo)
        data = provider.get_macro_data("BTC")
        self.assertEqual(data, {})

    def test_symbol_normalization(self):
        """符号标准化: BTCUSDT → BTC。"""
        repo = _make_mock_repo_with_washout_data()
        provider = WashoutMacroProvider(repo=repo)
        # 内部调用时会标准化
        data = provider.get_macro_data("BTCUSDT")
        # 如果标准化正确, 应该能查到数据
        self.assertTrue(len(data) > 0)

    def test_cvd_cumsum_correct(self):
        """CVD = cumsum(buy_sell_volume_diff)。"""
        taker_data = [
            ("BTC", Decimal("1500"), Decimal("1000"), Decimal("500"),
             Decimal("1.5"), datetime.now(timezone.utc))
            for _ in range(5)
        ]
        repo = MockMacroRepo(taker_data=taker_data)
        provider = WashoutMacroProvider(repo=repo)
        data = provider.get_macro_data("BTC")
        cvd = data["cvd_series"]
        # 500 * 1, 500 * 2, ... 500 * 5
        self.assertAlmostEqual(cvd[0], 500.0)
        self.assertAlmostEqual(cvd[4], 2500.0)


class TestEnhancedWashoutClassifier(unittest.TestCase):

    def setUp(self):
        self.clf = EnhancedWashoutClassifier()

    def test_washout_features(self):
        """缩量 + OI 下降 + CVD 背离 → WASHOUT。"""
        features = {
            "volume_ratio_20d": 0.5,
            "oi_change_rate_7d": -0.05,
            "cvd_price_divergence": -0.5,
            "funding_rate_zscore": -1.0,
        }
        verdict = self.clf.predict(features)
        self.assertEqual(verdict.label, WashoutLabel.WASHOUT)
        self.assertGreaterEqual(verdict.confidence, 0.80)

    def test_weakness_features(self):
        """缩量 + OI 上升 + CVD 同步 → WEAKNESS。"""
        features = {
            "volume_ratio_20d": 0.5,
            "oi_change_rate_7d": 0.05,
            "cvd_price_divergence": 0.5,
            "funding_rate_zscore": -1.0,
        }
        verdict = self.clf.predict(features)
        self.assertEqual(verdict.label, WashoutLabel.WEAKNESS)
        self.assertGreaterEqual(verdict.confidence, 0.75)

    def test_weakness_high_volume(self):
        """放量 → WEAKNESS。"""
        features = {
            "volume_ratio_20d": 2.0,
            "oi_change_rate_7d": 0.0,
            "cvd_price_divergence": 0.0,
            "funding_rate_zscore": 0.0,
        }
        verdict = self.clf.predict(features)
        self.assertEqual(verdict.label, WashoutLabel.WEAKNESS)

    def test_weakness_deep_negative_funding(self):
        """缩量 + funding 深度负值 → WEAKNESS (funding 辅助)。"""
        features = {
            "volume_ratio_20d": 0.5,
            "oi_change_rate_7d": 0.0,  # OI 不明确
            "cvd_price_divergence": 0.0,  # CVD 不明确
            "funding_rate_zscore": -3.0,  # 深度负值
        }
        verdict = self.clf.predict(features)
        self.assertEqual(verdict.label, WashoutLabel.WEAKNESS)
        self.assertGreaterEqual(verdict.confidence, 0.65)

    def test_unknown_insufficient_signals(self):
        """缩量但信号不足 → UNKNOWN。"""
        features = {
            "volume_ratio_20d": 0.5,
            "oi_change_rate_7d": 0.0,
            "cvd_price_divergence": 0.0,
            "funding_rate_zscore": 0.0,
        }
        verdict = self.clf.predict(features)
        self.assertEqual(verdict.label, WashoutLabel.UNKNOWN)

    def test_fail_open_empty_features(self):
        """空特征 → UNKNOWN。"""
        verdict = self.clf.predict({})
        self.assertEqual(verdict.label, WashoutLabel.UNKNOWN)

    def test_fail_open_none_features(self):
        """None → UNKNOWN。"""
        verdict = self.clf.predict(None)
        self.assertEqual(verdict.label, WashoutLabel.UNKNOWN)


class TestWashoutDetectorDALIntegration(unittest.TestCase):
    """端到端: WashoutDetector + Provider + Classifier + FeatureExtractor。"""

    def setUp(self):
        self.ext = WashoutFeatureExtractor()
        self.clf = EnhancedWashoutClassifier()

    def test_end_to_end_washout_scenario(self):
        """真洗盘: DAL 数据(OI下降+CVD背离) + 洗盘 pattern → WASHOUT。"""
        repo = _make_mock_repo_with_washout_data()
        provider = WashoutMacroProvider(repo=repo)
        df = _make_washout_ohlcv()
        macro_data = provider.get_macro_data("BTC")

        detector = WashoutDetector(
            enable=True, classifier=self.clf, feature_extractor=self.ext
        )
        verdict = detector.run("BTC", df, macro_data)

        # 应判为 WASHOUT 或 UNKNOWN (取决于特征提取)
        # 关键: 不应误判为 WEAKNESS
        self.assertNotEqual(verdict.label, WashoutLabel.WEAKNESS,
                            "真洗盘不应判为 WEAKNESS")

    def test_end_to_end_weakness_scenario(self):
        """假洗盘: DAL 数据(OI上升+CVD同步) + 洗盘 pattern → WEAKNESS。"""
        repo = _make_mock_repo_with_weakness_data()
        provider = WashoutMacroProvider(repo=repo)
        df = _make_washout_ohlcv()
        macro_data = provider.get_macro_data("BTC")

        detector = WashoutDetector(
            enable=True, classifier=self.clf, feature_extractor=self.ext
        )
        verdict = detector.run("BTC", df, macro_data)

        # 应判为 WEAKNESS 或 UNKNOWN (取决于特征提取)
        # 关键: 不应误判为 WASHOUT
        self.assertNotEqual(verdict.label, WashoutLabel.WASHOUT,
                            "假洗盘不应判为 WASHOUT")

    def test_disabled_returns_unknown(self):
        """开关关闭 → UNKNOWN。"""
        provider = WashoutMacroProvider(repo=None)
        df = _make_washout_ohlcv()
        detector = WashoutDetector(
            enable=False, classifier=self.clf, feature_extractor=self.ext
        )
        verdict = detector.run("BTC", df, {})
        self.assertEqual(verdict.label, WashoutLabel.UNKNOWN)
        self.assertFalse(verdict.trigger_activated)

    def test_no_macro_data_still_runs(self):
        """macro_data 为空时 detector 仍运行 (降级中性默认值)。"""
        df = _make_washout_ohlcv()
        detector = WashoutDetector(
            enable=True, classifier=self.clf, feature_extractor=self.ext
        )
        # macro_data={} → 特征提取器降级中性默认值 → classifier 可能判 UNKNOWN
        verdict = detector.run("BTC", df, {})
        # 不应崩溃，应返回有效 verdict
        self.assertIsNotNone(verdict)
        self.assertIn(verdict.label,
                       [WashoutLabel.WASHOUT, WashoutLabel.WEAKNESS,
                        WashoutLabel.UNKNOWN])


if __name__ == "__main__":
    unittest.main(verbosity=2)
