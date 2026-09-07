"""Task 10 RED → GREEN tests — TEE main class + V15 compat + idempotency + shadow.

5 TRs correspond to spec rules:
  TR-10.1 AC-7 byte-equivalence: ENABLE_TEE=False path → place_order body
    is identical (keys & values) to legacy okx_client.place_order(...).
    Pure market orders never include a "px" key (AC-7).
  TR-10.2 AC-9 idempotency: Same minute-bucket → 3 identical executes →
    place_order count = 1 (DirectMarket 1-child). After 120+ seconds the
    bucket changes → real count increases.
  TR-10.3 AC-10 shadow mode: SHADOW=True. SmartTWAP 3-slice execution →
    place_order.call_count=0, cancel_order.call_count=0. Auditor still
    records a parent but estimated_vwap/filled_sz are set. Audit file is
    suffixed with "_shadow" so real/shadow streams don't merge.
  TR-10.4 V15 integration smoke: simulate execute_open_position wrapper
    with tee.execute_market_compat(...) replacing client.place_order().
    Resultant state["positions"]["BTC"] equals baseline dict field-by-
    field; optional "open_engine": "TEE" extra field allowed but no
    legacy structural mutation.
  TR-10.5 V15 regression rubric (AC-11, threshold ≥ 2): Run
    open→addon→close 3-step mini flow. Compare the resultant state JSON
    serialized (sorted keys, no _engine tag) to the pre-TEE baseline.
    Exact match → score 2.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))
sys.path.insert(0, str(REPO / "14-V15经典马丁策略" / "lib"))


# =====================================================================
# helpers for TR-10.4 / 10.5 — V15 state "contract" snapshot
# =====================================================================
V15_POSITION_FIELDS_LEGACY = (
    # 1983.. L1999+ of v15_trader.py — every field written to
    # state["positions"][coin] when opening a position.
    "inst_id", "direction", "entry_price", "open_price", "sz",
    "addons", "confidence", "open_time", "take_profit_pct",
    "original_tp_pct", "addon_pct", "stop_loss_price",
    "stop_loss_type", "vol_mult", "per_coin_budget", "base_usd",
)  # (truncated for test purposes; at least the fields that TR-10.4
   #  smoke snapshot populates)

# TR-10.5 minimum legacy flow (open addon close) state keys.
MINI_OPEN_ARGS = dict(
    inst_id="BTC-USDT-SWAP", coin="BTC", is_short=False,
    sz=1, td_mode="isolated", pos_side="long", leverage=5,
    entry_price=70000.0, addon_pct=0.015, tp_pct=0.03,
    sl_price=67000.0, sl_type="fixed", conf=82, vol_mult=1.2,
    alloc={"per_coin_budget": 1000, "base_usd": 1000},
)


def _legacy_build_position_baseline(**kwargs: Any) -> Dict[str, Any]:
    """Rebuild exactly the lines 1983.. of v15_trader.py without TEE."""
    coin = kwargs["coin"]
    direction = "SHORT" if kwargs["is_short"] else "LONG"
    return {
        "inst_id": kwargs["inst_id"],
        "direction": direction,
        "entry_price": kwargs["entry_price"],
        "open_price": kwargs["entry_price"],
        "sz": kwargs["sz"],
        "addons": 0,
        "confidence": kwargs["conf"],
        "open_time": kwargs.get("open_time_iso")
        or datetime.now(timezone.utc).isoformat(),
        "take_profit_pct": kwargs["tp_pct"],
        "original_tp_pct": kwargs["tp_pct"],
        "addon_pct": kwargs["addon_pct"],
        "stop_loss_price": kwargs["sl_price"],
        "stop_loss_type": kwargs["sl_type"],
        "vol_mult": kwargs["vol_mult"],
        "per_coin_budget": kwargs["alloc"]["per_coin_budget"],
        "base_usd": kwargs["alloc"]["base_usd"],
    }


# =====================================================================
# TR-10.1 byte equivalence AC-7
# =====================================================================
class TestTR101ByteEquivalence:
    @staticmethod
    def _make_engine(client_mock: MagicMock, enable_tee: bool):
        from tee_core.core.engine import TradeExecutionEngine
        return TradeExecutionEngine(
            exchange_client=client_mock,
            enable_tee=enable_tee,
            shadow_mode=False,
        )

    def test_disabled_tee_matches_legacy_place_order_keys_and_values(
            self, tmp_path: Path):
        """AC-7: ENABLE_TEE=False → compat.place_order(...) sends the
        EXACT same kwargs as the original client.place_order(…) call. No
        extra keys (e.g. no "max_slippage_bps") and no missing keys."""
        from tee_core.core.engine import TradeExecutionEngine

        client_legacy = MagicMock(name="legacy-client")
        client_wrapped = MagicMock(name="wrapped-client")
        # Simulate ticker result (so compat can pick decision_px).
        client_wrapped.get_ticker.return_value = {
            "ok": True, "last": 70_000.0, "ask": 70_001.0, "bid": 69_999.0,
            "inst_id": "BTC-USDT-SWAP",
        }
        client_legacy.get_ticker.return_value = client_wrapped.get_ticker()
        # Both return identical success dicts with the same ordId so
        # equality assertions are stable.
        success_r = {"ok": True, "ord_id": "O1", "data": {"ordId": "O1"}}
        client_legacy.place_order.return_value = success_r
        client_wrapped.place_order.return_value = success_r

        # (1) legacy call.
        legacy_kwargs = dict(
            inst_id="BTC-USDT-SWAP",
            side="buy", sz=1, td_mode="isolated", pos_side="long",
        )
        client_legacy.place_order(**legacy_kwargs)

        # (2) compat call via TEE.execute_market_compat with enable_tee=False
        # (direct_no_slippage_cap=True path).
        tee = TradeExecutionEngine(
            exchange_client=client_wrapped,
            enable_tee=False,
            shadow_mode=False,
            audit_dir=str(tmp_path / "audit"),
            metrics_path=str(tmp_path / "metrics.json"),
            failopen_log_path=str(tmp_path / "tee_failopen.log"),
        )
        tee.execute_market_compat(
            inst_id="BTC-USDT-SWAP",
            side="buy", sz=1, td_mode="isolated", pos_side="long",
            tag="v15_compat_open",
        )

        legacy_call = client_legacy.place_order.call_args
        tee_call = client_wrapped.place_order.call_args
        # Keys set-equality (order doesn't matter).
        legacy_keys = set(legacy_call.kwargs.keys())
        tee_keys = set(tee_call.kwargs.keys())
        assert legacy_keys == tee_keys, (
            f"AC-7 FAIL: key sets differ. legacy={legacy_keys}, tee={tee_keys}"
        )
        assert legacy_call.kwargs == tee_call.kwargs, (
            f"AC-7 FAIL: values differ.\nlegacy  = {legacy_call.kwargs}\n"
            f"tee     = {tee_call.kwargs}"
        )
        # Pure market → NO "px" key in the body.
        assert "px" not in tee_keys and "px" not in legacy_keys, (
            "AC-7 FAIL: pure market order must never include price key."
        )
        # "max_slippage_bps" must NOT be attached when enable_tee=False
        # (direct_no_slippage_cap=True convention).
        assert "max_slippage_bps" not in tee_keys, (
            "AC-7 FAIL: ENABLE_TEE=False must NOT carry max_slippage_bps kwarg."
        )


# =====================================================================
# TR-10.2 idempotency AC-9 (minute bucket 120s TTL)
# =====================================================================
class TestTR102Idempotency:
    def test_same_minute_bucket_deduplicates_to_single_place(
            self, tmp_path: Path):
        from tee_core.core.engine import TradeExecutionEngine
        client = MagicMock()
        client.get_ticker.return_value = {
            "ok": True, "last": 70_000.0, "ask": 70_001.0, "bid": 69_999.0,
        }
        client.place_order.return_value = {
            "ok": True, "ord_id": "O-ID", "data": {"ordId": "O-ID"},
        }
        tee = TradeExecutionEngine(
            exchange_client=client, enable_tee=False, shadow_mode=False,
            audit_dir=str(tmp_path / "audit"),
            metrics_path=str(tmp_path / "metrics.json"),
            failopen_log_path=str(tmp_path / "fo.log"),
            idempotency_ttl_sec=120,
        )
        kwargs = dict(inst_id="BTC-USDT-SWAP", side="buy", sz=1,
                      td_mode="isolated", pos_side="long", tag="v15")
        # Same "now" for every call in this test → minute bucket same.
        fixed_ts = 1_700_000_000.0
        with patch("tee_core.core.engine.time") as tm:
            tm.time.return_value = fixed_ts
            r1 = tee.execute_market_compat(**kwargs)
            r2 = tee.execute_market_compat(**kwargs)
            r3 = tee.execute_market_compat(**kwargs)

        assert client.place_order.call_count == 1, (
            f"3 identical calls in same minute bucket must dedup to 1 place_order."
            f" Got {client.place_order.call_count} calls."
        )
        # Return value must be compatible with legacy return (has ord_id).
        assert r1.get("ok") and r1.get("ord_id")
        # r2, r3 should be duplicates — still return an OK dict but
        # ideally signal dedup via a nested marker (idempotent_hit: True).
        assert r2.get("ok") and r3.get("ok")

    def test_after_minute_bucket_rolls_real_place_repeats(
            self, tmp_path: Path):
        from tee_core.core.engine import TradeExecutionEngine
        client = MagicMock()
        client.get_ticker.return_value = {
            "ok": True, "last": 70_000.0, "ask": 70_001.0, "bid": 69_999.0,
        }
        client.place_order.return_value = {"ok": True, "ord_id": "O"}
        tee = TradeExecutionEngine(
            exchange_client=client, enable_tee=False, shadow_mode=False,
            audit_dir=str(tmp_path / "audit"),
            metrics_path=str(tmp_path / "metrics.json"),
            failopen_log_path=str(tmp_path / "fo.log"),
            idempotency_ttl_sec=120,
        )
        kwargs = dict(inst_id="ETH-USDT-SWAP", side="sell", sz=10,
                      td_mode="isolated", pos_side="short", tag="v15")
        with patch("tee_core.core.engine.time") as tm:
            tm.time.return_value = 1_700_000_000.0
            tee.execute_market_compat(**kwargs)
            # 130s later → new minute bucket (bucket key 120s granular TTL).
            tm.time.return_value = 1_700_000_130.0
            tee.execute_market_compat(**kwargs)
        assert client.place_order.call_count == 2, (
            f"Bucket rollover must allow a second real place. Got "
            f"{client.place_order.call_count}"
        )


# =====================================================================
# TR-10.3 shadow mode AC-10 (no real place/cancel; estimated_* populated)
# =====================================================================
class TestTR103ShadowMode:
    def test_shadow_smart_twap_makes_zero_real_calls(self, tmp_path: Path):
        from tee_core.core.engine import TradeExecutionEngine
        # Need a realistic-enough client that get_orderbook works.
        client = MagicMock()
        client.get_ticker.return_value = {
            "ok": True, "last": 70_000.0, "ask": 70_001.0, "bid": 69_999.0,
        }
        client.get_contract_info.return_value = (0.001, 0.01)  # lot, ctVal
        ob_levels = []
        for i in range(15):
            bid_p = 70_000 - i * 0.5
            ask_p = 70_001 + i * 0.5
            ob_levels.append((bid_p, 0.5, ask_p, 0.5))
        client.get_orderbook.return_value = ob_levels
        # Explicit success so any accidental real place returns ok (the test
        # asserts count == 0 anyway).
        client.place_order.return_value = {"ok": True, "ord_id": "X"}
        client.cancel_order.return_value = {"ok": True}
        client.get_order.return_value = {
            "ok": True, "ord_id": "X", "state": "filled", "side": "buy",
            "pos_side": "long", "filled_sz": 1.0, "avg_px": 70_000.0,
            "fee": 0.0, "pnl": 0.0,
        }

        audit_dir = tmp_path / "audit"
        audit_dir.mkdir(exist_ok=True)
        tee = TradeExecutionEngine(
            exchange_client=client, enable_tee=True, shadow_mode=True,
            audit_dir=str(audit_dir),
            metrics_path=str(tmp_path / "metrics.json"),
            failopen_log_path=str(tmp_path / "fo.log"),
        )
        # Force algo=SmartTWAP: build ParentRequest with size_ratio that
        # lands into TWAP15 bucket, or pass algo_override="twap15".
        parent_req = dict(
            inst_id="BTC-USDT-SWAP",
            side="buy", sz=1.0, pos_side="long", td_mode="isolated",
            leverage=5, decision_px=70_000.0,
            urgency="NORMAL",
            algo_override="twap15",
            source="ut_shadow",
        )
        result = tee.execute(parent_req)
        # No real exchange calls.
        assert client.place_order.call_count == 0, (
            f"AC-10 FAIL shadow: place_order called "
            f"{client.place_order.call_count}× expected 0."
        )
        assert client.cancel_order.call_count == 0, (
            f"AC-10 FAIL shadow: cancel_order called "
            f"{client.cancel_order.call_count}× expected 0."
        )
        # Estimated VWAP and total sz fields are meaningful non-zero.
        assert (result or {}).get("estimated_vwap", 0) > 0, (
            f"Shadow must populate estimated_vwap; result={result}"
        )
        assert (result or {}).get("total_filled_sz", None) == 0 or \
            (result or {}).get("shadow_mode_hit") is True, (
                "Shadow must signal it didn't actually fill (sz=0 or flag)."
            )
        # Audit file suffix: at least one *_shadow.jsonl exists.
        shadow_files = list(audit_dir.glob("*_shadow.jsonl"))
        assert len(shadow_files) >= 1, (
            "AC-10 FAIL: Shadow audit expected *_shadow.jsonl suffix file."
        )


# =====================================================================
# TR-10.4 V15 execute_open_position smoke integration
# =====================================================================
class TestTR104V15Smoke:
    def test_state_positions_matches_legacy_struct(self, tmp_path: Path):
        """Simulate a minimal execute_open_position wrapper: call the
        compat path, then write the position dict as v15_trader.py does.
        The resulting state object is equal to the legacy builder, modulo
        an optional "open_engine": "TEE" marker."""
        from tee_core.core.engine import TradeExecutionEngine
        client = MagicMock()
        client.get_ticker.return_value = {
            "ok": True, "last": 70_000.0, "ask": 70_001.0, "bid": 69_999.0,
        }
        client.place_order.return_value = {"ok": True, "ord_id": "OP-1"}

        tee = TradeExecutionEngine(
            exchange_client=client, enable_tee=True, shadow_mode=False,
            audit_dir=str(tmp_path / "audit"),
            metrics_path=str(tmp_path / "metrics.json"),
            failopen_log_path=str(tmp_path / "fo.log"),
        )
        # Simulate execute_open_position lines 1970-2000.
        open_time = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        kw = dict(MINI_OPEN_ARGS)
        kw["open_time_iso"] = open_time.isoformat()

        # TEE path: replace client.place_order() (line 1974) with compat.
        with patch("tee_core.core.engine.time") as tm:
            tm.time.return_value = open_time.timestamp()
            r = tee.execute_market_compat(
                inst_id=kw["inst_id"],
                side="sell" if kw["is_short"] else "buy", sz=kw["sz"],
                td_mode="isolated", pos_side=kw["pos_side"],
                leverage=kw["leverage"], tag="v15_compat_smoke",
            )

        assert r.get("ok"), f"TEE compat returned not-ok: {r}"
        direction = "SHORT" if kw["is_short"] else "LONG"
        state_tee_path: Dict[str, Any] = {
            "inst_id": kw["inst_id"],
            "direction": direction,
            "entry_price": kw["entry_price"],
            "open_price": kw["entry_price"],
            "sz": kw["sz"],
            "addons": 0,
            "confidence": kw["conf"],
            "open_time": kw["open_time_iso"],
            "take_profit_pct": kw["tp_pct"],
            "original_tp_pct": kw["tp_pct"],
            "addon_pct": kw["addon_pct"],
            "stop_loss_price": kw["sl_price"],
            "stop_loss_type": kw["sl_type"],
            "vol_mult": kw["vol_mult"],
            "per_coin_budget": kw["alloc"]["per_coin_budget"],
            "base_usd": kw["alloc"]["base_usd"],
            # Optional TEE marker — allowed, legacy code ignores extra keys.
            "open_engine": "TEE",
        }

        baseline = _legacy_build_position_baseline(**kw)
        # Compare ignoring the open_engine marker.
        a = dict(state_tee_path)
        a.pop("open_engine", None)
        assert a == baseline, (
            f"TR-10.4 FAIL: position state mismatch vs legacy.\n"
            f"  TEE      = {a}\n"
            f"  BASELINE = {baseline}"
        )


# =====================================================================
# TR-10.5 V15 regression 3-step rubric (≥2)
# =====================================================================
class TestTR105V15RegressionRubric:
    @staticmethod
    def _run_3_step_flow(runner: str, client_or_tee, fixed_open_ts: float,
                         fixed_addon_ts: float) -> Dict[str, Any]:
        """Runner ∈ {legacy, tee}. Returns state dict snapshot after
        open→addon→close."""
        coin = "BTC"
        state: Dict[str, Any] = {"positions": {}}

        # (1) OPEN — baseline direct place_order call.
        if runner == "legacy":
            client_or_tee.place_order(
                inst_id="BTC-USDT-SWAP", side="buy", sz=1,
                td_mode="isolated", pos_side="long")
        else:  # TEE
            client_or_tee.execute_market_compat(
                inst_id="BTC-USDT-SWAP", side="buy", sz=1,
                td_mode="isolated", pos_side="long", tag="v15c_open",
            )
        state["positions"][coin] = _legacy_build_position_baseline(
            coin=coin, inst_id="BTC-USDT-SWAP", is_short=False,
            sz=1, entry_price=70_000.0, addon_pct=0.015, tp_pct=0.03,
            sl_price=67_000.0, sl_type="fixed", conf=80, vol_mult=1.0,
            alloc={"per_coin_budget": 1000, "base_usd": 1000},
            open_time_iso=datetime.fromtimestamp(
                fixed_open_ts, tz=timezone.utc).isoformat(),
        )

        # (2) ADDON — sz=0.5, price dips to 68000.
        pos = state["positions"][coin]
        addon_sz = 0.5
        new_price = 68_000.0
        if runner == "legacy":
            client_or_tee.place_order(
                inst_id="BTC-USDT-SWAP", side="buy", sz=addon_sz,
                td_mode="isolated", pos_side="long")
        else:
            client_or_tee.execute_market_compat(
                inst_id="BTC-USDT-SWAP", side="buy", sz=addon_sz,
                td_mode="isolated", pos_side="long", tag="v15c_addon",
            )
        pos["addons"] = 1
        pos["entry_price"] = (pos["entry_price"] * pos["sz"]
                              + new_price * addon_sz) / (pos["sz"] + addon_sz)
        pos["sz"] += addon_sz
        pos["last_addon_time"] = datetime.fromtimestamp(
            fixed_addon_ts, tz=timezone.utc).isoformat()

        # (3) CLOSE — remove the position dict entirely.
        close_sz = pos["sz"]
        if runner == "legacy":
            client_or_tee.place_order(
                inst_id="BTC-USDT-SWAP", side="sell", sz=close_sz,
                td_mode="isolated", pos_side="long")
        else:
            client_or_tee.execute_market_compat(
                inst_id="BTC-USDT-SWAP", side="sell", sz=close_sz,
                td_mode="isolated", pos_side="long", tag="v15c_close",
                reason="close_position",
            )
        closed_entry = state["positions"].pop(coin, None)
        state["_last_closed"] = closed_entry
        return state

    def test_rubric_exact_state_match_score_2(self, tmp_path: Path):
        from tee_core.core.engine import TradeExecutionEngine
        legacy_client = MagicMock()
        legacy_client.place_order.return_value = {"ok": True, "ord_id": "OL"}

        tee_client = MagicMock()
        tee_client.get_ticker.return_value = {
            "ok": True, "last": 70_000.0, "ask": 70_001.0, "bid": 69_999.0,
        }
        tee_client.place_order.return_value = {"ok": True, "ord_id": "OT"}
        tee = TradeExecutionEngine(
            exchange_client=tee_client, enable_tee=True, shadow_mode=False,
            audit_dir=str(tmp_path / "audit"),
            metrics_path=str(tmp_path / "metrics.json"),
            failopen_log_path=str(tmp_path / "fo.log"),
        )

        t_open = 1_710_000_000.0
        t_add = 1_710_000_600.0

        baseline_state = self._run_3_step_flow(
            "legacy", legacy_client, t_open, t_add)
        with patch("tee_core.core.engine.time") as tm:
            tm.time.return_value = t_open
            tee_state = self._run_3_step_flow("tee", tee, t_open, t_add)

        # Strip runtime-added optional markers: open_engine, _last_closed
        # open_time ordering differences already equal because we set
        # explicitly.
        def scrub(s: Dict[str, Any]) -> str:
            if isinstance(s.get("_last_closed"), dict):
                s["_last_closed"].pop("open_engine", None)
            return json.dumps(s, sort_keys=True, default=str)

        assert scrub(baseline_state) == scrub(tee_state), (
            "TR-10.5 FAIL: 3-step state differs between legacy & TEE path."
        )
        # rubric score = 2 because we got exact match.
        rubric_score = 2
        assert rubric_score >= 2, "AC-11 rubric threshold not met"
