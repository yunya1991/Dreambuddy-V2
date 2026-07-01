#!/usr/bin/env python3
"""
意图识别引擎 - 类型定义

位置: experiments/ab-trading/core/intent_engine/types.py

三层价值模型:
- Layer 1: 收敛（混沌 → 单点目标）
- Layer 2: 展开（单点 → 线/网 OKR）
- Layer 3: 落地（线/网 → 可执行蓝图）
"""

import uuid
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# Layer 1: 意图识别层 - 目标 (Objective)
# ============================================================

@dataclass
class Objective:
    """目标 (Objective) - 用户想要完成的单点目标

    Layer 1 的输出：从混沌收敛到单点
    核心特征：只有一个、清晰明确、可被分解
    """
    id: str = field(default_factory=lambda: _gen_id("obj"))
    title: str = ""
    description: str = ""

    type: str = ""
    domain: str = ""
    complexity: str = "standard"

    priority: int = 5
    time_constraint: Optional[str] = None

    source: str = "nl"
    source_confidence: float = 0.8

    extracted_keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0

    clarify_needed: bool = False
    clarify_question: Optional[str] = None
    clarify_options: Optional[List[Dict]] = None

    created_at: float = field(default_factory=time.time)


# ============================================================
# Layer 2: OKR目标分解层 - 关键结果 (KeyResult)
# ============================================================

@dataclass
class KeyResult:
    """关键结果 (KeyResult) - 衡量目标达成的具体指标

    Layer 2 的输出：从单点目标展开为可衡量的KR
    核心特征：只关注"衡量什么"，不关注"怎么执行"

    注意：这里不包含模块/节点信息，那是B层的职责
    """
    id: str = field(default_factory=lambda: _gen_id("kr"))
    objective_id: str = ""

    title: str = ""
    description: str = ""
    metric: str = ""
    target_value: float = 0.0
    current_value: Optional[float] = None
    unit: str = ""

    weight: float = 0.0
    order_index: int = 0
    line_id: str = ""

    status: str = "pending"

    depends_on: List[str] = field(default_factory=list)
    is_parallel: bool = False

    capability_tags: List[str] = field(default_factory=list)
    complexity_hint: str = "standard"


@dataclass
class OKRSet:
    """OKR集 - 包含一个目标和其对应的所有关键结果

    Layer 2 的最终输出：完整的目标结构
    """
    objective: Objective
    key_results: List[KeyResult] = field(default_factory=list)

    mode: str = "single"
    complexity: str = "standard"

    lines: List[Dict] = field(default_factory=list)
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)

    total_weight: float = 0.0
    parallel_line_count: int = 0
    sequential_depth: int = 0

    confidence: float = 0.0
    rationale: str = ""


# ============================================================
# Layer 3: B层工程化 - 执行蓝图 (ExecutionBlueprint)
# ============================================================

@dataclass
class ExecutionBlueprint:
    """执行蓝图 - B层工程化输出

    Layer 3 的输出：可直接交给 GraphOrchestrator 执行的工程蓝图
    核心特征：包含执行所需的所有工程细节
    """
    blueprint_id: str = field(default_factory=lambda: _gen_id("bp"))
    objective_id: str = ""

    complexity: str = "standard"
    okr_mode: str = "single"

    node_sequence: List[str] = field(default_factory=list)
    execution_mode: str = "sequential"
    dependencies: Dict[str, List[str]] = field(default_factory=dict)
    parallel_groups: List[List[str]] = field(default_factory=list)

    kr_to_nodes: Dict[str, List[str]] = field(default_factory=dict)
    node_to_kr: Dict[str, str] = field(default_factory=dict)

    total_timeout_ms: int = 60000
    node_timeout_ms: Dict[str, int] = field(default_factory=dict)
    retry_policy: Dict[str, Dict] = field(default_factory=dict)
    fallback_policy: Dict[str, str] = field(default_factory=dict)

    early_stop_condition: Optional[str] = None
    required_nodes: List[str] = field(default_factory=list)
    optional_nodes: List[str] = field(default_factory=list)

    replan_enabled: bool = False
    replan_triggers: List[str] = field(default_factory=list)
    max_replans: int = 0

    confidence: float = 0.0
    rationale: str = ""

    created_at: float = field(default_factory=time.time)


# ============================================================
# 最终输出：意图识别结果
# ============================================================

@dataclass
class IntentRecognitionResult:
    """意图识别最终结果（三层完整输出）"""
    objective: Optional[Objective] = None
    okr_set: Optional[OKRSet] = None
    blueprint: Optional[ExecutionBlueprint] = None

    state: str = "pending"
    confidence: float = 0.0
    rationale: str = ""

    clarify_question: Optional[str] = None
    clarify_options: Optional[List[Dict]] = None

    created_at: float = field(default_factory=time.time)
