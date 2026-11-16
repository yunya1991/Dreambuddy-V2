"""A2-1: L1 发现 → repair_ledger.trigger 入队（契约 v1.1）

覆盖:
  - 生成条目满足 v1.1（初始 reported→reported 自迁移）
  - trigger 可追溯（source=l1_finding / resolver=54.discovery_path）
  - 幂等入队 + task_id 递增 + 复现产物哈希
  - 非法输入 fail-closed（ref / symptom / 复现证据）
  - 产出文件经 56 官方校验器 `--ledger` 0 violation
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent  # 34-前端应用训练系统/
REPO_ROOT = BASE.parent
sys.path.insert(0, str(BASE))

from core.l2_repair_ledger import (  # noqa: E402
    LedgerError,
    build_entry,
    enqueue_l1_finding,
    load_ledger,
    validate_entry,
)

NOW = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def _finding(**overrides):
    data = {
        "ref": "reports/discovery/20261117-0001",
        "symptom": "L1 语义路由在空候选集时 margin 恒为 0，导致直答误判",
        "repro_cmd": "pytest tests/test_semantic_margin.py -k empty",
        "artifact_hash": "sha256:" + "a" * 64,
        "kind": "bugfix",
        "base_commit": "a1b2c3d",
    }
    data.update(overrides)
    return data


def test_build_entry_is_contract_valid():
    entry = build_entry(_finding(), now=NOW)
    validate_entry(entry)

    assert entry["schema_version"] == "1.1"
    assert entry["task_id"] == "fix-20261117-001"
    assert entry["state"] == "reported"
    assert entry["history"] == [
        {
            "from": "reported",
            "to": "reported",
            "at": entry["created_at"],
            "by": "l1_finding",
        }
    ]
    assert entry["trigger"]["source"] == "l1_finding"
    assert entry["trigger"]["resolver"] == "54.discovery_path"
    assert entry["evidence"]["repro"]["fails_on_base"] is True
    assert entry["attempts"] == 0


def test_task_id_increments_per_kind_and_day(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    first = enqueue_l1_finding(_finding(), ledger_path=ledger, now=NOW)
    second = enqueue_l1_finding(
        _finding(
            ref="reports/discovery/20261117-0002", symptom="另一个独立的 L1 发现：指标漂移超阈值"
        ),
        ledger_path=ledger,
        now=NOW,
    )

    assert first["task_id"] == "fix-20261117-001"
    assert second["task_id"] == "fix-20261117-002"
    assert len(load_ledger(ledger)) == 2


def test_duplicate_finding_is_idempotent(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    first = enqueue_l1_finding(_finding(), ledger_path=ledger, now=NOW)
    again = enqueue_l1_finding(_finding(), ledger_path=ledger, now=NOW)

    assert again["task_id"] == first["task_id"]
    assert len(load_ledger(ledger)) == 1


def test_artifact_hash_computed_from_file(tmp_path):
    artifact = tmp_path / "discovery.json"
    artifact.write_text('{"drift": 0.42}', encoding="utf-8")

    entry = build_entry(_finding(artifact_hash=None, artifact_path=str(artifact)), now=NOW)
    assert entry["evidence"]["repro"]["artifact_hash"].startswith("sha256:")
    assert len(entry["evidence"]["repro"]["artifact_hash"]) == 71


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"ref": "reports/other/20261117-0001"}, "54.discovery_path"),
        ({"symptom": "有问题"}, "symptom"),
        ({"repro_cmd": ""}, "repro_cmd"),
        ({"base_commit": "xyz"}, "base_commit"),
        ({"kind": "refactor"}, "kind"),
        ({"artifact_hash": None}, "artifact_path"),
    ],
)
def test_invalid_findings_fail_closed(bad, message):
    with pytest.raises(LedgerError) as exc:
        build_entry(_finding(**bad), now=NOW)
    assert message in str(exc.value)


def test_optimization_requires_evidence():
    """优化类发现期无 45/统计证据 → 拒绝入队（G-L2-8，不写空壳）"""
    with pytest.raises(LedgerError) as exc:
        build_entry(_finding(kind="optimization"), now=NOW)
    assert "optimization" in str(exc.value)


def test_ledger_passes_official_validator(tmp_path):
    ledger = tmp_path / "l2_repair_ledger.jsonl"
    enqueue_l1_finding(_finding(), ledger_path=ledger, now=NOW)
    enqueue_l1_finding(
        _finding(
            ref="reports/discovery/20261117-0002",
            kind="optimization",
            symptom="优化候选：语义阈值可下调减少误拒",
            optimization_evidence={"gate45": "PASS"},
            metrics=[{"name": "reject_rate", "unit": "%", "before": 8.0, "after": 5.0}],
        ),
        ledger_path=ledger,
        now=NOW,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "56-L2架构能力聚合层" / "scripts" / "validate_contracts.py"),
            "--ledger",
            str(ledger),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
