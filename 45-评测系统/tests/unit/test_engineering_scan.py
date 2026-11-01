# -*- coding: utf-8 -*-
"""test_engineering_scan.py — P2-7 工程扫描与追溯（E-H1/H2/H3/H5）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.engineering.scan import (  # noqa: E402
    EngineeringScan,
    EngineeringScanEvaluator,
    Traceability,
    Vulnerability,
)


def trace(
    commit: str = "abc123", build: str = "sha256:aaa", sbom: str = "sha256:aaa", ok: bool = True
) -> Traceability:
    return Traceability(
        commit_sha=commit, build_digest=build, sbom_subject_digest=sbom, attestation_verified=ok
    )


def clean_scan(**overrides) -> EngineeringScan:
    base = {
        "secrets": (),
        "vulnerabilities": (),
        "traceability": trace(),
        "ci_commands": ("pytest -q", "flake8 src"),
    }
    base.update(overrides)
    return EngineeringScan(**base)


def test_clean_scan_passes_all_items():
    items = EngineeringScanEvaluator().evaluate(clean_scan(), run_id="RUN-1")
    assert [i.name for i in items] == [
        "E-H1-secrets",
        "E-H2-vulns",
        "E-H3-traceability",
        "E-H5-bypass",
    ]
    assert [i.status for i in items] == ["PASS"] * 4
    assert all(i.kind == "hard" for i in items)


def test_secret_hit_blocks_without_waiver():
    items = EngineeringScanEvaluator().evaluate(
        clean_scan(secrets=("src/config.py:12",)), run_id="RUN-1"
    )
    assert items[0].status == "BLOCK"
    assert items[0].detail == "E-H1_secret_leak:src/config.py:12"


def test_critical_vulnerability_blocks():
    vulns = (
        Vulnerability(advisory_id="CVE-2026-0001", severity="critical", fixed_version="2.0.1"),
    )
    items = EngineeringScanEvaluator().evaluate(clean_scan(vulnerabilities=vulns), run_id="RUN-1")
    assert items[1].status == "BLOCK"
    assert items[1].detail == "E-H2_critical_vuln:CVE-2026-0001"


def test_high_vulnerability_with_fix_blocks():
    vulns = (Vulnerability(advisory_id="CVE-2026-0002", severity="high", fixed_version="1.9.0"),)
    items = EngineeringScanEvaluator().evaluate(clean_scan(vulnerabilities=vulns), run_id="RUN-1")
    assert items[1].status == "BLOCK"
    assert items[1].detail == "E-H2_high_fixable:CVE-2026-0002"


def test_high_without_fix_or_medium_passes():
    vulns = (
        Vulnerability(advisory_id="CVE-2026-0003", severity="high", fixed_version=None),
        Vulnerability(advisory_id="CVE-2026-0004", severity="medium", fixed_version="1.1.0"),
    )
    items = EngineeringScanEvaluator().evaluate(clean_scan(vulnerabilities=vulns), run_id="RUN-1")
    assert items[1].status == "PASS"


def test_traceability_digest_mismatch_blocks():
    items = EngineeringScanEvaluator().evaluate(
        clean_scan(traceability=trace(sbom="sha256:bbb")), run_id="RUN-1"
    )
    assert items[2].status == "BLOCK"
    assert items[2].detail == "E-H3_digest_mismatch"


def test_traceability_attestation_invalid_blocks():
    items = EngineeringScanEvaluator().evaluate(
        clean_scan(traceability=trace(ok=False)), run_id="RUN-1"
    )
    assert items[2].status == "BLOCK"
    assert items[2].detail == "E-H3_attestation_invalid"


@pytest.mark.parametrize(
    "command,pattern",
    [
        ("pytest -q || true", "|| true"),
        ("curl ... || :", "|| :"),
        ("eslint --exit-code 0 src", "--exit-code 0"),
        ("continue-on-error: true", "continue-on-error"),
        ("git commit --no-verify", "--no-verify"),
        ("pytest -m 'not slow'", "skip 标记"),
    ],
)
def test_bypass_trace_detected(command, pattern):
    items = EngineeringScanEvaluator().evaluate(clean_scan(ci_commands=(command,)), run_id="RUN-1")
    assert items[3].status == "BLOCK"
    assert items[3].detail == f"E-H5_bypass_trace:{pattern}"


def test_bypass_patterns_constant_contains_required():
    from evaluators.engineering.scan import BYPASS_PATTERNS

    labels = {label for _, _, label in BYPASS_PATTERNS}
    assert {"|| true", "--exit-code 0", "continue-on-error", "skip 标记"} <= labels
