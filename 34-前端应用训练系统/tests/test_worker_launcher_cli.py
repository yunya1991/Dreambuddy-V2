# -*- coding: utf-8 -*-
"""W4 运维 CLI 单测：preflight / once / status（PROPOSAL-P0-D3 §4.9）。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.worker_launcher_cli import _acquire_instance_lock, main  # noqa: E402

_ROLES_YAML = """worker_roles:
  research:
    description: 研究 Worker
    shells: [l0.cognition.mcp]
    tools: [recall]
"""


def _write_roles(tmp_path) -> str:
    path = tmp_path / "roles.yaml"
    path.write_text(_ROLES_YAML, encoding="utf-8")
    return str(path)


def _write_inbox(root, records) -> None:
    inbox = root / "34-前端应用训练系统" / "dsh_worker_inbox.jsonl"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    inbox.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _metrics(root):
    path = root / "34-前端应用训练系统" / ".worker_launcher" / "metrics.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_preflight_ok(tmp_path, capsys):
    code = main(["preflight", "--root", str(tmp_path), "--roles", _write_roles(tmp_path)])
    assert code == 0
    report = json.loads(capsys.readouterr().out.strip())
    assert report["ok"] is True
    assert report["problems"] == []


def test_preflight_rejects_empty_roster(tmp_path, capsys):
    missing = str(tmp_path / "missing.yaml")
    code = main(["preflight", "--root", str(tmp_path), "--roles", missing])
    assert code == 2
    report = json.loads(capsys.readouterr().out.strip())
    assert report["ok"] is False
    assert any("roster" in problem for problem in report["problems"])


def test_once_executes_and_records_metrics(tmp_path, capsys):
    roles = _write_roles(tmp_path)
    _write_inbox(
        tmp_path,
        [{"ticket_id": "T-1", "role": "research", "worker_id": "w-1", "mandate": {"goal": "g"}}],
    )
    code = main(["once", "--root", str(tmp_path), "--roles", roles, "--executor", "noop"])
    assert code == 0
    stats = json.loads(capsys.readouterr().out.strip())
    assert stats["done"] == 1
    assert stats["pass_offset"] > 0

    receipts = (tmp_path / "34-前端应用训练系统" / "dsh_worker_receipts.jsonl").read_text(
        encoding="utf-8"
    )
    receipt = json.loads(receipts.splitlines()[0])
    assert receipt["status"] == "done"

    metrics = _metrics(tmp_path)
    assert metrics["passes"] == 1
    assert metrics["counters"]["done"] == 1
    assert metrics["latency_ms"]["count"] == 1
    assert metrics["success_rate"] == 1.0


def test_once_counts_role_rejection(tmp_path, capsys):
    roles = _write_roles(tmp_path)
    _write_inbox(tmp_path, [{"ticket_id": "T-2", "role": "unknown-role"}])
    code = main(["once", "--root", str(tmp_path), "--roles", roles, "--executor", "noop"])
    assert code == 0
    capsys.readouterr()

    metrics = _metrics(tmp_path)
    assert metrics["counters"]["role_rejections"] == 1
    assert metrics["counters"]["failed"] == 1
    assert metrics["success_rate"] == 0.0


def test_instance_lock_rejects_second_instance(tmp_path):
    path = str(tmp_path / "launcher.lock")
    first = _acquire_instance_lock(path)
    assert first is not None
    assert _acquire_instance_lock(path) is None
    first.close()
    again = _acquire_instance_lock(path)
    assert again is not None
    again.close()


def test_status_reports_metrics_and_claims(tmp_path, capsys):
    roles = _write_roles(tmp_path)
    _write_inbox(tmp_path, [{"ticket_id": "T-3", "role": "research"}])
    main(["once", "--root", str(tmp_path), "--roles", roles, "--executor", "noop"])
    capsys.readouterr()

    code = main(["status", "--root", str(tmp_path), "--roles", roles, "--executor", "noop"])
    assert code == 0
    report = json.loads(capsys.readouterr().out.strip())
    assert report["metrics"]["passes"] == 1
    assert report["claims"]["total"] == 0
