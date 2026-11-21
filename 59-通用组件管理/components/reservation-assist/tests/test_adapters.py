"""适配器 fixture 回放：只读解析与匹配结果稳定。"""

from __future__ import annotations

import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import _support
from adapters import ADAPTERS, get_adapter
from adapters.base import CN_TZ, fingerprint, iter_fixture_cases, load_fixture
from notify import deliver_once
from store import Store

FIXTURES = Path(_support.COMPONENT_ROOT) / "tests" / "fixtures"
STAMP = int(datetime(2026, 12, 1, 12, 0, tzinfo=CN_TZ).timestamp() * 1000)

EXPECTED_NAMES = ["bilibili", "damai", "gov", "maoyan", "medical", "railway"]


class AdapterFixtureTest(unittest.TestCase):
    def test_every_adapter_replays(self):
        cases = list(iter_fixture_cases(FIXTURES))
        self.assertEqual(sorted({name for name, _ in cases}), EXPECTED_NAMES)

        for name, case_dir in cases:
            with self.subTest(adapter=name, case=case_dir.name):
                request, response, expected = load_fixture(case_dir)
                adapter = get_adapter(name)
                transport = _support.FakeTransport(body=response.body, status=response.status)
                with patch("adapters.base.now_ms", return_value=STAMP):
                    snapshot = adapter.probe(request["target"], transport)
                hits = adapter.match(snapshot, request.get("rule") or {}, task_id="task1")

                self.assertEqual(len(transport.requests), 1)
                self.assertEqual(len(hits), len(expected["hits"]))
                for hit, want in zip(hits, expected["hits"], strict=False):
                    for key in ("target_id", "session", "price_tier", "remaining", "price"):
                        self.assertEqual(getattr(hit, key), want[key], key)
                    self.assertEqual(hit.task_id, "task1")
                    self.assertEqual(
                        hit.fingerprint,
                        fingerprint(name, hit.target_id, "2026-12-01", hit.session, hit.price_tier),
                    )

    def test_unknown_adapter_rejected(self):
        with self.assertRaises(KeyError):
            get_adapter("nope")

    def test_monitor_adapters_notify_once_across_restart(self):
        workdir = Path(_support.temp_dir())
        try:
            for name in ("railway", "damai", "bilibili", "maoyan", "medical", "gov"):
                with self.subTest(adapter=name):
                    db_path = workdir / "{}.db".format(name)
                    db = Store(db_path)
                    db.add_task(_support.make_task(adapter=name, id=name))
                    request, response, _ = load_fixture(FIXTURES / name / "basic")
                    adapter = get_adapter(name)
                    snapshot = adapter.probe(
                        request["target"],
                        _support.FakeTransport(body=response.body, status=response.status),
                    )
                    hits = adapter.match(snapshot, request.get("rule") or {}, task_id=name)
                    notifier = _support.FakeNotifier()
                    for _ in range(100):
                        for hit in hits:
                            db.upsert_hit(
                                name, hit.fingerprint, snapshot.fetched_at, snapshot.digest
                            )
                            deliver_once(db, notifier, name, hit.fingerprint, "命中提醒")
                    self.assertEqual(len(notifier.calls), len(hits))

                    db.close()
                    db = Store(db_path)
                    for hit in hits:
                        self.assertFalse(
                            deliver_once(db, notifier, name, hit.fingerprint, "命中提醒")
                        )
                    self.assertEqual(len(notifier.calls), len(hits))
                    db.close()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def test_login_state_requires_context(self):
        for name in ADAPTERS:
            adapter = get_adapter(name)
            if not adapter.REQUIRES_LOGIN:
                self.assertEqual(adapter.login_state({}), "ok")
                continue
            self.assertEqual(adapter.login_state({"logged_in": True}), "ok")
            self.assertEqual(adapter.login_state({}), "unknown")

    def test_http_error_mapping(self):
        adapter = get_adapter("railway")
        from adapters import AuthExpired, PlatformChanged, RateLimited, TransportError

        for status, error in (
            (401, AuthExpired),
            (429, RateLimited),
            (500, TransportError),
            (404, PlatformChanged),
        ):
            transport = _support.FakeTransport(status=status, body="{}")
            with self.assertRaises(error):
                adapter.probe({"target_id": "G1", "url": "https://example.invalid"}, transport)


if __name__ == "__main__":
    unittest.main()
