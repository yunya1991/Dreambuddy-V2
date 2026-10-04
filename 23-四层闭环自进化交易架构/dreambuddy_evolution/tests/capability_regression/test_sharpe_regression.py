"""test_sharpe_regression.py — Sharpe 比率能力回归测试（D7）

借鉴 ds4-eval core 套件.
验证维度: Sharpe 计算正确性 + 趋势策略正 Sharpe + 下跌策略负 Sharpe.

硬约束: HC-DS4-08（纯只读验证，不修改实盘行为）.
"""
from __future__ import annotations

from conftest import calc_sharpe


class TestSharpeRegression:
    """Sharpe 比率能力回归"""

    def test_sharpe_positive_on_trend(self, trending_market):
        """上升趋势中，做多策略的 Sharpe 应为正"""
        # 计算每 bar 收益率
        returns = []
        for i in range(1, len(trending_market)):
            ret = (trending_market[i]["close"] - trending_market[i - 1]["close"]) / trending_market[i - 1]["close"]
            returns.append(ret)

        sharpe = calc_sharpe(returns, periods_per_year=365 * 24 * 6)  # 假设 10min bars
        assert sharpe > 0, f"Trending market long Sharpe {sharpe:.4f} should be positive"

    def test_sharpe_negative_on_decline(self, declining_market):
        """下跌趋势中，做多策略的 Sharpe 应为负"""
        returns = []
        for i in range(1, len(declining_market)):
            ret = (declining_market[i]["close"] - declining_market[i - 1]["close"]) / declining_market[i - 1]["close"]
            returns.append(ret)

        sharpe = calc_sharpe(returns, periods_per_year=365 * 24 * 6)
        assert sharpe < 0, f"Declining market long Sharpe {sharpe:.4f} should be negative"

    def test_sharpe_zero_for_flat(self):
        """无波动时 Sharpe 应为 0"""
        returns = [0.0] * 100
        sharpe = calc_sharpe(returns)
        assert sharpe == 0.0

    def test_sharpe_consistency(self, trending_market):
        """相同输入 Sharpe 计算结果一致"""
        returns = []
        for i in range(1, len(trending_market)):
            ret = (trending_market[i]["close"] - trending_market[i - 1]["close"]) / trending_market[i - 1]["close"]
            returns.append(ret)

        s1 = calc_sharpe(returns)
        s2 = calc_sharpe(returns)
        assert s1 == s2, "Sharpe calculation should be deterministic"

    def test_short_sharpe_positive_on_decline(self, declining_market):
        """下跌趋势中，做空策略的 Sharpe 应为正"""
        returns = []
        for i in range(1, len(declining_market)):
            # 做空收益 = -(收盘价变化率)
            ret = -(declining_market[i]["close"] - declining_market[i - 1]["close"]) / declining_market[i - 1]["close"]
            returns.append(ret)

        sharpe = calc_sharpe(returns, periods_per_year=365 * 24 * 6)
        assert sharpe > 0, f"Declining market short Sharpe {sharpe:.4f} should be positive"

    def test_risk_adjusted_return(self, trending_market):
        """风险调整后收益: 趋势策略的单位风险收益应为正"""
        import statistics
        returns = []
        for i in range(1, len(trending_market)):
            ret = (trending_market[i]["close"] - trending_market[i - 1]["close"]) / trending_market[i - 1]["close"]
            returns.append(ret)

        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns)
        # 单位风险收益 = mean / std
        risk_adj = mean_r / std_r if std_r > 0 else 0
        assert risk_adj > 0, f"Risk-adjusted return {risk_adj:.4f} should be positive in trend"
