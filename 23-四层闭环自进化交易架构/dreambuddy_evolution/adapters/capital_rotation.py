"""
CapitalRotationAdapter — 资金轮动检测器

案例抽象（UNI/PUMP 2026-09-04）:
  UNI 链上手续费增长 → Robinhood 资金流入 → UNI/ARB 大涨
  → Meme 资金转移 → Pump 资金出逃 → PUMP 代币下跌

底层逻辑:
  1. 定义竞品组（同赛道代币，资金会在其间轮动）
  2. 对组内每币计算资金流得分（量比+动量+OI）
  3. 比较本币 vs 组均值得出相对强度（capital_rotation）
  4. 正=资金净流入（看多），负=资金净流出（看空）

输出: capital_rotation ∈ [-1, +1]，可直接增强 R_flow 维度
FAIL-OPEN: 任何异常 → 返回中性值 0.0
"""
from __future__ import annotations

import math
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)


# 竞品组定义（同赛道代币，资金会在其间轮动）
# 每个币可属于多个组，取所有组中最强的轮动信号
COMPETITOR_GROUPS: dict[str, list[str]] = {
    "large_cap": ["BTC", "ETH", "SOL", "BNB", "XRP"],
    "layer1": ["ETH", "SOL", "ARB", "OP", "AVAX"],
    "dex_platform": ["UNI", "SUSHI", "CAKE"],
    "meme_platform": ["PUMP", "UNI"],
    "layer2": ["ARB", "OP"],
}


class CapitalRotationAdapter:
    """资金轮动检测器 — 从竞对代币相对资金流推导目标代币强度"""

    def __init__(self, okx_client: Any, cache_ttl: float = 300.0):
        self._client = okx_client
        self._cache: dict[str, tuple[float, float]] = {}  # coin -> (score, timestamp)
        self._cache_ttl = cache_ttl  # 5 分钟缓存（匹配轮询间隔）

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def detect_rotation(self, symbol: str) -> dict[str, Any]:
        """
        检测 symbol 的资金轮动信号。

        Returns:
            {
                "capital_rotation": float,   # [-1, +1] 正=净流入，负=净流出
                "group_avg_score": float,    # 所属组平均资金流得分
                "token_score": float,        # 本币资金流得分
                "competitors": dict,         # {coin: score}
                "rotation_detected": bool,   # |rotation| > 0.15
                "group_name": str,           # 使用的组名
            }
        FAIL-OPEN: 异常 → capital_rotation=0.0
        """
        try:
            # 找 symbol 所属的组（取第一个匹配的组）
            group_name = self._find_group(symbol)
            if group_name is None:
                return self._neutral_result(symbol)

            group = COMPETITOR_GROUPS[group_name]
            # 计算组内每币的资金流得分
            scores: dict[str, float] = {}
            for coin in group:
                score = self._compute_capital_score(coin)
                if score is not None:
                    scores[coin] = score

            if not scores or symbol not in scores:
                return self._neutral_result(symbol)

            token_score = scores[symbol]
            group_scores = [s for c, s in scores.items() if c != symbol]
            group_avg = sum(group_scores) / len(group_scores) if group_scores else token_score

            # 相对强度 = 本币得分 - 组均分
            rotation = max(-1.0, min(1.0, token_score - group_avg))
            detected = abs(rotation) > 0.15

            return {
                "capital_rotation": round(rotation, 4),
                "group_avg_score": round(group_avg, 4),
                "token_score": round(token_score, 4),
                "competitors": {c: round(s, 4) for c, s in scores.items()},
                "rotation_detected": detected,
                "group_name": group_name,
            }
        except Exception as e:
            logger.warning("[FO] detect_rotation crash for %s: %s", symbol, e)
            return self._neutral_result(symbol)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _neutral_result(symbol: str) -> dict[str, Any]:
        return {
            "capital_rotation": 0.0,
            "group_avg_score": 0.0,
            "token_score": 0.0,
            "competitors": {},
            "rotation_detected": False,
            "group_name": "",
        }

    @staticmethod
    def _find_group(symbol: str) -> str | None:
        """找 symbol 所属的竞品组（返回第一个匹配的组名）"""
        for name, coins in COMPETITOR_GROUPS.items():
            if symbol in coins:
                return name
        return None

    def _compute_capital_score(self, coin: str) -> float | None:
        """
        计算单币资金流得分 ∈ [-1, +1]。（带 TTL 缓存，避免多币重复请求）

        三维加权:
        - 量比强度 (40%): vol_5/vol_20 归一化
        - 动量强度 (40%): (close - MA20)/MA20 归一化
        - OI 强度   (20%): OI 变化（若有）

        FAIL-OPEN: 数据不足 → 返回 None
        """
        # TTL 缓存检查
        cached = self._cache.get(coin)
        if cached is not None:
            score, ts = cached
            if time.time() - ts < self._cache_ttl:
                return score

        try:
            inst_id = f"{coin}-USDT-SWAP"
            kline_resp = self._client.get_kline(inst_id, bar="1H", limit=200)
            if not kline_resp or not kline_resp.get("ok"):
                return None

            candles = list(reversed(kline_resp.get("candles", [])))
            if len(candles) < 20:
                return None

            closes = [float(c["c"]) for c in candles]
            vols = [float(c["vol"]) for c in candles]

            # 1. 量比强度
            vol_5 = sum(vols[-5:]) / 5
            vol_20 = sum(vols[-20:]) / 20
            vol_ratio = vol_5 / max(vol_20, 1e-9)
            volume_score = math.tanh((vol_ratio - 1.0) * 2.0)  # [-1, +1]

            # 2. 动量强度
            ma20 = sum(closes[-20:]) / 20
            momentum = (closes[-1] - ma20) / max(ma20, 1e-9)
            momentum_score = math.tanh(momentum * 50.0)  # 2%波动→接近1

            # 3. OI 强度（可选）
            oi_score = 0.0
            get_oi = getattr(self._client, "get_open_interest", None)
            if callable(get_oi):
                try:
                    oi_resp = get_oi(inst_id)
                    if oi_resp and oi_resp.get("ok"):
                        oi = float(oi_resp.get("open_interest", 0))
                        if oi > 0:
                            oi_log = math.log10(max(oi, 1))
                            oi_score = max(-1.0, min(1.0, (oi_log - 6.0) / 2.0))
                except Exception:
                    oi_score = 0.0

            # 加权合成
            score = 0.4 * volume_score + 0.4 * momentum_score + 0.2 * oi_score
            score = max(-1.0, min(1.0, score))

            # 写入缓存
            self._cache[coin] = (score, time.time())
            return score

        except Exception as e:
            logger.debug("[FO] capital_score for %s: %s", coin, e)
            return None
