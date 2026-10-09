"""事件研究法 — 计算事件后 CAR（累计超额收益）。

核心逻辑：
  1. 对每个事件，在事件日按 direction 建仓（long→做多，short→做空，neutral→跳过）
  2. 持有 hold_days_mult × half_life 天
  3. CAR = direction_sign × (price[event+hold] / price[event] - 1)
  4. 汇总 mean_car / win_rate / n_events

半衰期 τ 通过持有期影响 CAR：
  - τ 太小：持有期太短，事件行情未完全兑现
  - τ 太大：持有期太长，事件行情已结束，被噪声稀释
  - 最优 τ 使 CAR 最大化
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd


def compute_car(
    events: list[dict],
    prices: pd.DataFrame,
    half_life: float,
    hold_days_mult: float = 2.0,
) -> dict:
    """事件研究法：计算事件后累计收益 CAR。

    Args:
        events: 事件列表，每项含 date(datetime) + direction(str)
        prices: K 线数据，含 close 列，index 为日期
        half_life: 半衰期 τ（天），决定持有期
        hold_days_mult: 持有期倍数，默认 2τ（覆盖 event + post_event 阶段）

    Returns:
        {
            "mean_car": float,        # 平均 CAR
            "win_rate": float,        # 胜率
            "n_events": int,          # 有效事件数
            "cars": list[float],      # 每个事件的 CAR
        }
    """
    cars: list[float] = []
    hold_days = max(1, int(round(half_life * hold_days_mult)))

    close_series = prices["close"] if isinstance(prices, pd.DataFrame) else prices
    if isinstance(close_series.index, pd.DatetimeIndex):
        close_index = close_series.index
    else:
        close_index = pd.to_datetime(close_series.index)

    for ev in events:
        direction = ev.get("direction", "neutral")
        if direction == "neutral":
            continue

        event_date = ev["date"]
        if isinstance(event_date, str):
            event_date = datetime.fromisoformat(event_date)
        # 归一化到 date（去时区）
        try:
            event_pos = close_index.get_indexer(
                [pd.Timestamp(event_date).normalize()], method="nearest"
            )[0]
        except Exception:
            continue
        if event_pos < 0 or event_pos >= len(close_series):
            continue

        event_price = float(close_series.iloc[event_pos])
        exit_pos = min(event_pos + hold_days, len(close_series) - 1)
        if exit_pos <= event_pos:
            continue
        exit_price = float(close_series.iloc[exit_pos])

        raw_return = (exit_price / event_price) - 1.0
        sign = 1.0 if direction == "long" else -1.0
        cars.append(sign * raw_return)

    if not cars:
        return {"mean_car": 0.0, "win_rate": 0.0, "n_events": 0, "cars": []}

    cars_arr = np.array(cars)
    return {
        "mean_car": float(np.mean(cars_arr)),
        "win_rate": float(np.mean(cars_arr > 0)),
        "n_events": len(cars),
        "cars": cars,
    }
