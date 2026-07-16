"""三屏趋势系统 — 过拟合检测工具包

包含：
1. 参数敏感性分析（Parameter Sensitivity Analysis）
2. 置换检验（Permutation Test）
3. 交易成本敏感性测试

参考业界量化研究的过拟合防护最佳实践。
"""

from typing import Dict, List, Optional, Callable, Any
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 1. 参数敏感性分析
# ============================================================

def parameter_sensitivity_analysis(
    prices: pd.DataFrame,
    strategy_factory: Callable,
    param_name: str,
    param_values: List,
    engine=None,
    metric: str = "sharpe_ratio",
) -> Dict:
    """
    参数敏感性分析：变动单个参数，观察策略表现变化

    经验法则：
    - 参数微调10%，收益变化>50% → 高度敏感，过拟合风险高
    - 参数变动较大，收益相对稳定 → 策略稳健

    参数:
        prices: OHLCV DataFrame
        strategy_factory: 创建策略的函数，签名 factory(**kwargs) -> strategy
        param_name: 要分析的参数名
        param_values: 参数值列表
        engine: 回测引擎
        metric: 评估指标（默认 sharpe_ratio）

    返回:
        {
            "param_name": str,
            "results": List[Dict],   # 每个参数值的结果
            "sensitivity_score": float,  # 敏感性评分(0-100，越低越好)
            "is_robust": bool,           # 是否稳健
            "best_value": Any,           # 最佳参数值
            "worst_value": Any,          # 最差参数值
        }
    """
    if engine is None:
        from .engine import BacktestEngine
        engine = BacktestEngine()

    df = _ensure_index(prices)
    close = df["close"]

    results = []
    for val in param_values:
        try:
            strategy = _call_strategy_factory(strategy_factory, param_name, val)
            signals = strategy.generate_signals(df)
            result = engine.run(close, signals, symbol=f"{param_name}={val}")
            metric_val = result["metrics"].get(metric, 0)

            results.append({
                "param_value": val,
                "metric_value": metric_val,
                "total_return": result["metrics"].get("total_return_pct", 0),
                "sharpe": result["metrics"].get("sharpe_ratio", 0),
                "max_dd": result["metrics"].get("max_drawdown_pct", 0),
                "trades": result["metrics"].get("total_trades", 0),
            })
        except Exception as e:
            results.append({
                "param_value": val,
                "metric_value": 0,
                "error": str(e)[:80],
            })

    metric_vals = [r["metric_value"] for r in results if "error" not in r]
    if len(metric_vals) < 2:
        return {"param_name": param_name, "results": results, "sensitivity_score": 100, "is_robust": False}

    mean_val = np.mean(metric_vals)
    std_val = np.std(metric_vals)
    cv = std_val / abs(mean_val) if abs(mean_val) > 0.001 else float("inf")

    sensitivity_score = min(cv * 50, 100)

    best_idx = np.argmax(metric_vals)
    worst_idx = np.argmin(metric_vals)

    is_robust = sensitivity_score < 30 and cv < 0.5

    return {
        "param_name": param_name,
        "results": results,
        "metric_mean": round(mean_val, 2),
        "metric_std": round(std_val, 2),
        "cv": round(cv, 3),
        "sensitivity_score": round(sensitivity_score, 1),
        "is_robust": is_robust,
        "best_value": results[best_idx]["param_value"] if "error" not in results[best_idx] else None,
        "worst_value": results[worst_idx]["param_value"] if "error" not in results[worst_idx] else None,
        "best_metric": round(max(metric_vals), 2),
        "worst_metric": round(min(metric_vals), 2),
    }


def format_sensitivity_report(result: Dict) -> str:
    """格式化参数敏感性报告"""
    lines = [
        "=" * 70,
        f"  参数敏感性分析 — {result['param_name']}",
        "=" * 70,
        "",
        f"  评估指标均值:   {result.get('metric_mean', 0):>8.2f}",
        f"  评估指标标准差: {result.get('metric_std', 0):>8.2f}",
        f"  变异系数 (CV):  {result.get('cv', 0):>8.3f}",
        f"  敏感性评分:     {result.get('sensitivity_score', 0):>7.1f}/100",
        f"  最佳参数值:     {result.get('best_value', '?')} (指标={result.get('best_metric', 0):.2f})",
        f"  最差参数值:     {result.get('worst_value', '?')} (指标={result.get('worst_metric', 0):.2f})",
        "",
    ]

    if result.get("is_robust"):
        lines.append("  ✅ 参数稳健：敏感性低，过拟合风险小")
    else:
        lines.append("  ⚠️ 参数敏感：参数微调可能导致表现大幅变化，过拟合风险高")

    lines.extend(["", "【各参数值详情】", f"{'参数值':>10} {'夏普':>8} {'收益%':>8} {'回撤%':>8} {'交易数':>6}", "-" * 50])

    for r in result["results"]:
        if "error" not in r:
            lines.append(
                f"{str(r['param_value']):>10} "
                f"{r.get('sharpe', 0):>8.2f} "
                f"{r.get('total_return', 0):>7.1f}% "
                f"{r.get('max_dd', 0):>7.1f}% "
                f"{r.get('trades', 0):>6d}"
            )

    lines.append("=" * 70)
    return "\n".join(lines)


# ============================================================
# 2. 置换检验（Permutation Test）
# ============================================================

def permutation_test(
    prices: pd.DataFrame,
    strategy,
    engine=None,
    n_permutations: int = 1000,
    metric: str = "sharpe_ratio",
    seed: int = 42,
) -> Dict:
    """
    置换检验：打乱信号时间序列，检验策略是否显著优于随机

    原假设 H0: 策略信号与价格走势无关（信号是随机的）
    备择假设 H1: 策略信号有真实预测能力

    方法：保持价格不变，随机打乱信号序列，重新回测。
    如果策略真有预测力，其真实指标应显著优于打乱后的指标。

    参数:
        prices: OHLCV DataFrame
        strategy: 策略对象
        engine: 回测引擎
        n_permutations: 置换次数
        metric: 评估指标
        seed: 随机种子

    返回:
        {
            "actual_metric": float,       # 真实策略指标
            "p_value": float,             # p值
            "is_significant": bool,       # 是否统计显著
            "percentile": float,          # 策略在随机分布中的百分位
            "random_mean": float,         # 随机策略指标均值
            "random_std": float,          # 随机策略指标标准差
            "n_permutations": int,
        }
    """
    if engine is None:
        from .engine import BacktestEngine
        engine = BacktestEngine()

    np.random.seed(seed)
    df = _ensure_index(prices)
    close = df["close"]

    actual_signals = strategy.generate_signals(df)
    actual_result = engine.run(close, actual_signals, symbol="actual")
    actual_metric = actual_result["metrics"].get(metric, 0)

    if (actual_signals.abs() < 0.01).all():
        return {"error": "策略未产生任何有效信号", "actual_metric": 0, "p_value": 1.0}

    signal_values = actual_signals.values.copy()
    n_signals = len(signal_values)

    permuted_metrics = []
    for i in range(n_permutations):
        shuffled = np.random.permutation(signal_values)
        permuted_signals = pd.Series(shuffled, index=actual_signals.index)

        result = engine.run(close, permuted_signals, symbol=f"perm_{i}")
        permuted_metrics.append(result["metrics"].get(metric, 0))

    permuted_metrics = np.array(permuted_metrics)
    p_value = np.mean(permuted_metrics >= actual_metric)
    percentile = np.mean(permuted_metrics < actual_metric) * 100

    return {
        "actual_metric": round(actual_metric, 2),
        "p_value": round(p_value, 4),
        "is_significant": p_value < 0.05,
        "significance_level": "p<0.01 (极显著)" if p_value < 0.01 else
                              "p<0.05 (显著)" if p_value < 0.05 else
                              "p<0.10 (弱显著)" if p_value < 0.10 else
                              "不显著",
        "percentile": round(percentile, 1),
        "random_mean": round(np.mean(permuted_metrics), 2),
        "random_std": round(np.std(permuted_metrics), 2),
        "random_95th": round(np.percentile(permuted_metrics, 95), 2),
        "random_99th": round(np.percentile(permuted_metrics, 99), 2),
        "n_permutations": n_permutations,
    }


def format_permutation_report(result: Dict) -> str:
    """格式化置换检验报告"""
    if "error" in result:
        return f"❌ {result['error']}"

    lines = [
        "=" * 70,
        "  置换检验（Permutation Test）",
        "=" * 70,
        "",
        f"  置换次数:         {result['n_permutations']}",
        f"  策略实际夏普:     {result['actual_metric']:>8.2f}",
        f"  随机策略夏普均值: {result['random_mean']:>8.2f} ± {result['random_std']:.2f}",
        f"  随机95分位:       {result['random_95th']:>8.2f}",
        f"  随机99分位:       {result['random_99th']:>8.2f}",
        "",
        f"  p值:              {result['p_value']:>8.4f}",
        f"  显著性:           {result['significance_level']}",
        f"  百分位:           {result['percentile']:>7.1f}%",
        "",
    ]

    if result["is_significant"]:
        if result["p_value"] < 0.01:
            lines.append("  ✅ 策略极显著优于随机（p<0.01），有真实预测能力")
        else:
            lines.append("  ✅ 策略显著优于随机（p<0.05），可能有真实预测能力")
    else:
        lines.append("  ❌ 策略不显著优于随机，收益可能来自运气")

    lines.append("=" * 70)
    return "\n".join(lines)


# ============================================================
# 3. 交易成本敏感性测试
# ============================================================

def cost_sensitivity_test(
    prices: pd.DataFrame,
    strategy,
    cost_range: List[float] = None,
    engine=None,
) -> Dict:
    """
    交易成本敏感性测试

    如果策略只有在极低交易成本下才赚钱 → 很可能过拟合
    成本翻倍后收益下降不超过30% → 较稳健

    参数:
        prices: OHLCV DataFrame
        strategy: 策略对象
        cost_range: 交易成本列表（单边费率）
        engine: 回测引擎

    返回:
        {
            "results": List[Dict],
            "is_cost_robust": bool,
            "break_even_cost": float,  # 盈亏平衡成本
        }
    """
    if cost_range is None:
        cost_range = [0.0001, 0.0003, 0.0005, 0.001, 0.002, 0.005, 0.01]

    from .engine import BacktestEngine

    if engine is None:
        engine = BacktestEngine()

    df = _ensure_index(prices)
    close = df["close"]
    signals = strategy.generate_signals(df)

    results = []
    for cost in cost_range:
        eng = BacktestEngine(
            initial_capital=engine.initial_capital,
            commission=cost,
            slippage=cost,
        )
        result = eng.run(close, signals, symbol=f"cost={cost}")
        sharpe = result["metrics"].get("sharpe_ratio", 0)
        total_ret = result["metrics"].get("total_return_pct", 0)

        results.append({
            "cost_pct": round(cost * 100, 3),
            "sharpe": round(sharpe, 2),
            "total_return_pct": round(total_ret, 2),
            "max_dd_pct": round(result["metrics"].get("max_drawdown_pct", 0), 2),
            "profitable": total_ret > 0,
        })

    profitable_results = [r for r in results if r["profitable"]]
    base_result = results[0] if results else None
    if base_result and len(profitable_results) > 0:
        last_profitable = profitable_results[-1]
        break_even = last_profitable["cost_pct"]
    else:
        break_even = 0

    if base_result and base_result["total_return_pct"] > 0:
        double_cost_result = None
        for r in results:
            if r["cost_pct"] >= base_result["cost_pct"] * 2:
                double_cost_result = r
                break

        if double_cost_result:
            decay = (base_result["total_return_pct"] - double_cost_result["total_return_pct"]) / abs(base_result["total_return_pct"])
            is_robust = decay < 0.3
        else:
            is_robust = len(profitable_results) >= 4
    else:
        is_robust = False

    return {
        "results": results,
        "is_cost_robust": is_robust,
        "break_even_cost_pct": break_even,
    }


def format_cost_report(result: Dict) -> str:
    """格式化成本敏感性报告"""
    lines = [
        "=" * 70,
        "  交易成本敏感性测试",
        "=" * 70,
        "",
        f"  盈亏平衡成本: {result['break_even_cost_pct']:.3f}%",
        f"  成本稳健性:   {'✅ 稳健' if result['is_cost_robust'] else '❌ 不稳健'}",
        "",
        f"{'成本(%)':>8} {'夏普':>8} {'收益(%)':>8} {'回撤(%)':>8} {'盈利':>6}",
        "-" * 45,
    ]

    for r in result["results"]:
        profit_mark = "✅" if r["profitable"] else "❌"
        lines.append(
            f"{r['cost_pct']:>7.3f}% "
            f"{r['sharpe']:>8.2f} "
            f"{r['total_return_pct']:>7.1f}% "
            f"{r['max_dd_pct']:>7.1f}% "
            f"{profit_mark:>6}"
        )

    lines.extend(["-" * 45, "=" * 70])
    return "\n".join(lines)


# ============================================================
# 辅助函数
# ============================================================

def _ensure_index(df: pd.DataFrame) -> pd.DataFrame:
    """确保 DataFrame 有合适的索引"""
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
    return df


def _call_strategy_factory(factory: Callable, param_name: str, param_value: Any):
    """
    调用 strategy_factory，兼容位置参数和关键字参数两种调用方式

    先尝试关键字参数调用 factory(param_name=param_value)，
    失败则回退到位置参数调用 factory(param_value)。
    """
    import inspect

    try:
        sig = inspect.signature(factory)
        params = list(sig.parameters.keys())
        if params and params[0] == param_name:
            return factory(**{param_name: param_value})
        elif params and len(params) == 1:
            return factory(param_value)
        else:
            return factory(**{param_name: param_value})
    except (ValueError, TypeError):
        try:
            return factory(**{param_name: param_value})
        except TypeError:
            return factory(param_value)
