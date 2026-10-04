"""tests/capability_regression/conftest.py — 能力回归测试共享 fixture

D7: 借鉴 ds4-eval 嵌入式能力回归测试套件
目标: 用真实策略基因库 + 确定性 mock 市场数据，验证核心交易能力不退化

覆盖能力维度:
  1. 开仓信号准确率（entry_accuracy）
  2. 离场时机质量（exit_quality）
  3. 最大回撤控制（drawdown_control）
  4. Sharpe 比率（sharpe_regression）

硬约束: HC-DS4-08（能力回归测试不得修改实盘交易行为，纯只读验证）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 dreambuddy_evolution 包可导入
EVO_ROOT = Path(__file__).resolve().parents[2]  # tests/capability_regression → dreambuddy_evolution
REPO_ROOT = EVO_ROOT.parent  # dreambuddy_evolution → 23-四层闭环自进化交易架构
if str(EVO_ROOT) not in sys.path:
    sys.path.insert(0, str(EVO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ==============================================================================
# 1. 真实策略基因库 fixture（只读，不修改）
# ==============================================================================
@pytest.fixture(scope="session")
def real_gene_library():
    """加载真实策略基因库（只读，用于能力回归验证）.

    HC-DS4-08: 纯只读验证，不修改任何实盘数据.
    """
    from dreambuddy_evolution.core.strategy_gene import load_gene_library
    gene_root = EVO_ROOT / "gene_data"
    return load_gene_library(str(gene_root))


# ==============================================================================
# 2. 确定性 mock 市场数据 fixture
# ==============================================================================
@pytest.fixture
def trending_market():
    """确定性上升趋势行情（100 bars，每 bar 涨 0.5%）.

    用于验证开仓信号方向正确性.
    """
    bars = []
    price = 100.0
    for i in range(100):
        bars.append({
            "timestamp": i,
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price * 1.005,
            "volume": 10000.0,
        })
        price *= 1.005
    return bars


@pytest.fixture
def ranging_market():
    """确定性震荡行情（100 bars，围绕 100 上下波动 ±1%）.

    用于验证止损/止盈逻辑.
    """
    import math
    bars = []
    for i in range(100):
        center = 100.0 + math.sin(i * 0.3) * 2.0
        bars.append({
            "timestamp": i,
            "open": center,
            "high": center + 1.5,
            "low": center - 1.5,
            "close": center + math.sin(i * 0.3 + 0.5) * 0.8,
            "volume": 5000.0,
        })
    return bars


@pytest.fixture
def declining_market():
    """确定性下跌行情（100 bars，每 bar 跌 0.5%）.

    用于验证最大回撤控制.
    """
    bars = []
    price = 100.0
    for i in range(100):
        bars.append({
            "timestamp": i,
            "open": price,
            "high": price * 1.005,
            "low": price * 0.99,
            "close": price * 0.995,
            "volume": 8000.0,
        })
        price *= 0.995
    return bars


# ==============================================================================
# 3. 计算指标辅助函数
# ==============================================================================
def calc_ma(values, window):
    """简单移动平均."""
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def calc_drawdowns(equity_curve):
    """计算权益曲线的回撤序列.

    Returns:
        list[float]: 每个点的回撤（正数表示从峰值下降的百分比）
    """
    peak = equity_curve[0]
    drawdowns = []
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        drawdowns.append(dd)
    return drawdowns


def calc_sharpe(returns, risk_free_rate=0.0, periods_per_year=365):
    """计算年化 Sharpe 比率.

    Args:
        returns: 每期收益率序列
        risk_free_rate: 无风险利率（年化）
        periods_per_year: 每年期数

    Returns:
        float: 年化 Sharpe 比率. 若无收益数据返回 0.0.
    """
    import statistics
    if not returns or len(returns) < 2:
        return 0.0
    try:
        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns)
        if std_r == 0:
            return 0.0
        rf_per_period = risk_free_rate / periods_per_year
        sharpe = (mean_r - rf_per_period) / std_r * (periods_per_year ** 0.5)
        return sharpe
    except Exception:
        return 0.0
