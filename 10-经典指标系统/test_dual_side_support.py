import unittest
from pathlib import Path


class TestDualSideSupport(unittest.TestCase):
    def test_regime_hybrid_dual_side(self) -> None:
        p = Path(__file__).resolve().parent / "user_data" / "strategies" / "RegimeHybridStrategy.py"
        src = p.read_text(encoding="utf-8")
        self.assertIn("can_short: bool = True", src)
        self.assertIn("enter_short", src)
        self.assertIn("exit_short", src)

    def test_multi_group_dual_side(self) -> None:
        p = Path(__file__).resolve().parent / "user_data" / "strategies" / "MultiGroupStrategy.py"
        src = p.read_text(encoding="utf-8")
        self.assertIn("can_short: bool = True", src)
        self.assertIn("enter_short", src)
        self.assertIn("exit_short", src)


if __name__ == "__main__":
    unittest.main()
