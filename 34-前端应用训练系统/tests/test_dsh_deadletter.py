# -*- coding: utf-8 -*-
"""P0-D3C RED: DSH 死信队列与租约。

契约:
  DeadLetterStore.append / claim / complete / list_pending
  并发 claim 仅一个成功；租约过期可重领；不修改 Ticket。
"""

import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.dsh_deadletter import DeadLetterEntry, DeadLetterStore  # noqa: E402

NOW = 10_000.0


def _entry(entry_id="DL-1", ticket_id="TK-1", **kw):
    data = {
        "entry_id": entry_id,
        "ticket_id": ticket_id,
        "trace_id": "rp-1",
        "trigger": "retry_exhausted",
        "payload": {"failure_class": "manual", "attempts": 3},
        "created_at": NOW,
    }
    data.update(kw)
    return DeadLetterEntry(**data)


def test_append_and_list_pending():
    store = DeadLetterStore()
    assert store.append(_entry()) is True
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["entry_id"] == "DL-1"


def test_claim_only_once():
    store = DeadLetterStore()
    store.append(_entry())
    first = store.claim("hermes-1", now=NOW, lease_ttl_s=300)
    assert first is not None
    assert first["status"] == "claimed"
    assert first["claimed_by"] == "hermes-1"
    second = store.claim("hermes-2", now=NOW + 1, lease_ttl_s=300)
    assert second is None


def test_expired_lease_reclaimable():
    store = DeadLetterStore()
    store.append(_entry())
    assert store.claim("hermes-1", now=NOW, lease_ttl_s=10) is not None
    again = store.claim("hermes-2", now=NOW + 11, lease_ttl_s=300)
    assert again is not None
    assert again["claimed_by"] == "hermes-2"


def test_complete_records_result():
    store = DeadLetterStore()
    store.append(_entry())
    store.claim("hermes-1", now=NOW)
    assert store.complete("DL-1", {"status": "resolved"}, now=NOW + 1) is True
    done = store.get("DL-1")
    assert done["status"] == "completed"
    assert done["result"] == {"status": "resolved"}


def test_persistence(tmp_path):
    path = tmp_path / "deadletter.jsonl"
    store = DeadLetterStore(str(path))
    store.append(_entry())
    store.claim("hermes-1", now=NOW)
    store.complete("DL-1", {"status": "partial"}, now=NOW + 1)
    again = DeadLetterStore(str(path))
    assert again.get("DL-1")["status"] == "completed"
    assert again.get("DL-1")["result"] == {"status": "partial"}


def test_concurrent_claim_only_one_wins():
    store = DeadLetterStore()
    store.append(_entry())
    results = []
    lock = threading.Lock()

    def worker(name):
        got = store.claim(name, now=NOW, lease_ttl_s=300)
        with lock:
            results.append(got is not None)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r) == 1
