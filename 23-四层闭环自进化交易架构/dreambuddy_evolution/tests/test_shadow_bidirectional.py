"""
Phase F2 TDD 测试：simulate_trade 双向 + eval_gene_with_direction

覆盖：
  T1. eval_gene_with_direction 返回 (bool, direction) 元组
  T2. CD-DONCHIAN-20-BREAK 趋势突破 → long 方向
  T3. CD-DONCHIAN-55-BREAK 趋势突破 → long 方向
  T4. CD-ADX-GT25-TREND 趋势市 → long 方向（趋势跟踪做多）
  T5. CD-ADX-LT25-RANGE 震荡市 → long 方向（网格默认做多）
  T6. CD-BOLL-WIDTH-NARROW 震荡市 → long 方向（网格做多）
  T7. CD-ATR-EXPANDING 波动扩张 → long 方向（趋势确认做多）
  T8. 未知 gene_id → (False, "long") FAIL-OPEN 默认 long
  T9. simulate_trade direction="short" 做空盈利计算正确
  T10. simulate_trade direction="long" 做多盈利计算正确

参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase F
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]  # 23-四层闭环自进化交易架构/
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCRIPTS_DIR = REPO / "dreambuddy_evolution" / "scripts"


def _make_synthetic_klines(n: int = 100, base_price: float = 100.0, trend: float = 0.0):
    """构造 n bar 合成 K 线"""
    klines = []
    for i in range(n):
        close = base_price + trend * i
        klines.append({
            "timestamp": f"2026-01-{i+1:02d}",
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0 + i * 10,
        })
    return klines


def _make_trend_klines(n: int = 100):
    return _make_synthetic_klines(n, base_price=100.0, trend=2.0)


def _make_range_klines(n: int = 100):
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


def _import_shadow_backtest():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "shadow_backtest", SCRIPTS_DIR / "shadow_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ====================================================================
# T1. eval_gene_with_direction 返回元组
# ====================================================================
def test_eval_gene_with_direction_returns_tuple():
    """T1: eval_gene_with_direction 返回 (bool, str) 元组"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    result = sb.eval_gene_with_direction("CD-DONCHIAN-20-BREAK", bars[80], klines, 80)
    assert isinstance(result, tuple), "应返回元组"
    assert len(result) == 2, "元组长度应为 2"
    assert isinstance(result[0], bool), "第一个元素应为 bool"
    assert isinstance(result[1], str), "第二个元素应为 str（方向）"


# ====================================================================
# T2. CD-DONCHIAN-20-BREAK → long
# ====================================================================
def test_donchian_20_break_direction_long():
    """T2: 20日突破信号方向为 long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-20-BREAK", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"20日突破方向应为 long，实际 {direction}"


# ====================================================================
# T3. CD-DONCHIAN-55-BREAK → long
# ====================================================================
def test_donchian_55_break_direction_long():
    """T3: 55日突破信号方向为 long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-DONCHIAN-55-BREAK", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"55日突破方向应为 long，实际 {direction}"


# ====================================================================
# T4. CD-ADX-GT25-TREND → long（趋势跟踪做多）
# ====================================================================
def test_adx_gt25_trend_direction_long():
    """T4: ADX>25 趋势市信号方向为 long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-ADX-GT25-TREND", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"趋势市方向应为 long，实际 {direction}"


# ====================================================================
# T5. CD-ADX-LT25-RANGE → long（网格默认做多）
# ====================================================================
def test_adx_lt25_range_direction_long():
    """T5: ADX<25 震荡市信号方向为 long（网格默认做多）"""
    sb = _import_shadow_backtest()
    klines = _make_range_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-ADX-LT25-RANGE", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"震荡市网格方向应为 long，实际 {direction}"


# ====================================================================
# T6. CD-BOLL-WIDTH-NARROW → long（网格做多）
# ====================================================================
def test_boll_width_narrow_direction_long():
    """T6: 布林带收窄信号方向为 long"""
    sb = _import_shadow_backtest()
    klines = _make_range_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-BOLL-WIDTH-NARROW", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"布林带收窄方向应为 long，实际 {direction}"


# ====================================================================
# T7. CD-ATR-EXPANDING → long（趋势确认做多）
# ====================================================================
def test_atr_expanding_direction_long():
    """T7: ATR 扩张信号方向为 long"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-ATR-EXPANDING", bars[80], klines, 80
    )
    if triggered:
        assert direction == "long", f"ATR扩张方向应为 long，实际 {direction}"


# ====================================================================
# T8. 未知 gene_id → (False, "long") FAIL-OPEN
# ====================================================================
def test_unknown_gene_fail_open_long():
    """T8: 未知 gene_id 返回 (False, "long") FAIL-OPEN"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    triggered, direction = sb.eval_gene_with_direction(
        "CD-UNKNOWN-GENE", bars[80], klines, 80
    )
    assert triggered is False, "未知基因应返回 False"
    assert direction == "long", f"FAIL-OPEN 默认方向应为 long，实际 {direction}"


# ====================================================================
# T9. simulate_trade direction="short" 做空盈利计算
# ====================================================================
def test_simulate_trade_short_pnl():
    """T9: 做空时价格下跌应盈利"""
    sb = _import_shadow_backtest()
    # 构造下跌 K 线：entry=100, exit=90
    klines = []
    for i in range(20):
        close = 100.0 - i * 0.5  # 100 → 90.5
        klines.append({
            "timestamp": f"2026-01-{i+1:02d}",
            "open": close + 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
        })
    # entry_idx=0 (100), exit_idx=12 (94)
    trade = sb.simulate_trade(klines, 0, direction="short")
    assert trade is not None
    # 做空：entry=100, exit=94, pnl = (100-94)/100 = 0.06
    assert trade["pnl_pct"] > 0, "做空时价格下跌应盈利"
    expected_pnl = (100.0 - klines[12]["close"]) / 100.0
    assert abs(trade["pnl_pct"] - expected_pnl) < 1e-9, f"PnL 计算错误: {trade['pnl_pct']} != {expected_pnl}"


# ====================================================================
# T10. simulate_trade direction="long" 做多盈利计算
# ====================================================================
def test_simulate_trade_long_pnl():
    """T10: 做多时价格上涨应盈利"""
    sb = _import_shadow_backtest()
    # 构造上涨 K 线：entry=100, exit=112
    klines = []
    for i in range(20):
        close = 100.0 + i  # 100 → 119
        klines.append({
            "timestamp": f"2026-01-{i+1:02d}",
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
        })
    # entry_idx=0 (100), exit_idx=12 (112)
    trade = sb.simulate_trade(klines, 0, direction="long")
    assert trade is not None
    # 做多：entry=100, exit=112, pnl = (112-100)/100 = 0.12
    assert trade["pnl_pct"] > 0, "做多时价格上涨应盈利"
    expected_pnl = (klines[12]["close"] - 100.0) / 100.0
    assert abs(trade["pnl_pct"] - expected_pnl) < 1e-9, f"PnL 计算错误: {trade['pnl_pct']} != {expected_pnl}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
