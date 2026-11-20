"""组件契约回归：component.yaml 版本与 SKILL.md 一致，golden 输出符合统一外壳。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

COMPONENT_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = COMPONENT_ROOT.parents[1]
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
        manifest = load_manifest()
        contract = json.loads(
            (MODULE_ROOT / "contracts" / "output.schema.json").read_text(encoding="utf-8")
        )
        profile = contract["profiles"][manifest["output_contract"]]
        samples = sorted((COMPONENT_ROOT / "tests" / "golden").glob("*.json"))
        self.assertTrue(samples, "缺少 golden 样本")

        try:
            from jsonschema import validate
        except ImportError:  # pragma: no cover - 环境缺依赖时降级为必填字段检查
            for sample in samples:
                payload = json.loads(sample.read_text(encoding="utf-8"))
                missing = [key for key in profile.get("required", []) if key not in payload]
                self.assertFalse(missing, "{} 缺少 {}".format(sample.name, missing))
            return

        for sample in samples:
            payload = json.loads(sample.read_text(encoding="utf-8"))
            validate(instance=payload, schema=profile)


if __name__ == "__main__":
    unittest.main()
