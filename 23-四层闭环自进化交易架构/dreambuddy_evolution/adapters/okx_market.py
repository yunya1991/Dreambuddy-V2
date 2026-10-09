"""
OKXMarketAdapter — 从 OKX REST API 获取行情数据，计算 R 向量所需字段
SPEC §2.1

FAIL-OPEN: 每个 API 调用独立 try/except，失败字段不包含在返回 dict 中
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class OKXMarketAdapter:
    """OKX 行情适配器 — 获取 K 线 + Ticker + 持仓比"""

    def __init__(self, okx_client: Any) -> None:
        self._client = okx_client
        # TTL 缓存：key -> (timestamp, data)，命中时跳过 API 调用
        self._cache: dict[str, tuple[float, dict]] = {}
        # stale 降级缓存：key -> (timestamp, data)，全失败时返回上次成功响应
        self._last_good: dict[str, tuple[float, dict]] = {}
        self._ttl: float = 60.0
        self._max_retries: int = 3

    def fetch(self, symbol: str, inst_id: str, limit: int = 200) -> dict[str, Any]:
        """
        获取完整行情数据。

        Returns dict with keys (失败的 key 不包含):
            close, high, low, volume (np.ndarray)
            ma_200, fib_retrace_0786 (float | NaN)
            bid_ask_spread_bps (float)
            vol_5, vol_20 (float)
            okx_positions (dict | None)
            symbol (str)
        """
        result: dict[str, Any] = {"symbol": symbol}
        kline_data = self._fetch_kline(inst_id, limit)
        result.update(kline_data)

        ticker_data = self._fetch_ticker(inst_id)
        result.update(ticker_data)

        positions = self._fetch_positions(inst_id)
        if positions is not None:
            result["okx_positions"] = positions

        # OKX open interest → capital_flow 基础
        oi_data = self._fetch_open_interest(inst_id)
        result.update(oi_data)

        return result

    # ------------------------------------------------------------------ K线
    def _fetch_kline(self, inst_id: str, limit: int = 200) -> dict[str, Any]:
        """获取 K 线并计算 ma_200, fib, vol_5, vol_20

        韧性：TTL 缓存命中直接返回；否则最多重试 _max_retries 次；
        4xx 错误立即返回不重试；全失败时回退到 _last_good stale 缓存。
        """
        cache_key = f"kline:{inst_id}"

        # TTL 缓存命中 → 跳过 API 调用
        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if time.time() - ts < self._ttl:
                return cached

        out: dict[str, Any] = {}

        for _attempt in range(self._max_retries):
            try:
                resp = self._client.get_kline(inst_id, bar="1H", limit=limit)
            except Exception as e:
                logger.warning("[FO] kline fetch error (attempt %d/%d): %s",
                               _attempt + 1, self._max_retries, e)
                continue

            if not resp or not resp.get("ok"):
                # 4xx 错误立即返回，不重试
                err_code = resp.get("error_code") if resp else None
                if err_code is not None and 400 <= err_code < 500:
                    logger.warning("[FO] kline 4xx (%s), no retry", err_code)
                    return {}
                logger.warning("[FO] kline fetch fail (attempt %d/%d): %s",
                               _attempt + 1, self._max_retries,
                               resp.get("error", "") if resp else "no resp")
                continue

            candles = resp.get("candles", [])
            if not candles:
                continue

            # OKX candles 降序(新→旧)，反转为升序(旧→新)
            candles_asc = list(reversed(candles))

            try:
                close_arr = np.array([float(c["c"]) for c in candles_asc], dtype=float)
                open_arr = np.array([float(c["o"]) for c in candles_asc], dtype=float)
                high_arr = np.array([float(c["h"]) for c in candles_asc], dtype=float)
                low_arr = np.array([float(c["l"]) for c in candles_asc], dtype=float)
                vol_arr = np.array([float(c["vol"]) for c in candles_asc], dtype=float)
            except Exception as e:
                logger.warning("[FO] kline parse error (attempt %d/%d): %s",
                               _attempt + 1, self._max_retries, e)
                continue

            out["close"] = close_arr
            out["open"] = open_arr
            out["high"] = high_arr
            out["low"] = low_arr
            out["volume"] = vol_arr

            # ma_200
            if close_arr.size >= 200:
                out["ma_200"] = float(np.mean(close_arr[-200:]))
            elif close_arr.size >= 50:
                # 降级：用可用长度均值，ResistanceVector 会走 fib fallback
                out["ma_200"] = float(np.mean(close_arr))
            else:
                out["ma_200"] = float("nan")

            # fib_retrace_0786: min + 0.786 × (max - min)
            if close_arr.size >= 30:
                lo = float(np.min(close_arr[-200:]))
                hi = float(np.max(close_arr[-200:]))
                out["fib_retrace_0786"] = lo + 0.786 * (hi - lo)
            else:
                out["fib_retrace_0786"] = float("nan")

            # vol_5 / vol_20
            if vol_arr.size >= 5:
                out["vol_5"] = float(np.mean(vol_arr[-5:]))
            if vol_arr.size >= 20:
                out["vol_20"] = float(np.mean(vol_arr[-20:]))

            # 成功 → 更新 TTL 缓存 + last_good
            now = time.time()
            self._cache[cache_key] = (now, out)
            self._last_good[cache_key] = (now, out)
            return out

        # 全部重试失败 → stale 降级
        if cache_key in self._last_good:
            ts, stale = self._last_good[cache_key]
            age = time.time() - ts
            logger.warning("[FO-raw-stale] returning stale kline for %s, age=%.0fs",
                           inst_id, age)
            return stale

        return {}

    # ------------------------------------------------------------------ Ticker
    def _fetch_ticker(self, inst_id: str) -> dict[str, Any]:
        """获取 ticker → bid_ask_spread_bps"""
        out: dict[str, Any] = {}
        try:
            resp = self._client.get_ticker(inst_id)
            if not resp or not resp.get("ok"):
                return out

            bid = float(resp.get("bid", 0))
            ask = float(resp.get("ask", 0))
            mid = (bid + ask) / 2.0
            if mid > 0:
                out["bid_ask_spread_bps"] = (ask - bid) / mid * 10000.0
        except Exception as e:
            logger.warning("[FO] _fetch_ticker crash: %s", e)

        return out

    # ------------------------------------------------------------------ 持仓比
    def _fetch_positions(self, inst_id: str) -> dict[str, float] | None:
        """
        获取多空持仓比。3 级降级：
        1. OKX public long-short-ratio (推荐)
        2. OKX get_positions (仅自身账户 — 不推荐)
        3. None → R_up/R_down 走 0.5 兜底
        """
        try:
            # Level 1: 尝试 OKX public long-short-ratio
            ratio = self._fetch_long_short_ratio(inst_id)
            if ratio is not None:
                return ratio

            # Level 2: get_positions (降级，仅自身账户)
            resp = self._client.get_positions(inst_id)
            if resp and resp.get("ok"):
                # 解析持仓 — 注意这是账户级，非全市场
                pos_data = resp.get("positions", {})
                if isinstance(pos_data, dict):
                    return pos_data

        except Exception as e:
            logger.warning("[FO] _fetch_positions crash: %s", e)

        return None

    def _fetch_long_short_ratio(self, inst_id: str) -> dict[str, float] | None:
        """OKX 公开多空持仓比接口

        优先调用 okx_client.get_long_short_ratio()；若不存在则降级到 _get。
        """
        try:
            # Level 1: 优先用 okx_client 命名方法（若有）
            get_lsr = getattr(self._client, "get_long_short_ratio", None)
            if callable(get_lsr):
                resp = get_lsr(inst_id, period="1H")
                if resp and resp.get("ok"):
                    lr = resp.get("long_ratio", 0.5)
                    sr = resp.get("short_ratio", 1.0 - lr)
                    return {"long": float(lr), "short": float(sr)}

            # Level 2: 降级用 _get 直连 OKX API
            # 端点已迁移: /api/v5/public/long-short-ratio (404) →
            #   /api/v5/rubik/stat/contracts/long-short-account-ratio
            # 参数: ccy (BTC-USDT-SWAP → BTC), 响应: data=[[ts, longShortRatio],...]
            _get = getattr(self._client, "_get", None)
            if _get is None:
                return None

            ccy = inst_id.split("-")[0] if inst_id else ""
            if not ccy:
                return None

            r = _get("/api/v5/rubik/stat/contracts/long-short-account-ratio",
                     {"ccy": ccy, "period": "1H"}, auth=False)
            if not r or r.get("code") != "0" or not r.get("data"):
                return None

            d = r["data"][0]  # [ts, longShortRatio]
            lsr = float(d[1])  # longShortRatio = longCount/shortCount
            long_ratio = lsr / (1.0 + lsr)
            short_ratio = 1.0 / (1.0 + lsr)
            return {"long": long_ratio, "short": short_ratio}

        except Exception as e:
            logger.debug("[FO] long-short-ratio not available: %s", e)
            return None

    # ---------------------------------------------------------- Open Interest
    def _fetch_open_interest(self, inst_id: str) -> dict[str, Any]:
        """
        获取 OKX 未平仓合约（OI）→ 用于计算 capital_flow。

        优先调用 okx_client.get_open_interest()；若不存在则降级到 _get。
        Returns dict (失败为空):
            open_interest: float        — 当前 OI（张）
            oi_change_pct: float        — OI 变化百分比（[-1, +1]，归一化到 capital_flow 范围）
        """
        out: dict[str, Any] = {}
        try:
            oi = None

            # Level 1: 优先用 okx_client 命名方法（若有）
            get_oi = getattr(self._client, "get_open_interest", None)
            if callable(get_oi):
                resp = get_oi(inst_id)
                if resp and resp.get("ok"):
                    oi = resp.get("open_interest", 0)

            # Level 2: 降级用 _get 直连 OKX API
            if oi is None:
                _get = getattr(self._client, "_get", None)
                if _get is None:
                    return out

                r = _get("/api/v5/public/open-interest",
                         {"instId": inst_id}, auth=False)
                if not r or r.get("code") != "0" or not r.get("data"):
                    return out

                oi = float(r["data"][0].get("oi", 0))

            if not oi or oi <= 0:
                return out

            out["open_interest"] = oi

            # 归一化到 capital_flow 范围 [-1, +1]
            oi_log = math.log10(max(oi, 1))
            # 假设 OI 在 10^4 ~ 10^8 范围 → 归一化到 [-1, +1]
            normalized = (oi_log - 6.0) / 2.0  # center at 1e6
            out["oi_change_pct"] = max(-1.0, min(1.0, normalized))

        except Exception as e:
            logger.debug("[FO] open-interest not available: %s", e)

        return out
