import unittest

from pathlib import Path


class TestBreakoutShortSupport(unittest.TestCase):
    def test_breakout_strategy_enables_short(self) -> None:
        p = Path(__file__).resolve().parent / "user_data" / "strategies" / "breakoutStrategy.py"
        src = p.read_text(encoding="utf-8")
        self.assertIn("can_short = True", src)


if __name__ == "__main__":
    unittest.main()
