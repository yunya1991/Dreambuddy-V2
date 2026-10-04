"""RED 测试 — PumpDumpEndingDetector (拉高出货结束信号判定器).

Spec: 阶段2 拉高出货基因组设计 (镜像阶段1洗盘基因组).

阶段2 新增文件 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/pump_dump_ending_detector.py
      — PumpDumpEndingSignal + PumpDumpEndingDetector

设计原则 (硬约束):
  - HC-P3: 任何异常 → activated=False (FAIL-OPEN)
  - 规则化条件 (全部满足才激活):
      条件1: RSI(14) > 70 (超买, 买盘枯竭)
      条件2: 成交量从峰值萎缩 (卖压累积) 或 量价背离
      条件3: 价格见顶 (上影线 > 实体 或 收盘价 < 前根收盘价)
      条件4: OI 下降 (聪明钱离场, FAIL-OPEN 数据缺失时放行)

TDD 测试清单:
  T1  / test_signal_dataclass_fields
  T2  / test_not_activated
  T3  / test_rsi_overbought
  T4  / test_volume_decline_from_peak
  T5  / test_price_topping_upper_shadow
  T6  / test_price_topping_close_below_prev
  T7  / test_oi_declining
  T8  / test_all_conditions_met
  T9  / test_partial_conditions_not_met
  T10 / test_oi_missing_fail_open
  T11 / test_empty_df_fail_open
  T12 / test_exception_fail_open
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"
for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dreamos.evolution.pump_dump_ending_detector import (  # noqa: E402
    PumpDumpEndingSignal,
    PumpDumpEndingDetector,
)


def _make_df(n=30, rsi_overbought=False, volume_decline=False,
             topping_upper=False, topping_close_below=False, seed=42):
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    if rsi_overbought:
        closes = [100.0 * (1 + 0.01 * i) for i in range(n)]
    else:
        closes = [100.0 + rng.randn() * 0.5 for _ in range(n)]
    opens = [c + rng.randn() * 0.3 for c in closes]
    highs = [max(o, c) + abs(rng.randn()) * 0.5 for o, c in zip(opens, closes)]
    lows = [min(o, c) - abs(rng.randn()) * 0.5 for o, c in zip(opens, closes)]
    volumes = [1000.0 + rng.randn() * 50 for _ in range(n)]
    if volume_decline:
        peak = max(volumes[:-5])
        volumes[-1] = peak * 0.5
        volumes[-2] = peak * 0.6
    if topping_upper:
        opens[-1] = closes[-1] - 1.0
        highs[-1] = opens[-1] + 3.0
        lows[-1] = closes[-1] - 0.5
    if topping_close_below:
        closes[-1] = closes[-2] - 1.0
        opens[-1] = closes[-1] + 0.5
    return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                         "close": closes, "volume": volumes}, index=idx)


class TestSignalDataclass:
    def test_signal_dataclass_fields(self):
        sig = PumpDumpEndingSignal(activated=True, confidence=0.8, reason="test",
                                    timestamp="2026-01-01T00:00:00+00:00")
        assert sig.activated is True
        assert 0.0 <= sig.confidence <= 1.0

    def test_not_activated(self):
        sig = PumpDumpEndingSignal.not_activated("no_overbought")
        assert sig.activated is False
        assert sig.confidence == 0.0


class TestConditions:
    def test_rsi_overbought(self):
        df = _make_df(rsi_overbought=True)
        det = PumpDumpEndingDetector()
        rsi = det._compute_rsi(df["close"], 14)
        assert rsi > 70.0

    def test_volume_decline_from_peak(self):
        df = _make_df(volume_decline=True)
        det = PumpDumpEndingDetector()
        assert det._check_volume_decline(df) is True

    def test_price_topping_upper_shadow(self):
        df = _make_df(topping_upper=True)
        det = PumpDumpEndingDetector()
        assert det._check_price_topping(df) is True

    def test_price_topping_close_below_prev(self):
        df = _make_df(topping_close_below=True)
        det = PumpDumpEndingDetector()
        assert det._check_price_topping(df) is True

    def test_oi_declining(self):
        macro = {"oi_current": 100.0, "oi_prev": 102.0}
        det = PumpDumpEndingDetector()
        assert det._check_oi_declining(macro) is True


class TestFullFlow:
    def test_all_conditions_met(self):
        df = _make_df(rsi_overbought=True, volume_decline=True, topping_upper=True)
        macro = {"oi_current": 100.0, "oi_prev": 102.0}
        det = PumpDumpEndingDetector()
        sig = det.check(df, macro)
        assert sig.activated is True

    def test_partial_not_met(self):
        df = _make_df(rsi_overbought=True)  # only RSI
        macro = {"oi_current": 100.0, "oi_prev": 102.0}
        det = PumpDumpEndingDetector()
        sig = det.check(df, macro)
        assert sig.activated is False


class TestFailOpen:
    def test_oi_missing_fail_open(self):
        df = _make_df(rsi_overbought=True, volume_decline=True, topping_upper=True)
        det = PumpDumpEndingDetector()
        sig = det.check(df, {})
        assert sig.activated is True

    def test_empty_df(self):
        det = PumpDumpEndingDetector()
        sig = det.check(pd.DataFrame(), {})
        assert sig.activated is False

    def test_exception(self):
        det = PumpDumpEndingDetector()
        sig = det.check(None, {})  # type: ignore
        assert sig.activated is False
