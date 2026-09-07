"""Typed dataclass contracts for all TEE API surface (FR-2.1)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Urgency(str, Enum):
    """How much Router should tilt thresholds toward aggressive exec."""
    LOW = "LOW"          # tighten → one tier more passive
    MEDIUM = "MEDIUM"    # default thresholds (FR-0.2)
    HIGH = "HIGH"        # loosen → one tier more aggressive


class AlgoName(str, Enum):
    DIRECT = "direct"
    TWAP15 = "twap15"
    TWAP60 = "twap60"
    PASSIVE = "passive"


@dataclass
class ParentRequest:
    """Input for TradeExecutionEngine.execute().

    FR-2.1 field list: inst_id, side, sz, pos_side, td_mode, leverage,
    decision_px (REQUIRED), source (REQUIRED). All others are optional."""
    inst_id: str
    side: str                              # "buy" / "sell"
    sz: float                              # 张数 (contract units)
    pos_side: str                          # "long" / "short" / "net"
    td_mode: str                           # "isolated" / "cross" / "cash"
    leverage: float                        # 5 (as default)
    decision_px: float                    # signal-trigger price (slip ref)
    source: str                            # "v15_open" / "v15_addon" / "v15_close" / …

    notional_usdt: Optional[float] = None  # optional: if caller already knows
    algo_override: Optional[str] = None    # e.g. "passive" to force algo
    algo_params_override: Optional[Dict[str, Any]] = None
    max_slippage_bps: Optional[float] = None  # override NFR defaults
    urgency: Urgency = Urgency.MEDIUM


@dataclass
class ChildOrderRecord:
    """Per-child audit row — embedded into the parent-order JSONL line."""
    child_id: str
    ord_type: str                          # "market" / "limit"
    px_submitted: Optional[float]          # None for pure market
    sz_submitted: float
    px_filled: Optional[float]             # avg fill price for this child
    sz_filled: float
    slippage_bps: float                    # vs parent decision_px
    ts_submitted_ms: int
    ts_settled_ms: Optional[int] = None
    closeout: bool = False                 # True if kill-switch close-out


@dataclass
class EstimateResult:
    """SlippageEstimator.estimate() output (FR-0.1)."""
    avg_fill_px: float
    slippage_bps: float
    market_impact_cost_usd: float
    walk_depth_level: int                  # how many levels consumed
    thin_book_warning: bool                # Top-10 insufficient for size
    fail_open: bool = False                # estimator used median fallback
    fallback_reason: Optional[str] = None
    orderbook_ts_ms: Optional[int] = None
    bids_consumed: List[Dict[str, Any]] = field(default_factory=list)
    asks_consumed: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """Return shape of TradeExecutionEngine.execute().

    FR-2.1 mandated fields: ok, parent_id, final_vwap, final_slippage_bps,
    total_filled_sz, remaining_sz, duration_ms, kill_switch_triggered,
    fail_open_reason, child_count."""
    ok: bool
    parent_id: str
    final_vwap: Optional[float]
    final_slippage_bps: Optional[float]
    total_filled_sz: float
    remaining_sz: float
    duration_ms: int
    kill_switch_triggered: bool
    fail_open_reason: Optional[str]
    child_count: int

    # Diagnostics (useful to callers but not for AC byte-equivalence)
    algo_used: Optional[str] = None
    router_decision: Optional[str] = None
    reject_reason: Optional[str] = None
    estimated_vwap: Optional[float] = None      # SHADOW mode: estimated fill
    estimated_slippage_bps: Optional[float] = None
    child_orders: List[ChildOrderRecord] = field(default_factory=list)
