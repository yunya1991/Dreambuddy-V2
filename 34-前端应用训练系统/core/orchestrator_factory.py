"""编排器工厂 — 组装 4 个适配器到 DualModeTrainingOrchestrator。

提供统一的工厂函数，创建配置好的编排器实例。
"""
import os
import sys

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_ADAPTERS_DIR = os.path.join(_34_DIR, "adapters")

for _p in [_ADAPTERS_DIR, _THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from interfaces.training_executor import TrainingLayer
from dual_mode_orchestrator import DualModeTrainingOrchestrator
from tdr_data_provider import TDRTrainingDataProvider
from ts_http_training_executor import TSHTTPTrainingExecutor
from generic_case_evaluator import GenericCaseEvaluator
from rea_native_parser import REANativeParser


def create_orchestrator(
    frontend_url: str = None,
    enable_rea: bool = True,
) -> DualModeTrainingOrchestrator:
    """创建配置好的双模式训练编排器。

    Args:
        frontend_url: 前端服务地址（默认 http://localhost:3001）
        enable_rea: 是否启用 33-REA 解析（默认 True）

    Returns:
        配置好 4 个适配器的 DualModeTrainingOrchestrator
    """
    # 1. 数据提供者：TDR
    data_providers = [TDRTrainingDataProvider()]

    # 2. 训练执行器：5 层 TS HTTP 执行器
    training_executors = [
        TSHTTPTrainingExecutor(TrainingLayer.S, base_url=frontend_url),
        TSHTTPTrainingExecutor(TrainingLayer.DSH, base_url=frontend_url),
        TSHTTPTrainingExecutor(TrainingLayer.C, base_url=frontend_url),
        TSHTTPTrainingExecutor(TrainingLayer.G, base_url=frontend_url),
        TSHTTPTrainingExecutor(TrainingLayer.LLM, base_url=frontend_url),
    ]

    # 3. 案例评估器
    case_evaluator = GenericCaseEvaluator()

    # 4. REA 解析器（可选）
    rea_parser = REANativeParser() if enable_rea else None

    return DualModeTrainingOrchestrator(
        data_providers=data_providers,
        training_executors=training_executors,
        case_evaluator=case_evaluator,
        rea_parser=rea_parser,
    )
