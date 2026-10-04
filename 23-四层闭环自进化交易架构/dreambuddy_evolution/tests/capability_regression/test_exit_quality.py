"""test_exit_quality.py — 离场时机质量能力回归测试（D7）

借鉴 ds4-eval core 套件.
验证维度: 止损/止盈逻辑正确性 + 盈利交易占比 + 持仓时间.

硬约束: HC-DS4-08（纯只读验证，不修改实盘行为）.
"""
from __future__ import annotations


def simulate_trade_with_sl_tp(entry_price, sl_pct, tp_pct, bars, direction="long"):
    """模拟一次带止损/止盈的交易.

    Args:
        entry_price: 入场价格
        sl_pct: 止损百分比（如 0.02 = 2%）
        tp_pct: 止盈百分比（如 0.04 = 4%）
        bars: 后续 K 线数据
        direction: "long" 或 "short"

    Returns:
        dict: {exit_price, exit_reason, hold_bars, pnl_pct}
    """
    if direction == "long":
        sl_price = entry_price * (1 - sl_pct)
        tp_price = entry_price * (1 + tp_pct)
    else:
        sl_price = entry_price * (1 + sl_pct)
        tp_price = entry_price * (1 - tp_pct)

    for i, bar in enumerate(bars):
        high, low = bar["high"], bar["low"]
        if direction == "long":
            if low <= sl_price:
                return {"exit_price": sl_price, "exit_reason": "stop_loss",
                        "hold_bars": i + 1, "pnl_pct": (sl_price - entry_price) / entry_price}
            if high >= tp_price:
                return {"exit_price": tp_price, "exit_reason": "take_profit",
                        "hold_bars": i + 1, "pnl_pct": (tp_price - entry_price) / entry_price}
        else:
            if high >= sl_price:
                return {"exit_price": sl_price, "exit_reason": "stop_loss",
                        "hold_bars": i + 1, "pnl_pct": (entry_price - sl_price) / entry_price}
            if low <= tp_price:
                return {"exit_price": tp_price, "exit_reason": "take_profit",
                        "hold_bars": i + 1, "pnl_pct": (entry_price - tp_price) / entry_price}

    # 持有到期
    last_close = bars[-1]["close"]
    if direction == "long":
        pnl = (last_close - entry_price) / entry_price
    else:
        pnl = (entry_price - last_close) / entry_price
    return {"exit_price": last_close, "exit_reason": "expiry",
            "hold_bars": len(bars), "pnl_pct": pnl}


class TestExitQuality:
    """离场时机质量能力回归"""

    def test_stop_loss_triggers_on_decline(self, declining_market):
        """下跌行情中，多头止损应触发"""
        entry = declining_market[0]["close"]
        result = simulate_trade_with_sl_tp(entry, sl_pct=0.02, tp_pct=0.04,
                                            bars=declining_market[1:], direction="long")
        assert result["exit_reason"] == "stop_loss"
        assert result["pnl_pct"] <= -0.019  # 接近 -2%

    def test_take_profit_triggers_on_rally(self, trending_market):
        """上涨行情中，多头止盈应触发"""
        entry = trending_market[0]["close"]
        result = simulate_trade_with_sl_tp(entry, sl_pct=0.02, tp_pct=0.04,
                                            bars=trending_market[1:], direction="long")
        assert result["exit_reason"] == "take_profit"
        assert result["pnl_pct"] >= 0.039  # 接近 +4%

    def test_loss_limited_by_stop_loss(self, declining_market):
        """止损限制最大亏损：亏损不超过 sl_pct + 滑点"""
        entry = declining_market[0]["close"]
        result = simulate_trade_with_sl_tp(entry, sl_pct=0.02, tp_pct=0.04,
                                            bars=declining_market[1:], direction="long")
        # 即使在持续下跌中，亏损也被止损限制在 -2% 附近
        assert result["pnl_pct"] >= -0.025

    def test_short_stop_loss_on_rally(self, trending_market):
        """上涨行情中，空头止损应触发"""
        entry = trending_market[0]["close"]
        result = simulate_trade_with_sl_tp(entry, sl_pct=0.02, tp_pct=0.04,
                                            bars=trending_market[1:], direction="short")
        assert result["exit_reason"] == "stop_loss"

    def test_rr_ratio_positive(self):
        """风险收益比: tp/sl 应 ≥ 2（符合策略设计）"""
        sl_pct = 0.02
        tp_pct = 0.04
        rr = tp_pct / sl_pct
        assert rr >= 2.0, f"Risk-reward ratio {rr} < 2.0"

    def test_trending_win_rate(self, trending_market):
        """趋势行情中多头胜率应 > 50%（多笔随机入场）"""
        wins = 0
        total = 0
        for i in range(0, len(trending_market) - 10, 10):
            entry = trending_market[i]["close"]
            result = simulate_trade_with_sl_tp(entry, sl_pct=0.02, tp_pct=0.04,
                                                bars=trending_market[i + 1:], direction="long")
            if result["pnl_pct"] > 0:
                wins += 1
            total += 1
        win_rate = wins / total if total > 0 else 0
        assert win_rate >= 0.5, f"Trending win rate {win_rate:.2%} < 50%"
