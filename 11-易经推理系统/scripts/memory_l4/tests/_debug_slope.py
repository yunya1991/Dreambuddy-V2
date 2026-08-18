#!/usr/bin/env python3
"""调试 _build_trend_closes_5ma 生成的 closes 和 MA 斜率方向"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.memory_l4.polling_trader import PollingTrader
from unittest.mock import patch, MagicMock
from scripts.memory_l4.tests.test_5ma_short_filter import _build_trend_closes_5ma

# 构造 bear 趋势数据
closes = _build_trend_closes_5ma(direction="bear", ma30=90000, spread_pct=0.05)
print(f"总长度: {len(closes)}")
print(f"前10根 closes: {[round(c, 1) for c in closes[:10]]}")
print(f"closes[0] (最新): {closes[0]:.1f}")
print(f"closes[19] (第20根): {closes[19]:.1f}")
print(f"closes[30]: {closes[30]:.1f}")
print(f"closes[200]: {closes[200]:.1f}")
print()

# 计算 MA
ma30 = sum(closes[:30]) / 30
ma65 = sum(closes[:65]) / 65
ma128 = sum(closes[:128]) / 128
ma200 = sum(closes[:200]) / 200
ma1400 = sum(closes[:1400]) / 1400
print(f"MA30={ma30:.1f} (目标 90000)")
print(f"MA65={ma65:.1f} (目标 94500)")
print(f"MA128={ma128:.1f} (目标 99000)")
print(f"MA200={ma200:.1f} (目标 103500)")
print(f"MA1400={ma1400:.1f} (目标 108000)")
print(f"价格 closes[0]={closes[0]:.1f}")
print()

# 计算 MA 斜率
with patch.object(PollingTrader, "__init__", lambda self, *a, **kw: None):
    t = PollingTrader.__new__(PollingTrader)
    t._log = MagicMock()

slope_ma30 = t._calc_ma_slope(closes, 30, 5)
slope_ma200 = t._calc_ma_slope(closes, 200, 5)
print(f"MA30 斜率: {slope_ma30:.4f}% (应为负，bear趋势)")
print(f"MA200 斜率: {slope_ma200:.4f}% (应为负，bear趋势)")
print()

# 计算5根 MA 序列
for i in range(5):
    ma30_i = sum(closes[i:i+30]) / 30
    print(f"  ma_series[{i}] (往前{i}期) MA30={ma30_i:.1f}")
