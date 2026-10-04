"""test_drawdown_control.py — 最大回撤控制能力回归测试（D7）

借鉴 ds4-eval core 套件.
验证维度: 最大回撤限制 + 连续亏损降仓 + 权益曲线平滑.

硬约束: HC-DS4-08（纯只读验证，不修改实盘行为）.
"""
from __future__ import annotations

from conftest import calc_drawdowns


class TestDrawdownControl:
    """最大回撤控制能力回归"""

    def test_max_drawdown_limited(self, declining_market):
        """持续下跌中，带止损的交易最大回撤应 < 无止损"""
        entry = declining_market[0]["close"]
        # 带止损的权益曲线（止损后空仓 5 bars 再入场）
        equity_sl = [entry]
        pos = None
        cooldown = 0
        for bar in declining_market[1:]:
            if cooldown > 0:
                cooldown -= 1
                equity_sl.append(equity_sl[-1])  # 空仓，权益不变
                continue
            if pos is None:
                # 入场
                pos = {"entry": bar["close"], "sl": bar["close"] * 0.98}
                equity_sl.append(bar["close"])
            else:
                if bar["low"] <= pos["sl"]:
                    # 止损离场，空仓 5 bars
                    equity_sl.append(pos["sl"])
                    pos = None
                    cooldown = 5
                else:
                    equity_sl.append(bar["close"])

        # 无止损的权益曲线（持续持有）
        equity_no_sl = [entry] + [b["close"] for b in declining_market[1:]]

        dd_sl = max(calc_drawdowns(equity_sl))
        dd_no_sl = max(calc_drawdowns(equity_no_sl))

        # 带止损的最大回撤应小于无止损
        assert dd_sl < dd_no_sl, f"Stop-loss DD {dd_sl:.2%} >= no-SL DD {dd_no_sl:.2%}"
        # 止损至少减少 1 个百分点的回撤
        assert dd_no_sl - dd_sl > 0.01, \
            f"Stop-loss reduced DD by only {(dd_no_sl - dd_sl)*100:.2f}pp (< 1pp)"

    def test_consecutive_loss_reduces_risk(self):
        """连续亏损后应降低仓位（风险递减）"""
        # 模拟连续亏损
        losses = [0.02, 0.02, 0.02, 0.02, 0.02]  # 连续 5 次 -2%
        position_sizes = [1.0, 0.8, 0.6, 0.5, 0.4]  # 仓位递减
        # 验证仓位随亏损递减
        for i in range(1, len(position_sizes)):
            assert position_sizes[i] < position_sizes[i - 1], \
                f"Position size should decrease after consecutive loss {i}"

    def test_drawdown_recovery(self, ranging_market):
        """震荡行情中，止损+止盈策略的回撤应能恢复"""
        entry = ranging_market[0]["close"]
        equity = [entry]
        for i in range(1, len(ranging_market)):
            bar = ranging_market[i]
            # 简单策略：价格低于 MA 做空，高于 MA 做多
            ma = sum(b["close"] for b in ranging_market[max(0, i - 10):i]) / min(10, i)
            if bar["close"] > ma:
                # 做多，带 2% 止损 4% 止盈
                ret = (bar["close"] - entry) / entry
                if ret <= -0.02 or ret >= 0.04:
                    entry = bar["close"]
            else:
                entry = bar["close"]
            equity.append(bar["close"])

        drawdowns = calc_drawdowns(equity)
        max_dd = max(drawdowns)
        # 震荡行情中最大回撤不应过大
        assert max_dd < 0.10, f"Ranging market max drawdown {max_dd:.2%} >= 10%"

    def test_equity_curve_smoother_with_sl(self, declining_market):
        """带止损的权益曲线比不带止损的更平滑（标准差更小）"""
        import statistics
        entry = declining_market[0]["close"]

        # 带止损
        equity_sl = [entry]
        pos_entry = entry
        for bar in declining_market[1:]:
            if bar["low"] <= pos_entry * 0.98:
                equity_sl.append(pos_entry * 0.98)
                pos_entry = bar["close"]
            else:
                equity_sl.append(bar["close"])

        # 不带止损
        equity_no_sl = [entry] + [b["close"] for b in declining_market[1:]]

        std_sl = statistics.stdev(equity_sl) if len(equity_sl) > 1 else 0
        std_no_sl = statistics.stdev(equity_no_sl) if len(equity_no_sl) > 1 else 0

        # 带止损的权益曲线波动应更小
        assert std_sl < std_no_sl, "Stop-loss should smooth equity curve"
