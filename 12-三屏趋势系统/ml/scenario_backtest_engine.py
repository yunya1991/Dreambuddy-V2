"""分场景回测引擎

按四类交易目的（DIP_BUY / TOP_EXIT / BEAR_SHORT / BEAR_EXIT）分别回测和评估，
支持特征消融实验，量化每个特征对各目的的增量贡献。

核心功能：
1. 分场景回测：对四类目的分别计算信号质量和交易绩效
2. 特征消融：逐个或分组移除特征，评估其增量贡献
3. 基线对比：和v2增强版MA200基线策略对比
4. 综合评分：按权重计算综合评分，判断是否优于基线

设计原则：
- 渐进式：不替代现有回测引擎，作为补充层
- 可扩展：支持新增目的类型、新增评估指标
- 可溯源：每个回测结果都记录实验条件和参数

依赖：
- backtest/engine.py：基础回测引擎
- backtest/strategy.py：策略实现（含v2基线）
- four_objective_feature_mapper.py：四类目的特征映射
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest.engine import BacktestEngine
from backtest.strategy import EnhancedMA200Strategy, BaseStrategy
from backtest.metrics import calculate_performance_metrics


# ── 数据结构 ──────────────────────────────────────────────────────────

@dataclass
class ObjectiveMetrics:
    """单个目的的回测指标"""
    objective: str                    # 目的类型
    objective_name: str               # 目的中文名
    total_signals: int = 0            # 总信号数
    signal_freq_pct: float = 0.0      # 信号频率（占总天数%）
    win_rate: float = 0.0             # 胜率
    avg_return: float = 0.0           # 平均收益
    median_return: float = 0.0        # 中位数收益
    max_return: float = 0.0           # 最大单笔收益
    min_return: float = 0.0           # 最小单笔收益
    profit_factor: float = 0.0        # 盈亏比
    max_drawdown: float = 0.0         # 按信号顺序的最大回撤
    sharpe_like: float = 0.0         # 类夏普比率（均收益/收益标准差）
    label_precision: float = 0.0      # 标签准确率（和ground truth对比）
    label_recall: float = 0.0         # 标签召回率
    label_f1: float = 0.0             # 标签F1分数
    baseline_delta: float = 0.0       # 相对基线的提升幅度


@dataclass
class ScenarioBacktestResult:
    """分场景回测完整结果"""
    experiment_name: str              # 实验名称
    strategy_name: str                # 策略名称
    symbol: str                       # 交易标的
    start_date: str                   # 开始日期
    end_date: str                     # 结束日期
    total_days: int = 0               # 总交易日数

    # 各目的指标
    objective_metrics: Dict[str, ObjectiveMetrics] = field(default_factory=dict)

    # 全周期综合指标（和现有回测结果对齐）
    overall_total_return: float = 0.0
    overall_sharpe: float = 0.0
    overall_max_drawdown: float = 0.0
    overall_calmar: float = 0.0
    overall_win_rate: float = 0.0
    overall_trade_count: int = 0

    # 基线对比
    baseline_name: str = "EnhancedMA200_v2"
    baseline_sharpe: float = 0.0
    baseline_calmar: float = 0.0
    baseline_maxdd: float = 0.0
    composite_score: float = 0.0     # 综合评分（>1.0优于基线）

    # 元信息
    created_at: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def save(self, filepath: str) -> None:
        """保存结果为JSON"""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "ScenarioBacktestResult":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        obj_metrics = {}
        for obj, m in data.get("objective_metrics", {}).items():
            obj_metrics[obj] = ObjectiveMetrics(**m)
        data["objective_metrics"] = obj_metrics
        return cls(**data)


@dataclass
class AblationResult:
    """消融实验结果"""
    feature_name: str                  # 被移除的特征/特征组
    objective: str                     # 目标目的
    baseline_accuracy: float = 0.0     # 基线（全特征）准确率
    ablated_accuracy: float = 0.0      # 消融后准确率
    accuracy_delta: float = 0.0        # 准确率变化（负=该特征有正贡献）
    baseline_sharpe: float = 0.0       # 基线夏普
    ablated_sharpe: float = 0.0        # 消融后夏普
    sharpe_delta: float = 0.0          # 夏普变化
    importance_score: float = 0.0      # 重要性综合评分


# ── 分场景回测引擎 ────────────────────────────────────────────────────

class ScenarioBacktestEngine:
    """分场景回测引擎

    按四类目的分别评估策略表现，支持特征消融实验。
    """

    def __init__(
        self,
        baseline_strategy: Optional[BaseStrategy] = None,
        result_dir: Optional[str] = None,
    ):
        """
        Args:
            baseline_strategy: 基线策略实例，默认用EnhancedMA200Strategy
            result_dir: 结果保存目录，默认 ml/backtest_results/
        """
        from ml.four_objective_feature_mapper import FourObjectiveFeatureMapper

        self.mapper = FourObjectiveFeatureMapper()
        self.baseline_strategy = baseline_strategy or EnhancedMA200Strategy()

        if result_dir is None:
            result_dir = Path(__file__).parent / "backtest_results"
        self.result_dir = Path(result_dir)
        self.result_dir.mkdir(parents=True, exist_ok=True)

    # ── 核心方法：分场景回测 ──────────────────────────────────────────

    def run_scenario_backtest(
        self,
        prices: pd.DataFrame,
        strategy: BaseStrategy,
        strategy_name: str,
        symbol: str = "BTC",
        experiment_name: Optional[str] = None,
    ) -> ScenarioBacktestResult:
        """运行分场景回测

        Args:
            prices: OHLCV数据，索引为datetime
            strategy: 策略实例
            strategy_name: 策略名称
            symbol: 交易标的
            experiment_name: 实验名称（自动生成则留空）

        Returns:
            ScenarioBacktestResult 完整结果
        """
        if experiment_name is None:
            experiment_name = f"{strategy_name}_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 1. 运行基础回测（全周期）
        engine = BacktestEngine()
        position_sizes = strategy.generate_signals(prices)
        bt_result = engine.run(prices["close"], position_sizes, symbol=symbol)

        equity = bt_result["equity_curve"]
        returns = bt_result["returns"]
        trades = bt_result["trades"]
        overall_metrics = bt_result["metrics"]

        # 2. 计算基线（v2）的全周期指标
        baseline_engine = BacktestEngine()
        baseline_pos = self.baseline_strategy.generate_signals(prices)
        baseline_bt = baseline_engine.run(prices["close"], baseline_pos, symbol=symbol)
        baseline_metrics = baseline_bt["metrics"]

        # 构造signals DataFrame（用于分场景分析）
        signals_df = pd.DataFrame({"position": position_sizes})

        # 4. 按四类目的分别评估
        objective_metrics = self._evaluate_all_objectives(
            prices, signals_df, strategy
        )

        # 5. 计算综合评分
        composite_score = self._compute_composite_score(
            overall_metrics, baseline_metrics
        )

        # 6. 组装结果
        result = ScenarioBacktestResult(
            experiment_name=experiment_name,
            strategy_name=strategy_name,
            symbol=symbol,
            start_date=str(prices.index[0].date()),
            end_date=str(prices.index[-1].date()),
            total_days=len(prices),
            objective_metrics=objective_metrics,
            overall_total_return=overall_metrics.get("total_return_pct", 0) / 100,
            overall_sharpe=overall_metrics.get("sharpe_ratio", 0),
            overall_max_drawdown=overall_metrics.get("max_drawdown_pct", 0) / 100,
            overall_calmar=overall_metrics.get("calmar_ratio", 0),
            overall_win_rate=overall_metrics.get("win_rate_pct", 0) / 100,
            overall_trade_count=overall_metrics.get("total_trades", 0),
            baseline_sharpe=baseline_metrics.get("sharpe_ratio", 0),
            baseline_calmar=baseline_metrics.get("calmar_ratio", 0),
            baseline_maxdd=baseline_metrics.get("max_drawdown_pct", 0) / 100,
            composite_score=composite_score,
            created_at=datetime.now().isoformat(),
            parameters={
                "strategy_params": getattr(strategy, "params", {}),
            },
        )

        return result

    # ── 消融实验 ────────────────────────────────────────────────────

    def run_ablation_study(
        self,
        prices: pd.DataFrame,
        strategy_factory: Callable[[List[str]], BaseStrategy],
        feature_list: List[str],
        objective: str,
        baseline_feature_set: Optional[List[str]] = None,
        strategy_name_prefix: str = "Ablation",
    ) -> List[AblationResult]:
        """运行特征消融实验

        逐个移除特征，评估各特征对某目的的增量贡献。

        Args:
            prices: OHLCV数据
            strategy_factory: 接受特征列表，返回策略实例的工厂函数
            feature_list: 要消融的特征列表
            objective: 目标目的类型
            baseline_feature_set: 基线特征集（默认用feature_list全集）
            strategy_name_prefix: 策略名称前缀

        Returns:
            消融结果列表，按重要性降序
        """
        if baseline_feature_set is None:
            baseline_feature_set = feature_list.copy()

        # 1. 基线（全特征）
        baseline_strategy = strategy_factory(baseline_feature_set)
        baseline_result = self.run_scenario_backtest(
            prices, baseline_strategy,
            strategy_name=f"{strategy_name_prefix}_baseline",
        )
        baseline_obj = baseline_result.objective_metrics.get(
            objective, ObjectiveMetrics(objective=objective, objective_name="")
        )

        # 2. 逐个消融
        results = []
        for feat in feature_list:
            ablated_features = [f for f in baseline_feature_set if f != feat]
            ablated_strategy = strategy_factory(ablated_features)
            ablated_result = self.run_scenario_backtest(
                prices, ablated_strategy,
                strategy_name=f"{strategy_name_prefix}_no_{feat}",
            )
            ablated_obj = ablated_result.objective_metrics.get(
                objective, ObjectiveMetrics(objective=objective, objective_name="")
            )

            acc_delta = ablated_obj.label_precision - baseline_obj.label_precision
            sharpe_delta = (
                ablated_result.overall_sharpe - baseline_result.overall_sharpe
            )
            # 重要性：准确率下降越多 + 夏普下降越多 = 越重要
            importance = abs(acc_delta) * 0.6 + abs(sharpe_delta) * 0.4

            results.append(AblationResult(
                feature_name=feat,
                objective=objective,
                baseline_accuracy=baseline_obj.label_precision,
                ablated_accuracy=ablated_obj.label_precision,
                accuracy_delta=acc_delta,
                baseline_sharpe=baseline_result.overall_sharpe,
                ablated_sharpe=ablated_result.overall_sharpe,
                sharpe_delta=sharpe_delta,
                importance_score=importance,
            ))

        # 按重要性降序
        results.sort(key=lambda x: x.importance_score, reverse=True)
        return results

    # ── 内部方法 ────────────────────────────────────────────────────

    def _evaluate_all_objectives(
        self,
        prices: pd.DataFrame,
        signals: pd.DataFrame,
        strategy: BaseStrategy,
    ) -> Dict[str, ObjectiveMetrics]:
        """评估四类目的的表现"""
        results = {}
        for obj in self.mapper.list_objectives():
            obj_metrics = self._evaluate_single_objective(
                prices, signals, strategy, obj
            )
            results[obj] = obj_metrics
        return results

    def _evaluate_single_objective(
        self,
        prices: pd.DataFrame,
        signals: pd.DataFrame,
        strategy: BaseStrategy,
        objective: str,
    ) -> ObjectiveMetrics:
        """评估单个目的的表现"""
        ldef = self.mapper.get_label_def(objective)
        obj_name = ldef.get("name", objective)

        # 1. 生成ground truth标签
        true_labels = self.mapper.generate_labels(prices, objective)

        # 2. 提取策略在该目的上的信号
        #    这里需要根据策略类型做适配
        #    对于规则策略，用策略的买卖信号近似对应目的的信号
        pred_signals = self._extract_objective_signals(
            signals, strategy, objective
        )

        # 3. 对齐长度
        min_len = min(len(true_labels), len(pred_signals))
        true_labels = true_labels.iloc[:min_len]
        pred_signals = pred_signals.iloc[:min_len]

        # 4. 计算信号频率
        total_days = len(pred_signals)
        signal_count = int(np.sum(pred_signals > 0))
        signal_freq = signal_count / total_days * 100 if total_days > 0 else 0

        # 5. 计算分类指标（precision/recall/f1）
        precision, recall, f1 = self._calc_classification_metrics(
            true_labels.values.astype(int),
            (pred_signals.values > 0).astype(int),
        )

        # 6. 计算按信号交易的收益统计
        avg_ret, med_ret, max_ret, min_ret, pf, win_rate = (
            self._calc_signal_returns(prices, pred_signals, objective)
        )

        return ObjectiveMetrics(
            objective=objective,
            objective_name=obj_name,
            total_signals=signal_count,
            signal_freq_pct=signal_freq,
            win_rate=win_rate,
            avg_return=avg_ret,
            median_return=med_ret,
            max_return=max_ret,
            min_return=min_ret,
            profit_factor=pf,
            label_precision=precision,
            label_recall=recall,
            label_f1=f1,
        )

    def _extract_objective_signals(
        self,
        signals: pd.DataFrame,
        strategy: BaseStrategy,
        objective: str,
    ) -> pd.Series:
        """从策略信号中提取对应目的的信号

        对于规则策略（如v2增强版MA200），用已知的规则映射：
        - DIP_BUY: 抄底买入信号（position从0变正，且处于MA200下方）
        - TOP_EXIT: 逃顶卖出信号（position从正变0/负，且处于顶部区域）
        - BEAR_SHORT: 做空开仓信号（position从0变负，且跌破MA200）
        - BEAR_EXIT: 做空平仓信号（position从负变0/正，且处于底部区域）

        对于ML策略，可以从置信度中提取。
        """
        n = len(signals)
        obj_signal = np.zeros(n)

        if "position" in signals.columns:
            pos = signals["position"].values

            if objective == "dip_buy":
                # 抄底：仓位从空变多，且价格相对低位
                for i in range(1, n):
                    if pos[i] > 0 and pos[i-1] <= 0:
                        obj_signal[i] = 1.0

            elif objective == "top_exit":
                # 逃顶：仓位从多变空/平
                for i in range(1, n):
                    if pos[i] <= 0 and pos[i-1] > 0:
                        obj_signal[i] = 1.0

            elif objective == "bear_short":
                # 做空：仓位从平变负
                for i in range(1, n):
                    if pos[i] < 0 and pos[i-1] >= 0:
                        obj_signal[i] = 1.0

            elif objective == "bear_exit":
                # 空平：仓位从负变平/正
                for i in range(1, n):
                    if pos[i] >= 0 and pos[i-1] < 0:
                        obj_signal[i] = 1.0

        return pd.Series(obj_signal, index=signals.index)

    def _calc_classification_metrics(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
    ) -> Tuple[float, float, float]:
        """计算分类指标：precision, recall, f1"""
        tp = np.sum((y_true == 1) & (y_pred == 1))
        fp = np.sum((y_true == 0) & (y_pred == 1))
        fn = np.sum((y_true == 1) & (y_pred == 0))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return precision, recall, f1

    def _calc_signal_returns(
        self,
        prices: pd.DataFrame,
        signals: pd.Series,
        objective: str,
    ) -> Tuple[float, float, float, float, float, float]:
        """计算按信号交易的收益统计

        Returns:
            (平均收益, 中位数收益, 最大收益, 最小收益, 盈亏比, 胜率)
        """
        closes = prices["close"].values
        sig_values = signals.values
        n = len(closes)
        lookahead = self.mapper.get_label_def(objective).get(
            "lookahead_days", 10
        )

        returns = []
        for i in range(n - lookahead):
            if sig_values[i] > 0:
                entry = closes[i]
                if objective in ("dip_buy", "bear_exit"):
                    # 做多方向
                    exit_price = closes[min(i + lookahead, n - 1)]
                    ret = (exit_price - entry) / entry
                else:
                    # 做空方向
                    exit_price = closes[min(i + lookahead, n - 1)]
                    ret = (entry - exit_price) / entry
                returns.append(ret)

        if not returns:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        arr = np.array(returns)
        wins = arr[arr > 0]
        losses = arr[arr < 0]
        win_rate = len(wins) / len(arr) if len(arr) > 0 else 0.0
        profit_factor = (
            abs(np.mean(wins) / np.mean(losses))
            if len(losses) > 0 and np.mean(losses) != 0
            else float("inf") if len(wins) > 0 else 0.0
        )

        return (
            float(np.mean(arr)),
            float(np.median(arr)),
            float(np.max(arr)),
            float(np.min(arr)),
            float(profit_factor),
            float(win_rate),
        )

    def _compute_composite_score(
        self,
        metrics: Dict[str, float],
        baseline_metrics: Dict[str, float],
    ) -> float:
        """计算综合评分

        score > 1.0 → 优于基线
        score ≤ 1.0 → 不优于基线
        """
        sharpe = metrics.get("sharpe_ratio", 0)
        calmar = metrics.get("calmar_ratio", 0)
        maxdd = metrics.get("max_drawdown_pct", 1)
        win_rate = metrics.get("win_rate_pct", 0)
        trade_count = metrics.get("total_trades", 1)

        b_sharpe = baseline_metrics.get("sharpe_ratio", 0)
        b_calmar = baseline_metrics.get("calmar_ratio", 0)
        b_maxdd = baseline_metrics.get("max_drawdown_pct", 1)
        b_winrate = baseline_metrics.get("win_rate_pct", 0)
        b_trade_count = baseline_metrics.get("total_trades", 1)

        # 交易频率评分
        freq_ratio = trade_count / b_trade_count if b_trade_count > 0 else 1.0
        if freq_ratio < 0.8:
            freq_score = 0.8
        elif freq_ratio <= 1.2:
            freq_score = 1.0
        elif freq_ratio <= 2.0:
            freq_score = 0.9
        else:
            freq_score = 0.5

        # 防止除零
        def safe_div(a, b):
            if b == 0:
                return 1.0 if a > 0 else 0.0
            return a / b

        score = (
            0.4 * safe_div(sharpe, b_sharpe)
            + 0.3 * safe_div(calmar, b_calmar)
            + 0.15 * (b_maxdd / maxdd if maxdd > 0 else 1.0)
            + 0.1 * safe_div(win_rate, b_winrate)
            + 0.05 * freq_score
        )
        return float(score)

    # ── 工具方法 ────────────────────────────────────────────────────

    def print_summary(self, result: ScenarioBacktestResult) -> None:
        """打印分场景回测摘要"""
        print("=" * 70)
        print(f"分场景回测结果: {result.experiment_name}")
        print("=" * 70)
        print(f"策略: {result.strategy_name} | 标的: {result.symbol}")
        print(f"区间: {result.start_date} ~ {result.end_date} ({result.total_days}天)")
        print()
        print("全周期综合指标:")
        print(f"  总收益率: {result.overall_total_return:.2%}")
        print(f"  夏普比率: {result.overall_sharpe:.3f} (基线: {result.baseline_sharpe:.3f})")
        print(f"  卡玛比率: {result.overall_calmar:.3f} (基线: {result.baseline_calmar:.3f})")
        print(f"  最大回撤: {result.overall_max_drawdown:.2%} (基线: {result.baseline_maxdd:.2%})")
        print(f"  交易次数: {result.overall_trade_count}")
        print(f"  综合评分: {result.composite_score:.3f} {'✅ 优于基线' if result.composite_score > 1.0 else '❌ 未优于基线'}")
        print()
        print("各目的表现:")
        for obj, m in result.objective_metrics.items():
            print(f"\n  [{obj}] {m.objective_name}:")
            print(f"    信号数: {m.total_signals} (频率: {m.signal_freq_pct:.2f}%)")
            print(f"    胜率: {m.win_rate:.2%} | 平均收益: {m.avg_return:.2%}")
            print(f"    盈亏比: {m.profit_factor:.2f}")
            print(f"    标签Precision: {m.label_precision:.3f} | Recall: {m.label_recall:.3f} | F1: {m.label_f1:.3f}")
        print()
        print("=" * 70)

    def save_result(self, result: ScenarioBacktestResult) -> str:
        """保存结果到文件，返回文件路径"""
        filename = f"{result.experiment_name}.json"
        filepath = self.result_dir / filename
        result.save(str(filepath))
        return str(filepath)


# ── 便捷函数 ──────────────────────────────────────────────────────────

def run_v2_baseline_scenarios(
    prices: pd.DataFrame,
    symbol: str = "BTC",
) -> ScenarioBacktestResult:
    """运行v2基线策略的分场景回测

    Args:
        prices: OHLCV数据
        symbol: 标的名称

    Returns:
        分场景回测结果
    """
    engine = ScenarioBacktestEngine()
    strategy = EnhancedMA200Strategy()
    result = engine.run_scenario_backtest(
        prices, strategy, "EnhancedMA200_v2", symbol=symbol,
        experiment_name=f"v2_baseline_{symbol}",
    )
    return result


if __name__ == "__main__":
    # 简单测试：用模拟数据验证引擎能跑通
    print("测试分场景回测引擎...")

    # 生成模拟价格数据
    np.random.seed(42)
    n_days = 500
    dates = pd.date_range("2020-01-01", periods=n_days, freq="D")
    base_price = 100.0
    returns = np.random.normal(0.001, 0.03, n_days)
    prices_arr = base_price * np.cumprod(1 + returns)

    df = pd.DataFrame({
        "open": prices_arr * (1 + np.random.normal(0, 0.01, n_days)),
        "high": prices_arr * (1 + abs(np.random.normal(0, 0.02, n_days))),
        "low": prices_arr * (1 - abs(np.random.normal(0, 0.02, n_days))),
        "close": prices_arr,
        "volume": np.random.randint(1000, 10000, n_days),
    }, index=dates)

    engine = ScenarioBacktestEngine()
    strategy = EnhancedMA200Strategy()
    result = engine.run_scenario_backtest(
        df, strategy, "Test_v2", symbol="TEST",
    )

    engine.print_summary(result)
    print(f"\n结果保存: {engine.save_result(result)}")
