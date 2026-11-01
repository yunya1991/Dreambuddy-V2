# -*- coding: utf-8 -*-
"""
test_finance_availability.py — P2-3 金融功能与高可用测试
==========================================================
验收（PLAN P2-3 / SPEC §5.1 F-H2）：
- 5 类故障注入模板可执行：pod-kill / 网络延迟 / 交易所 API 超时 / DB 主备切换 / 磁盘写满
- 模板渲染为具体命令（目标占位符必须替换）；注入执行器可注入（默认不真跑）
- RTO/RPO 判定：订单 RPO=0、订单 RTO≤30s、行情 RTO≤60s；缺故障类型/超时/丢单 → BLOCK
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluators.finance.availability import (  # noqa: E402
    FAULT_KINDS,
    AvailabilityEvaluator,
    FaultObservation,
    FaultPlanError,
    FaultTemplate,
    execute_plan,
    render_plan,
    template_for,
)

NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def obs(
    kind: str,
    seconds: float | None,
    path: str = "orders",
    orders_lost: int = 0,
) -> FaultObservation:
    recovered = None if seconds is None else NOW + timedelta(seconds=seconds)
    return FaultObservation(
        kind=kind,
        path=path,
        started_at=NOW,
        recovered_at=recovered,
        orders_lost=orders_lost,
        impacted_requests=10,
        error_rate_curve=(0.2, 0.1, 0.0),
    )


def all_ok() -> list[FaultObservation]:
    return [
        obs("pod_kill", 8.0),
        obs("network_delay", 12.0),
        obs("exchange_timeout", 45.0, path="market_data"),
        obs("db_failover", 20.0),
        obs("disk_full", 25.0),
    ]


# ---------- 模板 ----------


def test_five_fault_templates_registered():
    assert FAULT_KINDS == (
        "pod_kill",
        "network_delay",
        "exchange_timeout",
        "db_failover",
        "disk_full",
    )
    assert all(isinstance(template_for(kind), FaultTemplate) for kind in FAULT_KINDS)


def test_unknown_template_rejected():
    with pytest.raises(FaultPlanError):
        template_for("unknown_fault")


def test_template_metadata_matches_spec():
    assert template_for("pod_kill").path == "orders"
    assert template_for("exchange_timeout").path == "market_data"
    assert template_for("db_failover").max_recovery_s == 30
    assert template_for("exchange_timeout").max_recovery_s == 60


@pytest.mark.parametrize(
    "kind,target",
    [
        ("pod_kill", {"pod_selector": "app=polling-trader"}),
        ("network_delay", {"iface": "eth0"}),
        ("exchange_timeout", {"dest": "api.binance.com"}),
        ("db_failover", {"db_host": "pg-primary"}),
        ("disk_full", {"mount": "/var/lib/eval"}),
    ],
)
def test_render_plan_substitutes_targets(kind, target):
    plan = render_plan(kind, target, nonce="p2-20261101")
    assert plan.kind == kind
    assert plan.namespace == "p2-20261101"
    assert plan.commands, "注入命令不能为空"
    assert all("{" not in cmd for cmd in plan.commands)
    assert all("}" not in cmd for cmd in plan.commands)


def test_render_plan_requires_target_key():
    with pytest.raises(FaultPlanError):
        render_plan("pod_kill", {})


def test_execute_plan_runs_commands_with_injected_runner():
    plan = render_plan("network_delay", {"iface": "eth0"}, nonce="p2-1")
    ran: list[str] = []
    result = execute_plan(plan, runner=ran.append)
    assert result.ok is True
    assert result.executed == list(plan.commands)
    assert ran == list(plan.commands)


def test_execute_plan_reports_runner_failure():
    plan = render_plan("disk_full", {"mount": "/tmp"})

    def boom(_cmd: str) -> None:
        raise RuntimeError("命令失败")

    result = execute_plan(plan, runner=boom)
    assert result.ok is False
    assert "命令失败" in result.error


# ---------- RTO/RPO 判定 ----------


def test_all_faults_within_slo_pass():
    items = AvailabilityEvaluator().evaluate(all_ok(), run_id="RUN-20261101-000002-01")
    assert len(items) == 1
    item = items[0]
    assert (item.name, item.kind, item.status) == ("F-H2-availability", "hard", "PASS")
    assert item.detail is None


def test_missing_fault_kind_blocks():
    observations = [o for o in all_ok() if o.kind != "disk_full"]
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert item.detail == "F-H2_missing_fault:disk_full"


def test_orders_rpo_must_be_zero():
    observations = [o for o in all_ok() if o.kind != "pod_kill"]
    observations.append(obs("pod_kill", 5.0, orders_lost=3))
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert "F-H2_order_rpo_violation:pod_kill" in (item.detail or "")


def test_orders_rto_limit_30s_strict():
    observations = [o for o in all_ok() if o.kind != "db_failover"]
    observations.append(obs("db_failover", 30.0))
    assert AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0].status == "PASS"

    observations[-1] = obs("db_failover", 30.5)
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert "F-H2_order_rto_exceeded:db_failover:30.5" in (item.detail or "")


def test_market_data_rto_limit_60s():
    observations = [o for o in all_ok() if o.kind != "exchange_timeout"]
    observations.append(obs("exchange_timeout", 59.0, path="market_data"))
    assert AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0].status == "PASS"

    observations[-1] = obs("exchange_timeout", 61.0, path="market_data")
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert "F-H2_market_rto_exceeded:exchange_timeout:61.0" in (item.detail or "")


def test_unrecovered_fault_blocks():
    observations = all_ok()
    observations[0] = obs("pod_kill", None)
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert item.detail == "F-H2_not_recovered:pod_kill"


def test_invalid_path_blocks():
    observations = all_ok()
    observations[1] = obs("network_delay", 3.0, path="unknown")
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert "F-H2_invalid_path:network_delay" in (item.detail or "")


def test_multiple_violations_are_all_reported():
    observations = [o for o in all_ok() if o.kind != "disk_full"]
    observations.append(obs("pod_kill", 40.0, orders_lost=2))
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert (
        item.detail
        == "F-H2_missing_fault:disk_full; F-H2_order_rto_exceeded:pod_kill:40.0; F-H2_order_rpo_violation:pod_kill"
    )


def test_evidence_completeness_requires_curves():
    bad = FaultObservation(
        kind="pod_kill",
        path="orders",
        started_at=NOW,
        recovered_at=NOW + timedelta(seconds=2),
        orders_lost=0,
        impacted_requests=0,
        error_rate_curve=(),
    )
    observations = [o for o in all_ok() if o.kind != "pod_kill"] + [bad]
    item = AvailabilityEvaluator().evaluate(observations, run_id="RUN-1")[0]
    assert item.status == "BLOCK"
    assert "F-H2_incomplete_evidence:pod_kill" in (item.detail or "")
