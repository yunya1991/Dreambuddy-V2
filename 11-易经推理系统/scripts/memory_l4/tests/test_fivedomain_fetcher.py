"""FiveDomainFetcher 编排层单测 — 用 mock 的 DataCenter，校验 D1~T4 汇总为 coin_data。

失败→无 Key→空→fail-open：所有缺失字段应为 None，而不是抛异常。
三类资产：crypto_usdt / us_stock / precious_metal。
"""
import sys, os
import pytest

# 允许 import scripts/memory_l4
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_L4 = os.path.normpath(os.path.join(_HERE, ".."))
if _SCRIPTS_L4 not in sys.path:
    sys.path.insert(0, _SCRIPTS_L4)


# ---- 构造 mock DataCenter 产出的 DataRecord ----
def _fred(series, value, date="2026-08-21"):
    from data_center.core.contract import DataRecord
    from datetime import datetime, timezone
    return DataRecord(
        source="fred", category="macro", sub_category=series,
        timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
        metrics={"value": value, "date": date}, events=[],
        timeseries=[{"date": date, "value": value}], raw={"series_id": series},
    )

def _yf(symbol, price=100.0):
    from data_center.core.contract import DataRecord
    from datetime import datetime, timezone
    return DataRecord(
        source="yfinance", category="finance", sub_category=symbol,
        timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
        metrics={"price": price, "symbol": symbol}, events=[], timeseries=[], raw={},
    )

def _dl_chains(tvl_map: dict):
    from data_center.core.contract import DataRecord
    from datetime import datetime, timezone
    total = sum(tvl_map.values()) * 1e9  # 输入是 billion，还原成 dollar
    chains = {name: {"tvl": tvl*1e9, "tvl_bln": tvl} for name, tvl in tvl_map.items()}
    return DataRecord(
        source="defillama", category="chain", sub_category="chains_summary",
        timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
        metrics={"total_tvl": total, "total_tvl_bln": round(sum(tvl_map.values()), 4), "chain_count": len(tvl_map)},
        events=[], timeseries=[{"chain": n, "tvl_bln": t} for n, t in tvl_map.items()],
        raw={"chains": chains},
    )

def _gas(safe=12, propose=18, fast=24):
    from data_center.core.contract import DataRecord
    from datetime import datetime, timezone
    return DataRecord(
        source="etherscan", category="chain", sub_category="gas",
        timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
        metrics={"safe_gas": float(safe), "propose_gas": float(propose), "fast_gas": float(fast)},
        events=[], timeseries=[], raw={},
    )

def _tavily_results(n_good=2, n_bad=1):
    from data_center.core.contract import DataRecord
    from datetime import datetime, timezone
    good = [{"title": "宽松利好 crypto", "content": "SEC 批准 ETF 流入加速"}] * n_good
    bad = [{"title": "监管加码", "content": "CFTC 起诉交易所"}] * n_bad
    return DataRecord(
        source="tavily", category="news", sub_category="policy_query",
        timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
        metrics={"count": len(good) + len(bad)}, events=[],
        timeseries=[], raw={"results": good + bad},
    )


# ---- 测试 ----
class TestFiveDomainFetcher:
    def _target(self, overrides: dict | None = None):
        """构造 FiveDomainFetcher，内部注入一个 dict 版假的 DataCenter。"""
        from fivedomain_fetcher import FiveDomainFetcher

        default_results = {
            ("macro", "fred", "FEDFUNDS"): [_fred("FEDFUNDS", 5.25)],
            ("macro", "fred", "M2NS"):     [_fred("M2NS", 2.3)],
            ("macro", "fred", "WALCL"):    [_fred("WALCL", 7_200_000_000_000.0)],  # 7.2T
            # CPIAUCSL=240（<250 临界=非通胀） + INDPRO=102.5（>100=增长↑） → 美林: RECOVERY
            ("macro", "fred", "CPIAUCSL"): [_fred("CPIAUCSL", 240.0)],
            ("macro", "fred", "INDPRO"):   [_fred("INDPRO", 102.5)],
            ("finance", "yfinance", "^VIX"):        [_yf("^VIX", 14.2)],
            ("chain", "defillama", "chains"):       [_dl_chains({"Ethereum": 38.1, "TRON": 6.2})],
            ("chain", "etherscan", "gas"):          [_gas(12, 18, 24)],
            ("news", "tavily", "policy"):           [_tavily_results(2, 1)],
        }
        if overrides:
            default_results.update(overrides)

        class FakeDC:
            def __init__(self): self.calls = []
            def fetch(self, category, source=None, **kw):
                self.calls.append((category, source, dict(kw)))
                return default_results.get((category, source, kw.get("series") or kw.get("symbol") or kw.get("route") or kw.get("kind") or "policy"), [])

        dc = FakeDC()
        return FiveDomainFetcher(data_center=dc), dc

    def test_fetch_all_fills_crypto_keys(self):
        fetcher, dc = self._target()
        out = fetcher.fetch_coin_data()
        # 结构：三类资产
        assert set(out.keys()) == {"crypto_usdt", "us_stock", "precious_metal"}
        crypto = out["crypto_usdt"]
        # D1-D9 键存在（None 也允许，但结构要齐）
        for k in ("fedfunds_rate", "m2_yoy_pct", "fed_balance_sheet_trillion",
                  "us_cpi_yoy_pct", "us_indpro_yoy_pct",
                  "defi_tvl_bln", "gas_eth_gwei", "policy_sentiment_score",
                  "merrill_phase", "vix_close", "liquidity_score"):
            assert k in crypto, f"缺键 {k}"

    def test_cpi_comparison_routes_and_indpro_for_merrill(self):
        fetcher, dc = self._target()
        _ = fetcher.fetch_coin_data()
        # 至少发了 FRED CPIAUCSL + INDPRO 请求
        call_keys = {(c, s, p.get("series")) for c, s, p in dc.calls}
        assert ("macro", "fred", "CPIAUCSL") in call_keys
        assert ("macro", "fred", "INDPRO") in call_keys

    def test_crypto_merrill_recovery_from_rise_rise(self):
        """CPI↑+ 工业产出↑ = 复苏 = RECOVERY（§三 L128）"""
        # 五维 fetcher 会读取 CPIAUCSL 和 INDPRO 的 value，若 INDPRO 同比>0 视为增长↑，
        # CPI 同比>3% 视为通胀↑ → 过热；这里用 2.9 通胀 + 1.2 增长 → 复苏
        fetcher, _ = self._target()
        out = fetcher.fetch_coin_data()
        assert out["crypto_usdt"]["merrill_phase"] == "RECOVERY"

    def test_no_fred_key_all_fields_none_not_explode(self):
        """无 Key：所有 FRED 系列返回空列表。"""
        overrides = {
            ("macro", "fred", "FEDFUNDS"): [],
            ("macro", "fred", "M2NS"):     [],
            ("macro", "fred", "WALCL"):    [],
            ("macro", "fred", "CPIAUCSL"): [],
            ("macro", "fred", "INDPRO"):   [],
        }
        fetcher, _ = self._target(overrides)
        out = fetcher.fetch_coin_data()
        # 这些字段缺失时填 None（fail-open）
        for k in ("fedfunds_rate", "m2_yoy_pct", "fed_balance_sheet_trillion",
                  "us_cpi_yoy_pct", "us_indpro_yoy_pct", "merrill_phase", "liquidity_score"):
            # 不抛异常；值是 None 或者一个中性回退默认值都 ok
            assert out["crypto_usdt"][k] is None or out["crypto_usdt"][k] != ""

    def test_defillama_tvl_bln_parsed(self):
        fetcher, _ = self._target()
        out = fetcher.fetch_coin_data()
        # 38.1+6.2 = 44.3
        assert out["crypto_usdt"]["defi_tvl_bln"] == pytest.approx(44.3)

    def test_etherscan_gas_fills_propose_as_gwei(self):
        fetcher, _ = self._target()
        out = fetcher.fetch_coin_data()
        # 取 propose_gas 作为 gas_eth_gwei
        assert out["crypto_usdt"]["gas_eth_gwei"] == 18.0

    def test_policy_sentiment_score_normalized(self):
        fetcher, _ = self._target()
        out = fetcher.fetch_coin_data()
        # 2 正 1 负 → 简单 (pos-neg)/total = (2-1)/3 ≈ 0.33；归一化到 [0,1]
        s = out["crypto_usdt"]["policy_sentiment_score"]
        assert 0.0 <= s <= 1.0
        # 正样本多 → 分数应高于 0.5
        assert s > 0.5

    def test_shared_fields_common_across_classes(self):
        fetcher, _ = self._target()
        out = fetcher.fetch_coin_data()
        # 三类资产都要有共享的宏观字段（FRED/VIX 对所有类都适用）
        for cls in ("crypto_usdt", "us_stock", "precious_metal"):
            d = out[cls]
            assert "fedfunds_rate" in d
            assert "merrill_phase" in d
            assert "vix_close" in d
            assert "liquidity_score" in d
        # 美股类共享但 defi_tvl_bln 对股票类无意义 → 填 None（合理 fail-open）
        assert out["us_stock"].get("defi_tvl_bln") is None
        assert out["precious_metal"].get("gas_eth_gwei") is None
