# -*- coding: utf-8 -*-
"""
scan.py — 工程扫描与追溯（P2-7，SPEC §5.3）
============================================
硬性项：
- E-H1 秘密泄露：secret scanning 命中即 BLOCK，无豁免
- E-H2 可利用漏洞：CRITICAL=0；HIGH 且有修复版本=0
- E-H3 可追溯性：commit_sha ↔ build_digest ↔ SBOM subject digest 一致 + attestation 可验证
- E-H5 旁路痕迹：CI 中出现 `|| true`、`--exit-code 0`、continue-on-error、skip 标记等即 BLOCK

本模块只做「判定」，扫描结果由 CI/取证侧提供；新增行覆盖率与 pycg/Scorecard 见 tests.py（P2-8）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from storage.repo import EvalItemRecord

SEVERITIES = ("critical", "high", "medium", "low")

BYPASS_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (r"\|\| true", "shell", "|| true"),
    (r"\|\| :", "shell", "|| :"),
    (r"--exit-code 0", "lint", "--exit-code 0"),
    (r"continue-on-error", "ci", "continue-on-error"),
    (r"--no-verify", "git", "--no-verify"),
    (r"-m 'not", "skip", "skip 标记"),
    (r"pytest\.mark\.skip", "skip", "skip 标记"),
    (r"unittest\.skip", "skip", "skip 标记"),
)


@dataclass(frozen=True)
class Vulnerability:
    advisory_id: str
    severity: str
    fixed_version: str | None = None

    def __post_init__(self) -> None:
        normalized = self.severity.lower()
        if normalized not in SEVERITIES:
            raise ValueError(f"未知漏洞等级：{self.severity}")
        object.__setattr__(self, "severity", normalized)


@dataclass(frozen=True)
class Traceability:
    commit_sha: str
    build_digest: str
    sbom_subject_digest: str
    attestation_verified: bool


@dataclass(frozen=True)
class EngineeringScan:
    secrets: tuple[str, ...]
    vulnerabilities: tuple[Vulnerability, ...]
    traceability: Traceability
    ci_commands: tuple[str, ...]


class EngineeringScanEvaluator:
    """四项硬性判定，各自出一个 hard item。"""

    def evaluate(self, scan: EngineeringScan, run_id: str) -> list[EvalItemRecord]:
        return [
            self._item(run_id, "E-H1-secrets", self._secret_codes(scan)),
            self._item(run_id, "E-H2-vulns", self._vuln_codes(scan.vulnerabilities)),
            self._item(run_id, "E-H3-traceability", self._trace_codes(scan.traceability)),
            self._item(run_id, "E-H5-bypass", self._bypass_codes(scan.ci_commands)),
        ]

    @staticmethod
    def _secret_codes(scan: EngineeringScan) -> list[str]:
        return [f"E-H1_secret_leak:{location}" for location in scan.secrets]

    @staticmethod
    def _vuln_codes(vulnerabilities: tuple[Vulnerability, ...]) -> list[str]:
        codes: list[str] = []
        for vulnerability in vulnerabilities:
            if vulnerability.severity == "critical":
                codes.append(f"E-H2_critical_vuln:{vulnerability.advisory_id}")
            elif vulnerability.severity == "high" and vulnerability.fixed_version:
                codes.append(f"E-H2_high_fixable:{vulnerability.advisory_id}")
        return codes

    @staticmethod
    def _trace_codes(traceability: Traceability) -> list[str]:
        codes: list[str] = []
        if not traceability.commit_sha:
            codes.append("E-H3_commit_missing")
        if traceability.build_digest != traceability.sbom_subject_digest:
            codes.append("E-H3_digest_mismatch")
        if not traceability.attestation_verified:
            codes.append("E-H3_attestation_invalid")
        return codes

    @staticmethod
    def _bypass_codes(commands: tuple[str, ...]) -> list[str]:
        for command in commands:
            for pattern, _kind, label in BYPASS_PATTERNS:
                if re.search(pattern, command):
                    return [f"E-H5_bypass_trace:{label}"]
        return []

    @staticmethod
    def _item(run_id: str, name: str, codes: list[str]) -> EvalItemRecord:
        return EvalItemRecord(
            item_id=f"{run_id}-{name}",
            run_id=run_id,
            name=name,
            kind="hard",
            score=None,
            n=None,
            ci_lower=None,
            ci_upper=None,
            weight=None,
            status="BLOCK" if codes else "PASS",
            evidence_id=None,
            detail="; ".join(codes) or None,
        )
