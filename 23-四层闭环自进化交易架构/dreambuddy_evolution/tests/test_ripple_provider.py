"""
RippleDataProvider 测试 — R2 关联币 + R3 板块扩散
覆盖: MA20 趋势 / 强度过滤 / 量比确认 / R2-R3 差异化 / FAIL-OPEN
"""
import pytest

from dreambuddy_evolution.adapters.ripple_provider import RippleDataProvider


def _make_candles(direction: str, strength: float = 0.02, vol_ratio: float = 1.5, n: int = 30):
    """
    构造 30 根 4H K线（降序，candles[0]=最新）。

    - direction="long": close_last > MA20 by `strength`
    - direction="short": close_last < MA20 by `strength`
    - vol_ratio: vol_5 / vol_20
    """
    base = 100.0
    ma20 = base  # MA20 基准
    close_last = ma20 * (1 + strength) if direction == "long" else ma20 * (1 - strength)

    # 前 20 根 close 在 ma20 附近（确保 MA20 ≈ base）
    closes = [base] * 20
    closes[0] = close_last  # 最新一根偏离 MA20

    # 后 10 根也在 base 附近
    closes.extend([base] * (n - 20))

    # 成交量：前 5 根放量 vs 后 15 根
    base_vol = 1000.0
    high_vol = base_vol * vol_ratio
    vols = [high_vol] * 5 + [base_vol] * (n - 5)

    candles = []
    for i in range(n):
        candles.append({
            "ts": (n - i) * 4 * 3600 * 1000,
            "o": closes[i], "h": closes[i] * 1.01,
            "l": closes[i] * 0.99, "c": closes[i],
            "vol": vols[i],
        })
    return candles


class MockOKXClient:
    """模拟 OKX 客户端 — 按币种返回不同 4H 信号"""

    def __init__(self, signals: dict[str, dict]):
        # signals: {"ETH": {"direction": "long", "strength": 0.02, "vol_ratio": 1.5}, ...}
        self._signals = signals

    def get_kline(self, inst_id, bar="1H", limit=200):
        symbol = inst_id.split("-")[0]
        sig = self._signals.get(symbol)
        if sig is None:
            return {"ok": False, "error": "no data"}

        if bar == "4H":
            candles = _make_candles(
                direction=sig["direction"],
                strength=sig.get("strength", 0.02),
                vol_ratio=sig.get("vol_ratio", 1.5),
            )
            return {"ok": True, "candles": candles}

        # 非 4H 返回简单数据
        return {"ok": True, "candles": _make_candles("long", 0.01, 1.0, limit)}


class TestRippleDataProvider:
    def test_r2_all_match_long_with_volume(self):
        """BTC R2: ETH+SOL 全部 long, 强度达标, 放量 → hits=2, candidates=2"""
        client = MockOKXClient({
            "ETH": {"direction": "long", "strength": 0.02, "vol_ratio": 1.5},
            "SOL": {"direction": "long", "strength": 0.03, "vol_ratio": 2.0},
        })
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        assert result["R2"]["hits"] == 2
        assert result["R2"]["candidates"] == 2

    def test_r2_no_volume_filtered_out(self):
        """BTC R2: ETH+SOL long 但无放量 → 全部被过滤, candidates=0→1"""
        client = MockOKXClient({
            "ETH": {"direction": "long", "strength": 0.02, "vol_ratio": 0.8},
            "SOL": {"direction": "long", "strength": 0.03, "vol_ratio": 0.5},
        })
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        # R2 要求放量，无量 → candidates=0（max to 1）
        assert result["R2"]["hits"] == 0
        assert result["R2"]["candidates"] == 1

    def test_r2_weak_strength_filtered(self):
        """BTC R2: 强度 < 1% 被过滤"""
        client = MockOKXClient({
            "ETH": {"direction": "long", "strength": 0.003, "vol_ratio": 1.5},
            "SOL": {"direction": "long", "strength": 0.004, "vol_ratio": 2.0},
        })
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        assert result["R2"]["hits"] == 0
        assert result["R2"]["candidates"] == 1

    def test_r3_no_volume_required(self):
        """BTC R3: 不强制放量，无量也计入候选"""
        client = MockOKXClient({
            c: {"direction": "long", "strength": 0.01, "vol_ratio": 0.5}
            for c in ["ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"]
        })
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        # R3 不要求放量 → 6 个全部计入
        assert result["R3"]["hits"] == 6
        assert result["R3"]["candidates"] == 6

    def test_r3_weaker_strength_allowed(self):
        """BTC R3: 强度 0.6% > 0.5% 阈值 → 计入"""
        client = MockOKXClient({
            c: {"direction": "short", "strength": 0.006, "vol_ratio": 0.5}
            for c in ["ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"]
        })
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "short")
        assert result["R3"]["hits"] == 6
        assert result["R3"]["candidates"] == 6

    def test_r2_stricter_than_r3(self):
        """R2 比 R3 严格: 强度 0.7% + 无量 → R2 过滤, R3 通过"""
        client = MockOKXClient({
            "ETH": {"direction": "long", "strength": 0.007, "vol_ratio": 0.5},
            "SOL": {"direction": "long", "strength": 0.007, "vol_ratio": 0.5},
            "BNB": {"direction": "long", "strength": 0.007, "vol_ratio": 0.5},
            "XRP": {"direction": "long", "strength": 0.007, "vol_ratio": 0.5},
            "ADA": {"direction": "long", "strength": 0.007, "vol_ratio": 0.5},
            "DOGE": {"direction": "long", "strength": 0.007, "vol_ratio": 0.5},
        })
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        # R2: 无量 + 强度0.7%<1% → 0 candidates
        assert result["R2"]["candidates"] == 1
        assert result["R2"]["hits"] == 0
        # R3: 强度0.7%>0.5%, 不要求放量 → 6 candidates
        assert result["R3"]["candidates"] == 6
        assert result["R3"]["hits"] == 6

    def test_empty_ess_direction(self):
        """ESS 方向为空 → hits=0, candidates=1"""
        client = MockOKXClient({"ETH": {"direction": "long", "strength": 0.02, "vol_ratio": 1.5}})
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "")
        assert result["R2"]["hits"] == 0
        assert result["R2"]["candidates"] == 1

    def test_fo_coin_fetch_fail(self):
        """部分币种获取失败 → 跳过，不崩溃"""
        client = MockOKXClient({"ETH": {"direction": "long", "strength": 0.02, "vol_ratio": 1.5}})
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        # 只有 ETH 成功，SOL 失败
        assert result["R2"]["hits"] == 1
        assert result["R2"]["candidates"] == 1

    def test_fo_all_coins_fail(self):
        """全部币种获取失败 → hits=0, candidates=1"""
        client = MockOKXClient({})
        provider = RippleDataProvider(client)
        result = provider.get_ripple_hits("BTC", "long")
        assert result["R2"]["hits"] == 0
        assert result["R2"]["candidates"] == 1

    def test_fetch_4h_signal_long(self):
        """_fetch_4h_signal: close > MA20 → direction=long"""
        client = MockOKXClient({"BTC": {"direction": "long", "strength": 0.02, "vol_ratio": 1.5}})
        provider = RippleDataProvider(client)
        signal = provider._fetch_4h_signal("BTC")
        assert signal is not None
        assert signal["direction"] == "long"
        assert signal["strength"] > 0
        # vol_ratio = vol_5/vol_20; vol_20 包含前5根放量 → 实际值略低于输入
        assert signal["vol_ratio"] > 1.0  # 放量确认

    def test_fetch_4h_signal_short(self):
        """_fetch_4h_signal: close < MA20 → direction=short"""
        client = MockOKXClient({"BTC": {"direction": "short", "strength": 0.03, "vol_ratio": 2.0}})
        provider = RippleDataProvider(client)
        signal = provider._fetch_4h_signal("BTC")
        assert signal is not None
        assert signal["direction"] == "short"

    def test_fetch_4h_signal_fail(self):
        """_fetch_4h_signal: 获取失败 → None"""
        client = MockOKXClient({})
        provider = RippleDataProvider(client)
        assert provider._fetch_4h_signal("BTC") is None

    def test_is_confirmed_strength_only(self):
        """_is_confirmed: 不要求放量时，仅检查强度"""
        sig = {"direction": "long", "strength": 0.006, "vol_ratio": 0.5}
        # R3 params: min_strength=0.005, require_volume=False
        assert RippleDataProvider._is_confirmed(sig, 0.005, False) is True
        # R2 params: min_strength=0.01, require_volume=True
        assert RippleDataProvider._is_confirmed(sig, 0.01, True) is False

    def test_is_confirmed_with_volume(self):
        """_is_confirmed: 要求放量时，强度+量比都要达标"""
        sig = {"direction": "long", "strength": 0.02, "vol_ratio": 1.5}
        assert RippleDataProvider._is_confirmed(sig, 0.01, True) is True
        sig_low_vol = {"direction": "long", "strength": 0.02, "vol_ratio": 0.8}
        assert RippleDataProvider._is_confirmed(sig_low_vol, 0.01, True) is False

    def test_strength_capped_at_0_1(self):
        """强度 cap 在 0.1"""
        client = MockOKXClient({"BTC": {"direction": "long", "strength": 0.5, "vol_ratio": 1.5}})
        provider = RippleDataProvider(client)
        signal = provider._fetch_4h_signal("BTC")
        assert signal is not None
        assert signal["strength"] <= 0.1
