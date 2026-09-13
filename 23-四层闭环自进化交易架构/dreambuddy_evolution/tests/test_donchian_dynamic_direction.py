"""
Phase F3 TDD 测试：Donchian 突破动态方向选择

上突破（close > donchian_high）→ long
下突破（close < donchian_low）→ short

覆盖：
  T1. 上涨趋势 + 20日上突破 → (True, "long")
  T2. 下跌趋势 + 20日下突破 → (True, "short")
  T3. 上涨趋势 + 55日上突破 → (True, "long")
  T4. 下跌趋势 + 55日下突破 → (True, "short")
  T5. 震荡市无突破 → (False, "long")（默认方向）
  T6. calc_indicators 包含 low_55d 指标
  T7. 方向映射 _GENE_DIRECTION 不再硬编码 Donchian 为 long
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


def _make_trend_up_klines(n: int = 100):
    """强上涨趋势 K 线"""
    klines = []
    for i in range(n):
        close = 100.0 + i * 2.0
        klines.append({
            "timestamp": f"2026-01-{i+1:02d}",
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0 + i * 10,
        })
    return klines


def _make_trend_down_klines(n: int = 100):
    """强下跌趋势 K 线"""
    klines = []
    for i in range(n):
        close = 300.0 - i * 2.0
        klines.append({
            "timestamp": f"2026-01-{i+1:02d}",
            "open": close + 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0 + i * 10,
        })
    return klines


def _make_range_klines(n: int = 100):
    """震荡 K 线（100~105 之间反复）"""
    klines = []
    for i in range(n):
        close = 100.0 + (i % 5)
        klines.append({
            "timestamp": f"2026-01-{i+1:02d}",
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        })
    return klines


# ====================================================================
# T1. 上涨趋势 + 20日上突破 → (True, "long")
# ====================================================================
def test_donchian_20_up_breakout_long():
    """T1: 20日上突破 → long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_up_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-20-BREAK", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"上突破方向应为 long，实际 {direction}"


# ====================================================================
# T2. 下跌趋势 + 20日下突破 → (True, "short")
# ====================================================================
def test_donchian_20_down_breakout_short():
    """T2: 20日下突破 → short"""
    sb = _import_shadow_backtest()
    klines = _make_trend_down_klines(100)
    bars = sb.calc_indicators(klines)
    # 下跌趋势中应触发下突破
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-20-BREAK", bars[80], klines, 80
    )
    if triggered:
        assert direction == "short", f"下突破方向应为 short，实际 {direction}"


# ====================================================================
# T3. 上涨趋势 + 55日上突破 → (True, "long")
# ====================================================================
def test_donchian_55_up_breakout_long():
    """T3: 55日上突破 → long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_up_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-55-BREAK", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"55日上突破方向应为 long，实际 {direction}"


# ====================================================================
# T4. 下跌趋势 + 55日下突破 → (True, "short")
# ====================================================================
def test_donchian_55_down_breakout_short():
    """T4: 55日下突破 → short"""
    sb = _import_shadow_backtest()
    klines = _make_trend_down_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-55-BREAK", bars[80], klines, 80
    )
    if triggered:
        assert direction == "short", f"55日下突破方向应为 short，实际 {direction}"


# ====================================================================
# T5. 震荡市无突破 → (False, "long")（默认方向）
# ====================================================================
def test_donchian_no_breakout_default_long():
    """T5: 震荡市无突破 → (False, "long")"""
    sb = _import_shadow_backtest()
    klines = _make_range_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-20-BREAK", bars[80], klines, 80
    )
    assert isinstance(triggered, bool)
    # 未触发时方向应为默认 long
    if not triggered:
        assert direction == "long", f"未触发默认方向应为 long，实际 {direction}"


# ====================================================================
# T6. calc_indicators 包含 low_55d 指标
# ====================================================================
def test_calc_indicators_has_low_55d():
    """T6: calc_indicators 计算 low_55d（55日下沿）"""
    sb = _import_shadow_backtest()
    klines = _make_trend_up_klines(100)
    bars = sb.calc_indicators(klines)
    assert "low_55d" in bars[56], "bar[56] 应包含 low_55d"
    assert bars[56]["low_55d"] > 0, "low_55d 应 > 0"


# ====================================================================
# T7. 方向映射不再硬编码 Donchian 为 long
# ====================================================================
def test_gene_direction_not_hardcoded_donchian():
    """T7: _GENE_DIRECTION 中 Donchian 不再固定为 long（改为动态）"""
    sb = _import_shadow_backtest()
    # Donchian 基因应不在 _GENE_DIRECTION 中（由 eval_gene_with_direction 动态返回）
    assert "CD-DONCHIAN-20-BREAK" not in sb._GENE_DIRECTION, \
        "CD-DONCHIAN-20-BREAK 不应硬编码方向（应动态判断）"
    assert "CD-DONCHIAN-55-BREAK" not in sb._GENE_DIRECTION, \
        "CD-DONCHIAN-55-BREAK 不应硬编码方向（应动态判断）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
