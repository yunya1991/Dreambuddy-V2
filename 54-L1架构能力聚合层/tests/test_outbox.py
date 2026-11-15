# -*- coding: utf-8 -*-
"""L1X-03 outbox 幂等投递 + 失败重投单测。"""

import hashlib
import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import handoff  # noqa: E402
from l1agg.trading import outbox  # noqa: E402

_SIGNAL = {
    "as_of": "2026-11-14",
    "symbol": "BTC",
    "rule_version": "dr-1.0.0",
    "params_hash": "abcdef1234567890",
    "direction": 1,
    "strength": 0.81,
    "band": "strong",
    "flags": ["coherence_missing"],
}


def _decision(**overrides):
    signal = dict(_SIGNAL, **overrides)
    return handoff.build_final_decision(signal, notional_usdt=400.0)


def test_migrate_is_idempotent(tmp_path):
    db = str(tmp_path / "outbox.db")
    assert outbox.migrate(db)["created"] == ["outbox"]
    assert outbox.migrate(db)["created"] == []


def test_enqueue_dedupes_same_decision(tmp_path):
    db = str(tmp_path / "outbox.db")
    decision = _decision()
    first = outbox.enqueue(decision, db_path=db)
    assert first["status"] == outbox.STATE_QUEUED
    second = outbox.enqueue(decision, db_path=db)
    assert second["status"] == "duplicate"
    assert second["dedup_key"] == first["dedup_key"]
    assert len(outbox.pending(db_path=db)) == 1


def test_dedup_key_is_stable_and_sensitive():
    key = outbox.dedup_key(_decision())
    assert key == outbox.dedup_key(_decision())
    expected = hashlib.sha256(
        json.dumps(
            {"decision_id": _decision()["payload"]["decision_id"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert key == expected
    assert outbox.dedup_key(_decision(as_of="2026-11-13")) != key
    assert outbox.dedup_key(_decision(direction=-1)) != key
    with pytest.raises(ValueError):
        outbox.dedup_key({"payload": {}})


def test_replay_sends_once_and_skips_sent(tmp_path):
    db = str(tmp_path / "outbox.db")
    decision = _decision()
    outbox.enqueue(decision, db_path=db)
    sent = []
    first = outbox.replay_pending(sent.append, db_path=db)
    assert first == {"sent": 1, "failed": 0}
    assert len(sent) == 1 and sent[0]["payload"]["decision_id"]
    assert outbox.pending(db_path=db) == []
    assert outbox.get(outbox.dedup_key(decision), db_path=db)["state"] == outbox.STATE_SENT
    # 重投整个队列：已 sent 不再发第二次
    assert outbox.replay_pending(sent.append, db_path=db) == {"sent": 0, "failed": 0}
    assert len(sent) == 1


def test_failure_is_retried_until_sent(tmp_path):
    db = str(tmp_path / "outbox.db")
    decision = _decision()
    key = outbox.enqueue(decision, db_path=db)["dedup_key"]

    def _boom(_payload):
        raise RuntimeError("22 网关不可用")

    assert outbox.replay_pending(_boom, db_path=db) == {"sent": 0, "failed": 1}
    row = outbox.get(key, db_path=db)
    assert row["state"] == outbox.STATE_FAILED
    assert row["attempts"] == 1
    assert "22 网关不可用" in row["last_error"]
    assert len(outbox.pending(db_path=db)) == 1

    # 幂等的「重复 signal」不会制造第二条待投递记录
    assert outbox.enqueue(decision, db_path=db)["status"] == "duplicate"
    assert len(outbox.pending(db_path=db)) == 1

    assert outbox.replay_pending(lambda _p: True, db_path=db) == {"sent": 1, "failed": 0}
    row = outbox.get(key, db_path=db)
    assert row["state"] == outbox.STATE_SENT
    assert row["attempts"] == 1
    assert row["last_error"] is None
    assert outbox.pending(db_path=db) == []


def test_send_returning_false_counts_as_failure(tmp_path):
    db = str(tmp_path / "outbox.db")
    key = outbox.enqueue(_decision(), db_path=db)["dedup_key"]
    assert outbox.replay_pending(lambda _p: False, db_path=db) == {"sent": 0, "failed": 1}
    assert outbox.get(key, db_path=db)["last_error"] == "send_returned_false"


def test_distinct_signals_get_distinct_rows(tmp_path):
    db = str(tmp_path / "outbox.db")
    a = outbox.enqueue(_decision(), db_path=db)
    b = outbox.enqueue(_decision(as_of="2026-11-13", direction=-1), db_path=db)
    assert a["dedup_key"] != b["dedup_key"]
    assert len(outbox.pending(db_path=db)) == 2
