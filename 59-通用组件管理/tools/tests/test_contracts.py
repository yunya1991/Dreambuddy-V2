"""check_contracts / sync_mobile 的回归测试。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import check_contracts  # noqa: E402
import sync_mobile  # noqa: E402


class ContractTest(unittest.TestCase):
    def _make_component(self, root: Path, args: str) -> Path:
        component = root / "demo"
        scripts = component / "skill" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "demo.py").write_text(
            "import argparse\n"
            "p = argparse.ArgumentParser()\n"
            "sub = p.add_subparsers()\n"
            "run = sub.add_parser('run', aliases=['go'])\n"
            "run.add_argument('--limit')\n",
            encoding="utf-8",
        )
        (component / "component.yaml").write_text(
            "name: demo\nversion: 1.0.0\nentrypoints: [scripts/demo.py]\n"
            "actions:\n"
            "  - name: run\n"
            "    script: scripts/demo.py\n"
            "    args: [{}]\n"
            "    safety: read\n"
            "    params:\n"
            "      - {{name: limit, flag: '--limit'}}\n".format(args),
            encoding="utf-8",
        )
        return component

    def test_accepts_alias_and_skill_relative_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            component = self._make_component(Path(tmp), "go")
            self.assertEqual(check_contracts.check_component(component), [])

    def test_rejects_missing_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            component = self._make_component(Path(tmp), "show")
            errors = check_contracts.check_component(component)
            self.assertTrue(any("show" in item for item in errors), errors)


class SyncMobileTest(unittest.TestCase):
    def test_check_skips_when_source_missing(self) -> None:
        old = os.environ.get("SHUNFENGCHE_REPO")
        os.environ["SHUNFENGCHE_REPO"] = "/nonexistent/顺风车业务"
        try:
            self.assertEqual(sync_mobile.check(), 0)
        finally:
            if old is None:
                os.environ.pop("SHUNFENGCHE_REPO", None)
            else:
                os.environ["SHUNFENGCHE_REPO"] = old


if __name__ == "__main__":
    unittest.main()
