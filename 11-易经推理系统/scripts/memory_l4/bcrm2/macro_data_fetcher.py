"""MacroDataFetcher — 宏观数据历史采集器 + SQLite 缓存 + 时间对齐

P1 核心组件：为回测和实盘提供统一的宏观数据入口。

设计原则:
1. 无 Mock 兜底 — 采集失败返回 None，不伪造数据
2. 时间对齐严格 — lookahead_guard ≥ 1 根 K 线，避免未来函数
3. SQLite 缓存 — 回测可重复，避免重复请求 API
4. 复用 free_fundamental_provider 的采集模式

数据源（支持历史查询的）:
  1. alternative.me FGI — 每日，limit=365
  2. OKX 资金费率历史 — 8h 间隔，分页获取
  3. DefiLlama 稳定币 — 每日，全量历史
  4. DefiLlama TVL — 每日，全量历史
  5. CoinGecko market_chart — 每日，days=365
  6. Blockchain.info hash_rate — 每日，timespan=1year

数据源（仅实时，回测中返回 missing）:
  7. 币安 Web3 Social Hype — 仅当前排行榜
  8. 币安 Web3 Smart Money — 仅当前信号
"""
from __future__ import annotations

import sqlite3
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ============================================================
# symbol 映射表
# ============================================================
_COINGECKO_ID_MAP = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "DOGE": "dogecoin", "ADA": "cardano", "AVAX": "avalanche-2",
    "LINK": "chainlink", "DOT": "polkadot", "LTC": "litecoin", "ARB": "arbitrum",
    "OP": "optimism", "UNI": "uniswap", "SUI": "sui", "SEI": "sei-network",
    "TON": "the-open-network", "OKB": "okb", "HYPE": "hyperliquid",
}

_OKX_INST_MAP = {
    "BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP", "SOL": "SOL-USDT-SWAP",
    "BNB": "BNB-USDT-SWAP", "XRP": "XRP-USDT-SWAP", "DOGE": "DOGE-USDT-SWAP",
    "ADA": "ADA-USDT-SWAP", "AVAX": "AVAX-USDT-SWAP", "LINK": "LINK-USDT-SWAP",
    "DOT": "DOT-USDT-SWAP", "UNI": "UNI-USDT-SWAP", "ARB": "ARB-USDT-SWAP",
    "OP": "OP-USDT-SWAP", "LTC": "LTC-USDT-SWAP",
}

_LLAMA_CHAIN_MAP = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "BNB": "BSC",
    "AVAX": "Avalanche", "ARB": "Arbitrum", "OP": "Optimism", "DOT": "Polkadot",
    "MATIC": "Polygon", "LTC": "Litecoin", "XRP": "XRP", "DOGE": "Dogecoin",
    "ADA": "Cardano", "SUI": "Sui", "TON": "Toncoin", "UNI": "Ethereum",
}


class MacroDataFetcher:
    """宏观数据历史采集器

    用法（回测）:
        fetcher = MacroDataFetcher()
        macro_df = fetcher.fetch_all("BTC", kline_index=df.index)
        # macro_df 已对齐到 df.index，可直接传给 FeatureRegistry

    用法（实盘）:
        fetcher = MacroDataFetcher()
        macro_df = fetcher.fetch_all("BTC", kline_index=df.index, live=True)
    """

    # 类级内存缓存：{symbol: combined_raw_df}，避免贝叶斯优化时重复拉 API
    _raw_cache: Dict[str, pd.DataFrame] = {}

    def __init__(self, cache_dir: Optional[Path] = None, timeout: int = 10):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "DreamBuddy-MacroFetcher/1.0",
            "Accept": "application/json",
        })
        self.timeout = timeout

        if cache_dir is None:
            cache_dir = Path(__file__).resolve().parents[3] / "data" / "macro_cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # HTTP 辅助
    # ============================================================

    def _get(self, url: str, params=None) -> Optional[Any]:
        try:
            r = self._session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"MacroDataFetcher GET 失败 [{url}]: {e}")
            return None

    def _post_json(self, url: str, payload: dict) -> Optional[Any]:
        try:
            r = self._session.post(url, json=payload, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"MacroDataFetcher POST 失败 [{url}]: {e}")
            return None

    # ============================================================
    # SQLite 缓存
    # ============================================================

    def _cache_path(self, symbol: str) -> Path:
        return self.cache_dir / f"macro_{symbol.upper()}.db"

    def _load_cache(self, symbol: str, source: str) -> Optional[pd.DataFrame]:
        """从 SQLite 加载缓存"""
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        try:
            conn = sqlite3.connect(str(path))
            df = pd.read_sql(
                f"SELECT * FROM {source} ORDER BY timestamp", conn
            )
            conn.close()
            if df.empty:
                return None
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            df = df.set_index("timestamp")
            return df
        except Exception:
            return None

    def _save_cache(self, symbol: str, source: str, df: pd.DataFrame) -> None:
        """保存到 SQLite 缓存"""
        if df.empty:
            return
        path = self._cache_path(symbol)
        try:
            conn = sqlite3.connect(str(path))
            df_to_save = df.copy()
            df_to_save = df_to_save.reset_index()
            df_to_save["timestamp"] = df_to_save["timestamp"].astype(np.int64) // 10**9
            df_to_save.to_sql(source, conn, if_exists="replace", index=False)
            conn.close()
        except Exception as e:
            logger.warning(f"缓存保存失败 [{symbol}/{source}]: {e}")

    # ============================================================
    # 各数据源历史采集
    # ============================================================

    def fetch_fgi_history(self, limit: int = 365) -> pd.DataFrame:
        """alternative.me Fear & Greed Index — 每日历史

        返回 DataFrame: index=timestamp(UTC), columns=[fear_greed_index]
        """
        data = self._get("https://api.alternative.me/fng/", params={"limit": str(limit)})
        if not data or not data.get("data"):
            return pd.DataFrame()

        rows = []
        for item in data["data"]:
            ts = int(item.get("timestamp", 0))
            val = int(item.get("value", 50))
            rows.append({"timestamp": ts, "fear_greed_index": val})

        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame()
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()

        # 计算 7d 趋势
        df["fear_greed_trend_7d"] = df["fear_greed_index"] - df["fear_greed_index"].rolling(7, min_periods=1).mean()
        return df

    def fetch_funding_rate_history(self, symbol: str, days: int = 365) -> pd.DataFrame:
        """OKX 资金费率历史 — 8h 间隔，尝试取 3 个月/90 页（OKX 上限）

        返回 DataFrame: index=timestamp(UTC), columns=[funding_rate]
        """
        inst_id = _OKX_INST_MAP.get(symbol.upper())
        if not inst_id:
            return pd.DataFrame()

        # 先查缓存
        cache_key = f"funding_rate_{symbol.upper()}"
        cached = self._load_cache(symbol.upper(), cache_key)
        if cached is not None:
            return cached

        all_items = []
        # OKX 每8h一条，limit=100 → ~33天/页。最多尝试90页（API有历史上限）
        max_pages = 90
        before = None
        prev_oldest = None

        for _ in range(max_pages):
            params = {"instId": inst_id, "limit": "100"}
            if before:
                params["before"] = str(before)
            data = self._get(
                "https://www.okx.com/api/v5/public/funding-rate-history",
                params=params,
            )
            if not data or data.get("code") != "0" or not data.get("data"):
                break
            items = data["data"]
            for item in items:
                ts = int(item.get("fundingTime", 0)) // 1000
                rate = float(item.get("fundingRate", 0) or 0)
                all_items.append({"timestamp": ts, "funding_rate": rate})
            # 下一页用最旧的时间戳
            oldest_ts = items[-1].get("fundingTime")
            if oldest_ts == prev_oldest:
                break  # 无法更旧，已到历史边界
            prev_oldest = oldest_ts
            before = oldest_ts
            time.sleep(0.25)  # 限流

        if not all_items:
            return pd.DataFrame()

        df = pd.DataFrame(all_items)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()
        # 去重
        df = df[~df.index.duplicated(keep="last")]

        # 截断到 days 参数范围
        if not df.empty:
            cutoff = df.index.max() - pd.Timedelta(days=days)
            df = df[df.index >= cutoff]

        # 保存缓存
        self._save_cache(symbol.upper(), cache_key, df)
        return df

    def fetch_open_interest_history(self, symbol: str, days: int = 250) -> pd.DataFrame:
        """OKX 持仓量历史 — 1H 间隔，分页获取

        返回 DataFrame: index=timestamp(UTC), columns=[open_interest]
        使用 oiCcy（币本位持仓量）而非 oi（合约张数），跨币种可比。
        """
        inst_id = _OKX_INST_MAP.get(symbol.upper())
        if not inst_id:
            return pd.DataFrame()

        cache_key = f"open_interest_{symbol.upper()}"
        cached = self._load_cache(symbol.upper(), cache_key)
        if cached is not None:
            return cached

        all_items = []
        max_pages = 90
        after = None
        prev_oldest = None

        for _ in range(max_pages):
            params = {"instId": inst_id, "period": "1H", "limit": "100"}
            if after:
                params["after"] = str(after)
            data = self._get(
                "https://www.okx.com/api/v5/public/open-interest-history",
                params=params,
            )
            if not data or data.get("code") != "0" or not data.get("data"):
                break
            items = data["data"]
            for item in items:
                ts = int(item.get("ts", 0)) // 1000
                # 优先 oiCcy（币本位），缺失则用 oi（合约张数）
                oi = item.get("oiCcy") or item.get("oi")
                if oi is not None:
                    all_items.append({"timestamp": ts, "open_interest": float(oi)})
            oldest_ts = items[-1].get("ts")
            if oldest_ts == prev_oldest:
                break
            prev_oldest = oldest_ts
            after = oldest_ts
            time.sleep(0.25)

        if not all_items:
            return pd.DataFrame()

        df = pd.DataFrame(all_items)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()
        df = df[~df.index.duplicated(keep="last")]

        if not df.empty:
            cutoff = df.index.max() - pd.Timedelta(days=days)
            df = df[df.index >= cutoff]

        self._save_cache(symbol.upper(), cache_key, df)
        return df

    def fetch_stablecoin_history(self, days: int = 365) -> pd.DataFrame:
        """DefiLlama 稳定币总市值 — 每日历史

        返回 DataFrame: index=timestamp(UTC), columns=[stablecoin_supply]
        """
        data = self._get("https://stablecoins.llama.fi/stablecoincharts/all")
        if not data or len(data) < 2:
            return pd.DataFrame()

        rows = []
        for item in data:
            ts = int(item.get("date", 0))
            val = item.get("totalCirculatingUSD")
            if isinstance(val, dict):
                total = sum(float(v) for v in val.values() if v)
            elif val is not None:
                total = float(val)
            else:
                total = 0.0
            if total > 0:
                rows.append({"timestamp": ts, "stablecoin_supply": total})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()

        # 只保留最近 days 天
        cutoff = df.index.max() - pd.Timedelta(days=days)
        df = df[df.index >= cutoff]
        return df

    def fetch_tvl_history(self, symbol: str, days: int = 365) -> pd.DataFrame:
        """DefiLlama 链上 TVL — 每日历史

        返回 DataFrame: index=timestamp(UTC), columns=[tvl]
        """
        chain = _LLAMA_CHAIN_MAP.get(symbol.upper())
        if not chain:
            return pd.DataFrame()

        data = self._get(f"https://api.llama.fi/v2/historicalChainTvl/{chain}")
        if not data:
            return pd.DataFrame()

        rows = []
        for item in data:
            ts = int(item.get("date", 0))
            tvl = float(item.get("tvl", 0) or 0)
            if tvl > 0:
                rows.append({"timestamp": ts, "tvl": tvl})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()

        cutoff = df.index.max() - pd.Timedelta(days=days)
        df = df[df.index >= cutoff]
        return df

    def fetch_market_cap_history(self, symbol: str, days: int = 365) -> pd.DataFrame:
        """CoinGecko market_chart — 每日历史

        返回 DataFrame: index=timestamp(UTC), columns=[market_cap, ath_drop_pct, supply_ratio]
        """
        coin_id = _COINGECKO_ID_MAP.get(symbol.upper())
        if not coin_id:
            return pd.DataFrame()

        data = self._get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": str(days), "interval": "daily"},
        )
        if not data:
            return pd.DataFrame()

        mc_list = data.get("market_caps", [])
        prices = data.get("prices", [])

        if not mc_list:
            return pd.DataFrame()

        # 构建市场市值
        rows = []
        for ts_ms, mc in mc_list:
            ts = int(ts_ms) // 1000
            rows.append({"timestamp": ts, "market_cap": float(mc)})

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()

        # ATH 跌幅（用历史最高点计算）
        if not df.empty:
            ath = df["market_cap"].cummax()
            df["ath_drop_pct"] = (df["market_cap"] - ath) / ath * 100

        # supply_ratio 需要额外请求，简化为用 market_cap 排名近似
        # 实际 supply_ratio 在实时采集中获取

        return df

    def fetch_hash_rate_history(self, days: int = 365) -> pd.DataFrame:
        """Blockchain.info hash_rate — 每日历史（仅 BTC）

        返回 DataFrame: index=timestamp(UTC), columns=[hash_rate, miners_revenue]
        """
        data = self._get(
            "https://blockchain.info/charts/hash-rate",
            params={"timespan": "1year", "format": "json"},
        )
        if not data or not data.get("values"):
            return pd.DataFrame()

        rows = []
        for item in data["values"]:
            ts = int(item.get("x", 0))
            hr = float(item.get("y", 0) or 0)
            if hr > 0:
                rows.append({"timestamp": ts, "hash_rate": hr})

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        df = df.set_index("timestamp").sort_index()

        # miners_revenue 用另一个端点
        rev_data = self._get(
            "https://blockchain.info/charts/miners-revenue",
            params={"timespan": "1year", "format": "json"},
        )
        if rev_data and rev_data.get("values"):
            rev_rows = {}
            for item in rev_data["values"]:
                ts = int(item.get("x", 0))
                rev_rows[ts] = float(item.get("y", 0) or 0)
            df["miners_revenue"] = df.index.astype(np.int64).map(
                lambda ts: rev_rows.get(int(ts // 10**9), np.nan)
            )

        return df

    def fetch_smart_money_realtime(self) -> pd.DataFrame:
        """币安 Web3 Smart Money — 仅实时（回测中返回空）

        返回 DataFrame: index=now, columns=[smart_money_direction]
        """
        result = {"smart_money_direction": np.nan}
        try:
            total_buy = 0
            total_sell = 0
            total_sm_buy = 0
            total_sm_sell = 0

            for chain_id in ("CT_501", "56"):
                data = self._post_json(
                    "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money",
                    payload={
                        "smartSignalType": "",
                        "page": 1,
                        "pageSize": 100,
                        "chainId": chain_id,
                    },
                )
                if not data or not data.get("success"):
                    continue
                for item in data.get("data", []):
                    direction = item.get("direction", "")
                    sm_count = int(item.get("smartMoneyCount", 0) or 0)
                    if direction == "buy":
                        total_buy += 1
                        total_sm_buy += sm_count
                    elif direction == "sell":
                        total_sell += 1
                        total_sm_sell += sm_count

            total_sm = total_sm_buy + total_sm_sell
            if total_sm > 0:
                result["smart_money_direction"] = (total_sm_buy - total_sm_sell) / total_sm
        except Exception:
            pass

        return pd.DataFrame([result], index=pd.DatetimeIndex([datetime.now(timezone.utc)]))

    def fetch_social_hype_realtime(self, symbol: str) -> pd.DataFrame:
        """币安 Web3 Social Hype — 仅实时（回测中返回空）

        返回 DataFrame: index=now, columns=[social_hype_score]
        """
        result = {"social_hype_score": np.nan}
        if symbol.upper() not in ("BTC", "ETH", "SOL", "BNB"):
            return pd.DataFrame([result], index=pd.DatetimeIndex([datetime.now(timezone.utc)]))

        try:
            data = self._get(
                "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard",
                params={
                    "chainId": "56",
                    "sentiment": "All",
                    "targetLanguage": "en",
                    "timeRange": 1,
                    "socialLanguage": "ALL",
                },
            )
            if data and data.get("success"):
                items = data.get("data", {}).get("leaderBoardList", [])
                for item in items:
                    if item.get("metaInfo", {}).get("symbol", "").upper() == symbol.upper():
                        hype_info = item.get("socialHypeInfo", {})
                        result["social_hype_score"] = float(hype_info.get("socialHype", 0) or 0)
                        break
        except Exception:
            pass

        return pd.DataFrame([result], index=pd.DatetimeIndex([datetime.now(timezone.utc)]))

    # ============================================================
    # 综合采集
    # ============================================================

    def fetch_all(
        self,
        symbol: str,
        kline_index: pd.DatetimeIndex,
        live: bool = False,
        verbose: bool = False,
    ) -> pd.DataFrame:
        """采集所有宏观数据，对齐到 K 线时间戳

        Args:
            symbol: 交易标的
            kline_index: K 线时间索引
            live: True=实盘模式(含实时源), False=回测模式(仅历史源)
            verbose: 打印详细日志

        Returns:
            macro_df: 对齐到 kline_index 的宏观数据 DataFrame
        """
        sym = symbol.upper()
        cache_key = f"{sym}_live{live}"

        # 类级内存缓存命中：跳过所有 API 调用，直接对齐
        if cache_key in MacroDataFetcher._raw_cache:
            combined = MacroDataFetcher._raw_cache[cache_key]
            aligned = self.align_to_klines(combined, kline_index, lookahead_guard=1)
            if verbose:
                print(f"  [MacroDataFetcher] {sym}: 内存缓存命中, "
                      f"对齐后 {len(aligned.columns)} 列, {aligned.notna().sum().sum()} 个有效值")
            return aligned

        all_dfs: List[pd.DataFrame] = []
        source_status: Dict[str, str] = {}

        # 1. FGI（市场级，不分币种）
        try:
            fgi = self.fetch_fgi_history(limit=365)
            if not fgi.empty:
                all_dfs.append(fgi)
                source_status["fgi"] = "ok"
            else:
                source_status["fgi"] = "missing"
        except Exception as e:
            source_status["fgi"] = f"error:{type(e).__name__}"

        # 2. OKX 资金费率
        try:
            fr = self.fetch_funding_rate_history(sym, days=250)
            if not fr.empty:
                all_dfs.append(fr)
                source_status["funding_rate"] = "ok"
            else:
                source_status["funding_rate"] = "missing"
        except Exception as e:
            source_status["funding_rate"] = f"error:{type(e).__name__}"

        # 2b. OKX 持仓量（open_interest）— 用于 oi_change_rate 的正确计算
        try:
            oi = self.fetch_open_interest_history(sym, days=250)
            if not oi.empty:
                all_dfs.append(oi)
                source_status["open_interest"] = "ok"
            else:
                source_status["open_interest"] = "missing"
        except Exception as e:
            source_status["open_interest"] = f"error:{type(e).__name__}"

        # 3. DefiLlama 稳定币
        try:
            sc = self.fetch_stablecoin_history(days=365)
            if not sc.empty:
                all_dfs.append(sc)
                source_status["stablecoin"] = "ok"
            else:
                source_status["stablecoin"] = "missing"
        except Exception as e:
            source_status["stablecoin"] = f"error:{type(e).__name__}"

        # 4. DefiLlama TVL
        try:
            tvl = self.fetch_tvl_history(sym, days=365)
            if not tvl.empty:
                all_dfs.append(tvl)
                source_status["tvl"] = "ok"
            else:
                source_status["tvl"] = "missing"
        except Exception as e:
            source_status["tvl"] = f"error:{type(e).__name__}"

        # 5. CoinGecko market_cap
        try:
            mc = self.fetch_market_cap_history(sym, days=365)
            if not mc.empty:
                all_dfs.append(mc)
                source_status["market_cap"] = "ok"
            else:
                source_status["market_cap"] = "missing"
        except Exception as e:
            source_status["market_cap"] = f"error:{type(e).__name__}"

        # 6. Blockchain.info hash_rate（仅 BTC）
        if sym == "BTC":
            try:
                hr = self.fetch_hash_rate_history(days=365)
                if not hr.empty:
                    all_dfs.append(hr)
                    source_status["hash_rate"] = "ok"
                else:
                    source_status["hash_rate"] = "missing"
            except Exception as e:
                source_status["hash_rate"] = f"error:{type(e).__name__}"
        else:
            source_status["hash_rate"] = "skip_non_btc"

        # 7+8. 实时源（仅实盘模式）
        if live:
            try:
                sm = self.fetch_smart_money_realtime()
                if not sm.empty:
                    all_dfs.append(sm)
                    source_status["smart_money"] = "ok"
                else:
                    source_status["smart_money"] = "missing"
            except Exception as e:
                source_status["smart_money"] = f"error:{type(e).__name__}"

            try:
                sh = self.fetch_social_hype_realtime(sym)
                if not sh.empty:
                    all_dfs.append(sh)
                    source_status["social_hype"] = "ok"
                else:
                    source_status["social_hype"] = "missing"
            except Exception as e:
                source_status["social_hype"] = f"error:{type(e).__name__}"
        else:
            source_status["smart_money"] = "backtest_skip"
            source_status["social_hype"] = "backtest_skip"

        if not all_dfs:
            if verbose:
                print(f"  [MacroDataFetcher] {sym}: 所有数据源采集失败")
            return pd.DataFrame(index=kline_index)

        # 合并所有源（按时间戳外连接）
        # 先对每个 DataFrame 去重索引，避免 concat 时 InvalidIndexError
        cleaned_dfs = []
        for d in all_dfs:
            if d is None or d.empty:
                continue
            if not d.index.is_unique:
                d = d[~d.index.duplicated(keep="last")]
            cleaned_dfs.append(d)

        if not cleaned_dfs:
            return pd.DataFrame(index=kline_index)

        combined = pd.concat(cleaned_dfs, axis=1)
        if not combined.index.is_unique:
            combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()

        # 写入类级内存缓存，后续同 symbol 的调用直接复用
        MacroDataFetcher._raw_cache[cache_key] = combined

        # 对齐到 K 线时间戳
        aligned = self.align_to_klines(combined, kline_index, lookahead_guard=1)

        ok_count = sum(1 for v in source_status.values() if v == "ok")
        if verbose:
            print(f"  [MacroDataFetcher] {sym}: {ok_count}/{len(source_status)} 源成功, "
                  f"对齐后 {len(aligned.columns)} 列, {aligned.notna().sum().sum()} 个有效值")

        return aligned

    # ============================================================
    # 时间对齐 + 未来函数防护
    # ============================================================

    @staticmethod
    def align_to_klines(
        macro_df: pd.DataFrame,
        kline_index: pd.DatetimeIndex,
        lookahead_guard: int = 1,
    ) -> pd.DataFrame:
        """将宏观数据对齐到 K 线时间戳

        规则:
        1. 宏观数据时间戳 t_macro
        2. K 线时间戳 t_kline
        3. 只有当 t_macro <= t_kline - lookahead_guard * bar_size 时才填充
        4. 否则填充 NaN（特征模块自动跳过）

        Args:
            macro_df: 宏观数据 DataFrame（任意频率）
            kline_index: K 线时间索引
            lookahead_guard: 发布延迟保护（≥1 根 K 线）

        Returns:
            对齐到 kline_index 的 DataFrame
        """
        if macro_df.empty or len(kline_index) == 0:
            return pd.DataFrame(index=kline_index)

        # 确保都是 UTC
        if macro_df.index.tz is None:
            macro_df = macro_df.copy()
            macro_df.index = macro_df.index.tz_localize("UTC")
        if kline_index.tz is None:
            kline_index = kline_index.tz_localize("UTC")

        # 计算 K 线周期（秒）
        if len(kline_index) >= 2:
            bar_seconds = int((kline_index[1] - kline_index[0]).total_seconds())
        else:
            bar_seconds = 3600  # 默认 1H

        guard_delta = pd.Timedelta(seconds=bar_seconds * lookahead_guard)

        # 确保 macro_df 按时间排序
        macro_df = macro_df.sort_index()

        # 使用 merge_asof: 对每根 K 线，找最近的 t_macro <= t_kline - guard_delta
        kline_df = pd.DataFrame(index=kline_index)
        kline_df["_kline_ts"] = kline_index

        macro_reset = macro_df.reset_index()
        col_name = macro_reset.columns[0]  # timestamp 列名
        macro_reset = macro_reset.rename(columns={col_name: "_macro_ts"})

        # 将 K 线时间减去 guard_delta，然后用 asof 找 <= 该时间的宏观数据
        kline_df["_search_ts"] = kline_index - guard_delta

        aligned = pd.merge_asof(
            kline_df.sort_values("_search_ts"),
            macro_reset.sort_values("_macro_ts"),
            left_on="_search_ts",
            right_on="_macro_ts",
            direction="backward",
        )

        # 设回 K 线索引
        aligned = aligned.set_index(kline_index)
        # 删除辅助列
        aligned = aligned.drop(columns=["_kline_ts", "_search_ts", "_macro_ts"], errors="ignore")

        # 只保留原始宏观数据列
        macro_cols = [c for c in aligned.columns if c in macro_df.columns]
        aligned = aligned[macro_cols]

        return aligned
