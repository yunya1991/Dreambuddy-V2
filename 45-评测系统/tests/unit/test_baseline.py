# -*- coding: utf-8 -*-
"""
test_baseline.py — P4-6 季度 baseline 回归
==========================================
验收（PLAN P4-6 / SPEC §8.3 + §8.5）：
- 回归判定用「新分与基线差的 95% CI 下界 < 0」，不用点估计
- 逐项列出 baseline_diff（regressed/improved/unchanged/missing），不改主 verdict
- 样本不足（配对项 <2）判 INCONCLUSIVE，不妄称回归
- 容差可吸收模型裁判噪声（±5%）
- `evalctl baseline` 生成 JSON 报告；退出码 0 OK / 2 REGRESSION / 3 INCONCLUSIVE / 4 错误
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.cli import EXIT_BLOCK, EXIT_ERROR, EXIT_INCONCLUSIVE, EXIT_PASS, main  # noqa: E402
from core.baseline import (  # noqa: E402
    BaselineConfig,
    BaselineError,
    GoldenCase,
    build_regression_report,
    compare_reports,
)
from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.registry import ThresholdRegistry  # noqa: E402
from core.reporter import Reporter  # noqa: E402
from storage.repo import EvalItemRecord, EvalRunRecord, InMemoryRepo  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
MODULE_ROOT = Path(__file__).resolve().parent.parent.parent

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}


def make_eval(repo: InMemoryRepo, tag: str, scores: dict[str, float]) -> str:
    gateway = Gateway(
        store=repo,
        categories=CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=True),
        clock=lambda: NOW,
    )
    eval_id = gateway.submit(
        {
            "object_ref": f"git://repo/strategy@{tag}",
            "category": "finance",
            "object_type": "strategy",
            "submitter": "trader-01",
            "purpose": "l0_settle",
            "spec_id": "EVS-20261101-0001",
            "env_manifest": {"endpoints": ["https://object.local/health"]},
        },
        idempotency_key=f"key-{tag}",
    ).eval_id
    run = EvalRunRecord(
        run_id=f"RUN-{tag}",
        eval_id=eval_id,
        evaluator_id="EV-finance.backtest",
        evaluator_version="1.0.0",
        scorer_versions=None,
        attempt=1,
        spec_hash=gateway_spec_hash(repo, eval_id),
        code_commit=None,
        env_snapshot=None,
        budget_ms=None,
        degraded=False,
        started_at=NOW,
        ended_at=NOW,
        status="succeeded",
    )
    items = [
        EvalItemRecord(
            item_id=f"IT-{tag}-{name}",
            run_id=run.run_id,
            name=name,
            kind="weighted",
            score=score,
            n=200,
            ci_lower=score,
            ci_upper=score,
            weight=1.0 / len(scores),
            status="PASS",
            evidence_id=None,
            detail=None,
        )
        for name, score in scores.items()
    ]
    reporter = Reporter(repo=repo, thresholds=ThresholdRegistry.load(), clock=lambda: NOW)
    reporter.finalize(eval_id, run, items)
    return eval_id


def gateway_spec_hash(repo: InMemoryRepo, eval_id: str) -> str:
    return repo.get_request(eval_id).spec_hash


@pytest.fixture
def reports():
    repo = InMemoryRepo()
    baseline = make_eval(repo, "base", {"sharpe": 0.60, "drawdown": 0.70})
    candidate = make_eval(repo, "cand", {"sharpe": 0.50, "drawdown": 0.60})
    return {
        "base": repo.get_report(baseline),
        "cand": repo.get_report(candidate),
    }


# ---------- 纯比对 ----------


def test_identical_reports_not_regressed(reports) -> None:
    result = compare_reports(reports["base"], reports["base"])
    assert result["regressed"] is False
    assert result["inconclusive"] is False
    assert result["ci_lower"] == pytest.approx(0.0)
    assert result["reasons"] == []


def test_clear_regression_detected(reports) -> None:
    result = compare_reports(reports["base"], reports["cand"])
    assert result["score_diff"] == pytest.approx(-0.10)
    assert result["ci_lower"] < 0
    assert result["regressed"] is True
    verdicts = {item["name"]: item["verdict"] for item in result["items"]}
    assert verdicts == {"sharpe": "regressed", "drawdown": "regressed"}


def test_improvement_not_regressed(reports) -> None:
    result = compare_reports(reports["cand"], reports["base"])
    assert result["score_diff"] == pytest.approx(0.10)
    assert result["regressed"] is False
    assert all(item["verdict"] == "improved" for item in result["items"])


def test_tolerance_absorbs_small_drop() -> None:
    base = {"score": 0.5, "items": [{"name": "a", "score": 0.5}, {"name": "b", "score": 0.5}]}
    cand = {"score": 0.48, "items": [{"name": "a", "score": 0.48}, {"name": "b", "score": 0.48}]}
    strict = compare_reports(base, cand)
    tolerant = compare_reports(base, cand, tolerance=0.05)
    assert strict["regressed"] is True
    assert tolerant["regressed"] is False


def test_missing_items_listed(reports) -> None:
    candidate = {
        "score": 0.2,
        "items": [{"name": "sharpe", "score": 0.2}, {"name": "drawdown", "score": 0.2}],
    }
    baseline = {
        "score": 0.5,
        "items": [
            {"name": "sharpe", "score": 0.5},
            {"name": "drawdown", "score": 0.5},
            {"name": "capacity", "score": 0.5},
        ],
    }
    result = compare_reports(baseline, candidate)
    verdicts = {item["name"]: item["verdict"] for item in result["items"]}
    assert verdicts["capacity"] == "missing_in_candidate"
    assert "missing_in_candidate:capacity" in result["reasons"]


def test_single_paired_item_is_inconclusive() -> None:
    base = {"score": 0.5, "items": [{"name": "a", "score": 0.5}]}
    cand = {"score": 0.1, "items": [{"name": "a", "score": 0.1}]}
    result = compare_reports(base, cand)
    assert result["inconclusive"] is True
    assert result["regressed"] is False
    assert any(reason.startswith("insufficient_samples") for reason in result["reasons"])


def test_no_paired_items_is_inconclusive() -> None:
    base = {"score": 0.5, "items": [{"name": "a", "score": 0.5}]}
    cand = {"score": 0.5, "items": [{"name": "b", "score": 0.5}]}
    result = compare_reports(base, cand)
    assert result["inconclusive"] is True
    assert "no_paired_items" in result["reasons"]


# ---------- 配置与汇总 ----------


def test_config_loads_cases(tmp_path: Path) -> None:
    path = tmp_path / "baseline.yaml"
    path.write_text(
        "tolerance: 0.05\ncases:\n"
        "  - name: finance-core\n"
        "    baseline_eval_id: EV-1\n"
        "    candidate_eval_id: EV-2\n",
        encoding="utf-8",
    )
    config = BaselineConfig.load(path)
    assert config.tolerance == 0.05
    assert config.cases == (GoldenCase("finance-core", "EV-1", "EV-2", None),)


def test_config_rejects_unknown_field(tmp_path: Path) -> None:
    path = tmp_path / "baseline.yaml"
    path.write_text("cases: []\nunknown: 1\n", encoding="utf-8")
    with pytest.raises(BaselineError, match="未知"):
        BaselineConfig.load(path)


def test_config_missing_file_is_empty(tmp_path: Path) -> None:
    config = BaselineConfig.load(tmp_path / "missing.yaml")
    assert config.cases == ()
    assert config.tolerance == 0.0


def test_build_report_marks_regressions(reports) -> None:
    config = BaselineConfig(
        tolerance=0.0,
        cases=(GoldenCase("finance-core", "base", "cand", None),),
    )
    report = build_regression_report(config, {"base": reports["base"], "cand": reports["cand"]})
    assert report["verdict"] == "REGRESSION"
    assert report["regressions"] == ["finance-core"]
    assert report["cases"][0]["case"] == "finance-core"


def test_build_report_unknown_eval_rejected(reports) -> None:
    config = BaselineConfig(cases=(GoldenCase("x", "base", "missing", None),))
    with pytest.raises(BaselineError, match="未知"):
        build_regression_report(config, {"base": reports["base"]})


def test_build_report_without_cases_is_inconclusive() -> None:
    report = build_regression_report(BaselineConfig(), {})
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["cases"] == []


# ---------- CLI ----------


def test_cli_baseline_regression_exit_2(tmp_path: Path) -> None:
    repo = InMemoryRepo()
    baseline = make_eval(repo, "base", {"sharpe": 0.6, "drawdown": 0.7})
    candidate = make_eval(repo, "cand", {"sharpe": 0.4, "drawdown": 0.5})
    out_path = tmp_path / "regression.json"
    out = io.StringIO()
    code = main(
        [
            "baseline",
            "--baseline",
            baseline,
            "--candidate",
            candidate,
            "--out",
            str(out_path),
        ],
        repo=repo,
        out=out,
    )
    assert code == EXIT_BLOCK
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["verdict"] == "REGRESSION"
    assert json.loads(out.getvalue())["verdict"] == "REGRESSION"


def test_cli_baseline_ok_exit_0(tmp_path: Path) -> None:
    repo = InMemoryRepo()
    baseline = make_eval(repo, "base", {"sharpe": 0.5, "drawdown": 0.6})
    candidate = make_eval(repo, "cand", {"sharpe": 0.5, "drawdown": 0.6})
    out = io.StringIO()
    code = main(
        ["baseline", "--baseline", baseline, "--candidate", candidate],
        repo=repo,
        out=out,
    )
    assert code == EXIT_PASS
    assert json.loads(out.getvalue())["verdict"] == "OK"


def test_cli_baseline_unknown_eval_exit_4() -> None:
    out = io.StringIO()
    code = main(
        ["baseline", "--baseline", "EV-missing", "--candidate", "EV-missing-2"],
        repo=InMemoryRepo(),
        out=out,
    )
    assert code == EXIT_ERROR
    assert "error" in json.loads(out.getvalue())


def test_cli_baseline_requires_pair_or_config() -> None:
    out = io.StringIO()
    code = main(["baseline"], repo=InMemoryRepo(), out=out)
    assert code in (EXIT_ERROR, EXIT_INCONCLUSIVE)
    assert "error" in json.loads(out.getvalue()) or "verdict" in json.loads(out.getvalue())
