# -*- coding: utf-8 -*-
"""
baseline.py — 季度 baseline 回归（P4-6，SPEC §8.3 + §8.5）
==========================================================
- 回归判定：新分与基线差的 95% CI 下界 < -tolerance（不靠点估计）
- 逐项列出 `baseline_diff`（regressed / improved / unchanged / missing_*），不改主 verdict
- 配对项 <2 判 INCONCLUSIVE，不妄称回归
- golden set 由 `config/baseline.yaml` 的 cases 描述，供季度定时任务调用
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml
from storage.repo import zulu

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "baseline.yaml"
RESAMPLES = 1000
CI_SEED = 42


class BaselineError(ValueError):
    """回归比对输入非法（未知 eval_id / 配置字段非法 / 报告缺项）。"""


@dataclass(frozen=True)
class GoldenCase:
    name: str
    baseline_eval_id: str
    candidate_eval_id: str
    tolerance: float | None = None


@dataclass(frozen=True)
class BaselineConfig:
    tolerance: float = 0.0
    cases: tuple[GoldenCase, ...] = ()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "BaselineConfig":
        config_path = Path(path) if path else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls()
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise BaselineError(f"baseline 配置解析失败：{exc}") from exc
        if not isinstance(data, dict):
            raise BaselineError("baseline 配置必须是映射")
        unknown = set(data) - {"tolerance", "cases"}
        if unknown:
            raise BaselineError(f"baseline 配置含未知字段：{sorted(unknown)}")

        try:
            tolerance = float(data.get("tolerance", 0.0))
        except (TypeError, ValueError) as exc:
            raise BaselineError(f"tolerance 非法：{exc}") from exc

        raw_cases = data.get("cases", []) or []
        if not isinstance(raw_cases, list):
            raise BaselineError("cases 必须是列表")
        cases: list[GoldenCase] = []
        for raw in raw_cases:
            if not isinstance(raw, dict):
                raise BaselineError("每个 case 必须是映射")
            extra = set(raw) - {"name", "baseline_eval_id", "candidate_eval_id", "tolerance"}
            if extra:
                raise BaselineError(f"case 含未知字段：{sorted(extra)}")
            try:
                case_tolerance = raw.get("tolerance")
                cases.append(
                    GoldenCase(
                        name=str(raw["name"]),
                        baseline_eval_id=str(raw["baseline_eval_id"]),
                        candidate_eval_id=str(raw["candidate_eval_id"]),
                        tolerance=None if case_tolerance is None else float(case_tolerance),
                    )
                )
            except KeyError as exc:
                raise BaselineError(f"case 缺字段：{exc}") from exc
            except (TypeError, ValueError) as exc:
                raise BaselineError(f"case 字段类型非法：{exc}") from exc
        return cls(tolerance=tolerance, cases=tuple(cases))


def compare_reports(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    tolerance: float = 0.0,
    seed: int = CI_SEED,
    resamples: int = RESAMPLES,
) -> dict[str, Any]:
    """比对两份报告：逐项 diff + 配对差的 bootstrap 95% CI 下界。"""
    baseline_items = _item_scores(baseline)
    candidate_items = _item_scores(candidate)

    items: list[dict[str, Any]] = []
    diffs: list[float] = []
    reasons: list[str] = []
    for name in sorted(set(baseline_items) | set(candidate_items)):
        if name not in candidate_items:
            items.append(_item_diff(name, baseline_items[name], None, None, "missing_in_candidate"))
            reasons.append(f"missing_in_candidate:{name}")
            continue
        if name not in baseline_items:
            items.append(_item_diff(name, None, candidate_items[name], None, "missing_in_baseline"))
            reasons.append(f"missing_in_baseline:{name}")
            continue
        diff = candidate_items[name] - baseline_items[name]
        diffs.append(diff)
        if diff > 0:
            verdict = "improved"
        elif diff < 0:
            verdict = "regressed"
            reasons.append(f"item_regressed:{name}")
        else:
            verdict = "unchanged"
        items.append(_item_diff(name, baseline_items[name], candidate_items[name], diff, verdict))

    baseline_score = _score(baseline)
    candidate_score = _score(candidate)
    score_diff = (
        candidate_score - baseline_score
        if baseline_score is not None and candidate_score is not None
        else None
    )

    inconclusive = False
    ci_lower: float | None = None
    ci_upper: float | None = None
    if not diffs:
        inconclusive = True
        reasons.append("no_paired_items")
    elif len(diffs) < 2:
        inconclusive = True
        reasons.append(f"insufficient_samples:{len(diffs)}")
    else:
        ci_lower, ci_upper = _bootstrap_ci(diffs, seed=seed, resamples=resamples)

    regressed = ci_lower is not None and ci_lower < -abs(tolerance)
    return {
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "score_diff": score_diff,
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "ci_method": "bootstrap",
        "tolerance": tolerance,
        "paired_n": len(diffs),
        "regressed": regressed,
        "inconclusive": inconclusive,
        "reasons": reasons,
        "items": items,
    }


def build_regression_report(
    config: BaselineConfig,
    reports: dict[str, dict[str, Any]],
    *,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """按 golden set 生成汇总报告；缺报告即报错（fail-closed）。"""
    cases: list[dict[str, Any]] = []
    regressions: list[str] = []
    inconclusive = False
    for case in config.cases:
        for eval_id in (case.baseline_eval_id, case.candidate_eval_id):
            if eval_id not in reports:
                raise BaselineError(f"未知 eval_id：{eval_id}")
        tolerance = config.tolerance if case.tolerance is None else case.tolerance
        result = compare_reports(
            reports[case.baseline_eval_id],
            reports[case.candidate_eval_id],
            tolerance=tolerance,
        )
        result["case"] = case.name
        cases.append(result)
        if result["regressed"]:
            regressions.append(case.name)
        if result["inconclusive"]:
            inconclusive = True

    if regressions:
        verdict = "REGRESSION"
    elif inconclusive or not cases:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "OK"

    generated_clock = clock or (lambda: datetime.now(timezone.utc))
    return {
        "version": "baseline_regression.v1",
        "generated_at": zulu(generated_clock()),
        "tolerance": config.tolerance,
        "verdict": verdict,
        "regressions": regressions,
        "cases": cases,
    }


def _item_scores(report: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in report.get("items") or []:
        name = item.get("name")
        score = item.get("score")
        if isinstance(name, str) and name and isinstance(score, (int, float)):
            scores[name] = float(score)
    return scores


def _score(report: dict[str, Any]) -> float | None:
    score = report.get("score")
    return float(score) if isinstance(score, (int, float)) else None


def _item_diff(
    name: str,
    baseline_score: float | None,
    candidate_score: float | None,
    diff: float | None,
    verdict: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "baseline": baseline_score,
        "candidate": candidate_score,
        "diff": diff,
        "verdict": verdict,
    }


def _bootstrap_ci(diffs: list[float], *, seed: int, resamples: int) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lower = means[int(0.025 * (resamples - 1))]
    upper = means[int(0.975 * (resamples - 1))]
    return round(lower, 6), round(upper, 6)
