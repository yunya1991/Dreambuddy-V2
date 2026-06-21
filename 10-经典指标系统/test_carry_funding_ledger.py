import unittest

import ml_trade_service as svc


class TestCarryFundingLedger(unittest.TestCase):
    def setUp(self) -> None:
        svc.CONFIG["dry_run"] = True
        svc.TRACKER_STATE["carry_funding_ledger"] = []
        svc.TRACKER_STATE["carry_funding_ledger_seen"] = {}

    def _pnl_with_one_leg(self, coin: str = "BTC"):
        return {
            "ok": True,
            "details": {
                "positions": [
                    {
                        "coin": coin,
                        "side": "short",
                        "notional_usdc": 100.0,
                        "funding_rate": 0.0001,
                        "funding_pnl_next_usdc": 0.01,
                    }
                ]
            },
        }

    def test_tick_skips_when_not_in_funding_grace(self) -> None:
        clk = {
            "venue": "hyperliquid",
            "last_ts": 1_000,
            "next_ts": 2_000,
            "base_ts": 2_000,
        }
        svc._carry_funding_ledger_tick(1_500, clk, self._pnl_with_one_leg("BTC"))
        self.assertEqual(len(svc.TRACKER_STATE.get("carry_funding_ledger") or []), 0)
        self.assertEqual(len(svc.TRACKER_STATE.get("carry_funding_ledger_seen") or {}), 0)

    def test_tick_appends_once_per_venue_coin_funding_ts(self) -> None:
        clk = {
            "venue": "hyperliquid",
            "last_ts": 1_000,
            "next_ts": 2_000,
            "base_ts": 1_000,
        }
        pnl = self._pnl_with_one_leg("BTC")
        svc._carry_funding_ledger_tick(1_010, clk, pnl)
        svc._carry_funding_ledger_tick(1_020, clk, pnl)

        led = svc.TRACKER_STATE.get("carry_funding_ledger")
        seen = svc.TRACKER_STATE.get("carry_funding_ledger_seen")
        self.assertEqual(len(led or []), 1)
        self.assertEqual(len(seen or {}), 1)
        self.assertEqual((led or [])[0].get("funding_ts"), 1_000)
        self.assertEqual((led or [])[0].get("coin"), "BTC")


if __name__ == "__main__":
    unittest.main()
