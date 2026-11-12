"""L2-7 自动合入 — RED 测试

SPEC-33-G §2.11.4 L2-7 / §2.11.8 / §2.11.9：
  - 自动合入只允许 `evo/<change_id>` → main，由 CI 机器人执行，编排器只发请求
  - main 保护规则不放松；合入不得触发部署
  - 前置：CI 全绿 + 回滚演练通过（L2-5）+ 断路器关闭 + ≥30 条有效 outcome 且 ≥24h
          + held-out 对应桶 ≥20 条 + 八门禁全 pass
  - stateful 禁止自动（L2-9）；新增依赖 / 改契约 / schema → 拒绝（L2-3 / L2-4）
  - L3 不进入合入通道

RED 契约：core.evolution.auto_merge 不存在。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from core.evolution.auto_merge import AutoMergeBlocked, AutoMergeCoordinator
from core.evolution.governance import Governance, GovernanceError

BASE = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


def _gate_pass():
    return {
        "overall": "pass",
        "gates": [{"gate": index, "status": "pass"} for index in range(1, 9)],
    }


def _outcomes(count=30, span_hours=24, change_id="CH-1"):
    start = BASE - timedelta(hours=span_hours)
    return [
        {
            "change_id": change_id,
            "run_id": f"RUN-{index}",
            "outcome_seq": index,
            "accepted": True,
            "tests_pass": True,
            "reverted": False,
            "created_at": (
                start + timedelta(hours=span_hours * index / max(count - 1, 1))
            ).isoformat(),
        }
        for index in range(count)
    ]


def _coordinator(tmp_path, **overrides):
    kwargs = {
        "governance": Governance(tmp_path / "governance", clock=Clock()),
        "clock": Clock(),
    }
    kwargs.update(overrides)
    return AutoMergeCoordinator(**kwargs)


def _request(coordinator, **overrides):
    payload = {
        "change_id": "CH-1",
        "proposal_id": "P-1",
        "level": "L2",
        "stateful": False,
        "files": ["33-REA逆向解析工程/core/evolution/demo.py"],
        "lines_changed": 80,
        "branch": "evo/CH-1",
        "ci_status": "success",
        "rollback_drill": "pass",
        "breaker": {"state": "closed"},
        "gate_summary": _gate_pass(),
        "outcomes": _outcomes(),
        "heldout_bucket": 25,
    }
    payload.update(overrides)
    return coordinator.request(**payload)


def test_request_returns_merge_request_without_deploy(tmp_path):
    result = _request(_coordinator(tmp_path))

    assert result["status"] == "merge_requested"
    assert result["change_id"] == "CH-1"
    assert result["branch"] == "evo/CH-1"
    assert result["deploy_triggered"] is False
    assert result["main_protection"] == "unchanged"
    assert result["executor"] == "ci_bot"


@pytest.mark.parametrize(
    "overrides,keyword",
    [
        ({"stateful": True}, "L2-9"),
        ({"level": "L3"}, "L3"),
        ({"branch": "feature/CH-1"}, "evo/"),
        ({"ci_status": "failure"}, "CI"),
        ({"rollback_drill": "fail"}, "回滚"),
        ({"breaker": {"state": "open"}}, "断路器"),
        ({"outcomes": _outcomes(count=29)}, "outcome"),
        ({"outcomes": _outcomes(span_hours=12)}, "24"),
        ({"heldout_bucket": 19}, "held-out"),
        ({"files": [f"33-REA逆向解析工程/core/m{i}.py" for i in range(4)]}, "文件"),
        ({"lines_changed": 201}, "行"),
        ({"adds_dependency": True}, "依赖"),
        ({"changes_contract": True}, "契约"),
        ({"changes_schema": True}, "schema"),
    ],
)
def test_request_blocks_when_prerequisite_missing(tmp_path, overrides, keyword):
    with pytest.raises(AutoMergeBlocked) as excinfo:
        _request(_coordinator(tmp_path), **overrides)
    assert keyword in str(excinfo.value)


def test_complete_merge_requires_ci_bot(tmp_path):
    coordinator = _coordinator(tmp_path)
    request = _request(coordinator)

    with pytest.raises(GovernanceError):
        coordinator.complete(request, actor="orchestrator")

    merged = coordinator.complete(request, actor="ci_bot")
    assert merged["status"] == "merged"
    assert merged["branch_deleted"] is True
    assert merged["deploy_triggered"] is False


def test_complete_merge_requires_green_ci_again(tmp_path):
    coordinator = _coordinator(tmp_path)
    request = _request(coordinator)

    with pytest.raises(AutoMergeBlocked) as excinfo:
        coordinator.complete(request, actor="ci_bot", ci_status="failure")
    assert "CI" in str(excinfo.value)
