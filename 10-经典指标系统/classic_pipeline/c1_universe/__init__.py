"""C1 品种筛选（Symbol Filter）— 经典指标系统模块。

本模块只包含纯计算函数（无数据源/全局状态依赖）。
数据获取函数（_universe_pair_close_by_ts 等）仍留在 ml_trade_service.py 单体中，
通过调用本模块的纯计算函数完成指标计算。
"""

from . import universe

__all__ = ["universe"]
