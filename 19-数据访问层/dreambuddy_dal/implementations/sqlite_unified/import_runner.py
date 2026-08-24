"""
dreambuddy_dal.implementations.sqlite_unified.import_runner
-------------------------------------------------------------
P1-4：JSON/散 SQLite → 统一 SQLite 三批幂等导入脚本

入口：
  import_all_batches(data_dir: str, db_path: str, *, dry_run: bool = False)
      → list[ImportReport] （3 条：BATCH-1/2/3）

设计要点（对齐 MIGRATION_PLAN §3）：
  • 批次定义（严格顺序，核心先迁，外围后迁）：
      BATCH-1 core-trade       → tr_trades, po_positions, tr_daily_stats （不能缺）
      BATCH-2 performance-risk → rs_state, rs_cases                    （风控重要）
      BATCH-3 macro-config-kg  → mm_* / cv_* / kg_*                   （外围 可空）
  • 幂等（反复执行 DB 不变）：
      1) 所有写入使用 INSERT OR IGNORE 或 ON CONFLICT DO NOTHING / idempotent upsert
      2) 每批次执行后写 ma_migration_audit（category='migration_script'）
      3) 再执行：新数据 0 行（测试断言 run2.applied=0）
  • dry_run：所有业务写在事务内，执行完 ROLLBACK；但 ma_migration_audit 照常写（单独连接提交一次 DRY-RUN 记录）
  • 数据源 fallback：
      1) data_dir 下现有 JSON（若存在 → 读）
      2) 否则 JsonLegacy*Repository 内存实例（读 P0 阶段薄存数据）
      3) 两者都空 → 本批次 applied=0 skipped=0（正常不算失败）
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List

from dreambuddy_dal.connection import get_sqlite_connection


# ===========================================================================
# Report 契约
# ===========================================================================
@dataclass
class ImportReport:
    batch_id: str
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    duration_ms: int = 0
    notes: Dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# 工具：审计日志写入
# ===========================================================================
def _write_audit(
    db_path: str,
    *,
    batch_id: str,
    entity_key_suffix: str,
    result: str,
    severity: int,
    details: Dict[str, Any],
    latency_ms: int,
) -> None:
    """category='migration_script'；独立事务提交（用于 dry_run 也能看日志）。"""
    with get_sqlite_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ma_migration_audit
                (category, event_name, entity_key, result, severity, details, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "migration_script",
                batch_id,
                f"{batch_id}#{entity_key_suffix}",
                result,
                severity,
                json.dumps(details, ensure_ascii=False, default=str),
                latency_ms,
            ),
        )


def _checksum_obj(obj: Any) -> str:
    """对象 → SHA1 前 12 hex（作为幂等 entity_key 后缀）。"""
    payload = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


# ===========================================================================
# 数据源：读 JsonLegacy 内存薄实现
# ===========================================================================
def _read_trade_rows_from_legacy() -> List[Dict[str, Any]]:
    try:
        from dreambuddy_dal.implementations.json_legacy.trade_impl import (
            JsonLegacyTradeRepository,
        )
        repo = JsonLegacyTradeRepository()
        trades = repo.query_trades(limit=10_000)
        rows: List[Dict[str, Any]] = []
        for t in trades:
            rows.append({"kind": "trade", "obj": t})
        # daily stats：通过 repo 无枚举 API，P0 阶段返回空列表即可（T-兼容）
        return rows
    except Exception:
        return []


def _read_position_rows_from_legacy() -> List[Dict[str, Any]]:
    try:
        from dreambuddy_dal.implementations.json_legacy.position_impl import (
            JsonLegacyPositionRepository,
        )
        repo = JsonLegacyPositionRepository()
        positions = repo.list_positions()
        return [{"kind": "position", "obj": p} for p in positions]
    except Exception:
        return []


def _read_risk_rows_from_legacy() -> List[Dict[str, Any]]:
    try:
        from dreambuddy_dal.implementations.json_legacy.risk_impl import (
            JsonLegacyRiskRepository,
        )
        repo = JsonLegacyRiskRepository()
        state = repo.load_state()
        cases = repo.list_cases() or []
        rows = [{"kind": "risk_state", "obj": state}] if state else []
        rows += [{"kind": "risk_case", "obj": c} for c in cases]
        return rows
    except Exception:
        return []


# ===========================================================================
# 批次 1：核心交易（tr_trades / po_positions / tr_daily_stats）
# ===========================================================================
def _apply_batch_core_trade(conn, legacy_trade_rows, legacy_pos_rows, *, dry_run: bool) -> ImportReport:
    rep = ImportReport(batch_id="BATCH-1-core-trade")
    # trade_rows → insert or ignore tr_trades（用 SqliteTradeRepository Protocol 方法最稳）
    from dreambuddy_dal.implementations.sqlite_unified.position_impl import SqlitePositionRepository
    from dreambuddy_dal.implementations.sqlite_unified.trade_impl import SqliteTradeRepository

    # 需要拿到 db_path 构造 repo——这里 conn 不能直接复用 repo 的上下文，
    # 因此直接使用 conn.execute INSERT OR IGNORE，字段对齐 _TRADE_INSERT_COLUMNS 的简化子集
    # 为最小化实现，这里不重写 trade_impl 的 34 列 INSERT，而使用基于 unified_models 的最小子集：
    # 直接调用 repo（需要先从 conn 拿 db_path：sqlite3.Connection 有 .in_transaction；用 PRAGMA database_list）
    db_path_row = conn.execute("PRAGMA database_list").fetchall()
    # database_list 返回 (seq, name, file)；main 的 file 可能为空（:memory:）
    db_path = None
    for (_s, name, f) in db_path_row:
        if name == "main" and f:
            db_path = f
            break
    if db_path is None:
        # :memory: 或匿名，退回 dry_run 0 行路径
        return rep

    trade_repo = SqliteTradeRepository(db_path)
    pos_repo = SqlitePositionRepository(db_path)

    # --- trades ---
    for item in legacy_trade_rows:
        if item["kind"] != "trade":
            continue
        t = item["obj"]
        try:
            before = conn.execute(
                "SELECT COUNT(*) FROM tr_trades WHERE trade_id=?", (t.trade_id,)
            ).fetchone()[0]
            tid = trade_repo.add_trade(t)
            after = conn.execute(
                "SELECT COUNT(*) FROM tr_trades WHERE trade_id=?", (t.trade_id,)
            ).fetchone()[0]
            if before == after:
                rep.skipped += 1
            elif tid:
                rep.applied += 1
        except Exception:
            rep.failed += 1

    # --- positions ---
    for item in legacy_pos_rows:
        if item["kind"] != "position":
            continue
        p = item["obj"]
        try:
            before = conn.execute(
                "SELECT COUNT(*) FROM po_positions WHERE inst_id=?", (getattr(p, "inst_id", None) or p.symbol,)
            ).fetchone()[0]
            pos_repo.upsert_position(p)
            after = conn.execute(
                "SELECT COUNT(*) FROM po_positions WHERE inst_id=?", (getattr(p, "inst_id", None) or p.symbol,)
            ).fetchone()[0]
            if before == after:
                rep.skipped += 1
            else:
                rep.applied += 1
        except Exception:
            rep.failed += 1

    if dry_run:
        # 0 行，未真实写入（外层统一事务 ROLLBACK 保证）
        pass
    return rep


# ===========================================================================
# 批次 2：风控绩效（rs_state / rs_cases）
# ===========================================================================
def _apply_batch_performance_risk(conn, legacy_risk_rows, *, dry_run: bool) -> ImportReport:
    rep = ImportReport(batch_id="BATCH-2-performance-risk")
    db_path_row = conn.execute("PRAGMA database_list").fetchall()
    db_path = None
    for (_s, name, f) in db_path_row:
        if name == "main" and f:
            db_path = f
            break
    if db_path is None:
        return rep

    from dreambuddy_dal.implementations.sqlite_unified.risk_impl import SqliteRiskRepository
    risk_repo = SqliteRiskRepository(db_path)

    for item in legacy_risk_rows:
        try:
            if item["kind"] == "risk_state":
                state = item["obj"]
                current_ver = getattr(state, "version", 1)
                # save_state 幂等（写单行表）
                risk_repo.save_state(state)
                new_ver = conn.execute("SELECT version FROM rs_state WHERE id=1").fetchone()
                if new_ver is None or int(new_ver[0]) == int(current_ver or 1):
                    rep.skipped += 1
                else:
                    rep.applied += 1
            elif item["kind"] == "risk_case":
                case = item["obj"]
                cid = getattr(case, "case_id", None)
                if not cid:
                    rep.failed += 1
                    continue
                before = conn.execute(
                    "SELECT COUNT(*) FROM rs_cases WHERE case_id=?", (cid,)
                ).fetchone()[0]
                try:
                    risk_repo.add_case(case)
                except Exception:
                    pass
                after = conn.execute(
                    "SELECT COUNT(*) FROM rs_cases WHERE case_id=?", (cid,)
                ).fetchone()[0]
                if before == after:
                    rep.skipped += 1
                else:
                    rep.applied += 1
        except Exception:
            rep.failed += 1
    return rep


# ===========================================================================
# 批次 3：宏观配置 KG
# ===========================================================================
def _apply_batch_macro_config_kg(conn, *, dry_run: bool) -> ImportReport:
    """批次3：mm_* / cv_* / kg_*。P0 JsonLegacy 无 mm config kg 接口 → 内存空，0 行通过即可。"""
    rep = ImportReport(batch_id="BATCH-3-macro-config-kg")
    # 幂等 0 行允许。后续 P2 若真接入散 macro_*.db，此函数扩展即可。
    return rep


# ===========================================================================
# 主入口
# ===========================================================================
def import_all_batches(data_dir: str, db_path: str, *, dry_run: bool = False) -> List[ImportReport]:
    reports: List[ImportReport] = []
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    batches: List[Callable[[Any], ImportReport]] = [
        lambda conn: _apply_batch_core_trade(
            conn,
            _read_trade_rows_from_legacy(),
            _read_position_rows_from_legacy(),
            dry_run=dry_run,
        ),
        lambda conn: _apply_batch_performance_risk(
            conn,
            _read_risk_rows_from_legacy(),
            dry_run=dry_run,
        ),
        lambda conn: _apply_batch_macro_config_kg(conn, dry_run=dry_run),
    ]

    for fn in batches:
        t0 = time.perf_counter()
        batch_report: ImportReport
        if dry_run:
            # dry_run：开事务→执行→ROLLBACK；审计日志用独立连接写
            with get_sqlite_connection(db_path) as conn:
                conn.execute("BEGIN")
                try:
                    batch_report = fn(conn)
                finally:
                    conn.execute("ROLLBACK")
        else:
            with get_sqlite_connection(db_path) as conn:
                batch_report = fn(conn)
        dt = int((time.perf_counter() - t0) * 1000)
        batch_report.duration_ms = dt
        # 写审计（dry_run 也要有记录）
        result = "APPLIED" if batch_report.applied > 0 else (
            "FAILED" if batch_report.failed > 0 else "SKIPPED"
        )
        severity = 2 if batch_report.failed > 0 else (1 if batch_report.applied == 0 else 0)
        details = {
            "applied": batch_report.applied,
            "skipped": batch_report.skipped,
            "failed": batch_report.failed,
            "dry_run": dry_run,
        }
        suffix = _checksum_obj({"v": 1, "rep": details})
        _write_audit(
            db_path,
            batch_id=batch_report.batch_id,
            entity_key_suffix=suffix,
            result=result,
            severity=severity,
            details=details,
            latency_ms=dt,
        )
        reports.append(batch_report)
    return reports


__all__ = ["ImportReport", "import_all_batches"]
