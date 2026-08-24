"""FundamentalRatios — 基本面代理比率特征（8列）

由于 OHLCV 不含财务数据，使用价格+成交量衍生代理比率：
  market_cap_proxy   — 市值代理（close × volume 归一化）
  pe_proxy           — 市盈率代理（价格/波动幅度比）
  pb_proxy           — 市净率代理（价格/累计成交量比）
  revenue_proxy      — 营收代理（成交量移动平均）
  margin_proxy       — 利润率代理（日内涨幅均值）
  roe_proxy          — ROE 代理（涨幅/波动比）
  debt_ratio         — 负债率代理（下行波动/总波动）
  growth_rate        — 增长率代理（20日收益率）

后续 M3.5 H3 集成时可从 9-基本面分析 获取真实财务数据替换。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """基本面代理比率计算（8列）"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]
    result = pd.DataFrame(index=df.index)

    # market_cap_proxy：close × volume 归一化
    raw_mcap = close * volume
    result["market_cap_proxy"] = raw_mcap / raw_mcap.rolling(60, min_periods=1).mean()

    # pe_proxy：价格 / 日内波动幅度比
    daily_range = (high - low) / (close + 1e-10)
    avg_range = daily_range.rolling(20, min_periods=1).mean()
    result["pe_proxy"] = close / (close * avg_range + 1e-10)

    # pb_proxy：价格 / 累计成交量比
    cum_vol = volume.rolling(60, min_periods=1).sum()
    result["pb_proxy"] = close / (cum_vol + 1e-10) * 1e6

    # revenue_proxy：成交量移动平均
    result["revenue_proxy"] = volume.rolling(20, min_periods=1).mean()

    # margin_proxy：日内涨幅均值
    daily_return = close.pct_change()
    result["margin_proxy"] = daily_return.rolling(20, min_periods=1).mean()

    # roe_proxy：涨幅 / 波动比（Sharpe-like）
    vol = daily_return.rolling(20, min_periods=1).std()
    result["roe_proxy"] = result["margin_proxy"] / (vol + 1e-10)

    # debt_ratio：下行波动 / 总波动
    downside = daily_return.where(daily_return < 0, 0).rolling(20, min_periods=1).std()
    total_vol = daily_return.rolling(20, min_periods=1).std()
    result["debt_ratio"] = downside / (total_vol + 1e-10)

    # growth_rate：20日收益率
    result["growth_rate"] = close.pct_change(20)

    return result
