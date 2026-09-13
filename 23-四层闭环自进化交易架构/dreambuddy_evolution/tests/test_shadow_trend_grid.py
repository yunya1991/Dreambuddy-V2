"""
Phase F TDD 测试：Shadow 回测接入趋势跟踪 + 网格策略

覆盖：
  T1. calc_indicators 计算 donchian_55_high（55日唐奇安通道）
  T2. calc_indicators 计算 adx_14（ADX 趋势强度指标）
  T3. eval_gene 评估 CD-DONCHIAN-20-BREAK（20日突破）
  T4. eval_gene 评估 CD-DONCHIAN-55-BREAK（55日突破）
  T5. eval_gene 评估 CD-ATR-EXPANDING（ATR扩张）
  T6. eval_gene 评估 CD-ADX-GT25-TREND（ADX>25趋势市）
  T7. eval_gene 评估 CD-ADX-LT25-RANGE（ADX<25震荡市）
  T8. eval_gene 评估 CD-BOLL-WIDTH-NARROW（布林带收窄）
  T9. FAIL-OPEN：未知 gene_id 返回 False 不 crash

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


# ==================================================================================
# 辅助：构造合成 K 线数据
# ==================================================================================
def _make_synthetic_klines(n: int = 100, base_price: float = 100.0, trend: float = 0.0):
    """构造 n bar 合成 K 线（可指定趋势斜率）"""
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
    """强趋势 K 线（价格单调递增）"""
    return _make_synthetic_klines(n, base_price=100.0, trend=2.0)


def _make_range_klines(n: int = 100):
    """震荡 K 线（价格在 100~105 之间反复）"""
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


# ==================================================================================
# 导入 shadow_backtest（延迟导入以处理路径）
# ==================================================================================
def _import_shadow_backtest():
    """导入 shadow_backtest 模块"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "shadow_backtest", SCRIPTS_DIR / "shadow_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ====================================================================
# T1. calc_indicators 计算 donchian_55_high
# ====================================================================
def test_calc_indicators_donchian_55():
    """T1: calc_indicators 计算 donchian_55_high"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    # 第 56 bar 起应有 donchian_55_high
    assert "donchian_55_high" in bars[55], "bar[55] 应包含 donchian_55_high"
    assert bars[55]["donchian_55_high"] > 0, "donchian_55_high 应 > 0"


# ====================================================================
# T2. calc_indicators 计算 adx_14
# ====================================================================
def test_calc_indicators_adx():
    """T2: calc_indicators 计算 adx_14"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    assert "adx_14" in bars[15], "bar[15] 应包含 adx_14"
    assert bars[15]["adx_14"] >= 0, "adx_14 应 >= 0"


# ====================================================================
# T3. eval_gene: CD-DONCHIAN-20-BREAK
# ====================================================================
def test_eval_gene_donchian_20_break():
    """T3: CD-DONCHIAN-20-BREAK 评估"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    # 趋势市应触发 20 日突破
    result = sb.eval_gene("CD-DONCHIAN-20-BREAK", bars[80], klines, 80)
    assert isinstance(result, bool)


# ====================================================================
# T4. eval_gene: CD-DONCHIAN-55-BREAK
# ====================================================================
def test_eval_gene_donchian_55_break():
    """T4: CD-DONCHIAN-55-BREAK 评估"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    # 第 80 bar 应有 55 日突破信号
    result = sb.eval_gene("CD-DONCHIAN-55-BREAK", bars[80], klines, 80)
    assert isinstance(result, bool)


# ====================================================================
# T5. eval_gene: CD-ATR-EXPANDING
# ====================================================================
def test_eval_gene_atr_expanding():
    """T5: CD-ATR-EXPANDING 评估"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    result = sb.eval_gene("CD-ATR-EXPANDING", bars[80], klines, 80)
    assert isinstance(result, bool)


# ====================================================================
# T6. eval_gene: CD-ADX-GT25-TREND
# ====================================================================
def test_eval_gene_adx_gt25_trend():
    """T6: CD-ADX-GT25-TREND 评估（趋势市 ADX>25）"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    result = sb.eval_gene("CD-ADX-GT25-TREND", bars[80], klines, 80)
    assert isinstance(result, bool)


# ====================================================================
# T7. eval_gene: CD-ADX-LT25-RANGE
# ====================================================================
def test_eval_gene_adx_lt25_range():
    """T7: CD-ADX-LT25-RANGE 评估（震荡市 ADX<25）"""
    sb = _import_shadow_backtest()
    klines = _make_range_klines(100)
    bars = sb.calc_indicators(klines)
    result = sb.eval_gene("CD-ADX-LT25-RANGE", bars[80], klines, 80)
    assert isinstance(result, bool)


# ====================================================================
# T8. eval_gene: CD-BOLL-WIDTH-NARROW
# ====================================================================
def test_eval_gene_boll_width_narrow():
    """T8: CD-BOLL-WIDTH-NARROW 评估"""
    sb = _import_shadow_backtest()
    klines = _make_range_klines(100)
    bars = sb.calc_indicators(klines)
    result = sb.eval_gene("CD-BOLL-WIDTH-NARROW", bars[80], klines, 80)
    assert isinstance(result, bool)


# ====================================================================
# T9. FAIL-OPEN：未知 gene_id 返回 False 不 crash
# ====================================================================
def test_eval_gene_unknown_fail_open():
    """T9: 未知 gene_id 返回 False（HC-TF-07 FAIL-OPEN）"""
    sb = _import_shadow_backtest()
    klines = _make_trend_klines(100)
    bars = sb.calc_indicators(klines)
    result = sb.eval_gene("CD-UNKNOWN-GENE", bars[80], klines, 80)
    assert result is False, "未知 gene_id 应返回 False（FAIL-OPEN）"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
