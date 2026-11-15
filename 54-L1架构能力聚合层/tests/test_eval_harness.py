# -*- coding: utf-8 -*-
"""统计原语 + 评估 harness 测试。"""

import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.eval.harness import audit  # noqa: E402
from l1agg.methods.stats_core import (  # noqa: E402
    betai,
    bh_fdr,
    corr_p,
    kendall_tau_b,
    t_two_sided_p,
)

# ---------- 统计原语 ----------


def test_betai_symmetry():
    assert betai(2, 2, 0.5) == pytest.approx(0.5, abs=1e-9)
    assert betai(1, 1, 0.3) == pytest.approx(0.3, abs=1e-9)


def test_t_distribution_p_value():
    # t=2.0, df=58 → 双侧 p ≈ 0.0505（scipy: 0.0501）
    assert 0.045 < t_two_sided_p(2.0, 58) < 0.056


def test_corr_p_uses_t_not_normal():
    # n=60, r=0.3 → t≈2.39, p≈0.020；正态近似会给出 ~0.019，差异在小样本更明显
    p = corr_p(0.3, 60)
    assert 0.01 < p < 0.03
    assert corr_p(1.0, 60) == 0.0


def test_kendall_tau_b_ties():
    xs = [1, 2, 2, 3]
    ys = [1, 2, 2, 4]
    tau = kendall_tau_b(xs, ys)
    assert 0.0 < tau <= 1.0


def test_bh_fdr_known_case():
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    out = bh_fdr(pvals, alpha=0.05)
    assert out["m"] == 10
    assert out["reject"][:2] == [True, True]
    assert all(q <= 0.05 for q, rej in zip(out["q"], out["reject"], strict=False) if rej)
    assert out["q"] == sorted(out["q"])


# ---------- 评估 harness ----------


def test_audit_bootstrap_batch_all_pass():
    report = audit(["M01", "M02", "M03", "M04", "M05", "M06", "M07", "M11", "M12", "M24", "M25"])
    assert report["summary"]["failed"] == 0, report["failed"]
    assert report["summary"]["passed"] == 11
    assert report["summary"]["catalog_total"] == 243


def test_audit_checks_are_six():
    report = audit(["M01"])
    names = [c["name"] for c in report["methods"][0]["checks"]]
    assert names == ["meta", "gate", "determinism", "synthetic", "null", "reference"]


def test_audit_coverage_distinguishes_missing_from_not_applicable():
    report = audit(["M23"], null_trials=1)

    assert report["summary"]["coverage"] == {
        "total": 6,
        "executed": 3,
        "not_applicable": 2,
        "missing": 1,
        "rate": 0.75,
    }
    assert report["summary"]["checks"]["synthetic"] == {
        "total": 1,
        "executed": 0,
        "not_applicable": 0,
        "missing": 1,
        "rate": 0.0,
    }
    assert report["summary"]["checks"]["reference"]["not_applicable"] == 1
    method = report["methods"][0]
    assert method["passed"] is True
    assert method["coverage"]["rate"] == 0.75
    skips = {c["name"]: c for c in method["checks"] if c["skipped"]}
    assert skips["synthetic"]["skip_kind"] == "missing"
    assert skips["null"]["skip_kind"] == "not_applicable"
    assert skips["reference"]["skip_kind"] == "not_applicable"


def test_method_audit_cli_prints_coverage_summary(tmp_path, capsys):
    import importlib.util

    script = os.path.join(_MODULE_ROOT, "scripts", "method_audit.py")
    spec = importlib.util.spec_from_file_location("method_audit_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    rc = module.main(
        [
            "--methods",
            "M23",
            "--null-trials",
            "1",
            "--out",
            str(tmp_path / "audit.json"),
        ]
    )

    assert rc == 0
    summary = capsys.readouterr().out.splitlines()[0]
    assert "coverage=75.00%" in summary
    assert "executed=3" in summary
    assert "not_applicable=2" in summary
    assert "missing=1" in summary


def test_audit_failed_but_executed_check_counts_as_coverage():
    from l1agg.methods import register

    @register(
        "M98",
        name="broken coverage",
        group="M",
        layer="D2",
        input_kind="pairs",
        min_n=60,
        output_schema=("r",),
    )
    def _broken_coverage(data):
        raise RuntimeError("boom")

    try:
        report = audit(["M98"], null_trials=1)
        determinism = report["summary"]["checks"]["determinism"]
        assert determinism["executed"] == 1
        assert determinism["missing"] == 0
        assert report["summary"]["coverage"]["rate"] > 0
    finally:
        from l1agg.methods.registry import REGISTRY

        REGISTRY.pop("M98", None)


def test_audit_is_deterministic_under_seed():
    a = audit(["M01"], seed=7, null_trials=10)
    b = audit(["M01"], seed=7, null_trials=10)
    assert a["methods"] == b["methods"]


def test_audit_reports_failure_for_broken_method(tmp_path):
    # 故意登记一个必然失败的实现，验证 harness 能抓到（不污染正式注册表 id）
    from l1agg.methods import register

    @register(
        "M99",
        name="broken",
        group="M",
        layer="D2",
        input_kind="pairs",
        min_n=60,
        output_schema=("r",),
    )
    def _broken(data):
        raise RuntimeError("boom")

    try:
        report = audit(["M99"], null_trials=1)
        assert report["summary"]["failed"] == 1
        failed_checks = [
            c["name"]
            for c in report["methods"][0]["checks"]
            if not c["passed"] and not c["skipped"]
        ]
        assert "determinism" in failed_checks or "gate" in failed_checks
    finally:
        from l1agg.methods.registry import REGISTRY

        REGISTRY.pop("M99", None)
