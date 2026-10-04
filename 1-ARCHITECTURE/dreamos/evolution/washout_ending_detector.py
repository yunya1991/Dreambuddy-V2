"""WashoutEndingDetector — 洗盘结束信号判定器 (规则化先行).

Spec: docs/superpowers/specs/2026-09-22-washout-reversal-genome-design.md §3.1

阶段1 新增 (纯新增, 零回归):
  - EndingSignal dataclass: 洗盘结束信号输出契约
  - WashoutEndingDetector: 规则化判定器 (案例库≥30 后可升级 KNN)

设计原则 (硬约束):
  - HC-G3: 任何异常 → activated=False (FAIL-OPEN)
  - 规则化条件 (全部满足才激活):
      条件1: 连续 2 根 K 线成交量萎缩 ≥40% (相对前 10 根均值)
      条件2: RSI(14) < 35 (超卖)
      条件3: 价格企稳 (下影线 > 实体 或 收盘价 > 前根收盘价)
      条件4: OI 不再下降 (OI 变化率 > -0.5%, FAIL-OPEN 数据缺失时放行)

用法:
    detector = WashoutEndingDetector()
    signal = detector.check(df, macro_data)
    if signal.activated:
        # 洗盘结束, 可做多
"""
from __future__ import annotations

import logging
import math
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
import pandas as pd

__all__ = ["EndingSignal", "WashoutEndingDetector"]

logger = logging.getLogger(__name__)

# 规则化判定参数
_VOL_SHRINKAGE_THRESHOLD = 0.40  # 成交量萎缩阈值 ≥40%
_RSI_PERIOD = 14
_RSI_OVERSOLD = 35.0  # RSI<35 超卖
_OI_DECLINE_THRESHOLD = -0.005  # OI 变化率 > -0.5%
_VOL_LOOKBACK = 10  # 成交量前 N 根均值


@dataclass(frozen=True)
class EndingSignal:
    """洗盘结束信号输出契约.

    Attributes:
        activated: 是否激活 (全部条件满足)
        confidence: 置信度 [0.0, 1.0]
        reason: 触发原因摘要
        timestamp: ISO 8601 UTC
    """
    activated: bool
    confidence: float
    reason: str
    timestamp: str

    def __post_init__(self):
        c = float(self.confidence)
        if c < 0.0:
            c = 0.0
        elif c > 1.0:
            c = 1.0
        object.__setattr__(self, "confidence", c)

    @staticmethod
    def not_activated(reason: str) -> "EndingSignal":
        """FAIL-OPEN 兜底: activated=False, confidence=0.0."""
        return EndingSignal(
            activated=False,
            confidence=0.0,
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class WashoutEndingDetector:
    """洗盘结束信号判定器 (规则化先行).

    规则化条件 (全部满足才激活):
      1. 连续 2 根 K 线成交量萎缩 ≥40%
      2. RSI(14) < 35 (超卖)
      3. 价格企稳 (下影线>实体 或 收盘>前根收盘)
      4. OI 不再下降 (OI 变化率 > -0.5%, 缺失时放行)
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(config) if config else {}
        self._logger = logging.getLogger(__name__)

    def check(self, df: pd.DataFrame, macro_data: Dict) -> EndingSignal:
        """主入口: 判定洗盘是否结束.

        Args:
            df: OHLCV DataFrame (open/high/low/close/volume)
            macro_data: 宏观特征 (含 OI 等)

        Returns:
            EndingSignal

        FAIL-OPEN: 任何异常 → activated=False
        """
        try:
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                return EndingSignal.not_activated("empty_or_invalid_df")

            # 条件1: 成交量萎缩
            vol_ok = self._check_volume_shrinkage(df)
            if not vol_ok:
                return EndingSignal.not_activated("no_volume_shrinkage")

            # 条件2: RSI 超卖
            rsi = self._compute_rsi(df["close"], _RSI_PERIOD)
            if rsi is None or rsi >= _RSI_OVERSOLD:
                return EndingSignal.not_activated(
                    f"rsi_not_oversold_rsi={rsi}"
                )

            # 条件3: 价格企稳
            price_ok = self._check_price_stabilization(df)
            if not price_ok:
                return EndingSignal.not_activated("price_not_stabilized")

            # 条件4: OI 不再下降
            oi_ok = self._check_oi_stabilization(macro_data)
            if not oi_ok:
                return EndingSignal.not_activated("oi_still_declining")

            # 全部条件满足
            confidence = self._compute_confidence(rsi, df, macro_data)
            return EndingSignal(
                activated=True,
                confidence=confidence,
                reason=(
                    f"vol_shrink+rsi={rsi:.1f}+price_stabilize+oi_ok"
                ),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            tb = traceback.format_exc()
            self._logger.error(
                "WashoutEndingDetector.check FAIL-OPEN err=%s\n%s", e, tb
            )
            return EndingSignal.not_activated(f"exception:{type(e).__name__}")

    # ============================================================
    # 条件1: 成交量萎缩 ≥40%
    # ============================================================
    def _check_volume_shrinkage(self, df: pd.DataFrame) -> bool:
        """检查最后 2 根 K 线成交量是否萎缩 ≥40% (相对前 10 根均值)."""
        try:
            if len(df) < _VOL_LOOKBACK + 2:
                return False
            vol = df["volume"]
            avg_prev = float(vol.iloc[-(2 + _VOL_LOOKBACK):-2].mean())
            if avg_prev <= 0:
                return False
            vol_last1 = float(vol.iloc[-1])
            vol_last2 = float(vol.iloc[-2])
            shrink1 = (avg_prev - vol_last1) / avg_prev
            shrink2 = (avg_prev - vol_last2) / avg_prev
            return shrink1 >= _VOL_SHRINKAGE_THRESHOLD and \
                shrink2 >= _VOL_SHRINKAGE_THRESHOLD
        except Exception:
            return False

    # ============================================================
    # 条件2: RSI(14) 超卖
    # ============================================================
    def _compute_rsi(self, closes: pd.Series, period: int = _RSI_PERIOD) -> Optional[float]:
        """计算 RSI(14) using Wilder's smoothing.

        Returns:
            RSI 值 [0, 100], 或 None (数据不足时)
        """
        try:
            if len(closes) < period + 1:
                return None
            deltas = closes.diff().dropna()
            gains = deltas.clip(lower=0)
            losses = (-deltas.clip(upper=0))

            # Wilder's smoothing
            avg_gain = gains.iloc[:period].mean()
            avg_loss = losses.iloc[:period].mean()

            for i in range(period, len(deltas)):
                avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi)
        except Exception:
            return None

    # ============================================================
    # 条件3: 价格企稳
    # ============================================================
    def _check_price_stabilization(self, df: pd.DataFrame) -> bool:
        """检查价格企稳: 下影线 > 实体 或 收盘 > 前根收盘."""
        try:
            if len(df) < 2:
                return False
            last = df.iloc[-1]
            prev = df.iloc[-2]

            body = abs(float(last["close"]) - float(last["open"]))
            lower_shadow = min(
                float(last["close"]), float(last["open"])
            ) - float(last["low"])

            # 条件3a: 下影线 > 实体
            if lower_shadow > body and body > 0:
                return True

            # 条件3b: 收盘 > 前根收盘
            if float(last["close"]) > float(prev["close"]):
                return True

            return False
        except Exception:
            return False

    # ============================================================
    # 条件4: OI 不再下降
    # ============================================================
    def _check_oi_stabilization(self, macro_data: Dict) -> bool:
        """检查 OI 不再下降 (OI 变化率 > -0.5%).

        FAIL-OPEN: OI 数据缺失时放行 (返回 True).
        """
        try:
            oi_current = macro_data.get("oi_current")
            oi_prev = macro_data.get("oi_prev")

            # 数据缺失 → FAIL-OPEN 放行
            if oi_current is None or oi_prev is None:
                return True
            if float(oi_prev) == 0:
                return True

            oi_change_rate = (float(oi_current) - float(oi_prev)) / float(oi_prev)
            return oi_change_rate > _OI_DECLINE_THRESHOLD
        except Exception:
            # FAIL-OPEN: 异常时放行
            return True

    # ============================================================
    # confidence 计算
    # ============================================================
    def _compute_confidence(
        self, rsi: float, df: pd.DataFrame, macro_data: Dict
    ) -> float:
        """计算结束信号 confidence [0, 1].

        基于条件满足程度加权:
          - RSI 越低 (越超卖) → confidence 越高
          - 成交量萎缩越深 → confidence 越高
          - OI 回升 → 加分
        """
        try:
            # RSI 分量: RSI=0→1.0, RSI=35→0.5
            rsi_score = max(0.0, 1.0 - (rsi / (_RSI_OVERSOLD * 2)))

            # 成交量萎缩分量
            vol = df["volume"]
            avg_prev = float(vol.iloc[-(2 + _VOL_LOOKBACK):-2].mean())
            vol_last = float(vol.iloc[-1])
            if avg_prev > 0:
                shrink_ratio = max(0.0, (avg_prev - vol_last) / avg_prev)
                vol_score = min(1.0, shrink_ratio / 0.6)  # 60% 萎缩 → 满分
            else:
                vol_score = 0.5

            # OI 分量
            oi_current = macro_data.get("oi_current")
            oi_prev = macro_data.get("oi_prev")
            if oi_current is not None and oi_prev is not None and float(oi_prev) > 0:
                oi_change = (float(oi_current) - float(oi_prev)) / float(oi_prev)
                oi_score = min(1.0, max(0.0, 0.5 + oi_change * 50))  # 微小正向 → 0.5+
            else:
                oi_score = 0.5  # 数据缺失 → 中性

            confidence = rsi_score * 0.4 + vol_score * 0.35 + oi_score * 0.25
            return max(0.0, min(1.0, confidence))
        except Exception:
            return 0.5  # 中性兜底
