"""
形态预测器专用 — 免费市场数据 Feed（零成本，无需任何 API Key）

全部使用公开免费 API：
  - Binance 公共 REST：BTC 日线 OHLC、25 龙头 24h 涨跌幅/成交额（板块代理）
  - CoinGecko 免费层：BTC.D（市值占比）、Top8 稳定币市值总和
  - Alternative.me：Crypto Fear & Greed Index（情绪）
  - Stooq 免费 CSV：SPY/QQQ/GLD/TLT/IBIT 等美股与 ETF 日线（Yahoo v8 公共端点不稳定时的兜底）
  - OKX V5 公共 REST：持仓量 OI、资金费率、多空比（免费无凭证，和 Binance 双备份）
  - 自研 Pearson 相关性：BTC vs 标普/纳指/黄金 30/90 日滚动相关（无需外部付费接口）

定位：
  当 S8 开关（enable_coinglass_feed）关闭时，作为形态预测器 Layer 0 / Layer 1
  的默认全局 + 板块数据源；S8 打开时，与 CoinGlassFeed 返回字段对齐，
  取并集（CoinGlass 高精度字段覆盖免费代理）。

对应 spec 章节：
  §6 市场广度特征组、§7 板块间广度特征组、§8 外部数据源（免费降级方案）。
"""

from __future__ import annotations

import io
import csv
import math
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# ============================================================
# 板块定义（与 spec 保持一致：5 大板块 × 每个龙头数量 ≥ 5）
# ============================================================

CRYPTO_SECTORS: Dict[str, List[str]] = {
    # DeFi：去中心化金融
    "DEFI": ["UNI", "AAVE", "COMP", "LINK", "CRV", "MKR", "SNX", "DYDX", "LDO", "FXS"],
    # AI-Web3：AI + Web3 基础设施
    "AI_WEB3": ["FET", "AGIX", "RNDR", "AR", "NMR", "WLD", "TAO", "GRT", "OCEAN", "BTT"],
    # RWA：现实资产代币化
    "RWA": ["ONDO", "POLYX", "CFG", "WLD", "LINK", "SNX", "MKR", "COMP", "LDO", "FXS"],
    # MEME：模因币
    "MEME": ["DOGE", "WIF", "SHIB", "PEPE", "FLOKI", "BONK", "POPCAT", "MEW", "TURBO", "NOT"],
    # L2：二层网络 + 公链基础设施
    "L2": ["SOL", "AVAX", "MATIC", "ARB", "OP", "SUI", "SEI", "TON", "ADA", "DOT"],
}


# 主流币 Binance 交易对（用于广度特征：8 大主流币 MA128 同向比例等）
MAINSTREAM_COINS: List[str] = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
]


class FreeMarketFeed:
    """形态预测器免费市场数据源

    全部公开接口、零成本、无需 key。
    设计为「全局快照」：一次 collect_global() 返回所有 Layer 0 + Layer 1 所需数据。

    主要方法：
      - collect_global() -> dict         一次调用，完整采集所有全局/板块/美股/情绪
      - get_sector_proxy_weights()       基于 24h 龙头加权涨跌幅 + 成交额的板块资金偏置（免费替代 NetFlow）
      - get_mainstream_breadth()         8 大主流币同向比例（spec §6 广度组核心）
      - get_btc_us_assets_correlations() BTC vs SPY/QQQ/GLD 滚动相关性（自己算，替代 Coinglass 付费端点）
    """

    CACHE_TTL = 1800  # 全局快照缓存 30 分钟（日线训练 1 次/日，完全够用）

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "DreamOS-FreeMarketFeed/1.0",
            "Accept": "application/json",
        })
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # key -> (ts, data)

    # ============================================================
    # 底层 HTTP 工具
    # ============================================================

    def _get_json(self, url: str, params: Optional[Dict] = None, timeout: int = 15) -> Optional[Any]:
        try:
            r = self._session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"[FreeMarketFeed] GET JSON 失败 {url}: {e}")
            return None

    def _get_text(self, url: str, params: Optional[Dict] = None, timeout: int = 20) -> Optional[str]:
        try:
            r = self._session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.debug(f"[FreeMarketFeed] GET TEXT 失败 {url}: {e}")
            return None

    def _cached(self, key: str, compute_fn, ttl: Optional[int] = None):
        ttl = ttl or self.CACHE_TTL
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]
        result = compute_fn()
        self._cache[key] = (now, result)
        return result

    # ============================================================
    # 1) Binance：BTC 日线 OHLC（所有 Layer 0 特征的基础）
    # ============================================================

    def fetch_btc_daily_ohlc(self, limit: int = 365) -> List[Dict[str, Any]]:
        """BTC 日线（Binance USDT 标的，免费无 key）

        返回升序排列（最老在前，最新在后）的 OHLC 列表：
            [{'t': ts秒, 'O': float, 'H': float, 'L': float, 'C': float, 'V': float(btc数量)}, ...]
        """
        def _fetch():
            data = self._get_json(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": str(limit)},
                timeout=20,
            )
            if not data:
                return []
            rows = []
            for k in data:
                # [open_time_ms, open, high, low, close, vol, close_time_ms, quote_vol, ...]
                rows.append({
                    "t": int(k[0]) // 1000,
                    "O": float(k[1]),
                    "H": float(k[2]),
                    "L": float(k[3]),
                    "C": float(k[4]),
                    "V": float(k[5]),
                    "QV": float(k[7]),  # 成交额（USDT）
                })
            return rows
        return self._cached(f"btc_daily_{limit}", _fetch)

    # ============================================================
    # 2) Binance：24h ticker → 5 板块龙头的免费资金代理（涨跌幅 × 成交额加权）
    # ============================================================

    def fetch_all_binance_tickers(self) -> Dict[str, Dict[str, float]]:
        """全部 USDT 标的 24h ticker（symbol → {'pct': 涨跌幅%, 'vol_usd_24h': 成交额 USD}）"""
        def _fetch() -> Dict[str, Dict[str, float]]:
            raw = self._get_json(
                "https://api.binance.com/api/v3/ticker/24hr",
                timeout=25,
            )
            if not raw:
                return {}
            out: Dict[str, Dict[str, float]] = {}
            for t in raw:
                sym = t.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                coin = sym[:-4]
                try:
                    out[coin] = {
                        "pct": float(t.get("priceChangePercent", 0) or 0),
                        "vol_usd_24h": float(t.get("quoteVolume", 0) or 0),
                    }
                except (TypeError, ValueError):
                    continue
            return out
        return self._cached("binance_tickers_24h", _fetch, ttl=900)

    def get_sector_proxy_weights(self) -> Dict[str, Dict[str, Any]]:
        """板块资金偏置的免费代理（替代 Coinglass Startup 的 Coin NetFlow List）

        算法（等权 + 成交额加权两档都给，下游形态预测器自行选择）：
          sector_pct_equal_weight  = 板块内所有龙头 24h 涨跌幅等权平均
          sector_pct_volume_weight = 板块内所有龙头 24h 涨跌幅 × 成交额 加权平均
          sector_volume_share_pct  = 板块总成交额 / 5 板块总成交额（成交额占比）
          sector_rank_1st5         = 按 volume_weight 涨跌幅在 5 板块中的排名（1=最强 5=最弱）

        注意：这是「价格+成交额代理」，不是真实主动买卖净流入。
        若 S8 打开 + CoinGlass Startup 可用，则用真实 NetFlow 覆盖这些字段。
        """
        tickers = self.fetch_all_binance_tickers()
        sectors: Dict[str, Dict[str, Any]] = {}
        sector_totals: Dict[str, float] = {}

        for sector_name, members in CRYPTO_SECTORS.items():
            hits_pct: List[Tuple[float, float]] = []  # (pct, vol_usd)
            for coin in members:
                tk = tickers.get(coin)
                if not tk:
                    continue
                hits_pct.append((tk["pct"], tk["vol_usd_24h"]))

            if not hits_pct:
                sectors[sector_name] = {
                    "hits": 0,
                    "pct_equal": 0.0,
                    "pct_volume": 0.0,
                    "volume_total_usd_24h": 0.0,
                    "volume_share_pct": 0.0,
                    "note": "no members found on binance",
                }
                continue

            total_vol = sum(v for _, v in hits_pct)
            eq = sum(p for p, _ in hits_pct) / len(hits_pct)
            vw = sum(p * v for p, v in hits_pct) / total_vol if total_vol > 0 else eq

            sectors[sector_name] = {
                "hits": len(hits_pct),
                "pct_equal": round(eq, 4),
                "pct_volume": round(vw, 4),
                "volume_total_usd_24h": round(total_vol, 2),
                "volume_share_pct": 0.0,  # 稍后回填
            }
            sector_totals[sector_name] = total_vol

        # 计算板块成交额占比
        grand_total = sum(sector_totals.values())
        if grand_total > 0:
            for sn, tot in sector_totals.items():
                sectors[sn]["volume_share_pct"] = round(tot / grand_total * 100, 3)

        # 按 volume_weight 涨跌幅排名（1=最强）
        ranked = sorted(sectors.keys(), key=lambda s: -sectors[s]["pct_volume"])
        for i, sn in enumerate(ranked, start=1):
            sectors[sn]["strength_rank_1to5"] = i

        return sectors

    # ============================================================
    # 3) 广度：8 大主流币同向比例（spec §6 市场广度组）
    # ============================================================

    def get_mainstream_breadth(self, lookback_days: int = 20) -> Dict[str, Any]:
        """8 大主流币的同向比例 + 强度统计

        计算：
          - breadth_pct_above_ma20：8 币收盘价 > 各自 MA20 的比例（0~1）
          - breadth_pct_up_20d：   8 币 20d 收益 > 0 的比例（0~1）
          - avg_return_20d：       8 币平均 20d 收益率
          - equal_weighted_basket_return_20d：等权 8 币篮子 20d 收益（可当「山寨指数」用）

        全部数据来自 Binance 免费 kline。
        """
        def _ma(values: List[float], n: int) -> Optional[float]:
            if len(values) < n:
                return None
            return sum(values[-n:]) / n

        one_day = lookback_days + 30  # 多取一些以便 MA 计算
        basket_returns: List[float] = []
        above_ma20_count = 0
        up_20d_count = 0
        per_coin: Dict[str, Dict[str, Any]] = {}
        ok_coins = 0

        for coin in MAINSTREAM_COINS:
            sym = f"{coin}USDT"
            kl = self._get_json(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": sym, "interval": "1d", "limit": str(one_day)},
                timeout=20,
            )
            if not kl or len(kl) < lookback_days + 2:
                per_coin[coin] = {"ok": False, "reason": "insufficient_data"}
                continue
            closes = [float(k[4]) for k in kl]
            latest = closes[-1]
            ma20 = _ma(closes, 20)
            ret_20d = (latest / closes[-lookback_days - 1] - 1) * 100 if closes[-lookback_days - 1] > 0 else 0.0

            ok_coins += 1
            if ma20 is not None and latest > ma20:
                above_ma20_count += 1
            if ret_20d > 0:
                up_20d_count += 1
            basket_returns.append(ret_20d)
            per_coin[coin] = {
                "ok": True,
                "close_latest": round(latest, 4),
                "ma20": round(ma20, 4) if ma20 else None,
                "above_ma20": (latest > ma20) if ma20 else None,
                "return_20d_pct": round(ret_20d, 3),
            }

        if ok_coins == 0:
            return {"ok": False, "reason": "no_mainstream_coin_data"}

        avg_ret = sum(basket_returns) / len(basket_returns) if basket_returns else 0.0

        return {
            "ok": True,
            "lookback_days": lookback_days,
            "coins_covered": ok_coins,
            "breadth_pct_above_ma20": round(above_ma20_count / ok_coins, 4),
            "breadth_pct_up_20d": round(up_20d_count / ok_coins, 4),
            "avg_return_20d_pct": round(avg_ret, 3),
            # 等权 8 币篮子 20d 收益 — 与 BTC 20d 收益的差值 → 山寨相对强弱
            "equal_weighted_basket_return_20d_pct": round(avg_ret, 3),
            "coins_detail": per_coin,
        }

    # ============================================================
    # 4) CoinGecko：BTC.D + 稳定币总市值（spec §6 广度组 + §8 宏观组）
    # ============================================================

    def fetch_global_macro(self) -> Dict[str, Any]:
        """BTC 市值占比、Top8 稳定币总市值 + 7d 变化率"""
        def _fetch():
            result: Dict[str, Any] = {"_ok": False}
            g = self._get_json("https://api.coingecko.com/api/v3/global", timeout=15)
            if g and g.get("data"):
                d = g["data"]
                result["btc_dominance_pct"] = round(
                    float(d.get("market_cap_percentage", {}).get("btc", 0) or 0), 3
                )
                result["total_market_cap_usd"] = float(
                    d.get("total_market_cap", {}).get("usd", 0) or 0
                )
                result["total_volume_24h_usd"] = float(
                    d.get("total_volume", {}).get("usd", 0) or 0
                )
                result["_ok"] = True

            # Top8 稳定币市值求和（稳定币类别）
            sc = self._get_json(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "category": "stablecoins",
                    "order": "market_cap_desc",
                    "per_page": "8",
                    "page": "1",
                    "sparkline": "false",
                    "price_change_percentage": "7d,30d",
                },
                timeout=20,
            )
            if sc:
                total_mcap = 0.0
                top8 = []
                for c in sc:
                    mcap = float(c.get("market_cap") or 0)
                    total_mcap += mcap
                    top8.append({
                        "id": c["id"],
                        "symbol": c["symbol"],
                        "mcap_usd_billion": round(mcap / 1e9, 3),
                        "change_7d_pct": round(float(c.get("price_change_percentage_7d_in_currency") or 0), 3),
                        "change_30d_pct": round(float(c.get("price_change_percentage_30d_in_currency") or 0), 3),
                    })
                result["stablecoin_mcap_top8_usd_billion"] = round(total_mcap / 1e9, 3)
                # 稳定币市值 7d/30d 变化率 ≈ 稳定币「净申赎」（法币入场代理）
                if total_mcap > 0:
                    # 用 top8 的加权 7d/30d 价格变化率近似市值变化（稳定币 peg≈1，≈ 数量变化）
                    weighted_7d = sum(
                        (float(c.get("market_cap") or 0) / total_mcap) *
                        float(c.get("price_change_percentage_7d_in_currency") or 0)
                        for c in sc if c.get("market_cap")
                    )
                    weighted_30d = sum(
                        (float(c.get("market_cap") or 0) / total_mcap) *
                        float(c.get("price_change_percentage_30d_in_currency") or 0)
                        for c in sc if c.get("market_cap")
                    )
                    result["stablecoin_mcap_change_7d_pct_proxy"] = round(weighted_7d, 4)
                    result["stablecoin_mcap_change_30d_pct_proxy"] = round(weighted_30d, 4)
                result["stablecoin_top8"] = top8
                result["_ok"] = True

            return result if result["_ok"] else {"_ok": False, "err": "coingecko_failed"}
        return self._cached("cg_global_macro", _fetch, ttl=1800)

    # ============================================================
    # 5) Fear & Greed（Alternative.me 免费）
    # ============================================================

    def fetch_fear_greed(self, limit: int = 60) -> Dict[str, Any]:
        def _fetch():
            d = self._get_json(
                "https://api.alternative.me/fng/",
                params={"limit": str(limit)},
                timeout=15,
            )
            if not d or not d.get("data"):
                return {"ok": False, "err": "alternative_me_failed"}
            history = d["data"]
            latest = history[0]
            values = [int(h.get("value", 50)) for h in history]
            out = {
                "ok": True,
                "value": int(latest.get("value", 50)),
                "classification": latest.get("value_classification", "Neutral"),
                "timestamp_s": int(latest.get("timestamp", 0) or 0),
            }
            if len(values) >= 7:
                out["avg_7d"] = round(sum(values[:7]) / 7, 1)
                out["trend_vs_7d"] = round(out["value"] - out["avg_7d"], 1)
            if len(values) >= 30:
                out["avg_30d"] = round(sum(values[:30]) / 30, 1)
                out["trend_vs_30d"] = round(out["value"] - out["avg_30d"], 1)
                out["high_30d"] = max(values[:30])
                out["low_30d"] = min(values[:30])
                # 当前值在 30 天区间的分位位置 [0,1]
                rng = (out["high_30d"] - out["low_30d"]) or 1
                out["percentile_30d"] = round((out["value"] - out["low_30d"]) / rng, 3)
            return out
        return self._cached(f"fear_greed_{limit}", _fetch, ttl=1800)

    # ============================================================
    # 6) 美股/ETF 日线：yfinance 首选（项目已安装，绕过 JS 验证）
    #    支持 SPY / QQQ / GLD / TLT / IBIT / FBIT / ARKB / ^GSPC(标普500) / ^IXIC(纳指) / BTC-USD 等
    #    若无 yfinance，则返回空（兜底返回空不阻塞主流程）
    # ============================================================

    def fetch_equity_daily(self, ticker: str, limit: int = 252) -> List[Dict[str, Any]]:
        """美股/ETF/指数日线（yfinance 免费库，零 key，项目已预装 1.6.0）

        常用 ticker:
          SPY（标普500 ETF）、QQQ（纳指100 ETF）、GLD（黄金 ETF）、TLT（20年美债 ETF）
          IBIT（黑岩 BTC ETF）、FBIT（富达 BTC ETF）、ARKB（方舟 BTC ETF）
          ^GSPC 标普500指数、^IXIC 纳指、^DJI 道指
          BTC-USD / ETH-USD（yfinance 也能拿加密价格，但我们用 Binance 更准）

        注意：yfinance 有 rate limit，日线训练一天一次完全够用；此处加了进程内缓存避免重复打。
        """
        def _fetch() -> List[Dict[str, Any]]:
            try:
                import yfinance as yf  # lazy import：项目未装时也能跑加密侧数据
            except Exception as e:
                logger.debug(f"[FreeMarketFeed] yfinance 未安装，跳过美股/ETF {ticker}: {e}")
                return []
            try:
                # yfinance download 最近 limit+buffer 天，防止时区裁剪不够
                period = "5y" if limit > 365 else f"{limit + 30}d"
                df = yf.download(
                    ticker,
                    period=period,
                    interval="1d",
                    auto_adjust=False,  # 用原始 Close（与 Binance 逻辑一致）
                    progress=False,
                    threads=False,
                )
                if df is None or len(df) == 0:
                    logger.debug(f"[FreeMarketFeed] yfinance 无数据 {ticker}")
                    return []

                # yfinance >=1.3 会返回 MultiIndex columns（多标的），这里单标的需兼容
                # 把 columns 展平：可能是 ("Close","SPY") 这种 tuple，也可能是 "Close" 字符串
                def _col(df, name: str):
                    for c in df.columns:
                        key = c[0] if isinstance(c, tuple) else c
                        if key == name:
                            return df[c]
                    # 兜底：直接按 name 取
                    if name in df.columns:
                        return df[name]
                    return None

                closes = _col(df, "Close")
                opens = _col(df, "Open")
                highs = _col(df, "High")
                lows = _col(df, "Low")
                vols = _col(df, "Volume")
                if closes is None:
                    return []

                rows: List[Dict[str, Any]] = []
                for ts in closes.index:
                    i = closes.index.get_loc(ts)
                    c = closes.iloc[i]
                    try:
                        if hasattr(ts, "tz_convert"):
                            dt = ts.tz_convert("UTC") if str(ts.tz) != "UTC" else ts
                        else:
                            dt = datetime.combine(ts.date(), datetime.min.time(), tzinfo=timezone.utc)
                        rows.append({
                            "t": int(dt.timestamp()),
                            "date": dt.strftime("%Y-%m-%d"),
                            "O": float(opens.iloc[i]) if opens is not None else float(c),
                            "H": float(highs.iloc[i]) if highs is not None else float(c),
                            "L": float(lows.iloc[i]) if lows is not None else float(c),
                            "C": float(c),
                            "V": float(vols.iloc[i]) if vols is not None else 0.0,
                        })
                    except (TypeError, ValueError):
                        continue

                # 取最后 limit 条
                return rows[-limit:] if len(rows) > limit else rows
            except Exception as e:
                logger.debug(f"[FreeMarketFeed] yfinance 取 {ticker} 失败: {e}")
                return []
        return self._cached(f"yf_{ticker.lower()}_{limit}", _fetch, ttl=3600)

    # ============================================================
    # 7) 自研：BTC vs 美股/黄金 滚动 Pearson 相关性（替代 Coinglass 付费端点）
    # ============================================================

    @staticmethod
    def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
        n = len(xs)
        if n < 8:
            return None
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
        dx = math.sqrt(sum((xs[i] - mx) ** 2 for i in range(n)))
        dy = math.sqrt(sum((ys[i] - my) ** 2 for i in range(n)))
        if dx == 0 or dy == 0:
            return None
        return num / (dx * dy)

    @staticmethod
    def _align_by_date(
        a_rows: List[Dict[str, Any]],
        b_rows: List[Dict[str, Any]],
    ) -> Tuple[List[float], List[float]]:
        """按「日期字符串 YYYY-MM-DD」对齐两个日线序列。

        BTC（Binance）是 UTC 00:00 日K；美股 ETF (yfinance) 是 America/New_York 收盘日K。
        两边时区不一致会导致时间戳对不上，但 YYYY-MM-DD 日期本身是对齐的（加密 7*24h 但美股收市时对应的 UTC 日期一致）。
        """
        def _ymd(row: Dict) -> Optional[str]:
            # 优先用已解析好的 date 字段；否则从时间戳转回 UTC 日期字符串
            d = row.get("date")
            if isinstance(d, str) and len(d) == 10:
                return d
            t = row.get("t")
            if isinstance(t, (int, float)):
                return datetime.fromtimestamp(float(t), tz=timezone.utc).strftime("%Y-%m-%d")
            return None

        b_by_ymd: Dict[str, float] = {}
        for row in b_rows:
            key = _ymd(row)
            if key is None:
                continue
            b_by_ymd[key] = row["C"]

        xs, ys = [], []
        for row in a_rows:
            key = _ymd(row)
            if key is None:
                continue
            if key in b_by_ymd:
                xs.append(row["C"])
                ys.append(b_by_ymd[key])
        return xs, ys

    def get_btc_us_assets_correlations(self, window_days: int = 30) -> Dict[str, Any]:
        """BTC vs SPY / QQQ / GLD / TLT 的滚动 Pearson 相关性（自研，免费替代 Coinglass /api/index/btc-correlations-*）

        返回:
          {
            "window_days": 30,
            "btc_vs_spy": 0.523,
            "btc_vs_qqq": 0.588,
            "btc_vs_gld": 0.112,
            "btc_vs_tlt": -0.05,
            "btc_equity_coupled": True,  # 与美股高度耦合（SPY+QQQ 平均 > 0.4）
            "btc_safe_haven": False,      # 与黄金同涨+与美债同涨 → 避险属性
          }
        """
        # BTC 日线（取 1.5x window_days + 缓冲）
        take_days = max(60, int(window_days * 1.8))
        btc = self.fetch_btc_daily_ohlc(limit=take_days)
        spy = self.fetch_equity_daily("SPY", limit=take_days)
        qqq = self.fetch_equity_daily("QQQ", limit=take_days)
        gld = self.fetch_equity_daily("GLD", limit=take_days)
        tlt = self.fetch_equity_daily("TLT", limit=take_days)

        if not btc:
            return {"ok": False, "err": "btc_daily_missing"}

        # 对齐并取最近 window_days 个共同交易日
        def _corr(us_rows):
            btc_c, us_c = self._align_by_date(btc, us_rows)
            if len(btc_c) < max(8, window_days // 2):
                return None
            # 只取最近 window_days 个点
            btc_w = btc_c[-window_days:]
            us_w = us_c[-window_days:]
            return self._pearson(btc_w, us_w)

        corr_spy = _corr(spy)
        corr_qqq = _corr(qqq)
        corr_gld = _corr(gld)
        corr_tlt = _corr(tlt)

        result: Dict[str, Any] = {
            "ok": True,
            "window_days": window_days,
            "btc_vs_spy": round(corr_spy, 4) if corr_spy is not None else None,
            "btc_vs_qqq": round(corr_qqq, 4) if corr_qqq is not None else None,
            "btc_vs_gld": round(corr_gld, 4) if corr_gld is not None else None,
            "btc_vs_tlt": round(corr_tlt, 4) if corr_tlt is not None else None,
            "sample_dates_aligned": None,
        }

        # 综合判断（下游 regime 预测器可直接消费）
        equities = [c for c in (corr_spy, corr_qqq) if c is not None]
        avg_equity = sum(equities) / len(equities) if equities else None
        result["avg_equity_corr"] = round(avg_equity, 4) if avg_equity is not None else None
        result["btc_equity_coupled"] = bool(avg_equity is not None and avg_equity > 0.4)
        # 避险 = 正黄金+正美债+弱美股（或都正但黄金>美股）
        if corr_gld is not None and corr_tlt is not None and avg_equity is not None:
            result["btc_safe_haven"] = bool(corr_gld > 0.2 and corr_tlt > 0.0 and corr_gld > avg_equity)
        else:
            result["btc_safe_haven"] = None

        return result

    # ============================================================
    # 8) BTC ETF 价格代理（用 IBIT/FBIT/ARKB 三只最大 ETF 的日线作为「机构参与度」代理）
    #    — S8 打开时用 CoinGlass 真实 flow-history 覆盖，否则免费至少有 ETF 价格变化
    # ============================================================

    def fetch_btc_etf_price_proxy(self) -> Dict[str, Any]:
        """BTC ETF 价格 + 成交额代理（yfinance 免费 IBIT/FBTC/ARKB 日线）

        注：
          - BlackRock → IBIT（全球最大 BTC 现货 ETF）
          - Fidelity  → FBTC（注意：不是 FBIT！ticker 修正于 2024.01 上市）
          - Ark Invest → ARKB

        当没有 CoinGlass flow-history 时，用以下代理近似机构资金流：
          - ETF 20d 相对 BTC 20d 超额收益 → ETF 跑赢 = 机构扫货信号
          - ETF 最新收盘价相对净值的溢价 → 溢价>1% = FOMO 情绪
        """
        btc = self.fetch_btc_daily_ohlc(limit=60)
        ibit = self.fetch_equity_daily("IBIT", limit=60)
        fbtc = self.fetch_equity_daily("FBTC", limit=60)
        arkb = self.fetch_equity_daily("ARKB", limit=60)

        def _ret_20d(rows):
            if not rows or len(rows) < 21:
                return None
            return (rows[-1]["C"] / rows[-21]["C"] - 1) * 100

        btc_ret = _ret_20d(btc) or 0.0
        any_ok = bool(ibit or fbtc or arkb)
        out: Dict[str, Any] = {
            "ok": any_ok,
            "_note": (
                "CoinGlass 关闭时的免费价格代理；S8+CoinGlassStartup 可用真实 flow-history 覆盖"
            ),
            "btc_return_20d_pct": round(btc_ret, 3),
            "funds": {},
        }
        for name, rows in (("IBIT", ibit), ("FBTC", fbtc), ("ARKB", arkb)):
            if not rows:
                continue
            ret_20 = _ret_20d(rows)
            excess = round((ret_20 - btc_ret), 3) if ret_20 is not None else None
            out["funds"][name] = {
                "latest_close": round(rows[-1]["C"], 4),
                "latest_date": rows[-1].get("date"),
                "volume_latest": round(rows[-1]["V"], 0),
                "return_20d_pct": round(ret_20, 3) if ret_20 is not None else None,
                "excess_vs_btc_20d_pct": excess,
            }
        # 三只 ETF 平均超额收益 → 宏观机构参与度代理
        excesses = [
            v["excess_vs_btc_20d_pct"] for v in out["funds"].values()
            if v["excess_vs_btc_20d_pct"] is not None
        ]
        if excesses:
            out["avg_etf_excess_20d_pct"] = round(sum(excesses) / len(excesses), 3)
        return out

    # ============================================================
    # 9) 衍生品数据（OI / 资金费率 / 多空比）：Binance Futures + OKX V5 双备份
    #    全部公共无 key 接口，spec §6 市场广度 / §8 宏观组特征
    # ============================================================

    def fetch_binance_futures_derivatives(self, symbol: str = "BTCUSDT",
                                          period: str = "1h",
                                          limit: int = 30) -> Dict[str, Any]:
        """Binance Futures 免费衍生品数据（零 key、公开接口）

        采集 5 大类数据：
          1) 当前 OI（持仓量）+ 30h OI 历史（美元名义价值）
          2) 当前资金费率 + 30 期资金费率历史
          3) 主动买卖比（Taker long/short ratio）30 期历史
          4) 全账户多空比（Global Long/Short Account Ratio）30 期历史
          5) Top Trader 持仓多空比（Top Long/Short Position Ratio）30 期历史

        period: 5m/15m/30m/1h/2h/4h/6h/12h/1d
        """
        def _fetch() -> Dict[str, Any]:
            base_fapi = "https://fapi.binance.com"
            result: Dict[str, Any] = {"_ok": False, "symbol": symbol, "period": period}
            _META_KEYS = {"_ok", "symbol", "period"}

            # --- 1) OI + 美元名义价值历史（含最新 bar） ---
            #    /futures/data/openInterestHist 比 /fapi/v1/openInterest 信息更全：
            #    提供 sumOpenInterest（合约数） + sumOpenInterestValue（USDT 名义价值），30 期趋势
            oih = self._get_json(
                f"{base_fapi}/futures/data/openInterestHist",
                params={"symbol": symbol, "period": period, "limit": str(limit)},
            )
            if oih:
                oi_rows = []
                for r in oih:
                    try:
                        oi_rows.append({
                            "time_s": int(float(r.get("timestamp", 0)) // 1000) if r.get("timestamp") else None,
                            "oi_contracts_sum": float(r.get("sumOpenInterest") or 0),
                            "oi_usd_notional_sum": float(r.get("sumOpenInterestValue") or 0),
                        })
                    except (TypeError, ValueError):
                        continue
                if oi_rows:
                    result["oi_history_usd"] = oi_rows
                    latest = oi_rows[-1]
                    result["oi_latest"] = {
                        "oi_contracts": latest["oi_contracts_sum"],
                        "oi_usd_notional": latest["oi_usd_notional_sum"],
                        "time_s": latest["time_s"],
                    }
                    # 7 期 OI 变化率（美元名义）
                    if len(oi_rows) >= 7:
                        o7 = oi_rows[-7]["oi_usd_notional_sum"] or 1.0
                        result["oi_change_7bar_pct"] = round(
                            (latest["oi_usd_notional_sum"] - o7) / o7 * 100, 3
                        )

            # --- 2) 资金费率历史 ---
            fr = self._get_json(
                f"{base_fapi}/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": str(limit)},
            )
            if fr:
                fr_list = []
                for r in fr:
                    fr_list.append({
                        "funding_time_s": int(r.get("fundingTime", 0)) // 1000,
                        "rate_pct": round(float(r.get("fundingRate") or 0) * 100, 5),  # 转 %
                        "mark_price": float(r.get("markPrice") or 0),
                    })
                result["funding_rate_history"] = fr_list
                if fr_list:
                    latest_fr = fr_list[-1]
                    avg7 = sum(x["rate_pct"] for x in fr_list[-min(7, len(fr_list)):]) / min(7, len(fr_list))
                    avg30 = sum(x["rate_pct"] for x in fr_list) / len(fr_list)
                    result["funding_rate_latest"] = latest_fr
                    result["funding_rate_avg7_pct"] = round(avg7, 5)
                    result["funding_rate_avg30_pct"] = round(avg30, 5)
                    # 正资金费率 > 0.01%/8h = 多头亢奋（多付空）
                    result["funding_pressured_long"] = bool(latest_fr["rate_pct"] > 0.05)

            # --- 3) 主动买卖比（Taker L/S） ---
            tls = self._get_json(
                f"{base_fapi}/futures/data/takerlongshortRatio",
                params={"symbol": symbol, "period": period, "limit": str(limit)},
            )
            if tls:
                ls_list = []
                for r in tls:
                    ls_list.append({
                        "time_s": int(float(r.get("timestamp", 0)) // 1000) if r.get("timestamp") else None,
                        "buy_sell_ratio": round(float(r.get("buySellRatio") or 0), 4),
                        "buy_vol": float(r.get("buyVol") or 0),
                        "sell_vol": float(r.get("sellVol") or 0),
                    })
                result["taker_ls_ratio_history"] = ls_list
                if ls_list:
                    latest = ls_list[-1]
                    avg7 = sum(x["buy_sell_ratio"] for x in ls_list[-min(7, len(ls_list)):]) / min(7, len(ls_list))
                    result["taker_ls_ratio_latest"] = latest
                    result["taker_ls_ratio_avg7"] = round(avg7, 4)
                    result["taker_pressure_bullish"] = bool(latest["buy_sell_ratio"] > 1.05)  # 主动买 > 卖 5%

            # --- 4) 全账户多空比 ---
            gals = self._get_json(
                f"{base_fapi}/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": period, "limit": str(limit)},
            )
            if gals:
                ar_list = []
                for r in gals:
                    ar_list.append({
                        "time_s": int(float(r.get("timestamp", 0)) // 1000) if r.get("timestamp") else None,
                        "long_short_account_ratio": round(float(r.get("longShortRatio") or 0), 4),
                        "long_account_pct": round(float(r.get("longAccount") or 0) * 100, 2),
                        "short_account_pct": round(float(r.get("shortAccount") or 0) * 100, 2),
                    })
                result["global_ls_account_ratio_history"] = ar_list
                if ar_list:
                    result["global_ls_account_ratio_latest"] = ar_list[-1]

            # --- 5) Top Trader 持仓多空比 ---
            ttls = self._get_json(
                f"{base_fapi}/futures/data/topLongShortPositionRatio",
                params={"symbol": symbol, "period": period, "limit": str(limit)},
            )
            if ttls:
                tp_list = []
                for r in ttls:
                    tp_list.append({
                        "time_s": int(float(r.get("timestamp", 0)) // 1000) if r.get("timestamp") else None,
                        "long_short_position_ratio": round(float(r.get("longShortRatio") or 0), 4),
                        "long_position_pct": round(float(r.get("longAccount") or 0) * 100, 2),
                        "short_position_pct": round(float(r.get("shortAccount") or 0) * 100, 2),
                    })
                result["top_trader_position_ratio_history"] = tp_list
                if tp_list:
                    result["top_trader_position_ratio_latest"] = tp_list[-1]
                    t7_avg = sum(x["long_short_position_ratio"] for x in tp_list[-min(7, len(tp_list)):]) / min(7, len(tp_list))
                    result["top_trader_position_ratio_avg7"] = round(t7_avg, 4)

            has_any = any(k for k in result.keys() if k not in _META_KEYS)
            result["_ok"] = has_any
            return result
        cache_key = f"bif_{symbol.lower()}_{period}_{limit}"
        return self._cached(cache_key, _fetch, ttl=900)

    def fetch_okx_public_derivatives(self, inst_id: str = "BTC-USDT-SWAP",
                                     ccy: str = "BTC",
                                     period_bar: str = "1H",
                                     limit: int = 30) -> Dict[str, Any]:
        """OKX V5 公共接口免费衍生品数据（零 key、公开 REST，Binance 的双备份）

        采集 4 大类数据：
          1) 当前 + 历史 OI（持仓量 美元名义价值）
          2) 当前 + 历史资金费率（含预测费率 nextFundingRate）
          3) 主动买卖成交量（Taker buy/sell volume）
          4) 合约多空账户比（Rubik，若需 key 则跳过不报错）

        period_bar: 1H/4H/8H/12H/1D
        """
        def _fetch() -> Dict[str, Any]:
            base = "https://www.okx.com"
            result: Dict[str, Any] = {"_ok": False, "inst_id": inst_id, "ccy": ccy}
            _META_KEYS = {"_ok", "inst_id", "ccy"}

            # --- 1) OI 历史 ---
            oih = self._get_json(
                f"{base}/api/v5/rubik/stat/contracts/open-interest-volume",
                params={"ccy": ccy, "period": period_bar, "limit": str(limit)},
            )
            if oih and oih.get("code") == "0" and oih.get("data"):
                oi_list = []
                for r in oih["data"]:
                    # OKX 格式: [ts, oi, oi_usd, vol, vol_ccy] （具体字段根据版本）
                    # 文档: ts, openInterest, openInterestUsd, volume, volumeCcy
                    oi_list.append({
                        "time_s": int(float(r[0])) // 1000 if len(r) > 0 and r[0] else None,
                        "oi_ccy": float(r[1]) if len(r) > 1 else 0.0,
                        "oi_usd": float(r[2]) if len(r) > 2 else 0.0,
                        "vol_ccy": float(r[3]) if len(r) > 3 else 0.0,
                    })
                result["oi_history_usd"] = oi_list
                if oi_list:
                    result["oi_latest_usd"] = oi_list[-1]["oi_usd"]
                    if len(oi_list) >= 7:
                        oi7_ago = oi_list[-7]["oi_usd"] or 1.0
                        result["oi_change_7bar_pct"] = round(
                            (oi_list[-1]["oi_usd"] - oi7_ago) / oi7_ago * 100, 3
                        )

            # --- 2) 资金费率历史 ---
            frh = self._get_json(
                f"{base}/api/v5/public/funding-rate-history",
                params={"instId": inst_id, "limit": str(limit)},
            )
            if frh and frh.get("code") == "0" and frh.get("data"):
                fr_list = []
                for r in frh["data"]:
                    fr_list.append({
                        "time_s": int(r.get("fundingTime", 0)) // 1000,
                        "rate_pct": round(float(r.get("fundingRate") or 0) * 100, 5),
                        "method": r.get("method"),
                    })
                # OKX 历史返回是新→旧，反转为升序
                fr_list.reverse()
                result["funding_rate_history"] = fr_list
                if fr_list:
                    latest_fr = fr_list[-1]
                    avg7 = sum(x["rate_pct"] for x in fr_list[-min(7, len(fr_list)):]) / min(7, len(fr_list))
                    result["funding_rate_latest"] = latest_fr
                    result["funding_rate_avg7_pct"] = round(avg7, 5)

            # --- 3) 当前资金费率（含预测） ---
            frc = self._get_json(
                f"{base}/api/v5/public/funding-rate",
                params={"instId": inst_id},
            )
            if frc and frc.get("code") == "0" and frc.get("data"):
                r0 = frc["data"][0]
                result["funding_rate_settlement"] = {
                    "inst_type": r0.get("instType"),
                    "current_rate_pct": round(float(r0.get("fundingRate") or 0) * 100, 5),
                    "next_rate_pct": round(float(r0.get("nextFundingRate") or 0) * 100, 5),
                    "next_settle_time_s": int(r0.get("nextFundingTime", 0)) // 1000,
                }

            # --- 4) Taker buy/sell volume（Rubik 端点，部分情况需 key，失败就跳） ---
            tv = self._get_json(
                f"{base}/api/v5/rubik/stat/contracts/taker-volume",
                params={"ccy": ccy, "period": period_bar, "limit": str(limit)},
            )
            if tv and tv.get("code") == "0" and tv.get("data"):
                tv_list = []
                for r in tv["data"]:
                    tv_list.append({
                        "time_s": int(float(r[0])) // 1000 if len(r) > 0 and r[0] else None,
                        "taker_buy_vol_usd": float(r[1]) if len(r) > 1 else 0.0,
                        "taker_sell_vol_usd": float(r[2]) if len(r) > 2 else 0.0,
                        "taker_buy_sell_ratio": (
                            round(float(r[1]) / float(r[2]), 4)
                            if len(r) > 2 and float(r[2]) > 0 else None
                        ),
                    })
                result["taker_volume_history"] = tv_list
                if tv_list:
                    result["taker_ls_ratio_latest"] = tv_list[-1]

            has_any = any(k for k in result.keys() if k not in _META_KEYS)
            result["_ok"] = has_any
            return result
        cache_key = f"okx_{ccy.lower()}_{inst_id.lower()}_{period_bar}_{limit}"
        return self._cached(cache_key, _fetch, ttl=900)

    def get_derivatives_snapshot(self) -> Dict[str, Any]:
        """合成衍生品快照：Binance Futures + OKX 双备份（零 key 免费版）

        返回统一消费字段，下游 regime 预测器不用区分来源：
          - oi_latest_usd, oi_change_7d_pct_proxy
          - funding_rate_latest_pct, funding_rate_trend_7d
          - taker_ls_ratio_latest, taker_ls_pressure
          - top_trader_position_ratio_latest（仅 Binance）
          - _sources_ok：哪些来源成功
        """
        bi = self.fetch_binance_futures_derivatives("BTCUSDT", period="4h", limit=30)
        okx = self.fetch_okx_public_derivatives("BTC-USDT-SWAP", ccy="BTC", period_bar="4H", limit=30)

        snap: Dict[str, Any] = {
            "_sources_ok": {
                "binance_futures": bi.get("_ok", False),
                "okx_public": okx.get("_ok", False),
            }
        }

        # --- OI：优先 Binance，兜底 OKX ---
        if bi.get("oi_latest") and bi["oi_latest"].get("oi_usd_notional"):
            snap["oi_latest_usd"] = round(bi["oi_latest"]["oi_usd_notional"], 0)
        elif okx.get("oi_latest_usd"):
            snap["oi_latest_usd"] = round(okx["oi_latest_usd"], 0)

        # --- OI 7 期变化率：优先 Binance，兜底 OKX ---
        if bi.get("oi_change_7bar_pct") is not None:
            # Binance 4h × 7 ≈ 28h，近似 1d 变化率
            snap["oi_change_7bar_pct"] = bi["oi_change_7bar_pct"]
        elif okx.get("oi_change_7bar_pct") is not None:
            snap["oi_change_7bar_pct"] = okx["oi_change_7bar_pct"]

        # --- 资金费率：优先 Binance ---
        if bi.get("funding_rate_latest"):
            snap["funding_rate_latest_pct"] = bi["funding_rate_latest"]["rate_pct"]
            snap["funding_rate_avg7_pct"] = bi.get("funding_rate_avg7_pct")
            snap["funding_rate_avg30_pct"] = bi.get("funding_rate_avg30_pct")
            if bi.get("funding_rate_avg7_pct") and bi.get("funding_rate_avg30_pct"):
                snap["funding_rate_trend_accel"] = round(
                    bi["funding_rate_avg7_pct"] - bi["funding_rate_avg30_pct"], 5
                )
        elif okx.get("funding_rate_latest"):
            snap["funding_rate_latest_pct"] = okx["funding_rate_latest"]["rate_pct"]
            snap["funding_rate_avg7_pct"] = okx.get("funding_rate_avg7_pct")

        if okx.get("funding_rate_settlement"):
            snap["funding_rate_next_predicted_pct"] = (
                okx["funding_rate_settlement"]["next_rate_pct"]
            )

        # --- 主动买卖比（Taker L/S）：Binance + OKX 对比 ---
        sources_ls = []
        if bi.get("taker_ls_ratio_latest"):
            sources_ls.append(bi["taker_ls_ratio_latest"]["buy_sell_ratio"])
        if okx.get("taker_ls_ratio_latest") and okx["taker_ls_ratio_latest"].get("taker_buy_sell_ratio"):
            sources_ls.append(okx["taker_ls_ratio_latest"]["taker_buy_sell_ratio"])
        if sources_ls:
            snap["taker_buy_sell_ratio_consensus"] = round(
                sum(sources_ls) / len(sources_ls), 4
            )
            snap["taker_pressure_bullish"] = bool(snap["taker_buy_sell_ratio_consensus"] > 1.05)
            snap["taker_pressure_bearish"] = bool(snap["taker_buy_sell_ratio_consensus"] < 0.95)

        # --- Top Trader 持仓多空比（仅 Binance 有免费版） ---
        if bi.get("top_trader_position_ratio_latest"):
            tt = bi["top_trader_position_ratio_latest"]
            snap["top_trader_ls_position_ratio"] = tt["long_short_position_ratio"]
            snap["top_trader_position_ratio_avg7"] = bi.get("top_trader_position_ratio_avg7")

        # --- 全账户多空比（仅 Binance 免费） ---
        if bi.get("global_ls_account_ratio_latest"):
            ga = bi["global_ls_account_ratio_latest"]
            snap["global_ls_account_ratio"] = ga["long_short_account_ratio"]
            snap["global_long_account_pct"] = ga["long_account_pct"]

        return snap

    # ============================================================
    # 10) 全市场爆仓单（Liquidations） — Binance Futures 主源
    #    FORCE_LIQUIDATION 级别零 Key 端点：形态预测器的 VOLATILE_DROP / REVERSAL 特征
    # ============================================================

    def fetch_binance_futures_liquidations(
        self,
        symbols: Optional[List[str]] = None,
        lookback_hours: int = 24,
        per_bucket_hours: int = 1,
    ) -> Dict[str, Any]:
        """Binance Futures 全市场强制平仓爆仓单（免费 / 无 Key / FORCE_LIQUIDATION）

        参数:
            symbols: 要采集的永续合约币种，None 时默认采 BTC/ETH + 5 板块 Top2 = 12 个高流动性币种
            lookback_hours: 回溯窗口，默认 24h（足够覆盖 1 日级 FOMO/暴跌 cascade）
            per_bucket_hours: 时间桶宽度（小时），默认 1h（用于可视化 / 级联检测）

        返回字段:
            _ok, _symbols_queried, _symbols_with_liq
            total_liq_usd_24h: 全币种合计爆仓美元名义
            long_liq_usd_24h:  多单爆仓（空头买入回补）
            short_liq_usd_24h: 空单爆仓（多头卖出止盈）
            long_short_liq_ratio: long/short 爆仓比（>1 = 多头被爆得多 → 杀多行情，<1 = 空头被爆 → 轧空）
            per_hour_buckets: [{hour_ts_s, long_usd, short_usd, total_usd}] × N 桶
            max_1h_liq_usd:     峰值 1h 爆仓量（级联识别）
            cascade_hours:      连续≥3桶递增的小时数（爆仓 cascade 严重度）
            panic_score_0_to_1: 归一化到 [0,1] 的爆仓恐慌指数（形态预测器直接消费）
        """
        # 默认 12 个高流动性币种（BTC/ETH + 5 板块 Top2）
        DEFAULT_SYMBOLS = [
            "BTCUSDT", "ETHUSDT",
            "UNIUSDT", "AAVEUSDT",      # DEFI Top2
            "FETUSDT", "RNDRUSDT",      # AI_WEB3 Top2
            "ONDOUSDT", "POLYXUSDT",    # RWA Top2
            "DOGEUSDT", "WIFUSDT",      # MEME Top2
            "SOLUSDT", "ARBUSDT",       # L2 Top2
        ]
        syms = symbols or DEFAULT_SYMBOLS

        def _fetch() -> Dict[str, Any]:
            base_fapi = "https://fapi.binance.com"
            result: Dict[str, Any] = {"_ok": False, "_symbols_queried": list(syms)}
            _META_KEYS = {"_ok", "_symbols_queried", "_symbols_with_liq"}
            end_s = int(time.time())
            start_s = end_s - lookback_hours * 3600
            # 时间桶：按 (ts // bucket_s) 聚合
            bucket_s = per_bucket_hours * 3600
            buckets: Dict[int, Dict[str, float]] = {}
            any_api_reached = False  # 哪怕只有 1 个币种成功返回列表（哪怕空）也算 API 可达

            symbols_with_liq = 0
            for sym in syms:
                try:
                    raw = self._get_json(
                        f"{base_fapi}/fapi/v1/allForceOrders",
                        params={"symbol": sym, "limit": "500",
                                "startTime": str(start_s * 1000),
                                "endTime": str(end_s * 1000)},
                    )
                except Exception:
                    raw = None
                if isinstance(raw, list):
                    any_api_reached = True
                else:
                    continue
                rows = [r for r in raw if isinstance(r, dict) and
                        (str(r.get("origType", "")).startswith("FORCE_LIQUIDATION") or
                         r.get("closePosition") is True or
                         r.get("reduceOnly") is True)]
                if not rows:
                    continue
                symbols_with_liq += 1
                for r in rows:
                    try:
                        ts_s = int(r.get("time", r.get("updateTime", 0))) // 1000
                        if ts_s < start_s or ts_s > end_s:
                            continue
                        px = float(r.get("avgPrice", r.get("price", 0)) or 0)
                        qty = float(r.get("executedQty", r.get("origQty", 0)) or 0)
                        usd_val = abs(px * qty)
                        # side=BUY  = 多单爆仓后（空头回补买入）
                        # side=SELL = 空单爆仓后（多头止盈卖出）
                        side = str(r.get("side", "")).upper()
                        bk = ts_s // bucket_s
                        if bk not in buckets:
                            buckets[bk] = {"long_usd": 0.0, "short_usd": 0.0}
                        if side == "BUY":
                            buckets[bk]["long_usd"] += usd_val
                        elif side == "SELL":
                            buckets[bk]["short_usd"] += usd_val
                        else:
                            buckets[bk]["long_usd"] += usd_val * 0.5
                            buckets[bk]["short_usd"] += usd_val * 0.5
                    except (TypeError, ValueError):
                        continue

            result["_symbols_with_liq"] = symbols_with_liq
            if not buckets:
                # 低波动无爆仓是合法状态：返回零值 + CALM
                # _ok=True 前提是 API 确实可达（any_api_reached == True 或有币种有爆仓）
                zero_ok = bool(any_api_reached or symbols_with_liq > 0)
                result.update({
                    "total_liq_usd_24h": 0.0,
                    "long_liq_usd_24h": 0.0,
                    "short_liq_usd_24h": 0.0,
                    "long_short_liq_ratio": None,
                    "per_hour_buckets": [],
                    "max_1h_liq_usd": 0.0,
                    "cascade_hours": 0,
                    "panic_score_0_to_1": 0.0,
                    "panic_level": "CALM",
                    "_api_reached": any_api_reached,
                })
                result["_ok"] = zero_ok
                return result
            else:
                bucket_rows = []
                total_long = 0.0
                total_short = 0.0
                for bk in sorted(buckets.keys()):
                    b = buckets[bk]
                    hour_ts_s = bk * bucket_s
                    total_long += b["long_usd"]
                    total_short += b["short_usd"]
                    bucket_rows.append({
                        "hour_ts_s": hour_ts_s,
                        "hour_utc": datetime.fromtimestamp(hour_ts_s, tz=timezone.utc).strftime("%Y-%m-%d %H:00"),
                        "long_usd": round(b["long_usd"], 2),
                        "short_usd": round(b["short_usd"], 2),
                        "total_usd": round(b["long_usd"] + b["short_usd"], 2),
                    })
                total_all = total_long + total_short
                ls_ratio = round(total_long / total_short, 4) if total_short > 1e-6 else (
                    10.0 if total_long > 0 else None
                )
                max_1h = max((b["total_usd"] for b in bucket_rows), default=0.0)

                # cascade_hours: 连续≥3桶递增的最大连续段
                totals_series = [b["total_usd"] for b in bucket_rows]
                cascade = 0
                cur_run = 1
                for i in range(1, len(totals_series)):
                    if totals_series[i] > totals_series[i - 1]:
                        cur_run += 1
                        cascade = max(cascade, cur_run)
                    else:
                        cur_run = 1
                if cascade < 3:
                    cascade = 0

                # panic_score_0_to_1: 非线性归一化，避免极端值把分数钉在 1
                # 参考 OKX 公开研究：BTC 合约单币种 24h 爆仓 ≥ $1 亿属于典型 panic
                # 这里多币种合计，阈值调高到 $3 亿；log10 压缩
                import math
                THRESH_B = 3e8  # $300M
                if total_all <= 0:
                    pscore = 0.0
                else:
                    pscore = min(1.0, max(0.0,
                        (math.log10(max(total_all, 1e6)) - 6.0) /
                        (math.log10(THRESH_B) - 6.0)
                    ))
                # cascade 加成：3+ 级联连爆 → 分数 × 1.25，5+ → × 1.5，上限 1
                if cascade >= 5:
                    pscore = min(1.0, pscore * 1.5)
                elif cascade >= 3:
                    pscore = min(1.0, pscore * 1.25)

                if pscore >= 0.80:
                    plevel = "EXTREME_PANIC"
                elif pscore >= 0.55:
                    plevel = "PANIC"
                elif pscore >= 0.30:
                    plevel = "TENSE"
                elif pscore >= 0.10:
                    plevel = "MILD"
                else:
                    plevel = "CALM"

                result.update({
                    "total_liq_usd_24h": round(total_all, 2),
                    "long_liq_usd_24h": round(total_long, 2),
                    "short_liq_usd_24h": round(total_short, 2),
                    "long_short_liq_ratio": ls_ratio,
                    "per_hour_buckets": bucket_rows,
                    "max_1h_liq_usd": round(max_1h, 2),
                    "cascade_hours": cascade,
                    "panic_score_0_to_1": round(pscore, 4),
                    "panic_level": plevel,
                })

            has_data = any(k for k in result.keys() if k not in _META_KEYS)
            if has_data:
                result["_api_reached"] = any_api_reached or symbols_with_liq > 0
            result["_ok"] = has_data
            return result
        cache_key = f"biliq_{len(syms)}syms_{lookback_hours}h_{per_bucket_hours}b"
        return self._cached(cache_key, _fetch, ttl=300)  # 爆仓更实时，5 分钟缓存

    # ============================================================
    # 11) 全市场爆仓单 — OKX V5 备份（部署环境带代理可用）
    # ============================================================

    def fetch_okx_public_liquidations(
        self,
        ccy_list: Optional[List[str]] = None,
        inst_type: str = "SWAP",
        lookback_hours: int = 24,
        per_bucket_hours: int = 1,
    ) -> Dict[str, Any]:
        """OKX V5 公共爆仓单（/api/v5/public/liquidation-orders，免费零 Key）

        字段定义（与 Binance 版保持一致，便于统一合成）：
          - posSide="long"  被清算 → 多单爆仓，对应 side=BUY（回补）
          - posSide="short" 被清算 → 空单爆仓，对应 side=SELL（止盈）
        """
        CCYS = ccy_list or ["USDT"]  # USDT 本位覆盖全市场
        bucket_s = per_bucket_hours * 3600
        end_s = int(time.time())
        start_s = end_s - lookback_hours * 3600

        def _fetch() -> Dict[str, Any]:
            base = "https://www.okx.com"
            result: Dict[str, Any] = {"_ok": False, "_ccys_queried": list(CCYS)}
            _META_KEYS = {"_ok", "_ccys_queried"}
            buckets: Dict[int, Dict[str, float]] = {}
            any_api_reached = False

            for ccy in CCYS:
                raw = self._get_json(
                    f"{base}/api/v5/public/liquidation-orders",
                    params={"instType": inst_type, "ccy": ccy,
                            "limit": "100", "state": "filled"},
                )
                if raw and raw.get("code") == "0":
                    any_api_reached = True
                else:
                    continue
                for r in raw.get("data", []) or []:
                    try:
                        ts_ms = r.get("ts")
                        ts_s = int(float(ts_ms)) // 1000 if ts_ms else 0
                        if ts_s < start_s or ts_s > end_s:
                            continue
                        sz = float(r.get("sz") or 0)
                        bk_px = float(r.get("bkPx") or 0)
                        usd_val = abs(sz * bk_px)
                        pos_side = str(r.get("posSide", "")).lower()
                        bk = ts_s // bucket_s
                        if bk not in buckets:
                            buckets[bk] = {"long_usd": 0.0, "short_usd": 0.0}
                        if pos_side == "long":
                            buckets[bk]["long_usd"] += usd_val
                        elif pos_side == "short":
                            buckets[bk]["short_usd"] += usd_val
                        else:
                            # net 模式按 side 推测
                            side = str(r.get("side", "")).lower()
                            if side == "buy":
                                buckets[bk]["long_usd"] += usd_val
                            elif side == "sell":
                                buckets[bk]["short_usd"] += usd_val
                    except (TypeError, ValueError):
                        continue

            if not buckets:
                zero_ok = any_api_reached
                result.update({
                    "total_liq_usd_24h": 0.0,
                    "long_liq_usd_24h": 0.0,
                    "short_liq_usd_24h": 0.0,
                    "long_short_liq_ratio": None,
                    "per_hour_buckets": [],
                    "max_1h_liq_usd": 0.0,
                    "cascade_hours": 0,
                    "panic_score_0_to_1": 0.0,
                    "panic_level": "CALM",
                    "_api_reached": any_api_reached,
                    "_ok": zero_ok,
                })
                return result
            else:
                bucket_rows = []
                tl, ts_ = 0.0, 0.0
                for bk in sorted(buckets.keys()):
                    b = buckets[bk]
                    hts = bk * bucket_s
                    tl += b["long_usd"]; ts_ += b["short_usd"]
                    bucket_rows.append({
                        "hour_ts_s": hts,
                        "hour_utc": datetime.fromtimestamp(hts, tz=timezone.utc).strftime("%Y-%m-%d %H:00"),
                        "long_usd": round(b["long_usd"], 2),
                        "short_usd": round(b["short_usd"], 2),
                        "total_usd": round(b["long_usd"] + b["short_usd"], 2),
                    })
                total_all = tl + ts_
                ls_ratio = round(tl / ts_, 4) if ts_ > 1e-6 else (10.0 if tl > 0 else None)
                max_1h = max((b["total_usd"] for b in bucket_rows), default=0.0)
                totals_s = [b["total_usd"] for b in bucket_rows]
                cascade, cur_run = 0, 1
                for i in range(1, len(totals_s)):
                    if totals_s[i] > totals_s[i - 1]:
                        cur_run += 1; cascade = max(cascade, cur_run)
                    else:
                        cur_run = 1
                if cascade < 3:
                    cascade = 0
                import math
                THRESH_B = 3e8
                pscore = 0.0 if total_all <= 0 else min(1.0, max(0.0,
                    (math.log10(max(total_all, 1e6)) - 6.0) /
                    (math.log10(THRESH_B) - 6.0)))
                if cascade >= 5: pscore = min(1.0, pscore * 1.5)
                elif cascade >= 3: pscore = min(1.0, pscore * 1.25)
                if pscore >= 0.80: plevel = "EXTREME_PANIC"
                elif pscore >= 0.55: plevel = "PANIC"
                elif pscore >= 0.30: plevel = "TENSE"
                elif pscore >= 0.10: plevel = "MILD"
                else: plevel = "CALM"
                result.update({
                    "total_liq_usd_24h": round(total_all, 2),
                    "long_liq_usd_24h": round(tl, 2),
                    "short_liq_usd_24h": round(ts_, 2),
                    "long_short_liq_ratio": ls_ratio,
                    "per_hour_buckets": bucket_rows,
                    "max_1h_liq_usd": round(max_1h, 2),
                    "cascade_hours": cascade,
                    "panic_score_0_to_1": round(pscore, 4),
                    "panic_level": plevel,
                    "_api_reached": any_api_reached,
                })

            result["_ok"] = bool(any(k for k in result.keys() if k not in _META_KEYS))
            return result
        cache_key = f"okxliq_{inst_type.lower()}_{len(CCYS)}_{lookback_hours}h"
        return self._cached(cache_key, _fetch, ttl=300)

    # ============================================================
    # 12) 爆仓恐慌合成快照（Binance 主 + OKX 备双源一致化）
    # ============================================================

    def _estimate_liquidation_panic_proxy(self) -> Dict[str, Any]:
        """二阶爆仓代理估计器（当真实爆仓端点被网络 gating 时的 fallback）

        利用当前 100% 可用的免费 Binance 端点推导爆仓恐慌近似：
          1) OI 突变：4h OI 若环比下跌≥5%  ≈ 大规模被强平去杠杆
          2) Taker 主动买卖极端失衡：比率<0.7 或>1.4 ≈ 单边强平驱动
          3) 资金费率突变：绝对值跳升 ≈ 极端行情
        综合输出 proxy_panic_score_0_to_1 + proxy_level + 字段标注 _provenance="proxy"
        """
        bi = self.fetch_binance_futures_derivatives("BTCUSDT", period="4h", limit=30)
        result: Dict[str, Any] = {"_provenance": "proxy_from_working_derivatives"}

        score = 0.0
        # 1) OI 4h 环比变化率（7 期 ≈ 28h 内的 OI 差值）
        oi_change_7 = bi.get("oi_change_7bar_pct") or 0.0
        result["proxy_oi_7bar_change_pct"] = round(oi_change_7, 3)
        if oi_change_7 <= -15:
            score += 0.60  # OI 骤降 15%+ → 极端去杠杆
        elif oi_change_7 <= -8:
            score += 0.35
        elif oi_change_7 <= -5:
            score += 0.20
        elif oi_change_7 <= -3:
            score += 0.10
        elif oi_change_7 >= 8:
            # OI 暴增且伴随多头主动买 = FOMO 建仓（对应爆仓逼空的前置）
            score += 0.10

        # 2) Taker B/S 极端失衡
        t7 = bi.get("taker_ls_ratio_avg7") or 1.0
        result["proxy_taker_ls_ratio_avg7"] = round(t7, 4)
        if t7 <= 0.65:
            score += 0.40  # 主动卖远多于买 → 暴跌强平链
        elif t7 <= 0.80:
            score += 0.20
        elif t7 >= 1.40:
            score += 0.25  # 主动买远多于卖 → 轧空 / FOMO
        elif t7 >= 1.20:
            score += 0.10

        # 3) 资金费率异常高（正或负）
        fr7 = abs(bi.get("funding_rate_avg7_pct") or 0)
        result["proxy_funding_rate_abs_avg7_pct"] = round(fr7, 5)
        if fr7 >= 0.05:  # 8h 0.05% = 年化约 54% → 典型投机拥挤
            score += 0.25
        elif fr7 >= 0.02:
            score += 0.10
        elif fr7 >= 0.01:
            score += 0.05

        # 4) Top Trader 持仓 L/S 极端
        tt7 = bi.get("top_trader_position_ratio_avg7") or 1.0
        result["proxy_top_trader_ls_avg7"] = round(tt7, 4)
        if tt7 >= 3.0 or tt7 <= 0.40:
            score += 0.15  # 全市场一致 → 反向爆仓风险大
        elif tt7 >= 2.2 or tt7 <= 0.55:
            score += 0.08

        pscore = min(1.0, score)
        if pscore >= 0.80: plevel = "EXTREME_PANIC"
        elif pscore >= 0.55: plevel = "PANIC"
        elif pscore >= 0.30: plevel = "TENSE"
        elif pscore >= 0.10: plevel = "MILD"
        else: plevel = "CALM"
        result["proxy_panic_score_0_to_1"] = round(pscore, 4)
        result["proxy_panic_level"] = plevel

        # 形态 hint
        if pscore >= 0.55 and (t7 < 0.85 or oi_change_7 < -5):
            result["proxy_regime_hint"] = "VOLATILE_DROP"
        elif pscore >= 0.4 and t7 > 1.25:
            result["proxy_regime_hint"] = "FOMO_RALLY"
        elif pscore >= 0.70:
            result["proxy_regime_hint"] = "VOLATILE_DROP"
        elif pscore >= 0.30 and t7 > 1.15:
            result["proxy_regime_hint"] = "REVERSAL"
        else:
            result["proxy_regime_hint"] = "NONE"
        return result

    def get_liquidation_panic_snapshot(self) -> Dict[str, Any]:
        """形态预测器直接消费的爆仓形态特征

        输出:
          _sources_ok: {binance, okx}
          _data_provenance: "real_liquidation_api" | "proxy_fallback" | "none"
          total_liq_usd_24h: 最近 24h 合计爆仓量
          long_short_liq_ratio: L/S 爆仓比（形态耦合）
          panic_score_0_to_1: [0,1] 恐慌指数
          panic_level:     CALM / MILD / TENSE / PANIC / EXTREME_PANIC
          cascade_hours:   连续爆仓小时数（≥3 说明级联）
          regime_hint:     给 8 态分类器的建议 — VOLATILE_DROP / FOMO_RALLY / NONE
          proxy_fallback:  若真实 API 被网络 gating，注入二阶代理估计器字段
        """
        bi = self.fetch_binance_futures_liquidations()
        okx = self.fetch_okx_public_liquidations()

        snap: Dict[str, Any] = {
            "_sources_ok": {
                "binance_futures": bi.get("_ok", False),
                "okx_public": okx.get("_ok", False),
            }
        }
        # 优先 Binance（字段更全），OKX 作为纯覆盖备份
        pri = bi if bi.get("_ok") else (okx if okx.get("_ok") else None)
        if pri is not None:
            snap["_data_provenance"] = "real_liquidation_api"
            for k in ("total_liq_usd_24h", "long_liq_usd_24h", "short_liq_usd_24h",
                      "long_short_liq_ratio", "panic_score_0_to_1", "panic_level",
                      "cascade_hours", "max_1h_liq_usd"):
                if k in pri:
                    snap[k] = pri[k]

            # regime_hint：把爆仓结构映射到 8 态分类建议（软标签，非强制）
            pscore = snap.get("panic_score_0_to_1", 0) or 0
            ls = snap.get("long_short_liq_ratio") or 1.0
            cascade = snap.get("cascade_hours", 0) or 0
            if pscore >= 0.55 and ls > 1.5 and cascade >= 3:
                snap["regime_hint"] = "VOLATILE_DROP"
            elif pscore >= 0.4 and ls < 0.67 and cascade >= 3:
                snap["regime_hint"] = "FOMO_RALLY"
            elif pscore >= 0.70:
                snap["regime_hint"] = "VOLATILE_DROP"
            elif pscore >= 0.30 and ls > 1.2:
                snap["regime_hint"] = "REVERSAL"
            else:
                snap["regime_hint"] = "NONE"
            return snap

        # --- 两个真实 API 都被网络 gating → 二阶代理估计器作为 fallback ---
        proxy = self._estimate_liquidation_panic_proxy()
        snap["_data_provenance"] = "proxy_fallback"
        snap["proxy_fallback"] = proxy
        # 代理字段也镜像到顶层，让下游消费不用区分真实/代理
        snap["panic_score_0_to_1"] = proxy["proxy_panic_score_0_to_1"]
        snap["panic_level"] = proxy["proxy_panic_level"]
        snap["regime_hint"] = proxy["proxy_regime_hint"]
        # 二阶代理没有真实爆仓金额和级联小时，设 None 让下游区分
        snap["total_liq_usd_24h"] = None
        snap["long_liq_usd_24h"] = None
        snap["short_liq_usd_24h"] = None
        snap["long_short_liq_ratio"] = None
        snap["cascade_hours"] = None
        snap["max_1h_liq_usd"] = None
        return snap

    # ============================================================
    # 13) 期权隐含波动率快照 — OKX V5 opt-summary（零 Key，免费）
    #     ATM IV / 25Δ Put-Call Skew / Crypto VIX 代理
    # ============================================================

    def fetch_okx_options_iv_snapshot(self, inst_families: Optional[List[str]] = None
                                      ) -> Dict[str, Any]:
        """OKX 免费期权隐含波动率快照（/api/v5/public/opt-summary）

        形态预测器的波动率分层 + REVERSAL / FOMO_RALLY 信号核心特征：
          - **ATM IV**（level=0）：当前市场对未来波动的一致预期（≈ VIX）
          - **25Δ Put-Call Skew**：尾部恐慌度（Put IV 显著高于 Call = 市场恐惧尾部下跌）
          - **Crypto VIX Proxy**：BTC/ETH ATM IV 的加权平均（全市场波动代理）

        参数:
            inst_families: 期权链标的族，默认 ["BTC-USD", "ETH-USD"]（覆盖加密 90%+ 期权成交量）
        """
        fams = inst_families or ["BTC-USD", "ETH-USD"]

        def _fetch() -> Dict[str, Any]:
            base = "https://www.okx.com"
            result: Dict[str, Any] = {"_ok": False, "_families_queried": list(fams)}
            _META_KEYS = {"_ok", "_families_queried", "crypto_vix_proxy_pct",
                          "btc_eth_atm_iv_average_pct"}
            by_fam: Dict[str, Dict[str, Any]] = {}

            for fam in fams:
                raw = self._get_json(
                    f"{base}/api/v5/public/opt-summary",
                    params={"instFamily": fam},
                )
                if not raw or raw.get("code") != "0" or not raw.get("data"):
                    continue
                rows = raw["data"]
                # opt-summary 每行 = 一个 delta 档位 / level 的一组 call/put 买卖 IV
                # 按 delta / level 找 ATM（level=0 或 |delta| 最接近 0.50）、25Δ Call / 25Δ Put
                records = []
                ts_s = 0
                for r in rows:
                    try:
                        delta = float(r.get("delta") or 0)
                        level = int(r.get("level", -999))
                        ts_ms = r.get("ts")
                        if ts_ms:
                            ts_s = int(float(ts_ms)) // 1000
                        # volLv 是综合 IV；bid/ask vol 也可取 mid
                        def _mid(bid, ask):
                            b = float(bid or 0); a = float(ask or 0)
                            return (b + a) / 2.0 if (b > 0 and a > 0) else 0.0
                        call_mid_iv = _mid(r.get("callBidVol"), r.get("callAskVol"))
                        put_mid_iv  = _mid(r.get("putBidVol"),  r.get("putAskVol"))
                        composite   = float(r.get("volLv") or 0)
                        records.append({
                            "delta": delta,
                            "level": level,
                            "call_mid_iv_pct": round(call_mid_iv * 100, 3) if call_mid_iv > 0 else round(composite * 100, 3),
                            "put_mid_iv_pct":  round(put_mid_iv  * 100, 3) if put_mid_iv  > 0 else round(composite * 100, 3),
                            "composite_iv_pct": round(composite * 100, 3),
                        })
                    except (TypeError, ValueError):
                        continue
                if not records:
                    continue

                # --- ATM：|delta| 最接近 0.50，优先选 level=0 ---
                atm = min(records, key=lambda x: (
                    0 if x["level"] == 0 else 1,
                    abs(abs(x["delta"]) - 0.50)
                ))
                atm_iv_pct = (atm["call_mid_iv_pct"] + atm["put_mid_iv_pct"]) / 2.0
                if atm_iv_pct <= 0:
                    atm_iv_pct = atm["composite_iv_pct"]

                # --- 25Δ Put / Call：|delta| 最接近 0.25 ---
                c25 = min(records, key=lambda x: abs(x["delta"] - 0.25))
                p25 = min(records, key=lambda x: abs(x["delta"] - (-0.25)))
                call25_iv = c25["call_mid_iv_pct"] if c25["call_mid_iv_pct"] > 0 else c25["composite_iv_pct"]
                put25_iv  = p25["put_mid_iv_pct"]  if p25["put_mid_iv_pct"]  > 0 else p25["composite_iv_pct"]
                pc_skew_25d_pct = round(put25_iv - call25_iv, 3)

                # --- 10Δ（极虚值尾部） Put-Call Skew：黑天鹅定价 ---
                c10 = min(records, key=lambda x: abs(x["delta"] - 0.10))
                p10 = min(records, key=lambda x: abs(x["delta"] - (-0.10)))
                c10iv = c10["call_mid_iv_pct"] if c10["call_mid_iv_pct"] > 0 else c10["composite_iv_pct"]
                p10iv = p10["put_mid_iv_pct"]  if p10["put_mid_iv_pct"]  > 0 else p10["composite_iv_pct"]
                tail_skew_10d_pct = round(p10iv - c10iv, 3)

                by_fam[fam] = {
                    "snapshot_time_s": ts_s,
                    "n_levels": len(records),
                    "atm": {
                        "iv_pct": round(atm_iv_pct, 3),
                        "delta_used": atm["delta"],
                        "level_used": atm["level"],
                    },
                    "delta_25": {
                        "call_iv_pct": round(call25_iv, 3),
                        "put_iv_pct": round(put25_iv, 3),
                        "pc_skew_pct": pc_skew_25d_pct,
                    },
                    "delta_10_tail": {
                        "call_iv_pct": round(c10iv, 3),
                        "put_iv_pct": round(p10iv, 3),
                        "pc_skew_pct": tail_skew_10d_pct,
                    },
                    "interpretation": self._interpret_option_skew(
                        atm_iv_pct, pc_skew_25d_pct, tail_skew_10d_pct
                    ),
                }

            if by_fam:
                result["by_family"] = by_fam
                # Crypto VIX Proxy: BTC 权重 0.70，ETH 权重 0.30（按期权实际成交量占比）
                btc = by_fam.get("BTC-USD", {}).get("atm", {}).get("iv_pct")
                eth = by_fam.get("ETH-USD", {}).get("atm", {}).get("iv_pct")
                if btc and eth:
                    cvix = round(btc * 0.70 + eth * 0.30, 3)
                    result["crypto_vix_proxy_pct"] = cvix
                    result["btc_eth_atm_iv_average_pct"] = round((btc + eth) / 2.0, 3)
                elif btc:
                    result["crypto_vix_proxy_pct"] = btc
                # regime hint（仅期权侧）
                hints = []
                for fam, d in by_fam.items():
                    interp = d.get("interpretation", {})
                    if interp.get("regime_hint"):
                        hints.append(interp["regime_hint"])
                if hints:
                    # 简单投票：多数胜出
                    from collections import Counter
                    vc = Counter(hints)
                    result["regime_hint_majority"] = vc.most_common(1)[0][0]

            result["_ok"] = any(k for k in result.keys() if k not in _META_KEYS)
            if not result["_ok"]:
                result["_provenance"] = "okx_network_gated_no_proxy_available"
            else:
                result["_provenance"] = "okx_public_opt_summary_api"
            return result
        cache_key = f"okxiv_{'_'.join(sorted(fams)).lower()}"
        return self._cached(cache_key, _fetch, ttl=600)  # 期权 IV 变化慢，10 分钟缓存

    @staticmethod
    def _interpret_option_skew(atm_iv_pct: float,
                               skew25_pct: float,
                               skew10_pct: float) -> Dict[str, Any]:
        """把 ATM IV + PC Skew 翻译成形态预测器可消费的标签

        传统金融经验法则：
          - SKEW（Put IV - Call IV）> +3% → 市场明显为尾部下跌买保护 → 恐惧
          - SKEW < -2% → 市场为上涨买看涨期权（或 Covered Call 卖家压低 Call IV）→ 贪婪 / FOMO
          - ATM IV 水平: <40% = 低波平静，40~70% = 正常波动，70~100% = 高波动，>100% = 极端
        """
        # IV 水平
        if atm_iv_pct >= 100: iv_level = "EXTREME"
        elif atm_iv_pct >= 70: iv_level = "HIGH"
        elif atm_iv_pct >= 40: iv_level = "NORMAL"
        else: iv_level = "LOW"

        # 25Δ 偏度情绪
        if skew25_pct >= 3.0: skew_sentiment = "FEAR_TAIL_PROTECTION"
        elif skew25_pct >= 1.0: skew_sentiment = "CAUTIOUS"
        elif skew25_pct >= -1.0: skew_sentiment = "NEUTRAL"
        elif skew25_pct >= -2.5: skew_sentiment = "GREEDY_CALL_BUYING"
        else: skew_sentiment = "FOMO_RALLY_CALL_BINGE"

        # 10Δ 尾部偏度（是否有人为黑天鹅付高价）
        tail_risk_premium = skew10_pct - skew25_pct  # 尾部额外溢价（10Δ 比 25Δ 更斜多少）
        if tail_risk_premium >= 3.0: tail_risk = "EXTREME_BLACK_SWAN_HEDGE"
        elif tail_risk_premium >= 1.0: tail_risk = "MODERATE_TAIL_HEDGE"
        elif tail_risk_premium >= -1.0: tail_risk = "FLAT"
        else: tail_risk = "UPSIDE_TAIL_BET_FOMO"

        # 形态软标签建议（结合 IV + Skew）
        if iv_level in ("HIGH", "EXTREME") and skew_sentiment in (
            "FEAR_TAIL_PROTECTION", "CAUTIOUS"):
            regime = "VOLATILE_DROP"
        elif iv_level in ("HIGH", "EXTREME") and skew_sentiment in (
            "GREEDY_CALL_BUYING", "FOMO_RALLY_CALL_BINGE"):
            regime = "FOMO_RALLY"
        elif iv_level == "EXTREME":
            regime = "REVERSAL"
        elif skew_sentiment == "FEAR_TAIL_PROTECTION":
            regime = "REVERSAL"
        elif skew_sentiment == "FOMO_RALLY_CALL_BINGE":
            regime = "FOMO_RALLY"
        elif iv_level in ("NORMAL", "LOW") and skew_sentiment == "NEUTRAL":
            regime = "RANGE_BOUND"
        else:
            regime = "NONE"

        return {
            "iv_level": iv_level,
            "skew_25d_sentiment": skew_sentiment,
            "tail_10d_premium_type": tail_risk,
            "tail_premium_extra_pct": round(tail_risk_premium, 3),
            "regime_hint": regime,
        }

    # ============================================================
    # 14) 综合入口：一次采集 Layer 0 + Layer 1 全部免费数据
    # ============================================================

    def collect_global(self) -> Dict[str, Any]:
        """一次调用，形态预测器所需所有免费全局 / 板块 / 美股 / 情绪数据"""
        def _compute():
            started = time.time()
            sources: Dict[str, str] = {}
            snapshot: Dict[str, Any] = {}

            # 1) BTC 日线（基础中的基础）
            daily = self.fetch_btc_daily_ohlc(limit=365)
            if daily:
                latest = daily[-1]
                snapshot["btc_latest"] = {
                    "t": latest["t"],
                    "date_utc": datetime.fromtimestamp(latest["t"], tz=timezone.utc).strftime("%Y-%m-%d"),
                    "O": latest["O"], "H": latest["H"], "L": latest["L"], "C": latest["C"],
                    "vol_btc": latest["V"],
                    "vol_usdt_qv": latest.get("QV"),
                }
                # 常用均线（日线 MA128、周线 MA200 ≈ 1400 个日线不够，这里只给 MA20/50/128；周线 MA200 下游按需自取）
                closes = [r["C"] for r in daily]
                for n in (20, 50, 128):
                    if len(closes) >= n:
                        snapshot[f"btc_ma{n}"] = round(sum(closes[-n:]) / n, 2)
                sources["btc_daily"] = "binance_free"
            else:
                sources["btc_daily"] = "failed"

            # 2) CoinGecko 宏观（BTC.D、稳定币总市值）
            gm = self.fetch_global_macro()
            if gm.get("_ok"):
                for k, v in gm.items():
                    if k != "_ok":
                        snapshot[k] = v
                sources["coingecko_global"] = "free_tier_ok"
            else:
                sources["coingecko_global"] = gm.get("err", "failed")

            # 3) Fear & Greed
            fg = self.fetch_fear_greed()
            if fg.get("ok"):
                snapshot["fear_greed"] = fg
                sources["fear_greed"] = "alternative_me_free"
            else:
                sources["fear_greed"] = fg.get("err", "failed")

            # 4) 5 板块资金权重免费代理（龙头 24h 涨跌幅 + 成交额加权）
            sectors = self.get_sector_proxy_weights()
            snapshot["sector_proxy_weights"] = sectors
            sources["sector_proxy"] = "binance_24h_ticker_free"

            # 5) 8 主流币广度（MA20 同向比例 + 20d 收益比例）
            br = self.get_mainstream_breadth(lookback_days=20)
            snapshot["mainstream_breadth"] = br
            sources["mainstream_breadth"] = (
                "binance_klines_free" if br.get("ok") else br.get("reason", "failed")
            )

            # 6) BTC vs 美股/黄金/美债 相关性
            corr = self.get_btc_us_assets_correlations(window_days=30)
            if corr.get("ok"):
                snapshot["btc_us_assets_correlations"] = corr
                sources["correlations"] = "self_computed_pearson_free"
            else:
                sources["correlations"] = corr.get("err", "failed")

            # 7) BTC ETF 价格代理（免费 yfinance：IBIT/FBTC/ARKB）
            etf = self.fetch_btc_etf_price_proxy()
            if etf.get("ok"):
                snapshot["btc_etf_price_proxy"] = etf
                sources["btc_etf_proxy"] = "yfinance_free_ibit_fbtc_arkb"
            else:
                sources["btc_etf_proxy"] = "yfinance_fetch_failed_or_missing"

            # 8) 衍生品快照（OI / 资金费率 / 多空比 / 主动买卖） — Binance Futures + OKX 双备份
            deriv = self.get_derivatives_snapshot()
            snapshot["derivatives"] = deriv
            so = deriv.get("_sources_ok", {})
            parts = []
            if so.get("binance_futures"):
                parts.append("binance_futures_free")
            if so.get("okx_public"):
                parts.append("okx_public_free")
            sources["derivatives"] = "+".join(parts) if parts else "all_failed"

            # 9) 爆仓恐慌快照（Binance Futures 主 + OKX 备 + 二阶代理 fallback）
            liq = self.get_liquidation_panic_snapshot()
            snapshot["liquidation_panic"] = liq
            so_liq = liq.get("_sources_ok", {})
            lp = []
            if so_liq.get("binance_futures"):
                lp.append("binance_futures_free")
            if so_liq.get("okx_public"):
                lp.append("okx_public_free")
            provenance = liq.get("_data_provenance") or "none"
            if provenance == "proxy_fallback":
                lp.append("proxy_via_binance_derivatives")  # 用 OI/Taker/FR/Top LS 推导
            sources["liquidation_panic"] = "+".join(lp) if lp else ("none: data_provenance=" + provenance)
            # 提取顶层便捷消费字段（形态预测器不用再下钻 dict）
            if liq.get("panic_score_0_to_1") is not None:
                snapshot["liq_panic_score_0_to_1"] = liq["panic_score_0_to_1"]
                snapshot["liq_panic_level"] = liq.get("panic_level")
            if liq.get("total_liq_usd_24h") is not None:
                snapshot["liq_total_24h_usd"] = liq["total_liq_usd_24h"]
            if liq.get("regime_hint"):
                snapshot["liq_regime_hint"] = liq["regime_hint"]

            # 10) 期权 IV 快照（OKX opt-summary） — ATM IV / PC Skew / Crypto VIX 代理
            #     当前网络若无法访问 OKX，返回 _ok=False，不影响其他字段
            opts = self.fetch_okx_options_iv_snapshot()
            snapshot["options_iv"] = opts
            so_opts = opts.get("_ok", False)
            sources["options_iv"] = "okx_public_opt_summary_free" if so_opts else "okx_unreachable_or_no_options"
            # 顶层便捷消费字段（无论是否成功都注入 = None，让下游消费不用 dict.get 判断 key 是否存在）
            snapshot["crypto_vix_proxy_pct"] = opts.get("crypto_vix_proxy_pct")
            snapshot["options_regime_hint"] = opts.get("regime_hint_majority")
            snapshot["btc_option_atm_iv_pct"] = None
            snapshot["btc_option_pc_skew_25d_pct"] = None
            snapshot["btc_option_iv_level"] = None
            snapshot["btc_option_skew_sentiment"] = None
            snapshot["eth_option_atm_iv_pct"] = None
            snapshot["eth_option_pc_skew_25d_pct"] = None
            snapshot["eth_option_iv_level"] = None
            snapshot["eth_option_skew_sentiment"] = None
            # BTC / ETH 单品种 ATM IV 和 Skew 直接拿顶层（若有真实数据则覆盖 None）
            bf = opts.get("by_family", {})
            for ticker, key in (("BTC-USD", "btc"), ("ETH-USD", "eth")):
                fam = bf.get(ticker, {})
                if fam.get("atm"):
                    snapshot[f"{key}_option_atm_iv_pct"] = fam["atm"]["iv_pct"]
                if fam.get("delta_25"):
                    snapshot[f"{key}_option_pc_skew_25d_pct"] = fam["delta_25"]["pc_skew_pct"]
                interp = fam.get("interpretation", {})
                if interp.get("iv_level"):
                    snapshot[f"{key}_option_iv_level"] = interp["iv_level"]
                if interp.get("skew_25d_sentiment"):
                    snapshot[f"{key}_option_skew_sentiment"] = interp["skew_25d_sentiment"]

            # 元信息
            snapshot["_sources"] = sources
            snapshot["_collected_at_s"] = int(time.time())
            snapshot["_latency_ms"] = int((time.time() - started) * 1000)
            snapshot["_feature_count"] = len([k for k in snapshot.keys() if not k.startswith("_")])
            return snapshot
        return self._cached("global_snapshot", _compute, ttl=self.CACHE_TTL)

    def clear_cache(self, key: Optional[str] = None) -> None:
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()
