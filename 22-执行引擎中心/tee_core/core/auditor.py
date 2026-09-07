"""Auditor: per-parent JSONL lines + rolling metrics flushed periodically.

Public API:
    aud = Auditor(audit_dir=..., metrics_path=..., flush_interval_sec=60)
    status = aud.record_parent(execution_result_dict)
      → "OK_WRITTEN" or "DUPLICATE_PARENT_ID_IGNORED"
    aud.flush_metrics(force=False) → writes metrics JSON if due / forced.

Each record_parent() does:
  1. De-duplicate by ``execution["parent"]["parent_id"]`` (memory set).
  2. If new: append a JSONL line to ``<audit_dir>/<UTC date>.jsonl``.
  3. Accumulate into in-memory rolling counters.
  4. Maybe flush metrics if ``(now - last_flush) >= flush_interval``.

Fail-safe: all I/O errors are swallowed. The caller should never raise
because of auditor problems.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from . import config as _cfg


# Status strings — tests assert on them.
STATUS_OK_WRITTEN = "OK_WRITTEN"
STATUS_DUP_IGNORED = "DUPLICATE_PARENT_ID_IGNORED"
STATUS_ERROR = "ERROR_SWALLOWED"


class RollingMetrics:
    """In-memory accumulators. Reset on *manual* reset() only — otherwise
    they keep growing over the process lifetime, giving a 30-minute-ish
    "rolling" window (callers can reset via a cron if they want stricter
    windows). For the baseline rubric we just aggregate everything since
    process start, which is the most common case for a long-running
    trading poller."""

    __slots__ = (
        "total_parent_count",
        "_slip_improvement_bps_sum",
        "_slip_improvement_samples",
        "fail_open_count_per_coin",
        "algo_distribution_counts",
        "kill_switch_trigger_count",
    )

    def __init__(self) -> None:
        self.reset()

    # ── public ────────────────────────────────────────────────────────
    def reset(self) -> None:
        self.total_parent_count: int = 0
        self._slip_improvement_bps_sum: float = 0.0
        self._slip_improvement_samples: int = 0
        self.fail_open_count_per_coin: Dict[str, int] = {}
        self.algo_distribution_counts: Dict[str, int] = {}
        self.kill_switch_trigger_count: int = 0

    def accumulate(self, exec_result: Dict[str, Any]) -> None:
        # Parent tally.
        self.total_parent_count += 1

        # Slip improvement: baseline(direct_market) - tee(actual).
        # Skip if either value is missing/NaN.
        try:
            exec_block = exec_result.get("exec") or {}
            tee_bps = float(exec_block.get("slippage_bps_vs_decision"))
            dm_bps = float(exec_block.get("baseline_direct_market_slippage_bps"))
            if all(v is not None for v in (tee_bps, dm_bps)):
                self._slip_improvement_bps_sum += (dm_bps - tee_bps)
                self._slip_improvement_samples += 1
        except (TypeError, ValueError):
            pass

        # Algo counts.
        try:
            algo = str((exec_result.get("algo") or {}).get("name") or "UNKNOWN")
            self.algo_distribution_counts[algo] = (
                self.algo_distribution_counts.get(algo, 0) + 1
            )
        except Exception:  # noqa: BLE001
            pass

        # Fail-open per coin.
        try:
            if (exec_result.get("fail_open") or {}).get("triggered"):
                inst = str((exec_result.get("parent") or {}).get("inst_id") or "UNKNOWN")
                self.fail_open_count_per_coin[inst] = (
                    self.fail_open_count_per_coin.get(inst, 0) + 1
                )
        except Exception:  # noqa: BLE001
            pass

        # Kill switch tally.
        try:
            if (exec_result.get("kill_switch") or {}).get("runtime_triggered"):
                self.kill_switch_trigger_count += 1
        except Exception:  # noqa: BLE001
            pass

    def snapshot(self) -> Dict[str, Any]:
        samples = self._slip_improvement_samples
        avg = (self._slip_improvement_bps_sum / samples) if samples else 0.0
        now = time.time()
        return {
            "total_parent_count": self.total_parent_count,
            "avg_slip_improvement_baseline_direct_market_bps": round(avg, 6),
            "slip_improvement_sample_count": samples,
            "fail_open_count_per_coin": dict(self.fail_open_count_per_coin),
            "algo_distribution_counts":    dict(self.algo_distribution_counts),
            "kill_switch_trigger_count":    self.kill_switch_trigger_count,
            "flushed_at_epoch_ms":          int(now * 1000),
            "flushed_at_iso":               datetime.fromtimestamp(
                                                now, tz=timezone.utc
                                            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window": "process_lifetime_rolling",
        }


class Auditor:
    """JSONL per-parent auditable trail + rolling metrics."""

    def __init__(
        self,
        audit_dir: Optional[os.PathLike | str] = None,
        metrics_path: Optional[os.PathLike | str] = None,
        flush_interval_sec: int = _cfg.METRICS_FLUSH_INTERVAL_SEC,
        dedup_capacity: int = 20000,
    ) -> None:
        self.audit_dir: Path = (
            Path(audit_dir) if audit_dir else Path(_cfg.AUDIT_LOG_DIR)
        )
        self.metrics_path: Path = (
            Path(metrics_path) if metrics_path else Path(_cfg.METRICS_JSON_PATH)
        )
        self.flush_interval_sec: int = int(max(1, flush_interval_sec))
        self._dedup_capacity = int(max(1, dedup_capacity))

        # Runtime state.
        self._metrics = RollingMetrics()
        self._seen_parent_ids: set = set()
        self._last_flush_ts: float = 0.0
        self._lock = threading.Lock()

        # Create dirs on init (best-effort).
        try:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass

    # ── public API ────────────────────────────────────────────────────
    def record_parent(self, exec_result: Dict[str, Any]) -> str:
        """Record one parent execution result. Returns status string."""
        try:
            parent_block = exec_result.get("parent") or {}
            parent_id = str(parent_block.get("parent_id") or "").strip()
            if not parent_id:
                return STATUS_ERROR + "_MISSING_PARENT_ID"

            with self._lock:
                if parent_id in self._seen_parent_ids:
                    return STATUS_DUP_IGNORED

                # 1) write JSONL
                self._append_jsonl_locked(exec_result)

                # 2) metrics accumulate
                self._metrics.accumulate(exec_result)

                # 3) remember for dedup; prune FIFO-ish if cap exceeded.
                self._seen_parent_ids.add(parent_id)
                if len(self._seen_parent_ids) > self._dedup_capacity:
                    # Drop oldest ~25% — simple. order preservation is not
                    # required; set pop gives arbitrary element.
                    overflow = len(self._seen_parent_ids) - int(
                        self._dedup_capacity * 0.75
                    )
                    to_del = list(self._seen_parent_ids)[:overflow]
                    for x in to_del:
                        self._seen_parent_ids.discard(x)

                # 4) maybe flush metrics
                self._flush_metrics_locked(force=False)
            return STATUS_OK_WRITTEN
        except Exception:  # noqa: BLE001 — fail-safe swallow
            return STATUS_ERROR

    def flush_metrics(self, force: bool = False) -> bool:
        """External flush hook. Returns True if metrics JSON actually
        rewritten (either force=True or interval elapsed)."""
        with self._lock:
            return self._flush_metrics_locked(force=force)

    # ── internals (caller must hold the lock) ─────────────────────────
    def _append_jsonl_locked(self, exec_result: Dict[str, Any]) -> None:
        try:
            day = self._utc_day_for_result(exec_result)
            target = self.audit_dir / f"{day}.jsonl"
            line = json.dumps(exec_result, ensure_ascii=False, default=str)
            with open(target, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass

    def _flush_metrics_locked(self, force: bool) -> bool:
        now = time.time()
        if not force and (now - self._last_flush_ts) < self.flush_interval_sec:
            return False
        snap = self._metrics.snapshot()
        try:
            tmp = self.metrics_path.with_suffix(self.metrics_path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:  # noqa: BLE001
                    pass
            os.replace(tmp, self.metrics_path)
            self._last_flush_ts = now
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _utc_day_for_result(exec_result: Dict[str, Any]) -> str:
        ts_ms = exec_result.get("ts_epoch_ms")
        ts_s: float
        if isinstance(ts_ms, (int, float)) and ts_ms > 0:
            ts_s = float(ts_ms) / 1000.0
        else:
            ts_s = time.time()
        return datetime.fromtimestamp(ts_s, tz=timezone.utc).strftime("%Y-%m-%d")


__all__ = [
    "Auditor", "RollingMetrics",
    "STATUS_OK_WRITTEN", "STATUS_DUP_IGNORED", "STATUS_ERROR",
]
