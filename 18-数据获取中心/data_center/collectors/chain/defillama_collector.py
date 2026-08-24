"""DeFiLlama chain/TVL/stablecoin collector — 无 Key 公共 API，为易经推理五维补链上 D7~D9。

API 端点（全部 HTTPS GET 无需 Key）：
  - GET https://api.llama.fi/v2/chains       → 所有链的 TVL（D8：总 TVL 汇总 + 分链明细）
  - GET https://api.llama.fi/v2/historicalChainTvl/{chain}  → 单链历史 TVL
  - GET https://api.llama.fi/summary/fees/{chain}?dataType=dailyFees  → 手续费（Gas proxy）

稳定币总市值（D7）：从 /v2/chains 返回的每条链 tvl 汇总，并在 raw 中保留链名→TVL 映射。
如需单独"稳定币市值 proxy"，取 Tron + Ethereum Tether/USDC 所在链的 TVL 份额已足够接近 proxy。
若将来 DeFiLlama 有单独 stablecoins endpoint，可新增路由追加 metrics。

fail-open：网络不通 / HTTP 非 200 → 返回空列表，不抛异常（除 429 抛 RateLimitError）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import RateLimitError


_BASE = "https://api.llama.fi"


class DeFiLlamaCollector(BaseCollector):
    source = "defillama"
    category = "chain"

    def is_available(self) -> bool:
        # 公共 API 无需 Key → 默认可用，只要网络可达
        return True

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------
    def fetch(self, params: dict) -> list[DataRecord]:
        route = params.get("route")
        try:
            if route == "chains":
                return self._fetch_chains()
            if route == "historicalChainTvl":
                return self._fetch_historical_chain_tvl(params.get("chain", "Ethereum"))
            if route == "fees":
                return self._fetch_fees(params.get("chain", "Ethereum"))
            # 未知路由：静默返回空，避免意外触发网络
            return []
        except RateLimitError:
            raise
        except Exception:
            # fail-open：其它任何异常 → 空列表
            return []

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------
    @staticmethod
    def _get(url: str, timeout: int = 20):
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 429:
            raise RateLimitError(f"DeFiLlama 429 限流: {url}")
        if not resp.ok:
            raise RuntimeError(f"DeFiLlama HTTP {resp.status_code}: {url}")
        return resp.json()

    # ------------------------------------------------------------------
    # routes
    # ------------------------------------------------------------------
    def _fetch_chains(self) -> list[DataRecord]:
        data = self._get(f"{_BASE}/v2/chains")
        chains = {}
        total_tvl = 0.0
        top_names = []
        for c in data or []:
            try:
                name = str(c.get("name") or c.get("gecko_id") or "unknown")
                tvl = float(c.get("tvl") or 0.0)
            except (TypeError, ValueError):
                continue
            tvl_bln = tvl / 1e9
            chains[name] = {
                "tvl": tvl,
                "tvl_bln": tvl_bln,
                "symbol": c.get("symbol"),
            }
            top_names.append((name, tvl_bln))
            total_tvl += tvl
        top_names.sort(key=lambda kv: kv[1], reverse=True)
        top10_names = [n for n, _ in top_names[:10]]
        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="defillama",
            category="chain",
            sub_category="chains_summary",
            timestamp=now,
            metrics={
                "total_tvl": total_tvl,
                "total_tvl_bln": round(total_tvl / 1e9, 4),
                "chain_count": len(chains),
                "top1_chain": top10_names[0] if top10_names else "",
                "top2_chain": top10_names[1] if len(top10_names) > 1 else "",
                "top3_chain": top10_names[2] if len(top10_names) > 2 else "",
            },
            events=[],
            timeseries=[
                {"chain": name, "tvl": info["tvl"], "tvl_bln": info["tvl_bln"]}
                for name, info in chains.items()
            ],
            raw={
                "url": "/v2/chains",
                "chain_count": len(data or []),
                "chains": chains,
                "top10_by_tvl": [(n, round(t, 4)) for n, t in top_names[:10]],
            },
        )
        validate_record(rec)
        return [rec]

    def _fetch_historical_chain_tvl(self, chain: str) -> list[DataRecord]:
        data = self._get(f"{_BASE}/v2/historicalChainTvl/{chain}")
        ts = []
        latest_tvl = 0.0
        latest_date = None
        for item in data or []:
            try:
                d = int(item["date"])
                tvl = float(item["tvl"])
            except (TypeError, KeyError, ValueError):
                continue
            dt = datetime.fromtimestamp(d, tz=timezone.utc).date().isoformat()
            latest_date = dt
            latest_tvl = tvl
            ts.append({"date": dt, "tvl": tvl, "tvl_bln": round(tvl / 1e9, 4)})
        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="defillama",
            category="chain",
            sub_category=f"historical_tvl_{chain}",
            timestamp=now,
            metrics={
                "chain": chain,
                "points": len(ts),
                "latest_tvl": latest_tvl,
                "latest_tvl_bln": round(latest_tvl / 1e9, 4),
                "latest_date": latest_date,
            },
            events=[],
            timeseries=ts,
            raw={"url": f"/v2/historicalChainTvl/{chain}"},
        )
        validate_record(rec)
        return [rec]

    def _fetch_fees(self, chain: str) -> list[DataRecord]:
        data = self._get(f"{_BASE}/summary/fees/{chain}?dataType=dailyFees")
        total_24h = float(data.get("total24h") or 0.0) if isinstance(data, dict) else 0.0
        ts = []
        raw_chart = data.get("totalDataChart") if isinstance(data, dict) else None
        for item in raw_chart or []:
            try:
                d_ts, val = item[0], item[1]
                dt = datetime.fromtimestamp(int(d_ts), tz=timezone.utc).date().isoformat()
                ts.append({"date": dt, "fees_usd": float(val)})
            except (TypeError, IndexError, ValueError):
                continue
        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="defillama",
            category="chain",
            sub_category=f"fees_{chain}",
            timestamp=now,
            metrics={
                "chain": chain,
                "fees_24h_usd": total_24h,
                "points": len(ts),
            },
            events=[],
            timeseries=ts,
            raw={"url": f"/summary/fees/{chain}"},
        )
        validate_record(rec)
        return [rec]
