"""演化层（Evolution Layer）— SPEC-33-G 分层自更新。"""

from .adr_builder import AdrBuilder, AdrError
from .auto_merge import AutoMergeBlocked, AutoMergeCoordinator
from .case_ledger import CaseContractError, CaseStore, case_to_outcome, require_case
from .controller import ControllerError, EvolutionController
from .drift_guard import DriftGuard
from .emergence import CandidateError, EmergenceEngine
from .event_ledger import SCHEMA_VERSION, EventLedger, EventLedgerError
from .executor import (
    RollbackBudgetExceeded,
    RollbackExecutor,
    SandboxIsolationError,
    SandboxRunner,
    ShadowEvaluator,
    evaluate_observation,
)
from .heldout import HeldoutError, HeldoutStore, validate_manifest
from .pending_actions import PendingActionError, PendingActionStore
from .policy_ledger import (
    LEVEL_QUOTAS,
    PolicyLedger,
    PolicyLedgerError,
    evaluate_gates,
)
from .pollution import PollutionRollback
from .proposal_pipeline import DualModelPipeline, validate_proposal
from .reference_ledger import ReferenceError, ReferenceLedger
from .research_pipeline import (
    ChangeClassifier,
    PipelineError,
    ResearchPipeline,
    classify_change,
)
from .triggers import DEFAULT_CONFIG, TriggerEngine

__all__ = [
    "AdrBuilder",
    "AdrError",
    "AutoMergeBlocked",
    "AutoMergeCoordinator",
    "CaseContractError",
    "CaseStore",
    "case_to_outcome",
    "require_case",
    "CandidateError",
    "EmergenceEngine",
    "DriftGuard",
    "HeldoutError",
    "HeldoutStore",
    "validate_manifest",
    "PendingActionError",
    "PendingActionStore",
    "LEVEL_QUOTAS",
    "PolicyLedger",
    "PolicyLedgerError",
    "evaluate_gates",
    "DEFAULT_CONFIG",
    "TriggerEngine",
    "DualModelPipeline",
    "validate_proposal",
    "ReferenceError",
    "ReferenceLedger",
    "ChangeClassifier",
    "PipelineError",
    "ResearchPipeline",
    "classify_change",
    "SandboxRunner",
    "SandboxIsolationError",
    "ShadowEvaluator",
    "RollbackExecutor",
    "RollbackBudgetExceeded",
    "evaluate_observation",
    "PollutionRollback",
    "ControllerError",
    "EvolutionController",
    "EventLedger",
    "EventLedgerError",
    "SCHEMA_VERSION",
]
