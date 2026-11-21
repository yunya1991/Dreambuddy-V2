"""存储回归：DDL、幂等、指纹、TTL、通知持久化、grant 级联。"""

from __future__ import annotations

import shutil
import time
import unittest
from pathlib import Path

import _support
from adapters.base import fingerprint
from store import Store

NOW = 1763635200000  # 2026-11-20T12:00:00+08:00


class StoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = _support.temp_dir()
        self.path = Path(self.dir) / "state.db"
        self.db = Store(self.path)
        self.task = _support.make_task()
        self.db.add_task(self.task)

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_tables_and_schema_version(self):
        tables = {
            row[0]
            for row in self.db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertTrue({"tasks", "hits", "events", "grants", "drills", "meta"} <= tables)
        self.assertEqual(self.db.get_meta("schema_version"), "2")

    def test_set_task_notify(self):
        self.db.add_task(_support.make_task(id="t1"))
        self.assertTrue(self.db.set_task_notify("t1", "feishu,local"))
        self.assertEqual(self.db.get_task("t1")["rule"]["notify"], "feishu,local")
        self.assertFalse(self.db.set_task_notify("missing", "feishu"))

    def test_drills_roundtrip(self):
        self.db.add_drill("railway", "login", True, {"state": "ok"}, at=NOW)
        self.db.add_drill("railway", "submit", False, {"result": "wrong_target"}, at=NOW + 1)
        self.db.add_drill("damai", "login", True, {}, at=NOW)
        self.assertEqual(len(self.db.list_drills("railway")), 2)
        self.assertEqual(len(self.db.list_drills("railway", kind="login")), 1)
        self.assertEqual(len(self.db.list_drills(kind="login")), 2)
        self.assertFalse(self.db.list_drills("railway", kind="submit")[0]["ok"])

    def test_task_crud_and_cascade(self):
        self.assertEqual(len(self.db.list_tasks()), 1)
        self.db.upsert_hit(self.task["id"], "fp1", NOW)
        self.db.put_grant(
            {
                "id": "g1",
                "task_id": self.task["id"],
                "fingerprint": "fp1",
                "issued_at": NOW,
                "expires_at": NOW + 1000,
                "hmac": "x",
            }
        )
        self.assertTrue(self.db.delete_task(self.task["id"]))
        self.assertEqual(self.db.list_hits(), [])
        self.assertIsNone(self.db.get_grant(self.task["id"]))

    def test_upsert_hit_is_idempotent(self):
        self.assertTrue(self.db.upsert_hit(self.task["id"], "fp1", NOW, "digest"))
        for _ in range(99):
            self.assertFalse(self.db.upsert_hit(self.task["id"], "fp1", NOW, "digest"))
        self.assertEqual(len(self.db.list_hits(self.task["id"])), 1)

    def test_fingerprint_is_stable(self):
        value = fingerprint("railway", "G1", "2026-12-01", "2026-12-01 08:00", "二等座")
        self.assertEqual(len(value), 64)
        self.assertEqual(
            value, fingerprint("railway", "G1", "2026-12-01", "2026-12-01 08:00", "二等座")
        )
        self.assertNotEqual(
            value, fingerprint("railway", "G1", "2026-12-02", "2026-12-01 08:00", "二等座")
        )

    def test_notified_at_persists_across_reopen(self):
        from notify import deliver_once

        notifier = _support.FakeNotifier()
        self.db.upsert_hit(self.task["id"], "fp1", NOW)
        for _ in range(100):
            deliver_once(self.db, notifier, self.task["id"], "fp1", "hi", NOW)
        self.assertEqual(len(notifier.calls), 1)
        self.db.close()
        self.db = Store(self.path)
        self.assertFalse(deliver_once(self.db, notifier, self.task["id"], "fp1", "hi", NOW))
        self.assertEqual(len(notifier.calls), 1)
        self.assertIsNotNone(self.db.get_hit(self.task["id"], "fp1")["notified_at"])

    def test_purge_ttl(self):
        now = int(time.time() * 1000)
        self.db.upsert_hit(self.task["id"], "old", now - 31 * 86400 * 1000)
        self.db.upsert_hit(self.task["id"], "new", now)
        self.db.add_event("info", "old_event")
        with self.db.tx() as conn:
            conn.execute("UPDATE events SET at=?", (now - 91 * 86400 * 1000,))
        self.db.put_grant(
            {
                "id": "g1",
                "task_id": self.task["id"],
                "fingerprint": "new",
                "issued_at": now - 1000,
                "expires_at": now - 500,
                "hmac": "x",
            }
        )
        removed = self.db.purge(now)
        self.assertEqual(removed["hits"], 1)
        self.assertEqual(removed["events"], 1)
        self.assertEqual(removed["grants"], 1)
        self.assertEqual([hit["fingerprint"] for hit in self.db.list_hits()], ["new"])

    def test_terminal_submit_states(self):
        self.db.upsert_hit(self.task["id"], "fp1", NOW)
        self.assertFalse(self.db.has_terminal_submit(self.task["id"], "fp1"))
        for state in ("submitted", "unknown", "closed"):
            self.db.set_submit_state(self.task["id"], "fp1", state)
            self.assertTrue(self.db.has_terminal_submit(self.task["id"], "fp1"))


if __name__ == "__main__":
    unittest.main()
