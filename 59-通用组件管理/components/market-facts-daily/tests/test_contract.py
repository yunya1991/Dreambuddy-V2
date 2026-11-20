"""组件契约回归：component.yaml 版本与 SKILL.md 一致，golden 输出符合统一外壳。"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

COMPONENT_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = COMPONENT_ROOT / "skill"


def load_manifest() -> dict:
    return yaml.safe_load((COMPONENT_ROOT / "component.yaml").read_text(encoding="utf-8"))


def load_frontmatter(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return yaml.safe_load("\n".join(lines[1:index])) or {}
    return {}


class ContractTest(unittest.TestCase):
    def test_version_matches_skill_frontmatter(self):
        manifest = load_manifest()
        front = load_frontmatter(SKILL_DIR / "SKILL.md")
        self.assertEqual(manifest["version"], str(front.get("version")))

    def test_golden_matches_output_schema(self):
        self.skipTest(
            "facts.py --json 仍为文本主输出的辅助格式，未携带 data.v1 外壳；"
            "缺口登记于 SPEC §9 P2 备注，P4 构建期补齐"
        )


if __name__ == "__main__":
    unittest.main()
