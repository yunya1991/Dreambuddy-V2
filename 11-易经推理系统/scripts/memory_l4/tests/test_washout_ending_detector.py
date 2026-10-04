"""RED 测试 — WashoutEndingDetector (洗盘结束信号判定器).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.1

阶段1 新增文件 (纯新增):
  - 1-ARCHITECTURE/dreamos/evolution/washout_ending_detector.py
      — EndingSignal dataclass + WashoutEndingDetector (规则化先行)

设计原则 (硬约束):
  - HC-G3: EndingDetector 任何异常 → activated=False (FAIL-OPEN)
  - 规则化条件 (全部满足才激活):
      条件1: 连续 2 根 K 线成交量萎缩 ≥40% (相对前 10 根均值)
      条件2: RSI(14) < 35 (超卖)
      条件3: 价格企稳 (下影线 > 实体 或 收盘价 > 前根收盘价)
      条件4: OI 不再下降 (OI 变化率 > -0.5%, FAIL-OPEN 数据缺失时放行)

TDD 测试清单:
  T1  / test_ending_signal_dataclass_fields                    — EndingSignal 字段
  T2  / test_ending_signal_not_activated                      — not_activated() 静态方法
  T3  / test_volume_shrinkage_detected                        — 条件1: 成交量萎缩≥40%
  T4  / test_rsi_oversold_detected                            — 条件2: RSI<35
  T5  / test_price_stabilization_lower_shadow                — 条件3a: 下影线>实体
  T6  / test_price_stabilization_close_above_prev             — 条件3b: 收盘>前根收盘
  T7  / test_oi_not_declining                                 — 条件4: OI 变化率>-0.5%
  T8  / test_all_conditions_met_activated                     — 全部满足→activated=True
  T9  / test_partial_conditions_not_activated                  — 部分满足→activated=False
  T10 / test_oi_missing_data_fail_open                        — OI 缺失→FAIL-OPEN 放行
  T11 / test_empty_df_fail_open                               — 空 DataFrame→activated=False
  T12 / test_exception_fail_open                              — 异常→activated=False
  T13 / test_confidence_range                                 — confidence ∈ [0,1]
  T14 / test_no_llm_dependency                                — grep 确认无 LLM 调用
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import pytest

# ============================================================
# sys.path 设置
# ============================================================
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_SCRIPTS_ROOT = _THIS_DIR.parent.parent
_PROJECT_ROOT = _BCRM2_SCRIPTS_ROOT.parent.parent
_ARCH_ROOT = _PROJECT_ROOT / "1-ARCHITECTURE"

for _p in (_BCRM2_SCRIPTS_ROOT, _ARCH_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================
# 导入（RED 阶段：模块不存在时 ImportError）
# ============================================================
from dreamos.evolution.washout_ending_detector import (  # noqa: E402
    EndingSignal,
    WashoutEndingDetector,
)


# ============================================================
# 辅助函数: 构造测试用 OHLCV DataFrame
# ============================================================
def _make_df(
    n: int = 30,
    base_close: float = 100.0,
    volume_base: float = 1000.0,
    shrink_last_2: bool = False,
    rsi_oversold: bool = False,
    stabilize_lower_shadow: bool = False,
    stabilize_close_above_prev: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    """构造测试用 OHLCV DataFrame.

    Args:
        n: K 线数量 (默认 30)
        base_close: 基础收盘价
        volume_base: 基础成交量
        shrink_last_2: 最后 2 根成交量萎缩≥40%
        rsi_oversold: 使 RSI<35 (连续下跌)
        stabilize_lower_shadow: 最后 1 根下影线>实体
        stabilize_close_above_prev: 最后 1 根收盘>前根收盘
    """
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="1H")

    if rsi_oversold:
        # 连续下跌使 RSI<35
        closes = [base_close * (1 - 0.01 * i) for i in range(n)]
    else:
        closes = [base_close + rng.randn() * 0.5 for _ in range(n)]

    opens = [c + rng.randn() * 0.3 for c in closes]
    highs = [max(o, c) + abs(rng.randn()) * 0.5 for o, c in zip(opens, closes)]
    lows = [min(o, c) - abs(rng.randn()) * 0.5 for o, c in zip(opens, closes)]

    volumes = [volume_base + rng.randn() * 50 for _ in range(n)]

    if shrink_last_2:
        # 最后 2 根成交量萎缩 ≥40%
        avg_prev_10 = sum(volumes[-12:-2]) / 10
        volumes[-1] = avg_prev_10 * 0.55  # 萎缩 45%
        volumes[-2] = avg_prev_10 * 0.55

    if stabilize_lower_shadow:
        # 最后 1 根: 下影线 > 实体
        opens[-1] = closes[-1] + 1.0  # open above close → 阴线实体小
        lows[-1] = closes[-1] - 3.0  # 长下影线
        highs[-1] = opens[-1] + 0.5

    if stabilize_close_above_prev:
        # 最后 1 根收盘 > 前根收盘
        closes[-1] = closes[-2] + 1.0
        opens[-1] = closes[-1] - 0.5

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }, index=idx)
    return df


def _make_macro_data(oi_declining: bool = False, oi_missing: bool = False) -> Dict:
    """构造宏观特征字典."""
    if oi_missing:
        return {}
    if oi_declining:
        return {"oi_current": 100.0, "oi_prev": 102.0}  # OI 下降 2%
    return {"oi_current": 100.0, "oi_prev": 99.5}  # OI 上升


# ============================================================
# T1: EndingSignal dataclass 字段
# ============================================================
class TestEndingSignalDataclass:
    def test_ending_signal_dataclass_fields(self):
        """T1: EndingSignal 包含 activated, confidence, reason, timestamp."""
        sig = EndingSignal(
            activated=True,
            confidence=0.85,
            reason="volume_shrink+rsi_oversold+price_stabilize+oi_ok",
            timestamp="2026-09-22T00:00:00+00:00",
        )
        assert sig.activated is True
        assert 0.0 <= sig.confidence <= 1.0
        assert isinstance(sig.reason, str)
        assert isinstance(sig.timestamp, str)

    def test_ending_signal_not_activated(self):
        """T2: not_activated() 返回 activated=False."""
        sig = EndingSignal.not_activated("no_volume_shrinkage")
        assert sig.activated is False
        assert sig.confidence == 0.0
        assert "no_volume_shrinkage" in sig.reason or sig.reason != ""


# ============================================================
# T3-T7: 单条件测试
# ============================================================
class TestEndingDetectorConditions:
    def test_volume_shrinkage_detected(self):
        """T3: 成交量萎缩≥40% 被检测到."""
        df = _make_df(shrink_last_2=True)
        detector = WashoutEndingDetector()
        # 内部方法检测成交量萎缩
        result = detector._check_volume_shrinkage(df)
        assert result is True

    def test_rsi_oversold_detected(self):
        """T4: RSI(14)<35 被检测到."""
        df = _make_df(rsi_oversold=True, n=30)
        detector = WashoutEndingDetector()
        rsi = detector._compute_rsi(df["close"], 14)
        assert rsi < 35.0

    def test_price_stabilization_lower_shadow(self):
        """T5: 下影线>实体 被检测到."""
        df = _make_df(stabilize_lower_shadow=True)
        detector = WashoutEndingDetector()
        result = detector._check_price_stabilization(df)
        assert result is True

    def test_price_stabilization_close_above_prev(self):
        """T6: 收盘>前根收盘 被检测到."""
        df = _make_df(stabilize_close_above_prev=True)
        detector = WashoutEndingDetector()
        result = detector._check_price_stabilization(df)
        assert result is True

    def test_oi_not_declining(self):
        """T7: OI 变化率>-0.5% 被检测到."""
        macro = _make_macro_data(oi_declining=False)
        detector = WashoutEndingDetector()
        result = detector._check_oi_stabilization(macro)
        assert result is True


# ============================================================
# T8-T9: 全条件 / 部分条件
# ============================================================
class TestEndingDetectorFullFlow:
    def test_all_conditions_met_activated(self):
        """T8: 全部条件满足 → activated=True."""
        df = _make_df(
            shrink_last_2=True,
            rsi_oversold=True,
            stabilize_lower_shadow=True,
            n=30,
        )
        macro = _make_macro_data(oi_declining=False)
        detector = WashoutEndingDetector()
        signal = detector.check(df, macro)
        assert signal.activated is True
        assert signal.confidence > 0.0

    def test_partial_conditions_not_activated(self):
        """T9: 仅部分条件满足 → activated=False."""
        # 只有成交量萎缩, RSI 不超卖
        df = _make_df(shrink_last_2=True, n=30)
        macro = _make_macro_data(oi_declining=False)
        detector = WashoutEndingDetector()
        signal = detector.check(df, macro)
        assert signal.activated is False


# ============================================================
# T10-T12: FAIL-OPEN 测试
# ============================================================
class TestEndingDetectorFailOpen:
    def test_oi_missing_data_fail_open(self):
        """T10: OI 数据缺失 → FAIL-OPEN 放行 (条件4 通过)."""
        df = _make_df(
            shrink_last_2=True,
            rsi_oversold=True,
            stabilize_lower_shadow=True,
            n=30,
        )
        macro = _make_macro_data(oi_missing=True)  # OI 缺失
        detector = WashoutEndingDetector()
        signal = detector.check(df, macro)
        # OI 缺失 → 条件4 FAIL-OPEN 放行 → 其余条件满足 → activated=True
        assert signal.activated is True

    def test_empty_df_fail_open(self):
        """T11: 空 DataFrame → activated=False (不抛异常)."""
        df = pd.DataFrame()
        macro = _make_macro_data()
        detector = WashoutEndingDetector()
        signal = detector.check(df, macro)
        assert signal.activated is False

    def test_exception_fail_open(self):
        """T12: 内部异常 → activated=False (不抛异常)."""
        # 传入非 DataFrame 触发异常
        detector = WashoutEndingDetector()
        signal = detector.check(None, {})  # type: ignore
        assert signal.activated is False

    def test_confidence_range(self):
        """T13: confidence 始终 ∈ [0, 1]."""
        df = _make_df(
            shrink_last_2=True,
            rsi_oversold=True,
            stabilize_lower_shadow=True,
            n=30,
        )
        macro = _make_macro_data(oi_declining=False)
        detector = WashoutEndingDetector()
        signal = detector.check(df, macro)
        assert 0.0 <= signal.confidence <= 1.0

        # not_activated 路径
        sig2 = EndingSignal.not_activated("test")
        assert 0.0 <= sig2.confidence <= 1.0


# ============================================================
# T14: 无 LLM 依赖
# ============================================================
class TestNoLLMDependency:
    def test_no_llm_dependency(self):
        """T14: 源码中无 LLM/openai/anthropic 调用."""
        source_path = (
            _ARCH_ROOT / "dreamos" / "evolution" / "washout_ending_detector.py"
        )
        if source_path.exists():
            source = source_path.read_text()
            for kw in ("import openai", "from openai", "import anthropic", "from anthropic",
                        "chat.completions.create", "messages.create"):
                assert kw not in source.lower(), f"发现 LLM 依赖: {kw}"
