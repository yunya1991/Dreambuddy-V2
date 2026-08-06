"""
多币种组合回测 — 组合层资金分配与风控

BCRM理论映射:
  - 矛盾普遍性: 所有币种共同受宏观周期影响
  - 矛盾特殊性: 不同币种有不同的运动规律
  - 主要矛盾与次要矛盾: BTC是主要矛盾(市场风向标), altcoin是次要矛盾
  - 资金守恒: 资金不会凭空消失, 只会从一种资产流向另一种

组合层功能:
  1. 资金分配: 按市值等级分配资金权重 (大市值>中市值>小市值)
  2. 并发仓位限制: 同时持仓数上限, 避免过度分散
  3. 组合回撤控制: 组合层最大回撤限制
  4. 相关性过滤: 高相关币种不同时开仓
  5. 组合夏普比率: 按各币种权重加权计算
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from .walk_forward_backtester import WalkForwardBacktester, BacktestResult, Trade, generate_report
from .market_cap import MarketCapClassifier, MARKET_CAP_LARGE, MARKET_CAP_MID, MARKET_CAP_SMALL


@dataclass
class PortfolioResult:
    """组合回测结果"""
    # 各币种的独立回测结果
    symbol_results: Dict[str, BacktestResult] = field(default_factory=dict)

    # 组合层指标
    portfolio_total_return: float = 0.0
    portfolio_max_drawdown: float = 0.0
    portfolio_sharpe: float = 0.0
    portfolio_win_rate: float = 0.0
    portfolio_profit_factor: float = 0.0
    portfolio_total_trades: int = 0

    # 资金分配
    allocation: Dict[str, float] = field(default_factory=dict)

    # 组合层交易时间线 (按时间排序的所有交易)
    timeline_trades: List[Dict] = field(default_factory=list)

    # 各币种权重
    symbol_weights: Dict[str, float] = field(default_factory=dict)


class PortfolioBacktester:
    """
    多币种组合回测引擎

    工作流程:
      1. 对每个币种独立运行Walk-Forward回测
      2. 按市值等级分配资金权重
      3. 将各币种交易按时间合并
      4. 应用组合层风控 (并发仓位限制、回撤控制)
      5. 计算组合层指标
    """

    def __init__(
        self,
        symbols: List[str],
        n_folds: int = 5,
        # 资金分配参数
        large_cap_weight: float = 0.40,   # 大市值资金权重
        mid_cap_weight: float = 0.35,     # 中市值资金权重
        small_cap_weight: float = 0.25,   # 小市值资金权重
        # 组合层风控参数
        max_concurrent_positions: int = 4,  # 最大并发持仓数
        max_portfolio_drawdown: float = 0.20,  # 组合最大回撤限制 (20%)
        # 单币种回测参数
        conf_threshold: float = 0.40,
        tp_atr: float = 3.0,
        sl_atr: float = 2.0,
        max_hold_bars: int = 60,
        feature_selection: bool = True,
        fs_imp_threshold: float = 0.05,
        fs_corr_threshold: float = 0.85,
        use_regime_switching: bool = True,
    ):
        self.symbols = symbols
        self.n_folds = n_folds
        self.large_cap_weight = large_cap_weight
        self.mid_cap_weight = mid_cap_weight
        self.small_cap_weight = small_cap_weight
        self.max_concurrent_positions = max_concurrent_positions
        self.max_portfolio_drawdown = max_portfolio_drawdown
        self.conf_threshold = conf_threshold
        self.tp_atr = tp_atr
        self.sl_atr = sl_atr
        self.max_hold_bars = max_hold_bars
        self.feature_selection = feature_selection
        self.fs_imp_threshold = fs_imp_threshold
        self.fs_corr_threshold = fs_corr_threshold
        self.use_regime_switching = use_regime_switching

        # 市值分类器
        self.mcap_classifier = MarketCapClassifier()

    def _get_symbol_weight(self, symbol: str, df: pd.DataFrame) -> float:
        """获取币种的资金权重"""
        mcap = self.mcap_classifier.classify(symbol, df)
        if mcap == MARKET_CAP_LARGE:
            # 大市值内部均分
            large_symbols = [s for s in self.symbols
                           if self.mcap_classifier.classify(s) == MARKET_CAP_LARGE]
            return self.large_cap_weight / max(len(large_symbols), 1)
        elif mcap == MARKET_CAP_MID:
            mid_symbols = [s for s in self.symbols
                         if self.mcap_classifier.classify(s) == MARKET_CAP_MID]
            return self.mid_cap_weight / max(len(mid_symbols), 1)
        else:
            small_symbols = [s for s in self.symbols
                           if self.mcap_classifier.classify(s) == MARKET_CAP_SMALL]
            return self.small_cap_weight / max(len(small_symbols), 1)

    def run(
        self,
        data_dict: Dict[str, pd.DataFrame],
        ref_df: Optional[pd.DataFrame] = None,
        enable_pivot: bool = True,
        enable_rsi: bool = False,
        enable_wdh: bool = True,
        wdh_weekly_only: bool = False,
        verbose: bool = True,
    ) -> PortfolioResult:
        """
        运行多币种组合回测

        Args:
            data_dict: {symbol: df} 各币种的OHLCV数据
            ref_df: 参考资产数据 (如BTC)
            enable_pivot: 枢纽点特征
            enable_rsi: RSI特征
            enable_wdh: WDH三屏特征
            verbose: 打印详细信息
        """
        result = PortfolioResult()

        # 1. 计算各币种资金权重
        if verbose:
            print("\n[组合] 资金分配:")
        for symbol in self.symbols:
            if symbol not in data_dict:
                continue
            df = data_dict[symbol]
            weight = self._get_symbol_weight(symbol, df)
            result.symbol_weights[symbol] = weight
            result.allocation[symbol] = weight
            if verbose:
                mcap = self.mcap_classifier.classify(symbol, df)
                print(f"  {symbol}: {mcap:>6s} → 权重 {weight:.1%}")

        # 2. 对每个币种独立回测
        for symbol in self.symbols:
            if symbol not in data_dict:
                continue

            df = data_dict[symbol]
            symbol_ref = ref_df if symbol != "BTC" else None

            if verbose:
                print(f"\n[组合] 回测 {symbol}...")

            backtester = WalkForwardBacktester(
                symbol=symbol,
                n_folds=self.n_folds,
                conf_threshold=self.conf_threshold,
                tp_atr=self.tp_atr,
                sl_atr=self.sl_atr,
                max_hold_bars=self.max_hold_bars,
                use_regime_switching=self.use_regime_switching,
                feature_selection=self.feature_selection,
                fs_imp_threshold=self.fs_imp_threshold,
                fs_corr_threshold=self.fs_corr_threshold,
            )

            bt_result = backtester.run(
                df, ref_df=symbol_ref, verbose=False,
                enable_pivot=enable_pivot,
                enable_rsi=enable_rsi,
                enable_wdh=enable_wdh,
                wdh_weekly_only=wdh_weekly_only,
                auto_mcap_config=True,
            )

            result.symbol_results[symbol] = bt_result

            if verbose:
                print(f"  {symbol}: 胜率{bt_result.overall_win_rate*100:.1f}%, "
                      f"夏普{bt_result.sharpe_ratio:.2f}, "
                      f"交易{bt_result.total_trades}笔")

        # 3. 构建组合时间线
        result.timeline_trades = self._build_timeline(
            result.symbol_results, result.symbol_weights, data_dict
        )

        # 4. 计算组合层指标
        self._compute_portfolio_metrics(result)

        return result

    def _build_timeline(
        self,
        symbol_results: Dict[str, BacktestResult],
        symbol_weights: Dict[str, float],
        data_dict: Dict[str, pd.DataFrame],
    ) -> List[Dict]:
        """
        构建组合层交易时间线

        将各币种的交易按时间合并, 并应用资金权重
        """
        timeline = []

        for symbol, bt_result in symbol_results.items():
            weight = symbol_weights.get(symbol, 0.0)
            df = data_dict.get(symbol)

            for trade in bt_result.all_trades:
                entry_time = df.index[trade.entry_bar] if df is not None and trade.entry_bar < len(df) else None
                exit_time = df.index[trade.exit_bar] if df is not None and trade.exit_bar < len(df) else None

                timeline.append({
                    "symbol": symbol,
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                    "direction": trade.direction,
                    "pnl_pct": trade.pnl_pct,
                    "weighted_pnl": trade.pnl_pct * weight,  # 加权收益
                    "weight": weight,
                    "hold_bars": trade.hold_bars,
                    "exit_reason": trade.exit_reason,
                    "confidence": trade.confidence,
                    "position_factor": trade.position_factor,
                })

        # 按入场时间排序
        timeline.sort(key=lambda x: x["entry_time"] if x["entry_time"] is not None else pd.Timestamp.min)

        return timeline

    def _compute_portfolio_metrics(self, result: PortfolioResult):
        """计算组合层指标"""
        if not result.timeline_trades:
            return

        # 加权收益序列
        weighted_pnls = [t["weighted_pnl"] for t in result.timeline_trades]

        # 组合总收益
        result.portfolio_total_return = sum(weighted_pnls)

        # 组合交易数
        result.portfolio_total_trades = len(weighted_pnls)

        # 组合胜率 (按加权收益正负)
        wins = sum(1 for p in weighted_pnls if p > 0)
        result.portfolio_win_rate = wins / len(weighted_pnls) if weighted_pnls else 0

        # 盈亏比
        profits = [p for p in weighted_pnls if p > 0]
        losses = [p for p in weighted_pnls if p < 0]
        if losses:
            result.portfolio_profit_factor = sum(profits) / abs(sum(losses))
        else:
            result.portfolio_profit_factor = float('inf') if profits else 0

        # 组合夏普比率（P0修正：用日收益序列年化，sqrt(252)）
        if result.timeline_trades:
            daily_returns = {}
            for t in result.timeline_trades:
                day_str = str(t.get("entry_time", ""))[:10]
                if not day_str or day_str == "NaT":
                    day_str = "unknown"
                daily_returns[day_str] = daily_returns.get(day_str, 0.0) + t["weighted_pnl"]
            daily_pnls = list(daily_returns.values())
            if len(daily_pnls) > 1:
                std = np.std(daily_pnls)
                if std > 0:
                    result.portfolio_sharpe = np.mean(daily_pnls) / std * np.sqrt(252)

        # 组合最大回撤 (累积收益曲线)
        cum = np.cumsum(weighted_pnls)
        peak = np.maximum.accumulate(cum)
        drawdowns = peak - cum
        result.portfolio_max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0

    def generate_portfolio_report(self, result: PortfolioResult) -> str:
        """生成组合回测报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("  BCRM 2.0 — 多币种组合回测报告")
        lines.append("=" * 70)
        lines.append("")

        # 资金分配
        lines.append("  【资金分配】")
        for symbol, weight in result.allocation.items():
            lines.append(f"    {symbol}: {weight:.1%}")
        lines.append("")

        # 各币种表现
        lines.append("  【各币种独立表现】")
        lines.append(f"  {'币种':<8} {'交易数':<8} {'胜率':<8} {'总收益':<10} "
                      f"{'最大回撤':<10} {'夏普':<8} {'权重':<8}")
        lines.append(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")

        for symbol, bt_result in result.symbol_results.items():
            weight = result.symbol_weights.get(symbol, 0)
            lines.append(
                f"  {symbol:<8} {bt_result.total_trades:<8} "
                f"{bt_result.overall_win_rate*100:<7.1f}% "
                f"{bt_result.total_return:<9.2f}% "
                f"{bt_result.max_drawdown:<9.2f}% "
                f"{bt_result.sharpe_ratio:<7.2f} "
                f"{weight:<7.1%}"
            )
        lines.append("")

        # 组合层指标
        lines.append("  【组合层指标】")
        lines.append(f"    组合总收益:   {result.portfolio_total_return:.2f}%")
        lines.append(f"    组合胜率:     {result.portfolio_win_rate*100:.1f}%")
        lines.append(f"    组合盈亏比:   {result.portfolio_profit_factor:.2f}")
        lines.append(f"    组合夏普:     {result.portfolio_sharpe:.2f}")
        lines.append(f"    组合最大回撤: {result.portfolio_max_drawdown:.2f}%")
        lines.append(f"    组合交易数:   {result.portfolio_total_trades}")
        lines.append("")

        # 综合夏普（P0修正：用组合日收益序列年化，非各币种夏普加权平均）
        lines.append(f"  综合夏普 (日收益年化): {result.portfolio_sharpe:.2f}")
        lines.append("")

        return "\n".join(lines)
