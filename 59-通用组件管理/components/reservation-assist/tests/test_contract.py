"""组件契约：版本一致、golden 合 profile、docs/入口齐全、DC-2 登记存在。"""

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

    def test_required_fields(self):
        manifest = load_manifest()
        for key in (
            "name",
            "version",
            "family",
            "lifecycle",
            "entrypoints",
            "kernel_deps",
            "output_contract",
            "tests",
        ):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["family"], "reservation-assist")
        self.assertEqual(manifest["output_contract"], "reservation.v1")
        self.assertEqual(manifest["kernel_deps"], [])

    def test_entrypoints_exist(self):
        manifest = load_manifest()
        for entry in manifest["entrypoints"]:
            self.assertTrue((SKILL_DIR / entry).is_file(), entry)

    def test_docs_exist(self):
        for doc in load_manifest().get("docs") or []:
            self.assertTrue((COMPONENT_ROOT / doc).is_file(), doc)

    def test_golden_matches_reservation_profile(self):
        manifest = load_manifest()
        contract = json.loads(
            (MODULE_ROOT / "contracts" / "output.schema.json").read_text(encoding="utf-8")
        )
        profile = contract["profiles"][manifest["output_contract"]]
        samples = sorted((COMPONENT_ROOT / "tests" / "golden").glob("*.json"))
        self.assertTrue(samples, "缺少 golden 样本")

        try:
            from jsonschema import validate
        except ImportError:  # pragma: no cover
            for sample in samples:
                payload = json.loads(sample.read_text(encoding="utf-8"))
                missing = [key for key in profile["required"] if key not in payload]
                self.assertFalse(missing, "{} 缺少 {}".format(sample.name, missing))
            return

        for sample in samples:
            payload = json.loads(sample.read_text(encoding="utf-8"))
            validate(instance=payload, schema=profile)

    def test_component_schema_accepts_family(self):
        schema = json.loads(
            (MODULE_ROOT / "contracts" / "component.schema.json").read_text(encoding="utf-8")
        )
        self.assertIn("reservation-assist", schema["properties"]["family"]["enum"])
        self.assertRegex("reservation.v1", schema["properties"]["output_contract"]["pattern"])

    def test_data_sources_dc2_registered(self):
        ledger = yaml.safe_load(
            (MODULE_ROOT / "contracts" / "data-sources.yaml").read_text(encoding="utf-8")
        )
        by_id = {item["id"]: item for item in ledger["sources"]}
        for source in (
            "railway_12306",
            "damai",
            "bilibili_mall",
            "maoyan",
            "hospital_h5",
            "gov_portal",
        ):
            self.assertIn(source, by_id)
            entry = by_id[source]
            self.assertEqual(entry["status"], "active")
            self.assertEqual(entry["commercial_use"], "exception")
            self.assertEqual(entry["exception"]["id"], "DC-2")
            self.assertIn("reservation-assist", entry["used_by"])


if __name__ == "__main__":
    unittest.main()
