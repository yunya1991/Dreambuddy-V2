"""GAP-21: Node 采集器实测（timer / handle / subscription）

用真实 node 子进程验证：
  - withOwner 内的 setInterval / fs.watch 被归属到插件
  - clearInterval / watcher.close 后副作用清零
  - 未开启订阅采集 → probe.complete=false
  - 开启并登记订阅 → complete=true，且能通过 Python 侧 require_complete
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.capability.side_effect_probe import (  # noqa: E402
    ProbeError,
    require_complete,
    validate_snapshot,
)

PROBE = BASE / "dreamos" / "probes" / "side_effect_probe.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(not NODE, reason="node 不可用")


def _run() -> dict:
    script = f"""
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {{ withOwner, snapshot, enableSubscriptionTracking, registerSubscription, reset }} from '{PROBE.as_uri()}';

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'probe-'));
const timer = withOwner('p-new', () => setInterval(() => {{}}, 1000));
const watcher = withOwner('p-new', () => fs.watch(dir));
const active = snapshot('2026-11-17T10:00:00.000Z');

clearInterval(timer);
watcher.close();
const cleaned = snapshot('2026-11-17T10:00:01.000Z');

reset();
enableSubscriptionTracking();
registerSubscription('p-new', 'sub:p-new:agent/pre-step');
const complete = snapshot('2026-11-17T10:00:02.000Z');

fs.rmSync(dir, {{ recursive: true, force: true }});
console.log(JSON.stringify({{ active, cleaned, complete }}));
"""
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_node_probe_tracks_and_clears_effects():
    data = _run()
    active = data["active"]
    validate_snapshot(active)

    assert active["probe"]["complete"] is False
    assert active["probe"]["unavailable"] == ["subscription"]
    assert [(e["owner"]) for e in active["effects"]["timer"]] == ["p-new"]
    assert [(e["owner"]) for e in active["effects"]["handle"]] == ["p-new"]

    cleaned = data["cleaned"]
    assert all(not cleaned["effects"][cls] for cls in cleaned["effects"])


def test_node_probe_complete_requires_subscription_tracking():
    data = _run()
    complete = data["complete"]

    require_complete(complete)
    assert complete["effects"]["subscription"] == [
        {"id": "sub:p-new:agent/pre-step", "owner": "p-new"}
    ]

    with pytest.raises(ProbeError):
        require_complete(data["active"])
