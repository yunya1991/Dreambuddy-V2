"""
统一统计工具库 — 基本面分析的统计学基础设施

提供:
    - z-score 标准化（带限幅）
    - 分位数计算
    - tanh/sigmoid 归一化
    - Sharpe / Sortino / Max Drawdown / Profit Factor 统一计算
    - 贝叶斯置信度更新
    - 滚动窗口统计
    - 信号冲突检测

设计原则:
    - 所有函数无副作用，纯计算
    - 缺失数据安全返回中性值，不抛异常
    - 样本不足时返回保守估计
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple, Sequence
from dataclasses import dataclass, field


# ============================================================
# 基础统计
# ============================================================

def mean(data: Sequence[float]) -> float:
    """算术平均，空序列返回 0"""
    if not data:
        return 0.0
    return sum(data) / len(data)


def stdev(data: Sequence[float], ddof: int = 1) -> float:
    """标准差

    Args:
        ddof: 自由度修正。1=样本标准差(n-1), 0=总体标准差(n)
    """
    n = len(data)
    if n <= ddof:
        return 0.0
    m = mean(data)
    var = sum((x - m) ** 2 for x in data) / (n - ddof)
    return math.sqrt(var)


def z_score(value: float, mu: float, sigma: float, clip: float = 3.0) -> float:
    """Z-score 标准化，限幅到 [-clip, clip]

    sigma=0 时返回 0（无法标准化）
    """
    if sigma == 0:
        return 0.0
    z = (value - mu) / sigma
    return max(-clip, min(clip, z))


def percentile(data: Sequence[float], p: float) -> float:
    """计算第 p 百分位（p ∈ [0, 100]）

    使用线性插值法（与 numpy.percentile 默认一致）
    """
    if not data:
        return 0.0
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    k = (p / 100) * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_data[lo]
    frac = k - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def percentile_rank(data: Sequence[float], value: float) -> float:
    """计算 value 在 data 中的百分位排名（0-100）

    返回值表示 value 大于 data 中多少比例的数据
    """
    if not data:
        return 50.0  # 中性
    below = sum(1 for x in data if x < value)
    equal = sum(1 for x in data if x == value)
    n = len(data)
    # 平均秩（与 scipy.stats.percentileofscore 一致）
    return (below + 0.5 * equal) / n * 100


def normalize_tanh(value: float, scale: float = 1.0) -> float:
    """tanh 归一化到 [-1, 1]

    scale 越大，非线性越强（中间区域更敏感）
    """
    return math.tanh(value / scale) if scale > 0 else 0.0


def normalize_sigmoid(value: float, scale: float = 1.0) -> float:
    """sigmoid 归一化到 [0, 1]"""
    if scale <= 0:
        return 0.5
    return 1.0 / (1.0 + math.exp(-value / scale))


def normalize_linear(value: float, lo: float, hi: float) -> float:
    """线性归一化到 [0, 1]

    值 < lo → 0, 值 > hi → 1
    """
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def normalize_signed(value: float, lo: float, hi: float) -> float:
    """线性归一化到 [-1, 1]

    中心点 = (lo + hi) / 2
    """
    if hi == lo:
        return 0.0
    center = (lo + hi) / 2
    half_range = (hi - lo) / 2
    return max(-1.0, min(1.0, (value - center) / half_range))


# ============================================================
# 滚动窗口统计
# ============================================================

class RollingStats:
    """滚动窗口统计器

    维护固定长度的历史数据，支持增量计算 z-score / 分位数。

    用法:
        rs = RollingStats(window=100)
        rs.push(0.5)
        z = rs.z_score(0.6)  # 当前值相对历史的 z-score
        pct = rs.percentile_rank(0.6)
    """

    def __init__(self, window: int = 100, min_samples: int = 10):
        self.window = window
        self.min_samples = min_samples
        self._data: List[float] = []

    def push(self, value: float) -> None:
        """添加新数据点"""
        self._data.append(value)
        if len(self._data) > self.window:
            self._data = self._data[-self.window:]

    def push_batch(self, values: Sequence[float]) -> None:
        """批量添加"""
        self._data.extend(values)
        if len(self._data) > self.window:
            self._data = self._data[-self.window:]

    @property
    def count(self) -> int:
        return len(self._data)

    @property
    def is_ready(self) -> bool:
        return self.count >= self.min_samples

    def mean(self) -> float:
        return mean(self._data) if self._data else 0.0

    def stdev(self) -> float:
        return stdev(self._data, ddof=1) if len(self._data) > 1 else 0.0

    def z_score(self, value: float, clip: float = 3.0) -> float:
        """当前值相对历史分布的 z-score"""
        if not self.is_ready:
            return 0.0
        return z_score(value, self.mean(), self.stdev(), clip)

    def percentile_rank(self, value: float) -> float:
        """当前值在历史分布中的百分位（0-100）"""
        if not self.is_ready:
            return 50.0
        return percentile_rank(self._data, value)

    def percentile(self, p: float) -> float:
        """历史分布的第 p 百分位值"""
        if not self._data:
            return 0.0
        return percentile(self._data, p)

    def is_extreme_high(self, value: float, threshold: float = 95.0) -> bool:
        """值是否处于历史分布高位（默认 >95 百分位）"""
        return self.percentile_rank(value) > threshold

    def is_extreme_low(self, value: float, threshold: float = 5.0) -> bool:
        """值是否处于历史分布低位（默认 <5 百分位）"""
        return self.percentile_rank(value) < threshold


# ============================================================
# 回测指标统一计算
# ============================================================

@dataclass
class BacktestMetrics:
    """统一回测指标"""

    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    calmar_ratio: float = 0.0  # 年化收益 / 最大回撤

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


def calculate_metrics(
    trades: Sequence[float],
    periods_per_year: int = 365,
    risk_free_rate: float = 0.0,
) -> BacktestMetrics:
    """统一计算回测指标

    Args:
        trades: 每笔交易的收益率序列（如 [0.02, -0.01, 0.03, ...]）
        periods_per_year: 年化因子（日线=365, 4h=2190, 1h=8760）
        risk_free_rate: 无风险利率（年化）

    Returns:
        BacktestMetrics 统一指标
    """
    metrics = BacktestMetrics()
    n = len(trades)
    metrics.total_trades = n
    if n == 0:
        return metrics

    # 基本统计
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    metrics.win_rate = len(wins) / n if n > 0 else 0.0
    metrics.avg_win = mean(wins) if wins else 0.0
    metrics.avg_loss = mean(losses) if losses else 0.0

    # 总收益
    metrics.total_return = sum(trades)

    # 年化收益
    if periods_per_year > 0 and metrics.total_return > -1:
        per_period_return = metrics.total_return / n
        try:
            metrics.annualized_return = (1 + per_period_return) ** periods_per_year - 1
        except OverflowError:
            metrics.annualized_return = 0.0

    # Profit Factor
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0.0

    # 期望值
    metrics.expectancy = metrics.win_rate * metrics.avg_win + (1 - metrics.win_rate) * metrics.avg_loss

    # Sharpe Ratio（样本标准差，年化）
    sigma = stdev(trades, ddof=1)
    avg_return = mean(trades)
    rf_per_period = risk_free_rate / periods_per_year
    excess_return = avg_return - rf_per_period
    if sigma > 0:
        metrics.sharpe_ratio = (excess_return / sigma) * math.sqrt(periods_per_year)
    else:
        metrics.sharpe_ratio = 0.0

    # Sortino Ratio（仅用下行标准差）
    downside_returns = [min(0, t) for t in trades]
    downside_sigma = stdev([t for t in downside_returns if t < 0], ddof=1) if len([t for t in downside_returns if t < 0]) > 1 else 0.0
    if downside_sigma > 0:
        metrics.sortino_ratio = (excess_return / downside_sigma) * math.sqrt(periods_per_year)
    else:
        metrics.sortino_ratio = 0.0

    # Max Drawdown
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    dd_start = 0
    dd_duration = 0
    max_dd_duration = 0
    for i, t in enumerate(trades):
        equity += t
        if equity > peak:
            peak = equity
            dd_start = i
            dd_duration = 0
        else:
            dd_duration += 1
            if dd_duration > max_dd_duration:
                max_dd_duration = dd_duration
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
    metrics.max_drawdown = max_dd
    metrics.max_drawdown_duration = max_dd_duration

    # Calmar Ratio
    if metrics.max_drawdown > 0:
        metrics.calmar_ratio = metrics.annualized_return / metrics.max_drawdown
    else:
        metrics.calmar_ratio = 0.0

    return metrics


# ============================================================
# 贝叶斯置信度更新
# ============================================================

def bayesian_update(
    prior_alpha: float,
    prior_beta: float,
    successes: int,
    failures: int,
) -> Tuple[float, float]:
    """贝叶斯置信度更新（Beta 分布共轭先验）

    Args:
        prior_alpha: 先验 Beta 分布 alpha 参数
        prior_beta: 先验 Beta 分布 beta 参数
        successes: 观测到的成功次数
        failures: 观测到的失败次数

    Returns:
        (posterior_alpha, posterior_beta)
    """
    return (prior_alpha + successes, prior_beta + failures)


def bayesian_mean(alpha: float, beta: float) -> float:
    """Beta 分布的期望值"""
    total = alpha + beta
    if total == 0:
        return 0.5
    return alpha / total


def bayesian_confidence(alpha: float, beta: float, min_samples: int = 10) -> float:
    """贝叶斯置信度（考虑样本量）

    返回 [0, 1] 的置信度，样本不足时返回保守值
    """
    total = alpha + beta
    if total < min_samples:
        # 样本不足，线性增长
        return total / (2 * min_samples)
    # 样本充足，使用 Beta 分布期望
    base_conf = bayesian_mean(alpha, beta)
    # 方差越小置信度越高
    variance = (alpha * beta) / ((alpha + beta) ** 2 * (alpha + beta + 1))
    # 方差→0 时置信度→1，方差→0.25(均匀分布) 时置信度→0.5
    precision = 1.0 - 4.0 * variance  # [0, 1]
    return base_conf * max(0.3, precision)


# ============================================================
# 信号冲突检测
# ============================================================

@dataclass
class SignalStats:
    """单节点信号统计"""

    direction: str = "HOLD"
    confidence: float = 0.3
    score: float = 0.0
    long_score: float = 0.0
    short_score: float = 0.0
    hold_score: float = 0.0
    active_signals: int = 0
    total_signals: int = 0
    z_score: float = 0.0  # 综合得分的 z-score（相对历史）
    percentile: float = 50.0  # 综合得分的百分位
    rationale: List[str] = field(default_factory=list)


def aggregate_signals(
    scores: List[Tuple[str, float, str]],
    history: Optional[RollingStats] = None,
) -> SignalStats:
    """聚合信号列表，生成统计化的信号统计

    Args:
        scores: [(direction, weight, reason), ...]
        history: 可选的历史分布，用于 z-score / 分位数计算

    Returns:
        SignalStats 包含方向、置信度、z-score 等
    """
    stats = SignalStats()
    stats.total_signals = len(scores)

    long_score = sum(w for d, w, _ in scores if d == "LONG")
    short_score = sum(w for d, w, _ in scores if d == "SHORT")
    hold_score = sum(w for d, w, _ in scores if d == "HOLD")
    total = long_score + short_score + hold_score

    stats.long_score = long_score
    stats.short_score = short_score
    stats.hold_score = hold_score
    stats.score = long_score - short_score
    stats.active_signals = sum(1 for d, _, _ in scores if d != "HOLD")

    if total == 0:
        stats.direction = "HOLD"
        stats.confidence = 0.3
    elif hold_score > long_score and hold_score > short_score:
        stats.direction = "HOLD"
        stats.confidence = hold_score / total
    elif long_score > short_score:
        stats.direction = "LONG"
        stats.confidence = long_score / total
    else:
        stats.direction = "SHORT"
        stats.confidence = short_score / total

    # 如果有历史分布，计算 z-score 和百分位
    if history and history.is_ready:
        stats.z_score = history.z_score(stats.score)
        stats.percentile = history.percentile_rank(stats.score)
        # 基于统计显著性调整置信度
        if abs(stats.z_score) > 1.5:
            stats.confidence = min(0.95, stats.confidence + 0.1)

    stats.rationale = [r for _, _, r in scores[:6]]
    return stats


def detect_conflict(
    signals_a: SignalStats,
    signals_b: SignalStats,
    threshold: float = 0.3,
) -> bool:
    """检测两个信号源是否冲突

    冲突条件: 方向相反 且 得分差值 > threshold
    """
    if signals_a.direction == signals_b.direction:
        return False
    if signals_a.direction == "HOLD" or signals_b.direction == "HOLD":
        return False
    return abs(signals_a.score - signals_b.score) > threshold


# ============================================================
# 经典平滑与滤波算法
# ============================================================

def ewma_update(prev_ewma: float, new_value: float, alpha: float = 0.3) -> float:
    """EWMA 指数加权移动平均 — 增量更新

    new_ewma = alpha * new_value + (1 - alpha) * prev_ewma

    Args:
        prev_ewma: 上一期 EWMA 值
        new_value: 当前新观测值
        alpha: 平滑系数，越大越响应新数据（0.1=强平滑, 0.5=中等, 0.9=弱平滑）

    Returns:
        更新后的 EWMA 值
    """
    alpha = max(0.0, min(1.0, alpha))
    return alpha * new_value + (1.0 - alpha) * prev_ewma


def ewma_series(values: Sequence[float], alpha: float = 0.3) -> List[float]:
    """EWMA 指数加权移动平均 — 序列计算

    对完整序列计算 EWMA，适合回测场景。

    Args:
        values: 输入序列
        alpha: 平滑系数

    Returns:
        与输入等长的 EWMA 序列
    """
    if not values:
        return []
    result = [float(values[0])]
    for v in values[1:]:
        result.append(ewma_update(result[-1], float(v), alpha))
    return result


def holt_linear_update(
    prev_level: float,
    prev_trend: float,
    new_value: float,
    alpha: float = 0.3,
    beta: float = 0.1,
) -> Tuple[float, float]:
    """Holt 双指数平滑 — 增量更新（带趋势）

    适合处理有趋势的信号序列，分离 level 和 trend。

    Args:
        prev_level: 上一期 level
        prev_trend: 上一期 trend
        new_value: 当前新观测值
        alpha: level 平滑系数
        beta: trend 平滑系数

    Returns:
        (new_level, new_trend)
    """
    alpha = max(0.0, min(1.0, alpha))
    beta = max(0.0, min(1.0, beta))
    new_level = alpha * new_value + (1 - alpha) * (prev_level + prev_trend)
    new_trend = beta * (new_level - prev_level) + (1 - beta) * prev_trend
    return new_level, new_trend


def median(values: Sequence[float]) -> float:
    """中位数"""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]


def median_absolute_deviation(values: Sequence[float]) -> float:
    """MAD 中位数绝对偏差

    鲁棒离散度度量，对异常值不敏感。
    MAD = median(|x_i - median(x)|)

    Returns:
        MAD 值（0 表示无离散度）
    """
    if not values:
        return 0.0
    med = median(values)
    deviations = [abs(x - med) for x in values]
    return median(deviations)


def mad_outlier_score(value: float, history: Sequence[float]) -> float:
    """基于 MAD 的异常值评分

    返回 [0, 1] 的异常分数：
        - 0 = 完全正常
        - 1 = 极端异常

    使用 1.4826 将 MAD 转换为正态分布等效标准差。

    Args:
        value: 待检测的值
        history: 历史参考序列（至少 5 个样本）

    Returns:
        异常分数 [0, 1]
    """
    if len(history) < 5:
        return 0.0
    med = median(history)
    mad = median_absolute_deviation(history)
    if mad == 0:
        return 0.0
    # 转换为正态等效 z-score
    sigma_eq = 1.4826 * mad
    z = abs(value - med) / sigma_eq
    # z > 3.5 视为极端异常
    return min(1.0, max(0.0, (z - 1.5) / 2.0))


def robust_clip(value: float, history: Sequence[float], z_limit: float = 3.5) -> float:
    """鲁棒限幅 — 基于 MAD 的异常值裁剪

    将超出 z_limit 倍 MAD 等效标准差的值裁剪到边界，
    避免极端噪声污染信号。

    Args:
        value: 待处理值
        history: 历史参考序列
        z_limit: 等效 z-score 限幅阈值（默认 3.5σ）

    Returns:
        裁剪后的值
    """
    if len(history) < 5:
        return value
    med = median(history)
    mad = median_absolute_deviation(history)
    if mad == 0:
        return value
    sigma_eq = 1.4826 * mad
    bound = z_limit * sigma_eq
    return max(med - bound, min(med + bound, value))


def savitzky_golay_simplify(values: Sequence[float], window: int = 5) -> float:
    """Savitzky-Golay 简化版 — 最近 window 个点的线性回归斜率

    保留趋势特征同时平滑噪声，返回最新点的平滑值。
    比简单移动平均更能保留信号边缘。

    Args:
        values: 输入序列
        window: 回归窗口大小

    Returns:
        最新点的平滑值
    """
    if not values:
        return 0.0
    w = min(window, len(values))
    recent = [float(v) for v in values[-w:]]
    if w == 1:
        return recent[0]
    # 简单线性回归: y = a + b*x
    n = w
    x_mean = (n - 1) / 2
    y_mean = sum(recent) / n
    numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return y_mean
    slope = numerator / denominator
    # 预测最新点（已平滑）
    return y_mean + slope * (n - 1 - x_mean)


class ExponentialSmoother:
    """有状态的指数平滑器

    维护单个指标的 EWMA 状态，支持增量更新。

    用法:
        es = ExponentialSmoother(alpha=0.3)
        es.update(0.5)
        smoothed = es.value  # 当前平滑值
    """

    def __init__(self, alpha: float = 0.3, initial: Optional[float] = None):
        self.alpha = alpha
        self._value: Optional[float] = initial
        self._count: int = 0
        self._history: List[float] = []

    def update(self, value: float) -> float:
        """更新平滑值，返回当前平滑结果"""
        self._history.append(value)
        if len(self._history) > 100:
            self._history = self._history[-100:]
        if self._value is None:
            self._value = float(value)
        else:
            self._value = ewma_update(self._value, float(value), self.alpha)
        self._count += 1
        return self._value

    @property
    def value(self) -> float:
        return self._value if self._value is not None else 0.0

    @property
    def is_ready(self) -> bool:
        return self._count >= 2

    @property
    def history(self) -> List[float]:
        return list(self._history)

    def reset(self) -> None:
        self._value = None
        self._count = 0
        self._history = []
