"""三屏趋势系统 — Walk-Forward 滚动前向验证

参考微软 Qlib / VectorBT 的 Walk-Forward Analysis 设计：
- 用历史窗口训练/优化策略参数
- 在后续窗口上测试（样本外）
- 滚动推进，汇总所有样本外结果

核心价值：
- 防止过拟合：确保策略在"未来"数据上也有效
- 模拟实盘：用过去优化，用未来验证
- 参数稳定性：观察参数在不同市场环境下的表现
"""

from typing import Dict, List, Optional, Tuple, Callable
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')


class WalkForwardAnalyzer:
    """Walk-Forward 滚动前向验证引擎

    用法:
        analyzer = WalkForwardAnalyzer(
            train_window=252,  # 训练窗口（252天≈1年）
            test_window=21,    # 测试窗口（21天≈1月）
        )
        result = analyzer.run(prices, strategy, param_optimizer=None)
    """

    def __init__(
        self,
        train_window: int = 252,
        test_window: int = 21,
        step_size: Optional[int] = None,
    ):
        """
        参数:
            train_window: 训练窗口长度（K线数量）
            test_window:  测试窗口长度
            step_size:    滚动步长（默认=test_window）
        """
        self.train_window = train_window
        self.test_window = test_window
        self.step_size = step_size or test_window

    def run(
        self,
        prices: pd.DataFrame,
        strategy,
        param_optimizer: Optional[Callable] = None,
        engine=None,
    ) -> Dict:
        """
        运行 Walk-Forward 滚动验证

        参数:
            prices: OHLCV DataFrame（需有 date 列或 DatetimeIndex）
            strategy: 策略对象（需有 generate_signals 方法）
            param_optimizer: 参数优化函数（可选）
                签名: optimizer(train_df) -> dict (最优参数)
                如果为None，使用策略默认参数
            engine: 回测引擎（如不提供则创建默认的）

        返回:
            {
                "folds": List[Dict],      # 每折结果
                "aggregated": Dict,        # 汇总指标
                "oos_sharpe": float,       # 样本外夏普
                "is_sharpe": float,        # 样本内夏普
                "decay_ratio": float,      # 夏普衰减率
                "stability": float,        # 稳定性评分
            }
        """
        if engine is None:
            from .engine import BacktestEngine
            engine = BacktestEngine()

        df = self._ensure_index(prices)
        n = len(df)

        min_required = self.train_window + self.test_window
        if n < min_required:
            return {
                "error": f"数据不足: 需要≥{min_required}根K线，实际{n}根",
                "folds": [],
                "aggregated": {},
            }

        folds = []
        oos_returns_list = []
        is_sharpes = []
        oos_sharpes = []

        start = 0
        fold_idx = 0

        while start + min_required <= n:
            train_end = start + self.train_window
            test_end = min(train_end + self.test_window, n)

            train_df = df.iloc[start:train_end].copy()
            test_df = df.iloc[train_end:test_end].copy()

            if len(test_df) < 5:
                break

            history_df = df.iloc[:test_end].copy()

            fold_result = self._run_single_fold(
                fold_idx, train_df, test_df, history_df,
                strategy, param_optimizer, engine,
            )

            folds.append(fold_result)
            is_sharpes.append(fold_result["is_sharpe"])
            oos_sharpes.append(fold_result["oos_sharpe"])

            if fold_result["oos_returns"] is not None:
                oos_returns_list.append(fold_result["oos_returns"])

            start += self.step_size
            fold_idx += 1

        aggregated = self._aggregate_oos_results(oos_returns_list, engine)

        is_mean = np.mean(is_sharpes) if is_sharpes else 0
        oos_mean = np.mean(oos_sharpes) if oos_sharpes else 0
        decay = self._calc_decay_ratio(is_mean, oos_mean)
        stability = self._calc_stability_score(oos_sharpes, is_sharpes)

        return {
            "folds": folds,
            "n_folds": len(folds),
            "aggregated": aggregated,
            "is_sharpe": round(is_mean, 2),
            "oos_sharpe": round(oos_mean, 2),
            "decay_ratio": round(decay * 100, 1),
            "stability": round(stability, 1),
            "train_window": self.train_window,
            "test_window": self.test_window,
            "step_size": self.step_size,
        }

    def _run_single_fold(
        self,
        fold_idx: int,
        train_df: pd.DataFrame,
        test_df: pd.DataFrame,
        history_df: pd.DataFrame,
        strategy,
        param_optimizer: Optional[Callable],
        engine,
    ) -> Dict:
        """运行单折验证

        参数:
            history_df: train+test 的完整历史数据，用于生成信号（避免warmup不足）
        """
        train_start = train_df.index[0]
        train_end = train_df.index[-1]
        test_start = test_df.index[0]
        test_end = test_df.index[-1]

        if param_optimizer is not None:
            try:
                best_params = param_optimizer(train_df)
            except Exception:
                best_params = {}
        else:
            best_params = {}

        if best_params and hasattr(strategy, '__dict__'):
            for k, v in best_params.items():
                if hasattr(strategy, k):
                    setattr(strategy, k, v)

        train_signals = strategy.generate_signals(train_df)
        train_prices = train_df["close"]
        is_result = engine.run(train_prices, train_signals, symbol=f"fold{fold_idx}_train")
        is_sharpe = is_result["metrics"].get("sharpe_ratio", 0)

        full_signals = strategy.generate_signals(history_df)
        test_signals = full_signals.loc[test_df.index]
        test_prices = test_df["close"]
        oos_result = engine.run(test_prices, test_signals, symbol=f"fold{fold_idx}_test")
        oos_sharpe = oos_result["metrics"].get("sharpe_ratio", 0)

        return {
            "fold": fold_idx,
            "train_start": str(train_start)[:10],
            "train_end": str(train_end)[:10],
            "test_start": str(test_start)[:10],
            "test_end": str(test_end)[:10],
            "train_bars": len(train_df),
            "test_bars": len(test_df),
            "is_sharpe": round(is_sharpe, 2),
            "oos_sharpe": round(oos_sharpe, 2),
            "is_return_pct": round(is_result["metrics"].get("total_return_pct", 0), 2),
            "oos_return_pct": round(oos_result["metrics"].get("total_return_pct", 0), 2),
            "is_max_dd_pct": round(is_result["metrics"].get("max_drawdown_pct", 0), 2),
            "oos_max_dd_pct": round(oos_result["metrics"].get("max_drawdown_pct", 0), 2),
            "oos_trades": oos_result["metrics"].get("total_trades", 0),
            "oos_returns": oos_result.get("returns"),
            "best_params": best_params,
        }

    def _aggregate_oos_results(
        self, returns_list: List[pd.Series], engine
    ) -> Dict:
        """汇总所有样本外结果"""
        if not returns_list:
            return {}

        all_returns = pd.concat(returns_list, ignore_index=True)

        from .metrics import calculate_performance_metrics

        equity = engine.initial_capital * (1 + all_returns).cumprod()
        equity.iloc[0] = engine.initial_capital

        trades_df = pd.DataFrame()
        metrics = calculate_performance_metrics(equity, all_returns, trades_df)

        return {
            "oos_total_return_pct": metrics.get("total_return_pct", 0),
            "oos_annualized_return_pct": metrics.get("annualized_return_pct", 0),
            "oos_sharpe": metrics.get("sharpe_ratio", 0),
            "oos_sortino": metrics.get("sortino_ratio", 0),
            "oos_max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
            "oos_volatility_pct": metrics.get("annualized_volatility_pct", 0),
            "oos_periods": len(all_returns),
        }

    def _calc_decay_ratio(self, is_sharpe: float, oos_sharpe: float) -> float:
        """计算夏普衰减率

        衰减率 = (样本内 - 样本外) / 样本内
        <0: 样本外更好（罕见但可能）
        0~30%: 良好
        30~50%: 一般
        >50%: 过拟合风险高
        """
        if is_sharpe <= 0:
            return 0.0
        return (is_sharpe - oos_sharpe) / abs(is_sharpe)

    def _calc_stability_score(
        self, oos_sharpes: List[float], is_sharpes: List[float]
    ) -> float:
        """计算稳定性评分（0-100）

        评分依据：
        - 样本外夏普的均值/标准差比（越高越稳定）
        - 样本内外夏普的相关性（越高越稳定）
        """
        if len(oos_sharpes) < 2:
            return 50.0

        oos_arr = np.array(oos_sharpes)
        is_arr = np.array(is_sharpes)

        oos_mean = np.mean(oos_arr)
        oos_std = np.std(oos_arr)

        if oos_std > 1e-8:
            consistency = min(abs(oos_mean) / oos_std, 2.0) / 2.0
        else:
            consistency = 0.3

        if len(oos_arr) == len(is_arr) and oos_std > 1e-8 and np.std(is_arr) > 1e-8:
            try:
                corr = np.corrcoef(is_arr, oos_arr)[0, 1]
                corr_score = max(0, min(corr, 1.0))
            except Exception:
                corr_score = 0.3
        else:
            corr_score = 0.3

        positive_ratio = float(np.mean(oos_arr > 0))

        score = (consistency * 0.4 + corr_score * 0.3 + positive_ratio * 0.3) * 100
        return float(min(max(score, 0.0), 100.0))

    def _ensure_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """确保 DataFrame 有合适的索引"""
        df = df.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            else:
                df.index = pd.RangeIndex(len(df))
        return df

    def format_report(self, result: Dict) -> str:
        """格式化 Walk-Forward 报告"""
        if "error" in result:
            return f"❌ {result['error']}"

        lines = [
            "=" * 70,
            "  Walk-Forward 滚动前向验证报告",
            "=" * 70,
            "",
            f"  训练窗口: {result['train_window']} 根K线",
            f"  测试窗口: {result['test_window']} 根K线",
            f"  滚动步长: {result['step_size']} 根K线",
            f"  总折数:   {result['n_folds']}",
            "",
            "【汇总指标】",
            f"  样本内夏普 (IS):  {result['is_sharpe']:>8.2f}",
            f"  样本外夏普 (OOS): {result['oos_sharpe']:>8.2f}",
            f"  夏普衰减率:       {result['decay_ratio']:>7.1f}%",
            f"  稳定性评分:       {result['stability']:>7.1f}/100",
            "",
        ]

        agg = result.get("aggregated", {})
        if agg:
            lines.extend([
                "【样本外汇总绩效】",
                f"  累计收益:     {agg.get('oos_total_return_pct', 0):>8.2f}%",
                f"  年化收益:     {agg.get('oos_annualized_return_pct', 0):>8.2f}%",
                f"  最大回撤:     {agg.get('oos_max_drawdown_pct', 0):>8.2f}%",
                f"  年化波动率:   {agg.get('oos_volatility_pct', 0):>8.2f}%",
                f"  索提诺比率:   {agg.get('oos_sortino', 0):>8.2f}",
                "",
            ])

        lines.append("【各折详情】")
        lines.append(f"{'折':>3} {'训练期':>12} {'测试期':>12} {'IS夏普':>7} {'OOS夏普':>8} {'IS收益':>8} {'OOS收益':>9} {'OOS回撤':>8}")
        lines.append("-" * 80)

        for fold in result["folds"]:
            lines.append(
                f"{fold['fold']:>3} "
                f"{fold['train_start']}~{fold['train_end']:>8} "
                f"{fold['test_start']}~{fold['test_end']:>8} "
                f"{fold['is_sharpe']:>7.2f} "
                f"{fold['oos_sharpe']:>8.2f} "
                f"{fold['is_return_pct']:>7.1f}% "
                f"{fold['oos_return_pct']:>8.1f}% "
                f"{fold['oos_max_dd_pct']:>7.1f}%"
            )

        lines.extend([
            "-" * 80,
            "",
            "【过拟合评估】",
        ])

        decay = result["decay_ratio"]
        if decay < 0:
            lines.append(f"  ✅ 夏普衰减 {decay:.1f}%：样本外优于样本内（罕见，需检查数据泄漏）")
        elif decay < 30:
            lines.append(f"  ✅ 夏普衰减 {decay:.1f}%：过拟合风险低，策略稳健")
        elif decay < 50:
            lines.append(f"  ⚠️ 夏普衰减 {decay:.1f}%：过拟合风险中等，需关注")
        else:
            lines.append(f"  ❌ 夏普衰减 {decay:.1f}%：过拟合风险高，策略可能不稳健")

        stability = result["stability"]
        if stability >= 70:
            lines.append(f"  ✅ 稳定性 {stability:.1f}/100：策略表现稳定")
        elif stability >= 50:
            lines.append(f"  ⚠️ 稳定性 {stability:.1f}/100：稳定性一般")
        else:
            lines.append(f"  ❌ 稳定性 {stability:.1f}/100：策略不稳定，需改进")

        lines.append("=" * 70)
        return "\n".join(lines)
