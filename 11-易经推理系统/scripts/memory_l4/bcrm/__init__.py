"""
BCRM - Binary Contradiction Reasoning Model
二分矛盾推理模型（易经交易决策系统）

第一性原理：市场沿阻力最小方向运动 = 力的合成。
架构：力学引擎（核心）+ 易经引擎（符号解释层）。
"""

from ._constants import (
    DIR_UP, DIR_DOWN, DIR_FLAT,
    GUA_QIAN, GUA_KUN, GUA_ZHEN, GUA_XUN,
    GUA_KAN, GUA_LI, GUA_GEN, GUA_DUI,
    GUA_NAMES_CN, GUA_NATURE, GUA_WUXING,
    GUA_BINARY, BINARY_TO_GUA, EIGHT_GUAS,
    OPPOSITE_GUAS,
    SPIRAL_FIRST_AFFIRMATION, SPIRAL_FIRST_NEGATION, SPIRAL_SECOND_NEGATION,
    PHIL_YIJING, PHIL_MATERIALIST_DIALECTIC,
    DEFAULT_QUALITATIVE_THRESHOLD,
    DEFAULT_MIN_CONFIDENCE_THRESHOLD,
    SIXIANG_TAIYANG, SIXIANG_SHAOYANG, SIXIANG_SHAOYIN, SIXIANG_TAIYIN,
    SIXIANG_TIME, SIXIANG_SPACE, SIXIANG_SURFACE, SIXIANG_CORE,
)

from .output_contract import (
    BCRMOutput,
    ContradictionState,
    DialecticalStep,
    NextState,
    TransformationTrigger,
    StrategyBranch,
    HexagramResult,
    SpiralPosition,
    PracticeDirective,
)

from .sixty_four_guas import (
    HexagramKnowledge,
    YaoResult,
    SIXTY_FOUR_GUAS,
    get_hexagram_knowledge,
    build_hexagram_by_guas,
    get_all_hexagram_names,
)

from .yijing_engine import (
    YijingEngine,
    YijingResult,
)

from .force_engine import (
    ForceEngine,
    Force3D,
    MarketForces,
    ForceResult,
)

from .scale_engine import (
    ScaleEngine,
    ScaleParams,
    compute_scale,
    scale_to_params,
    scale_to_gua,
    gua_to_scale_params,
    smooth_scale_to_params,
    compute_hexagram_params,
)

from .liangyi_engine import (
    LiangyiEngine,
    LiangyiState,
)

from .engine import BCRMEngine

from .guardrail import BCRMGuardrail, GuardResult, default_guardrail
from .knowledge_base import (
    BCRMKnowledgeBase,
    KnowledgeEntry,
    GuaKnowledge,
    default_knowledge_base,
)
from .memory_adapter import (
    MockMemoryAdapter,
    L4MemoryAdapter,
    BCRMMemoryCase,
    default_memory_adapter,
)
from .walk_forward import (
    WalkForwardEngine,
    WalkForwardResult,
    generate_synthetic_data,
    run_bcrm_backtest,
    build_bcrm_predict_fn,
)
from .backtest_gate import (
    BacktestGateEngine,
    GateResult,
    BacktestMetrics,
    default_backtest_gate,
)
from .case_writer import CaseWriter, default_case_writer
from .a_series_bridge import AShareBridge, AShareSnapshot, default_ashare_bridge

__all__ = [
    "DIR_UP", "DIR_DOWN", "DIR_FLAT",
    "GUA_QIAN", "GUA_KUN", "GUA_ZHEN", "GUA_XUN",
    "GUA_KAN", "GUA_LI", "GUA_GEN", "GUA_DUI",
    "GUA_NAMES_CN", "GUA_NATURE", "GUA_WUXING",
    "GUA_BINARY", "BINARY_TO_GUA", "EIGHT_GUAS", "OPPOSITE_GUAS",
    "SPIRAL_FIRST_AFFIRMATION", "SPIRAL_FIRST_NEGATION",
    "SPIRAL_SECOND_NEGATION",
    "PHIL_YIJING", "PHIL_MATERIALIST_DIALECTIC",
    "DEFAULT_QUALITATIVE_THRESHOLD",
    "DEFAULT_MIN_CONFIDENCE_THRESHOLD",
    "SIXIANG_TAIYANG", "SIXIANG_SHAOYANG",
    "SIXIANG_SHAOYIN", "SIXIANG_TAIYIN",

    "BCRMOutput",
    "ContradictionState",
    "DialecticalStep",
    "NextState",
    "TransformationTrigger",
    "StrategyBranch",
    "HexagramResult",
    "SpiralPosition",
    "PracticeDirective",

    "HexagramKnowledge",
    "YaoResult",
    "SIXTY_FOUR_GUAS",
    "get_hexagram_knowledge",
    "build_hexagram_by_guas",
    "get_all_hexagram_names",

    "YijingEngine",
    "YijingResult",

    "ForceEngine", "Force3D", "MarketForces", "ForceResult",

    "ScaleEngine", "ScaleParams",
    "compute_scale", "scale_to_params", "scale_to_gua",
    "gua_to_scale_params", "smooth_scale_to_params",
    "compute_hexagram_params",

    "LiangyiEngine", "LiangyiState",

    "BCRMEngine",

    "BCRMGuardrail", "GuardResult", "default_guardrail",
    "BCRMKnowledgeBase", "KnowledgeEntry", "GuaKnowledge",
    "default_knowledge_base",
    "MockMemoryAdapter", "L4MemoryAdapter", "BCRMMemoryCase",
    "default_memory_adapter",
    "WalkForwardEngine", "WalkForwardResult",
    "generate_synthetic_data", "run_bcrm_backtest",
    "build_bcrm_predict_fn",
    "BacktestGateEngine", "GateResult", "BacktestMetrics",
    "default_backtest_gate",
    "CaseWriter", "default_case_writer",
    "AShareBridge", "AShareSnapshot", "default_ashare_bridge",
]

__version__ = "0.1.0"
