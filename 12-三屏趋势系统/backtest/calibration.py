"""三屏趋势系统 — 置信度校准分析工具

参考 scikit-learn CalibratedClassifierCV 的设计理念：
- ECE (Expected Calibration Error) 计算
- 可靠性图 (Reliability Diagram) 数据生成
- Platt Scaling 校准
- Isotonic Regression 校准

解决 A8 报告指出的"过度自信偏差"问题：
验证置信度是否准确反映实际概率。
"""

from typing import Dict, List, Optional, Tuple, Callable
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')


def calculate_ece(
    confidences: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> Dict:
    """
    计算预期校准误差 (Expected Calibration Error)

    ECE = Σ (|bin_count/total| × |avg_confidence - avg_accuracy|)

    参数:
        confidences: 置信度数组（0-100）
        outcomes: 实际结果数组（1=正确预测，0=错误预测）
        n_bins: 分箱数量

    返回:
        {
            "ece": float,           # 预期校准误差（0-100，越低越好）
            "mce": float,           # 最大校准误差
            "bin_data": List[Dict], # 各分箱数据
            "n_samples": int,
        }
    """
    confidences = np.array(confidences, dtype=float)
    outcomes = np.array(outcomes, dtype=float)

    confidences = np.clip(confidences, 0, 100) / 100.0

    bin_boundaries = np.linspace(0, 1, n_bins + 1)

    ece = 0.0
    mce = 0.0
    bin_data = []
    n_total = len(confidences)

    for i in range(n_bins):
        bin_lower = bin_boundaries[i]
        bin_upper = bin_boundaries[i + 1]

        if i == 0:
            in_bin = (confidences >= bin_lower) & (confidences <= bin_upper)
        else:
            in_bin = (confidences > bin_lower) & (confidences <= bin_upper)

        n_in_bin = in_bin.sum()

        if n_in_bin > 0:
            avg_conf = confidences[in_bin].mean()
            avg_acc = outcomes[in_bin].mean()
            gap = abs(avg_acc - avg_conf)

            weight = n_in_bin / n_total
            ece += weight * gap
            mce = max(mce, gap)

            bin_data.append({
                "bin_idx": i,
                "bin_lower_pct": round(bin_lower * 100, 1),
                "bin_upper_pct": round(bin_upper * 100, 1),
                "n_samples": int(n_in_bin),
                "avg_confidence_pct": round(avg_conf * 100, 1),
                "avg_accuracy_pct": round(avg_acc * 100, 1),
                "gap_pct": round(gap * 100, 1),
            })
        else:
            bin_data.append({
                "bin_idx": i,
                "bin_lower_pct": round(bin_lower * 100, 1),
                "bin_upper_pct": round(bin_upper * 100, 1),
                "n_samples": 0,
                "avg_confidence_pct": 0,
                "avg_accuracy_pct": 0,
                "gap_pct": 0,
            })

    return {
        "ece": round(ece * 100, 2),
        "mce": round(mce * 100, 2),
        "bin_data": bin_data,
        "n_samples": n_total,
        "n_bins": n_bins,
    }


def platt_scaling(
    confidences: np.ndarray,
    outcomes: np.ndarray,
) -> Tuple[Callable, Dict]:
    """
    Platt Scaling 校准：用 sigmoid 函数拟合校准曲线

    校准后置信度 = sigmoid(A × 原始置信度 + B)

    参数:
        confidences: 原始置信度（0-100）
        outcomes: 实际结果（0或1）

    返回:
        (calibrate_func, params)
        calibrate_func: 校准函数，输入原始置信度，返回校准后置信度
        params: {"A": float, "B": float, "fitted": bool}
    """
    from scipy.optimize import minimize

    confidences = np.array(confidences, dtype=float) / 100.0
    outcomes = np.array(outcomes, dtype=float)

    def neg_log_likelihood(params):
        A, B = params
        logits = A * confidences + B
        probs = 1 / (1 + np.exp(-logits))
        probs = np.clip(probs, 1e-10, 1 - 1e-10)
        return -np.mean(outcomes * np.log(probs) + (1 - outcomes) * np.log(1 - probs))

    result = minimize(neg_log_likelihood, x0=[1.0, 0.0], method='Nelder-Mead')

    A, B = result.x

    def calibrate(confidence):
        c = np.clip(confidence, 0, 100) / 100.0
        logit = A * c + B
        prob = 1 / (1 + np.exp(-logit))
        return prob * 100.0

    return calibrate, {
        "A": round(float(A), 4),
        "B": round(float(B), 4),
        "method": "platt_scaling",
        "fitted": result.success,
    }


def isotonic_calibration(
    confidences: np.ndarray,
    outcomes: np.ndarray,
) -> Tuple[Callable, Dict]:
    """
    Isotonic Regression 校准：非参数保序回归

    不假设分布形状，更灵活但需要更多数据。

    参数:
        confidences: 原始置信度（0-100）
        outcomes: 实际结果（0或1）

    返回:
        (calibrate_func, params)
    """
    from sklearn.isotonic import IsotonicRegression

    confidences = np.array(confidences, dtype=float)
    outcomes = np.array(outcomes, dtype=float)

    iso = IsotonicRegression(out_of_bounds='clip', y_min=0, y_max=1)
    iso.fit(confidences, outcomes)

    def calibrate(confidence):
        c = np.atleast_1d(np.clip(confidence, 0, 100))
        return iso.predict(c) * 100.0

    return calibrate, {
        "method": "isotonic_regression",
        "n_training_samples": len(confidences),
        "fitted": True,
    }


def cross_validated_calibration(
    confidences: np.ndarray,
    outcomes: np.ndarray,
    method: str = "platt",
    cv: int = 5,
) -> Dict:
    """
    交叉验证校准，避免过拟合

    参考 scikit-learn CalibratedClassifierCV 的做法：
    将数据分为 cv 折，每折在其余折上训练校准器，在自己折上预测

    参数:
        confidences: 原始置信度（0-100）
        outcomes: 实际结果（0或1）
        method: "platt" 或 "isotonic"
        cv: 交叉验证折数

    返回:
        {
            "calibrated_confidences": np.ndarray,  # 校准后置信度
            "original_ece": float,
            "calibrated_ece": float,
            "improvement": float,
            "method": str,
        }
    """
    confidences = np.array(confidences, dtype=float)
    outcomes = np.array(outcomes, dtype=float)
    n = len(confidences)

    if n < cv * 10:
        cv = max(2, n // 10)

    indices = np.arange(n)
    np.random.shuffle(indices)
    fold_sizes = np.full(cv, n // cv, dtype=int)
    fold_sizes[:n % cv] += 1

    calibrated = np.zeros(n)

    current = 0
    for fold_size in fold_sizes:
        test_idx = indices[current:current + fold_size]
        train_idx = np.concatenate([indices[:current], indices[current + fold_size:]])
        current += fold_size

        train_conf = confidences[train_idx]
        train_out = outcomes[train_idx]

        if method == "platt":
            calibrate_func, _ = platt_scaling(train_conf, train_out)
        else:
            calibrate_func, _ = isotonic_calibration(train_conf, train_out)

        calibrated[test_idx] = calibrate_func(confidences[test_idx])

    original_ece = calculate_ece(confidences, outcomes)["ece"]
    calibrated_ece = calculate_ece(calibrated, outcomes)["ece"]
    improvement = original_ece - calibrated_ece

    return {
        "calibrated_confidences": calibrated,
        "original_ece": original_ece,
        "calibrated_ece": calibrated_ece,
        "improvement": round(improvement, 2),
        "improvement_pct": round(improvement / original_ece * 100, 1) if original_ece > 0 else 0,
        "method": method,
        "cv": cv,
    }


def collect_calibration_data(
    prices: pd.DataFrame,
    strategy,
    lookahead: int = 7,
    engine=None,
) -> Dict:
    """
    从回测中收集置信度校准数据

    对每个时间点：
    - 记录策略的置信度
    - 记录未来 lookahead 天的实际涨跌方向
    - 判断策略方向是否正确

    参数:
        prices: OHLCV DataFrame
        strategy: 三屏策略对象
        lookahead: 预测前瞻天数
        engine: 回测引擎

    返回:
        {
            "confidences": np.ndarray,  # 置信度数组
            "outcomes": np.ndarray,     # 正确/错误数组
            "directions": List[str],    # 方向列表
            "n_samples": int,
        }
    """
    df = prices.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")

    n = len(df)
    close = df["close"]

    future_returns = close.shift(-lookahead) / close - 1
    future_direction = (future_returns > 0).astype(int)

    signals = strategy.generate_signals(df)

    confidences = []
    outcomes = []
    directions = []

    warmup = getattr(strategy, 'warmup_periods', 200) if hasattr(strategy, 'warmup_periods') else 200

    for i in range(warmup, n - lookahead):
        pos = signals.iloc[i]

        if abs(pos) < 0.01:
            continue

        confidence = abs(pos) * 100
        strategy_bullish = pos > 0

        actual_bullish = future_direction.iloc[i]

        if pd.isna(actual_bullish):
            continue

        is_correct = 1 if (strategy_bullish == bool(actual_bullish)) else 0

        confidences.append(confidence)
        outcomes.append(is_correct)
        directions.append("BULL" if strategy_bullish else "BEAR")

    return {
        "confidences": np.array(confidences),
        "outcomes": np.array(outcomes),
        "directions": directions,
        "n_samples": len(confidences),
        "lookahead": lookahead,
    }


def format_calibration_report(ece_result: Dict, cv_result: Optional[Dict] = None) -> str:
    """格式化置信度校准报告"""
    lines = [
        "=" * 70,
        "  置信度校准分析报告",
        "=" * 70,
        "",
        "【校准误差】",
        f"  样本数:           {ece_result['n_samples']}",
        f"  ECE (预期校准误差): {ece_result['ece']:>6.2f}%",
        f"  MCE (最大校准误差): {ece_result['mce']:>6.2f}%",
        "",
    ]

    if ece_result["ece"] < 3:
        lines.append("  ✅ 校准优秀（ECE<3%）：置信度准确反映实际概率")
    elif ece_result["ece"] < 5:
        lines.append("  ⚠️ 校准良好（ECE<5%）：置信度基本可靠")
    elif ece_result["ece"] < 10:
        lines.append("  ⚠️ 校准一般（ECE<10%）：存在一定偏差，建议校准")
    else:
        lines.append("  ❌ 校准较差（ECE≥10%）：过度自信偏差严重，必须校准")

    lines.extend(["", "【可靠性图数据】", f"{'区间(%)':>12} {'样本数':>6} {'平均置信':>8} {'实际准确':>8} {'偏差':>6}", "-" * 50])

    for b in ece_result["bin_data"]:
        if b["n_samples"] > 0:
            lines.append(
                f"{b['bin_lower_pct']:>5.1f}~{b['bin_upper_pct']:>5.1f} "
                f"{b['n_samples']:>6d} "
                f"{b['avg_confidence_pct']:>7.1f}% "
                f"{b['avg_accuracy_pct']:>7.1f}% "
                f"{b['gap_pct']:>5.1f}%"
            )

    if cv_result:
        lines.extend([
            "-" * 50,
            "",
            f"【{cv_result['method']} 交叉验证校准结果】",
            f"  校准前 ECE:  {cv_result['original_ece']:>6.2f}%",
            f"  校准后 ECE:  {cv_result['calibrated_ece']:>6.2f}%",
            f"  改善幅度:    {cv_result['improvement']:>6.2f}% ({cv_result['improvement_pct']:.1f}%)",
            f"  交叉验证折数: {cv_result['cv']}",
            "",
        ])

        if cv_result["calibrated_ece"] < 3:
            lines.append("  ✅ 校准后达到优秀水平")
        elif cv_result["calibrated_ece"] < 5:
            lines.append("  ⚠️ 校准后达到良好水平")
        else:
            lines.append("  ⚠️ 校准后仍有偏差，可能需要更多数据或尝试其他方法")

    lines.append("=" * 70)
    return "\n".join(lines)
