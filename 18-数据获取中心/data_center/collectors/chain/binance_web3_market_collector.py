"""币安 Web3 市场榜采集器 — 公开 bapi（无需 Key）。

覆盖 crypto-market-rank 技能中实测可用的 5 个端点：
  - unified/rank/list          → 趋势榜/搜索榜/Alpha 榜（含持仓结构与审计摘要）
  - social/hype/leaderboard    → 社交热度榜（含情绪与 AI 摘要）
  - pulse/exclusive/rank/list  → memecoin 算法评分榜
  - tracker/.../inflow/rank    → 聪明钱净流入榜
  - social-rush/rank/list      → 叙事热点（Topic Rush）

设计要点：
  - 全部 FAIL-OPEN：网络异常/非 000000 返回 → 跳过该路，不抛错
  - 每个代币一条 DataRecord，sub_category 带 symbol（对齐 coingecko 的 per-asset 约定），
    便于 18→19 回填后形成单币时间序列
  - metrics 仅扁平 number/string；raw 精简（剔除 chart1m~chart24h 等大字段）
  - 连续调用实测会出现 SSL EOF，故统一 3 次重试
"""

from __future__ import annotations

import logging
import time
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
_HEADERS_JSON = {**_HEADERS, "Content-Type": "application/json"}
_MAX_RETRIES = 3
_RETRY_SLEEP_SEC = 0.8
# bapi 对短时突发请求敏感：同一进程内串行请求强制最小间隔，避免 429 空返回
_MIN_REQUEST_GAP_SEC = 0.6
_last_request_at = 0.0
_log = logging.getLogger(__name__)

_RANK_TYPES = {10: "trending", 11: "top_search", 20: "alpha", 40: "stock"}
_RANK_METRIC_FIELDS = (
    ("price", "price"),
    ("marketCap", "market_cap"),
    ("volume24h", "volume_24h"),
    ("volume24hBuy", "volume_24h_buy"),
    ("volume24hSell", "volume_24h_sell"),
    ("liquidity", "liquidity"),
    ("holders", "holders"),
    ("holdersTop10Percent", "top10_holders_pct"),
    ("devHoldingPercent", "dev_holding_pct"),
    ("sniperHoldersPercent", "sniper_holding_pct"),
    ("insiderHoldingPercent", "insider_holding_pct"),
    ("bundlesHoldingPercent", "bundler_holding_pct"),
    ("newAddressHoldersPercent", "new_wallet_pct"),
    ("smartMoneyHoldingPercent", "smart_money_pct"),
    ("kolHoldingPercent", "kol_pct"),
    ("proHoldersPercent", "pro_pct"),
    ("kycHolders", "kyc_holders"),
    ("searchCount24h", "search_count_24h"),
    ("percentChange24h", "price_change_24h"),
    ("uniqueTrader24h", "unique_trader_24h"),
    ("count24h", "tx_count_24h"),
)
_SENTIMENT_SCORE = {"Positive": 1.0, "Neutral": 0.0, "Negative": -1.0}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _token_key(symbol: str, address: Any) -> str:
    """sub_category 的币种键：symbol + 合约地址尾 4 位。

    同一批数据里存在同名不同合约的代币（如多个 PEPE），
    而 chain 的 stable_id 是 symbol|分钟桶，若 sub_category 只含 symbol
    会触发 DUPLICATE_DETECTED 导致整批被质量门禁拦截。
    """
    sym = symbol.lower()
    addr = str(address or "").lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    return f"{sym}_{addr[-8:]}" if addr else sym


def _f(v: Any) -> float | None:
    """宽松数值解析：兼容字符串/千分位/空值。"""
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


def _throttle() -> None:
    """进程内串行最小间隔（防止 bapi 突发限流导致空返回）。"""
    global _last_request_at
    if _MIN_REQUEST_GAP_SEC > 0:
        wait = _MIN_REQUEST_GAP_SEC - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
    _last_request_at = time.monotonic()


def _request(method: str, url: str, *, params: dict | None = None, json_body: dict | None = None):
    """带重试的请求，返回 data 字段；失败返回 None（FAIL-OPEN）。"""
    last_error: str | None = None
    for attempt in range(_MAX_RETRIES):
        _throttle()
        try:
            if method == "POST":
                resp = requests.post(url, json=json_body, headers=_HEADERS_JSON, timeout=12)
            else:
                resp = requests.get(url, params=params, headers=_HEADERS, timeout=12)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict) or str(payload.get("code")) != "000000":
                code = payload.get("code") if isinstance(payload, dict) else None
                last_error = f"code={code}"
            else:
                return payload.get("data")
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_RETRY_SLEEP_SEC)
    _log.warning("binance_web3 请求失败 url=%s err=%s", url, last_error)
    return None


class BinanceWeb3MarketCollector(BaseCollector):
    """币安 Web3 榜单采集器（趋势/社交/聪明钱/meme/叙事）。"""

    source = "binance_web3_market"
    category = "chain"

    def is_available(self) -> bool:
        return True  # 公开接口，无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        route = params.get("route", "rank")
        chain_id = str(params.get("chain_id", "56"))
        ts = _now_iso()

        if route == "rank":
            rank_types = params.get("rank_types") or [10]
            size = int(params.get("size", 30))
            recs: list[DataRecord] = []
            for rt in rank_types:
                recs.extend(self._fetch_rank(chain_id, int(rt), size, ts))
            return recs
        if route == "social_hype":
            return self._fetch_social_hype(chain_id, ts)
        if route == "meme_rank":
            return self._fetch_meme_rank(chain_id, ts)
        if route == "smart_money":
            return self._fetch_smart_money(chain_id, str(params.get("period", "24h")), ts)
        if route == "narrative":
            return self._fetch_narrative(
                chain_id,
                int(params.get("rank_type", 30)),
                int(params.get("sort", 30)),
                ts,
            )
        return []

    # ------------------------------------------------------------------
    # 各路子实现
    # ------------------------------------------------------------------
    def _fetch_rank(self, chain_id: str, rank_type: int, size: int, ts: str) -> list[DataRecord]:
        data = _request(
            "POST",
            f"{_API_BASE}/v1/public/wallet-direct/buw/wallet/market/token/pulse/unified/rank/list",
            json_body={
                "rankType": rank_type,
                "chainId": chain_id,
                "period": 50,
                "sortBy": 70,
                "orderAsc": False,
                "page": 1,
                "size": size,
            },
        )
        tokens = (data or {}).get("tokens") or []
        name = _RANK_TYPES.get(rank_type, f"rank{rank_type}")
        recs: list[DataRecord] = []
        for tok in tokens:
            if not isinstance(tok, dict):
                continue
            symbol = str(tok.get("symbol") or "").strip()
            if not symbol:
                continue
            metrics: dict[str, Any] = {"symbol": symbol}
            for src_key, dst_key in _RANK_METRIC_FIELDS:
                _put(metrics, dst_key, _f(tok.get(src_key)))
            launch_ms = _f(tok.get("launchTime"))
            _put(metrics, "launch_time_ms", launch_ms)
            audit = tok.get("auditInfo") or {}
            if isinstance(audit, dict):
                _put(metrics, "risk_level", _f(audit.get("riskLevel")))
                _put(metrics, "risk_num", _f(audit.get("riskNum")))
                _put(metrics, "caution_num", _f(audit.get("cautionNum")))
                extra = audit.get("extra") or {}
                if isinstance(extra, dict):
                    _put(metrics, "buy_tax", _f(extra.get("buyTax")))
                    _put(metrics, "sell_tax", _f(extra.get("sellTax")))
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=f"web3_{name}_{_token_key(symbol, tok.get('contractAddress'))}",
                timestamp=ts,
                metrics=metrics,
                events=[],
                timeseries=[],
                raw={
                    "symbol": symbol,
                    "name": (tok.get("metaInfo") or {}).get("name"),
                    "chainId": tok.get("chainId"),
                    "contractAddress": tok.get("contractAddress"),
                    "launchTime": tok.get("launchTime"),
                    "links": tok.get("links"),
                    "auditInfo": audit,
                    "alphaInfo": tok.get("alphaInfo"),
                    "tokenTag": tok.get("tokenTag"),
                    "stockCompanyName": tok.get("stockCompanyName"),
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs

    def _fetch_social_hype(self, chain_id: str, ts: str) -> list[DataRecord]:
        data = _request(
            "GET",
            f"{_API_BASE}/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard",
            params={
                "chainId": chain_id,
                "sentiment": "All",
                "socialLanguage": "ALL",
                "targetLanguage": "zh",
                "timeRange": "1",
            },
        )
        rows = (data or {}).get("leaderBoardList") or []
        recs: list[DataRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            meta = row.get("metaInfo") or {}
            market = row.get("marketInfo") or {}
            hype = row.get("socialHypeInfo") or {}
            symbol = str(meta.get("symbol") or "").strip()
            if not symbol:
                continue
            metrics: dict[str, Any] = {"symbol": symbol}
            _put(metrics, "social_hype", _f(hype.get("socialHype")))
            _put(metrics, "social_hype_cn", _f(hype.get("socialHypeCn")))
            _put(metrics, "social_hype_en", _f(hype.get("socialHypeEn")))
            _put(metrics, "market_cap", _f(market.get("marketCap")))
            _put(metrics, "price_change_24h", _f(market.get("priceChange")))
            _put(metrics, "token_age_ms", _f(meta.get("tokenAge")))
            sentiment = str(hype.get("sentiment") or "")
            score = _SENTIMENT_SCORE.get(sentiment)
            if score is not None:
                metrics["sentiment_score"] = score
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=f"web3_social_hype_{_token_key(symbol, meta.get('contractAddress'))}",
                timestamp=ts,
                metrics=metrics,
                events=[],
                timeseries=[],
                raw={
                    "symbol": symbol,
                    "chainId": meta.get("chainId"),
                    "contractAddress": meta.get("contractAddress"),
                    "sentiment": sentiment,
                    "social_summary": hype.get("socialSummaryBrief"),
                    "social_summary_cn": hype.get("socialSummaryBriefTranslated")
                    or hype.get("socialSummaryBrief"),
                    "tagInfoList": row.get("tagInfoList"),
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs

    def _fetch_meme_rank(self, chain_id: str, ts: str) -> list[DataRecord]:
        data = _request(
            "GET",
            f"{_API_BASE}/v1/public/wallet-direct/buw/wallet/market/token/pulse/exclusive/rank/list",
            params={"chainId": chain_id},
        )
        rows = (data or {}).get("tokens") or []
        recs: list[DataRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            meta = row.get("metaInfo") or {}
            metrics: dict[str, Any] = {"symbol": symbol}
            for src_key, dst_key in (
                ("score", "score"),
                ("rank", "rank"),
                ("price", "price"),
                ("percentChange", "price_change_24h"),
                ("percentChange7d", "price_change_7d"),
                ("marketCap", "market_cap"),
                ("liquidity", "liquidity"),
                ("volume", "volume_24h"),
                ("volumeBn7d", "volume_bn_7d"),
                ("holders", "holders"),
                ("kycHolders", "kyc_holders"),
                ("bnUniqueHolders", "bn_unique_holders"),
                ("holdersTop10Percent", "top10_holders_pct"),
                ("count", "tx_count"),
                ("countBn7d", "tx_count_bn_7d"),
                ("uniqueTraderBn", "unique_trader_bn"),
                ("impression", "impression"),
                ("alphaStatus", "alpha_status"),
            ):
                _put(metrics, dst_key, _f(row.get(src_key)))
            if isinstance(meta, dict):
                flag = _f(meta.get("aiNarrativeFlag"))
                if flag is not None:
                    metrics["ai_narrative_flag"] = flag
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=f"web3_meme_rank_{_token_key(symbol, row.get('contractAddress'))}",
                timestamp=ts,
                metrics=metrics,
                events=[],
                timeseries=[],
                raw={
                    "symbol": symbol,
                    "name": meta.get("name") if isinstance(meta, dict) else None,
                    "chainId": row.get("chainId"),
                    "contractAddress": row.get("contractAddress"),
                    "createTime": row.get("createTime"),
                    "migrateTime": row.get("migrateTime"),
                    "previewLink": row.get("previewLink"),
                    "tokenTag": row.get("tokenTag"),
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs

    def _fetch_smart_money(self, chain_id: str, period: str, ts: str) -> list[DataRecord]:
        data = _request(
            "POST",
            f"{_API_BASE}/v1/public/wallet-direct/tracker/wallet/token/inflow/rank/query",
            json_body={"chainId": chain_id, "period": period, "tagType": 2},
        )
        rows = data if isinstance(data, list) else []
        recs: list[DataRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or row.get("tokenName") or "").strip()
            if not symbol:
                continue
            metrics: dict[str, Any] = {"symbol": symbol}
            for src_key, dst_key in (
                ("price", "price"),
                ("priceChangeRate", "price_change_pct"),
                ("marketCap", "market_cap"),
                ("volume", "volume_24h"),
                ("liquidity", "liquidity"),
                ("holders", "holders"),
                ("holdersTop10Percent", "top10_holders_pct"),
                ("count", "tx_count"),
                ("countBuy", "tx_count_buy"),
                ("countSell", "tx_count_sell"),
                ("inflow", "inflow_usd"),
                ("traders", "smart_traders"),
                ("tokenRiskLevel", "risk_level"),
            ):
                _put(metrics, dst_key, _f(row.get(src_key)))
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=f"web3_smart_money_{_token_key(symbol, row.get('ca'))}",
                timestamp=ts,
                metrics=metrics,
                events=[],
                timeseries=[],
                raw={
                    "symbol": symbol,
                    "name": row.get("tokenName"),
                    "chainId": chain_id,
                    "contractAddress": row.get("ca"),
                    "period": period,
                    "link": row.get("link"),
                    "tokenTag": row.get("tokenTag"),
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs

    def _fetch_narrative(
        self, chain_id: str, rank_type: int, sort: int, ts: str
    ) -> list[DataRecord]:
        data = _request(
            "GET",
            f"{_API_BASE}/v1/public/wallet-direct/buw/wallet/market/token/social-rush/rank/list",
            params={
                "chainId": chain_id,
                "rankType": rank_type,
                "sort": sort,
                "asc": "false",
            },
        )
        rows = data if isinstance(data, list) else []
        recs: list[DataRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            topic_id = str(row.get("topicId") or "").strip()
            if not topic_id:
                continue
            name = row.get("name") or {}
            if not isinstance(name, dict):
                name = {}
            metrics: dict[str, Any] = {
                "topic_id": topic_id,
                "topic_name": str(name.get("topicNameCn") or name.get("topicNameEn") or ""),
            }
            for src_key, dst_key in (
                ("topicNetInflow", "net_inflow_usd"),
                ("topicNetInflow1h", "net_inflow_1h_usd"),
                ("topicNetInflowAth", "net_inflow_ath_usd"),
                ("tokenSize", "token_size"),
                ("progress", "progress"),
            ):
                _put(metrics, dst_key, _f(row.get(src_key)))
            tokens = []
            for tok in row.get("tokenList") or []:
                if not isinstance(tok, dict):
                    continue
                tokens.append(
                    {
                        "symbol": tok.get("symbol"),
                        "contractAddress": tok.get("contractAddress"),
                        "marketCap": tok.get("marketCap"),
                        "netInflow": tok.get("netInflow"),
                        "smartMoneyHolders": tok.get("smartMoneyHolders"),
                        "kolHolders": tok.get("kolHolders"),
                        "holders": tok.get("holders"),
                        "priceChange24h": tok.get("priceChange24h"),
                    }
                )
            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=f"web3_narrative_{topic_id[:8]}",
                timestamp=ts,
                metrics=metrics,
                events=[],
                timeseries=[],
                raw={
                    "topic_id": topic_id,
                    "name_cn": name.get("topicNameCn"),
                    "name_en": name.get("topicNameEn"),
                    "type": row.get("type"),
                    "topicLink": row.get("topicLink"),
                    "createTime": row.get("createTime"),
                    "viralTime": row.get("viralTime"),
                    "aiSummary": row.get("aiSummary"),
                    "topicTags": row.get("topicTags"),
                    "tokens": tokens,
                },
            )
            validate_record(rec)
            recs.append(rec)
        return recs
