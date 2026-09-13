"""
P3 TDD 测试：ADX 阈值 25→30 减少误触发

问题：CD-ADX-GT25-TREND 在 3 个月数据中触发 364 次（过于频繁），
      PnL -0.19%，误触发率高。
方案：提高 ADX 阈值至 30，减少低质量信号触发。

覆盖：
  T1. ADX=26 时不触发（旧阈值 25 会触发，新阈值 30 不触发）
  T2. ADX=31 时触发
  T3. ADX=25 时不触发（边界）
  T4. ADX=30 时不触发（边界）
  T5. ADX=30.01 时触发（刚超过阈值）
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


def _make_bar(adx, close=100.0, plus_di=25, minus_di=15):
    """构造指定 ADX 值的 bar"""
    return {
        "close": close,
        "adx_14": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "sma_20": close - 1.0,  # close > sma → long 方向
        "atr": 2.0,
        "ma_atr": 1.5,
    }


def test_adx_26_not_triggered():
    """T1: ADX=26 不触发（旧阈值 25 会触发，新阈值 30 不触发）"""
    sb = _import_shadow_backtest()
    bar = _make_bar(adx=26)
    triggered = sb.eval_gene("CD-ADX-GT25-TREND", bar, [], 50)
    assert not triggered, "ADX=26 应不触发（阈值已提高至 30）"


def test_adx_31_triggered():
    """T2: ADX=31 触发"""
    sb = _import_shadow_backtest()
    bar = _make_bar(adx=31)
    triggered = sb.eval_gene("CD-ADX-GT25-TREND", bar, [], 50)
    assert triggered, "ADX=31 应触发"


def test_adx_25_not_triggered():
    """T3: ADX=25 不触发（边界，低于 30）"""
    sb = _import_shadow_backtest()
    bar = _make_bar(adx=25)
    triggered = sb.eval_gene("CD-ADX-GT25-TREND", bar, [], 50)
    assert not triggered, "ADX=25 应不触发"


def test_adx_30_not_triggered():
    """T4: ADX=30 不触发（边界，不大于 30）"""
    sb = _import_shadow_backtest()
    bar = _make_bar(adx=30)
    triggered = sb.eval_gene("CD-ADX-GT25-TREND", bar, [], 50)
    assert not triggered, "ADX=30 应不触发（严格大于）"


def test_adx_30_01_triggered():
    """T5: ADX=30.01 触发（刚超过阈值）"""
    sb = _import_shadow_backtest()
    bar = _make_bar(adx=30.01)
    triggered = sb.eval_gene("CD-ADX-GT25-TREND", bar, [], 50)
    assert triggered, "ADX=30.01 应触发"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
