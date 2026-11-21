"""SkillSet 打包与供应链校验的回归测试（P2-2）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import skillset  # noqa: E402
import supply_chain  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class SkillsetTest(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        _write(
            root / "skillsets" / "demo.yaml",
            "skillset: demo\ndisplay_name: 演示\nproducts:\n  - alpha\n  - beta\n",
        )
        _write(root / "products" / "alpha.yaml", "product: alpha\ncomponent: components/alpha\n")
        _write(root / "products" / "beta.yaml", "product: beta\ncomponent: components/beta\n")
        _write(root / "components" / "alpha" / "component.yaml", "name: alpha\nlifecycle: active\n")
        _write(root / "components" / "beta" / "component.yaml", "name: beta\nlifecycle: active\n")
        _write(root / "dist" / "alpha" / "free" / "SKILL.md", "# alpha\n")
        _write(root / "dist" / "beta" / "free" / "SKILL.md", "# beta\n")

    def test_check_passes_for_valid_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            results = skillset.check(root / "skillsets", root / "products")
            self.assertTrue(results["demo"]["ok"])

    def test_check_rejects_unknown_product_and_name_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            _write(root / "skillsets" / "demo.yaml", "skillset: other\nproducts:\n  - ghost\n")
            results = skillset.check(root / "skillsets", root / "products")
            joined = "；".join(results["demo"]["errors"])
            self.assertIn("文件名一致", joined)
            self.assertIn("商品不存在", joined)

    def test_build_pack_writes_manifest_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            out = root / "dist" / "packs" / "demo.zip"
            result = skillset.build_pack(
                "demo",
                out,
                root / "skillsets",
                root / "dist",
                root / "products",
            )
            self.assertFalse(result["dry_run"])
            with zipfile.ZipFile(out) as archive:
                names = archive.namelist()
            self.assertIn("pack.json", names)
            self.assertIn("alpha/free/SKILL.md", names)
            self.assertIn("beta/free/SKILL.md", names)

    def test_build_pack_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            out = root / "dist" / "packs" / "demo.zip"
            skillset.build_pack(
                "demo", out, root / "skillsets", root / "dist", root / "products", dry_run=True
            )
            self.assertFalse(out.exists())

    def test_build_pack_requires_built_dist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._tree(root)
            (root / "dist" / "beta").rename(root / "dist" / "beta_missing")
            with self.assertRaises(ValueError):
                skillset.build_pack(
                    "demo",
                    root / "dist" / "packs" / "demo.zip",
                    root / "skillsets",
                    root / "dist",
                    root / "products",
                )


class SupplyChainTest(unittest.TestCase):
    def _build_tree(self, root: Path, version: str = "1.0.0") -> None:
        _write(
            root / "products" / "demo.yaml",
            "product: demo\ncomponent: components/demo\nvariants:\n  free:\n"
            "    entrypoints: [scripts/run.py]\n",
        )
        _write(root / "components" / "demo" / "component.yaml", "version: {}\n".format(version))
        _write(root / "kernel" / "headers.py", "X = 1\n")
        built = root / "dist" / "demo" / "free"
        _write(built / "SKILL.md", "# demo\n")
        _write(built / "scripts" / "run.py", "print(1)\n")
        manifest = {
            "product": "demo",
            "variant": "free",
            "component": "components/demo",
            "component_version": version,
            "skill_sha256": supply_chain.sha256(built / "SKILL.md"),
            "kernel": {"headers": supply_chain.sha256(root / "kernel" / "headers.py")},
        }
        _write(
            root / "dist" / "demo" / "free.manifest.json",
            json.dumps(manifest),
        )

    def test_check_is_skip_when_dist_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "products" / "demo.yaml", "product: demo\nvariants: {}\n")
            results = supply_chain.check(root / "products", root / "dist")
            self.assertEqual(results["demo"]["status"], "skip")

    def test_check_detects_consistent_and_stale_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._build_tree(root)
            with (
                mock.patch.object(supply_chain, "ROOT", root),
                mock.patch.object(supply_chain, "KERNEL", root / "kernel"),
            ):
                results = supply_chain.check(root / "products", root / "dist")
                self.assertEqual(results["demo"]["status"], "ok")

                _write(root / "components" / "demo" / "component.yaml", "version: 1.0.1\n")
                results = supply_chain.check(root / "products", root / "dist")
                self.assertEqual(results["demo"]["status"], "fail")
                self.assertIn("版本漂移", results["demo"]["errors"][0])

    def test_check_detects_kernel_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._build_tree(root)
            _write(root / "kernel" / "headers.py", "X = 2\n")
            with (
                mock.patch.object(supply_chain, "ROOT", root),
                mock.patch.object(supply_chain, "KERNEL", root / "kernel"),
            ):
                results = supply_chain.check(root / "products", root / "dist")
                self.assertEqual(results["demo"]["status"], "fail")
                self.assertIn("kernel/headers.py", results["demo"]["errors"][0])

    def test_classify_verify_branches(self):
        self.assertEqual(supply_chain.classify_verify(0, '{"ok": true}')["status"], "ok")
        self.assertEqual(supply_chain.classify_verify(1, "401 not logged in")["status"], "skip")
        self.assertEqual(supply_chain.classify_verify(1, "boom")["status"], "fail")
        self.assertEqual(supply_chain.classify_verify(0, '{"ok": false}')["status"], "fail")

    def test_verify_offline_is_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "products" / "demo.yaml", "product: demo\nvariants: {}\n")
            results = supply_chain.verify(online=False, products=root / "products")
            self.assertEqual(results["demo"]["status"], "skip")


if __name__ == "__main__":
    unittest.main()
