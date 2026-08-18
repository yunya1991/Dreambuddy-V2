import unittest
from pathlib import Path
import subprocess
import json


class TestP2LifecycleIntegration(unittest.TestCase):
    def test_run_sh_has_artifact_cleanup_hook(self) -> None:
        root = Path(__file__).resolve().parent.parent
        content = (root / "ops" / "nanoclaw" / "core_task1" / "run.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/artifact_lifecycle.py cleanup", content)

    def test_launchd_stack_has_artifact_cleanup_hook(self) -> None:
        root = Path(__file__).resolve().parent.parent
        content = (root / "ops" / "launchd" / "fundamental_stack.sh").read_text(encoding="utf-8")
        self.assertIn("artifact_lifecycle.py", content)
        self.assertIn(" cleanup ", content)

    def test_bridge_outputs_macro_pressure_and_source_coverage(self) -> None:
        root = Path(__file__).resolve().parent.parent
        bridge = root / "ops" / "nanoclaw" / "core_task1" / "scripts" / "multi_agent_bridge.mjs"
        script = f"""
process.env.MULTI_AGENT_BRIDGE_NO_MAIN = '1';
const m = await import('{bridge.as_uri()}');
const out = m.buildFundamentalPlaceholder({{
  asset: 'BTC',
  narrativeRegistry: {{ contract: {{ quality: {{ coverage: 0.2 }} }} }},
  flowRegime: {{ quality: {{ coverage: 0.3 }}, composite: 0.9 }},
  macroPressure: 0.1,
  macroPressureQuality: 'ok'
}});
console.log(JSON.stringify(out));
"""
        cp = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
        out = json.loads((cp.stdout or "").strip())
        self.assertIn("macroPressure", out)
        self.assertIn("sourceCoverage", out)
        self.assertEqual(str(out.get("fundamentalSignal") or ""), "neutral")


if __name__ == "__main__":
    unittest.main()
