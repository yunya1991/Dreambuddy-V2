# -*- coding: utf-8 -*-
"""
repo.py — 评测存储层（P0-5）
=============================
职责（PLAN P0-5 验收 / SPEC §12）：
- EvalRepo 接口：受理（兼容 Gateway 的 EvalRequestStore）、Run、证据链、报告
- InMemoryRepo：单测 / 本地空跑；PgRepo：PostgreSQL（psycopg3）
- get_report 从规范化行重建 eval_report.v1.json 结构（两实现共用装配逻辑）

约束：
- DSN 清洗：去除 Prisma 专有 ?schema= 参数（认知经验 VM-1791981667092）
- eval_requests 无 spec_hash 列（§12）：读取时按占位规则由 spec_id 重算，
  TODO(P2-9)：spec 注册表落地后以 eval_runs.spec_hash 为准
- eval_reports.ci 仅 lower/upper 两列：重建时 method 固定 "none"，
  TODO(P1.5)：CI 方法列随统计校准落地补充
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from core.gateway import (
    EvalRequestRecord,
    InMemoryEvalRequestStore,
    spec_hash_placeholder,
)

logger = logging.getLogger(__name__)

CREDENTIAL_TTL_DAYS = 7  # §4 凭证默认有效期


# ---------- DSN 清洗 ----------


def clean_dsn(dsn: str) -> str:
    """去除 Prisma 专有查询参数（psycopg 遇 ?schema= 报 invalid dsn）。

    兼容 schema 位于查询串任意位置（首参 / 中间 / 末尾）。
    """
    cleaned = re.sub(r"[?&]schema=[^&]*", lambda m: "?" if m.group(0).startswith("?") else "", dsn)
    return cleaned.replace("?&", "?").rstrip("?")


# ---------- 记录 ----------


@dataclass(frozen=True)
class EvalRunRecord:
    """一次不可变评测执行（§3.2 eval_runs）。"""

    run_id: str
    eval_id: str
    evaluator_id: str
    evaluator_version: str
    scorer_versions: dict[str, Any] | None
    attempt: int
    spec_hash: str
    code_commit: str | None
    env_snapshot: dict[str, Any] | None
    budget_ms: int | None
    degraded: bool
    started_at: datetime | None
    ended_at: datetime | None
    status: str  # running / succeeded / failed / cancelled / timeout


@dataclass(frozen=True)
class EvalItemRecord:
    """评测项级结果（§4 eval_items）。"""

    item_id: str
    run_id: str
    name: str
    kind: str  # hard / weighted / reference
    score: float | None
    n: int | None
    ci_lower: float | None
    ci_upper: float | None
    weight: float | None
    status: str  # PASS / BLOCK / INCONCLUSIVE / TIMEOUT / SKIPPED
    evidence_id: str | None
    detail: str | None


@dataclass(frozen=True)
class EvidenceRow:
    """证据链条目（§2.1 evidence）。"""

    evidence_id: str
    run_id: str
    sha256: str
    uri: str
    prev_hash: str | None
    hash: str
    signed_by: str | None
    created_at: datetime


# ---------- 时间 / 哈希工具 ----------


def zulu(dt: datetime) -> str:
    """UTC Z 格式（契约 evaluated_at/expires_at 模式）。"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_zulu(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def canonical_json(obj: Any) -> str:
    def _default(o: Any) -> Any:
        if isinstance(o, datetime):
            return zulu(o)
        raise TypeError(f"不可序列化: {type(o).__name__}")

    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------- 报告行 <-> 报告字典 ----------


def report_to_row(report: dict[str, Any]) -> dict[str, Any]:
    """报告字典 → eval_reports 行（规范化存储）。"""
    ci = report.get("ci")
    return {
        "eval_id": report["eval_id"],
        "run_id": report["run_id"],
        "verdict": report["verdict"],
        "score": report.get("score"),
        "n": report.get("n"),
        "ci_lower": ci["lower"] if ci else None,
        "ci_upper": ci["upper"] if ci else None,
        "thresholds_version": report["thresholds_version"],
        "baseline_run_id": report.get("baseline_run_id"),
        "block_reasons": list(report.get("block_reasons", [])),
        "report_uri": f"local://reports/{report['eval_id']}.json",
        "report_sha256": sha256_hex(canonical_json(report)),
        "decided_at": parse_zulu(report["evaluated_at"]),
    }


def assemble_report(
    report_row: dict[str, Any],
    run_row: dict[str, Any],
    item_rows: list[dict[str, Any]],
    evidence_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """规范化行 → eval_report.v1.json 字典（InMemory/PG 共用）。

    evidence_row 缺失即 LookupError：报告无证据违反 §2.1 Evidence-First。
    """
    if evidence_row is None:
        raise LookupError(f"报告 {report_row['eval_id']} 缺证据行（§2.1）")
    decided_at: datetime = report_row["decided_at"]
    ci = None
    if report_row["ci_lower"] is not None:
        ci = {
            "lower": report_row["ci_lower"],
            "upper": report_row["ci_upper"],
            "method": "none",  # TODO(P1.5): method 列随统计校准落地
        }
    sla = None
    if run_row.get("budget_ms") is not None:
        started, ended = run_row.get("started_at"), run_row.get("ended_at")
        elapsed = int((ended - started).total_seconds() * 1000) if started and ended else 0
        sla = {
            "budget_ms": run_row["budget_ms"],
            "elapsed_ms": elapsed,
            "degraded": bool(run_row.get("degraded", False)),
        }
    return {
        "eval_id": report_row["eval_id"],
        "run_id": report_row["run_id"],
        "spec_hash": run_row["spec_hash"],
        "verdict": report_row["verdict"],
        "score": report_row["score"],
        "n": report_row["n"],
        "ci": ci,
        "items": [
            {
                "name": r["name"],
                "kind": r["kind"],
                "status": r["status"],
                "score": r["score"],
                "n": r["n"],
                "ci_lower": r["ci_lower"],
                "ci_upper": r["ci_upper"],
                "weight": r["weight"],
                "evidence_id": r["evidence_id"],
                "detail": r["detail"],
            }
            for r in sorted(item_rows, key=lambda r: r["item_id"])
        ],
        "block_reasons": list(report_row["block_reasons"]),
        "evidence": {"uri": evidence_row["uri"], "sha256": evidence_row["sha256"]},
        "thresholds_version": report_row["thresholds_version"],
        "baseline_run_id": report_row["baseline_run_id"],
        "baseline_diff": None,  # P0 未启用回归比对（§8.3 属后续里程碑）
        "sla": sla,
        "evaluated_at": zulu(decided_at),
        "expires_at": zulu(decided_at + timedelta(days=CREDENTIAL_TTL_DAYS)),
    }


# ---------- 接口 ----------


class EvalRepo(Protocol):
    """评测存储接口（InMemory / PG 两实现）。"""

    # 受理
    def insert_request(self, record: EvalRequestRecord) -> None: ...
    def get_by_idempotency_key(self, key: str) -> EvalRequestRecord | None: ...
    def get_request(self, eval_id: str) -> EvalRequestRecord | None: ...
    def count_for_day(self, day: str) -> int: ...
    def update_status(self, eval_id: str, status: str) -> bool: ...
    def list_requests(
        self,
        submitter: str | None = None,
        category: str | None = None,
        verdict: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...

    # Run
    def insert_run(self, run: EvalRunRecord) -> None: ...
    def get_run(self, run_id: str) -> EvalRunRecord | None: ...
    def latest_run_for_eval(self, eval_id: str) -> EvalRunRecord | None: ...

    # 评测项
    def insert_items(self, items: list[EvalItemRecord]) -> None: ...
    def list_items(self, run_id: str) -> list[EvalItemRecord]: ...

    # 证据链
    def insert_evidence(self, entry: EvidenceRow) -> None: ...
    def list_evidence(self, run_id: str) -> list[EvidenceRow]: ...
    def count_evidence(self, run_id: str) -> int: ...
    def latest_evidence_hash(self, run_id: str) -> str | None: ...

    # 报告
    def insert_report(self, report: dict[str, Any]) -> None: ...
    def get_report(self, eval_id: str) -> dict[str, Any] | None: ...


# ---------- 内存实现 ----------


class InMemoryRepo(InMemoryEvalRequestStore):
    """内存实现：单测与 API 契约测试（TestClient）后端。"""

    def __init__(self) -> None:
        super().__init__()
        self._runs: dict[str, EvalRunRecord] = {}
        self._items: dict[str, list[EvalItemRecord]] = {}
        self._evidence: dict[str, list[EvidenceRow]] = {}
        self._report_rows: dict[str, dict[str, Any]] = {}

    # 受理
    def insert_request(self, record: EvalRequestRecord) -> None:
        self.insert(record)

    def get_request(self, eval_id: str) -> EvalRequestRecord | None:
        return self._by_id.get(eval_id)

    def update_status(self, eval_id: str, status: str) -> bool:
        record = self._by_id.get(eval_id)
        if record is None:
            return False
        updated = replace(record, status=status)
        self._by_id[eval_id] = updated
        self._by_key[record.idempotency_key] = updated
        return True

    def list_requests(
        self,
        submitter: str | None = None,
        category: str | None = None,
        verdict: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = []
        for r in self._by_id.values():
            if submitter is not None and r.submitter != submitter:
                continue
            if category is not None and r.category != category:
                continue
            if from_dt is not None and r.created_at < from_dt:
                continue
            if to_dt is not None and r.created_at > to_dt:
                continue
            report_row = self._report_rows.get(r.eval_id)
            row_verdict = report_row["verdict"] if report_row else None
            if verdict is not None and row_verdict != verdict:
                continue
            rows.append(
                {
                    "eval_id": r.eval_id,
                    "submitter": r.submitter,
                    "category": r.category,
                    "object_type": r.object_type,
                    "purpose": r.purpose,
                    "priority": r.priority,
                    "status": r.status,
                    "verdict": row_verdict,
                    "created_at": r.created_at,
                }
            )
        rows.sort(key=lambda x: x["created_at"], reverse=True)
        return rows[: max(1, min(limit, 1000))]

    # Run
    def insert_run(self, run: EvalRunRecord) -> None:
        if run.run_id in self._runs:
            raise ValueError(f"run_id 冲突: {run.run_id}")
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> EvalRunRecord | None:
        return self._runs.get(run_id)

    def latest_run_for_eval(self, eval_id: str) -> EvalRunRecord | None:
        runs = [r for r in self._runs.values() if r.eval_id == eval_id]
        return max(runs, key=lambda r: r.attempt, default=None)

    # 评测项
    def insert_items(self, items: list[EvalItemRecord]) -> None:
        for item in items:
            self._items.setdefault(item.run_id, []).append(item)

    def list_items(self, run_id: str) -> list[EvalItemRecord]:
        return sorted(self._items.get(run_id, []), key=lambda i: i.item_id)

    # 证据链
    def insert_evidence(self, entry: EvidenceRow) -> None:
        chain = self._evidence.setdefault(entry.run_id, [])
        if any(e.hash == entry.hash for e in chain):
            raise ValueError(f"证据哈希冲突: {entry.hash}")
        chain.append(entry)

    def list_evidence(self, run_id: str) -> list[EvidenceRow]:
        return sorted(
            self._evidence.get(run_id, []),
            key=lambda e: (e.created_at, e.evidence_id),
        )

    def count_evidence(self, run_id: str) -> int:
        return len(self._evidence.get(run_id, []))

    def latest_evidence_hash(self, run_id: str) -> str | None:
        chain = self.list_evidence(run_id)
        return chain[-1].hash if chain else None

    # 报告
    def insert_report(self, report: dict[str, Any]) -> None:
        row = report_to_row(report)
        if row["eval_id"] in self._report_rows:
            raise ValueError(f"报告已存在: {row['eval_id']}")
        self._report_rows[row["eval_id"]] = row

    def get_report(self, eval_id: str) -> dict[str, Any] | None:
        row = self._report_rows.get(eval_id)
        if row is None:
            return None
        run = self._runs.get(row["run_id"])
        if run is None:
            raise LookupError(f"报告 {eval_id} 缺 Run 行")
        evidence = self.list_evidence(row["run_id"])
        return assemble_report(
            report_row=dict(row),
            run_row=asdict(run),
            item_rows=[asdict(i) for i in self.list_items(row["run_id"])],
            evidence_row=asdict(evidence[0]) if evidence else None,
        )


# ---------- PostgreSQL 实现 ----------


class PgRepo:  # pragma: no cover — PG 专属实现，本地无库；集成用例需 EVAL_PG_DSN（CI/云端执行）
    """PostgreSQL 实现（psycopg3）：每方法短连接，连接池属 P1 优化。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = clean_dsn(dsn)

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(self._dsn, row_factory=dict_row)

    # 受理
    def insert_request(self, record: EvalRequestRecord) -> None:
        from psycopg.types.json import Jsonb

        sql = """
            INSERT INTO eval_requests
                (eval_id, idempotency_key, category, object_type, purpose,
                 priority, object_ref, submitter, env_manifest, spec_id,
                 status, created_at)
            VALUES
                (%(eval_id)s, %(idempotency_key)s, %(category)s, %(object_type)s,
                 %(purpose)s, %(priority)s, %(object_ref)s, %(submitter)s,
                 %(env_manifest)s, %(spec_id)s, %(status)s, %(created_at)s)
        """
        params = asdict(record)
        params["env_manifest"] = Jsonb(record.env_manifest)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)

    def get_by_idempotency_key(self, key: str) -> EvalRequestRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM eval_requests WHERE idempotency_key = %s", (key,)
            ).fetchone()
        return self._row_to_request(row) if row else None

    def get_request(self, eval_id: str) -> EvalRequestRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM eval_requests WHERE eval_id = %s", (eval_id,)
            ).fetchone()
        return self._row_to_request(row) if row else None

    @staticmethod
    def _row_to_request(row: dict[str, Any]) -> EvalRequestRecord:
        return EvalRequestRecord(
            eval_id=row["eval_id"],
            idempotency_key=row["idempotency_key"],
            object_ref=row["object_ref"],
            category=row["category"],
            object_type=row["object_type"],
            submitter=row["submitter"],
            purpose=row["purpose"],
            priority=row["priority"],
            spec_id=row["spec_id"],
            env_manifest=row["env_manifest"],
            # eval_requests 无 spec_hash 列（§12）：按占位规则重算（P2-9 后以 run 为准）
            spec_hash=spec_hash_placeholder(row["spec_id"]),
            status=row["status"],
            created_at=row["created_at"],
        )

    def count_for_day(self, day: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                "SELECT count(*) AS c FROM eval_requests WHERE eval_id LIKE %s",
                (f"EV-{day}-%",),
            ).fetchone()
        return int(row["c"])

    def update_status(self, eval_id: str, status: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE eval_requests SET status = %s, updated_at = now()" " WHERE eval_id = %s",
                (status, eval_id),
            )
            return cur.rowcount > 0

    def list_requests(
        self,
        submitter: str | None = None,
        category: str | None = None,
        verdict: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT r.eval_id, r.submitter, r.category, r.object_type, r.purpose,
                   r.priority, r.status, p.verdict, r.created_at
            FROM eval_requests r
            LEFT JOIN eval_reports p ON p.eval_id = r.eval_id
            WHERE (CAST(%s AS text) IS NULL OR r.submitter = %s)
              AND (CAST(%s AS text) IS NULL OR r.category = %s)
              AND (CAST(%s AS timestamptz) IS NULL OR r.created_at >= %s)
              AND (CAST(%s AS timestamptz) IS NULL OR r.created_at <= %s)
              AND (CAST(%s AS text) IS NULL OR p.verdict = %s)
            ORDER BY r.created_at DESC
            LIMIT %s
        """
        limit = max(1, min(int(limit), 1000))
        params = (
            submitter,
            submitter,
            category,
            category,
            from_dt,
            from_dt,
            to_dt,
            to_dt,
            verdict,
            verdict,
            limit,
        )
        with self._connect() as conn, conn.cursor() as cur:
            return list(cur.execute(sql, params).fetchall())

    # Run
    def insert_run(self, run: EvalRunRecord) -> None:
        from psycopg.types.json import Jsonb

        sql = """
            INSERT INTO eval_runs
                (run_id, eval_id, evaluator_id, evaluator_version,
                 scorer_versions, attempt, spec_hash, code_commit, env_snapshot,
                 budget_ms, degraded, started_at, ended_at, status)
            VALUES
                (%(run_id)s, %(eval_id)s, %(evaluator_id)s, %(evaluator_version)s,
                 %(scorer_versions)s, %(attempt)s, %(spec_hash)s, %(code_commit)s,
                 %(env_snapshot)s, %(budget_ms)s, %(degraded)s, %(started_at)s,
                 %(ended_at)s, %(status)s)
        """
        params = asdict(run)
        params["scorer_versions"] = (
            Jsonb(run.scorer_versions) if run.scorer_versions is not None else None
        )
        params["env_snapshot"] = Jsonb(run.env_snapshot) if run.env_snapshot is not None else None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)

    def get_run(self, run_id: str) -> EvalRunRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute("SELECT * FROM eval_runs WHERE run_id = %s", (run_id,)).fetchone()
        return EvalRunRecord(**row) if row else None

    def latest_run_for_eval(self, eval_id: str) -> EvalRunRecord | None:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM eval_runs WHERE eval_id = %s" " ORDER BY attempt DESC LIMIT 1",
                (eval_id,),
            ).fetchone()
        return EvalRunRecord(**row) if row else None

    # 评测项
    def insert_items(self, items: list[EvalItemRecord]) -> None:
        from psycopg.types.json import Jsonb

        sql = """
            INSERT INTO eval_items
                (item_id, run_id, name, kind, score, n, ci_lower, ci_upper,
                 weight, status, evidence_id, detail)
            VALUES
                (%(item_id)s, %(run_id)s, %(name)s, %(kind)s, %(score)s, %(n)s,
                 %(ci_lower)s, %(ci_upper)s, %(weight)s, %(status)s,
                 %(evidence_id)s, %(detail)s)
        """
        with self._connect() as conn, conn.cursor() as cur:
            for item in items:
                params = asdict(item)
                params["detail"] = Jsonb(item.detail) if item.detail else None
                cur.execute(sql, params)

    def list_items(self, run_id: str) -> list[EvalItemRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM eval_items WHERE run_id = %s ORDER BY item_id",
                (run_id,),
            ).fetchall()
        return [EvalItemRecord(**r) for r in rows]

    # 证据链
    def insert_evidence(self, entry: EvidenceRow) -> None:
        sql = """
            INSERT INTO evidence
                (evidence_id, run_id, sha256, uri, prev_hash, hash,
                 signed_by, created_at)
            VALUES
                (%(evidence_id)s, %(run_id)s, %(sha256)s, %(uri)s, %(prev_hash)s,
                 %(hash)s, %(signed_by)s, %(created_at)s)
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, asdict(entry))

    def list_evidence(self, run_id: str) -> list[EvidenceRow]:
        with self._connect() as conn, conn.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM evidence WHERE run_id = %s" " ORDER BY created_at, evidence_id",
                (run_id,),
            ).fetchall()
        return [EvidenceRow(**r) for r in rows]

    def count_evidence(self, run_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                "SELECT count(*) AS c FROM evidence WHERE run_id = %s", (run_id,)
            ).fetchone()
        return int(row["c"])

    def latest_evidence_hash(self, run_id: str) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                "SELECT hash FROM evidence WHERE run_id = %s"
                " ORDER BY created_at DESC, evidence_id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return row["hash"] if row else None

    # 报告
    def insert_report(self, report: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        row = report_to_row(report)
        sql = """
            INSERT INTO eval_reports
                (eval_id, run_id, verdict, score, n, ci_lower, ci_upper,
                 thresholds_version, baseline_run_id, block_reasons,
                 report_uri, report_sha256, decided_at)
            VALUES
                (%(eval_id)s, %(run_id)s, %(verdict)s, %(score)s, %(n)s,
                 %(ci_lower)s, %(ci_upper)s, %(thresholds_version)s,
                 %(baseline_run_id)s, %(block_reasons)s, %(report_uri)s,
                 %(report_sha256)s, %(decided_at)s)
        """
        row["block_reasons"] = Jsonb(row["block_reasons"])
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, row)

    def get_report(self, eval_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT p.*, r.spec_hash, r.budget_ms, r.degraded,
                       r.started_at, r.ended_at
                FROM eval_reports p
                JOIN eval_runs r ON r.run_id = p.run_id
                WHERE p.eval_id = %s
                """,
                (eval_id,),
            ).fetchone()
            if row is None:
                return None
            run_row = {
                "spec_hash": row.pop("spec_hash"),
                "budget_ms": row.pop("budget_ms"),
                "degraded": row.pop("degraded"),
                "started_at": row.pop("started_at"),
                "ended_at": row.pop("ended_at"),
            }
            item_rows = list(
                cur.execute(
                    "SELECT * FROM eval_items WHERE run_id = %s ORDER BY item_id",
                    (row["run_id"],),
                ).fetchall()
            )
            evidence_row = cur.execute(
                "SELECT * FROM evidence WHERE run_id = %s"
                " ORDER BY created_at, evidence_id LIMIT 1",
                (row["run_id"],),
            ).fetchone()
        return assemble_report(
            report_row=row,
            run_row=run_row,
            item_rows=item_rows,
            evidence_row=evidence_row,
        )


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
