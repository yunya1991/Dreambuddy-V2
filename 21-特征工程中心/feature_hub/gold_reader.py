"""GoldReader — 从 19-DAL 读取 Gold 数据，组装 FeaturePipeline 输入。

调用 MarketMacroRepo.query_*_by_time()，将结果转为 DataFrame，
供 FeaturePipeline.run(df, macro_df=...) 使用。

设计原则：
  - DAL 异常 → fail-open（返回空 DataFrame）
  - 空查询结果 → 返回空 DataFrame
  - OHLCV 可外部传入或从 18-DataCenter 自动拉取
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class GoldReader:
    """从 19-DAL 读取 Gold 数据。

    Args:
        mm_repo: MarketMacroRepository 实例。None 时尝试从 dreambuddy_dal 获取。
        data_center: DataCenter 实例。None 时延迟初始化。
    """

    def __init__(
        self,
        mm_repo: Optional[Any] = None,
        data_center: Optional[Any] = None,
    ) -> None:
        if mm_repo is None:
            try:
                from dreambuddy_dal import get_market_macro_repo
                mm_repo = get_market_macro_repo()
            except Exception:
                logger.warning("[GoldReader] 无法从 dreambuddy_dal 获取默认 repo")
                mm_repo = None
        self.mm_repo = mm_repo
        self._data_center = data_center

    # ------------------------------------------------------------------
    # 单指标读取
    # ------------------------------------------------------------------

    def read_fear_greed(
        self, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """读取恐惧贪婪指数。"""
        if self.mm_repo is None:
            return pd.DataFrame()
        try:
            rows = self.mm_repo.query_fear_greed_by_time(start_ts, end_ts)
        except Exception as exc:
            logger.warning("[GoldReader] fear_greed 读取失败: %s", exc)
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["value", "value_classification", "timestamp"])

    def read_funding_rate(
        self, symbol: str, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """读取资金费率。"""
        if self.mm_repo is None:
            return pd.DataFrame()
        try:
            rows = self.mm_repo.query_funding_by_time(symbol, start_ts, end_ts)
        except Exception as exc:
            logger.warning("[GoldReader] funding 读取失败: %s", exc)
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["symbol", "funding_rate", "timestamp"])
        df = df.rename(columns={"funding_rate": "funding_rate"})
        return df

    def read_open_interest(
        self, symbol: str, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """读取持仓量。"""
        if self.mm_repo is None:
            return pd.DataFrame()
        try:
            rows = self.mm_repo.query_open_interest_by_time(symbol, start_ts, end_ts)
        except Exception as exc:
            logger.warning("[GoldReader] open_interest 读取失败: %s", exc)
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["symbol", "open_interest", "sum_open_interest_value", "timestamp"])

    def read_long_short_ratio(
        self, symbol: str, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """读取多空比。"""
        if self.mm_repo is None:
            return pd.DataFrame()
        try:
            rows = self.mm_repo.query_long_short_ratio_by_time(symbol, start_ts, end_ts)
        except Exception as exc:
            logger.warning("[GoldReader] long_short_ratio 读取失败: %s", exc)
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["symbol", "long_account", "short_account", "long_short_ratio", "timestamp"])

    def read_taker_volume(
        self, symbol: str, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """读取主动买卖量。"""
        if self.mm_repo is None:
            return pd.DataFrame()
        try:
            rows = self.mm_repo.query_taker_volume_by_time(symbol, start_ts, end_ts)
        except Exception as exc:
            logger.warning("[GoldReader] taker_volume 读取失败: %s", exc)
            return pd.DataFrame()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=["symbol", "buy_vol", "sell_vol", "buy_sell_volume_diff", "buy_sell_volume_ratio", "timestamp"])

    # ------------------------------------------------------------------
    # 合并读取
    # ------------------------------------------------------------------

    def read_all_macro(
        self, symbol: str, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """合并读取所有宏观指标，按时间对齐。"""
        frames: list[pd.DataFrame] = []

        # fear_greed
        fg = self.read_fear_greed(start_ts, end_ts)
        if not fg.empty:
            fg = fg.rename(columns={"value": "fear_greed"})
            fg = fg[["timestamp", "fear_greed", "value_classification"]]
            fg["timestamp"] = pd.to_datetime(fg["timestamp"], utc=True, errors="coerce")
            frames.append(fg)

        # funding_rate
        fr = self.read_funding_rate(symbol, start_ts, end_ts)
        if not fr.empty:
            fr["timestamp"] = pd.to_datetime(fr["timestamp"], utc=True, errors="coerce")
            frames.append(fr[["timestamp", "funding_rate"]])

        # open_interest
        oi = self.read_open_interest(symbol, start_ts, end_ts)
        if not oi.empty:
            oi["timestamp"] = pd.to_datetime(oi["timestamp"], utc=True, errors="coerce")
            frames.append(oi[["timestamp", "open_interest"]])

        # long_short_ratio
        ls = self.read_long_short_ratio(symbol, start_ts, end_ts)
        if not ls.empty:
            ls["timestamp"] = pd.to_datetime(ls["timestamp"], utc=True, errors="coerce")
            frames.append(ls[["timestamp", "long_short_ratio"]])

        # taker_volume
        tv = self.read_taker_volume(symbol, start_ts, end_ts)
        if not tv.empty:
            tv["timestamp"] = pd.to_datetime(tv["timestamp"], utc=True, errors="coerce")
            tv["buy_sell_ratio"] = tv.get("buy_sell_volume_ratio")
            frames.append(tv[["timestamp", "buy_vol", "sell_vol", "buy_sell_ratio"]])

        if not frames:
            return pd.DataFrame()

        macro = frames[0]
        for f in frames[1:]:
            macro = pd.merge(macro, f, on="timestamp", how="outer")

        macro = macro.sort_values("timestamp").reset_index(drop=True)
        return macro

    # ------------------------------------------------------------------
    # OHLCV + 宏观合并
    # ------------------------------------------------------------------

    def read_ohlcv_with_macro(
        self,
        symbol: str,
        start_ts: datetime,
        end_ts: datetime,
        ohlcv_df: Optional[pd.DataFrame] = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """读取 OHLCV + 宏观指标，返回 (df, macro_df) 供 FeaturePipeline.run()。

        Args:
            symbol: 交易标的（如 "BTC"）
            start_ts: 开始时间
            end_ts: 结束时间
            ohlcv_df: 外部传入的 OHLCV DataFrame。None 时从 18-DataCenter 拉取。

        Returns:
            (ohlcv_df, macro_df)
        """
        # 1) OHLCV
        if ohlcv_df is not None:
            df = ohlcv_df.copy()
        else:
            df = self._fetch_ohlcv_from_dc(symbol, start_ts, end_ts)

        # 2) 宏观
        macro_df = self.read_all_macro(symbol, start_ts, end_ts)

        return df, macro_df

    def _fetch_ohlcv_from_dc(
        self, symbol: str, start_ts: datetime, end_ts: datetime,
    ) -> pd.DataFrame:
        """从 18-DataCenter 拉取 OHLCV。"""
        try:
            if self._data_center is None:
                from data_center.core.dispatcher import DataCenter
                self._data_center = DataCenter()
            records = self._data_center.fetch(
                category="finance", source="yfinance",
                symbol=symbol, start=start_ts, end=end_ts,
            )
            if not records:
                return pd.DataFrame()
            # DataRecord → DataFrame
            ts_list = []
            for rec in records:
                for item in rec.timeseries:
                    ts_list.append(item)
            return pd.DataFrame(ts_list) if ts_list else pd.DataFrame()
        except Exception as exc:
            logger.warning("[GoldReader] OHLCV 拉取失败: %s", exc)
            return pd.DataFrame()
