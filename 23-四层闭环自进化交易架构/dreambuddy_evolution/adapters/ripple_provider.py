"""
RippleDataProvider — 涟漪引擎关联币数据提供器
SPEC §6 / Phase 4

为 R2（关联币方向一致性）和 R3（板块扩散）提供关联币 4H 方向数据。

设计原则（候选→质量度量→过滤管线）:
1. 候选生成: 获取每枚关联币 4H K线（30 根）
2. 质量度量: 方向=close vs MA20, 强度=|close-MA20|/MA20, 量比=vol_5/vol_20
3. 过滤: 仅保留 confirmed=True 的币种（趋势强度达标 + 成交量确认）

R2: 核心关联币（BTC↔ETH↔SOL）紧确认（强度≥0.01 + 放量）
R3: 板块大盘币宽扩散（强度≥0.005，不强制放量）

FAIL-OPEN: 任一币种获取失败 → 跳过该币种，不影响其他
"""
from __future__ import annotations

import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

# R2 核心关联币映射（双向）
_R2_RELATED: dict[str, list[str]] = {
    "BTC": ["ETH", "SOL"],
    "ETH": ["BTC", "SOL"],
    "SOL": ["BTC", "ETH"],
}

# R3 板块大盘币（加密大盘）
_R3_SECTOR: dict[str, list[str]] = {
    "BTC": ["ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"],
    "ETH": ["BTC", "SOL", "BNB", "XRP", "ADA", "DOGE"],
    "SOL": ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE"],
}

# 默认 fallback（未配置币种用一组大盘币）
_DEFAULT_SECTOR = ["BTC", "ETH", "SOL", "BNB", "XRP"]

# R2 紧确认参数
_R2_MIN_STRENGTH = 0.01   # 趋势强度 ≥ 1%
_R2_REQUIRE_VOLUME = True  # 必须放量确认

# R3 宽扩散参数
_R3_MIN_STRENGTH = 0.005   # 趋势强度 ≥ 0.5%
_R3_REQUIRE_VOLUME = False  # 不强制放量（板块扩散看广度）

# K线获取参数
_FETCH_LIMIT = 30
_MA_PERIOD = 20
_VOL_SHORT = 5
_VOL_LONG = 20


class RippleDataProvider:
    """涟漪关联币数据提供器"""

    def __init__(self, okx_client: Any, cache_ttl: float = 300.0) -> None:
        self._client = okx_client
        self._kline_cache: dict[str, tuple[list, float]] = {}  # inst_id -> (candles, ts)
        self._cache_ttl = cache_ttl

    def get_ripple_hits(
        self, symbol: str, ess_direction: str
    ) -> dict[str, dict[str, float]]:
        """
        计算 R2 和 R3 的 hits/candidates。

        Args:
            symbol: 目标币种 (BTC/ETH/SOL)
            ess_direction: ESS 最优方向 (long/short)

        Returns:
            {
                "R2": {"hits": int, "candidates": int},
                "R3": {"hits": int, "candidates": int},
            }
            若 ess_direction 为空 → hits=0, candidates=1
        """
        ess_dir = (ess_direction or "").lower()
        if ess_dir not in ("long", "short"):
            return {
                "R2": {"hits": 0, "candidates": 1},
                "R3": {"hits": 0, "candidates": 1},
            }

        r2_coins = _R2_RELATED.get(symbol.upper(), [])
        r3_coins = _R3_SECTOR.get(symbol.upper(), _DEFAULT_SECTOR)

        r2_hits, r2_cands = self._count_direction_match(
            r2_coins, ess_dir,
            min_strength=_R2_MIN_STRENGTH,
            require_volume=_R2_REQUIRE_VOLUME,
        )
        r3_hits, r3_cands = self._count_direction_match(
            r3_coins, ess_dir,
            min_strength=_R3_MIN_STRENGTH,
            require_volume=_R3_REQUIRE_VOLUME,
        )

        return {
            "R2": {"hits": r2_hits, "candidates": max(r2_cands, 1)},
            "R3": {"hits": r3_hits, "candidates": max(r3_cands, 1)},
        }

    # ------------------------------------------------------------------ 核心
    def _count_direction_match(
        self,
        coins: list[str],
        ess_dir: str,
        min_strength: float,
        require_volume: bool,
    ) -> tuple[int, int]:
        """
        统计关联币中 4H 方向与 ess_dir 一致的数量（仅计入 confirmed 币种）。

        Pipeline:
        1. 候选生成: fetch 4H signal per coin
        2. 质量过滤: strength ≥ min_strength AND (vol_confirm OR not require_volume)
        3. 方向匹配: confirmed direction == ess_dir → hit

        Returns:
            (hits, candidates) — candidates=成功获取且 confirmed 的币种数
        """
        hits = 0
        candidates = 0

        for coin in coins:
            signal = self._fetch_4h_signal(coin)
            if signal is None:
                continue  # FAIL-OPEN: 数据获取失败

            # 质量过滤
            if not self._is_confirmed(signal, min_strength, require_volume):
                continue  # 趋势太弱或无量，不计入候选

            candidates += 1
            if signal["direction"] == ess_dir:
                hits += 1

        return hits, candidates

    @staticmethod
    def _is_confirmed(
        signal: dict, min_strength: float, require_volume: bool
    ) -> bool:
        """质量过滤：趋势强度达标 + 成交量确认（可选）"""
        strength = float(signal.get("strength", 0))
        if strength < min_strength:
            return False
        if require_volume:
            vol_ratio = float(signal.get("vol_ratio", 0))
            if vol_ratio < 1.0:
                return False
        return True

    def _fetch_4h_signal(self, symbol: str) -> dict | None:
        """
        获取指定币种 4H 趋势信号。

        Pipeline:
        1. 获取 30 根 4H K线
        2. 计算 MA20
        3. 方向 = close > MA20 ? "long" : "short"
        4. 强度 = |close - MA20| / MA20（归一化，cap at 0.1）
        5. 量比 = vol_5 / vol_20

        Returns:
            {
                "direction": "long" | "short",
                "strength": float in [0, 0.1],
                "vol_ratio": float,
            }
            None — 获取失败或数据不足
        """
        try:
            inst_id = f"{symbol}-USDT-SWAP"

            # TTL 缓存检查（多币共享关联币 K 线数据）
            cached = self._kline_cache.get(inst_id)
            if cached is not None:
                candles, ts = cached
                if time.time() - ts < self._cache_ttl:
                    return self._calc_4h_signal(candles)

            resp = self._client.get_kline(inst_id, bar="4H", limit=_FETCH_LIMIT)
            if not resp or not resp.get("ok"):
                return None

            candles = resp.get("candles", [])
            if len(candles) < _MA_PERIOD + 1:
                return None  # 数据不足，无法计算 MA20

            # 写入缓存
            self._kline_cache[inst_id] = (candles, time.time())
            return self._calc_4h_signal(candles)

        except Exception as e:
            logger.debug("[FO] ripple 4h signal fail for %s: %s", symbol, e)
            return None

    def _calc_4h_signal(self, candles: list) -> dict | None:
        """从 candles 计算 4H 趋势信号（供缓存命中时复用）"""
        try:
            # OKX candles 降序(新→旧): candles[0]=最新
            closes = [float(c["c"]) for c in candles]
            vols = [float(c["vol"]) for c in candles]

            # MA20（用最新 20 根的均值）
            ma20 = sum(closes[:_MA_PERIOD]) / _MA_PERIOD
            if ma20 <= 0:
                return None

            close_last = closes[0]
            direction = "long" if close_last > ma20 else "short"

            # 趋势强度（归一化到 [0, 0.1]）
            raw_strength = abs(close_last - ma20) / ma20
            strength = min(raw_strength, 0.1)

            # 量比 vol_5 / vol_20
            vol_5 = sum(vols[:_VOL_SHORT]) / _VOL_SHORT
            vol_20 = sum(vols[:_VOL_LONG]) / _VOL_LONG
            vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1.0

            return {
                "direction": direction,
                "strength": strength,
                "vol_ratio": vol_ratio,
            }
        except Exception:
            return None
