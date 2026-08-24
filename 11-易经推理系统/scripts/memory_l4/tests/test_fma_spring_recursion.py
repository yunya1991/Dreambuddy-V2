"""Recursion regression tests for _calc_5ma_spring_force + US index trend check.

Bug context (2026-08-21):
  _calc_5ma_spring_force() computes F_dot by calling itself on closes[1:].
  For US index 5y daily data (~1254 bars), this cascades into 1054 levels of
  recursion, which exceeds the CPython default recursionlimit=1000 and raises
  RecursionError. The error is swallowed by _check_us_index_trend()'s blanket
  `except Exception` and returned as "美股大盘检查异常: maximum recursion depth
  exceeded", so all US_STOCK_COINS (COIN/SKHYNIX/CRCL/SPCX/HYPE/...) get
  wrongfully intercepted at P1 short filter.

  The fix must keep recursion depth O(1) - i.e. at most ONE recursive call per
  top-level invocation (a single step-lookback, no cascading).
"""

import sys
import unittest

# ---- helpers --------------------------------------------------------------

_MINI_CONSTANTS = dict(
    FMA_SLOPE_WINDOW=20,
    FMA_SLOPE_ALPHA=0.2,
    FMA_GROUP_WEIGHT_SHORT=0.35,
    FMA_GROUP_WEIGHT_MID=0.40,
    FMA_GROUP_WEIGHT_LONG=0.25,
    FMA_INTER_K_RATIO=0.5,
    FMA_LONG_TERM_BOTTOM_BUFFER=0.02,
    FMA_SHORT_TIER_BREAKDOWN_BARS=3,
)


def _make_instance():
    """Create a PollingTrader (OKX mocked) so real binding/staticmethod dispatch works.

    Uses full __init__ with mocked balance so all attributes are wired correctly.
    """
    from unittest.mock import patch
    from scripts.memory_l4.polling_trader import PollingTrader

    with patch("scripts.memory_l4.okx_simulated.OKXSimulatedClient") as mc:
        mc.return_value.get_balance.return_value = {"ok": True, "total_eq": 1000.0}
        return PollingTrader(
            interval=300,
            coins=["BTC"],
            bar="1H",
            confidence_threshold=0.5,
            short_confidence_threshold=0.8,
            max_positions=5,
            initial_equity=1000.0,
            daily_loss_limit=-30.0,
            max_consecutive_losses=999,
            default_position_pct=0.20,
            guardian=None,
            use_bcrm2=True,
        )


# ---- tests ---------------------------------------------------------------


class Calc5MaSpringForceRecursionTests(unittest.TestCase):
    # Lengths chosen to reproduce the on-stack failure: yfinance 5y ~1254 bars.
    LENGTH_NEAR_LIMIT = 1100   # still below limit?  with old bug it recurs ~900x
    LENGTH_OVER_LIMIT = 1500   # definitely triggers RecursionError (1054+ stack)

    @staticmethod
    def _closes(n: int) -> list:
        """Build a fake daily downtrend: 1500.0 -> (1500.0 - n*0.05) newest-first.

        Monotonic so MA calculations are stable and always well-defined.
        """
        base = 1500.0
        arr = [base - i * 0.05 for i in range(n)]  # oldest -> newest
        return arr[::-1]                           # newest -> oldest

    # -- RED tests (should fail BEFORE the fix) --------------------------------
    def test_daily_index_1500bars_no_recursion_error(self):
        """_calc_5ma_spring_force MUST NOT blow the stack on 5y index data."""
        inst = _make_instance()
        closes = self._closes(self.LENGTH_OVER_LIMIT)

        # Pin the system recursionlimit to the production default (lower is
        # fine for this synthetic test - we want the failure to be loud).
        prev = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(1000)
            # Should complete normally, NOT raise.
            res = inst._calc_5ma_spring_force(closes, tier="daily_index")
        finally:
            sys.setrecursionlimit(prev)

        self.assertIn("bearish_score", res)
        self.assertIn("F_total", res)
        # Monotonic downtrend -> at least WEAK/NORMAL expected
        self.assertIn(res.get("bearish_score"), {"WEAK", "NORMAL", "STRONG"})

    def test_daily_index_depth_is_at_most_2(self):
        """The call-graph depth MUST be <= 2 (top-level + one step lookback).

        Any deeper recursion is the cascading bug we are eliminating.
        """
        inst = _make_instance()
        closes = self._closes(self.LENGTH_NEAR_LIMIT)

        seen_depth = {"max": 0, "cur": 0}
        # PollingTrader stores the unbound fn in its class dict. Access via
        # type().__dict__ so we don't double-bind self on the recursive call.
        cls = type(inst)
        orig_raw = cls.__dict__["_calc_5ma_spring_force"]

        def _patched(self2, closes, k=2.0, tier="daily_index"):
            seen_depth["cur"] += 1
            seen_depth["max"] = max(seen_depth["max"], seen_depth["cur"])
            try:
                return orig_raw(self2, closes, k=k, tier=tier)
            finally:
                seen_depth["cur"] -= 1

        # Swap the method at class level (affects this single-instance class copy
        # only in CPython for user-created classes). Safer: swap the bound attr.
        import types
        inst._calc_5ma_spring_force = types.MethodType(_patched, inst)
        # Ensure recursion re-enters _patched by also shadowing through cls:
        cls._calc_5ma_spring_force = _patched

        res = inst._calc_5ma_spring_force(closes, tier="daily_index")
        self.assertIn(res.get("bearish_score"), {"WEAK", "NORMAL", "STRONG"})
        self.assertLessEqual(
            seen_depth["max"], 2,
            f"cascading recursion detected: max depth = {seen_depth['max']}",
        )

    def test_result_keys_unchanged(self):
        """Sanity: downstream consumers rely on these keys."""
        inst = _make_instance()
        closes = self._closes(300)
        res = inst._calc_5ma_spring_force(closes, tier="daily_self")
        for k in (
            "F_net", "F_total", "bearish_score", "bearish_n",
            "current_price", "ma_values", "valid_breakdown",
            "in_long_term_window",
        ):
            self.assertIn(k, res, f"missing downstream key {k}")

    def test_f_dot_calculated(self):
        """F_dot should be a float, non-zero on trending (monotonic) data."""
        inst = _make_instance()
        closes = self._closes(300)
        res = inst._calc_5ma_spring_force(closes, tier="daily_self")
        f_dot = res.get("F_dot", None)
        self.assertIsInstance(f_dot, float)
        # downtrend -> F_total is negative; stepping by 1 bar changes it slightly
        self.assertNotEqual(f_dot, 0.0)


if __name__ == "__main__":
    unittest.main()
