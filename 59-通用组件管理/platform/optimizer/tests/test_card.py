"""评分卡结构校验测试（离线）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from optimizer import (  # noqa: E402
    loaders,
    rules,
)
from optimizer.cli import _check_card  # noqa: E402


class ScorecardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.card = loaders.load_scorecard()

    def test_version_matches_changelog(self) -> None:
        changelog = self.card.get("changelog") or []
        self.assertTrue(changelog)
        self.assertEqual(changelog[-1]["version"], self.card["version"])

    def test_card_is_structurally_valid(self) -> None:
        self.assertEqual(_check_card(self.card), [])

    def test_rule_ids_unique(self) -> None:
        ids = [rule["id"] for rule in self.card["rules"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_check_types_supported(self) -> None:
        for rule in self.card["rules"]:
            check_type = rule["check"]["type"]
            self.assertIn(check_type, rules.SUPPORTED_CHECKS, rule["id"])

    def test_five_dimensions_weighted(self) -> None:
        dimensions = self.card["dimensions"]
        self.assertEqual(len(dimensions), 5)
        self.assertEqual(sum(item["weight"] for item in dimensions.values()), 100)


if __name__ == "__main__":
    unittest.main()
