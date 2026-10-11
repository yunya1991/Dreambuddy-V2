"""34-前端应用训练系统 对外接口协议包。

本模块通过 Protocol 定义与外部系统的契约，确保独立性和可复用性。
外部系统通过 adapters/ 实现这些协议接入。
"""
from .training_data_provider import TrainingDataProvider, TrainingCase
from .training_executor import TrainingExecutor, TrainingLayer, TrainingResult
from .case_evaluator import CaseEvaluator, CaseEvaluation, IngestDecision
from .rea_parser import REAParser, REAParseResult

__all__ = [
    "TrainingDataProvider",
    "TrainingCase",
    "TrainingExecutor",
    "TrainingLayer",
    "TrainingResult",
    "CaseEvaluator",
    "CaseEvaluation",
    "IngestDecision",
    "REAParser",
    "REAParseResult",
]
