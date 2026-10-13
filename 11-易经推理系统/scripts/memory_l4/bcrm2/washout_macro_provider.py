"""WashoutMacroProvider — 从 19-DAL 查询 OI/funding/CVD 构造 macro_data。

设计:
  - 通过 MarketMacroRepository 统一管理数据源（单一数据源 + 缓存 + 降级）
  - FAIL-OPEN: DAL 不可用 / 无数据 → 返回 {} 空字典（WashoutFeatureExtractor 降级中性默认值）
  - CVD 从 taker_volume 表的 buy_sell_volume_diff 累加得到

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §4
"""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

import numpy as np

__all__ = ["WashoutMacroProvider"]


class WashoutMacroProvider:
    """从 19-DAL 查询洗盘外部因子数据，构造 macro_data dict。

    供 WashoutDetector.run(coin, df, macro_data) 的 macro_data 参数使用。

    数据映射:
      - oi_series: MarketMacroRepository.query_open_interest_by_time()
      - funding_rate_series: MarketMacroRepository.query_funding_by_time()
      - cvd_series: MarketMacroRepository.query_taker_volume_by_time()
        (CVD = cumsum(buy_sell_volume_diff))
    """

    def __init__(
        self,
        repo: Optional[object] = None,
        lookback_hours: int = 500,
    ):
        """
        Args:
            repo: MarketMacroRepository 实例（19-DAL）。
                  None → get_macro_data 始终返回 {}（FAIL-OPEN）
            lookback_hours: 查询回看时长（小时），默认 500h ≈ 21 天
        """
        self._repo = repo
        self._lookback_hours = int(lookback_hours)
        self._logger = logging.getLogger(__name__)

    def get_macro_data(self, coin: str) -> Dict[str, list]:
        """查询 OI/funding/CVD 序列，构造 macro_data dict。

        Args:
            coin: 币种符号（如 "BTC"）

        Returns:
            {"oi_series": [...], "funding_rate_series": [...], "cvd_series": [...]}
            任何异常 → {} (FAIL-OPEN)
        """
        if self._repo is None:
            return {}
        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(hours=self._lookback_hours)

            symbol = self._normalize_symbol(coin)

            oi_series = self._query_oi_series(symbol, start, now)
            funding_series = self._query_funding_series(symbol, start, now)
            cvd_series = self._query_cvd_series(symbol, start, now)

            macro_data: Dict[str, list] = {}
            if oi_series:
                macro_data["oi_series"] = oi_series
            if funding_series:
                macro_data["funding_rate_series"] = funding_series
            if cvd_series:
                macro_data["cvd_series"] = cvd_series

            return macro_data
        except Exception as e:
            self._logger.warning(
                "WashoutMacroProvider FAIL-OPEN coin=%s err=%s", coin, e
            )
            return {}

    def _normalize_symbol(self, coin: str) -> str:
        """标准化币种符号为 DAL 使用的格式。"""
        c = coin.upper().strip()
        # 去除可能的 USDT 后缀
        for suffix in ("USDT", "USD", "-SWAP", "-PERP"):
            if c.endswith(suffix):
                c = c[: -len(suffix)]
                break
        return c

    def _query_oi_series(
        self, symbol: str, start: datetime, end: datetime
    ) -> List[float]:
        """查询持仓量序列。"""
        try:
            rows = self._repo.query_open_interest_by_time(symbol, start, end)
            if not rows:
                return []
            # rows: List[Tuple[str, Decimal, Decimal, datetime]]
            # (symbol, open_interest, sum_open_interest_value, ts)
            return [float(r[1]) for r in rows]
        except Exception as e:
            self._logger.debug("OI query fail-open: %s", e)
            return []

    def _query_funding_series(
        self, symbol: str, start: datetime, end: datetime
    ) -> List[float]:
        """查询资金费率序列。"""
        try:
            rows = self._repo.query_funding_by_time(symbol, start, end)
            if not rows:
                return []
            # rows: List[Tuple[str, Decimal, datetime]]
            # (symbol, funding_rate, ts)
            return [float(r[1]) for r in rows]
        except Exception as e:
            self._logger.debug("funding query fail-open: %s", e)
            return []

    def _query_cvd_series(
        self, symbol: str, start: datetime, end: datetime
    ) -> List[float]:
        """查询 CVD 序列（从 taker_volume 表的 buy_sell_volume_diff 累加）。

        CVD = cumsum(buy_vol - sell_vol) = cumsum(buy_sell_volume_diff)
        """
        try:
            rows = self._repo.query_taker_volume_by_time(symbol, start, end)
            if not rows:
                return []
            # rows: List[Tuple[str, Decimal, Decimal, Decimal, Decimal, datetime]]
            # (symbol, buy_vol, sell_vol, buy_sell_volume_diff, buy_sell_volume_ratio, ts)
            diffs = [float(r[3]) for r in rows]
            cvd = np.cumsum(diffs).tolist()
            return cvd
        except Exception as e:
            self._logger.debug("CVD query fail-open: %s", e)
            return []
