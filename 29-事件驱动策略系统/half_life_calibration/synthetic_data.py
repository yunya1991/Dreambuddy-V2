"""合成数据生成器 — 用于验证半衰期校准框架正确性。

设计原理：
  生成已知 true_half_life 的事件+K线，使最优 τ = true_half_life。
  若校准框架能从合成数据中恢复 true_half_life，则框架逻辑正确。

价格模型：
  - 基线：几何布朗运动（小幅随机游走 + 微小负漂移代表市场摩擦）
  - 事件冲击：每个事件在方向上施加一个累计收益 impulse，
    在 2×true_half_life 天内逐步兑现（线性），之后持平。
  - 负漂移使过长持有期的 CAR 下降，从而在 τ = true_half_life 处形成最优。

  持有期 T = hold_days_mult × τ（默认 2τ）：
    - τ < true_half_life：T < 2×true_half_life，只兑现部分 impulse → CAR 低
    - τ = true_half_life：T = 2×true_half_life，兑现全部 impulse → CAR 最高
    - τ > true_half_life：T > 2×true_half_life，impulse 已兑现完，额外天数只有负漂移 → CAR 下降
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd


def generate_events(
    n_events: int = 50,
    true_half_life: float = 2.0,
    seed: int = 42,
    start_date: str = "2025-01-01",
    day_spacing: int = 7,
) -> list[dict]:
    """生成合成事件列表。

    Args:
        n_events: 事件数量
        true_half_life: 真实半衰期（仅用于确定事件间距，不影响方向）
        seed: 随机种子
        start_date: 起始日期
        day_spacing: 事件平均间隔（天）

    Returns:
        事件列表，每项含 date(datetime) + direction(str)
    """
    rng = np.random.default_rng(seed)
    events = []
    directions = ["long", "short", "neutral"]
    # 方向概率：long/short 各 40%，neutral 20%
    probs = [0.4, 0.4, 0.2]

    current = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    for _ in range(n_events):
        # 事件间隔：day_spacing ± 2 天
        gap = int(rng.integers(day_spacing - 2, day_spacing + 3))
        current = current + timedelta(days=gap)
        direction = rng.choice(directions, p=probs)
        events.append({"date": current, "direction": direction})

    return events


def generate_prices(
    events: list[dict],
    true_half_life: float = 2.0,
    seed: int = 42,
    impulse_magnitude: float = 0.04,
    drift: float = -0.0003,
    volatility: float = 0.012,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """生成与事件关联的合成 K 线。

    价格模型：
      log_return = drift + volatility × ε + Σ event_impulses
      event_impulse: 事件方向 × impulse_magnitude，在 2×true_half_life 天内线性兑现

    Args:
        events: 事件列表
        true_half_life: 真实半衰期（决定 impulse 兑现速度）
        seed: 随机种子
        impulse_magnitude: 单次事件冲击幅度（4%）
        drift: 每日漂移（-0.03%，代表市场摩擦）
        volatility: 日波动率
        start_price: 起始价格

    Returns:
        DataFrame，含 close 列，index 为日期
    """
    rng = np.random.default_rng(seed)

    # 确定日期范围：从第一个事件前 30 天到最后一个事件后 2×true_half_life + 30 天
    if not events:
        return pd.DataFrame({"close": [start_price]}, index=pd.date_range("2025-01-01", periods=1))

    event_dates = [ev["date"] for ev in events]
    start = min(event_dates) - timedelta(days=30)
    end = max(event_dates) + timedelta(days=int(2 * true_half_life) + 30)
    dates = pd.date_range(start, end, freq="D")
    n_days = len(dates)

    # 日收益率
    log_returns = rng.normal(drift, volatility, size=n_days)

    # 事件冲击：每个事件在 2×true_half_life 天内线性兑现
    impulse_days = int(round(2 * true_half_life))
    for ev in events:
        if ev["direction"] == "neutral":
            continue
        sign = 1.0 if ev["direction"] == "long" else -1.0
        # 找到事件在 dates 中的位置
        try:
            event_idx = dates.get_indexer([pd.Timestamp(ev["date"])], method="nearest")[0]
        except Exception:
            continue
        if event_idx < 0:
            continue
        # 线性兑现：每天 impulse / impulse_days
        daily_impulse = (impulse_magnitude * sign) / impulse_days
        for d in range(impulse_days):
            idx = event_idx + d
            if 0 <= idx < n_days:
                log_returns[idx] += daily_impulse

    # 转换为价格
    log_prices = np.log(start_price) + np.cumsum(log_returns)
    close = np.exp(log_prices)

    return pd.DataFrame({"close": close}, index=dates)
