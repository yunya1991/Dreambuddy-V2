"""
意图识别引擎 (Intent Recognition Engine)

S链核心：将用户模糊需求转化为可执行的工程蓝图

三层价值模型：
- Layer 1: 收敛（混沌 → 单点目标）
- Layer 2: 展开（单点 → 线/网 OKR）
- Layer 3: 落地（线/网 → 可执行蓝图）
"""

from .types import (
    Objective,
    KeyResult,
    OKRSet,
    ExecutionBlueprint,
    IntentRecognitionResult,
)
from .engine import IntentRecognitionEngine

__all__ = [
    'Objective',
    'KeyResult',
    'OKRSet',
    'ExecutionBlueprint',
    'IntentRecognitionResult',
    'IntentRecognitionEngine',
]
