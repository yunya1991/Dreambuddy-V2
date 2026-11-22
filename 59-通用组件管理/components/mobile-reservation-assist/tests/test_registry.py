"""能力索引消费端：加载、查找、命令翻译、安全级复核。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401 - 注册 scripts 到 sys.path

import registry

INDEX = {
    "schema": "dreambuddy.capabilities.v2",
    "generated_at": "2026-11-22T10:00:00+08:00",
    "capabilities": [
        {
            "id": "cogsteward.index",
            "kind": "run",
            "component": "cogsteward",
            "action": "index",
            "safety": "read",
            "args": [],
        },
        {
            "id": "cogsteward.scan",
            "kind": "run",
            "component": "cogsteward",
            "action": "scan",
            "safety": "write",
            "escalate": {},
            "args": [],
        },
        {
            "id": "mobile.jobs",
            "kind": "mobile",
            "component": "mobile-reservation-assist",
            "action": "jobs",
            "command": "jobs",
            "safety": "read",
            "args": ["jobs"],
        },
        {
            "id": "data.data_store_read",
            "kind": "data",
            "tool": "data_store_read",
            "safety": "read",
            "schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer"},
                },
            },
        },
        {
            "id": "data.data_fetch",
            "kind": "data",
            "tool": "data_fetch",
            "safety": "read",
            "schema": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string"},
                    "params": {"type": "object"},
                },
                "required": ["scope"],
            },
        },
        {
            "id": "workflow.daily-market-brief",
            "kind": "workflow",
            "workflow": "daily-market-brief",
            "safety": "read",
        },
    ],
}


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "capabilities.json"
        self.path.write_text(json.dumps(INDEX, ensure_ascii=False), encoding="utf-8")
        self._old = os.environ.get("DREAMBUDDY_REGISTRY")
        os.environ["DREAMBUDDY_REGISTRY"] = str(self.path)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("DREAMBUDDY_REGISTRY", None)
        else:
            os.environ["DREAMBUDDY_REGISTRY"] = self._old
        self._tmp.cleanup()

    def test_load_and_find(self):
        index = registry.load()
        self.assertEqual(len(registry.capabilities(index)), 6)
        cap = registry.find("cogsteward.index", index)
        self.assertEqual(cap["component"], "cogsteward")
        self.assertIsNone(registry.find("nope.none", index))

    def test_missing_or_bad_schema_raises(self):
        os.environ["DREAMBUDDY_REGISTRY"] = str(Path(self._tmp.name) / "absent.json")
        with self.assertRaises(registry.RegistryError):
            registry.load()
        self.path.write_text('{"schema": "other.v1", "capabilities": []}', encoding="utf-8")
        with self.assertRaises(registry.RegistryError):
            registry.load()

    def test_plan_argv_run_and_workflow(self):
        index = registry.load()
        run = registry.plan_argv(Path("/tmp/cli.py"), registry.find("cogsteward.index", index), ["--json"])
        self.assertEqual(run[2:], ["run", "cogsteward", "index", "--json"])
        gated = registry.plan_argv(
            Path("/tmp/cli.py"),
            registry.find("cogsteward.scan", index),
            ["--root", "/tmp"],
            allow_write=True,
        )
        self.assertEqual(gated[-1], "--allow-write")
        flow = registry.plan_argv(Path("/tmp/cli.py"), registry.find("workflow.daily-market-brief", index))
        self.assertEqual(flow[2:], ["workflow", "run", "daily-market-brief", "--dry-run"])
        data = registry.plan_argv(
            Path("/tmp/cli.py"),
            registry.find("data.data_store_read", index),
            ["--json", '{"table": "mm_metrics", "filters": {"sub_category": "macro", "metric_name": "DGS10"}, "limit": 5}'],
        )
        self.assertEqual(
            data[2:],
            [
                "dal",
                "read",
                "--table",
                "mm_metrics",
                "--sub-category",
                "macro",
                "--metric-name",
                "DGS10",
                "--limit",
                "5",
            ],
        )
        fetch = registry.plan_argv(
            Path("/tmp/cli.py"),
            registry.find("data.data_fetch", index),
            ["scope=market", 'params={"symbol": "BTC"}'],
        )
        self.assertEqual(
            fetch[2:], ["dal", "fetch", "--scope", "market", "--params", '{"symbol": "BTC"}']
        )
        mobile = registry.plan_argv(Path("/tmp/cli.py"), registry.find("mobile.jobs", index))
        self.assertIsNone(mobile)

    def test_data_requires_scope(self):
        index = registry.load()
        with self.assertRaises(ValueError):
            registry.plan_argv(
                Path("/tmp/cli.py"), registry.find("data.data_fetch", index), ["--json", "{}"]
            )

    def test_local_and_effective_safety(self):
        index = registry.load()
        self.assertTrue(registry.is_local(registry.find("mobile.jobs", index)))
        self.assertFalse(registry.is_local(registry.find("cogsteward.index", index)))
        escalated = {"safety": "read", "escalate": {"--execute": "write"}}
        self.assertEqual(registry.effective_safety(escalated, []), "read")
        self.assertEqual(registry.effective_safety(escalated, ["--execute"]), "write")

    def test_cli_path_env_wins(self):
        old = os.environ.get("DREAMBUDDY_CLI")
        os.environ["DREAMBUDDY_CLI"] = "/tmp/dreambuddy.py"
        try:
            self.assertEqual(str(registry.cli_path()), "/tmp/dreambuddy.py")
        finally:
            if old is None:
                os.environ.pop("DREAMBUDDY_CLI", None)
            else:
                os.environ["DREAMBUDDY_CLI"] = old


if __name__ == "__main__":
    unittest.main()
