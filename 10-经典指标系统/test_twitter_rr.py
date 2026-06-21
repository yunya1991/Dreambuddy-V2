import unittest


import ml_trade_service as svc


class TestTwitterRR(unittest.TestCase):
    def setUp(self) -> None:
        svc.CONFIG["dry_run"] = True

    def test_rr_long_uses_entry(self) -> None:
        obj = {
            "coin": "BTC",
            "direction": "多",
            "entry": 100.0,
            "tp": 110.0,
            "sl": 95.0,
            "coin_signal": "",
            "macro_signal": "",
            "ai_confidence": 0.7,
        }
        text = svc._twitter_build_fixed_text(obj, lang="en")
        self.assertIn("R:R ~2.0:1", text)

    def test_rr_short_uses_mid_when_entry_missing(self) -> None:
        obj = {
            "coin": "BTC",
            "direction": "空",
            "mid": 100.0,
            "tp": 90.0,
            "sl": 105.0,
            "coin_signal": "",
            "macro_signal": "",
            "ai_confidence": 0.7,
        }
        text = svc._twitter_build_fixed_text(obj, lang="en")
        self.assertIn("R:R ~2.0:1", text)

    def test_rr_invalid_returns_na(self) -> None:
        obj = {
            "coin": "BTC",
            "direction": "多",
            "entry": 100.0,
            "tp": 99.0,
            "sl": 95.0,
            "coin_signal": "",
            "macro_signal": "",
            "ai_confidence": 0.7,
        }
        text = svc._twitter_build_fixed_text(obj, lang="en")
        self.assertIn("R:R ~n/a", text)

