# -*- coding: utf-8 -*-
"""
reporter.py — 评测报告归档（P0-5）
===================================
职责（PLAN P0-5 验收 / SPEC §2.1/§4）：
- finalize：证据链 → 判定合成（§4 三态优先级）→ 契约校验 → 入库
- finalize_empty：空评测收尾（P0 骨架；P1-2 runner 落地后由 runner 供 run/items）
- 证据哈希链：hash = sha256(prev_hash || sha256 || uri)，首条 prev_hash=None

判定语义（§4）：
- 任一 BLOCK → BLOCK；否则任一 INCONCLUSIVE/TIMEOUT → INCONCLUSIVE
- 空 items 或全部 SKIPPED → INCONCLUSIVE（fail-closed，§2.4）
- 其余 → PASS；score = Σ w_i × score_i（加权项），n 取加权项最小样本量（保守）

出厂自检：报告落库前必须通过 eval_report.v1.json 契约校验，
内部生成物违反契约即 ReporterError（Evidence-First 硬保证）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from storage.evidence import append_entry
from storage.repo import (
    CREDENTIAL_TTL_DAYS,
    EvalItemRecord,
    EvalRepo,
    EvalRunRecord,
    EvidenceRow,
    zulu,
)

from core.registry import ThresholdRegistry

logger = logging.getLogger(__name__)

REPORT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "contracts" / "schemas" / "eval_report.v1.json"
)


class ReporterError(Exception):
    """报告归档失败：未知 eval_id / 内部产物违反契约等。"""


class Reporter:
    """评测报告构建与归档。"""

    def __init__(
        self,
        repo: EvalRepo,
        thresholds: ThresholdRegistry,
        clock: Callable[[], datetime] | None = None,
        schema_path: str | Path = REPORT_SCHEMA_PATH,
        signed_by: str | None = None,
    ) -> None:
        self._repo = repo
        self._thresholds = thresholds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._signed_by = signed_by
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        self._validator = Draft202012Validator(schema)

    def finalize_empty(self, eval_id: str) -> dict[str, Any]:
        """空评测收尾：占位 run + 空 items → INCONCLUSIVE 报告（fail-closed）。

        P0 骨架：P1-2 runner 落地后，真实评测由 runner 提供 run/items
        并调用 finalize。
        """
        request = self._repo.get_request(eval_id)
        if request is None:
            raise ReporterError(f"未知 eval_id: {eval_id}")
        now = self._clock()
        run = EvalRunRecord(
            run_id=f"RUN-{eval_id.removeprefix('EV-')}-01",
            eval_id=eval_id,
            evaluator_id="EV-placeholder.empty",
            evaluator_version="0.0.0",
            scorer_versions=None,
            attempt=1,
            spec_hash=request.spec_hash,
            code_commit=None,
            env_snapshot=None,
            budget_ms=None,
            degraded=False,
            started_at=now,
            ended_at=now,
            status="succeeded",
        )
        return self.finalize(eval_id, run, [])

    def finalize(
        self, eval_id: str, run: EvalRunRecord, items: list[EvalItemRecord]
    ) -> dict[str, Any]:
        """构建并持久化报告：证据链 → 判定合成 → 契约校验 → 入库。"""
        if self._repo.get_request(eval_id) is None:
            raise ReporterError(f"未知 eval_id: {eval_id}")

        self._repo.insert_run(run)
        evidence = self._build_evidence(run, items)
        if items:
            self._repo.insert_items(items)

        verdict, block_reasons = _synthesize_verdict(items)
        score, n = _synthesize_score(items)
        now = self._clock()

        report: dict[str, Any] = {
            "eval_id": eval_id,
            "run_id": run.run_id,
            "spec_hash": run.spec_hash,
            "verdict": verdict,
            "score": score,
            "n": n,
            "ci": None,  # TODO(P1.5): 统计校准落地后按 §8.2 计算 CI
            "items": [_report_item(i) for i in items],
            "block_reasons": block_reasons,
            "evidence": {"uri": evidence.uri, "sha256": evidence.sha256},
            "thresholds_version": self._thresholds.version,
            "baseline_run_id": None,  # §8.3 回归比对属后续里程碑
            "baseline_diff": None,
            "sla": _build_sla(run),
            "evaluated_at": zulu(now),
            "expires_at": zulu(now + timedelta(days=CREDENTIAL_TTL_DAYS)),
        }

        errors = list(self._validator.iter_errors(report))
        if errors:
            details = "; ".join(e.message for e in errors[:5])
            raise ReporterError(f"内部生成的报告违反契约: {details}")

        self._repo.insert_report(report)
        self._repo.update_status(eval_id, "succeeded")
        logger.info(
            "report finalized eval_id=%s verdict=%s items=%d evidence=%s",
            eval_id,
            verdict,
            len(items),
            evidence.hash[:12],
        )
        return report

    def _build_evidence(self, run: EvalRunRecord, items: list[EvalItemRecord]) -> EvidenceRow:
        """证据链条目：规范化哈希 + prev 链哈希（§14.4，P4-1 起可带签名主体）。"""
        # TODO(P4-2): WORM 对象存储落地后替换 local:// 占位 URI
        return append_entry(
            self._repo,
            run.run_id,
            {"run": asdict(run), "items": [asdict(i) for i in items]},
            signed_by=self._signed_by,
            clock=self._clock,
        )


# ---------- 判定与分数合成（§4） ----------


def _synthesize_verdict(
    items: list[EvalItemRecord],
) -> tuple[str, list[str]]:
    """BLOCK > INCONCLUSIVE > PASS；空/全跳过 fail-closed。"""
    if not items:
        return "INCONCLUSIVE", ["no_items: 评测项为空，证据不足，默认不放行（§2.4/§4）"]
    blocked = [i for i in items if i.status == "BLOCK"]
    if blocked:
        return "BLOCK", [f"{i.kind} item {i.name}: BLOCK" for i in blocked]
    inconclusive = [i for i in items if i.status in ("INCONCLUSIVE", "TIMEOUT")]
    if inconclusive:
        return "INCONCLUSIVE", [f"item {i.name}: {i.status}" for i in inconclusive]
    active = [i for i in items if i.status != "SKIPPED"]
    if not active:
        return "INCONCLUSIVE", ["all_skipped: 全部评测项被隔离跳过，证据不足，默认不放行"]
    return "PASS", []


def _synthesize_score(
    items: list[EvalItemRecord],
) -> tuple[float | None, int | None]:
    """score = Σ w_i × score_i（加权项）；n 取加权项最小样本量（保守）。"""
    weighted = [i for i in items if i.kind == "weighted" and i.score is not None and i.weight]
    score = round(sum(i.weight * i.score for i in weighted), 6) if weighted else None
    ns = [i.n for i in items if i.kind == "weighted" and i.n is not None]
    return score, (min(ns) if ns else None)


def _report_item(item: EvalItemRecord) -> dict[str, Any]:
    return {
        "name": item.name,
        "kind": item.kind,
        "status": item.status,
        "score": item.score,
        "n": item.n,
        "ci_lower": item.ci_lower,
        "ci_upper": item.ci_upper,
        "weight": item.weight,
        "evidence_id": item.evidence_id,
        "detail": item.detail,
    }


def _build_sla(run: EvalRunRecord) -> dict[str, Any] | None:
    if run.budget_ms is None:
        return None
    elapsed = 0
    if run.started_at and run.ended_at:
        elapsed = int((run.ended_at - run.started_at).total_seconds() * 1000)
    return {
        "budget_ms": run.budget_ms,
        "elapsed_ms": elapsed,
        "degraded": run.degraded,
    }
