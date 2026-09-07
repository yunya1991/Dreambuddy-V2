"""Typed exceptions raised inside TEE core.

All exceptions:
  1. should be CAUGHT by FailOpenManager inside engine.execute();
  2. NEVER bubble up to strategy caller (guaranteed by TEE design).
"""
from __future__ import annotations


class TEEError(Exception):
    """Base for all TEE-internal exceptions."""


class EstimatorUnavailableError(TEEError):
    """Order-book or market-data endpoint unreachable; estimator degraded."""


class RouterDecisionError(TEEError):
    """Router could not determine algo decision; fall back to DIRECT."""


class AlgorithmExecutionError(TEEError):
    """Algorithmic executor raised during child-order dispatch loop."""


class KillSwitchTriggered(TEEError):
    """Non-error signal: runtime kill-switch closed-out remaining inventory."""


class RejectedPreExecution(TEEError):
    """Pre-order slippage exceeded hard gate; order rejected."""
