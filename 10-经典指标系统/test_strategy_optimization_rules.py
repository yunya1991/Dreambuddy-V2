import unittest
from pathlib import Path


class TestStrategyOptimizationRules(unittest.TestCase):
    def test_regime_hybrid_has_short_vote_relax_and_counter_short(self) -> None:
        p = Path(__file__).resolve().parent / "user_data" / "strategies" / "RegimeHybridStrategy.py"
        src = p.read_text(encoding="utf-8")
        self.assertIn("entry_votes_req_short", src)
        self.assertIn("range_counter_short", src)
        self.assertIn("risk_off_short_bucket", src)
        self.assertIn("risk_off_score_short", src)
        self.assertIn("risk_off_short_threshold", src)
        self.assertIn("short_min_rr", src)
        self.assertIn("short_max_hold_hours", src)

    def test_breakout_has_dynamic_vote_threshold(self) -> None:
        p = Path(__file__).resolve().parent / "user_data" / "strategies" / "breakoutStrategy.py"
        src = p.read_text(encoding="utf-8")
        self.assertIn("min_votes_long", src)
        self.assertIn("min_votes_short", src)
        self.assertIn("cooldown_long_bars", src)
        self.assertIn("breakout_quality_long", src)


if __name__ == "__main__":
    unittest.main()
