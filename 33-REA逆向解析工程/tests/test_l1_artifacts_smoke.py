"""T4 消费侧 smoke（SPEC-54-统计图表化能力 L1S-05 / ADR-V12）。

验证 `thought_tree.load_l1_visual_artifacts` 能只读加载 L1 制品并回显
capability 列表；制品缺失/不可读时 FAIL-OPEN 返回空列表，不抛异常。
"""

import tempfile
import unittest

from core.reflection.thought_tree import load_l1_visual_artifacts


class TestL1ArtifactsConsumption(unittest.TestCase):
    def test_returns_capability_list_from_artifact_root(self):
        # 54 侧 `persist_visuals` 的产物结构（只读，本层不重算）
        with tempfile.TemporaryDirectory() as root:
            import json
            import os

            for capability, as_of, n_visuals in (
                ("D-E15", "2026-11-11", 1),
                ("D-E15", "2026-11-12", 2),
                ("T3", "2026-11-11", 2),
            ):
                folder = os.path.join(root, capability)
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, f"{as_of}.json"), "w", encoding="utf-8") as fh:
                    json.dump(
                        {"capability": capability, "as_of": as_of, "n_visuals": n_visuals}, fh
                    )

            view = load_l1_visual_artifacts(root=root)
            self.assertTrue(view["ok"])
            self.assertEqual(view["capabilities"], ["D-E15", "T3"])
            self.assertEqual(view["as_of"], "2026-11-12")
            self.assertEqual([item["n_visuals"] for item in view["items"]], [2, 2])

    def test_missing_root_falls_back_to_empty_state(self):
        with tempfile.TemporaryDirectory() as root:
            view = load_l1_visual_artifacts(root=root)
            self.assertTrue(view["ok"])
            self.assertEqual(view["capabilities"], [])
            self.assertIsNone(view["as_of"])


if __name__ == "__main__":
    unittest.main()
