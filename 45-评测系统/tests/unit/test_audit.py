# -*- coding: utf-8 -*-
"""P3-5 门禁审计日志测试（append-only JSONL + 查询）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from storage.audit import AuditLog

NOW = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)


def make_log(tmp_path) -> AuditLog:
    return AuditLog(path=tmp_path / "enforcement.jsonl", clock=lambda: NOW)


def test_append_writes_jsonl(tmp_path):
    log = make_log(tmp_path)
    record = log.append({"kind": "deploy", "eval_id": "EV-1", "decision": "PASS"})

    assert record["at"] == "2026-11-01T00:00:00Z"
    lines = (tmp_path / "enforcement.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["eval_id"] == "EV-1"


def test_query_filters_by_eval_id_and_kind(tmp_path):
    log = make_log(tmp_path)
    log.append({"kind": "deploy", "eval_id": "EV-1", "decision": "PASS"})
    log.append({"kind": "l0_settle", "eval_id": "EV-1", "decision": "BLOCK"})
    log.append({"kind": "deploy", "eval_id": "EV-2", "decision": "PASS"})

    assert len(log.query(eval_id="EV-1")) == 2
    assert len(log.query(eval_id="EV-1", kind="l0_settle")) == 1
    assert len(log.query(kind="deploy")) == 2


def test_query_newest_first_and_limit(tmp_path):
    log = make_log(tmp_path)
    for i in range(5):
        log.append({"kind": "deploy", "eval_id": f"EV-{i}", "decision": "PASS"})

    rows = log.query(limit=2)
    assert [r["eval_id"] for r in rows] == ["EV-4", "EV-3"]


def test_query_missing_file_returns_empty(tmp_path):
    log = AuditLog(path=tmp_path / "nope.jsonl", clock=lambda: NOW)
    assert log.query() == []


def test_append_creates_parent_dir(tmp_path):
    log = AuditLog(path=tmp_path / "nested" / "audit.jsonl", clock=lambda: NOW)
    log.append({"kind": "deploy", "eval_id": "EV-1", "decision": "PASS"})
    assert (tmp_path / "nested" / "audit.jsonl").is_file()
