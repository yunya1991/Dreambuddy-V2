"""ASIL — Agentic Self-Improvement Loop Phase 1 + Phase 2.

Phase 1 MVP (2026-11-10): 纯 stub，零 LLM，零 GPU，42 tests
Phase 2 (2026-11-10): 真实 D3 + D2-B + OracleV2(AST) + VaR 第三门
"""

from .cognitive_writeback import CognitiveWriteback
from .d2b_adapter import D2B_TYPES, D2BAdapter
from .d3_adapter import D3Adapter, D3IntentResult
from .emergence_loop import (
    D2EmergenceLoop,
    D3EmergenceLoop,
    LoopRecord,
    RuleVariant,
    TraeReviewCheckpoint,
)
from .kill_switch import KillSwitchAction, KillSwitchMonitor
from .llm_budget_tracker import LLMBudgetTracker
from .oracle_rea_independent import OracleValidatorV2
from .oracle_validator import OracleValidator
from .orchestrator import ASILOrchestrator
from .pipeline_builder import D2_BOOTSTRAP_TEMPLATES, PipelineBuilder
from .recall_stats import RecallStatsProvider, RecallWindowStats
from .session_outcome import SessionOutcome, SessionOutcomeCollector
from .trigger_scanner import PipelineTrigger, TriggerScanner
from .var_gate import compute_var_violation
from .variant_generator import (
    D2TemplateGenerator,
    D3VariantGenerator,
    TemplatePolicy,
    plan_diagnostics,
)
from .verdict_router import FeedbackWriter, VerdictResult, VerdictRouter

__all__ = [
    "ASILOrchestrator",
    "OracleValidator",
    "OracleValidatorV2",
    "LLMBudgetTracker",
    "TriggerScanner",
    "PipelineTrigger",
    "PipelineBuilder",
    "D2_BOOTSTRAP_TEMPLATES",
    "D2B_TYPES",
    "VerdictRouter",
    "VerdictResult",
    "FeedbackWriter",
    "KillSwitchMonitor",
    "KillSwitchAction",
    "MetricsCollector",
    "RecallStatsProvider",
    "RecallWindowStats",
    "D3Adapter",
    "D3IntentResult",
    "D2BAdapter",
    "SessionOutcomeCollector",
    "SessionOutcome",
    "compute_var_violation",
    "D3EmergenceLoop",
    "D2EmergenceLoop",
    "TraeReviewCheckpoint",
    "RuleVariant",
    "LoopRecord",
    "D3VariantGenerator",
    "D2TemplateGenerator",
    "TemplatePolicy",
    "plan_diagnostics",
    "CognitiveWriteback",
]

__version__ = "0.3.0"  # Phase 1 → Phase 2
