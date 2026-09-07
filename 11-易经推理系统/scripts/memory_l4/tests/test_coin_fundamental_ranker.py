"""B1: CoinFundamentalSignal 数据类 + coin 映射表测试 — TDD 先红后绿。

验证：
- CoinFundamentalSignal dataclass 字段完整
- classify_asset_class 正确分类 crypto_usdt / us_stock / precious_metal
- CRYPTO_MAP / STOCK_MAP / METAL_MAP 映射正确
- get_protocol_mapping 返回 DeFiLlama protocol slug
- 未知 coin 返回 None
"""
import pytest
import sys
from pathlib import Path
from datetime import datetime, timezone

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_ranker import (
    CoinFundamentalSignal,
    CRYPTO_MAP,
    STOCK_MAP,
    METAL_MAP,
    classify_asset_class,
    get_protocol_mapping,
    get_coingecko_id,
    get_yfinance_symbol,
)


# ---------------------------------------------------------------------------
# CoinFundamentalSignal dataclass
# ---------------------------------------------------------------------------

class TestCoinFundamentalSignalDataclass:
    """验证 CoinFundamentalSignal 字段完整。"""

    def test_signal_dataclass_fields(self):
        """CoinFundamentalSignal 含全部必填字段。"""
        sig = CoinFundamentalSignal(
            coin="UNI",
            asset_class="crypto_usdt",
            fundamental_score=0.35,
            rank="A",
            sub_signals={
                "revenue_stability": 0.4,
                "mc_fees_mean_reversion": 0.3,
                "tvl_growth_momentum": 0.2,
                "revenue_quality": 0.5,
            },
            data_quality="sufficient",
            confidence=0.72,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert sig.coin == "UNI"
        assert sig.asset_class == "crypto_usdt"
        assert sig.fundamental_score == pytest.approx(0.35)
        assert sig.rank == "A"
        assert len(sig.sub_signals) == 4
        assert sig.data_quality == "sufficient"
        assert sig.confidence == pytest.approx(0.72)
        assert sig.error is None  # 默认 None

    def test_signal_error_field_defaults_none(self):
        """error 字段默认 None（FAIL-OPEN 时可设为错误信息）。"""
        sig = CoinFundamentalSignal(
            coin="UNKNOWN",
            asset_class="",
            fundamental_score=0.0,
            rank="B",
            sub_signals={},
            data_quality="insufficient",
            confidence=0.0,
            timestamp="",
            error="classify failed: unknown coin",
        )
        assert sig.error == "classify failed: unknown coin"


# ---------------------------------------------------------------------------
# E4: CoinFundamentalSignal 阶段字段扩展（Phase E 闭环）
# ---------------------------------------------------------------------------

class TestCoinFundamentalSignalPhaseFields:
    """验证 CoinFundamentalSignal 新增 4 个阶段字段（E4）。"""

    def test_signal_has_current_phase_field_default_p2(self):
        """current_phase 默认 P2_REVENUE_EXPANSION（中性）。"""
        sig = CoinFundamentalSignal(
            coin="UNI", asset_class="crypto_usdt",
            fundamental_score=0.35, rank="A",
            sub_signals={}, data_quality="sufficient",
            confidence=0.72, timestamp="",
        )
        assert sig.current_phase == "P2_REVENUE_EXPANSION"

    def test_signal_has_phase_confidence_default_zero(self):
        """phase_confidence 默认 0.0。"""
        sig = CoinFundamentalSignal(
            coin="UNI", asset_class="crypto_usdt",
            fundamental_score=0.35, rank="A",
            sub_signals={}, data_quality="sufficient",
            confidence=0.72, timestamp="",
        )
        assert sig.phase_confidence == 0.0

    def test_signal_has_phase_switch_triggers_default_empty(self):
        """phase_switch_triggers 默认空 list。"""
        sig = CoinFundamentalSignal(
            coin="UNI", asset_class="crypto_usdt",
            fundamental_score=0.35, rank="A",
            sub_signals={}, data_quality="sufficient",
            confidence=0.72, timestamp="",
        )
        assert sig.phase_switch_triggers == []

    def test_signal_has_phase_strategy_hint_default_empty(self):
        """phase_strategy_hint 默认空 dict。"""
        sig = CoinFundamentalSignal(
            coin="UNI", asset_class="crypto_usdt",
            fundamental_score=0.35, rank="A",
            sub_signals={}, data_quality="sufficient",
            confidence=0.72, timestamp="",
        )
        assert sig.phase_strategy_hint == {}

    def test_signal_phase_fields_can_be_set(self):
        """phase 字段可以被显式赋值。"""
        sig = CoinFundamentalSignal(
            coin="CRCL", asset_class="crypto_usdt",
            fundamental_score=0.5, rank="S",
            sub_signals={}, data_quality="sufficient",
            confidence=0.8, timestamp="",
            current_phase="P1_EXPECTATION",
            phase_confidence=0.85,
            phase_switch_triggers=["e6_high_val_low"],
            phase_strategy_hint={"case_anchor": "CRCL"},
        )
        assert sig.current_phase == "P1_EXPECTATION"
        assert sig.phase_confidence == 0.85
        assert sig.phase_switch_triggers == ["e6_high_val_low"]
        assert sig.phase_strategy_hint["case_anchor"] == "CRCL"


# ---------------------------------------------------------------------------
# classify_asset_class
# ---------------------------------------------------------------------------

class TestClassifyAssetClass:
    """验证 classify_asset_class 正确分类。"""

    def test_classify_asset_class_crypto(self):
        assert classify_asset_class("BTC") == "crypto_usdt"
        assert classify_asset_class("ETH") == "crypto_usdt"
        assert classify_asset_class("UNI") == "crypto_usdt"
        assert classify_asset_class("LINK") == "crypto_usdt"
        assert classify_asset_class("AAVE") == "crypto_usdt"

    def test_classify_asset_class_stock(self):
        assert classify_asset_class("NVDA") == "us_stock"
        assert classify_asset_class("AAPL") == "us_stock"
        assert classify_asset_class("MSFT") == "us_stock"

    def test_classify_asset_class_metal(self):
        assert classify_asset_class("XAUUSD") == "precious_metal"
        assert classify_asset_class("XAGUSD") == "precious_metal"

    def test_classify_unknown_returns_none(self):
        assert classify_asset_class("DOGE") is None
        assert classify_asset_class("UNKNOWN123") is None
        assert classify_asset_class("") is None


# ---------------------------------------------------------------------------
# 映射表
# ---------------------------------------------------------------------------

class TestCryptoMap:
    """验证 CRYPTO_MAP 映射。"""

    def test_crypto_map_uni_to_uniswap(self):
        """UNI → CoinGecko id=uniswap, DeFiLlama slug=uniswap。"""
        info = CRYPTO_MAP["UNI"]
        assert info["coingecko_id"] == "uniswap"
        assert info["defillama_slug"] == "uniswap"

    def test_crypto_map_btc_to_bitcoin(self):
        info = CRYPTO_MAP["BTC"]
        assert info["coingecko_id"] == "bitcoin"
        # BTC 是链，不是 protocol，无 DeFiLlama slug
        assert info["defillama_slug"] is None

    def test_crypto_map_contains_aave(self):
        info = CRYPTO_MAP["AAVE"]
        assert info["coingecko_id"] == "aave"
        assert info["defillama_slug"] == "aave"

    # --- E6: 新增 HYPE / CRCL 映射 ---

    def test_crypto_map_hype_to_hyperliquid(self):
        """HYPE → CoinGecko id=hyperliquid, DeFiLlama slug=hyperliquid。"""
        info = CRYPTO_MAP["HYPE"]
        assert info["coingecko_id"] == "hyperliquid"
        assert info["defillama_slug"] == "hyperliquid"

    def test_crypto_map_crcl_resolves(self):
        """CRCL 必须可解析（CoinGecko id 非空，DeFiLlama slug 可为 None）。"""
        assert "CRCL" in CRYPTO_MAP
        info = CRYPTO_MAP["CRCL"]
        assert info["coingecko_id"] is not None
        # CRCL 视实际可用性调整，DeFiLlama slug 可为 None（非 protocol 类）

    def test_classify_asset_class_hype_is_crypto(self):
        """HYPE 必须分类为 crypto_usdt。"""
        assert classify_asset_class("HYPE") == "crypto_usdt"

    def test_classify_asset_class_crcl_is_crypto(self):
        """CRCL 必须分类为 crypto_usdt。"""
        assert classify_asset_class("CRCL") == "crypto_usdt"

    def test_get_coingecko_id_hype(self):
        assert get_coingecko_id("HYPE") == "hyperliquid"

    def test_get_protocol_mapping_hype(self):
        assert get_protocol_mapping("HYPE") == "hyperliquid"


class TestStockMap:
    """验证 STOCK_MAP 映射。"""

    def test_stock_map_nvda(self):
        assert STOCK_MAP["NVDA"] == "NVDA"

    def test_stock_map_aapl(self):
        assert STOCK_MAP["AAPL"] == "AAPL"


class TestMetalMap:
    """验证 METAL_MAP 映射。"""

    def test_metal_map_xauusd(self):
        info = METAL_MAP["XAUUSD"]
        assert info["yfinance_etf"] == "GLD"
        assert info["fred_series"] == "T10YIE"

    def test_metal_map_xagusd(self):
        info = METAL_MAP["XAGUSD"]
        assert info["yfinance_etf"] == "SLV"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

class TestGetProtocolMapping:
    """验证 get_protocol_mapping。"""

    def test_uni_returns_uniswap(self):
        assert get_protocol_mapping("UNI") == "uniswap"

    def test_aave_returns_aave(self):
        assert get_protocol_mapping("AAVE") == "aave"

    def test_btc_returns_none(self):
        """BTC 是链不是 protocol，返回 None。"""
        assert get_protocol_mapping("BTC") is None

    def test_non_crypto_returns_none(self):
        assert get_protocol_mapping("NVDA") is None
        assert get_protocol_mapping("XAUUSD") is None

    def test_unknown_returns_none(self):
        assert get_protocol_mapping("DOGE") is None


class TestGetCoingeckoId:
    """验证 get_coingecko_id。"""

    def test_uni_returns_uniswap(self):
        assert get_coingecko_id("UNI") == "uniswap"

    def test_btc_returns_bitcoin(self):
        assert get_coingecko_id("BTC") == "bitcoin"

    def test_non_crypto_returns_none(self):
        assert get_coingecko_id("NVDA") is None

    def test_unknown_returns_none(self):
        assert get_coingecko_id("DOGE") is None


class TestGetYfinanceSymbol:
    """验证 get_yfinance_symbol。"""

    def test_stock_nvda(self):
        assert get_yfinance_symbol("NVDA") == "NVDA"

    def test_metal_xauusd(self):
        """贵金属通过 ETF symbol 获取。"""
        assert get_yfinance_symbol("XAUUSD") == "GLD"

    def test_metal_xagusd(self):
        assert get_yfinance_symbol("XAGUSD") == "SLV"

    def test_crypto_returns_none(self):
        """加密货币不走 yfinance。"""
        assert get_yfinance_symbol("BTC") is None

    def test_unknown_returns_none(self):
        assert get_yfinance_symbol("DOGE") is None


# ---------------------------------------------------------------------------
# E4: compute_signal 阶段集成（Phase E 闭环）
# ---------------------------------------------------------------------------

class TestComputeSignalPhaseIntegration:
    """验证 compute_signal 在合成后调用 classify_phase + get_strategy_hint。

    集成点（spec E4）：compute_signal() 在等权合成后调用 classify_phase()，
    填充 current_phase / phase_confidence / phase_switch_triggers / phase_strategy_hint。
    """

    def test_compute_signal_populates_phase_fields_on_success(self):
        """compute_signal 成功后必须填充 4 个 phase 字段（非默认空值）。"""
        from unittest.mock import patch
        from force_vector.coin_fundamental_ranker import compute_signal

        # 模拟 crypto compute_all 返回 P2 强信号（E5 高、E6 正）
        fake_signals = {
            "revenue_stability": 0.5,
            "mc_fees_mean_reversion": 0.3,
            "tvl_growth_momentum": 0.4,
            "revenue_quality": 0.5,
            "supply_shrinkage_intensity": 0.7,  # E5 高
            "value_capture_delta": 0.5,         # E6 正
        }
        with patch("force_vector.coin_fundamental_ranker._get_crypto_compute_all") as mock:
            mock.return_value = lambda coin, db: fake_signals
            sig = compute_signal("UNI", db_path="/fake/db.db")

        assert sig.current_phase == "P2_REVENUE_EXPANSION"
        assert sig.phase_confidence > 0.0
        assert len(sig.phase_switch_triggers) > 0
        assert "e5_high_e6_positive" in sig.phase_switch_triggers
        # phase_strategy_hint 必须从映射表查询得到（含 case_anchor）
        assert sig.phase_strategy_hint.get("case_anchor") == "UNI"
        assert sig.phase_strategy_hint.get("priority_weight") == 2

    def test_compute_signal_phase_default_p2_on_neutral(self):
        """中性信号（全 0）→ phase 默认 P2 + 低 confidence。"""
        from unittest.mock import patch
        from force_vector.coin_fundamental_ranker import compute_signal

        fake_signals = {
            "revenue_stability": 0.0,
            "mc_fees_mean_reversion": 0.0,
            "tvl_growth_momentum": 0.0,
            "revenue_quality": 0.0,
            "supply_shrinkage_intensity": 0.0,
            "value_capture_delta": 0.0,
        }
        with patch("force_vector.coin_fundamental_ranker._get_crypto_compute_all") as mock:
            mock.return_value = lambda coin, db: fake_signals
            sig = compute_signal("UNI", db_path="/fake/db.db")

        assert sig.current_phase == "P2_REVENUE_EXPANSION"
        assert "default_neutral" in sig.phase_switch_triggers

    def test_compute_signal_phase_failopen_keeps_default_p2(self):
        """子模块抛异常 → FAIL-OPEN，phase 保持默认 P2 + confidence=0。"""
        from unittest.mock import patch
        from force_vector.coin_fundamental_ranker import compute_signal

        def raise_fn(coin, db):
            raise RuntimeError("db not found")

        with patch("force_vector.coin_fundamental_ranker._get_crypto_compute_all") as mock:
            mock.return_value = raise_fn
            sig = compute_signal("UNI", db_path="/fake/db.db")

        assert sig.current_phase == "P2_REVENUE_EXPANSION"
        assert sig.phase_confidence == 0.0
        assert sig.phase_strategy_hint == {}  # FAIL-OPEN 不查映射表
        assert sig.error is not None

    def test_compute_signal_phase_strategy_hint_has_required_keys(self):
        """phase_strategy_hint 必须含映射表全部核心字段。"""
        from unittest.mock import patch
        from force_vector.coin_fundamental_ranker import compute_signal

        fake_signals = {
            "revenue_stability": 0.5, "mc_fees_mean_reversion": 0.5,
            "tvl_growth_momentum": 0.5, "revenue_quality": 0.5,
            "supply_shrinkage_intensity": 0.7, "value_capture_delta": 0.5,
        }
        with patch("force_vector.coin_fundamental_ranker._get_crypto_compute_all") as mock:
            mock.return_value = lambda coin, db: fake_signals
            sig = compute_signal("UNI", db_path="/fake/db.db")

        required = {
            "signal_weight_bias", "sl_space_hint", "tp_space_hint",
            "holding_period_hint", "case_anchor", "priority_weight",
        }
        assert required.issubset(set(sig.phase_strategy_hint.keys()))

    def test_compute_signal_uses_real_valuation_query(self):
        """F1 集成：compute_signal 调用 query_valuation_percentile 获取真实分位。"""
        from unittest.mock import patch
        from force_vector.coin_fundamental_ranker import compute_signal

        fake_signals = {
            "revenue_stability": 0.5, "mc_fees_mean_reversion": 0.5,
            "tvl_growth_momentum": 0.5, "revenue_quality": 0.5,
            "supply_shrinkage_intensity": 0.7, "value_capture_delta": 0.5,
        }
        # mock valuation 查询返回 85.0（高位）→ 应触发 P3 倾向
        with patch("force_vector.coin_fundamental_ranker._get_crypto_compute_all") as mock_crypto, \
             patch("force_vector.coin_fundamental_valuation_query.query_valuation_percentile",
                   return_value=85.0) as mock_val:
            mock_crypto.return_value = lambda coin, db: fake_signals
            sig = compute_signal("UNI", db_path="/fake/db.db")
            # 验证 query_valuation_percentile 被调用
            assert mock_val.called
            # valuation=85 + e5=0.7>0.3 → P3
            assert sig.current_phase == "P3_VALUATION_RECOVERY"

    def test_compute_signal_valuation_query_failopen_neutral(self):
        """F1 FAIL-OPEN：valuation 查询异常 → 返回 50（中性）→ 阶段默认 P2。"""
        from unittest.mock import patch
        from force_vector.coin_fundamental_ranker import compute_signal

        fake_signals = {
            "revenue_stability": 0.3, "mc_fees_mean_reversion": 0.3,
            "tvl_growth_momentum": 0.3, "revenue_quality": 0.3,
            "supply_shrinkage_intensity": 0.2, "value_capture_delta": 0.2,
        }
        with patch("force_vector.coin_fundamental_ranker._get_crypto_compute_all") as mock_crypto, \
             patch("force_vector.coin_fundamental_valuation_query.query_valuation_percentile",
                   side_effect=RuntimeError("db error")):
            mock_crypto.return_value = lambda coin, db: fake_signals
            # 查询异常被 compute_signal 的 try-except 捕获 → phase_classification=None
            # → current_phase 保持默认 P2
            sig = compute_signal("UNI", db_path="/fake/db.db")
            assert sig.current_phase == "P2_REVENUE_EXPANSION"
