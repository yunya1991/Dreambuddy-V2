"""
TDD 测试: P1 接入 PatternDetector → regime_gate + weight 回测

P1-1: PatternDetector 接入 regime_gate
  T1. detect_regime 返回 TOP_DROP（头肩顶检测）
  T2. route_strategy 对 TOP_DROP 返回 short 方向
  T3. TOP_DROP 时不路由到 trend_following（做多）

P1-2: 基因 weight 字段接入 shadow_backtest
  T4. 回测结果中包含 weight 字段
  T5. weight 影响最终 PnL 评分
  T6. weight=0 的基因不参与交易
  T7. weight=2.0 的基因 PnL 翻倍
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.engines.regime_gate import RegimeGateSwitch


# ====================================================================
# P1-1: PatternDetector 接入 regime_gate
# ====================================================================

def _make_head_shoulders_klines():
    """构造头肩顶 K线数据"""
    klines = []
    # 左肩: 上涨到 105
    for i in range(15):
        klines.append({"close": 100 + i * 0.33})
    # 左肩峰: 105
    klines.append({"close": 105.0})
    # 回落到 100
    for i in range(5):
        klines.append({"close": 105 - (i + 1) * 1.0})
    # 头部: 上涨到 110
    for i in range(5):
        klines.append({"close": 100 + i * 2.0})
    # 头部峰: 110
    klines.append({"close": 110.0})
    # 回落到 100
    for i in range(5):
        klines.append({"close": 110 - (i + 1) * 2.0})
    # 右肩: 上涨到 104
    for i in range(5):
        klines.append({"close": 100 + i * 0.8})
    # 右肩峰: 104
    klines.append({"close": 104.0})
    # 下跌
    for i in range(10):
        klines.append({"close": 104 - (i + 1) * 0.5})
    return klines


def test_detect_regime_top_drop():
    """T1: detect_regime 在头肩顶时返回 TOP_DROP"""
    klines = _make_head_shoulders_klines()
    closes = [k["close"] for k in klines]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    kline_data = {"close": closes, "high": highs, "low": lows}

    regime = RegimeGateSwitch.detect_regime(kline_data, klines=klines)
    assert regime == "TOP_DROP", f"头肩顶应返回 TOP_DROP，实际={regime}"


def test_route_strategy_top_drop_returns_short():
    """T2: route_strategy 对 TOP_DROP 返回 short 方向"""
    klines = _make_head_shoulders_klines()
    closes = [k["close"] for k in klines]
    kline_data = {"close": closes, "high": [c+1 for c in closes], "low": [c-1 for c in closes]}

    result = RegimeGateSwitch.route_strategy("TOP_DROP", kline_data, {}, klines=klines)
    assert result["engine"] == "pattern_short"
    assert result["action"] == "SHORT"
    assert "signal" in result


def test_top_drop_not_trend_following():
    """T3: TOP_DROP 时不路由到 trend_following"""
    klines = _make_head_shoulders_klines()
    closes = [k["close"] for k in klines]
    kline_data = {"close": closes, "high": [c+1 for c in closes], "low": [c-1 for c in closes]}

    result = RegimeGateSwitch.route_strategy("TOP_DROP", kline_data, {}, klines=klines)
    assert result["engine"] != "trend_following", "TOP_DROP 不应路由到趋势跟踪做多"


# ====================================================================
# P1-2: 基因 weight 字段接入 shadow_backtest
# ====================================================================

def test_load_gene_weight():
    """T4: 能从基因 JSON 加载 weight 字段"""
    from dreambuddy_evolution.scripts.shadow_backtest import load_gene_weight
    weight = load_gene_weight("CD-ADX-GT25-TREND")
    assert weight is not None, "应能加载 weight"
    assert 0.0 <= weight <= 2.0, f"weight 应在 [0,2] 范围，实际={weight}"


def test_weight_affects_pnl():
    """T5: weight 影响最终 PnL 评分"""
    from dreambuddy_evolution.scripts.shadow_backtest import calc_weighted_pnl
    avg_pnl = 0.05
    weight = 0.5
    weighted = calc_weighted_pnl(avg_pnl, weight)
    assert abs(weighted - 0.025) < 1e-6, f"weighted_pnl 应为 0.025，实际={weighted}"


def test_weight_zero_blocks_trading():
    """T6: weight=0 的基因不参与交易"""
    from dreambuddy_evolution.scripts.shadow_backtest import should_trade
    assert should_trade(weight=0.0) == False, "weight=0 不应交易"
    assert should_trade(weight=0.5) == True, "weight=0.5 应交易"
    assert should_trade(weight=2.0) == True, "weight=2.0 应交易"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
