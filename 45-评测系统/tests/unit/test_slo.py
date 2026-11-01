# -*- coding: utf-8 -*-
"""
test_slo.py — P4-5 SLO 看板与告警
==================================
验收（PLAN P4-5 / SPEC §17 + §14.5）：
- 9 项 KPI 全部可见（有信号给值、无信号标 no_data，不伪造）
- 队列积压 ≥10 触发告警；SLA 达标率 <90% 触发告警
- 灰度期（shadow=true）SLA 目标 90%，正式期 95%
- 配置可覆盖（config/slo.yaml）；`evalctl slo` 输出 JSON 且退出码 0
"""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from api.cli import EXIT_ERROR, EXIT_PASS, main  # noqa: E402
from core.gateway import CategoriesConfig, Gateway  # noqa: E402
from core.metrics import Metrics  # noqa: E402
from core.slo import (  # noqa: E402
    EXTERNAL_KPI_KEYS,
    KPI_DEFINITIONS,
    SLOConfig,
    SLODashboard,
    SLOError,
    build_snapshot,
)
from storage.repo import InMemoryRepo  # noqa: E402

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

MAPPING = {
    "finance": ("strategy", "service"),
    "ai": ("model", "service"),
    "engineering": ("code_artifact", "dataset", "knowledge"),
}

ALL_SIGNALS = {
    "api_availability": 0.999,
    "accepted_latency_p95_ms": 800.0,
    "l1_latency_p95_ms": 30_000.0,
    "sla_attainment_rate": 0.97,
    "misblock_rate_upper": 0.005,
    "evidence_complete_rate": 1.0,
    "recompute_match_rate": 0.98,
    "branch_coverage_rate": 1.0,
}


def make_repo(shadow: bool = False, queued: int = 0) -> InMemoryRepo:
    repo = InMemoryRepo()
    gateway = Gateway(
        store=repo,
        categories=CategoriesConfig(version="CAT-TEST@1", mapping=MAPPING, gate_shadow=shadow),
        clock=lambda: NOW,
    )
    for index in range(queued):
        gateway.submit(
            {
                "object_ref": f"git://repo/strategy@abc{index:03d}",
                "category": "finance",
                "object_type": "strategy",
                "submitter": "trader-01",
                "purpose": "l0_settle",
                "spec_id": "EVS-20261101-0001",
                "env_manifest": {"endpoints": ["https://object.local/health"]},
            },
            idempotency_key=f"k-{index}",
        )
    return repo


def make_dashboard(
    repo: InMemoryRepo, shadow: bool = False, config: SLOConfig | None = None
) -> SLODashboard:
    return SLODashboard(
        repo=repo,
        metrics=Metrics(repo=repo, shadow=shadow, clock=lambda: NOW),
        config=config or SLOConfig(),
        shadow=shadow,
        clock=lambda: NOW,
    )


# ---------- 定义 ----------


def test_nine_kpis_match_spec_17() -> None:
    keys = {spec.key for spec in KPI_DEFINITIONS}
    assert len(KPI_DEFINITIONS) == 9
    assert keys == {
        "api_availability",
        "accepted_latency_p95_ms",
        "l1_latency_p95_ms",
        "sla_attainment_rate",
        "misblock_rate_upper",
        "evidence_complete_rate",
        "recompute_match_rate",
        "branch_coverage_rate",
        "backlog",
    }
    assert {spec.key for spec in KPI_DEFINITIONS if spec.source == "signals"} == EXTERNAL_KPI_KEYS


def test_empty_repo_reports_zero_backlog_and_no_data() -> None:
    snapshot = make_dashboard(make_repo()).snapshot()
    rows = {row["key"]: row for row in snapshot["kpis"]}
    assert len(rows) == 9
    assert rows["backlog"]["value"] == 0
    assert rows["backlog"]["status"] == "ok"
    assert rows["api_availability"]["status"] == "no_data"
    assert rows["api_availability"]["value"] is None
    assert snapshot["alerts"] == []
    assert snapshot["generated_at"] == "2026-11-01T12:00:00Z"


def test_backlog_breach_triggers_alert() -> None:
    snapshot = make_dashboard(make_repo(queued=10)).snapshot()
    rows = {row["key"]: row for row in snapshot["kpis"]}
    assert rows["backlog"]["value"] == 10
    assert rows["backlog"]["status"] == "breach"
    assert snapshot["alerts"] == [
        {"key": "backlog", "value": 10, "threshold": 10, "severity": "warning"}
    ]


def test_sla_below_90_triggers_critical_alert() -> None:
    snapshot = make_dashboard(make_repo()).snapshot(signals={"sla_attainment_rate": 0.85})
    rows = {row["key"]: row for row in snapshot["kpis"]}
    assert rows["sla_attainment_rate"]["status"] == "breach"
    assert snapshot["alerts"] == [
        {
            "key": "sla_attainment_rate",
            "value": 0.85,
            "threshold": 0.90,
            "severity": "critical",
        }
    ]


def test_gray_period_uses_90_percent_target() -> None:
    snapshot = make_dashboard(make_repo(shadow=True), shadow=True).snapshot(
        signals={"sla_attainment_rate": 0.92}
    )
    rows = {row["key"]: row for row in snapshot["kpis"]}
    assert rows["sla_attainment_rate"]["target"] == ">=90.0%"
    assert rows["sla_attainment_rate"]["status"] == "ok"
    assert snapshot["alerts"] == []
    assert snapshot["gate_shadow"] is True


def test_signals_fill_all_external_kpis() -> None:
    snapshot = make_dashboard(make_repo()).snapshot(signals=ALL_SIGNALS)
    rows = {row["key"]: row for row in snapshot["kpis"]}
    for key, value in ALL_SIGNALS.items():
        assert rows[key]["value"] == pytest.approx(value)
        assert rows[key]["status"] == "ok"
    assert snapshot["alerts"] == []


def test_unknown_signal_rejected() -> None:
    with pytest.raises(SLOError, match="未知"):
        build_snapshot(
            metrics=Metrics(repo=make_repo(), clock=lambda: NOW),
            config=SLOConfig(),
            signals={"unknown_kpi": 1.0},
        )


def test_missing_signal_marked_no_data_not_zero() -> None:
    snapshot = make_dashboard(make_repo()).snapshot(signals={"sla_attainment_rate": 0.0})
    rows = {row["key"]: row for row in snapshot["kpis"]}
    assert rows["sla_attainment_rate"]["value"] == 0.0
    assert rows["sla_attainment_rate"]["status"] == "breach"
    assert rows["api_availability"]["status"] == "no_data"
    assert rows["api_availability"]["value"] is None


# ---------- 配置 ----------


def test_config_defaults_when_file_missing(tmp_path: Path) -> None:
    config = SLOConfig.load(tmp_path / "missing.yaml")
    assert config.backlog_threshold == 10
    assert config.sla_target == 0.95
    assert config.gray_sla_target == 0.90
    assert config.sla_alert_threshold == 0.90


def test_config_override(tmp_path: Path) -> None:
    path = tmp_path / "slo.yaml"
    path.write_text(
        "sla_target: 0.96\ngray_sla_target: 0.92\nbacklog_threshold: 5\nsla_alert_threshold: 0.95\n",
        encoding="utf-8",
    )
    config = SLOConfig.load(path)
    snapshot = make_dashboard(make_repo(queued=6), config=config).snapshot()
    assert snapshot["alerts"] == [
        {"key": "backlog", "value": 6, "threshold": 5, "severity": "warning"}
    ]


def test_shipped_config_file_loads() -> None:
    config = SLOConfig.load(Path(__file__).resolve().parent.parent.parent / "config" / "slo.yaml")
    assert config.backlog_threshold == 10


# ---------- CLI ----------


def test_cli_slo_prints_nine_kpis() -> None:
    out = io.StringIO()
    code = main(["slo"], repo=make_repo(), out=out, shadow=False)
    assert code == EXIT_PASS
    payload = json.loads(out.getvalue())
    assert len(payload["kpis"]) == 9
    assert payload["alerts"] == []


def test_cli_slo_reads_signals_file(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text(json.dumps(ALL_SIGNALS), encoding="utf-8")
    out = io.StringIO()
    code = main(["slo", "--signals", str(signals_path)], repo=make_repo(), out=out, shadow=False)
    assert code == EXIT_PASS
    payload = json.loads(out.getvalue())
    rows = {row["key"]: row for row in payload["kpis"]}
    assert rows["api_availability"]["value"] == pytest.approx(0.999)


def test_cli_slo_bad_signals_file_returns_error(tmp_path: Path) -> None:
    signals_path = tmp_path / "signals.json"
    signals_path.write_text("{not-json", encoding="utf-8")
    out = io.StringIO()
    code = main(["slo", "--signals", str(signals_path)], repo=make_repo(), out=out)
    assert code == EXIT_ERROR
    assert "error" in json.loads(out.getvalue())
