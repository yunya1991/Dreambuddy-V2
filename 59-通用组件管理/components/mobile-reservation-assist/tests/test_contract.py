"""契约测试：component.yaml 与 SKILL.md 版本一致、枚举合法、入口存在、golden 合规。"""

from __future__ import annotations

import json
import unittest

import yaml

from _support import COMPONENT

REQUIRED_GOLDEN = [
    "schema_version",
    "command",
    "generated_at",
    "tasks",
    "hits",
    "events",
    "limits",
]


def _frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    body = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    return yaml.safe_load("\n".join(body)) or {}


class ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = yaml.safe_load((COMPONENT / "component.yaml").read_text(encoding="utf-8"))
        self.front = _frontmatter((COMPONENT / "skill" / "SKILL.md").read_text(encoding="utf-8"))

    def test_version_matches_skill_md(self) -> None:
        self.assertEqual(self.manifest["version"], self.front["version"])

    def test_name_matches_dir(self) -> None:
        self.assertEqual(self.manifest["name"], COMPONENT.name)

    def test_enum_fields(self) -> None:
        self.assertEqual(self.manifest["family"], "reservation-assist")
        self.assertEqual(self.manifest["output_contract"], "reservation.v1")

    def test_entrypoints_exist(self) -> None:
        for entry in self.manifest["entrypoints"]:
            self.assertTrue((COMPONENT / "skill" / entry).is_file(), entry)

    def test_golden_valid(self) -> None:
        golden = json.loads((COMPONENT / "tests" / "golden" / "report.json").read_text(encoding="utf-8"))
        for key in REQUIRED_GOLDEN:
            self.assertIn(key, golden)
        self.assertGreaterEqual(len(golden["limits"]), 1)


if __name__ == "__main__":
    unittest.main()
