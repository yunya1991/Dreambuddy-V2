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
# 反射性指标新鲜度门槛：停更 symbol（含夜间无行情的股票）不再导出当前值/恒定序列，
# 否则 24h 窗口内残存的少量样本会触发恒 1 的假告警
_REFLEXIVITY_FRESH_SECONDS = 3 * 3600
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


def _last_node_ts(path: Path, node: str, max_bytes: int = 2 * 1024 * 1024) -> float:
    """从文件尾部向前扫描，返回匹配 node 的最新事件 ts（0 表示未找到）。"""
    if not path.exists():
        return 0.0
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block = min(size, max_bytes)
            fh.seek(size - block)
            chunk = fh.read().decode("utf-8", errors="ignore")
    except OSError:
        return 0.0
    for line in reversed(chunk.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if str(rec.get("node") or "") != node:
            continue
        ts = _iso_to_ts(str(rec.get("ts") or ""))
        if ts:
            return ts
    return 0.0


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
                _metric("sltp_reconcile_query_failed_1h", 0),
            ]
        age = max(0.0, _now() - path.stat().st_mtime)
        patched = failed = query_failed = 0
        cutoff = _now() - 3600
        _summaries = []
        _details = []
        for rec in _tail_jsonl(path, limit=2000):
            ts = _iso_to_ts(str(rec.get("ts") or ""))
            if not ts or ts < cutoff:
                continue
            if rec.get("kind") == "summary":
                _summaries.append(rec)
            elif "ok" in rec or rec.get("kind") == "algo_query_fail":
                _details.append(rec)
        if _summaries:
            patched = sum(int(r.get("patched") or 0) for r in _summaries)
            failed = sum(int(r.get("failed") or 0) for r in _summaries)
            query_failed = sum(int(r.get("query_failed") or 0) for r in _summaries)
        else:
            patched = sum(1 for r in _details if r.get("ok"))
            failed = sum(1 for r in _details if r.get("ok") is False)
            query_failed = sum(1 for r in _details if r.get("kind") == "algo_query_fail")
        return [
            _metric("sltp_reconcile_age_seconds", round(age, 1)),
            _metric("sltp_reconcile_patched_1h", patched),
            _metric("sltp_reconcile_failed_1h", failed),
            _metric("sltp_reconcile_query_failed_1h", query_failed),
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
    def _chain_event_age(self, pattern: str, node: str) -> float | None:
        """按 chain_events 中指定 node 的最新 ts 计算新鲜度（判"决策沉默"而非"未下单"）。"""
        for path in sorted(self.repo.glob(pattern))[-2:][::-1]:
            ts = _last_node_ts(path, node)
            if ts:
                return max(0.0, _now() - ts)
        return None

    def artifact_metrics(self) -> list[str]:
        out = []
        for item in self.config.get("artifacts", []):
            name = item.get("name", item["path"])
            ttl = float(item.get("ttl_seconds", 0))
            labels = {"artifact": name}
            if item.get("severity"):
                labels["severity"] = str(item["severity"])
            node = item.get("chain_event_node")
            if node:
                age = self._chain_event_age(str(item["path"]), str(node))
                out.append(_metric("artifact_present", 0 if age is None else 1, **labels))
                out.append(
                    _metric("artifact_age_seconds", 0 if age is None else round(age, 1), **labels)
                )
                out.append(_metric("artifact_ttl_seconds", ttl, **labels))
                continue
            path = self.repo / item["path"]
            if not path.exists():
                out.append(_metric("artifact_present", 0, **labels))
                out.append(_metric("artifact_age_seconds", 0, **labels))
                out.append(_metric("artifact_ttl_seconds", ttl, **labels))
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
            out.append(_metric("artifact_present", 1, **labels))
            out.append(_metric("artifact_age_seconds", round(age, 1), **labels))
            out.append(_metric("artifact_ttl_seconds", ttl, **labels))
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
        n2_rows: list[tuple[str, float, float, str, dict]] = []

        for rec in rows:
            ts = _iso_to_ts(str(rec.get("ts") or ""))
            if not ts or ts < cutoff_24h:
                continue
            stage = str(rec.get("stage") or "")
            data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            sym = str(rec.get("symbol") or "?").split("-")[0] or "?"
            if stage == "N2":
                # 反射性可观测：24h 窗口（用于恒定检测），口径隔离延后到循环后处理
                try:
                    refl = float(data["R_reflexivity"])
                except (KeyError, TypeError, ValueError):
                    continue
                r_inputs = data.get("r_inputs")
                r_inputs = r_inputs if isinstance(r_inputs, dict) else {}
                comp = r_inputs.get("refl_components")
                comp = comp if isinstance(comp, dict) else {}
                n2_rows.append(
                    (
                        sym,
                        ts,
                        refl,
                        str(comp.get("formula") or "legacy"),
                        {
                            "sent": r_inputs.get("news_sentiment_score"),
                            "spread": r_inputs.get("bid_ask_spread_bps"),
                            "liq": comp.get("liq_term"),
                        },
                    )
                )
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

        # 口径隔离：只保留与最新样本同公式的 N2 记录
        #   1) 切换前 legacy 样本污染 distinct，会掩盖当前公式的真实恒定（假阴性）
        #   2) 已停更 symbol 的窗口内只剩少量旧样本 → distinct 恒 1（假阳性）
        active_formula = max(n2_rows, key=lambda r: r[1])[3] if n2_rows else ""
        fresh_after = _now() - _REFLEXIVITY_FRESH_SECONDS
        by_symbol: dict[str, list[tuple[float, float, dict]]] = {}
        for sym, ts, refl, formula, extra in n2_rows:
            if formula != active_formula:
                continue
            by_symbol.setdefault(sym, []).append((ts, refl, extra))
        for sym, items in by_symbol.items():
            latest_ts, latest_val, latest_extra = max(items, key=lambda it: it[0])
            if latest_ts < fresh_after:  # 停更 symbol：不导出当前值与恒定序列
                continue
            latest_refl[sym] = latest_val
            refl_series[sym] = {round(val, 6) for _, val, _ in items}
            for key, bucket in (
                ("sent", latest_sent),
                ("spread", latest_spread),
                ("liq", latest_liq),
            ):
                val = latest_extra[key]
                if isinstance(val, (int, float)):
                    bucket[sym] = float(val)

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

    # ---------- 主神经网络链（TD §14，M0–M14） ----------
    def main_nn_metrics(self) -> list[str]:
        """48→40→43→42→50→22 主神经网络链的语义快照与链路指标（只读旁路）。"""
        cfg = self.signals.get("main_nn", {}) or {}
        ex = (self.config.get("execution", {}) or {}).get("main_nn", {}) or {}
        src = str(cfg.get("source", "main-nn"))
        out: list[str] = [_metric("main_nn_export_timestamp_seconds", _now())]

        # M1/M2 周期判定（40）
        cs = _read_json(self.repo / "40-周期神经网络系统/cycle_state.json")
        out.append(_metric("main_nn_cycle_present", 1 if cs else 0))
        stale = 1
        if cs:
            rc = cs.get("real_cycle") if isinstance(cs.get("real_cycle"), dict) else {}
            level = str(rc.get("confidence") or "unknown")
            out.append(
                _metric(
                    "main_nn_cycle_confidence",
                    {"high": 2.0, "medium": 1.0, "low": 0.0}.get(level, -1.0),
                    level=level,
                )
            )
            out.append(_metric("main_nn_cycle_state", 1, state=str(rc.get("state") or "unknown")))
            stale_after = float(cfg.get("cycle_stale_seconds", 93600))
            stamp = _iso_to_ts(str(cs.get("generated_at") or "")) if cs.get("generated_at") else 0.0
            age = max(0.0, _now() - stamp) if stamp else stale_after + 1
            stale = 1 if age > stale_after else 0
        out.append(_metric("main_nn_cycle_stale", stale))

        # M3/M4 战略承接与发布（43）
        sig = _read_json(self.repo / "43-战略承接推演层/runtime/strategic_extension_signal.json")
        out.append(_metric("main_nn_strategic_present", 1 if sig else 0))
        if sig:
            payload = sig.get("payload") if isinstance(sig.get("payload"), dict) else {}
            shadow = 1 if sig.get("shadow") else 0
            bridge = 1 if payload.get("bridge_switch") else 0
            out.append(_metric("main_nn_strategic_shadow", shadow))
            out.append(_metric("main_nn_strategic_bridge", bridge))
            per = (
                payload.get("per_asset_class")
                if isinstance(payload.get("per_asset_class"), dict)
                else {}
            )
            totals = []
            for cls, item in sorted(per.items()):
                if not isinstance(item, dict):
                    continue
                total = int(item.get("total") or 0)
                totals.append(total)
                out.append(_metric("main_nn_strategic_total", total, asset_class=str(cls)))
                out.append(
                    _metric(
                        "main_nn_strategic_war_state",
                        1,
                        asset_class=str(cls),
                        state=str(item.get("war_state") or "unknown"),
                    )
                )
            # 三条件同时满足（bridge 开 + 40 产物新鲜 + shadow 未解除）才具备告警资格；
            # 单独 strategic_total==51 不是异常，规则侧只看本指标。
            flat = bool(totals) and all(t == 51 for t in totals)
            out.append(
                _metric(
                    "main_nn_strategic_fallback_dominant",
                    1 if (flat and bridge and not stale and shadow == 1) else 0,
                )
            )

        # M5 总线归一化（42）
        bus = _read_json(self.repo / "42-神经网络交易协调层/runtime/bus_state.json")
        out.append(_metric("main_nn_bus_present", 1 if bus else 0))
        if bus:
            sources = bus.get("sources") if isinstance(bus.get("sources"), list) else []
            sig_n = int(bus.get("signal_count") or 0)
            rej_n = int(bus.get("rejected_count") or 0)
            denom = sig_n + rej_n
            out.append(_metric("main_nn_bus_sources_ok", len(sources)))
            out.append(_metric("main_nn_bus_signal_count", sig_n))
            out.append(
                _metric("main_nn_bus_reject_ratio", round(rej_n / denom, 4) if denom else 0.0)
            )

        # M11 决策（50 decisions.jsonl）
        dec_path = self.repo / str(ex.get("decisions", "50-NN主矛盾评估器/runtime/decisions.jsonl"))
        window = float(cfg.get("state_window_seconds", 86400))
        cutoff = _now() - window
        latest: dict[str, dict] = {}
        modes: dict[str, int] = {}
        live_ids: set[str] = set()
        if dec_path.exists():
            for rec in _tail_jsonl(dec_path, limit=2000):
                ts = _iso_to_ts(str(rec.get("ts") or ""))
                if ts and ts < cutoff:
                    continue
                latest[str(rec.get("symbol") or rec.get("inst_id") or "?")] = rec
                payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
                mode = str(rec.get("mode") or payload.get("mode") or "unknown")
                modes[mode] = modes.get(mode, 0) + 1
                if mode == "live" and rec.get("decision_id"):
                    live_ids.add(str(rec["decision_id"]))
            out.append(
                _metric(
                    "main_nn_decisions_age_seconds",
                    round(max(0.0, _now() - dec_path.stat().st_mtime), 1),
                )
            )
        out.append(_metric("main_nn_decision_samples", len(latest)))
        for sym, rec in sorted(latest.items()):
            try:
                conf = float(rec.get("confidence"))
            except (TypeError, ValueError):
                continue
            out.append(_metric("main_nn_decision_confidence", round(conf, 4), symbol=sym))
        for mode, n in sorted(modes.items()):
            out.append(_metric("main_nn_decision_mode_total", n, mode=mode))

        # M7–M10 语义快照（聚合，低基数）：全部取自 decisions payload，不新增推断
        if latest:
            path_counts: list[int] = []
            neutral = total_paths = conflicted = fallback = locked = frozen = 0
            source_sets: list[set[str]] = []
            for rec in latest.values():
                payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
                w4 = payload.get("w4") if isinstance(payload.get("w4"), dict) else {}
                dom = payload.get("dominance") if isinstance(payload.get("dominance"), dict) else {}
                flap = (
                    payload.get("trigger_flap")
                    if isinstance(payload.get("trigger_flap"), dict)
                    else {}
                )
                paths = payload.get("paths") if isinstance(payload.get("paths"), list) else []
                path_counts.append(int(payload.get("path_count") or 0))
                conflicted += 1 if w4.get("conflict_flag") else 0
                fallback += 1 if dom.get("overall_fallback_argmax") else 0
                locked += 1 if flap.get("locked") else 0
                frozen += 1 if payload.get("constraint_freeze") else 0
                srcs: set[str] = set()
                for p in paths:
                    if not isinstance(p, dict):
                        continue
                    total_paths += 1
                    try:
                        if float(p.get("confidence") or 0) < 0.1:
                            neutral += 1
                    except (TypeError, ValueError):
                        neutral += 1
                    if p.get("source"):
                        srcs.add(str(p["source"]))
                source_sets.append(srcs)
            out.append(_metric("main_nn_path_count", max(path_counts or [0])))
            out.append(_metric("main_nn_contradiction_present", 1 if conflicted else 0))
            out.append(
                _metric("main_nn_dominance_fallback_ratio", round(fallback / len(latest), 4))
            )
            out.append(_metric("main_nn_trigger_flap_locked_ratio", round(locked / len(latest), 4)))
            out.append(_metric("main_nn_constraint_freeze_ratio", round(frozen / len(latest), 4)))
            out.append(
                _metric(
                    "main_nn_dimension_neutral_ratio",
                    round(neutral / total_paths, 4) if total_paths else 0.0,
                )
            )
            out.append(
                _metric(
                    "main_nn_evidence_sources_ok",
                    max((len(s) for s in source_sets), default=0),
                )
            )

        # M12 live 出箱（50 outbox.jsonl）
        ob_path = self.repo / str(ex.get("outbox", "50-NN主矛盾评估器/runtime/live/outbox.jsonl"))
        ob_rows: list[dict] = []
        if ob_path.exists():
            ob_age = max(0.0, _now() - ob_path.stat().st_mtime)
            out.append(_metric("main_nn_outbox_age_seconds", round(ob_age, 1)))
            out.append(
                _metric(
                    "main_nn_outbox_stale",
                    1 if ob_age > float(cfg.get("outbox_stale_seconds", 900)) else 0,
                )
            )
            # outbox 只保留最近 500 条；join/契约校验需覆盖整个窗口，不能只取尾部 200
            ob_rows = _tail_jsonl(ob_path, limit=5000)
        # 单出口契约：live 决策必须是 execution=live:50-bypass 且带 mandate_id
        if ob_rows:
            bad = 0
            for d in ob_rows:
                mode = str(d.get("mode") or "")
                execution = d.get("execution") if isinstance(d.get("execution"), dict) else {}
                outcome = str(execution.get("outcome") or "")
                if mode == "live" and (outcome != "live:50-bypass" or not d.get("mandate_id")):
                    bad += 1
                # 成交可回溯的 live 决策全集 = decisions.jsonl(live) ∪ outbox(live)：
                # outbox 是实盘决策的实际出口，仅看 decisions.jsonl 会漏掉未落账本的出口
                if mode == "live" and d.get("decision_id"):
                    live_ids.add(str(d["decision_id"]))
            out.append(_metric("main_nn_execution_rights_ok", 0 if bad else 1))

        # M6/M11 约束降级（42 统一降级审计流，layer=50/source=constraint_loader）
        # direction_leak_check 是加载器的设计动作（主动剥离方向字段），不是降级，排除
        benign = {"direction_leak_check"}
        dg_path = self.repo / "42-神经网络交易协调层/runtime/degraded_events.jsonl"
        if dg_path.exists():
            degraded_n = sum(
                1
                for rec in _iter_jsonl_since(dg_path, _now() - 3600)
                if str(rec.get("layer")) == "50"
                and str(rec.get("source")) == "constraint_loader"
                and str(rec.get("reason") or "") not in benign
            )
            out.append(_metric("main_nn_constraint_degraded_1h", degraded_n))

        # M13 执行复核（22 x1_live_processed.json 幂等状态）
        st = _read_json(
            self.repo / str(ex.get("x1_state", "22-执行引擎中心/runtime/x1_live_processed.json"))
        )
        processed = st.get("processed") if isinstance(st.get("processed"), dict) else {}
        reasons: dict[str, int] = {}
        for item in processed.values():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "unknown")
            reason = str(item.get("reason") or "")
            key = status if not reason else f"{status}:{reason}"
            reasons[key] = reasons.get(key, 0) + 1
        for key, n in sorted(reasons.items()):
            out.append(_metric("main_nn_x1_skip_total", n, reason=key))

        # P2 资金安全：决策→成交 join 与下单保护附带率（离线可算，不查交易所）
        # live_ids 来自 decisions.jsonl（v2.31 起 make_decision 落盘即带 decision_id）
        fills_path = self.repo / str(ex.get("fills", "22-执行引擎中心/audit/x1_live_fills.jsonl"))
        filled_ids: set[str] = set()
        placed = attached = 0
        if fills_path.exists():
            for rec in _iter_jsonl_since(fills_path, _now() - 86400):
                if not rec.get("order_placed"):
                    continue
                placed += 1
                if rec.get("decision_id"):
                    filled_ids.add(str(rec["decision_id"]))
                request = rec.get("request") if isinstance(rec.get("request"), dict) else {}
                try:
                    if (
                        float(request.get("sl_pct") or 0) > 0
                        and float(request.get("tp_pct") or 0) > 0
                    ):
                        attached += 1
                except (TypeError, ValueError):
                    pass
        # 口径：24h 成交中可按 decision_id 回溯到 50 live outbox 的占比（可回溯率）
        if filled_ids:
            out.append(
                _metric(
                    "main_nn_decision_fill_join_ratio",
                    round(len(filled_ids & live_ids) / len(filled_ids), 4),
                )
            )
        if placed:
            out.append(_metric("main_nn_fill_sltp_attach_ratio", round(attached / placed, 4)))

        # M0–M14 链路事件（仅 source=main-nn）
        cutoff_24h = _now() - 86400
        stage_counts: dict[tuple[str, str], int] = {}
        chains: dict[str, set[str]] = {}
        wait_total = wait_broken = 0
        for rel in (
            "50-NN主矛盾评估器/runtime",
            "22-执行引擎中心/runtime",
            "43-战略承接推演层/runtime",
            "42-神经网络交易协调层/runtime",
            "40-周期神经网络系统/runtime",
        ):
            folder = self.repo / rel
            if not folder.exists():
                continue
            for path in sorted(folder.glob("chain_events-*.jsonl"))[-2:]:
                for rec in _iter_jsonl_since(path, cutoff_24h):
                    if str(rec.get("source") or "") != src:
                        continue
                    stage = str(rec.get("stage") or "?")
                    status = str(rec.get("status") or "?")
                    stage_counts[(stage, status)] = stage_counts.get((stage, status), 0) + 1
                    cid = str(
                        rec.get("chain_id") or rec.get("trace_id") or rec.get("decision_id") or ""
                    )
                    if cid:
                        chains.setdefault(cid, set()).add(stage)
                    if status == "skip":
                        wait_total += 1
                        data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
                        reason = str(
                            rec.get("reason_category") or data.get("reason_category") or ""
                        )
                        if not reason.strip():
                            wait_broken += 1
        # 独立命名：23 的 chain_* series 无 source 标签，复用同名会导致既有规则串台
        for (stage, status), n in sorted(stage_counts.items()):
            out.append(
                _metric("main_nn_chain_stage_total", n, source=src, stage=stage, status=status)
            )
        # 口径：分母只取"已出箱(M12)的 live 决策链"。M6 只是总线读证据，WAIT/未出箱
        # 属主动终止（由 wait_vs_broken 单独度量），计入分母会把正常 WAIT 误判为断链。
        signal_chains = [stages for stages in chains.values() if "M12" in stages]
        if signal_chains:
            complete = sum(1 for stages in signal_chains if {"M12", "M13"} <= stages)
            out.append(
                _metric(
                    "main_nn_chain_completion_ratio",
                    round(complete / len(signal_chains), 4),
                    source=src,
                    segment="M6-M13",
                )
            )
            for required in ("M7", "M11", "M13"):
                missing = sum(1 for stages in signal_chains if required not in stages)
                out.append(
                    _metric(
                        "main_nn_chain_missing_stage_total", missing, source=src, stage=required
                    )
                )
        if wait_total:
            out.append(
                _metric(
                    "main_nn_wait_vs_broken_ratio", round(wait_broken / wait_total, 4), source=src
                )
            )
            out.append(_metric("main_nn_chain_broken_total", wait_broken, source=src))
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
            self.main_nn_metrics(),
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
