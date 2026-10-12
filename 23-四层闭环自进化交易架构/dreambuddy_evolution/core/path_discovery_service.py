"""PathDiscoveryService — 路径发现服务组件

从 evolution_pipeline.py _discover_paths/_select_optimal_path/_apply_high_order_factors 抽出。
当前为委托模式（通过 pipeline 引用委托），后续 Phase 逐步将实现搬入。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class PathDiscoveryService:
    """路径发现与寻优服务。

    职责：
    - apply_high_order_factors(): 高阶基因因子阻力调制（BCRM/BDSM/战略层）
    - discover_paths(): 多源路径发现（L2/Regime/BCRM/BDSM/战略/DeepReasoning）
    - select_optimal_path(): 路径寻优（HJB权重+矛盾调制+趋势延续）

    改造2/4代码（HJB 30%→70%权重 + FREEZE双候选）随此服务迁移。
    """

    def __init__(self, pipeline: Any = None):
        """构造函数。

        Args:
            pipeline: EvolutionPipeline 引用（委托模式，后续优化为独立依赖）
        """
        self._pipeline = pipeline

    def apply_high_order_factors(self, r_out: dict, symbol: str) -> dict:
        """高阶基因因子阻力调制。委托 pipeline._apply_high_order_factors。"""
        if self._pipeline is not None:
            return self._pipeline._apply_high_order_factors(r_out, symbol)
        return r_out

    def discover_paths(self, r_out: dict, kline_data: dict | None = None,
                       market_data: dict | None = None, symbol: str = "") -> list[dict]:
        """多源路径发现。委托 pipeline._discover_paths。"""
        if self._pipeline is not None:
            return self._pipeline._discover_paths(r_out, kline_data, market_data, symbol)
        return []

    def select_optimal_path(self, paths: list[dict], r_out: dict,
                            market_data: dict | None = None) -> dict:
        """路径寻优。委托 pipeline._select_optimal_path。"""
        if self._pipeline is not None:
            return self._pipeline._select_optimal_path(paths, r_out, market_data)
        return {"optimal_path": None, "all_paths": [], "path_scores": []}
