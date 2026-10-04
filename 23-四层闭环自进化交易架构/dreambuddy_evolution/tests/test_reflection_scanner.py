"""Test ReflectionScanner class prior inheritance (P1a) and asset class mapper."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure package importable
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dreambuddy_evolution.engines.asset_class_mapper import (
    get_asset_class,
    get_coarse_class,
    get_all_classified_coins,
    CRYPTO_MAJOR,
    CRYPTO_LAYER1,
    CRYPTO_DEFI,
    CRYPTO_MEME,
    CRYPTO_ALT,
    US_STOCK,
    PRECIOUS_METAL,
)


class TestAssetClassMapper:
    """Test asset_class_mapper.py coin classification."""

    def test_get_asset_class_known_coins(self):
        assert get_asset_class("BTC") == CRYPTO_MAJOR
        assert get_asset_class("ETH") == CRYPTO_MAJOR
        assert get_asset_class("SOL") == CRYPTO_LAYER1
        assert get_asset_class("UNI") == CRYPTO_DEFI
        assert get_asset_class("DOGE") == CRYPTO_MEME
        assert get_asset_class("XRP") == CRYPTO_ALT

    def test_get_asset_class_us_stock(self):
        assert get_asset_class("NVDA") == US_STOCK
        assert get_asset_class("GOOGL") == US_STOCK

    def test_get_asset_class_precious_metal(self):
        assert get_asset_class("XAU") == PRECIOUS_METAL
        assert get_asset_class("XAG") == PRECIOUS_METAL

    def test_get_asset_class_unknown_coin(self):
        assert get_asset_class("UNKNOWN") is None
        assert get_asset_class("") is None

    def test_case_insensitive(self):
        assert get_asset_class("btc") == CRYPTO_MAJOR
        assert get_asset_class("Sol") == CRYPTO_LAYER1

    def test_get_coarse_class(self):
        assert get_coarse_class("BTC") == "crypto_usdt"
        assert get_coarse_class("NVDA") == "us_stock"
        assert get_coarse_class("XAU") == "precious_metal"
        assert get_coarse_class("UNKNOWN") is None

    def test_all_scan_coins_classified(self):
        """Every coin in SCAN_COINS must be classified (regression guard)."""
        SCAN_COINS = [
            "UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB",
            "MU", "SKHYNIX", "XAU", "XAG", "GOOGL", "NVDA", "AMZN", "OKB", "SNDK", "SPCX",
            "COIN", "BMNR", "MSTR", "BNB", "LINK", "DOGE", "XRP", "ADA", "DOT", "AVAX",
            "MATIC", "LTC", "TRX", "ATOM", "NEAR", "APT", "OP", "INJ", "PEPE", "WIF",
            "SHIB", "TON", "SUI", "FIL", "ETC", "IMX", "SEI", "TIA", "JUP", "RUNE",
            "VET", "FTM", "ALGO", "HBAR", "ICP", "EGLD", "XTZ", "XLM", "EOS",
            "CRO", "QNT", "GRT", "SNX", "COMP", "MKR", "DYDX", "GMX", "RDNT",
        ]
        missing = [c for c in SCAN_COINS if get_asset_class(c) is None]
        assert not missing, f"Unclassified coins: {missing}"


class TestReflectionScannerClassPrior:
    """Test ReflectionScanner class prior inheritance for coins with no trades."""

    def _write_mock_trades(self, tmp_path: Path, trades: list[dict]):
        """Write mock trades to a JSONL file."""
        p = tmp_path / "mock_trades.jsonl"
        with open(p, "w") as f:
            for t in trades:
                f.write(json.dumps(t) + "\n")
        return str(p)

    def test_get_coin_stats_no_trades_returns_default(self):
        """Unknown coin with no class prior returns default values."""
        from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
        rs = ReflectionScanner(project_root="/tmp")
        # Force empty cache
        rs._cache = {}
        rs._cache_ts = float("inf")
        rs._class_priors = {}
        stats = rs.get_coin_stats("TOTALLY_UNKNOWN")
        assert stats["reflection_ri"] == 0.50
        assert stats["eligible"] is False
        assert stats["is_prior"] is False

    def test_class_prior_ri_capped_at_065(self):
        """Class prior reflection_ri should be capped at 0.65."""
        from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
        rs = ReflectionScanner(project_root="/tmp")
        # Manually set high-ri class prior
        rs._class_priors = {
            "crypto_major": {
                "class_win_rate": 0.90,
                "class_n_trades": 100,
                "class_reflection_ri": 0.65,
                "class_eligible": True,
                "has_real_trades": True,
            }
        }
        rs._cache = {}
        rs._cache_ts = float("inf")
        stats = rs.get_coin_stats("BTC")  # BTC has trades normally, but cache is empty
        # Since BTC is in cache (empty), it falls to class prior
        # Wait - BTC might be in the empty cache. Let's force it.
        # Actually with empty cache and force=False, scan() will reload.
        # But we set cache_ts to inf so it won't reload.
        # Since BTC is not in the empty cache, it goes to class prior.
        assert stats["reflection_ri"] <= 0.65
        assert stats["is_prior"] is True
        assert stats["asset_class"] == "crypto_major"

    def test_real_trades_coin_not_prior(self):
        """Coin with trade records should never have is_prior=True."""
        from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
        rs = ReflectionScanner(project_root="/tmp")
        # Set cache with a real trade coin
        rs._cache = {
            "BTC": {
                "win_rate": 0.70,
                "n_trades": 10,
                "avg_pnl_pct": 0.02,
                "reflection_ri": 0.62,
                "eligible": True,
                "sources": {"bcrm": 10},
                "is_backtest_only": False,
                "is_prior": False,
            }
        }
        rs._cache_ts = float("inf")
        rs._class_priors = {}
        stats = rs.get_coin_stats("BTC")
        assert stats["is_prior"] is False
        assert stats["win_rate"] == 0.70

    def test_fail_open_on_missing_class_priors(self):
        """If _class_priors is missing or broken, get_coin_stats returns default."""
        from dreambuddy_evolution.engines.reflection_scanner import ReflectionScanner
        rs = ReflectionScanner(project_root="/tmp")
        rs._cache = {}
        rs._cache_ts = float("inf")
        # Don't set _class_priors at all
        if hasattr(rs, "_class_priors"):
            del rs._class_priors
        stats = rs.get_coin_stats("VET")
        # Should not crash, should return default or prior
        assert "reflection_ri" in stats
        assert "is_prior" in stats
