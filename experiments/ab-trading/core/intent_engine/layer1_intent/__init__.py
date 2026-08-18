"""
Layer 1: 意图识别层（收敛：从混沌到单点）

从用户自然语言、市场数据、信号等多源输入中，
收敛出一个清晰的单点目标（Objective）。
"""

from .objective_extractor import ObjectiveExtractor
from .objective_types import (
    OBJECTIVE_TYPES,
    get_objective_type,
    list_objective_types,
    search_objective_types,
)

__all__ = [
    'ObjectiveExtractor',
    'OBJECTIVE_TYPES',
    'get_objective_type',
    'list_objective_types',
    'search_objective_types',
]
