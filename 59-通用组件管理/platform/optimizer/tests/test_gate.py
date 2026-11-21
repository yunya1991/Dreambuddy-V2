"""门禁、建议与 A/B 测试（离线）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PLATFORM_DIR = Path(__file__).resolve().parents[2]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from optimizer import ab as ab_mod  # noqa: E402
from optimizer import advise as advise_mod  # noqa: E402
from optimizer import gate as gate_mod  # noqa: E402
from optimizer import loaders  # noqa: E402
from optimizer import score as score_mod  # noqa: E402
from optimizer.tests.test_score import _bad_skill, _good_skill  # noqa: E402


class GateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.card = loaders.load_scorecard()
        self.payload = score_mod.score_all([_good_skill(), _bad_skill()], self.card, "legacy")

    def test_blocker_blocks_release(self) -> None:
        blocked = gate_mod.blocking_findings(self.payload, self.card, "legacy")
        self.assertTrue(blocked)
        self.assertEqual(gate_mod.exit_code(blocked), 1)

    def test_clean_payload_passes(self) -> None:
        payload = score_mod.score_all([_good_skill()], self.card, "legacy")
        blocked = gate_mod.blocking_findings(payload, self.card, "legacy")
        self.assertEqual(blocked, [])
        self.assertEqual(gate_mod.exit_code(blocked), 0)

    def test_render_text_mentions_profile(self) -> None:
        blocked = gate_mod.blocking_findings(self.payload, self.card, "legacy")
        text = gate_mod.render_text(blocked, self.payload, "legacy")
        self.assertIn("profile=legacy", text)


class AdviseTest(unittest.TestCase):
    def test_advise_sorted_with_blocker_first(self) -> None:
        card = loaders.load_scorecard()
        payload = score_mod.score_all([_bad_skill()], card, "legacy")
        items = advise_mod.advise(payload, "info")
        self.assertTrue(items)
        self.assertEqual(items[0]["severity"], "blocker")
        self.assertTrue(items[0]["advice"])
        self.assertIn("建议清单", advise_mod.render_text(items))


class AbTest(unittest.TestCase):
    def test_dry_run_reuses_bench_fixtures(self) -> None:
        result = ab_mod.run_ab(dry_run=True)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["verdict"], "fixtures-ok")


if __name__ == "__main__":
    unittest.main()
