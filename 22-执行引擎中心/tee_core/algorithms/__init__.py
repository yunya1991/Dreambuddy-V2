"""ExecutionAlgorithm base package.

Concrete algorithms:
    DirectMarket — place a single market order (existing-behaviour parity)
    SmartTWAP    — time-sliced with jitter + escalation tiers
    SmartPassive — limit rehang top-of-book; fallback to TWAP if slow fill

All four share the same ``.run(parent_req, algo_params, client, estimator,
kill_switch_cb, audit_cb)`` signature and return :class:`AlgoRunResult`.
"""
from __future__ import annotations

from .base import AlgoRunResult, ExecutionAlgorithm  # noqa: F401
from .direct_market import DirectMarket                  # noqa: F401
from .smart_passive import SmartPassive                  # noqa: F401
from .smart_twap import SmartTWAP                        # noqa: F401

__all__ = [
    "AlgoRunResult", "ExecutionAlgorithm",
    "DirectMarket", "SmartTWAP", "SmartPassive",
]
