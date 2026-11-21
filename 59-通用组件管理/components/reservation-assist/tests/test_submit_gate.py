"""提交门禁回归：默认拒绝、grant 绑定、就绪开关、终态幂等、无锁座调用。"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import _support
import security
from adapters import GateDenied, get_adapter
from adapters.base import BaseHttpAdapter, Hit, SubmitResult, target_fingerprint
from store import Store

NOW = 1763635200000
SECRET = b"test-secret"


class ReadyAdapter(BaseHttpAdapter):
    NAME = "ready"
    SUBMIT_READY = True

    def submit(self, hit: Hit, grant, transport) -> SubmitResult:
        return SubmitResult(state="ok", official_order_ref="R-1")


class SubmitGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = _support.temp_dir()
        self.db = Store(Path(self.dir) / "state.db")
        self.task = _support.make_task(submit_enabled=1)
        self.db.add_task(self.task)
        self.fingerprint = target_fingerprint(self.task, NOW)
        self._real_container = security.is_container
        security.is_container = lambda: False

    def tearDown(self) -> None:
        security.is_container = self._real_container
        self.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _grant(self, fingerprint: str | None = None, ttl_ms: int = 3600_000) -> dict:
        grant = security.issue_grant(
            self.task["id"], fingerprint or self.fingerprint, SECRET, now=NOW, ttl_ms=ttl_ms
        )
        self.db.put_grant(grant)
        return grant

    def test_denies_without_grant(self):
        with self.assertRaises(GateDenied) as ctx:
            security.evaluate_submit(
                self.task, ReadyAdapter(), self.db, SECRET, env={"RA_ALLOW_SUBMIT": "1"}, now=NOW
            )
        self.assertEqual(str(ctx.exception), "grant")

    def test_env_zero_denies_even_with_grant(self):
        self._grant()
        with self.assertRaises(GateDenied) as ctx:
            security.evaluate_submit(
                self.task, ReadyAdapter(), self.db, SECRET, env={"RA_ALLOW_SUBMIT": "0"}, now=NOW
            )
        self.assertEqual(str(ctx.exception), "env")

    def test_adapter_not_ready_denies(self):
        self._grant()
        with self.assertRaises(GateDenied) as ctx:
            security.evaluate_submit(
                self.task, get_adapter("railway"), self.db, SECRET, env={}, now=NOW
            )
        self.assertEqual(str(ctx.exception), "adapter_not_ready")

    def test_grant_fingerprint_mismatch_denies(self):
        self._grant(fingerprint="b" * 64)
        with self.assertRaises(GateDenied):
            security.evaluate_submit(self.task, ReadyAdapter(), self.db, SECRET, env={}, now=NOW)

    def test_expired_grant_denies(self):
        self._grant(ttl_ms=1000)
        with self.assertRaises(GateDenied):
            security.evaluate_submit(
                self.task, ReadyAdapter(), self.db, SECRET, env={}, now=NOW + 2000
            )

    def test_task_config_requires_price_and_identity(self):
        self._grant()
        self.task["rule"] = {"identity_selected": True}
        with self.assertRaises(GateDenied) as ctx:
            security.evaluate_submit(self.task, ReadyAdapter(), self.db, SECRET, env={}, now=NOW)
        self.assertEqual(str(ctx.exception), "task_config")

    def test_terminal_state_blocks_replay(self):
        self._grant()
        self.db.upsert_hit(self.task["id"], self.fingerprint, NOW)
        self.db.set_submit_state(self.task["id"], self.fingerprint, "submitted")
        with self.assertRaises(GateDenied) as ctx:
            security.evaluate_submit(self.task, ReadyAdapter(), self.db, SECRET, env={}, now=NOW)
        self.assertEqual(str(ctx.exception), "already_submitted")

    def test_positive_path_when_all_gates_pass(self):
        self._grant()
        grant = security.evaluate_submit(
            self.task, ReadyAdapter(), self.db, SECRET, env={}, now=NOW
        )
        result = ReadyAdapter().submit(None, grant, _support.FakeTransport())
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.official_order_ref, "R-1")

    def test_unready_adapter_submit_raises(self):
        hit = Hit(
            task_id="t",
            fingerprint="f",
            adapter="railway",
            target_id="G1",
            session="",
            price_tier="",
        )
        with self.assertRaises(GateDenied) as ctx:
            get_adapter("railway").submit(hit, None, _support.FakeTransport())
        self.assertEqual(str(ctx.exception), "adapter_not_ready")

    def test_no_seat_lock_calls_in_source(self):
        scripts = Path(_support.COMPONENT_ROOT) / "skill" / "scripts"
        tokens = ("lock_seat", "occupy_seat", "hold_seat")
        for path in scripts.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in tokens:
                self.assertNotIn(token, text, "{} 出现 {}".format(path.name, token))


if __name__ == "__main__":
    unittest.main()
