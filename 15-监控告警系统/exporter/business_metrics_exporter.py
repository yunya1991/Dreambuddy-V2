#!/usr/bin/env python3
"""DreamBuddy 业务指标导出器（只读，:9101）。

一期聚焦 23 推理信号链：
  - 信号产出/静默/置信度分布/契约完整率
  - 发件箱状态（SQLite 只读）
  - 产物新鲜度（monitoring.yaml artifacts）
  - entry23 期望模式 vs 实际模式
  - entry23/exit23 存活、22 账本与 SL/TP 补挂（TD §13.8）
  - 3+3 单元格成熟度（domains.yaml）

不写任何业务文件，不触发交易动作。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config/monitoring.yaml"
DEFAULT_DOMAINS = Path(__file__).resolve().parent.parent / "config/domains.yaml"
METRIC_PREFIX = "dreambuddy_"
MATURITY = {"M0": 0, "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5}
_cache = {"text": "", "ts": 0.0, "lock": threading.Lock()}
_provider = None


def _now() -> float:
    return time.time()


def _iso_to_ts(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _tail_jsonl(path: Path, limit: int = 500) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, 512 * 1024)
            fh.seek(size - block)
            chunk = fh.read().decode("utf-8", errors="ignore")
        for line in chunk.splitlines()[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return rows


def _iter_jsonl_since(path: Path, cutoff_ts: float, stages: tuple[str, ...] = ()) -> Iterator[dict]:
    """流式读取 JSONL 并按 ts 过滤（替代 _tail_jsonl 的 512KB 截断，覆盖完整窗口）。

    _tail_jsonl 只读文件尾部 512KB（≈3000 行），24h 指标会被压成几分钟窗口，
    导致 r_reflexivity_distinct_24h 恒为 1（ReflexivityConstant 误报）。
    """
    if not path.exists():
        return
    markers = tuple(f'"{s}"' for s in stages)
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if markers and not any(m in line for m in markers):
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if stages and str(rec.get("stage") or "") not in stages:
                    continue
                if _iso_to_ts(str(rec.get("ts") or "")) < cutoff_ts:
                    continue
                yield rec
    except OSError:
        return


def _signal_of(rec: dict) -> dict:
    for key in ("decision", "signal"):
        if isinstance(rec.get(key), dict):
            return rec[key]
    return rec


def _metric(name: str, value: float, **labels: str) -> str:
    tag = ",".join(f'{k}="{v}"' for k, v in labels.items())
    suffix = f"{{{tag}}}" if tag else ""
    return f"{METRIC_PREFIX}{name}{suffix} {value}"


class Collector:
    def __init__(self, repo: Path, config_path: Path, domains_path: Path) -> None:
        self.repo = repo
        self.config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        self.domains = yaml.safe_load(domains_path.read_text(encoding="utf-8")) or {}
        self.signals = self.config.get("signals", {})

    # ---------- 23 信号 ----------
    def signal_metrics(self) -> list[str]:
        audit = self.repo / self.signals.get(
            "decision_audit", "23-四层闭环自进化交易架构/runtime/execution_decisions.jsonl"
        )
        rows = _tail_jsonl(audit)
        out = []
        if audit.exists():
            out.append(
                _metric(
                    "signal_last_timestamp_seconds", audit.stat().st_mtime, source="23-evolution"
                )
            )
        else:
            out.append(_metric("signal_last_timestamp_seconds", 0, source="23-evolution"))

        required = self.signals.get("required_top_level") or []
        required_payload = self.signals.get("required_payload_23") or []
        valid = 0
        missing: dict[str, int] = {}
        confidences: list[float] = []
        counts: dict[tuple[str, str], int] = {}
        cutoff = _now() - 86400
        recent = 0
        for rec in rows:
            # 只统计携带完整信号的审计记录；旧版仅摘要的记录无法参与契约校验
            if "signal" not in rec and "payload" not in rec:
                continue
            sig = _signal_of(rec)
            ts = _iso_to_ts(str(sig.get("ts") or rec.get("ts") or "")) or 0.0
            if ts and ts < cutoff:
                continue
            recent += 1
            gaps = [f for f in required if f not in sig]
            payload = sig.get("payload") if isinstance(sig.get("payload"), dict) else {}
            if str(sig.get("source") or "") == "23-evolution":
                gaps.extend(f"payload.{f}" for f in required_payload if f not in payload)
            if not gaps:
                valid += 1
            for f in gaps:
                missing[f] = missing.get(f, 0) + 1
            try:
                confidences.append(float(sig.get("confidence")))
            except (TypeError, ValueError):
                pass
            sym = str(sig.get("symbol") or rec.get("symbol") or "?")
            act = str(payload.get("action") or sig.get("action") or "?")
            counts[(sym, act)] = counts.get((sym, act), 0) + 1

        out.append(_metric("signal_samples_recent", recent, source="23-evolution"))
        if recent:
            out.append(
                _metric(
                    "signal_schema_valid_ratio", round(valid / recent, 4), source="23-evolution"
                )
            )
        out.append(
            _metric(
                "signal_confidence_stdev",
                round(statistics.pstdev(confidences), 4) if len(confidences) > 1 else 0,
            )
        )
        for (sym, act), n in sorted(counts.items()):
            out.append(
                _metric("signal_generated_total", n, source="23-evolution", symbol=sym, action=act)
            )
        for field, n in sorted(missing.items()):
            out.append(
                _metric("signal_missing_fields_total", n, source="23-evolution", field=field)
            )

        expected = str(self.signals.get("expected_mode", "live"))
        actual_dry = self._entry_dry_run()
        mismatch = 1 if (expected == "live" and actual_dry) else 0
        out.append(_metric("signal_mode_mismatch", mismatch, source="23-evolution"))
        out.append(_metric("entry23_active", 1 if self._active("dreambuddy-entry23") else 0))
        return out

    @staticmethod
    def _active(unit: str) -> bool:
        try:
            return (
                subprocess.run(
                    ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5
                ).stdout.strip()
                == "active"
            )
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _entry_dry_run() -> bool:
        try:
            out = subprocess.run(
                ["systemctl", "show", "dreambuddy-entry23", "-p", "ExecStart"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            return "--dry-run" in out
        except (OSError, subprocess.SubprocessError):
            return False

    # ---------- 发件箱 ----------
    def outbox_metrics(self) -> list[str]:
        db = self.repo / self.signals.get(
            "outbox_db", "23-四层闭环自进化交易架构/runtime/execution_outbox.db"
        )
        if not db.exists():
            return [_metric("outbox_stuck", 0, state="unknown")]
        stuck_after = float(self.signals.get("outbox_stuck_seconds", 300))
        out: list[str] = []
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            cur = conn.cursor()
            tables = [
                r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ]
            if not tables:
                return [_metric("outbox_stuck", 0, state="unknown")]
            table = "outbox" if "outbox" in tables else tables[0]
            cols = [r[1] for r in cur.execute(f"PRAGMA table_info({table})")]
            status_col = next((c for c in ("status", "state") if c in cols), None)
            ts_col = next(
                (c for c in ("updated_at", "created_at", "ts", "timestamp") if c in cols), None
            )
            if not status_col:
                return [_metric("outbox_stuck", 0, state="unknown")]
            if ts_col:
                sql = (
                    f"SELECT {status_col}, COUNT(*), "
                    f"SUM(CASE WHEN {status_col} NOT IN ('filled','failed','cancelled','canceled','done','submitted','archived') "
                    f"AND datetime(replace({ts_col}, 'T', ' ')) < datetime('now', '-{int(stuck_after)} seconds') "
                    f"THEN 1 ELSE 0 END) FROM {table} GROUP BY {status_col}"
                )
            else:
                sql = f"SELECT {status_col}, COUNT(*), 0 FROM {table} GROUP BY {status_col}"
            for status, total, stuck in cur.execute(sql):
                out.append(_metric("outbox_items", total, state=str(status)))
                out.append(_metric("outbox_stuck", stuck or 0, state=str(status)))
            # 可用保证金不足导致的拒单：区分「资金不足」与「参数/网关」类失败
            if "last_error" in cols:
                try:
                    n_insufficient = cur.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {status_col}='failed' "
                        f"AND lower(last_error) LIKE '%insufficient%'"
                    ).fetchone()[0]
                    out.append(_metric("outbox_failed_insufficient_margin", n_insufficient or 0))
                except sqlite3.Error:
                    pass
            conn.close()
        except sqlite3.Error:
            return [_metric("outbox_stuck", 0, state="error")]
        return out

    # ---------- 23 全市场探索（币种池） ----------
    def universe_metrics(self) -> list[str]:
        """全市场探索快照指标（11 退役后默认关闭，避免永久误报）。"""
        cfg = self.config.get("universe", {}) or {}
        if not cfg.get("enabled", False):
            return []
        path = self.repo / str(
            cfg.get("path", "23-四层闭环自进化交易架构/runtime/universe_snapshot.json")
        )
        stale_age = 86400.0
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [
                _metric("evolution_universe_snapshot_age_seconds", stale_age),
                _metric("evolution_scan_failed", 1),
            ]
        age = max(0.0, _now() - float(snap.get("ts") or 0.0))
        return [
            _metric("evolution_universe_snapshot_age_seconds", round(age, 1)),
            _metric("evolution_base_count", int(snap.get("base_count") or 0)),
            _metric("evolution_scan_candidates", int(snap.get("scan_candidates") or 0)),
            _metric("evolution_scan_new", int(snap.get("scan_new") or 0)),
            _metric("evolution_pool_size", int(snap.get("pool_size") or 0)),
            _metric("evolution_pool_truncated", int(snap.get("truncated") or 0)),
            _metric("evolution_scan_failed", 1 if snap.get("scan_failed") else 0),
        ]

    # ---------- 22 公共执行 / 23 进程（TD §13.8） ----------
    def execution_metrics(self) -> list[str]:
        ex = self.config.get("execution", {}) or {}
        out = [
            _metric(
                "exit23_active",
                1 if self._active(str(ex.get("exit23_unit", "dreambuddy-exit23"))) else 0,
            ),
        ]
        out.extend(self._ledger_metrics(ex))
        out.extend(self._sltp_metrics(ex))
        out.extend(self._cycle_metrics())
        return out

    def _cycle_metrics(self) -> list[str]:
        """40→23 周期上下文新鲜度（P2-5 trace 配套监控）。"""
        base = self.repo / "40-周期神经网络系统"

        def _age(name: str) -> float:
            try:
                return max(0.0, _now() - (base / name).stat().st_mtime)
            except OSError:
                return 86400.0

        cs_age = _age("cycle_state.json")
        sm_age = _age("strategy_mapping.json")
        return [
            _metric("cycle_state_age_seconds", round(cs_age, 1)),
            _metric("strategy_mapping_age_seconds", round(sm_age, 1)),
            _metric("cycle_context_available", 0 if cs_age > 72 * 3600 else 1),
        ]

    def _ledger_metrics(self, ex: dict) -> list[str]:
        db = self.repo / str(ex.get("ledger_db", "22-执行引擎中心/runtime/position_ledger.db"))
        if not db.exists():
            return [
                _metric("ledger_positions", 0),
                _metric("ledger_last_write_age_seconds", 86400),
                _metric("ledger_reconcile_updated_1h", 0),
                _metric("ledger_ghost_closed_24h", 0),
                _metric("ledger_ghost_stale_24h", 0),
                _metric("ledger_ghost_exchange_flat_24h", 0),
                _metric("ledger_exchange_sltp_24h", 0),
                _metric("ledger_stale_positions", 0),
                _metric("ledger_breaks_open", 0),
                _metric("ledger_breaks_overdue", 0),
                _metric("ledger_miss_max", 0),
                _metric("ledger_reservations_held", 0),
                _metric("ledger_domain_qty_mismatch", 0),
                _metric("ledger_janitor_age_seconds", 86400),
                _metric("ledger_feed_state", 1),
            ]
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            cur = conn.cursor()

            def _scalar(sql: str, params=()) -> float:
                try:
                    row = cur.execute(sql, params).fetchone()
                    return float(row[0]) if row and row[0] is not None else 0.0
                except sqlite3.Error:
                    return 0.0

            positions = cur.execute("SELECT COUNT(*) FROM positions WHERE qty > 1e-9").fetchone()[0]
            last = cur.execute("SELECT MAX(ts) FROM fills").fetchone()[0]
            updated = cur.execute(
                "SELECT COUNT(*) FROM fills WHERE action='reconcile_update' AND ts >= ?",
                (_iso_utc(_now() - 3600),),
            ).fetchone()[0]
            _ghost_rows = cur.execute(
                "SELECT exit_reason, COUNT(*) FROM cooldowns WHERE exit_reason IN"
                " ('ghost_stale','ghost_exchange_flat','exchange_sltp') AND close_ts >= ?"
                " GROUP BY exit_reason",
                (_iso_utc(_now() - 86400),),
            ).fetchall()
            _ghost_map = {str(r[0]): int(r[1]) for r in _ghost_rows}
            ghost_stale = _ghost_map.get("ghost_stale", 0)
            ghost_flat = _ghost_map.get("ghost_exchange_flat", 0)
            exchange_sltp = _ghost_map.get("exchange_sltp", 0)
            ghost = ghost_stale + ghost_flat
            # P1/P2：域归因与巡检健康（旧库无新表时按 0/正常处理）
            stale_pos = int(_scalar("SELECT COUNT(*) FROM positions WHERE status='stale'"))
            breaks_open = int(_scalar("SELECT COUNT(*) FROM recon_breaks WHERE state='OPEN'"))
            breaks_overdue = int(
                _scalar(
                    "SELECT COUNT(*) FROM recon_breaks WHERE state IN ('OPEN','ACK')"
                    " AND sla_due_at IS NOT NULL AND sla_due_at < ?",
                    (_iso_utc(_now()),),
                )
            )
            miss_max = int(_scalar("SELECT COALESCE(MAX(miss_count),0) FROM positions"))
            resv_held = int(_scalar("SELECT COUNT(*) FROM reservations WHERE state='held'"))
            _pos_sum = _scalar("SELECT COALESCE(SUM(qty),0) FROM positions WHERE qty > 1e-9")
            _dom_sum = _scalar("SELECT COALESCE(SUM(qty),0) FROM domain_positions WHERE qty > 1e-9")
            mismatch = 1 if abs(_pos_sum - _dom_sum) > 1e-9 else 0
            _hb = _scalar("SELECT 1 FROM ledger_heartbeat WHERE id=1")
            _hb_ts = None
            if _hb:
                try:
                    _hb_ts = cur.execute("SELECT ts FROM ledger_heartbeat WHERE id=1").fetchone()[0]
                except sqlite3.Error:
                    _hb_ts = None
            _feed = "ok"
            try:
                _row = cur.execute(
                    "SELECT value FROM ledger_settings WHERE key='feed_state'"
                ).fetchone()
                _feed = str(_row[0]) if _row and _row[0] else "ok"
            except sqlite3.Error:
                _feed = "ok"
            conn.close()
        except sqlite3.Error:
            return [_metric("ledger_error", 1)]
        age = max(0.0, _now() - _iso_to_ts(str(last))) if last else 86400.0
        janitor_age = max(0.0, _now() - _iso_to_ts(str(_hb_ts))) if _hb_ts else 86400.0
        feed_state = {"ok": 0, "degraded": 1, "stale": 2}.get(_feed, 1)
        return [
            _metric("ledger_positions", positions),
            _metric("ledger_last_write_age_seconds", round(age, 1)),
            _metric("ledger_reconcile_updated_1h", updated),
            _metric("ledger_ghost_closed_24h", ghost),
            _metric("ledger_ghost_stale_24h", ghost_stale),
            _metric("ledger_ghost_exchange_flat_24h", ghost_flat),
            _metric("ledger_exchange_sltp_24h", exchange_sltp),
            _metric("ledger_stale_positions", stale_pos),
            _metric("ledger_breaks_open", breaks_open),
            _metric("ledger_breaks_overdue", breaks_overdue),
            _metric("ledger_miss_max", miss_max),
            _metric("ledger_reservations_held", resv_held),
            _metric("ledger_domain_qty_mismatch", mismatch),
            _metric("ledger_janitor_age_seconds", round(janitor_age, 1)),
            _metric("ledger_feed_state", feed_state),
        ]

    def _sltp_metrics(self, ex: dict) -> list[str]:
        path = self.repo / str(ex.get("sltp_audit", "22-执行引擎中心/audit/sltp_reconcile.jsonl"))
        if not path.exists():
            return [
                _metric("sltp_reconcile_age_seconds", 86400),
                _metric("sltp_reconcile_patched_1h", 0),
                _metric("sltp_reconcile_failed_1h", 0),
            ]
        age = max(0.0, _now() - path.stat().st_mtime)
        patched = failed = 0
        cutoff = _now() - 3600
        _summaries = []
        _details = []
        for rec in _tail_jsonl(path, limit=2000):
            ts = _iso_to_ts(str(rec.get("ts") or ""))
            if not ts or ts < cutoff:
                continue
            if rec.get("kind") == "summary":
                _summaries.append(rec)
            elif "ok" in rec:
                _details.append(rec)
        if _summaries:
            patched = sum(int(r.get("patched") or 0) for r in _summaries)
            failed = sum(int(r.get("failed") or 0) for r in _summaries)
        else:
            patched = sum(1 for r in _details if r.get("ok"))
            failed = sum(1 for r in _details if not r.get("ok"))
        return [
            _metric("sltp_reconcile_age_seconds", round(age, 1)),
            _metric("sltp_reconcile_patched_1h", patched),
            _metric("sltp_reconcile_failed_1h", failed),
        ]

    # ---------- A 类交易链路事件（TD §13.4） ----------
    def chain_metrics(self) -> list[str]:
        runtime = self.repo / "23-四层闭环自进化交易架构/runtime"
        cutoff_24h = _now() - 86400
        cutoff_1h = _now() - 3600
        rows: list[dict] = []
        for path in sorted(runtime.glob("chain_events-*.jsonl"))[-2:]:
            rows.extend(_tail_jsonl(path, limit=5000))

        stage_counts: dict[tuple[str, str], int] = {}
        chains: dict[str, set[str]] = {}
        blocked_chains: set[str] = set()
        blocked_reasons: dict[str, int] = {}
        wait_reasons: dict[str, int] = {}
        exit_size_unknown = 0
        exit_close_failed: dict[str, int] = {}

        for rec in rows:
            ts = _iso_to_ts(str(rec.get("ts") or ""))
            if not ts or ts < cutoff_24h:
                continue
            stage = str(rec.get("stage") or "?")
            status = str(rec.get("status") or "?")
            stage_counts[(stage, status)] = stage_counts.get((stage, status), 0) + 1
            cid = str(rec.get("chain_id") or rec.get("trace_id") or rec.get("decision_id") or "")
            if cid:
                chains.setdefault(cid, set()).add(stage)
            data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            # N11 拦截（如已有持仓）是策略主动终止，不是静默断链；
            # 计入完成率会让正常拦截长期压低 ratio 并触发 ChainBroken/ChainCompletionLow 误报
            if stage == "N11" and status == "blocked" and cid:
                blocked_chains.add(cid)
                _gate = str(data.get("gate") or "unknown")
                blocked_reasons[_gate] = blocked_reasons.get(_gate, 0) + 1
            if stage == "N8" and status == "skip":
                reason = str(data.get("reason_category") or "unknown")
                wait_reasons[reason] = wait_reasons.get(reason, 0) + 1
            if ts >= cutoff_1h:
                if (
                    stage == "E4"
                    and status == "failed"
                    and str(data.get("reason_code")) == "SIZE_UNKNOWN"
                ):
                    exit_size_unknown += 1
                if stage == "E5" and status == "failed":
                    rc = str(data.get("reason_code") or "UNKNOWN")
                    exit_close_failed[rc] = exit_close_failed.get(rc, 0) + 1

        out: list[str] = []
        for (stage, status), n in sorted(stage_counts.items()):
            out.append(_metric("chain_stage_total", n, stage=stage, status=status))
        if chains:
            signal_chains = [
                stages
                for cid, stages in chains.items()
                if "N10" in stages and cid not in blocked_chains
            ]
            if signal_chains:
                complete = sum(1 for stages in signal_chains if {"N12", "N14"} <= stages)
                out.append(
                    _metric("chain_completion_ratio", round(complete / len(signal_chains), 4))
                )
                for required in ("N12", "N14"):
                    missing = sum(1 for stages in signal_chains if required not in stages)
                    out.append(_metric("chain_missing_stage_total", missing, stage=required))
        for gate, n in sorted(blocked_reasons.items()):
            out.append(_metric("chain_blocked_total", n, gate=gate))
        wait_total = sum(wait_reasons.values())
        if wait_total:
            out.append(_metric("chain_wait_events_total", wait_total))
            for reason, n in sorted(wait_reasons.items()):
                out.append(_metric("chain_wait_total", n, reason=reason))
            broken = wait_reasons.get("unknown", 0)
            out.append(_metric("wait_vs_broken_ratio", round(broken / wait_total, 4)))
            out.append(_metric("chain_broken_total", broken))

        out.append(_metric("exit_size_unknown_total", exit_size_unknown))
        for rc, n in sorted(exit_close_failed.items()):
            out.append(_metric("exit_close_failed_total", n, reason_code=rc))
        return out

    # ---------- 22 契约告警 ----------
    def contract_metrics(self) -> list[str]:
        path = self.repo / "22-执行引擎中心/audit/contract_violations.jsonl"
        cutoff = _now() - 3600
        counts: dict[str, int] = {}
        if path.exists():
            for rec in _tail_jsonl(path, limit=2000):
                ts = _iso_to_ts(str(rec.get("ts") or ""))
                if ts and ts >= cutoff:
                    src = str(rec.get("source") or "unknown")
                    counts[src] = counts.get(src, 0) + 1
        out = [
            _metric(
                "contract_mode_alert_only",
                1 if os.getenv("EXECUTION_CONTRACT_MODE", "alert") == "alert" else 0,
            )
        ]
        for src, n in sorted(counts.items()):
            out.append(_metric("contract_violations_1h", n, source=src))
        return out

    # ---------- 矛盾 / 交叉验证语义 ----------
    def semantic_metrics(self) -> list[str]:
        path = self.repo / "23-四层闭环自进化交易架构/runtime/execution_decisions.jsonl"
        # 状态指标只反映"当前态"：决策超过时效窗口即视为陈旧，
        # 不参与 contradiction/cv 状态统计（审计记录本身仍保留）。
        # 否则已停止决策的 symbol 会把 both_none/空 cross_validation 永久留在指标里，
        # 导致 CrossValidationDegraded / CrossValidationMissing 永不恢复。
        window = float(self.signals.get("state_window_seconds", 43200))
        cutoff = _now() - window
        latest: dict[str, dict] = {}
        for rec in _tail_jsonl(path, limit=2000):
            sig = _signal_of(rec)
            ts = _iso_to_ts(str(sig.get("ts") or rec.get("ts") or ""))
            if not ts or ts < cutoff:
                continue
            if isinstance(sig.get("payload"), dict):
                latest[str(sig.get("symbol") or rec.get("symbol") or "?")] = sig
        out: list[str] = []
        total = len(latest)
        pc_ok = cv_ok = degraded = 0
        for sym, sig in latest.items():
            payload = sig["payload"]
            pc = payload.get("primary_contradiction") or {}
            pc_present = bool(pc) and str(pc.get("dimension") or "unknown") != "unknown"
            cv = payload.get("cross_validation") or {}
            cv_present = bool(cv)
            pc_ok += int(pc_present)
            cv_ok += int(cv_present)
            out.append(_metric("contradiction_present", int(pc_present), symbol=sym))
            if pc_present:
                out.append(
                    _metric(
                        "contradiction_strength",
                        float(pc.get("strength") or 0.0),
                        symbol=sym,
                        dimension=str(pc.get("dimension") or "unknown"),
                        direction=str(pc.get("direction") or "unknown"),
                    )
                )
            out.append(_metric("cv_present", int(cv_present), symbol=sym))
            if cv_present:
                _mode = str(cv.get("degraded_mode") or "")
                if _mode:
                    degraded += 1
                    out.append(_metric("cv_degraded_mode", 1, symbol=sym, mode=_mode))
                out.append(
                    _metric("cv_shift_signal", int(bool(cv.get("shift_signal"))), symbol=sym)
                )
                out.append(
                    _metric(
                        "cv_confidence_mult",
                        float(cv.get("confidence_mult") or 1.0),
                        symbol=sym,
                    )
                )
                out.append(
                    _metric(
                        "cv_divergence_count",
                        int(cv.get("divergence_count") or 0),
                        symbol=sym,
                    )
                )
        if total:
            out.append(_metric("contradiction_present_ratio", round(pc_ok / total, 4)))
            out.append(_metric("cv_present_ratio", round(cv_ok / total, 4)))
            out.append(_metric("cv_degraded", degraded))
        return out

    # ---------- 产物 / 单元 ----------
    def artifact_metrics(self) -> list[str]:
        out = []
        for item in self.config.get("artifacts", []):
            path = self.repo / item["path"]
            name = item.get("name", item["path"])
            ttl = float(item.get("ttl_seconds", 0))
            if not path.exists():
                out.append(_metric("artifact_present", 0, artifact=name))
                out.append(_metric("artifact_age_seconds", 0, artifact=name))
                out.append(_metric("artifact_ttl_seconds", ttl, artifact=name))
                continue
            field = item.get("timestamp_field")
            age = _now() - path.stat().st_mtime
            if field:
                try:
                    stamp = json.loads(path.read_text(encoding="utf-8")).get(field)
                    ts = _iso_to_ts(str(stamp))
                    if ts:
                        age = max(0.0, _now() - ts)
                except (OSError, ValueError):
                    pass
            out.append(_metric("artifact_present", 1, artifact=name))
            out.append(_metric("artifact_age_seconds", round(age, 1), artifact=name))
            out.append(_metric("artifact_ttl_seconds", ttl, artifact=name))
        return out

    def cell_metrics(self) -> list[str]:
        out = []
        for cell in self.domains.get("cells", []):
            score = MATURITY.get(str(cell.get("maturity", "M0")), 0)
            out.append(
                _metric(
                    "cell_health", score, cell=str(cell.get("id")), chain=str(cell.get("chain"))
                )
            )
        return out

    # ---------- 信号口径校准（F1–F4，2026-11-18） ----------
    def signal_calibration_metrics(self) -> list[str]:
        """d_star wait 口径 / ri / ESS 方向 / 放量门槛 / reflection 样本 的 1h 健康度。"""
        runtime = self.repo / "23-四层闭环自进化交易架构/runtime"
        cutoff_1h = _now() - 3600
        cutoff_24h = _now() - 86400
        rows: list[dict] = []
        for path in sorted(runtime.glob("chain_events-*.jsonl"))[-2:]:
            rows.extend(_iter_jsonl_since(path, cutoff_24h, ("N2", "N4", "N9")))

        mode = ""
        cal_wait = cal_trade = flip = 0
        ri_neutral = ess_empty = refl_ok = 0
        refl_max = 0.0
        latest_ri: dict[str, float] = {}
        latest_thr: dict[str, float] = {}
        latest_refl: dict[str, float] = {}
        refl_series: dict[str, set[float]] = {}
        latest_sent: dict[str, float] = {}
        latest_spread: dict[str, float] = {}
        latest_liq: dict[str, float] = {}

        for rec in rows:
            ts = _iso_to_ts(str(rec.get("ts") or ""))
            if not ts or ts < cutoff_24h:
                continue
            stage = str(rec.get("stage") or "")
            data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            sym = str(rec.get("symbol") or "?").split("-")[0] or "?"
            if stage == "N2":
                # 反射性可观测：24h 窗口（用于恒定检测）
                try:
                    refl = float(data["R_reflexivity"])
                except (KeyError, TypeError, ValueError):
                    refl = None
                if refl is not None:
                    latest_refl[sym] = refl
                    refl_series.setdefault(sym, set()).add(round(refl, 6))
                    r_inputs = data.get("r_inputs")
                    if isinstance(r_inputs, dict):
                        comp = r_inputs.get("refl_components")
                        comp = comp if isinstance(comp, dict) else {}
                        for key, bucket in (
                            ("news_sentiment_score", latest_sent),
                            ("bid_ask_spread_bps", latest_spread),
                        ):
                            val = r_inputs.get(key)
                            if isinstance(val, (int, float)):
                                bucket[sym] = float(val)
                        if isinstance(comp.get("liq_term"), (int, float)):
                            latest_liq[sym] = float(comp["liq_term"])
                continue
            if ts < cutoff_1h:
                continue
            if stage == "N4":
                shadow = data.get("d_star_shadow")
                if isinstance(shadow, dict) and shadow:
                    mode = str(shadow.get("wait_mode") or mode)
                    if str(shadow.get("d_star_calibrated")) == "WAIT":
                        cal_wait += 1
                    else:
                        cal_trade += 1
                    if str(shadow.get("d_star_calibrated")) != str(data.get("d_star_original")):
                        flip += 1
            elif stage == "N9":
                try:
                    if data.get("ri") is not None:
                        ri = float(data["ri"])
                        latest_ri[sym] = ri
                        if abs(ri - 0.5) < 1e-9:
                            ri_neutral += 1
                    if data.get("vol_threshold") is not None:
                        latest_thr[sym] = float(data["vol_threshold"])
                    if data.get("reflection_ri") is not None:
                        refl_max = max(refl_max, float(data["reflection_ri"]))
                except (TypeError, ValueError):
                    continue
                if not str(data.get("ess_top_direction") or "").strip():
                    ess_empty += 1
                if data.get("reflection_eligible"):
                    refl_ok += 1

        out = [
            _metric("dstar_calibrated_enabled", 1 if mode == "calibrated" else 0),
            _metric("dstar_wait_mode", 1, mode=mode or "unknown"),
            _metric("dstar_calibrated_wait_1h", cal_wait),
            _metric("dstar_calibrated_trade_1h", cal_trade),
            _metric("dstar_calibrated_flip_1h", flip),
            _metric("ri_neutral_1h", ri_neutral),
            _metric("ess_direction_empty_1h", ess_empty),
            _metric("reflection_eligible_1h", refl_ok),
            _metric("reflection_ri_max", round(refl_max, 4)),
        ]
        for sym, v in sorted(latest_ri.items()):
            out.append(_metric("ri_value", round(v, 4), symbol=sym))
        for sym, v in sorted(latest_thr.items()):
            out.append(_metric("ripple_vol_threshold", round(v, 4), symbol=sym))
        # 反射性维度健康度（R_reflexivity 恒定 = 40/30/30 分项失效）
        for sym, v in sorted(latest_refl.items()):
            out.append(_metric("r_reflexivity", round(v, 4), symbol=sym))
            out.append(
                _metric("r_reflexivity_distinct_24h", len(refl_series.get(sym, ())), symbol=sym)
            )
        for sym, v in sorted(latest_sent.items()):
            out.append(_metric("r_refl_sentiment_score", round(v, 4), symbol=sym))
        for sym, v in sorted(latest_spread.items()):
            out.append(_metric("r_refl_spread_bps", round(v, 4), symbol=sym))
        for sym, v in sorted(latest_liq.items()):
            out.append(_metric("r_refl_liq_term", round(v, 4), symbol=sym))
        return out

    def collect(self) -> str:
        lines = [
            "# HELP dreambuddy_monitor_heartbeat_timestamp_seconds exporter heartbeat",
            "# TYPE dreambuddy_monitor_heartbeat_timestamp_seconds gauge",
            _metric("monitor_heartbeat_timestamp_seconds", _now()),
        ]
        for group in (
            self.signal_metrics(),
            self.outbox_metrics(),
            self.contract_metrics(),
            self.semantic_metrics(),
            self.universe_metrics(),
            self.execution_metrics(),
            self.chain_metrics(),
            self.signal_calibration_metrics(),
            self.artifact_metrics(),
            self.cell_metrics(),
        ):
            lines.extend(group)
        return "\n".join(lines) + "\n"


def _metrics_text(collector_provider) -> str:
    with _cache["lock"]:
        age = _now() - float(_cache["ts"])
        if age >= 30 or not _cache["text"]:
            try:
                _cache["text"] = collector_provider().collect()
                _cache["ts"] = _now()
            except Exception as exc:  # noqa: BLE001 - exporter 不能因单点异常整体 5xx
                print(f"[exporter] collect failed: {exc}", file=sys.stderr)
                _cache["text"] = (
                    "# TYPE dreambuddy_exporter_error gauge\ndreambuddy_exporter_error 1\n"
                )
                _cache["ts"] = _now()
        return str(_cache["text"])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/metrics":
            data = _metrics_text(_provider).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/healthz":
            data = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--domains", default=str(DEFAULT_DOMAINS))
    parser.add_argument("--repo-root", default="/home/luke/dreambuddy")
    parser.add_argument("--listen", default=os.environ.get("EXPORTER_LISTEN", "127.0.0.1:9101"))
    args = parser.parse_args()

    collector = Collector(Path(args.repo_root), Path(args.config), Path(args.domains))

    def provide_collector() -> Collector:
        return collector

    global _provider
    _provider = provide_collector
    host, _, port = args.listen.partition(":")
    print(f"[exporter] repo={args.repo_root} listen={args.listen}", flush=True)
    ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
