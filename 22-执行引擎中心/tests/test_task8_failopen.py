"""Task 8 RED → GREEN tests — FailOpenManager + Lark alert throttle.

Behaviour under test (AC-6 / FR-3.1):
  TR-8.1 Any internal exception thrown inside TEE.execute():
      → *no* exception propagates. The engine instead:
        - writes 6-level stacktrace + meta to FAILOPEN_LOG_PATH
        - falls back to a SINGLE DirectMarket place_order (market order for
          the original parent sz)
        - returns ExecutionResult with fail_open_reason="ORDERBOOK_TIMEOUT"
          (or a similar short tag for the specific failure cause).
      We test this against an injected "mini execute stub" inside
      FailOpenManager.guard() because the full TEE.execute() class is
      Task-10. Here the manager only provides the guard decorator /
      wrapper function. (Same semantics.)

  TR-8.2 300s sliding window: 3 FAIL-OPENs → send_lark_alert() exactly once.
      A 4th event within the same window does NOT re-trigger (throttled:
      at most one alert per 5 min). When the window advances past the
      first event, a fresh 3-count triggers again.

  TR-8.3 If the Feishu bridge itself explodes (network error), the main
      trading path must NOT propagate; the alert error is logged to the
      same failopen.log and the guard still returns a DirectMarket-style
      fallback result (fail_safe even on failure to alert).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "22-执行引擎中心"))


# =====================================================================
# Helpers & fixtures
# =====================================================================
@pytest.fixture
def temp_log(tmp_path: Path) -> Path:
    log = tmp_path / "tee_failopen.log"
    return log


@pytest.fixture
def lark_bridge_mock_ok() -> MagicMock:
    m = MagicMock()
    m.send_alert.return_value = "msg-id-fake-0001"
    return m


def _dummy_failing_agent(parent_req: Dict[str, Any]) -> None:
    """Always raises TimeoutError as if the orderbook endpoint died."""
    raise TimeoutError("GET /api/v5/market/books: 504 Gateway Timeout")


def _dummy_ok_agent(parent_req: Dict[str, Any]) -> str:
    return f"all-good sz={parent_req['sz']}"


# =====================================================================
# TR-8.1 (=AC-6) Single failure → no propagate, write log, market fallback
# =====================================================================
class TestTR81FailOpenGuards:
    def test_exception_does_not_propagate_and_returns_fallback_result(self, temp_log):
        """Core guard contract: returns result with fail_open_reason set,
        no exception ever leaves FailOpenManager.execute_with_fallback()."""
        from tee_core.core.failopen import FailOpenManager
        mgr = FailOpenManager(log_path=str(temp_log),
                              lark_bridge=None,
                              alert_window_sec=300, alert_count=3)
        parent_req = dict(inst_id="BTC-USDT-SWAP", side="buy", sz=0.5,
                          pos_side="long", td_mode="isolated", leverage=5.0,
                          decision_px=70000.0, source="ut_f81")

        result = mgr.execute_with_fallback(
            parent_req=parent_req,
            primary_runner=_dummy_failing_agent,
            fallback_runner=lambda pr: {
                "algo": "direct_market_fallback",
                "child_orders": [{"ord_id": "FB-1", "sz_filled": 0.5}],
                "fallback_reason_tag": "ORDERBOOK_TIMEOUT",
            },
        )
        # Never raised — returns dict with fallback flag set
        assert isinstance(result, dict), (
            f"expected dict fallback result, got {type(result)}"
        )
        assert result.get("fallback_reason_tag") == "ORDERBOOK_TIMEOUT", (
            f"Expected tag ORDERBOOK_TIMEOUT, got {result.get('fallback_reason_tag')}"
        )

    def test_failopen_log_contains_6level_traceback(self, temp_log):
        """Must write a log line with ≥ 6 stack frames (FR-3.1: "完整
        traceback 6 层堆栈")"""
        from tee_core.core.failopen import FailOpenManager
        mgr = FailOpenManager(log_path=str(temp_log), lark_bridge=None)
        parent_req = dict(sz=0.1, inst_id="SOL", decision_px=100.0,
                          side="sell", pos_side="short", td_mode="isolated",
                          leverage=5, source="ut")
        mgr.execute_with_fallback(
            parent_req=parent_req,
            primary_runner=_dummy_failing_agent,
            fallback_runner=lambda pr: {"ok_fallback": True,
                                        "fallback_reason_tag": "FO"},
        )
        text = temp_log.read_text(encoding="utf-8")
        assert len(text) > 50, "failopen.log should not be empty after FO event"
        # FR-3.1 contract: at least 6 stack levels present.
        # Manager writes JSON; parse the single line and check the
        # dedicated count fields rather than doing fragile string matches
        # on JSON-escaped quote characters.
        rec = json.loads(text.strip().splitlines()[-1])
        structured_count = int(rec.get("traceback_frames_count", 0))
        raw_lines = int(rec.get("traceback_text_lines_count", 0))
        # Either the structured frame list OR the raw traceback text
        # containing 6+ lines with "File " markers is sufficient.
        frame_markers_in_raw = rec.get("traceback_text", "").count('File "')
        assert structured_count >= 6 or frame_markers_in_raw >= 6, (
            f"Expected ≥ 6 stack levels in failopen log. "
            f"structured_frames={structured_count}, raw_File-markers="
            f"{frame_markers_in_raw}, raw_lines={raw_lines}. "
            f"Record keys: {sorted(rec.keys())}"
        )
        # Also expect meta (parent_id / decision_px / sz) and error class.
        assert "TimeoutError" in text
        assert "ORDERBOOK_TIMEOUT" not in text  # → result not in log; log has stack

    def test_happy_path_no_log_written(self, temp_log):
        """If primary_runner succeeds → no log entry (no spurious noise)."""
        from tee_core.core.failopen import FailOpenManager
        mgr = FailOpenManager(log_path=str(temp_log), lark_bridge=None)
        parent_req = dict(sz=1.0, inst_id="BTC", decision_px=100.0,
                          side="buy", pos_side="long", td_mode="isolated",
                          leverage=5, source="ut")
        res = mgr.execute_with_fallback(
            parent_req=parent_req,
            primary_runner=_dummy_ok_agent,
            fallback_runner=lambda pr: {"fallback": True,
                                        "fallback_reason_tag": "NONE"},
        )
        # Success → primary's return value is passed through as-is.
        assert isinstance(res, str) and res.startswith("all-good sz=1.0")
        # Log either doesn't exist OR is empty.
        if temp_log.exists():
            assert temp_log.read_text(encoding="utf-8") == "", (
                "Successful primary must not write failopen log."
            )


# =====================================================================
# TR-8.2 Sliding window: 3 events → ONE lark alert; throttled on 4th;
#                       window rollover triggers again later.
# =====================================================================
class TestTR82SlidingWindowAlert:
    @staticmethod
    def _fail(mgr, bridge, n_times: int, start_ts: float,
              gap_sec: float) -> None:
        for i in range(n_times):
            # Patch time.time inside the manager to advance by i*gap
            fake_now = start_ts + i * gap_sec
            parent_req = dict(sz=0.1, inst_id="BTC", decision_px=100.0,
                              side="buy", pos_side="long",
                              td_mode="isolated", leverage=5,
                              source=f"ut_loop_{i}")

            def blow_up(*a, **kw):
                raise RuntimeError(f"boom #{i}")

            with patch("tee_core.core.failopen.time") as tm:
                tm.time.return_value = fake_now
                # Manager uses traceback/time module; use patched current
                # time via mgr's guard that accepts our explicit timestamps
                # if present, else falls back to time.time() — we patch the
                # wall clock inside failopen module so the deque entries
                # have the intended ts.
                mgr.execute_with_fallback(
                    parent_req=parent_req,
                    primary_runner=blow_up,
                    fallback_runner=lambda pr, i=i: {
                        "fallback": True,
                        "fallback_reason_tag": f"BOOM_{i}",
                    },
                    lark_bridge_override=bridge,
                )

    def test_3_events_within_300s_send_alert_exactly_once(self, temp_log,
                                                           lark_bridge_mock_ok):
        """3 FAIL-OPENs spaced by 60 seconds (all within 300s window) →
        bridge.send_alert() called once and only once."""
        from tee_core.core.failopen import FailOpenManager
        bridge = lark_bridge_mock_ok
        mgr = FailOpenManager(log_path=str(temp_log),
                              lark_bridge=bridge,
                              alert_window_sec=300, alert_count=3)
        self._fail(mgr, bridge, n_times=3, start_ts=1_700_000_000.0, gap_sec=60.0)
        assert bridge.send_alert.call_count == 1, (
            f"Expected 1 alert after 3 FOs, got {bridge.send_alert.call_count}"
        )
        # Alert payload should mention the 3-count threshold and TEE context
        call_kwargs = bridge.send_alert.call_args.kwargs
        title = call_kwargs.get("title") or ""
        body = call_kwargs.get("md_body") or ""
        assert any("FAIL" in x for x in [title, body]), (
            f"Alert seems unrelated: title='{title}'"
        )

    def test_4th_event_within_window_does_not_retrigger_alert(
            self, temp_log, lark_bridge_mock_ok):
        """After the initial 3→alert, a 4th at t=240s (still within 300s
        window) must NOT send a 2nd alert (throttle/de-dup)."""
        from tee_core.core.failopen import FailOpenManager
        bridge = lark_bridge_mock_ok
        mgr = FailOpenManager(log_path=str(temp_log),
                              lark_bridge=bridge,
                              alert_window_sec=300, alert_count=3)
        self._fail(mgr, bridge, n_times=4, start_ts=1_700_000_000.0, gap_sec=60.0)
        # t=0, 60, 120, 180 all within 300s window of first event (0..300).
        assert bridge.send_alert.call_count == 1, (
            f"Expected 1 throttled alert, got {bridge.send_alert.call_count}"
        )

    def test_window_rollover_fires_again_after_300s(
            self, temp_log, lark_bridge_mock_ok):
        """After 3+ alerts at t=0,60,120… wait until t=400 then two more at
        t=400, 420, 440 → 3 newest (400, 420, 440) are all > 300s from first.
        So we should fire a 2nd alert."""
        from tee_core.core.failopen import FailOpenManager
        bridge = lark_bridge_mock_ok
        mgr = FailOpenManager(log_path=str(temp_log),
                              lark_bridge=bridge,
                              alert_window_sec=300, alert_count=3)

        # First batch (t=0/60/120) → 1 alert. last_alert_ts=120 within patch.
        self._fail(mgr, bridge, n_times=3, start_ts=1_700_000_000.0, gap_sec=60.0)
        first_alert_count = bridge.send_alert.call_count
        assert first_alert_count == 1

        # Produce 3 more events spaced 1s each, starting at +450s.
        # last_alert_ts was recorded inside the patch at patched "now"=120s.
        # With this spacing, first event ts = 450 → 450 - 120 = 330s > 300s
        # throttle window. 3rd event (452s) still satisfies count≥3, so a
        # fresh 2nd alert fires.
        for i in range(3):
            fake_now = 1_700_000_450 + i
            parent_req = dict(sz=0.1, inst_id="ETH", decision_px=3000.0,
                              side="buy", pos_side="long",
                              td_mode="isolated", leverage=5,
                              source=f"ut_batch2_{i}")

            def blow_up(*a, **kw): raise RuntimeError(f"boom-b2-{i}")

            with patch("tee_core.core.failopen.time") as tm:
                tm.time.return_value = fake_now
                mgr.execute_with_fallback(
                    parent_req=parent_req, primary_runner=blow_up,
                    fallback_runner=lambda pr, i=i: {"fallback": True,
                                                     "fallback_reason_tag": "B2"},
                    lark_bridge_override=bridge,
                )

        assert bridge.send_alert.call_count == 2, (
            "After window rollover, second group of 3 FOs must fire a "
            f"second alert. Calls = {bridge.send_alert.call_count}"
        )


# =====================================================================
# TR-8.3 Alert bridge failure must NOT break execution (fail_safe)
# =====================================================================
class TestTR83AlertFailureFailSafe:
    def test_lark_bridge_raise_is_swallowed_and_logged(self, temp_log):
        """send_alert() raises ConnectionError — the manager must still
        return a fallback result without raising. Extra error line should
        appear in failopen.log."""
        from tee_core.core.failopen import FailOpenManager
        broken = MagicMock()
        broken.send_alert.side_effect = ConnectionError(
            "feishu: DNS failure for open.feishu.cn"
        )
        mgr = FailOpenManager(log_path=str(temp_log),
                              lark_bridge=broken,
                              alert_window_sec=60, alert_count=1)
        # Trigger 1 FO (window=60, count=1 → bridge called immediately)
        # → broken.send_alert.raise. We still must not propagate.
        parent_req = dict(sz=0.02, inst_id="DOGE", decision_px=0.5,
                          side="buy", pos_side="long", td_mode="isolated",
                          leverage=5, source="ut_broken_alert")

        def boom(*a, **kw): raise RuntimeError("fire-alert-exception-test")

        # We need time.time patched to an increasing clock so 1st entry
        # triggers an alert at count=1 exactly.
        result: Any = None
        with patch("tee_core.core.failopen.time") as tm:
            tm.time.side_effect = [100.0, 100.0, 100.0]  # enqueue, write, alert
            raised = True
            try:
                result = mgr.execute_with_fallback(
                    parent_req=parent_req, primary_runner=boom,
                    fallback_runner=lambda pr: {"fallback": True,
                                                "fallback_reason_tag": "ALERT_ERR"},
                    lark_bridge_override=broken,
                )
                raised = False
            except Exception as e:
                # Test will fail — we want to guarantee raised=False.
                pytest.fail(f"FailOpenManager propagated: {type(e).__name__}: {e}")

        assert raised is False
        assert result is not None
        assert result.get("fallback_reason_tag") == "ALERT_ERR"
        # The alert error + traceback must be appended to failopen.log.
        text = temp_log.read_text(encoding="utf-8") if temp_log.exists() else ""
        assert "ConnectionError" in text and "DNS failure" in text, (
            "Alert-call failure must still be written to failopen.log. "
            f"Log content:\n{text[-1200:]}"
        )
