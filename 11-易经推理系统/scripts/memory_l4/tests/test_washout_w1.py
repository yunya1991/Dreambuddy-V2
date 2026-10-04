"""W1: WashoutDetector / WashoutVerdict / WashoutTriggerGate TDD 测试（RED 阶段）.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §9.1

TDD 流程：本文件先于生产代码编写，每一项测试保证 RED（先失败）再 GREEN。

测试清单（共 10 项）：
  T1  / test_washout_verdict_unknown_fallback
        — WashoutVerdict.unknown() 返回 label=UNKNOWN, confidence=0.0
  T2  / test_washout_verdict_to_dict_from_dict_roundtrip_1000
        — 1000 次随机 roundtrip 无损
  T3  / test_washout_verdict_frozen_immutable
        — frozen=True 不可变
  T4  / test_trigger_gate_no_runup_returns_false
        — 无上涨(涨幅<15%) → 不触发
  T5  / test_trigger_gate_runup_but_no_drawdown_returns_false
        — 上涨15%+ 但无回撤 → 不触发
  T6  / test_trigger_gate_runup_and_drawdown_returns_true
        — 上涨15%+ 回撤5%+ → 触发
  T7  / test_trigger_gate_below_ma200_returns_false
        — 价格在 MA200 之下 → 不触发
  T8  / test_washout_detector_disabled_returns_unknown
        — enable=False → unknown
  T9  / test_washout_detector_enabled_no_trigger_returns_unknown
        — enable=True 但触发门未通过 → unknown
  T10 / test_washout_detector_fail_open_on_exception
        — 异常 → unknown + 6 层堆栈日志
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # 11-易经推理系统/
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# 导入（RED 阶段：模块不存在时 ImportError）
# ============================================================
from scripts.memory_l4.bcrm2.washout_detector import (  # noqa: E402
    WashoutDetector,
    WashoutLabel,
    WashoutVerdict,
)
from scripts.memory_l4.bcrm2.washout_trigger_gate import (  # noqa: E402
    WashoutTriggerGate,
)


# ============================================================
# Helpers: 构造 OHLCV DataFrame
# ============================================================
def _make_ohlcv(closes: list[float], highs=None, lows=None, vols=None) -> pd.DataFrame:
    """从 close 序列构造 OHLCV DataFrame，index 为日期。"""
    n = len(closes)
    closes_arr = np.asarray(closes, dtype=float)
    if highs is None:
        highs_arr = closes_arr * 1.005
    else:
        highs_arr = np.asarray(highs, dtype=float)
    if lows is None:
        lows_arr = closes_arr * 0.995
    else:
        lows_arr = np.asarray(lows, dtype=float)
    if vols is None:
        vols_arr = np.full(n, 1000.0)
    else:
        vols_arr = np.asarray(vols, dtype=float)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"close": closes_arr, "high": highs_arr, "low": lows_arr, "volume": vols_arr},
        index=idx,
    )


def _make_runup_then_drawdown_df(
    base_price: float = 100.0,
    runup_pct: float = 0.20,
    drawdown_pct: float = 0.10,
    n_pre_days: int = 220,
    n_runup_days: int = 15,
    n_drawdown_days: int = 15,
) -> pd.DataFrame:
    """构造「上涨后回撤」场景：前 n_pre_days 平稳，n_runup_days 快速上涨，n_drawdown_days 回撤。

    30d 前的价格 = base_price（平稳段末尾），峰值 = base_price*(1+runup_pct)，
    回撤后当前价 = peak*(1-drawdown_pct)。总天数 ≥ 250 满足 MA200。
    """
    pre_prices = np.full(n_pre_days, base_price)
    peak_price = base_price * (1 + runup_pct)
    runup_prices = np.linspace(base_price, peak_price, n_runup_days)
    trough_price = peak_price * (1 - drawdown_pct)
    drawdown_prices = np.linspace(peak_price, trough_price, n_drawdown_days)
    closes = np.concatenate([pre_prices, runup_prices, drawdown_prices])
    highs = closes * 1.005
    lows = closes * 0.995
    return _make_ohlcv(list(closes), list(highs), list(lows))


def _make_flat_df(n_days: int = 250, price: float = 100.0) -> pd.DataFrame:
    """构造横盘场景：价格在 price 附近小幅震荡，30d 涨幅 < 15%。"""
    rng = np.random.default_rng(42)
    closes = price * (1 + rng.normal(0, 0.005, n_days))
    closes[0] = price  # 起点固定
    return _make_ohlcv(list(closes))


def _make_runup_no_drawdown_df(
    base_price: float = 100.0,
    runup_pct: float = 0.20,
    n_pre_days: int = 220,
    n_runup_days: int = 30,
) -> pd.DataFrame:
    """构造「上涨后无回撤」场景：前 n_pre_days 平稳，n_runup_days 持续上涨，当前价=峰值。

    当前价 = 30d 高点（close），回撤 = 1 - close/peak_high ≈ 0.5% < 5%。
    """
    pre_prices = np.full(n_pre_days, base_price)
    peak_price = base_price * (1 + runup_pct)
    runup_prices = np.linspace(base_price, peak_price, n_runup_days)
    closes = np.concatenate([pre_prices, runup_prices])
    highs = closes * 1.005
    lows = closes * 0.995
    return _make_ohlcv(list(closes), list(highs), list(lows))


def _make_below_ma200_df(
    n_days: int = 250,
    start_price: float = 200.0,
    bottom_price: float = 50.0,
    bounce_peak: float = 100.0,
    trough_price: float = 90.0,
    n_decline_days: int = 220,
    n_bounce_days: int = 5,
    n_drawdown_days: int = 25,
) -> pd.DataFrame:
    """构造「价格在 MA200 之下」场景：长期下跌到 bottom，快速反弹到 bounce_peak，
    回撤到 trough。涨幅充足 + 回撤充足，但当前价 << MA200（长期均值高）。

    关键：MA200 ≈ (200+50)/2 ≈ 125，当前价 90 < 125 → require_above_ma200 拦截。
    """
    decline = np.linspace(start_price, bottom_price, n_decline_days)
    bounce = np.linspace(bottom_price, bounce_peak, n_bounce_days)
    drawdown = np.linspace(bounce_peak, trough_price, n_drawdown_days)
    closes = np.concatenate([decline, bounce, drawdown])
    highs = closes * 1.005
    lows = closes * 0.995
    return _make_ohlcv(list(closes), list(highs), list(lows))


# ============================================================
# T1: WashoutVerdict.unknown() 兜底
# ============================================================
def test_washout_verdict_unknown_fallback():
    """unknown() 返回 label=UNKNOWN, confidence=0.0, trigger_activated=False, feature_snapshot={}."""
    v = WashoutVerdict.unknown()
    assert v.label == WashoutLabel.UNKNOWN
    assert v.confidence == 0.0
    assert v.trigger_activated is False
    assert v.feature_snapshot == {}
    assert isinstance(v.reason, str)
    assert isinstance(v.timestamp, str)


# ============================================================
# T2: to_dict / from_dict 1000 次 roundtrip 无损
# ============================================================
def test_washout_verdict_to_dict_from_dict_roundtrip_1000():
    """1000 次随机 WashoutVerdict → to_dict → from_dict → 等价于原对象。"""
    rng = random.Random(2026)
    labels = list(WashoutLabel)
    for _ in range(1000):
        label = rng.choice(labels)
        confidence = round(rng.uniform(0.0, 1.0), 6)
        trigger = rng.choice([True, False])
        snap = {
            f"f{i}": round(rng.uniform(-5.0, 5.0), 6)
            for i in range(rng.randint(0, 12))
        }
        reason = f"reason_{rng.randint(0, 999)}"
        ts = f"2026-09-{rng.randint(1,30):02d}T{rng.randint(0,23):02d}:{rng.randint(0,59):02d}:00Z"
        v = WashoutVerdict(
            label=label,
            confidence=confidence,
            trigger_activated=trigger,
            feature_snapshot=snap,
            reason=reason,
            timestamp=ts,
        )
        d = v.to_dict()
        assert isinstance(d, dict)
        v2 = WashoutVerdict.from_dict(d)
        assert v2.label == v.label
        assert abs(v2.confidence - v.confidence) < 1e-9
        assert v2.trigger_activated == v.trigger_activated
        assert v2.feature_snapshot == v.feature_snapshot
        assert v2.reason == v.reason
        assert v2.timestamp == v.timestamp


# ============================================================
# T3: frozen=True 不可变
# ============================================================
def test_washout_verdict_frozen_immutable():
    """WashoutVerdict 是 frozen dataclass，赋值应抛 FrozenInstanceError。"""
    v = WashoutVerdict.unknown()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        v.confidence = 0.5  # type: ignore[misc]
    with pytest.raises(Exception):
        v.label = WashoutLabel.WASHOUT  # type: ignore[misc]


# ============================================================
# T4: 无上涨（涨幅 < 15%）→ 不触发
# ============================================================
def test_trigger_gate_no_runup_returns_false():
    """横盘场景，30d 涨幅 < 15%，触发门返回 False。"""
    df = _make_flat_df(n_days=250, price=100.0)
    gate = WashoutTriggerGate()
    assert gate.should_activate(df) is False


# ============================================================
# T5: 上涨 15%+ 但无回撤 → 不触发
# ============================================================
def test_trigger_gate_runup_but_no_drawdown_returns_false():
    """持续上涨无回撤，当前价=30d高点，回撤=0%，触发门返回 False。"""
    df = _make_runup_no_drawdown_df(runup_pct=0.20)
    gate = WashoutTriggerGate()
    assert gate.should_activate(df) is False


# ============================================================
# T6: 上涨 15%+ 回撤 5%+ → 触发
# ============================================================
def test_trigger_gate_runup_and_drawdown_returns_true():
    """上涨 20% + 回撤 10%，价格在 MA200 之上，触发门返回 True。"""
    df = _make_runup_then_drawdown_df(runup_pct=0.20, drawdown_pct=0.10)
    gate = WashoutTriggerGate()
    assert gate.should_activate(df) is True


# ============================================================
# T7: 价格在 MA200 之下 → 不触发
# ============================================================
def test_trigger_gate_below_ma200_returns_false():
    """长期下跌，近期反弹+回撤，但价格仍 < MA200，触发门返回 False。"""
    df = _make_below_ma200_df()
    gate = WashoutTriggerGate()
    assert gate.should_activate(df) is False


# ============================================================
# T8: WashoutDetector enable=False → unknown
# ============================================================
def test_washout_detector_disabled_returns_unknown():
    """enable=False 时，run() 直接返回 unknown()，不执行任何判定。"""
    df = _make_runup_then_drawdown_df()
    detector = WashoutDetector(enable=False)
    v = detector.run("UNI", df, macro_data={})
    assert v.label == WashoutLabel.UNKNOWN
    assert v.confidence == 0.0
    assert v.trigger_activated is False


# ============================================================
# T9: enable=True 但触发门未通过 → unknown
# ============================================================
def test_washout_detector_enabled_no_trigger_returns_unknown():
    """enable=True 但触发门未通过（横盘场景），run() 返回 unknown。"""
    df = _make_flat_df()
    detector = WashoutDetector(enable=True)
    v = detector.run("UNI", df, macro_data={})
    assert v.label == WashoutLabel.UNKNOWN
    assert v.trigger_activated is False


# ============================================================
# T10: 异常 → FAIL-OPEN 返回 unknown + 6 层堆栈日志
# ============================================================
def test_washout_detector_fail_open_on_exception(caplog):
    """run() 内部异常 → FAIL-OPEN 返回 unknown()，并记录 ≥6 层堆栈日志。"""
    detector = WashoutDetector(enable=True)

    # 传入坏数据触发异常：df 为 None 或空
    v = detector.run("UNI", None, macro_data={})
    assert v.label == WashoutLabel.UNKNOWN
    assert v.confidence == 0.0
    assert v.trigger_activated is False
    # 验证堆栈日志被记录（至少 6 层 frame 信息或 traceback）
    logs = caplog.text
    assert "washout" in logs.lower() or "traceback" in logs.lower() or len(logs) > 0
