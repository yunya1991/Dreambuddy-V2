"""
P0 TDD 测试：CD-ATR-EXPANDING + CD-ADX-GT25-TREND 方向动态化

ATR 扩张：close > SMA20 → long, close < SMA20 → short
ADX 趋势：+DI > -DI → long, +DI < -DI → short

覆盖：
  T1. CD-ATR-EXPANDING 在上涨趋势（close > SMA20）→ long
  T2. CD-ATR-EXPANDING 在下跌趋势（close < SMA20）→ short
  T3. CD-ADX-GT25-TREND 在上涨趋势（+DI > -DI）→ long
  T4. CD-ADX-GT25-TREND 在下跌趋势（+DI < -DI）→ short
  T5. calc_indicators 计算 sma_20 和 plus_di/minus_di
  T6. _DYNAMIC_DIRECTION_GENES 包含 ATR-EXPANDING 和 ADX-GT25-TREND
  T7. _GENE_DIRECTION 不再硬编码 ATR-EXPANDING 和 ADX-GT25-TREND
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCRIPTS_DIR = REPO / "dreambuddy_evolution" / "scripts"


def _import_shadow_backtest():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "shadow_backtest", SCRIPTS_DIR / "shadow_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_trend_up(n=100):
    """强上涨趋势"""
    klines = []
    for i in range(n):
        close = 100.0 + i * 2.0
        klines.append({"timestamp": f"2026-01-{i+1:02d}", "open": close-0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 1000.0})
    return klines


def _make_trend_down(n=100):
    """强下跌趋势"""
    klines = []
    for i in range(n):
        close = 300.0 - i * 2.0
        klines.append({"timestamp": f"2026-01-{i+1:02d}", "open": close+0.5,
                        "high": close+1.0, "low": close-1.0, "close": close, "volume": 1000.0})
    return klines


# ====================================================================
# T1. CD-ATR-EXPANDING 上涨趋势 → long
# ====================================================================
def test_atr_expanding_uptrend_long():
    sb = _import_shadow_backtest()
    klines = _make_trend_up(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction("CD-ATR-EXPANDING", bars[80], klines, 80)
    if triggered:
        assert direction == "long", f"上涨趋势 ATR 扩张应为 long，实际 {direction}"


# ====================================================================
# T2. CD-ATR-EXPANDING 下跌趋势 → short
# ====================================================================
def test_atr_expanding_downtrend_short():
    sb = _import_shadow_backtest()
    klines = _make_trend_down(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction("CD-ATR-EXPANDING", bars[80], klines, 80)
    if triggered:
        assert direction == "short", f"下跌趋势 ATR 扩张应为 short，实际 {direction}"


# ====================================================================
# T3. CD-ADX-GT25-TREND 上涨趋势 → long
# ====================================================================
def test_adx_gt25_uptrend_long():
    sb = _import_shadow_backtest()
    klines = _make_trend_up(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction("CD-ADX-GT25-TREND", bars[80], klines, 80)
    if triggered:
        assert direction == "long", f"上涨趋势 ADX>25 应为 long，实际 {direction}"


# ====================================================================
# T4. CD-ADX-GT25-TREND 下跌趋势 → short
# ====================================================================
def test_adx_gt25_downtrend_short():
    sb = _import_shadow_backtest()
    klines = _make_trend_down(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction("CD-ADX-GT25-TREND", bars[80], klines, 80)
    if triggered:
        assert direction == "short", f"下跌趋势 ADX>25 应为 short，实际 {direction}"


# ====================================================================
# T5. calc_indicators 包含 sma_20, plus_di, minus_di
# ====================================================================
def test_calc_indicators_has_di_and_sma():
    sb = _import_shadow_backtest()
    klines = _make_trend_up(100)
    bars = sb.calc_indicators(klines)
    assert "sma_20" in bars[25], "bar[25] 应包含 sma_20"
    assert "plus_di" in bars[25], "bar[25] 应包含 plus_di"
    assert "minus_di" in bars[25], "bar[25] 应包含 minus_di"


# ====================================================================
# T6. _DYNAMIC_DIRECTION_GENES 包含 ATR-EXPANDING 和 ADX-GT25-TREND
# ====================================================================
def test_dynamic_direction_genes_includes_atr_adx():
    sb = _import_shadow_backtest()
    assert "CD-ATR-EXPANDING" in sb._DYNAMIC_DIRECTION_GENES
    assert "CD-ADX-GT25-TREND" in sb._DYNAMIC_DIRECTION_GENES


# ====================================================================
# T7. _GENE_DIRECTION 不再硬编码 ATR-EXPANDING 和 ADX-GT25-TREND
# ====================================================================
def test_gene_direction_not_hardcoded_atr_adx():
    sb = _import_shadow_backtest()
    assert "CD-ATR-EXPANDING" not in sb._GENE_DIRECTION
    assert "CD-ADX-GT25-TREND" not in sb._GENE_DIRECTION


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
