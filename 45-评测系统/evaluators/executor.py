# -*- coding: utf-8 -*-
"""
executor.py — 45-评测系统 生产执行器 v2（专项评测器接入）
==========================================================
职责：
- E3 通用准入（L1，全类型必跑）：网络/内容/交叉三层
- 按类别路由专项评测器（L2）：
  * finance: F-H2 可用性（故障观测）+ F-H6/H7 回测统计
  * ai:      A-H4 裁判校准（人工/裁判标签）+ A-W2 压测（样本+阈值）
  * engineering: E-H1/H2/H3/H5 工程扫描 + E-H4/E-W5/E-W6 测试基准
- 专项输入交付通道：artifacts/inputs/{eval_id}.json（提交方/取证侧在受理后写入）
- 输入缺失 → 该专项产出 SKIPPED 项（可审计，不静默跳过）
- 产出 EvalRunRecord + EvalItemRecord，走 Reporter.finalize 报告归档
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.reporter import Reporter
from evaluators.common.e3 import E3Validator
from storage.repo import EvalItemRecord, EvalRepo, EvalRunRecord

logger = logging.getLogger(__name__)

MODULE_ROOT = Path(__file__).resolve().parents[1]
INPUTS_DIR = MODULE_ROOT / "artifacts" / "inputs"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _skipped_item(run_id: str, name: str, reason: str) -> EvalItemRecord:
    return EvalItemRecord(
        item_id=f"{run_id}-{name}",
        run_id=run_id,
        name=name,
        kind="reference",
        score=None,
        n=None,
        ci_lower=None,
        ci_upper=None,
        weight=None,
        status="SKIPPED",
        evidence_id=None,
        detail=reason,
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class E3Executor:
    """生产执行器：E3 通用准入 + 按类别专项评测 → 报告收尾。"""

    def __init__(
        self,
        repo: EvalRepo,
        reporter: Reporter,
        validator: E3Validator | None = None,
        clock: Callable[[], datetime] = utcnow,
        inputs_dir: Path | None = None,
    ) -> None:
        self._repo = repo
        self._reporter = reporter
        self._validator = validator or E3Validator()
        self._clock = clock
        self._inputs_dir = inputs_dir or INPUTS_DIR

    # ---------- 输入加载 ----------
    def _load_inputs(self, eval_id: str) -> dict[str, Any]:
        path = self._inputs_dir / f"{eval_id}.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("评测输入文件读取失败 eval_id=%s: %s", eval_id, exc)
            return {}

    # ---------- 专项路由 ----------
    def _finance_items(self, run_id: str, inputs: dict[str, Any]) -> list[EvalItemRecord]:
        from evaluators.finance.availability import AvailabilityEvaluator, FaultObservation
        from evaluators.finance.backtest import BacktestStatisticsEvaluator, BacktestStats

        items: list[EvalItemRecord] = []
        avail = inputs.get("availability") or {}
        if avail.get("observations"):
            observations = [
                FaultObservation(
                    kind=obs["kind"],
                    path=obs["path"],
                    started_at=_parse_dt(obs["started_at"]),
                    recovered_at=_parse_dt(obs.get("recovered_at")),
                    orders_lost=int(obs.get("orders_lost", 0)),
                    impacted_requests=int(obs.get("impacted_requests", 0)),
                    error_rate_curve=tuple(obs.get("error_rate_curve", ())),
                )
                for obs in avail["observations"]
            ]
            items.extend(AvailabilityEvaluator().evaluate(observations, run_id))
        else:
            items.append(_skipped_item(run_id, "F-H2-availability", "F-H2_input_missing:observations"))

        stats = inputs.get("backtest") or {}
        if stats.get("sharpe") is not None:
            backtest = BacktestStats(
                sharpe=float(stats["sharpe"]),
                n_observations=int(stats["n_observations"]),
                n_trials=int(stats["n_trials"]),
                oos_trades=int(stats["oos_trades"]),
                walk_forward_folds=int(stats["walk_forward_folds"]),
                pbo=float(stats["pbo"]),
                skew=float(stats.get("skew", 0.0)),
                kurtosis=float(stats.get("kurtosis", 3.0)),
                sr_std=float(stats.get("sr_std", 1.0)),
            )
            items.extend(BacktestStatisticsEvaluator().evaluate(backtest, run_id))
        else:
            items.append(_skipped_item(run_id, "F-H6-backtest", "F-H6_input_missing:backtest_stats"))
        return items

    def _ai_items(self, run_id: str, inputs: dict[str, Any]) -> list[EvalItemRecord]:
        from evaluators.ai.judge import JudgeCalibrationEvaluator
        from evaluators.ai.stress import StressEvaluator, StressPlan, StressSample

        items: list[EvalItemRecord] = []
        judge = inputs.get("judge") or {}
        if judge.get("human") and judge.get("judge_labels"):
            items.extend(
                JudgeCalibrationEvaluator().evaluate(
                    list(judge["human"]), list(judge["judge_labels"]), run_id
                )
            )
        else:
            items.append(_skipped_item(run_id, "A-H4-calibration", "A-H4_input_missing:labels"))

        stress = inputs.get("stress") or {}
        if stress.get("samples") and stress.get("plan"):
            plan = StressPlan(
                p95_max_ms=float(stress["plan"]["p95_max_ms"]),
                throughput_min_rps=float(stress["plan"]["throughput_min_rps"]),
                max_error_rate=float(stress["plan"]["max_error_rate"]),
            )
            samples = [
                StressSample(
                    concurrency=int(s["concurrency"]),
                    p95_latency_ms=float(s["p95_latency_ms"]),
                    throughput_rps=float(s["throughput_rps"]),
                    error_rate=float(s["error_rate"]),
                )
                for s in stress["samples"]
            ]
            items.extend(StressEvaluator().evaluate(samples, plan, run_id))
        else:
            items.append(_skipped_item(run_id, "A-W2-stress", "A-W2_input_missing:samples_or_plan"))
        return items

    def _engineering_items(self, run_id: str, inputs: dict[str, Any]) -> list[EvalItemRecord]:
        from evaluators.engineering.scan import (
            EngineeringScan,
            EngineeringScanEvaluator,
            Traceability,
            Vulnerability,
        )
        from evaluators.engineering.tests import (
            BenchmarkReport,
            CoverageReport,
            EngineeringTestsEvaluator,
            EngineeringTestsInput,
            ScorecardReport,
        )

        items: list[EvalItemRecord] = []
        scan = inputs.get("scan") or {}
        if scan:
            trace = scan.get("traceability") or {}
            engineering_scan = EngineeringScan(
                secrets=tuple(scan.get("secrets", ())),
                vulnerabilities=tuple(
                    Vulnerability(
                        advisory_id=v["advisory_id"],
                        severity=v["severity"],
                        fixed_version=v.get("fixed_version"),
                    )
                    for v in scan.get("vulnerabilities", ())
                ),
                traceability=Traceability(
                    commit_sha=trace.get("commit_sha", ""),
                    build_digest=trace.get("build_digest", ""),
                    sbom_subject_digest=trace.get("sbom_subject_digest", ""),
                    attestation_verified=bool(trace.get("attestation_verified", False)),
                ),
                ci_commands=tuple(scan.get("ci_commands", ())),
            )
            items.extend(EngineeringScanEvaluator().evaluate(engineering_scan, run_id))
        else:
            items.append(_skipped_item(run_id, "E-H-scan", "E-H_input_missing:scan"))

        tests = inputs.get("tests") or {}
        if tests:
            coverage = tests.get("coverage") or {}
            benchmark = tests.get("benchmark") or {}
            scorecard = tests.get("scorecard") or {}
            data = EngineeringTestsInput(
                coverage=CoverageReport(
                    base_sha=coverage.get("base_sha", ""),
                    job_signature=coverage.get("job_signature", ""),
                    added_lines={k: tuple(v) for k, v in (coverage.get("added_lines") or {}).items()},
                    covered_lines={k: tuple(v) for k, v in (coverage.get("covered_lines") or {}).items()},
                ),
                benchmark=BenchmarkReport(
                    expected_edges=tuple(tuple(e) for e in benchmark.get("expected_edges", ())),
                    predicted_edges=tuple(tuple(e) for e in benchmark.get("predicted_edges", ())),
                ),
                scorecard=ScorecardReport(score=float(scorecard.get("score", 0.0))),
            )
            items.extend(EngineeringTestsEvaluator().evaluate(data, run_id))
        else:
            items.append(_skipped_item(run_id, "E-H4-tests", "E-H4_input_missing:tests"))
        return items

    # ---------- 主入口 ----------
    def __call__(self, eval_id: str) -> dict[str, Any]:
        request = self._repo.get_request(eval_id)
        if request is None:
            raise RuntimeError(f"未知 eval_id: {eval_id}")

        payload = {
            "object_ref": request.object_ref,
            "category": request.category,
            "object_type": request.object_type,
            "submitter": request.submitter,
            "purpose": request.purpose,
            "priority": request.priority,
            "spec_id": request.spec_id,
            "env_manifest": request.env_manifest,
        }

        started = self._clock()
        run_id = f"RUN-{eval_id}"

        # L1 通用准入（全类型必跑）
        issues = self._validator.validate(payload)
        items = list(self._validator.build_items(run_id, issues))

        # L2 专项评测（按类别路由；输入缺失 → SKIPPED 可审计）
        inputs = self._load_inputs(eval_id)
        router = {
            "finance": self._finance_items,
            "ai": self._ai_items,
            "engineering": self._engineering_items,
        }
        handler = router.get(request.category)
        if handler is not None:
            items.extend(handler(run_id, inputs))
        ended = self._clock()

        run = EvalRunRecord(
            run_id=run_id,
            eval_id=eval_id,
            evaluator_id="e3+specialized",
            evaluator_version="2.0.0",
            scorer_versions=None,
            attempt=1,
            spec_hash=request.spec_hash,
            code_commit=None,
            env_snapshot={"runtime": request.env_manifest.get("runtime")},
            budget_ms=60_000,
            degraded=False,
            started_at=started,
            ended_at=ended,
            status="succeeded",
        )
        report = self._reporter.finalize(eval_id, run, items)
        logger.info(
            "评测执行完成 eval_id=%s category=%s verdict=%s items=%d",
            eval_id,
            request.category,
            report.get("verdict"),
            len(items),
        )
        return report


def requeue_pending(repo: EvalRepo, runner) -> int:
    """服务重启恢复：把滞留 queued 状态的请求重新入队。"""
    count = 0
    for row in repo.list_requests(limit=1000):
        if row.get("status") == "queued":
            eval_id = row.get("eval_id")
            if eval_id and runner.enqueue(str(eval_id)):
                count += 1
    if count:
        logger.info("重启恢复：重新入队 %d 个滞留任务", count)
    return count
