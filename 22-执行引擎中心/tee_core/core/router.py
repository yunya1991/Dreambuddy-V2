"""OrderRouter — maps an order's size ratio vs recent 1-min volume, an
urgency level, and an optional caller override into one of four
execution algorithms (AC-2 / FR-0.2).

Decisions are *pure data*: the caller (TradeExecutionEngine) is free to
run them, compare them, or ignore them under FAIL-OPEN. The only side
effect this module should have is a single ``get_kline`` call when
``compute_size_ratio`` is requested — and that call has a full FAIL-OPEN
guard with per-asset medians.

Decision buckets (default Q3-A, ``config.ROUTER_*``):
    DIRECT  : size_ratio <  0.5 %        (→ direct_market algo)
    TWAP15  : size_ratio ∈ [0.5 %, 3 %)   (→ smart_twap 15 min)
    TWAP60  : size_ratio ∈ [3 %, 10 %)    (→ smart_twap 60 min)
    PASSIVE : size_ratio ≥ 10 %           (→ smart_passive)

Urgency shifts the decision one *row*:
    LOW    → one tier MORE passive   (e.g. DIRECT   → TWAP15)
    MEDIUM → tiers as-defined
    HIGH   → one tier MORE aggressive (e.g. TWAP60  → TWAP15)

``compute_size_ratio(inst_id, notional_usdt, client)`` returns
``order_notional_usdt / avg_1min_volume_usdt`` (fraction). If the kline
endpoint is unreachable it falls back to ``DEFAULT_1MIN_VOLUME_USDT`` so
a downstream decision is always possible — never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import config as _cfg
from ..core.contract import AlgoName, Urgency


# ── data shape ─────────────────────────────────────────────────────────
@dataclass
class RouterDecision:
    """Immutable return value of :meth:`OrderRouter.decide`."""
    algo: AlgoName
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_direct(self) -> bool:
        """Convenience — ENGINE branch cuts directly to market when True."""
        return self.algo is AlgoName.DIRECT


# ── ordered bucket list (used by both decide() and urgency shifting) ──
_BUCKETS: list[tuple[str, AlgoName]] = [
    # (name, algo). ORDER IS CRITICAL: from MOST aggressive → MOST passive.
    ("DIRECT",   AlgoName.DIRECT),
    ("TWAP15",   AlgoName.TWAP15),
    ("TWAP60",   AlgoName.TWAP60),
    ("PASSIVE",  AlgoName.PASSIVE),
]
_NB = len(_BUCKETS)


def _threshold_bucket(size_ratio: float) -> int:
    """Return index into _BUCKETS for a raw size_ratio (no urgency yet).

    Inclusive lower bounds (per tasks.md TR-5.1 boundary tests):
        ratio <  DIRECT_MAX            → DIRECT
        ratio ∈ [DIRECT_MAX, TWAP15_MAX) → TWAP15
        ratio ∈ [TWAP15_MAX, TWAP60_MAX) → TWAP60
        ratio ≥  TWAP60_MAX              → PASSIVE
    """
    if size_ratio < _cfg.ROUTER_DIRECT_MAX_PCT:
        return 0
    if size_ratio < _cfg.ROUTER_TWAP15_MAX_PCT:
        return 1
    if size_ratio < _cfg.ROUTER_TWAP60_MAX_PCT:
        return 2
    return 3


def _apply_urgency(bucket_idx: int, urgency: Urgency) -> int:
    """Shift the bucket index by one tier. Clamp to [0, NB-1]."""
    if urgency is Urgency.HIGH:
        shifted = bucket_idx - 1                 # more aggressive → smaller idx
    elif urgency is Urgency.LOW:
        shifted = bucket_idx + 1                 # more passive → larger idx
    else:
        shifted = bucket_idx
    # Clamp (can't go more aggressive than DIRECT, more passive than PASSIVE)
    return max(0, min(_NB - 1, shifted))


_OVERRIDE_ALIASES: Dict[str, AlgoName] = {
    "direct":  AlgoName.DIRECT,
    "twap":    AlgoName.TWAP15,
    "twap15":  AlgoName.TWAP15,
    "twap60":  AlgoName.TWAP60,
    "passive": AlgoName.PASSIVE,
}


def _default_params_for(algo: AlgoName) -> Dict[str, Any]:
    """Router parameter hints — algorithms honour these when possible.

    All values are configurable via ``tee_core.core.config``. The engine
    can override any hint (e.g. a kill-switch might force fewer slices),
    but the router's defaults are the canonical ones per AC-2.
    """
    if algo is AlgoName.DIRECT:
        return {}
    if algo is AlgoName.TWAP15:
        return {
            "window_sec":      15 * 60,
            "num_slices":      _cfg.TWAP_NUM_SLICES_TWAP15,
            "jitter_pct":      _cfg.TWAP_JITTER_PCT,
            "escalate_sec":    _cfg.TWAP_ESCALATE_SEC,
            "escalate_bps":    _cfg.TWAP_ESCALATE_STEP_BPS,
            "escalate_max":    _cfg.TWAP_ESCALATE_MAX_BPS,
            "timeout_sec":     _cfg.TWAP_TIMEOUT_TO_MARKET_SEC,
        }
    if algo is AlgoName.TWAP60:
        return {
            "window_sec":      60 * 60,
            "num_slices":      _cfg.TWAP_NUM_SLICES_TWAP60,
            "jitter_pct":      _cfg.TWAP_JITTER_PCT,
            "escalate_sec":    _cfg.TWAP_ESCALATE_SEC,
            "escalate_bps":    _cfg.TWAP_ESCALATE_STEP_BPS,
            "escalate_max":    _cfg.TWAP_ESCALATE_MAX_BPS,
            "timeout_sec":     _cfg.TWAP_TIMEOUT_TO_MARKET_SEC,
        }
    if algo is AlgoName.PASSIVE:
        return {
            "rehang_sec":               _cfg.PASSIVE_REHANG_SEC,
            "twap_fallback_sec":        _cfg.PASSIVE_TO_TWAP_SEC,
            "twap_fallback_fill_ratio": _cfg.PASSIVE_TO_TWAP_FILL_RATIO,
        }
    return {}


# ── main class ─────────────────────────────────────────────────────────
class OrderRouter:
    """Compute execution algorithm for a parent order."""

    def __init__(self, client: Any = None) -> None:
        """Inject a market-data client (used only by :meth:`compute_size_ratio`).

        ``client`` is accepted duck-typed. It must expose a ``get_kline``
        method that returns ``{"ok": bool, "bars": [{"c":, "vol":}, …]}``.
        Anything else is tolerated — compute_size_ratio will just fall
        back to the median table and never raise.
        """
        self._client = client

    # ── public: decide ────────────────────────────────────────────────
    def decide(
        self,
        size_ratio: float,
        urgency: Urgency = Urgency.MEDIUM,
        override: Optional[str] = None,
    ) -> RouterDecision:
        """Return the router's chosen algorithm for a size/urgency pair.

        Args:
            size_ratio:   order_notional_usdt / avg_1min_volume_usdt
                          (fraction, e.g. 0.01 = 1 %).
            urgency:      LOW / MEDIUM / HIGH. Shifts the decision by one
                          tier in the passive / aggressive direction.
            override:     None or one of the keys in _OVERRIDE_ALIASES —
                          any non-None value DOMINATES and bypasses the
                          matrix (useful for caller-forced routing).
        """
        # Override short-circuit (TR-5.2) — validate first.
        if override is not None:
            key = str(override).lower()
            if key not in _OVERRIDE_ALIASES:
                raise ValueError(
                    f"Unknown OrderRouter override='{override}'. "
                    f"Allowed: {sorted(_OVERRIDE_ALIASES)}"
                )
            algo = _OVERRIDE_ALIASES[key]
            return RouterDecision(algo=algo,
                                  params=_default_params_for(algo))

        # Pure threshold + urgency shift.
        bucket = _threshold_bucket(float(size_ratio))
        bucket_shifted = _apply_urgency(bucket, urgency)
        _, algo = _BUCKETS[bucket_shifted]
        return RouterDecision(algo=algo, params=_default_params_for(algo))

    # ── public: compute_size_ratio ────────────────────────────────────
    def compute_size_ratio(self, inst_id: str,
                           notional_usdt: float) -> float:
        """order_notional / avg-1m USDT volume. FAIL-OPEN guarded.

        Returns:
            A fraction (e.g. 0.01 means the order = 1 % of recent 1-min
            USDT turnover). Zero or negative notional inputs return 0.0
            (caller can treat that as DIRECT — an empty order doesn't
            need a 60-min TWAP).
        """
        if notional_usdt is None or float(notional_usdt) <= 0:
            return 0.0
        notional = float(notional_usdt)

        avg_1min_usdt = self._average_1min_volume_usdt(inst_id) or 1.0
        return notional / avg_1min_usdt

    # ── internal helpers ──────────────────────────────────────────────
    def _average_1min_volume_usdt(self, inst_id: str) -> float:
        """Compute avg 1-minute USDT notional from last 5 × 1m bars.

        If the call fails for any reason (network, missing bars, empty
        bars, client None, …) the function returns the per-asset median
        stored in ``config.DEFAULT_1MIN_VOLUME_USDT`` so callers always
        get a sane positive denominator.
        """
        # 1) Try happy path.
        client = self._client
        bars: Optional[list] = None
        if client is not None:
            get_kline = getattr(client, "get_kline", None)
            if callable(get_kline):
                try:
                    result = get_kline(inst_id, bar="1m", limit=5)
                    if isinstance(result, dict) and result.get("ok"):
                        bars = list(result.get("bars", []) or [])
                except Exception:  # noqa: BLE001 — broad, intentional FAIL-OPEN
                    bars = None

        # 2) If we got bars → compute mean USDT notional.
        if bars:
            per_bar_usdt: list[float] = []
            for b in bars:
                try:
                    close = float(b.get("c", 0.0) or 0.0)
                    vol = float(b.get("vol", 0.0) or 0.0)   # base coin volume
                except (TypeError, ValueError):
                    close = vol = 0.0
                if close > 0 and vol > 0:
                    per_bar_usdt.append(close * vol)
            if per_bar_usdt:
                return sum(per_bar_usdt) / len(per_bar_usdt)

        # 3) FAIL-OPEN — per-asset median or __DEFAULT__.
        coin = self._base_coin(inst_id)
        table = _cfg.DEFAULT_1MIN_VOLUME_USDT
        return float(table.get(coin) or table.get("__DEFAULT__") or 100_000.0)

    @staticmethod
    def _base_coin(inst_id: str) -> str:
        for sep in ("-", "/"):
            if sep in inst_id:
                return inst_id.split(sep)[0]
        return inst_id
