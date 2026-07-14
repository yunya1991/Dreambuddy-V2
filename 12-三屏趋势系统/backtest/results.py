"""三屏趋势系统 — 回测结果与报告生成

提供回测结果的汇总、对比、格式化输出等功能。
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np


class BacktestResult:
    """回测结果封装类

    提供便捷的访问方式和格式化输出。
    """

    def __init__(self, result_dict: Dict):
        self._result = result_dict

    @property
    def symbol(self) -> str:
        return self._result.get("symbol", "")

    @property
    def metrics(self) -> Dict:
        return self._result.get("metrics", {})

    @property
    def equity_curve(self) -> pd.Series:
        return self._result.get("equity_curve", pd.Series())

    @property
    def returns(self) -> pd.Series:
        return self._result.get("returns", pd.Series())

    @property
    def trades(self) -> pd.DataFrame:
        return self._result.get("trades", pd.DataFrame())

    @property
    def total_return_pct(self) -> float:
        return self.metrics.get("total_return_pct", 0)

    @property
    def annualized_return_pct(self) -> float:
        return self.metrics.get("annualized_return_pct", 0)

    @property
    def sharpe_ratio(self) -> float:
        return self.metrics.get("sharpe_ratio", 0)

    @property
    def max_drawdown_pct(self) -> float:
        return self.metrics.get("max_drawdown_pct", 0)

    @property
    def win_rate_pct(self) -> float:
        return self.metrics.get("win_rate_pct", 0)

    def summary(self) -> str:
        """生成文本格式的回测摘要"""
        m = self.metrics
        lines = [
            "=" * 60,
            f"  回测结果摘要 — {self.symbol}",
            "=" * 60,
            "",
            "【收益指标】",
            f"  累计收益:     {m.get('total_return_pct', 0):>8.2f}%",
            f"  年化收益:     {m.get('annualized_return_pct', 0):>8.2f}%",
            f"  初始资金:     {m.get('initial_equity', 0):>10.2f}",
            f"  最终资金:     {m.get('final_equity', 0):>10.2f}",
            f"  回测周期:     {m.get('years', 0):>8.2f} 年",
            "",
            "【风险指标】",
            f"  年化波动率:   {m.get('annualized_volatility_pct', 0):>8.2f}%",
            f"  下行波动率:   {m.get('downside_volatility_pct', 0):>8.2f}%",
            f"  最大回撤:     {m.get('max_drawdown_pct', 0):>8.2f}%",
            f"  VaR (95%):    {m.get('var_95_pct', 0):>8.2f}%",
            f"  CVaR (95%):   {m.get('cvar_95_pct', 0):>8.2f}%",
            "",
            "【风险调整收益】",
            f"  夏普比率:     {m.get('sharpe_ratio', 0):>8.2f}",
            f"  索提诺比率:   {m.get('sortino_ratio', 0):>8.2f}",
            f"  卡玛比率:     {m.get('calmar_ratio', 0):>8.2f}",
            "",
            "【交易统计】",
            f"  总交易次数:   {m.get('total_trades', 0):>8d}",
            f"  胜率:         {m.get('win_rate_pct', 0):>8.2f}%",
            f"  盈亏比:       {m.get('profit_factor', 0):>8.2f}",
            f"  平均每笔盈亏: {m.get('avg_trade_pnl_pct', 0):>8.2f}%",
            f"  最大连胜:     {m.get('max_consecutive_wins', 0):>8d}",
            f"  最大连亏:     {m.get('max_consecutive_losses', 0):>8d}",
            "",
            "【一致性】",
            f"  月胜率:       {m.get('monthly_win_rate_pct', 0):>8.2f}%",
            "=" * 60,
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        return self._result.copy()


def compare_results(
    results: Dict[str, BacktestResult],
    metrics: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    对比多个回测结果

    参数:
        results: {策略名: BacktestResult}
        metrics: 要对比的指标列表，默认包含核心指标

    返回:
        对比 DataFrame
    """
    if metrics is None:
        metrics = [
            "total_return_pct",
            "annualized_return_pct",
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "max_drawdown_pct",
            "win_rate_pct",
            "profit_factor",
            "total_trades",
        ]

    data = {}
    for name, result in results.items():
        data[name] = {m: result.metrics.get(m, 0) for m in metrics}

    return pd.DataFrame(data).T


def format_comparison_table(comparison_df: pd.DataFrame) -> str:
    """格式化对比表为可读文本"""
    metric_labels = {
        "total_return_pct": "累计收益(%)",
        "annualized_return_pct": "年化收益(%)",
        "sharpe_ratio": "夏普比率",
        "sortino_ratio": "索提诺",
        "calmar_ratio": "卡玛比率",
        "max_drawdown_pct": "最大回撤(%)",
        "win_rate_pct": "胜率(%)",
        "profit_factor": "盈亏比",
        "total_trades": "交易次数",
    }

    lines = ["=" * 80]
    header = f"{'指标':<15}"
    for col in comparison_df.columns:
        header += f"{col:>15}"
    lines.append(header)
    lines.append("-" * 80)

    for metric in comparison_df.index:
        label = metric_labels.get(metric, metric)
        row = f"{label:<15}"
        for col in comparison_df.columns:
            val = comparison_df.loc[metric, col]
            if isinstance(val, float):
                row += f"{val:>15.2f}"
            else:
                row += f"{val:>15}"
        lines.append(row)

    lines.append("=" * 80)
    return "\n".join(lines)
