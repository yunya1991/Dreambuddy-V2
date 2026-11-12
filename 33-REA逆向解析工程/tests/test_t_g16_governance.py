"""T-G16 权限切分与发布治理 — RED 测试

SPEC-33-G §2.11.8：
  - 三权分立：编排器不得同时持有提案 / 合并 / 部署三类凭据
  - 合并：CI 机器人仅 `evo/* → main`；请求必须携带 change_id + proposal_id + 门禁结论摘要
  - 部署：发布系统独占；同环境同一时刻仅 1 个发布（分布式锁，TTL 可配）
  - 人工接管：环境必须登记 owner 与 RTO/RPO，未声明不得部署
  - 分支生命周期：未合并分支 14 天归档；落后 main 超阈值告警（阈值入配置）

RED 契约：core.evolution.governance 不存在。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from core.evolution.governance import Governance, GovernanceError

BASE = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


def _gate_pass():
    return {"overall": "pass", "gates": [{"gate": i, "status": "pass"} for i in range(1, 9)]}


def _governance(tmp_path, clock=None):
    return Governance(
        tmp_path / "governance",
        clock=clock or Clock(),
        lock_ttl_seconds=900,
        branch_archive_days=14,
        behind_main_threshold=50,
    )


def _merge(gov, **overrides):
    payload = {
        "actor": "ci_bot",
        "change_id": "CH-1",
        "proposal_id": "PP-1",
        "gate_summary": _gate_pass(),
        "branch": "evo/CH-1",
    }
    payload.update(overrides)
    return gov.request_merge(**payload)


def _deploy(gov, **overrides):
    payload = {
        "actor": "release_system",
        "change_id": "CH-1",
        "proposal_id": "PP-1",
        "gate_summary": _gate_pass(),
        "env": "staging",
        "owner": "ops-oncall",
        "rto": "15m",
        "rpo": "5m",
    }
    payload.update(overrides)
    return gov.request_deploy(**payload)


# ---------------------------------------------------------------- 三权分立


def test_orchestrator_holds_no_merge_or_deploy_credentials(tmp_path):
    gov = _governance(tmp_path)

    with pytest.raises(GovernanceError, match="合并"):
        _merge(gov, actor="orchestrator")
    with pytest.raises(GovernanceError, match="部署"):
        _deploy(gov, actor="orchestrator")

    with pytest.raises(GovernanceError, match="三权"):
        gov.validate_credentials("orchestrator", {"propose", "merge"})
    gov.validate_credentials("ci_bot", {"merge"})
    gov.validate_credentials("release_system", {"deploy"})


# ---------------------------------------------------------------- 合并治理


def test_merge_requires_ids_gate_summary_and_evo_branch(tmp_path):
    gov = _governance(tmp_path)

    with pytest.raises(GovernanceError, match="change_id"):
        _merge(gov, change_id="")
    with pytest.raises(GovernanceError, match="proposal_id"):
        _merge(gov, proposal_id="")
    with pytest.raises(GovernanceError, match="门禁"):
        _merge(gov, gate_summary={"overall": "fail", "gates": []})
    with pytest.raises(GovernanceError, match="evo/"):
        _merge(gov, branch="main")

    result = _merge(gov)
    assert result["status"] == "merge_requested"
    assert result["branch"] == "evo/CH-1"
    assert result["change_id"] == "CH-1"


def test_branch_lifecycle_archive_and_alert(tmp_path):
    gov = _governance(tmp_path)

    active = gov.branch_status(branch="evo/CH-1", days_since_update=3, behind_main=10)
    assert active["state"] == "active"
    assert active["alert"] is False

    stale = gov.branch_status(branch="evo/CH-2", days_since_update=15, behind_main=10)
    assert stale["state"] == "archive"

    behind = gov.branch_status(branch="evo/CH-3", days_since_update=3, behind_main=51)
    assert behind["alert"] is True
    assert behind["state"] == "active"


# ---------------------------------------------------------------- 发布治理


def test_deploy_requires_env_owner_and_rto_rpo(tmp_path):
    gov = _governance(tmp_path)

    with pytest.raises(GovernanceError, match="owner"):
        _deploy(gov, owner="")
    with pytest.raises(GovernanceError, match="RTO"):
        _deploy(gov, rto="")
    with pytest.raises(GovernanceError, match="RPO"):
        _deploy(gov, rpo="")
    with pytest.raises(GovernanceError, match="部署"):
        _deploy(gov, actor="ci_bot")

    result = _deploy(gov)
    assert result["status"] == "deploy_requested"
    assert result["env"] == "staging"
    assert result["lock"]["change_id"] == "CH-1"


def test_single_deploy_lock_per_env_with_ttl(tmp_path):
    clock = Clock()
    gov = _governance(tmp_path, clock)

    first = _deploy(gov)
    assert first["lock"]["expires_at"]

    with pytest.raises(GovernanceError, match="锁"):
        _deploy(gov, change_id="CH-2", proposal_id="PP-2")

    clock.now = BASE + timedelta(seconds=901)
    resumed = _deploy(gov, change_id="CH-2", proposal_id="PP-2")
    assert resumed["lock"]["change_id"] == "CH-2"

    gov.release_deploy(env="staging", change_id="CH-2")
    assert gov.deploy_lock("staging") is None
    assert _deploy(gov, change_id="CH-3", proposal_id="PP-3")["status"] == "deploy_requested"


def test_release_wrong_owner_cannot_unlock(tmp_path):
    gov = _governance(tmp_path)
    _deploy(gov)

    with pytest.raises(GovernanceError, match="锁"):
        gov.release_deploy(env="staging", change_id="CH-404")
