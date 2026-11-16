"""GAP-21 loader 接线实测（真实 Cordis）

验证 dsh_probe_plugin.mjs 作为 Cordis 插件挂载后：
  - 插件 `ctx.on` 被归属到 `ctx.name`，并出现在 snapshot.subscription
  - probe.complete=true（订阅采集已开启）
  - root dispose 后订阅自动注销，无需手动清理
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
    require_complete,
)

PROBE = BASE / "dreamos" / "probes" / "side_effect_probe.mjs"
PLUGIN = BASE / "dreamos" / "probes" / "dsh_probe_plugin.mjs"
NODE = shutil.which("node")


def _cordis_index() -> Path | None:
    dsh = shutil.which("dsh")
    if not dsh or not NODE:
        return None
    current = Path(dsh).resolve()
    for _ in range(4):
        current = current.parent
        if (current / "package.json").exists():
            candidate = current / "node_modules" / "@deepseek-ai" / "cordis" / "lib" / "index.js"
            if candidate.exists():
                return candidate
    return None


CORDIS = _cordis_index()

pytestmark = pytest.mark.skipif(CORDIS is None or not NODE, reason="node 或 cordis 不可用")


def _run() -> dict:
    script = f"""
import {{ Context }} from '{CORDIS.as_uri()}';
import {{ apply }} from '{PLUGIN.as_uri()}';
import {{ snapshot, reset }} from '{PROBE.as_uri()}';

reset();
const root = new Context();
await root.plugin({{ name: 'dreambuddy-side-effect-probe', apply }});
const fiber = await root.plugin({{
  name: 'p-new',
  apply: (ctx) => {{ ctx.on('agent/pre-step', () => {{}}); }},
}});
const active = snapshot('2026-11-17T10:00:00.000Z');
await fiber.dispose();
await root.fiber.dispose();
const cleaned = snapshot('2026-11-17T10:00:01.000Z');
console.log(JSON.stringify({{ active, cleaned }}));
"""
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_cordis_plugin_captures_and_releases_subscriptions():
    data = _run()
    active = data["active"]

    require_complete(active)
    assert active["effects"]["subscription"] == [
        {"id": "sub:p-new:agent/pre-step", "owner": "p-new"}
    ]
    assert active["plugins"] == ["p-new"]

    assert data["cleaned"]["effects"]["subscription"] == []
