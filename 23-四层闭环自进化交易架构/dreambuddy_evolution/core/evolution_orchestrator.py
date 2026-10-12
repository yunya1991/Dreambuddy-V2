"""EvolutionOrchestrator — 四层闭环编排组件

从 evolution_pipeline.py run_symbol 主流程抽出。
当前为委托模式（通过 pipeline 引用委托），后续 Phase 逐步将实现搬入。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EvolutionOrchestrator:
    """四层闭环编排器。

    职责：
    - run_symbol(): 四层闭环主流程（L1→Level0→L2→决策→L3→L4→回馈）
    - get_feedback(): L4 反馈获取

    依赖注入：
    - weight_store: 权重持久化
    - path_discovery: 路径发现服务
    - logging_ctx: 日志上下文
    """

    def __init__(self, weight_store: Any = None, path_discovery: Any = None,
                 logging_ctx: Any = None, pipeline: Any = None):
        """构造函数。

        Args:
            weight_store: WeightStore 实例
            path_discovery: PathDiscoveryService 实例
            logging_ctx: PipelineLoggingContext 实例
            pipeline: EvolutionPipeline 引用（委托模式）
        """
        self._weight_store = weight_store
        self._path_discovery = path_discovery
        self._logging = logging_ctx
        self._pipeline = pipeline

    def run_symbol(self, symbol: str, market_data: dict, rv: Any = None) -> dict:
        """四层闭环主流程。委托 pipeline.run_symbol。"""
        if self._pipeline is not None:
            return self._pipeline.run_symbol(symbol, market_data, rv)
        return {}

    def get_feedback(self) -> dict:
        """L4 反馈获取。委托 pipeline.get_feedback。"""
        if self._pipeline is not None:
            return self._pipeline.get_feedback()
        return {}
