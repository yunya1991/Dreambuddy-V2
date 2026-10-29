# -*- coding: utf-8 -*-
"""反思层（Reflection Layer）— SPEC-33-反思层 v0.3。

P1 回放模拟器（对齐 Dream-RSI）：发现树 Schema、回放池、确定性重放引擎。
P2 做梦评估循环：候选策略生成与回放目标函数。
P3 外部最优路径获取：E1-E4 全链路（采集→解析→验证→注入）。
P4 R1-R3 三级反思 + 纸上谈兵检测。
P5 批评自循环：观察期与客观回滚机制。
"""
from .replay_simulator import (
    MIN_TREES_FOR_EVAL,
    DiscoveryNode,
    DiscoveryTree,
    ReplayPool,
    ReplaySimulator,
)
from .recorder import AnalysisRecorder
from .dreaming import DreamingLoop, replay_objective, generate_candidates
from .harvest import ExternalHarvester, HarvestSource, HarvestOutcome
from .reflection_layer import ReflectionLayer, CritiqueFinding
from .critic_loop import CriticLoop, CriticProposal
from .training_cases import (
    TrainingCaseRecord,
    TrainingCaseGenerator,
    HistoricalCaseConverter,
    TrainingCaseStore,
)
from .rea_training_provider import REATrainingCaseProvider

__all__ = [
    "DiscoveryNode",
    "DiscoveryTree",
    "ReplayPool",
    "ReplaySimulator",
    "MIN_TREES_FOR_EVAL",
    "AnalysisRecorder",
    "DreamingLoop",
    "replay_objective",
    "generate_candidates",
    "ExternalHarvester",
    "HarvestSource",
    "HarvestOutcome",
    "ReflectionLayer",
    "CritiqueFinding",
    "CriticLoop",
    "CriticProposal",
    "TrainingCaseRecord",
    "TrainingCaseGenerator",
    "HistoricalCaseConverter",
    "TrainingCaseStore",
    "REATrainingCaseProvider",
]
