"""
CoinScanner — OKX 50+ 币种扫描器

设计哲学:
  易经系统仅跟踪 22 币，但 OKX 上有 50+ 活跃 USDT 永续合约。
  扫描器周期性获取全市场数据，筛选出有积极信号的币种，
  按信号强度排序，供进化系统选择最优路径。

  置信度 → 仓位映射:
    高置信 (≥0.7)  → 正常仓位 (Kelly × vol_scalar)
    中置信 (0.4-0.7) → 半仓
    低置信 (0.2-0.4) → 1/4 仓（探索性开仓，不禁止）
    极低 (<0.2)   → 不开仓

  数据少 → 置信度低 → 仓位小，但**不禁止开仓**（探索价值）
"""
from __future__ import annotations

import math
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CoinScanner:
    """
    OKX 全市场币种扫描器

    扫描流程:
      1. 获取所有 USDT 永续合约（按 24h 成交量过滤）
      2. 对每币计算信号强度（动量 + 量比 + 波动率）
      3. 按信号强度排序，返回 Top N 候选
      4. 为每个候选计算置信度 → 仓位映射
    """

    # 24h 成交量下限（USDT），过滤流动性不足的币
    MIN_VOLUME_24H = 5_000_000  # 500 万 USDT

    # 扫描结果缓存 TTL
    CACHE_TTL = 300  # 5 分钟

    # 美股代币白名单（OKX 上的美股/贵金属代币化合约）
    # 非白名单默认视为加密币
    US_STOCK_COINS: frozenset[str] = frozenset({
        # 科技
        "AAPL", "AMZN", "GOOGL", "NVDA", "MSFT", "TSLA", "META", "NFLX", "AMD",
        "INTC", "TSM", "AVGO", "QCOM", "ORCL", "CRM", "ADBE", "SAP", "NOW",
        "INTU", "AMAT", "LRCX", "KLAC", "MU", "ARM", "SMCI", "PLTR", "SNOW",
        "UBER", "ABNB", "PYPL", "SHOP", "SQ", "ROKU", "ZM", "SNAP", "PINS",
        "DASH", "COIN", "MSTR", "HOOD", "SOFI", "RIVN", "LCID", "NIO", "XPEV",
        "LI", "BABA", "PDD", "JD", "BIDU", "NIO", "TME", "WB", "YMM", "ZTO",
        # 金融
        "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK",
        # 消费
        "WMT", "PG", "KO", "PEP", "MCD", "NKE", "SBUX", "TGT", "LOW", "HD",
        "COST", "KR", "DG", "DLTR", "ROST", "BBY", "AZO",
        # 医疗
        "JNJ", "PFE", "UNH", "CVS", "LLY", "MRK", "ABBV", "TMO", "ABT", "DHR",
        # 工业
        "BA", "CAT", "GE", "MMM", "HON", "LMT", "RTX", "DE", "UNP", "UPS",
        "FDX",
        # 能源
        "XOM", "CVX", "COP", "SLB", "EOG",
        # 通信
        "DIS", "CMCSA", "T", "VZ", "WBD", "PARA", "FOX",
        # 半导体（韩国等）
        "SKHYNIX", "SNDK", "SPCX",
        # 汽车
        "F", "GM", "TM", "RACE", "HMC",
        # 贵金属/商品
        "XAU", "XAG", "XPT", "XPD",
        # 其他
        "BMNR", "CRCL", "GME", "AMC", "BB", "NOK", "F",
    })

    # 美股代币在扫描结果中的目标占比（50%）
    US_STOCK_RATIO = 0.5

    def __init__(self, okx_client: Any):
        self._client = okx_client
        self._cache: dict[str, Any] | None = None
        self._cache_ts: float = 0.0

    def scan(self, top_n: int = 20, force: bool = False) -> list[dict[str, Any]]:
        """
        扫描全市场，返回信号最强的 top_n 个币种。

        Returns:
            [
                {
                    "symbol": str,
                    "inst_id": str,
                    "signal": float,        # [-1, +1] 正=看多
                    "confidence": float,    # [0, 1]
                    "position_mult": float, # 仓位乘数 [0, 1]
                    "metrics": {
                        "momentum": float,
                        "vol_ratio": float,
                        "volatility": float,
                        "volume_24h": float,
                    },
                },
                ...
            ]
        """
        # 缓存检查
        if not force and self._cache is not None:
            if time.time() - self._cache_ts < self.CACHE_TTL:
                return self._cache[:top_n]

        try:
            # 1. 获取所有 USDT 永续合约 ticker
            tickers = self._get_all_swap_tickers()
            if not tickers:
                return []

            # 2. 按流动性过滤
            # 美股代币成交量普遍较低，单独降低门槛
            us_stock_min_vol = 300_000  # 美股 30 万 U（美股代币在 OKX 流动性较低）
            liquid = [
                t for t in tickers
                if t.get("vol24h_usd", 0) >= (
                    us_stock_min_vol
                    if t["inst_id"].replace("-USDT-SWAP", "") in self.US_STOCK_COINS
                    else self.MIN_VOLUME_24H
                )
            ]

            # 3. 计算每币信号
            candidates = []
            for t in liquid:
                inst_id = t["inst_id"]
                symbol = inst_id.replace("-USDT-SWAP", "")
                try:
                    signal, metrics = self._calc_signal(inst_id, symbol)
                    if signal is not None:
                        confidence = self._calc_confidence(metrics)
                        position_mult = self._confidence_to_position(confidence)
                        candidates.append({
                            "symbol": symbol,
                            "inst_id": inst_id,
                            "signal": round(signal, 4),
                            "confidence": round(confidence, 4),
                            "position_mult": round(position_mult, 4),
                            "metrics": metrics,
                        })
                except Exception as e:
                    logger.debug("[FO] scan coin %s: %s", symbol, e)
                    continue

            # 4. 分类：美股 vs 加密
            us_stock_cands = [c for c in candidates if c["symbol"] in self.US_STOCK_COINS]
            crypto_cands = [c for c in candidates if c["symbol"] not in self.US_STOCK_COINS]

            # 各自按 |signal| × confidence 排序
            us_stock_cands.sort(
                key=lambda x: abs(x["signal"]) * x["confidence"], reverse=True,
            )
            crypto_cands.sort(
                key=lambda x: abs(x["signal"]) * x["confidence"], reverse=True,
            )

            # 5. 配额平衡：美股占 US_STOCK_RATIO(50%)，加密占剩余
            us_stock_n = int(top_n * self.US_STOCK_RATIO)
            crypto_n = top_n - us_stock_n

            # 如果某类数量不足，从另一类补足
            us_stock_pick = us_stock_cands[:us_stock_n]
            crypto_pick = crypto_cands[:crypto_n]
            if len(us_stock_pick) < us_stock_n:
                crypto_pick = crypto_cands[:crypto_n + (us_stock_n - len(us_stock_pick))]
            if len(crypto_pick) < crypto_n:
                us_stock_pick = us_stock_cands[:us_stock_n + (crypto_n - len(crypto_pick))]

            # 合并并按信号强度重新排序
            balanced = us_stock_pick + crypto_pick
            balanced.sort(
                key=lambda x: abs(x["signal"]) * x["confidence"], reverse=True,
            )

            self._cache = balanced
            self._cache_ts = time.time()
            return balanced[:top_n]

        except Exception as e:
            logger.warning("[FO] scan crash: %s", e)
            return []

    # ------------------------------------------------------------------
    # OKX API 封装
    # ------------------------------------------------------------------

    def _get_all_swap_tickers(self) -> list[dict[str, Any]]:
        """获取所有 USDT 永续合约的 24h ticker 数据"""
        try:
            # 尝试用 OKX tickers 接口
            get_tickers = getattr(self._client, "get_tickers", None)
            if callable(get_tickers):
                resp = get_tickers(instType="SWAP")
            else:
                resp = self._client._get(
                    "/api/v5/market/tickers", {"instType": "SWAP"}, auth=False
                )

            if not resp or resp.get("code") != "0":
                return []

            tickers = []
            for item in resp.get("data", []):
                inst_id = item.get("instId", "")
                if not inst_id.endswith("-USDT-SWAP"):
                    continue
                try:
                    vol24h = float(item.get("vol24h", 0))
                    last = float(item.get("last", 0))
                    tickers.append({
                        "inst_id": inst_id,
                        "vol24h_usd": vol24h * last,
                        "last": last,
                    })
                except (ValueError, TypeError):
                    continue
            return tickers
        except Exception as e:
            logger.debug("[FO] get_all_swap_tickers: %s", e)
            return []

    def _calc_signal(self, inst_id: str, symbol: str) -> tuple[float | None, dict]:
        """
        计算单币信号强度（轻量化，不依赖完整数据管线）。

        信号 = 0.5×动量 + 0.3×量比 + 0.2×波动率方向
        """
        try:
            resp = self._client.get_kline(inst_id, bar="1H", limit=24)
            if not resp or not resp.get("ok"):
                return None, {}

            candles = list(reversed(resp.get("candles", [])))
            if len(candles) < 20:
                return None, {}

            closes = [float(c["c"]) for c in candles]
            vols = [float(c["vol"]) for c in candles]

            # 1. 动量 (24h 收益率)
            momentum = (closes[-1] - closes[0]) / closes[0] if closes[0] > 0 else 0
            momentum_score = math.tanh(momentum * 20)  # 5% → tanh(1)=0.76

            # 2. 量比
            vol_5 = sum(vols[-5:]) / 5
            vol_20 = sum(vols[-20:]) / 20
            vol_ratio = vol_5 / max(vol_20, 1e-9)
            vol_score = math.tanh((vol_ratio - 1.0) * 1.5)  # 1.5x → 0.66

            # 3. 波动率方向（近期波动 vs 历史）
            recent_std = self._std(closes[-6:])
            hist_std = self._std(closes[-20:])
            vol_direction = 1.0 if recent_std > hist_std else -0.5
            vol_expand_score = math.tanh((recent_std / max(hist_std, 1e-9) - 1.0) * 2)

            # 合成信号
            signal = 0.5 * momentum_score + 0.3 * vol_score + 0.2 * vol_expand_score
            signal = max(-1.0, min(1.0, signal))

            metrics = {
                "momentum": round(momentum, 6),
                "vol_ratio": round(vol_ratio, 4),
                "volatility": round(recent_std / max(closes[-1], 1e-9), 6),
                "vol_expand": vol_direction > 0,
                "volume_24h": sum(vols[-24:]) * closes[-1] if len(vols) >= 24 else 0,
            }
            return signal, metrics

        except Exception as e:
            logger.debug("[FO] calc_signal %s: %s", symbol, e)
            return None, {}

    def _calc_confidence(self, metrics: dict) -> float:
        """
        计算置信度。
        数据越充分、信号越强 → 置信度越高。
        数据少 → 置信度低（但不禁止开仓）。
        """
        # 量比确认度
        vol_ratio = metrics.get("vol_ratio", 1.0)
        vol_conf = min(1.0, vol_ratio / 2.0)  # 量比2.0 → 1.0

        # 波动率确认度
        vol_expand = metrics.get("vol_expand", False)
        vol_expand_conf = 0.6 if vol_expand else 0.3

        # 动量强度确认度
        momentum = abs(metrics.get("momentum", 0))
        mom_conf = min(1.0, momentum / 0.05)  # 5% 动量 → 1.0

        # 数据充分度（这里简化为常量，实际可加入历史数据量）
        data_conf = 0.5  # 扫描器只有 24h 数据，置信度中等

        confidence = 0.3 * vol_conf + 0.2 * vol_expand_conf + 0.3 * mom_conf + 0.2 * data_conf
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _confidence_to_position(confidence: float) -> float:
        """
        置信度 → 仓位乘数映射。

        核心原则: 低置信也可开仓（探索价值），但仓位小。
        - ≥0.7 → 1.0 (满仓)
        - 0.4-0.7 → 0.5 (半仓)
        - 0.2-0.4 → 0.25 (1/4 仓，探索)
        - <0.2 → 0.0 (不开仓)
        """
        if confidence >= 0.7:
            return 1.0
        elif confidence >= 0.4:
            return 0.5
        elif confidence >= 0.2:
            return 0.25
        else:
            return 0.0

    @staticmethod
    def _std(data: list[float]) -> float:
        if len(data) < 2:
            return 0.0
        mean = sum(data) / len(data)
        var = sum((x - mean) ** 2 for x in data) / len(data)
        return math.sqrt(var)
