"""PumpDumpEndingDetector — 拉高出货结束信号判定器 (做空因子).

阶段2 新增 (纯新增, 零回归):
  - PumpDumpEndingSignal: 结束信号输出契约
  - PumpDumpEndingDetector: 规则化判定器

设计原则 (硬约束):
  - HC-P3: 任何异常 → activated=False (FAIL-OPEN)
  - 规则化条件 (全部满足才激活):
      条件1: RSI(14) > 70 (超买, 买盘枯竭)
      条件2: 成交量从峰值萎缩 (卖压累积)
      条件3: 价格见顶 (上影线 > 实体 或 收盘 < 前根收盘)
      条件4: OI 下降 (聪明钱离场, FAIL-OPEN 数据缺失时放行)

镜像 WashoutEndingDetector (做多因子), 方向相反.
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
import pandas as pd

__all__ = ["PumpDumpEndingSignal", "PumpDumpEndingDetector"]

logger = logging.getLogger(__name__)

_RSI_PERIOD = 14
_RSI_OVERBOUGHT = 70.0
_OI_DECLINE_THRESHOLD = -0.005  # OI 变化率 < -0.5% 即视为下降
_VOL_LOOKBACK = 10


@dataclass(frozen=True)
class PumpDumpEndingSignal:
    """拉高出货结束信号输出契约."""
    activated: bool
    confidence: float
    reason: str
    timestamp: str

    def __post_init__(self):
        c = float(self.confidence)
        object.__setattr__(self, "confidence", max(0.0, min(1.0, c)))

    @staticmethod
    def not_activated(reason: str) -> "PumpDumpEndingSignal":
        return PumpDumpEndingSignal(
            activated=False, confidence=0.0, reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class PumpDumpEndingDetector:
    """拉高出货结束信号判定器 (镜像 WashoutEndingDetector)."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(config) if config else {}

    def check(self, df: pd.DataFrame, macro_data: Dict) -> PumpDumpEndingSignal:
        try:
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                return PumpDumpEndingSignal.not_activated("empty_or_invalid_df")

            rsi = self._compute_rsi(df["close"], _RSI_PERIOD)
            if rsi is None or rsi <= _RSI_OVERBOUGHT:
                return PumpDumpEndingSignal.not_activated(
                    f"rsi_not_overbought_rsi={rsi}")

            if not self._check_volume_decline(df):
                return PumpDumpEndingSignal.not_activated("volume_not_declining")

            if not self._check_price_topping(df):
                return PumpDumpEndingSignal.not_activated("price_not_topping")

            if not self._check_oi_declining(macro_data):
                return PumpDumpEndingSignal.not_activated("oi_not_declining")

            confidence = self._compute_confidence(rsi, df, macro_data)
            return PumpDumpEndingSignal(
                activated=True, confidence=confidence,
                reason=f"rsi={rsi:.1f}+vol_decline+price_topping+oi_down",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("PumpDumpEndingDetector.check FAIL-OPEN err=%s\n%s", e, tb)
            return PumpDumpEndingSignal.not_activated(f"exception:{type(e).__name__}")

    def _compute_rsi(self, closes, period=_RSI_PERIOD) -> Optional[float]:
        try:
            if len(closes) < period + 1:
                return None
            deltas = closes.diff().dropna()
            gains = deltas.clip(lower=0)
            losses = (-deltas.clip(upper=0))
            ag = gains.iloc[:period].mean()
            al = losses.iloc[:period].mean()
            for i in range(period, len(deltas)):
                ag = (ag * (period - 1) + gains.iloc[i]) / period
                al = (al * (period - 1) + losses.iloc[i]) / period
            if al == 0:
                return 100.0
            return float(100.0 - (100.0 / (1.0 + ag / al)))
        except Exception:
            return None

    def _check_volume_decline(self, df) -> bool:
        """成交量从峰值萎缩 (最后 2 根 < 前 10 根均值的 80%)."""
        try:
            if len(df) < _VOL_LOOKBACK + 2:
                return False
            vol = df["volume"].astype(float)
            avg = float(vol.iloc[-(2 + _VOL_LOOKBACK):-2].mean())
            if avg <= 0:
                return False
            v1 = float(vol.iloc[-1])
            v2 = float(vol.iloc[-2])
            return v1 < avg * 0.8 and v2 < avg * 0.8
        except Exception:
            return False

    def _check_price_topping(self, df) -> bool:
        """价格见顶: 上影线 > 实体 或 收盘 < 前根收盘."""
        try:
            if len(df) < 2:
                return False
            last = df.iloc[-1]
            prev = df.iloc[-2]
            body = abs(float(last["close"]) - float(last["open"]))
            upper_shadow = float(last["high"]) - max(
                float(last["close"]), float(last["open"]))
            if upper_shadow > body and body > 0:
                return True
            if float(last["close"]) < float(prev["close"]):
                return True
            return False
        except Exception:
            return False

    def _check_oi_declining(self, macro_data) -> bool:
        """OI 下降 (变化率 < -0.5%). FAIL-OPEN: 缺失放行."""
        try:
            oi_cur = macro_data.get("oi_current")
            oi_prev = macro_data.get("oi_prev")
            if oi_cur is None or oi_prev is None:
                return True  # FAIL-OPEN
            if float(oi_prev) == 0:
                return True
            rate = (float(oi_cur) - float(oi_prev)) / float(oi_prev)
            return rate < _OI_DECLINE_THRESHOLD
        except Exception:
            return True  # FAIL-OPEN

    def _compute_confidence(self, rsi, df, macro_data) -> float:
        try:
            rsi_score = min(1.0, max(0.0, (rsi - 50) / 50))
            vol = df["volume"].astype(float)
            avg = float(vol.iloc[-(2 + _VOL_LOOKBACK):-2].mean())
            if avg > 0:
                decline = max(0.0, (avg - float(vol.iloc[-1])) / avg)
                vol_score = min(1.0, decline / 0.4)
            else:
                vol_score = 0.5
            oi_cur = macro_data.get("oi_current")
            oi_prev = macro_data.get("oi_prev")
            if oi_cur is not None and oi_prev is not None and float(oi_prev) > 0:
                oi_chg = (float(oi_cur) - float(oi_prev)) / float(oi_prev)
                oi_score = min(1.0, max(0.0, -oi_chg * 50))
            else:
                oi_score = 0.5
            return max(0.0, min(1.0, rsi_score * 0.4 + vol_score * 0.35 + oi_score * 0.25))
        except Exception:
            return 0.5
