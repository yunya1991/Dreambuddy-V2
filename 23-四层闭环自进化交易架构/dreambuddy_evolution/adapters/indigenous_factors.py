"""23 自产高阶因子 — 不读取任何 11 域实例属性/文件。

背景：BCRM 方向、BDSM 估值、BTC regime、方向状态原先从 11 `polling_trader`
实例属性读取。23 独立运行后这些因子缺失，此处用 23 自有行情快照（close/high/low）
自产等价口径，保持下游调制链（Resistance 调制、DataPipeline 装配）可用。

口径（全部基于最近收盘序列，数据不足时返回中性默认）：
- BTC regime：close>MA20>MA60 且 MA20 高于 MA60 1% → STRONG；
  close<MA20<MA60 且 MA20 低于 MA60 1% → WEAK；否则 NEUTRAL
- direction_state：STRONG → LONG_ONLY；WEAK → SHORT_ONLY；否则 NEUTRAL
- bcrm_direction：由 direction_state 映射 long/short/""
- bcrm_confidence：|close/MA60-1| 与 ATR 占比的合成强度，clip [0,1]
- bdsm_valuation：0.5 + (close/MA60-1)×2，clip [0,1]（高于 MA60 视为高估）
- direction_bias：(close/MA60-1)×100，clip [-100,100]

开关：``EVOLUTION_INDIGENOUS_FACTORS``（默认 on）；off 时全部返回中性默认。
FAIL-OPEN：任何异常返回中性默认，不影响主链路。
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_NEUTRAL = {
    "bcrm_direction": "",
    "bcrm_confidence": 0.0,
    "bcrm_pattern": {"hs_top": False, "hs_bottom": False, "confidence": 0.0},
    "bdsm_valuation": 0.5,
    "btc_regime": "NEUTRAL",
    "direction_state": "NEUTRAL",
    "direction_bias": 0.0,
}


def _switch_on() -> bool:
    return str(os.getenv("EVOLUTION_INDIGENOUS_FACTORS", "on")).strip().lower() in (
        "1",
        "true",
        "on",
        "yes",
    )


def _series(market_data: dict | None, *keys: str) -> list[float]:
    if not isinstance(market_data, dict):
        return []
    for _k in keys:
        _v = market_data.get(_k)
        if not _v:
            continue
        try:
            return [float(x) for x in _v]
        except (TypeError, ValueError):
            continue
    return []


def _ma(values: list[float], window: int) -> float:
    if len(values) < window:
        return 0.0
    return sum(values[-window:]) / float(window)


class IndigenousFactorProvider:
    """23 自产高阶因子提供器（线程内快照，按 symbol 更新）。"""

    def __init__(self) -> None:
        self._snap: dict[str, Any] = {}

    def update(self, market_data: dict | None, symbol: str = "") -> None:
        """用当前 K 线快照刷新因子；数据不足时清空为中性。"""
        if not _switch_on():
            self._snap = {}
            return
        try:
            closes = _series(market_data, "close", "closes", "kline_close")
            if len(closes) < 60:
                self._snap = {}
                return
            highs = _series(market_data, "high", "highs")
            lows = _series(market_data, "low", "lows")

            ma20 = _ma(closes, 20)
            ma60 = _ma(closes, 60)
            last = closes[-1]
            if ma20 <= 0 or ma60 <= 0:
                self._snap = {}
                return

            ratio = last / ma60 - 1.0
            regime = "NEUTRAL"
            if last > ma20 > ma60 and ma20 > ma60 * 1.01:
                regime = "STRONG"
            elif last < ma20 < ma60 and ma20 < ma60 * 0.99:
                regime = "WEAK"

            if len(highs) >= 15 and len(lows) >= 15:
                _trs = [
                    max(
                        highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]),
                    )
                    for i in range(len(closes) - 14, len(closes))
                ]
                atr_pct = (sum(_trs) / len(_trs)) / last if last > 0 else 0.0
            else:
                _diffs = [
                    abs(closes[i] - closes[i - 1]) for i in range(len(closes) - 14, len(closes))
                ]
                atr_pct = (sum(_diffs) / len(_diffs)) / last if last > 0 else 0.0

            direction_state = "NEUTRAL"
            if regime == "STRONG":
                direction_state = "LONG_ONLY"
            elif regime == "WEAK":
                direction_state = "SHORT_ONLY"

            self._snap = {
                "regime": regime,
                "direction_state": direction_state,
                "direction_bias": max(-100.0, min(100.0, ratio * 100.0)),
                "bcrm_confidence": max(0.0, min(1.0, abs(ratio) * 8.0 + atr_pct * 2.0)),
                "bdsm_valuation": max(0.0, min(1.0, 0.5 + ratio * 2.0)),
                "ma20": round(ma20, 8),
                "ma60": round(ma60, 8),
                "atr_pct": round(atr_pct, 6),
                "symbol": symbol,
            }
        except Exception as exc:  # noqa: BLE001 — 因子失败不阻塞交易
            logger.debug("[FO] IndigenousFactorProvider update fail: %s", exc)
            self._snap = {}

    # ── 与 SubSystemBridge 对齐的读取接口 ──────────────────────────
    def get_bcrm_direction(self) -> str:
        _state = self._snap.get("direction_state")
        return "long" if _state == "LONG_ONLY" else ("short" if _state == "SHORT_ONLY" else "")

    def get_bcrm_confidence(self) -> float:
        return float(self._snap.get("bcrm_confidence", _NEUTRAL["bcrm_confidence"]))

    def get_bcrm_pattern(self) -> dict:
        _regime = self._snap.get("regime", "NEUTRAL")
        return {
            "hs_top": False,
            "hs_bottom": False,
            "confidence": 0.0,
            "pattern": {"STRONG": "trend_up", "WEAK": "trend_down"}.get(_regime, "range"),
            "ma20": self._snap.get("ma20"),
            "ma60": self._snap.get("ma60"),
        }

    def get_bdsm_valuation(self) -> float:
        return float(self._snap.get("bdsm_valuation", _NEUTRAL["bdsm_valuation"]))

    def get_btc_regime(self) -> str:
        return str(self._snap.get("regime", _NEUTRAL["btc_regime"]))

    def get_direction_state(self, _cls: str = "crypto_usdt") -> str:
        return str(self._snap.get("direction_state", _NEUTRAL["direction_state"]))

    def get_direction_bias(self, _cls: str = "crypto_usdt") -> float:
        return float(self._snap.get("direction_bias", _NEUTRAL["direction_bias"]))
