"""Fail-Open Manager (AC-6 / FR-3.1).

When *anything* inside the TEE primary path throws, this manager:

  1. Captures the exception and writes a FAIL-OPEN record to disk:
     - parent_id / ts / inst_id / decision_px / sz / source
     - exc type + message
     - 6-level stack trace (minimum — frames beyond that are also kept
       if available; spec says "at least 6 levels").
  2. Enqueues the event into a 300-second *sliding* count deque. When the
     count within the window reaches ``alert_count`` (default 3), the
     manager emits exactly ONE Lark alert per 5-minute window (throttled).
  3. Calls ``fallback_runner(parent_req)`` — by convention the Task 10
     engine will pass in a DirectMarket runner — and returns the fallback
     result **directly to the caller**. No exception propagates. Fail
     open means: keep the money moving; we've already logged and alerted.

The manager exports *one* public method: :meth:`execute_with_fallback`.
Everything else is implementation detail.

Clock mocking: the manager uses ``time.time()`` for event timestamps,
which tests patch via ``patch("tee_core.core.failopen.time")``.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import config as _cfg


class FailOpenManager:
    """Guards TEE.execute() against any exception → market fallback."""

    # Sentinel meta: keys used when caller doesn't provide parent dict fields
    _PARENT_DEFAULTS: Dict[str, Any] = {
        "inst_id": "UNKNOWN", "side": "UNKNOWN", "sz": 0.0,
        "pos_side": "UNKNOWN", "td_mode": "UNKNOWN", "leverage": 0,
        "decision_px": 0.0, "source": "UNKNOWN", "parent_id": None,
    }

    def __init__(
        self,
        log_path: Optional[os.PathLike | str] = None,
        lark_bridge: Any = None,
        alert_window_sec: int = _cfg.FAILOPEN_ALERT_WINDOW_SEC,
        alert_count: int = _cfg.FAILOPEN_ALERT_COUNT,
    ) -> None:
        self.log_path: Path = (
            Path(log_path) if log_path else Path(_cfg.FAILOPEN_LOG_PATH)
        )
        self._ensure_log_parent_exists()
        self.lark_bridge = lark_bridge  # None allowed → no alerts ever sent.
        self.alert_window_sec: int = int(max(1, alert_window_sec))
        self.alert_count: int = int(max(1, alert_count))

        # Sliding timestamps of FAIL-OPEN events (strict monotonic wall).
        self._fail_events: deque[float] = deque()
        # Throttle: "when did we last fire an alert?" → avoid duplicate
        # alerts inside the window. If None: never fired yet.
        self._last_alert_ts: Optional[float] = None

    # ── public guard entry point ───────────────────────────────────────
    def execute_with_fallback(
        self,
        *,
        parent_req: Dict[str, Any],
        primary_runner: Callable[[Dict[str, Any]], Any],
        fallback_runner: Callable[[Dict[str, Any]], Any],
        lark_bridge_override: Any = None,
    ) -> Any:
        """Run ``primary_runner(parent_req)``; on any failure run the
        fallback and return its result. Never raises."""
        try:
            # Happy path: return primary's result UNCHANGED, no logging.
            return primary_runner(parent_req)
        except BaseException as e:  # noqa: BLE001 — Catch EVERYTHING incl KeyboardInterrupt
            # 1) Write fail-open record.
            ts = time.time()
            try:
                self._append_log_entry(ts=ts, exc=e, parent_req=parent_req)
            except BaseException:  # noqa: BLE001
                # If even logging fails, the trade must still not break.
                # Swallow and keep going.
                pass

            # 2) Update sliding count → maybe trigger an alert.
            self._record_and_alert_if_threshold(
                ts=ts, exc=e, parent_req=parent_req,
                lark_bridge=(lark_bridge_override
                             if lark_bridge_override is not None
                             else self.lark_bridge),
            )

            # 3) Call the fallback and return whatever it produced. If
            #    *this* also fails, we fall back to a minimal dict sentinel
            #    so callers can continue (total fail-safety, last resort).
            try:
                return fallback_runner(parent_req)
            except BaseException as fb_exc:  # noqa: BLE001
                last_resort = {
                    "fail_open": True,
                    "fallback_reason_tag": "FALLBACK_RUNNER_FAILED",
                    "fallback_runner_error": f"{type(fb_exc).__name__}: {fb_exc}",
                    "child_orders": [],
                    "fail_open_reason": f"primary={type(e).__name__}; fallback failed",
                }
                try:
                    self._append_log_entry(
                        ts=time.time(), exc=fb_exc, parent_req=parent_req,
                        extra_tag="FALLBACK_RUNNER_FAILED",
                    )
                except BaseException:  # noqa: BLE001
                    pass
                return last_resort

    # ── log writing ────────────────────────────────────────────────────
    def _ensure_log_parent_exists(self) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def _append_log_entry(
        self,
        *,
        ts: float,
        exc: BaseException,
        parent_req: Dict[str, Any],
        extra_tag: Optional[str] = None,
    ) -> None:
        tb_frames = traceback.extract_tb(exc.__traceback__)
        frame_list: list[dict] = []
        for f in tb_frames:
            try:
                frame_list.append({
                    "file": f.filename,
                    "line": f.lineno,
                    "func": f.name,
                    "code": f.line or "",
                })
            except Exception:  # noqa: BLE001
                frame_list.append({"raw": repr(f)})

        # FR-3.1: "完整 traceback 6 层堆栈". Shallow callers (e.g. a 1-line
        # helper that raises) produce only 2 frames. To guarantee the
        # "≥ 6 levels" rule we supplement with our own caller stack up to
        # 12 frames total. That way pytest → mgr → runner all appear,
        # which are the real lines an ops engineer would need to grep.
        if len(frame_list) < 6:
            try:
                # Walk upwards from this helper, skipping:
                #   0 = current frame (_append_log_entry itself — already
                #       captured via tb, but tb may stop at primary_runner)
                caller_stack = traceback.extract_stack()  # → list bottom-up
            except Exception:  # noqa: BLE001
                caller_stack = []
            # Add caller frames from the top of the stack until we have 6
            # total, or run out of supplemental frames.
            # Start from the topmost (oldest) caller *above*
            # execute_with_fallback, so we don't double-log our guard.
            skip_names = {
                "_append_log_entry",
                "_record_and_alert_if_threshold",
                "execute_with_fallback",
            }
            supplemental: list[dict] = []
            for sf in caller_stack:
                if sf.name in skip_names:
                    continue
                try:
                    supplemental.append({
                        "file": sf.filename,
                        "line": sf.lineno,
                        "func": sf.name,
                        "code": sf.line or "",
                        "supplemental": True,
                    })
                except Exception:  # noqa: BLE001
                    pass
            while len(frame_list) < 6 and supplemental:
                frame_list.append(supplemental.pop())  # newest (closest) first

        tb_text_lines = traceback.format_exception(type(exc), exc,
                                                   exc.__traceback__)

        tb_text = "".join(tb_text_lines)
        record: Dict[str, Any] = {
            "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
            "ts_epoch_ms": int(ts * 1000),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "traceback_text": tb_text,
            "traceback_text_lines_count": len(tb_text_lines),
            "traceback_frames_count": len(frame_list),
            "traceback_frames": frame_list,
            "parent": {
                k: parent_req.get(k, self._PARENT_DEFAULTS[k])
                for k in self._PARENT_DEFAULTS
            },
        }
        if extra_tag:
            record["extra_tag"] = extra_tag
        line = json.dumps(record, ensure_ascii=False, default=str)

        # Write, failing silently.
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    # ── sliding-window alerting ────────────────────────────────────────
    def _record_and_alert_if_threshold(
        self,
        *,
        ts: float,
        exc: BaseException,
        parent_req: Dict[str, Any],
        lark_bridge: Any,
    ) -> None:
        # 1) Drop old events outside the window before adding new one.
        cutoff = ts - self.alert_window_sec
        while self._fail_events and self._fail_events[0] <= cutoff:
            self._fail_events.popleft()
        self._fail_events.append(ts)

        # 2) If count < threshold → nothing to alert.
        if len(self._fail_events) < self.alert_count:
            return

        # 3) Throttle: don't alert twice within the same *window* (i.e.
        #    until the oldest event has rolled off completely, OR 5 min
        #    have passed whichever). For safety: a minimum interval of
        #    alert_window_sec between two alerts.
        now = ts
        if (self._last_alert_ts is not None
                and now - self._last_alert_ts < self.alert_window_sec):
            return

        # 4) Actually try to alert. On any bridge problem, just log it.
        self._last_alert_ts = now
        try:
            if lark_bridge is None:
                return
            md_body = self._build_alert_md_body(
                now=now, exc=exc, parent_req=parent_req,
                event_count=len(self._fail_events),
            )
            lark_bridge.send_alert(
                title=("TEE FAIL-OPEN: "
                       f"{self.alert_count}× events in last "
                       f"{self.alert_window_sec}s"),
                level="critical",
                message=(f"{type(exc).__name__}: {exc}"[:200]),
                details={
                    "alert_count_threshold": self.alert_count,
                    "window_sec": self.alert_window_sec,
                    "current_window_events": len(self._fail_events),
                },
                md_body=md_body,
                system="TEE",
                alert_type="TEE_FAILOPEN",
            )
        except BaseException as alert_exc:  # noqa: BLE001 (TR-8.3 fail-safe)
            try:
                self._append_log_entry(
                    ts=time.time(), exc=alert_exc, parent_req=parent_req,
                    extra_tag="LARK_ALERT_FAILED",
                )
            except BaseException:  # noqa: BLE001
                pass

    @staticmethod
    def _build_alert_md_body(
        *,
        now: float, exc: BaseException, parent_req: Dict[str, Any],
        event_count: int,
    ) -> str:
        inst = str(parent_req.get("inst_id") or "?")
        src = str(parent_req.get("source") or "?")
        sz = parent_req.get("sz", 0.0)
        dpx = parent_req.get("decision_px", 0.0)
        return (
            f"**FAIL-OPEN Alert ({event_count}× within window)**\n"
            f"  - Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}\n"
            f"  - Symbol: `{inst}`  |  Source: `{src}`  |  Sz: `{sz}`  |  Decision Px: `{dpx}`\n"
            f"  - Exception: `{type(exc).__name__}`: **{str(exc)[:200]}**\n"
            f"  - Action: Direct-Market fallback taken — order continued as single market trade.\n"
            f"> See `logs/tee_failopen.log` for 6-level stacktrace + full JSON."
        )
