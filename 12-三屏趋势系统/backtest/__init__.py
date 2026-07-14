"""三屏趋势系统 — 回测框架

向量化回测引擎，参考 VectorBT 设计理念。

模块结构:
- engine.py:        核心回测引擎（向量化计算）
- metrics.py:       绩效指标计算
- strategy.py:      策略基类与三屏策略包装器
- data_utils.py:    数据准备工具
- results.py:       回测结果与报告
- walk_forward.py:  Walk-Forward 滚动前向验证
- overfitting.py:   过拟合检测（参数敏感性/置换检验/成本敏感性）
- calibration.py:   置信度校准分析（ECE/Platt Scaling/Isotonic）
"""

from .engine import BacktestEngine
from .metrics import calculate_performance_metrics
from .strategy import (
    BaseStrategy,
    BuyAndHoldStrategy,
    MovingAverageStrategy,
    TrendScreenStrategy,
)
from .data_utils import (
    prepare_ohlcv_dataframe,
    fetch_historical_data,
    train_test_split,
    generate_sample_data,
)
from .results import (
    BacktestResult,
    compare_results,
    format_comparison_table,
)
from .walk_forward import WalkForwardAnalyzer
from .overfitting import (
    parameter_sensitivity_analysis,
    format_sensitivity_report,
    permutation_test,
    format_permutation_report,
    cost_sensitivity_test,
    format_cost_report,
)
from .calibration import (
    calculate_ece,
    platt_scaling,
    isotonic_calibration,
    cross_validated_calibration,
    collect_calibration_data,
    format_calibration_report,
)

__all__ = [
    # 核心引擎
    "BacktestEngine",
    "calculate_performance_metrics",
    # 策略
    "BaseStrategy",
    "BuyAndHoldStrategy",
    "MovingAverageStrategy",
    "TrendScreenStrategy",
    # 数据工具
    "prepare_ohlcv_dataframe",
    "fetch_historical_data",
    "train_test_split",
    "generate_sample_data",
    # 结果报告
    "BacktestResult",
    "compare_results",
    "format_comparison_table",
    # Walk-Forward
    "WalkForwardAnalyzer",
    # 过拟合检测
    "parameter_sensitivity_analysis",
    "format_sensitivity_report",
    "permutation_test",
    "format_permutation_report",
    "cost_sensitivity_test",
    "format_cost_report",
    # 置信度校准
    "calculate_ece",
    "platt_scaling",
    "isotonic_calibration",
    "cross_validated_calibration",
    "collect_calibration_data",
    "format_calibration_report",
]
