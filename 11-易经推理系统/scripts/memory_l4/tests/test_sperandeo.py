"""test_sperandeo.py — P1.1 Sperandeo 1-2-3 渐进式趋势反转调整 TDD 测试

Spec §2.4 规则2：道氏 123 法则渐进式评分（不一次性切换）。

牛市反转（下降趋势 → 上升趋势）:
  ① close 突破下降趋势线(SH_prev→SH_last) → Trend +0.33
  ② 回撤不破前低(SL_last) → Trend +0.33
  ③ close 突破前高(SH_last) → Trend +0.34
  三条渐进累计 +1.0。不满足 = +0，不反向扣分。

运行:
    cd 11-易经推理系统
    python -m pytest scripts/memory_l4/tests/test_sperandeo.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# —— 路径处理
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4", "tests 需放在 memory_l4/tests 下"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

from bcrm2.score_composer import ScoreComposer, _trend_line_val  # noqa: E402


# ================================================================
# 辅助函数
# ================================================================

def _build_df(high, low, close):
    """从 high/low/close 数组构建 OHLCV DataFrame。"""
    n = len(close)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open":  np.asarray(close, dtype=float),
        "high":  np.asarray(high, dtype=float),
        "low":   np.asarray(low, dtype=float),
        "close": np.asarray(close, dtype=float),
        "volume": np.ones(n) * 1e6,
    }, index=idx)


# ================================================================
# 1. 牛市反转测试
# ================================================================
def test_sperandeo_bullish_reversal():
    """构造下降趋势→牛市反转序列，断言三条条件渐进累计 +1.0。

    swing_window=3, 构造明确的 zigzag：
      SH_prev (bar 3,  high=100)  — 下降趋势线第一点
      SL      (bar 7,  low=50)    — 中间 swing low
      SH_last (bar 10, high=80)   — 下降趋势线第二点 (80 < 100)
      SL_last (bar 13, low=45)    — 最近 swing low

      bar 14: close=70 > 趋势线(68.57)  → 条件① +0.33
      bar 15: close=65 < close[14]=70 (回撤), low=55 > SL_last=45 → 条件② +0.33
      bar 16: close=85 > SH_last=80     → 条件③ +0.34  (累计 +1.00)
    """
    swing_window = 3
    high =  [90, 92, 95, 100, 95, 92, 90, 70, 75, 78, 80, 78, 75, 72, 75, 80, 85]
    low =   [93, 90, 92, 95,  80, 75, 70, 50, 55, 58, 60, 58, 55, 45, 50, 55, 60]
    close = [88, 90, 93, 97,  82, 77, 72, 55, 60, 65, 70, 65, 60, 50, 70, 65, 85]
    n = len(close)

    # 基础 trend_smooth（全 0，便于隔离 Sperandeo 调整量）
    base_trend = np.zeros(n, dtype=float)
    level_smooth = np.zeros(n, dtype=float)

    result = ScoreComposer.apply_sperandeo_adjustment(
        level_smooth, base_trend,
        np.array(high, dtype=float),
        np.array(low, dtype=float),
        np.array(close, dtype=float),
        swing_window=swing_window,
    )

    # 反转前 (bar 0-13)：无调整
    for i in range(14):
        assert abs(result[i]) < 1e-9, f"bar {i} 反转前应无调整，实际={result[i]:.4f}"

    # bar 14: 条件① → +0.33
    assert abs(result[14] - 0.33) < 1e-6, f"bar 14 条件① 应 +0.33，实际={result[14]:.4f}"

    # bar 15: 条件② → 累计 +0.66
    assert abs(result[15] - 0.66) < 1e-6, f"bar 15 条件② 应累计 0.66，实际={result[15]:.4f}"

    # bar 16: 条件③ → 累计 +1.00
    assert abs(result[16] - 1.00) < 1e-6, f"bar 16 条件③ 应累计 1.00，实际={result[16]:.4f}"


# ================================================================
# 2. 熊市反转测试
# ================================================================
def test_sperandeo_bearish_reversal():
    """构造上升趋势→熊市反转序列，断言三条条件渐进累计 -1.0。

    swing_window=3, 构造明确的 zigzag：
      SL_prev (bar 3,  low=40)    — 上升趋势线第一点
      SH      (bar 7,  high=75)   — 中间 swing high
      SL_last (bar 10, low=48)    — 上升趋势线第二点 (48 > 40)
      SH_last (bar 13, high=85)   — 最近 swing high

      bar 14: close=50 < 趋势线(52.57)  → 条件① -0.33
      bar 15: close=55 > close[14]=50 (反弹), high=75 < SH_last=85 → 条件② -0.33
      bar 16: close=40 < SL_last=48      → 条件③ -0.34  (累计 -1.00)
    """
    swing_window = 3
    high =  [60, 62, 64, 55, 50, 45, 42, 75, 70, 65, 60, 70, 80, 85, 80, 75, 70]
    low =   [55, 50, 48, 40, 45, 50, 55, 52, 55, 58, 48, 55, 60, 65, 70, 65, 60]
    close = [58, 55, 50, 45, 48, 52, 48, 60, 65, 62, 55, 65, 75, 80, 50, 55, 40]
    n = len(close)

    base_trend = np.zeros(n, dtype=float)
    level_smooth = np.zeros(n, dtype=float)

    result = ScoreComposer.apply_sperandeo_adjustment(
        level_smooth, base_trend,
        np.array(high, dtype=float),
        np.array(low, dtype=float),
        np.array(close, dtype=float),
        swing_window=swing_window,
    )

    # 反转前 (bar 0-13)：无调整
    for i in range(14):
        assert abs(result[i]) < 1e-9, f"bar {i} 反转前应无调整，实际={result[i]:.4f}"

    # bar 14: 条件① → -0.33
    assert abs(result[14] - (-0.33)) < 1e-6, f"bar 14 条件① 应 -0.33，实际={result[14]:.4f}"

    # bar 15: 条件② → 累计 -0.66
    assert abs(result[15] - (-0.66)) < 1e-6, f"bar 15 条件② 应累计 -0.66，实际={result[15]:.4f}"

    # bar 16: 条件③ → 累计 -1.00
    assert abs(result[16] - (-1.00)) < 1e-6, f"bar 16 条件③ 应累计 -1.00，实际={result[16]:.4f}"


# ================================================================
# 3. 无反转 — trend 不变
# ================================================================
def test_sperandeo_no_reversal_no_change():
    """单调上升趋势无反转信号时，trend 不变。"""
    n = 30
    close = np.linspace(100, 200, n)
    high = close * 1.01
    low = close * 0.99

    base_trend = np.ones(n, dtype=float) * 1.5  # 非零基础值
    level_smooth = np.zeros(n, dtype=float)

    result = ScoreComposer.apply_sperandeo_adjustment(
        level_smooth, base_trend,
        high, low, close,
        swing_window=3,
    )

    # 全部不变
    np.testing.assert_allclose(result, base_trend, atol=1e-9,
                               err_msg="单调趋势无反转时 trend 不应变")


# ================================================================
# 4. compose() 集成测试
# ================================================================
def test_sperandeo_compose_integration():
    """完整 ScoreComposer.compose() 流程：sperandeo_enabled=True/False 对比。"""
    # 构造足够长的序列（250 根），前段平坦后段含牛市反转
    n_flat = 220
    n_rev = 17  # 反转段长度（与牛市测试一致）

    # 平坦段：close=100，high/low 微幅波动
    flat_close = np.full(n_flat, 100.0)
    flat_high = flat_close * 1.005
    flat_low = flat_close * 0.995

    # 反转段（复用牛市测试数据）
    rev_high =  [90, 92, 95, 100, 95, 92, 90, 70, 75, 78, 80, 78, 75, 72, 75, 80, 85]
    rev_low =   [93, 90, 92, 95,  80, 75, 70, 50, 55, 58, 60, 58, 55, 45, 50, 55, 60]
    rev_close = [88, 90, 93, 97,  82, 77, 72, 55, 60, 65, 70, 65, 60, 50, 70, 65, 85]

    # 衔接：反转段的起点接近平坦段的终点
    offset = flat_close[-1] - rev_high[0]
    rev_high = [h + offset for h in rev_high]
    rev_low = [l + offset for l in rev_low]
    rev_close = [c + offset for c in rev_close]

    close = np.concatenate([flat_close, rev_close])
    high = np.concatenate([flat_high, np.array(rev_high, dtype=float)])
    low = np.concatenate([flat_low, np.array(rev_low, dtype=float)])
    n = len(close)

    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    df = pd.DataFrame({
        "open":  close,
        "high":  high,
        "low":   low,
        "close": close,
        "volume": np.ones(n) * 1e6,
    }, index=idx)

    from bcrm2.indicators import IndicatorBank
    bank = IndicatorBank()
    indicators = bank.compute_all(df)

    # 关闭 Sperandeo
    composer_off = ScoreComposer(sperandeo_enabled=False, sperandeo_swing_window=3)
    level_off, trend_off = composer_off.compose(indicators, df)

    # 开启 Sperandeo
    composer_on = ScoreComposer(sperandeo_enabled=True, sperandeo_swing_window=3)
    level_on, trend_on = composer_on.compose(indicators, df)

    # level 不应改变（Sperandeo 只调整 trend）
    np.testing.assert_allclose(
        np.asarray(level_on, dtype=float),
        np.asarray(level_off, dtype=float),
        atol=1e-9,
        err_msg="Sperandeo 不应影响 level",
    )

    # trend 应有变化（反转段有调整）
    diff = np.abs(np.asarray(trend_on, dtype=float) - np.asarray(trend_off, dtype=float))
    assert diff.max() > 0.01, (
        f"开启 Sperandeo 后 trend 应有变化，最大差异={diff.max():.6f}"
    )

    # 最终结果在 [-4, +4] 范围内
    trend_on_arr = np.asarray(trend_on, dtype=float)
    assert trend_on_arr.min() >= -4.0 - 1e-9, f"trend 最小值 {trend_on_arr.min():.4f} < -4"
    assert trend_on_arr.max() <= 4.0 + 1e-9, f"trend 最大值 {trend_on_arr.max():.4f} > +4"


# ================================================================
# 5. _trend_line_val 单元测试
# ================================================================
def test_trend_line_val():
    """趋势线线性外推计算。"""
    # (x1=0, y1=100), (x2=10, y2=80): y = 100 - 2x
    assert abs(_trend_line_val(0, 100, 10, 80, 0) - 100) < 1e-9
    assert abs(_trend_line_val(0, 100, 10, 80, 10) - 80) < 1e-9
    assert abs(_trend_line_val(0, 100, 10, 80, 5) - 90) < 1e-9
    assert abs(_trend_line_val(0, 100, 10, 80, 14) - 72) < 1e-9  # 外推

    # 退化情况：x1 == x2
    assert abs(_trend_line_val(5, 100, 5, 80, 5) - 100) < 1e-9
