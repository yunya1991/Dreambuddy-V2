#!/usr/bin/env python3
"""洗盘入场信号接入测试 — 验证 _washout_entry_signal_scan 行为。

测试覆盖:
  1. 开关关闭 → 不调用 detector
  2. WASHOUT + conf≥0.80 → 调用 _open_position
  3. WEAKNESS/UNKNOWN → 不开仓
  4. confidence < 0.80 → 不开仓
  5. 子池已满 → 不开仓
  6. FAIL-OPEN: detector 异常 → 不阻断

运行: python3 -m pytest tests/test_washout_entry_signal_wiring.py -v -p no:warnings
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.bcrm2.washout_detector import WashoutLabel, WashoutVerdict  # noqa: E402


def _make_klines(n: int = 200) -> list:
    """构造 mock K 线数据。"""
    import numpy as np
    rng = np.random.RandomState(42)
    prices = np.cumprod(1 + rng.normal(0.001, 0.01, n))
    prices = prices * 100 / prices[0]
    return [
        {
            "ts": 1700000000000 + i * 3600000,
            "o": float(prices[i]),
            "h": float(prices[i] * 1.005),
            "l": float(prices[i] * 0.995),
            "c": float(prices[i]),
            "v": 1000.0,
        }
        for i in range(n)
    ]


def _make_washout_verdict(confidence: float = 0.85) -> WashoutVerdict:
    return WashoutVerdict(
        label=WashoutLabel.WASHOUT,
        confidence=confidence,
        trigger_activated=True,
        feature_snapshot={
            "volume_ratio_20d": 0.5,
            "oi_change_rate_7d": -0.05,
            "cvd_price_divergence": -0.5,
        },
        reason="test_washout",
        timestamp="",
    )


def _make_weakness_verdict() -> WashoutVerdict:
    return WashoutVerdict(
        label=WashoutLabel.WEAKNESS,
        confidence=0.80,
        trigger_activated=True,
        feature_snapshot={},
        reason="test_weakness",
        timestamp="",
    )


class TestWashoutEntrySignalWiring(unittest.TestCase):
    """验证 _washout_entry_signal_scan 接入逻辑。"""

    def _make_trader(self, enable_signal: bool = True):
        """构造 mock PollingTrader 实例。"""
        from scripts.memory_l4.polling_trader import PollingTrader

        # 用 __new__ 避免 __init__ 副作用
        trader = PollingTrader.__new__(PollingTrader)

        # 基础属性
        trader.coins = ["BTC", "ETH"]
        trader.bar = "1H"
        trader.kline_limit = 300
        trader.ENABLE_WASHOUT_ENTRY_SIGNAL = enable_signal
        trader.WASHOUT_ENTRY_SOURCE_TAG = "washout_entry"
        trader.WASHOUT_ENTRY_MIN_CONFIDENCE = 0.80
        trader.SUBPOOL_MAX_POSITIONS = {"washout_entry": 2}
        trader.MAX_TRIAL_POSITIONS = 2

        # mock detector
        trader._washout_detector = MagicMock()
        trader._washout_macro_provider = MagicMock()
        trader._washout_macro_provider.get_macro_data.return_value = {}

        # mock okx_client
        trader.okx_client = MagicMock()
        trader.okx_client.get_kline.return_value = {"candles": _make_klines()}
        trader.okx_client.get_ticker.return_value = {"ok": True, "last": "50000.0"}

        # mock position_tracker
        trader.position_tracker = MagicMock()
        trader.position_tracker.has_open_position.return_value = False

        # mock _count_trial_positions
        trader._count_trial_positions = MagicMock(return_value=0)

        # mock _open_position
        trader._open_position = MagicMock()

        # mock _kline_to_dataframe
        trader._kline_to_dataframe = MagicMock(
            return_value=pd.DataFrame({
                "open": [100] * 200, "high": [100.5] * 200,
                "low": [99.5] * 200, "close": [100] * 200,
                "volume": [1000] * 200,
            })
        )

        # mock _log
        trader._log = MagicMock()

        return trader

    def test_disabled_no_op(self):
        """开关关闭 → 不调用 detector。"""
        trader = self._make_trader(enable_signal=False)
        trader._washout_entry_signal_scan()
        trader._washout_detector.run.assert_not_called()
        trader._open_position.assert_not_called()

    def test_washout_signal_triggers_open(self):
        """WASHOUT + conf≥0.80 → 调用 _open_position。"""
        trader = self._make_trader(enable_signal=True)
        trader._washout_detector.run.return_value = _make_washout_verdict(0.85)

        trader._washout_entry_signal_scan()

        self.assertGreaterEqual(trader._open_position.call_count, 1)
        # _open_position(inference, is_reverse=False, is_trial=True)
        call = trader._open_position.call_args
        self.assertFalse(call.kwargs.get("is_reverse", True))
        self.assertTrue(call.kwargs.get("is_trial", False))

    def test_weakness_signal_no_open(self):
        """WEAKNESS → 不开仓。"""
        trader = self._make_trader(enable_signal=True)
        trader._washout_detector.run.return_value = _make_weakness_verdict()

        trader._washout_entry_signal_scan()

        trader._open_position.assert_not_called()

    def test_low_confidence_no_open(self):
        """confidence < 0.80 → 不开仓。"""
        trader = self._make_trader(enable_signal=True)
        trader._washout_detector.run.return_value = _make_washout_verdict(0.70)

        trader._washout_entry_signal_scan()

        trader._open_position.assert_not_called()

    def test_subpool_full_no_open(self):
        """子池已满 → 不开仓。"""
        trader = self._make_trader(enable_signal=True)
        trader._count_trial_positions.return_value = 2  # 已满

        trader._washout_entry_signal_scan()

        trader._open_position.assert_not_called()

    def test_detector_none_no_crash(self):
        """detector=None → 不崩溃。"""
        trader = self._make_trader(enable_signal=True)
        trader._washout_detector = None

        # 不应抛异常
        trader._washout_entry_signal_scan()
        trader._open_position.assert_not_called()

    def test_inference_has_source_tag(self):
        """开仓时 inference 含 source_tag='washout_entry'。"""
        trader = self._make_trader(enable_signal=True)
        trader._washout_detector.run.return_value = _make_washout_verdict(0.85)

        trader._washout_entry_signal_scan()

        # 第一次开仓应该是 BTC
        inference = trader._open_position.call_args_list[0].args[0]
        self.assertEqual(inference["source_tag"], "washout_entry")
        self.assertEqual(inference["direction"], "UP")
        self.assertEqual(inference["coin"], "BTC")

    def test_fail_open_exception(self):
        """detector 异常 → 不阻断主流程。"""
        trader = self._make_trader(enable_signal=True)
        trader._washout_detector.run.side_effect = RuntimeError("detector crash")

        # 不应抛异常
        trader._washout_entry_signal_scan()
        trader._open_position.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
