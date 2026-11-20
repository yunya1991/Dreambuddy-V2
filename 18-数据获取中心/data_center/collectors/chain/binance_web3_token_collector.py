"""币安 Web3 单币画像采集器 — query-token-info + query-token-audit 的可用端点。

路由：
  - watchlist：先取 unified 趋势榜 top N，再逐币拉「动态行情 + 安全审计」
  - token：显式传入 [{chain_id, contract_address, symbol}] 逐币拉取

产出（每币两条）：
  - web3_token_profile_<symbol>：真实持有人结构 / 流通量 / FDV / 多周期量价
  - web3_token_audit_<symbol>：风险等级 / 买卖税 / 风险命中项

设计要点：
  - FAIL-OPEN：单币失败不影响其他币；网络异常 → 空列表
  - audit 需 UUID requestId + source: agent 头
  - audit 仅在 hasResult && isSupported 时才写入风险结论字段
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

_API_BASE = "https://web3.binance.com/bapi/defi"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DataBuddy/1.0)",
    "Accept-Encoding": "identity",
}
_HEADERS_JSON = {**_HEADERS, "Content-Type": "application/json", "source": "agent"}
_MAX_RETRIES = 3
_RETRY_SLEEP_SEC = 0.8

_PROFILE_FIELDS = (
    ("price", "price"),
    ("marketCap", "market_cap"),
    ("fdv", "fdv"),
    ("totalSupply", "total_supply"),
    ("circulatingSupply", "circulating_supply"),
    ("liquidity", "liquidity"),
    ("holders", "holders"),
    ("top10HoldersPercentage", "top10_holders_pct"),
    ("kycHolderCount", "kyc_holders"),
    ("kolHolders", "kol_holders"),
    ("proHolders", "pro_holders"),
    ("smartMoneyHolders", "smart_money_holders"),
    ("smartMoneyHoldingPercent", "smart_money_pct"),
    ("volume24h", "volume_24h"),
    ("volume24hBuy", "volume_24h_buy"),
    ("volume24hSell", "volume_24h_sell"),
    ("count24h", "tx_count_24h"),
    ("percentChange1h", "price_change_1h"),
    ("percentChange4h", "price_change_4h"),
    ("percentChange24h", "price_change_24h"),
    ("priceHigh24h", "price_high_24h"),
    ("priceLow24h", "price_low_24h"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _token_key(symbol: str, address: str) -> str:
    """sub_category 币种键：symbol + 合约地址尾 4 位（同名不同合约防撞）。"""
    sym = str(symbol or "").lower()
    addr = str(address or "").lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    return f"{sym}_{addr[-8:]}" if addr else sym


def _f(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("%", "")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _put(metrics: dict, key: str, value: float | None) -> None:
    if value is not None:
        metrics[key] = value


def _request(method: str, url: str, *, params: dict | None = None, json_body: dict | None = None):
    for attempt in range(_MAX_RETRIES):
        try:
            if method == "POST":
                resp = requests.post(url, json=json_body, headers=_HEADERS_JSON, timeout=12)
            else:
                resp = requests.get(url, params=params, headers=_HEADERS, timeout=12)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict) or str(payload.get("code")) != "000000":
                return None
            return payload.get("data")
        except Exception:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_SLEEP_SEC)
    return None


class BinanceWeb3TokenCollector(BaseCollector):
    """币安 Web3 单币画像 + 安全审计采集器。"""

    source = "binance_web3_token"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 公开接口，无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        route = params.get("route", "watchlist")
        chain_id = str(params.get("chain_id", "56"))
        ts = _now_iso()

        if route == "watchlist":
            tokens = self._fetch_watchlist(chain_id, int(params.get("limit", 10)))
        elif route == "token":
            tokens = [t for t in (params.get("tokens") or []) if isinstance(t, dict)]
        else:
            return []

        recs: list[DataRecord] = []
        for tok in tokens:
            addr = str(tok.get("contract_address") or tok.get("contractAddress") or "").strip()
            if not addr:
                continue
            tok_chain = str(tok.get("chain_id") or tok.get("chainId") or chain_id)
            symbol = str(tok.get("symbol") or addr[:8]).strip()
            profile = self._fetch_profile(tok_chain, addr, symbol, ts)
            if profile is not None:
                recs.append(profile)
            audit = self._fetch_audit(tok_chain, addr, symbol, ts)
            if audit is not None:
                recs.append(audit)
        return recs

    # ------------------------------------------------------------------
    def _fetch_watchlist(self, chain_id: str, limit: int) -> list[dict]:
        data = _request(
            "POST",
            f"{_API_BASE}/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list",
            json_body={
                "rankType": 10,
                "chainId": chain_id,
                "period": 50,
                "sortBy": 70,
                "orderAsc": False,
                "page": 1,
                "size": limit,
            },
        )
        out: list[dict] = []
        for tok in (data or {}).get("tokens") or []:
            if not isinstance(tok, dict):
                continue
            addr = tok.get("contractAddress")
            symbol = tok.get("symbol")
            if not addr or not symbol:
                continue
            out.append(
                {
                    "chain_id": str(tok.get("chainId") or chain_id),
                    "contract_address": addr,
                    "symbol": symbol,
                }
            )
        return out

    def _fetch_profile(
        self, chain_id: str, contract_address: str, symbol: str, ts: str
    ) -> DataRecord | None:
        data = _request(
            "GET",
            f"{_API_BASE}/v4/public/wallet-direct/buw/wallet/market/token/dynamic/info",
            params={"chainId": chain_id, "contractAddress": contract_address},
        )
        if not isinstance(data, dict):
            return None

        metrics: dict[str, Any] = {"symbol": symbol}
        for src_key, dst_key in _PROFILE_FIELDS:
            _put(metrics, dst_key, _f(data.get(src_key)))
        launch = _f(data.get("launchTime"))
        if launch is not None:
            metrics["launch_time_ms"] = launch

        rec = DataRecord(
            source=self.source,
            category=self.category,
            sub_category=f"web3_token_profile_{_token_key(symbol, contract_address)}",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={
                "symbol": symbol,
                "chainId": chain_id,
                "contractAddress": contract_address,
                "devHoldingPercent": data.get("devHoldingPercent"),
                "kolHoldingPercent": data.get("kolHoldingPercent"),
                "proHoldingPercent": data.get("proHoldingPercent"),
                "launchTime": data.get("launchTime"),
            },
        )
        validate_record(rec)
        return rec

    def _fetch_audit(
        self, chain_id: str, contract_address: str, symbol: str, ts: str
    ) -> DataRecord | None:
        data = _request(
            "POST",
            f"{_API_BASE}/v1/public/wallet-direct/security/token/audit",
            json_body={
                "binanceChainId": chain_id,
                "contractAddress": contract_address,
                "requestId": str(uuid.uuid4()),
            },
        )
        if not isinstance(data, dict):
            return None

        has_result = bool(data.get("hasResult"))
        is_supported = bool(data.get("isSupported"))
        metrics: dict[str, Any] = {
            "symbol": symbol,
            "has_result": 1 if has_result else 0,
            "is_supported": 1 if is_supported else 0,
        }

        # 仅在审计结果有效时写入结论字段（对齐 SKILL 文档约束）
        if has_result and is_supported:
            _put(metrics, "risk_level", _f(data.get("riskLevel")))
            extra = data.get("extraInfo") or {}
            if isinstance(extra, dict):
                _put(metrics, "buy_tax", _f(extra.get("buyTax")))
                _put(metrics, "sell_tax", _f(extra.get("sellTax")))
                verified = extra.get("isVerified")
                if isinstance(verified, bool):
                    metrics["is_verified"] = 1 if verified else 0
            risk_hits = caution_hits = 0
            for group in data.get("riskItems") or []:
                if not isinstance(group, dict):
                    continue
                for item in group.get("details") or []:
                    if not isinstance(item, dict) or not item.get("isHit"):
                        continue
                    if item.get("riskType") == "RISK":
                        risk_hits += 1
                    elif item.get("riskType") == "CAUTION":
                        caution_hits += 1
            metrics["risk_hits"] = risk_hits
            metrics["caution_hits"] = caution_hits

        rec = DataRecord(
            source=self.source,
            category=self.category,
            sub_category=f"web3_token_audit_{_token_key(symbol, contract_address)}",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[],
            raw={
                "symbol": symbol,
                "chainId": chain_id,
                "contractAddress": contract_address,
                "riskLevelEnum": data.get("riskLevelEnum"),
                "extraInfo": data.get("extraInfo"),
                "riskItems": data.get("riskItems"),
            },
        )
        validate_record(rec)
        return rec
