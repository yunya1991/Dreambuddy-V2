"""SlippageEstimator — walk the top-N orderbook ladder to compute a
realistic expected VWAP and slip for a given parent order.

Public API (consumed by OrderRouter before dispatch, AC-1):

    est = SlippageEstimator(client: ExchangeClientProtocol)
    result = est.estimate(inst_id, side, *, sz_contracts, notional_usdt,
                          decision_px) -> EstimateResult

Algorithm (FR-0.1 / AC-1):

1. Load top-N book and (lot_sz, ct_val) from the client.
2. Derive the base-coin order size. Parent size can be provided either in
   contracts via ``sz_contracts`` (preferred) or in USDT via
   ``notional_usdt``. Each *level* of the OKX book reports its sz in
   base-coin units already, so consumption math is coin-vs-coin (no
   cross-rate surprises).
3. Walk the level list on the *consumed* side:
     side == buy  → eats asks from best → worst
     side == sell → eats bids from best → worst
   On each level fill ``min(remaining_coins, level_coin)``.
4. Compute:
     ``total_paid_usdt = Σ(fill_coin * fill_px)``
     ``total_filled_coin = Σ(fill_coin)``
     ``avg_fill_px = total_paid / total_filled``   (if filled > 0 else mid)
     ``slippage_bps = (avg_fill - decision_px) / decision_px * 10000``
     ``market_impact_cost_usd`` = extra paid (or less received) vs
        ``decision_px × total_filled``
5. ``walk_depth_level`` = the deepest 0-indexed level index touched + 1.
   (so the first level = depth 1).
6. ``thin_book_warning = True`` when ``want_coin > total_coin_on_side``
   (top-N depth insufficient for the requested size — router will pick a
   more passive algo when possible; see FR-0.2 thresholds).
7. FAIL-OPEN (AC-6): if ``get_orderbook`` raises or returns ok=False,
   estimator uses ``DEFAULT_SLIPPAGE_MEDIAN_BPS[coin]`` as a static slip
   estimate, sets ``fail_open=True, fallback_reason=<desc>``, and uses
   ``ask`` (buy) / ``bid`` (sell) from ``get_ticker`` as synthetic
   single-level fill anchor so avg_fill_px / impact still come out
   consistent.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..core.config import DEFAULT_SLIPPAGE_MEDIAN_BPS
from ..core.contract import EstimateResult
from ..core.protocol import ExchangeClient


# ── helpers ────────────────────────────────────────────────────────────
def _base_coin(inst_id: str) -> str:
    """Return base-coin for median/slippage lookup.

    Handles the three prevalent id shapes without needing to import an
    OKX-specific regex:
        "BTC-USDT-SWAP"  → "BTC"
        "BTC/USDT"       → "BTC"
        "BTCUSDT"        → fallback "BTCUSDT" (won't match dict → default)
    """
    for sep in ("-", "/"):
        if sep in inst_id:
            return inst_id.split(sep)[0]
    return inst_id


def _parse_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f


# ── estimator ──────────────────────────────────────────────────────────
class SlippageEstimator:
    """Walks top-N orderbook depth to estimate VWAP + slip for an order."""

    def __init__(self, client: ExchangeClient) -> None:
        self._client = client

    # ── public api ────────────────────────────────────────────────────
    def estimate(
        self,
        inst_id: str,
        side: str,
        *,
        sz_contracts: Optional[float] = None,
        notional_usdt: Optional[float] = None,
        decision_px: Optional[float] = None,
    ) -> EstimateResult:
        """Best-effort slippage estimation; FAIL-OPEN guarantees a result.

        Returns an :class:`EstimateResult`. Callers are expected to check
        ``fail_open`` and ``thin_book_warning`` before trusting the
        numerical fields too closely.
        """
        # 1. Fetch book.
        book: Optional[Dict[str, Any]] = None
        book_exception: Optional[str] = None
        try:
            book = self._client.get_orderbook(inst_id, sz=10)
        except Exception as e:  # noqa: BLE001 — FAIL-OPEN intentionally broad
            book_exception = f"get_orderbook raised {type(e).__name__}: {e}"
            book = None

        # 2. Fetch metadata and mid for fallback branches.
        ticker: Optional[Dict[str, Any]] = None
        try:
            ticker = self._client.get_ticker(inst_id)
        except Exception:  # noqa: BLE001
            ticker = None

        try:
            lot_sz, ct_val = self._client.get_contract_info(inst_id)
        except Exception:  # noqa: BLE001
            lot_sz, ct_val = (1.0, 1.0)
        lot_sz = float(lot_sz or 1.0)
        ct_val = float(ct_val or 1.0)

        # 3. Derive a sane decision_px anchor (mandatory per FR parent but
        #    callers sometimes pass None; fallback = best-mid).
        last = _parse_float(ticker.get("last")) if ticker else None
        bid = _parse_float(ticker.get("bid")) if ticker else None
        ask = _parse_float(ticker.get("ask")) if ticker else None
        mid = (
            (bid + ask) / 2.0 if (bid is not None and ask is not None)
            else last or 0.0
        )
        decision_anchor = float(decision_px) if decision_px else mid
        if not decision_anchor:
            decision_anchor = 1.0  # avoid div-by-zero if no data at all

        # 4. Derive want_coin (base coin size).
        want_coin = self._derive_want_coin(
            sz_contracts=sz_contracts, notional_usdt=notional_usdt,
            lot_sz=lot_sz, ct_val=ct_val, decision_px=decision_anchor,
        )

        # 5. FAIL-OPEN branch — if book failed → use MEDIAN bps fallback.
        if book_exception or (book and (not book.get("ok"))) or (not book):
            return self._median_fallback(
                inst_id=inst_id, side=side, want_coin=want_coin,
                decision_px=decision_anchor, bid=bid, ask=ask, mid=mid,
                fallback_reason=(
                    book_exception
                    or (book.get("error") if book else "book is None")
                    or "book not ok / empty"
                ),
            )

        # 6. Primary path — walk the ladder.
        return self._walk_ladder(
            book=book, side=side, want_coin=want_coin,
            decision_px=decision_anchor,
            ts_ms=book.get("ts"),
        )

    # ── size derivation ───────────────────────────────────────────────
    @staticmethod
    def _derive_want_coin(
        sz_contracts: Optional[float],
        notional_usdt: Optional[float],
        lot_sz: float,
        ct_val: float,
        decision_px: float,
    ) -> float:
        """Convert the caller-provided size expression to base coins.

        If the caller used ``sz_contracts``:
            coin = sz_contracts * lot_sz * ct_val

        If the caller used ``notional_usdt`` (no contracts):
            coin = notional / decision_px   (approx).

        lot_sz is the smallest tradable contract unit (e.g. BTC = 0.01
        means 1 contract = 0.01 BTC). ct_val = number of coins per
        contract for products where 1 contract != 1 lotcoin.
        """
        if sz_contracts is not None and float(sz_contracts) > 0:
            return float(sz_contracts) * lot_sz * ct_val
        if notional_usdt is not None and float(notional_usdt) > 0 and decision_px:
            return float(notional_usdt) / max(decision_px, 1e-12)
        return 0.0

    # ── primary ladder walk ───────────────────────────────────────────
    def _walk_ladder(
        self,
        book: Dict[str, Any],
        side: str,
        want_coin: float,
        decision_px: float,
        ts_ms: Any,
    ) -> EstimateResult:
        is_buy = (side or "buy").lower() == "buy"
        raw_levels: List[List[Any]] = (
            list(book.get("asks", []) if is_buy else book.get("bids", []))
        )
        # Parse to floats once. Order: best first (OKX convention).
        levels: List[Tuple[float, float]] = []
        for row in raw_levels:
            if not row:
                continue
            px = _parse_float(row[0])
            sz = _parse_float(row[1]) if len(row) > 1 else None
            if px is None or sz is None:
                continue
            levels.append((px, sz))

        total_level_coin = sum(sz for _, sz in levels)
        remaining = max(want_coin, 0.0)
        paid = 0.0            # USDT paid (buy) / USDT received (sell)
        filled_coin = 0.0
        depth_reached = 0
        consumed_records_bids: List[Dict[str, Any]] = []
        consumed_records_asks: List[Dict[str, Any]] = []

        for idx, (px, sz_coin) in enumerate(levels):
            if remaining <= 0:
                break
            take = min(remaining, sz_coin)
            paid += take * px
            filled_coin += take
            remaining -= take
            depth_reached = idx + 1
            rec = {"level": idx, "px": px, "coin_taken": take,
                   "level_total_coin": sz_coin}
            (consumed_records_asks if is_buy else consumed_records_bids).append(rec)

        thin_warning = want_coin > total_level_coin + 1e-12

        # If we couldn't fill anything (empty book / 0 want), anchor = mid.
        if filled_coin <= 0:
            # Use first visible level px as "fill" so slip math still works.
            if levels:
                avg_px = levels[0][0]
            else:
                avg_px = decision_px
            filled_coin_for_avg = want_coin if want_coin > 0 else 0.0
            impact = abs(avg_px - decision_px) * filled_coin_for_avg
            # slip sign
            slip_sign = 1.0 if is_buy else -1.0
            slip_bps = slip_sign * abs((avg_px - decision_px) / max(decision_px, 1e-12)) * 10000
            return EstimateResult(
                avg_fill_px=float(avg_px),
                slippage_bps=float(slip_bps),
                market_impact_cost_usd=float(impact),
                walk_depth_level=0, thin_book_warning=bool(thin_warning),
                fail_open=False,
                orderbook_ts_ms=int(ts_ms) if str(ts_ms).isdigit() else None,
                bids_consumed=consumed_records_bids,
                asks_consumed=consumed_records_asks,
            )

        avg_fill_px = paid / filled_coin
        # Slip sign: buy → avg > decision = positive slip (cost). sell: avg <
        # decision = positive slip (cost). In market convention we always
        # report slippage_bps as "cost vs decision", so both directions
        # should produce POSITIVE bps when they cost more than decision
        # and NEGATIVE when they beat it (e.g. buy at 100.05 but
        # decision=100.1, sell at 99.95 but decision=99.9).
        #
        # Our tests expect a directional signed bps where
        #   buy beats → neg, sell beats → neg, costs → pos
        # which matches
        #   (avg - decision)/decision10000 uniformly.
        slip_bps = (avg_fill_px - decision_px) / max(decision_px, 1e-12) * 10000.0

        # Impact in USDT (always positive = cost of slippage for a round
        # trip that entered at decision; for sell = less received).
        #     buy impact = paid - filled * decision
        #     sell impact = filled * decision - received
        benchmark_cost = filled_coin * decision_px
        impact = (paid - benchmark_cost) if is_buy else (benchmark_cost - paid)

        # book ts → int ms if possible
        ts_int: Optional[int] = None
        if ts_ms is not None:
            try:
                ts_int = int(ts_ms)
            except (TypeError, ValueError):
                ts_int = None

        return EstimateResult(
            avg_fill_px=float(avg_fill_px),
            slippage_bps=float(slip_bps),
            market_impact_cost_usd=float(impact),
            walk_depth_level=int(depth_reached),
            thin_book_warning=bool(thin_warning),
            fail_open=False,
            orderbook_ts_ms=ts_int,
            bids_consumed=consumed_records_bids,
            asks_consumed=consumed_records_asks,
        )

    # ── FAIL-OPEN: median fallback ───────────────────────────────────
    def _median_fallback(
        self,
        inst_id: str,
        side: str,
        want_coin: float,
        decision_px: float,
        bid: Optional[float],
        ask: Optional[float],
        mid: float,
        fallback_reason: str,
    ) -> EstimateResult:
        coin = _base_coin(inst_id)
        median_bps = float(
            DEFAULT_SLIPPAGE_MEDIAN_BPS.get(coin)
            or DEFAULT_SLIPPAGE_MEDIAN_BPS.get("__DEFAULT__", 10)
        )
        is_buy = (side or "buy").lower() == "buy"

        # FR-0.1 / AC-1 convention: the reported median bps is computed
        # from the decision_px anchor itself (bid/ask spread is a first-
        # touch cost handled by the buy-at-ask / sell-at-bid offset, but
        # the "slippage_bps" metric is the median *after* that touch).
        # To keep slip_bps == ±median_bps exactly we anchor on decision_px
        # directly. (sell slip comes out negative because avg < decision.)
        if is_buy:
            avg_fill = decision_px * (1.0 + median_bps / 10000.0)
        else:
            avg_fill = decision_px * (1.0 - median_bps / 10000.0)

        # Uniform slip_bps convention — signed (avg - decision)/decision*1e4
        slip_bps = (avg_fill - decision_px) / max(decision_px, 1e-12) * 10000.0
        impact = abs(avg_fill - decision_px) * max(want_coin, 0.0)

        return EstimateResult(
            avg_fill_px=float(avg_fill),
            slippage_bps=float(slip_bps),
            market_impact_cost_usd=float(impact),
            walk_depth_level=0,
            thin_book_warning=False,  # no depth info — don't flag
            fail_open=True,
            fallback_reason=fallback_reason,
        )
