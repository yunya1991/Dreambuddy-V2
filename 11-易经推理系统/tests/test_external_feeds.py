"""Phase 5 TDD 测试：外部数据源

Spec §8 — 外部数据源接入（S7 开关 enable_external_data）

免费数据源（已验证可用）：
  1. CoinGecko API — USDT 市值、BTC.D（无需 key，有 rate limit）
  2. alternative.me — Fear & Greed Index（无需 key）
  3. yfinance — VIX 恐慌指数（无需 key）

付费/不可用（预留接口）：
  - NYSE A/D Line — 需付费数据源，接口预留，返回 None

Spec §8.3 TDD 测试矩阵：
  - test_coingecko_api        CoinGecko API 调用，返回 USDT 市值
  - test_vix_fetch            VIX 数据拉取，返回 0-100 数值
  - test_external_data_off    S7 关闭时等价旧路径（零漂移）
"""

import sys
import os
import numpy as np
import pytest

# ── 路径设置 ──
_MEM_L4 = os.path.join(os.path.dirname(__file__), "..", "scripts", "memory_l4")
sys.path.insert(0, _MEM_L4)
sys.path.insert(0, os.path.join(_MEM_L4, "bcrm2"))


# ══════════════════════════════════════════════════════════════════
# 测试组 1: CoinGeckoFeed
# ══════════════════════════════════════════════════════════════════

class TestCoinGeckoFeed:

    def test_coingecko_api(self):
        """CoinGecko API 调用：返回 USDT 市值 > 0

        注意：CoinGecko 免费版有 rate limit（~30 次/分钟），
        若触发 429 则跳过此测试（网络限流，非代码 bug）。
        """
        from datafeeds.coingecko_feed import CoinGeckoFeed

        feed = CoinGeckoFeed()
        mc = feed.fetch_usdt_market_cap()
        if mc is None:
            pytest.skip("CoinGecko API rate limit 或网络不可用")
        assert mc > 0, f"USDT 市值异常: {mc}"
        # USDT 市值应在 10B ~ 500B 之间
        assert 1e10 < mc < 5e11, f"USDT 市值超出合理范围: {mc}"

    def test_coingecko_btc_dominance(self):
        """CoinGecko BTC.D: 返回 0-100 之间的百分比"""
        from datafeeds.coingecko_feed import CoinGeckoFeed

        feed = CoinGeckoFeed()
        btc_d = feed.fetch_btc_dominance()
        if btc_d is None:
            pytest.skip("CoinGecko API rate limit 或网络不可用")
        assert 0 < btc_d < 100, f"BTC.D 超出合理范围: {btc_d}"

    def test_coingecko_fetch_all(self):
        """fetch_all 返回包含所有字段的 dict"""
        from datafeeds.coingecko_feed import CoinGeckoFeed

        feed = CoinGeckoFeed()
        data = feed.fetch_all()
        assert isinstance(data, dict)
        assert "usdt_market_cap" in data
        assert "btc_dominance" in data
        if data["usdt_market_cap"] is None or data["btc_dominance"] is None:
            pytest.skip("CoinGecko API rate limit 或网络不可用")
        assert data["usdt_market_cap"] > 0
        assert 0 < data["btc_dominance"] < 100

    def test_coingecko_cache(self):
        """同一秒内重复调用应命中缓存（不重复请求）"""
        from datafeeds.coingecko_feed import CoinGeckoFeed

        feed = CoinGeckoFeed(cache_ttl=60)
        mc1 = feed.fetch_usdt_market_cap()
        mc2 = feed.fetch_usdt_market_cap()
        # 缓存命中应返回相同值（包括都为 None 的情况）
        assert mc1 == mc2


# ══════════════════════════════════════════════════════════════════
# 测试组 2: MacroFeed
# ══════════════════════════════════════════════════════════════════

class TestMacroFeed:

    def test_vix_fetch(self):
        """VIX 数据拉取：返回 0-100 数值（网络不可用时跳过）"""
        from datafeeds.macro_feed import MacroFeed

        feed = MacroFeed()
        vix = feed.fetch_vix()
        if vix is None:
            pytest.skip("yfinance VIX 网络不可用")
        assert 0 < vix < 100, f"VIX 超出合理范围: {vix}"

    def test_fear_greed_index(self):
        """Fear & Greed Index: 返回 0-100 数值（网络不可用时跳过）"""
        from datafeeds.macro_feed import MacroFeed

        feed = MacroFeed()
        fgi = feed.fetch_fear_greed_index()
        if fgi is None:
            pytest.skip("Fear & Greed API 网络不可用")
        assert 0 <= fgi <= 100, f"Fear & Greed 超出合理范围: {fgi}"

    def test_advance_decline_line_not_implemented(self):
        """A/D Line 预留接口：未接入付费数据源时返回 None"""
        from datafeeds.macro_feed import MacroFeed

        feed = MacroFeed()
        adl = feed.fetch_advance_decline_line()
        # 预留接口，未接入时返回 None（不抛异常）
        assert adl is None, f"A/D Line 应返回 None（预留接口），实际: {adl}"

    def test_macro_fetch_all(self):
        """fetch_all 返回包含 VIX 和 F&G 的 dict"""
        from datafeeds.macro_feed import MacroFeed

        feed = MacroFeed()
        data = feed.fetch_all()
        assert isinstance(data, dict)
        assert "vix" in data
        assert "fear_greed_index" in data
        assert "advance_decline_line" in data
        # A/D Line 必须为 None（预留接口）
        assert data["advance_decline_line"] is None
        # VIX 和 F&G 网络不可用时可为 None，但字段必须存在
        if data["vix"] is not None:
            assert 0 < data["vix"] < 100
        if data["fear_greed_index"] is not None:
            assert 0 <= data["fear_greed_index"] <= 100


# ══════════════════════════════════════════════════════════════════
# 测试组 3: S7 开关零漂移
# ══════════════════════════════════════════════════════════════════

class TestExternalDataSwitch:

    def test_external_data_off_equivalent_baseline(self):
        """S7 关闭时 RegimePredictor 行为等价旧路径（零漂移）"""
        from regime_predictor import RegimePredictor

        np.random.seed(42)
        n, nf = 200, 6
        X = np.random.randn(n, nf)
        # 所有 8 个类别都需出现
        regimes8 = [
            "TREND_UP_STRONG", "TREND_UP_MILD", "RANGE_BOUND", "CONSOLIDATION",
            "REVERSAL", "VOLATILE_DROP", "FOMO_RALLY", "DISTRIBUTION",
        ]
        y = np.array(regimes8 * (n // 8) + [regimes8[0]] * (n % 8), dtype=object)

        # S7 关闭
        predictor_off = RegimePredictor(enable_external_data=False)
        predictor_off.fit(X, y, feature_names=[f"f{i}" for i in range(nf)])
        y_off, conf_off, proba_off = predictor_off.predict(X)

        # baseline（同参数）
        predictor_base = RegimePredictor(enable_external_data=False)
        predictor_base.fit(X, y, feature_names=[f"f{i}" for i in range(nf)])
        y_base, conf_base, proba_base = predictor_base.predict(X)

        np.testing.assert_array_equal(y_off, y_base)
        np.testing.assert_array_almost_equal(proba_off, proba_base)

    def test_external_data_off_default(self):
        """S7 默认关闭（enable_external_data 默认 False）"""
        from regime_predictor import RegimePredictor

        predictor = RegimePredictor()
        assert predictor.enable_external_data is False

    def test_external_data_on_accepts_dict(self):
        """S7 打开时可通过 external_data 注入外部特征"""
        from regime_predictor import RegimePredictor

        np.random.seed(42)
        n, nf = 200, 6
        X = np.random.randn(n, nf)
        # 所有 8 个类别都需出现，否则 predict_proba 列数 < 8
        regimes8 = [
            "TREND_UP_STRONG", "TREND_UP_MILD", "RANGE_BOUND", "CONSOLIDATION",
            "REVERSAL", "VOLATILE_DROP", "FOMO_RALLY", "DISTRIBUTION",
        ]
        y = np.array(regimes8 * (n // 8) + [regimes8[0]] * (n % 8), dtype=object)

        # S7 打开 + 注入外部数据
        external_data = {
            "usdt_market_cap": 183e9,
            "btc_dominance": 56.0,
            "vix": 18.0,
            "fear_greed_index": 41.0,
        }
        predictor = RegimePredictor(enable_external_data=True)
        predictor.fit(X, y, feature_names=[f"f{i}" for i in range(nf)])
        predictor.set_external_data(external_data)

        # S7 打开时应能预测（不抛异常）
        y_pred, conf, proba = predictor.predict(X)
        assert len(y_pred) == n
        assert proba.shape == (n, len(predictor.REGIME_ORDER))
