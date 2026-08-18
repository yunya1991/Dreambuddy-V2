"""
三重障碍标注系统 — 辩证法三规律的算法落地

理论映射 (辩证法三规律 → Triple Barrier):
  对立统一规律 → 上障(多方) vs 下障(空方) 的对立统一
    上障 = 多方力量的顶点 (止盈位)
    下障 = 空方力量的顶点 (止损位)
    多空对立，一方被突破则矛盾解决

  量变质变规律 → 价格在障碍间的积累(量变)与突破(质变)
    未触碰障碍 = 量变过程 (矛盾双方力量积累)
    触碰障碍 = 质变发生 (矛盾一方取得胜利)

  否定之否定规律 → 时间障否定了初始矛盾，新矛盾开启
    时间障 = 旧矛盾被时间否定 (持有到期，未分胜负)
    新周期 = 否定之否定，新的矛盾统一体开始

标签体系:
  +1 = 先触碰上障 (多方胜利，做多正确)
  -1 = 先触碰下障 (空方胜利，做空正确)
   0 = 先触碰时间障 (矛盾未解决，无明确方向)
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, List, Optional


# ============================================================
# 三重障碍标注
# ============================================================

def triple_barrier_labels(
    df: pd.DataFrame,
    tp_factor: float = 0.02,      # 止盈倍数 (相对于波动率)
    sl_factor: float = 0.015,     # 止损倍数 (相对于波动率)
    max_bars: int = 60,           # 最大持有bar数 (时间障)
    use_atr: bool = True,         # 是否用ATR动态计算障碍
    atr_period: int = 14,         # ATR周期
    atr_multiplier_tp: float = 3.0,  # 止盈ATR倍数
    atr_multiplier_sl: float = 2.0,  # 止损ATR倍数
    multi_horizons: Optional[List[int]] = None,  # Phase C: 多 horizon 并行标注
) -> pd.DataFrame | Dict[int, pd.DataFrame]:
    """
    三重障碍标注 (Triple Barrier Method)

    基于Marcos López de Prado的方法，为每根K线标注：
    - 先触碰上障 → label=1 (做多盈利)
    - 先触碰下障 → label=-1 (做空盈利)
    - 先触碰时间障 → label=0 (方向不明)

    Args:
        df: 包含 OHLCV 的K线数据
        tp_factor: 固定止盈比例 (当use_atr=False时)
        sl_factor: 固定止损比例 (当use_atr=False时)
        max_bars: 最大持有bar数 (时间障)
        use_atr: 是否使用ATR动态计算障碍
        atr_period: ATR周期
        atr_multiplier_tp: 止盈的ATR倍数
        atr_multiplier_sl: 止损的ATR倍数
        multi_horizons: Phase C (Spec §4.3.1) — 传入 [1,2,3,6,10,20,30] 时，
            对每个 horizon h 独立运行 triple_barrier(max_bars=h)，返回
            Dict[int, pd.DataFrame]（key=horizon, value=该 horizon 的标注 DataFrame）。
            传入 None 时保持旧行为（返回单个 DataFrame）。

    Returns:
        当 multi_horizons=None: DataFrame with columns:
            label, barrier_hit, hit_bar, tp_price, sl_price, return_pct

        当 multi_horizons=[h1,h2,...]: Dict[int, DataFrame]，
            key=horizon h, value=该 horizon 的标注 DataFrame（列同上）。
    """
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    # 计算ATR
    if use_atr:
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
        atr = pd.Series(tr).rolling(atr_period).mean().values
        tp_dist = atr * atr_multiplier_tp
        sl_dist = atr * atr_multiplier_sl
    else:
        tp_dist = close * tp_factor
        sl_dist = close * sl_factor

    # 输出数组
    labels = np.zeros(n, dtype=int)
    barrier_hit = np.full(n, "time", dtype=object)
    hit_bars = np.full(n, max_bars, dtype=int)
    tp_prices = np.zeros(n)
    sl_prices = np.zeros(n)
    returns_pct = np.zeros(n)

    # 为每个入场点计算三重障碍
    for i in range(n - 1):
        if np.isnan(tp_dist[i]) or np.isnan(sl_dist[i]) or close[i] == 0:
            labels[i] = 0
            barrier_hit[i] = "nan"
            continue

        entry = close[i]
        tp = entry + tp_dist[i]
        sl = entry - sl_dist[i]
        tp_prices[i] = tp
        sl_prices[i] = sl

        # 未来max_bars根K线内，检测先触碰哪个障碍
        end = min(i + 1 + max_bars, n)
        hit = "time"
        hit_idx = max_bars

        for j in range(i + 1, end):
            # 检查上障 (高价比tp高)
            if high[j] >= tp:
                hit = "tp"
                hit_idx = j - i
                break
            # 检查下障 (低价比sl低)
            if low[j] <= sl:
                hit = "sl"
                hit_idx = j - i
                break

        # 持有到期收益率
        end_idx = min(i + max_bars, n - 1)
        returns_pct[i] = (close[end_idx] - entry) / entry

        # 设置标签
        if hit == "tp":
            labels[i] = 1
            barrier_hit[i] = "tp"
            hit_bars[i] = hit_idx
        elif hit == "sl":
            labels[i] = -1
            barrier_hit[i] = "sl"
            hit_bars[i] = hit_idx
        else:
            # 时间障: 按最终收益方向标记（也可以标0，视情况）
            if returns_pct[i] > 0.005:
                labels[i] = 1
                barrier_hit[i] = "time_up"
            elif returns_pct[i] < -0.005:
                labels[i] = -1
                barrier_hit[i] = "time_down"
            else:
                labels[i] = 0
                barrier_hit[i] = "time"
            hit_bars[i] = max_bars

    result = pd.DataFrame({
        "label": labels,
        "barrier_hit": barrier_hit,
        "hit_bar": hit_bars,
        "tp_price": tp_prices,
        "sl_price": sl_prices,
        "return_pct": returns_pct,
    }, index=df.index)

    # Phase C (Spec §4.3.1): 多 horizon 并行标注
    if multi_horizons is not None:
        return {
            h: triple_barrier_labels(
                df, tp_factor=tp_factor, sl_factor=sl_factor,
                max_bars=h, use_atr=use_atr, atr_period=atr_period,
                atr_multiplier_tp=atr_multiplier_tp,
                atr_multiplier_sl=atr_multiplier_sl,
                multi_horizons=None,  # 防递归
            )
            for h in multi_horizons
        }

    return result


# ============================================================
# 辩证标签系统 (Dialectical Labeling)
# ============================================================

class DialecticalLabeler:
    """
    辩证标注器 — 用辩证法三规律解读三重障碍结果

    理论框架:
      对立统一 → 多空力量对比 → 方向标签
      量变质变 → 障碍突破速度 → 矛盾强度
      否定之否定 → 时间周期转化 → 矛盾演化阶段
    """

    def __init__(
        self,
        tp_atr: float = 3.0,
        sl_atr: float = 2.0,
        max_bars: int = 60,
        atr_period: int = 14,
    ):
        self.tp_atr = tp_atr
        self.sl_atr = sl_atr
        self.max_bars = max_bars
        self.atr_period = atr_period

    def label(self, df: pd.DataFrame) -> pd.DataFrame:
        """执行三重障碍标注 + 辩证解读"""
        tb = triple_barrier_labels(
            df,
            use_atr=True,
            atr_period=self.atr_period,
            atr_multiplier_tp=self.tp_atr,
            atr_multiplier_sl=self.sl_atr,
            max_bars=self.max_bars,
        )

        # 辩证解读层
        dialectics = self._dialectical_interpretation(df, tb)
        result = pd.concat([tb, dialectics], axis=1)
        return result

    def _dialectical_interpretation(
        self, df: pd.DataFrame, tb: pd.DataFrame
    ) -> pd.DataFrame:
        """
        辩证解读：从三重障碍结果中提取辩证法三规律的量化指标

        对立统一 → contradiction_strength (矛盾强度: 双方力量差的大小)
        量变质变 → quality_change_velocity (质变速度: 多快触碰障碍)
        否定之否定 → negation_cycle (否定周期: 时间障占比)
        """
        n = len(df)
        result = pd.DataFrame(index=df.index)

        # 1. 对立统一: 矛盾强度 (基于ATR的相对距离)
        result["contradiction_strength"] = np.where(
            tb["label"] != 0,
            1.0 - tb["hit_bar"] / self.max_bars,  # 越快触障，矛盾越尖锐
            0.0  # 时间障 = 矛盾不尖锐
        )

        # 2. 量变质变: 质变速度 (触碰障碍的速度)
        result["quality_change_velocity"] = np.where(
            tb["hit_bar"] > 0,
            1.0 / tb["hit_bar"].clip(lower=1) * 10,  # 越快速度越大
            0.0
        ).clip(0, 1)

        # 3. 否定之否定: 周期演化阶段 (基于过去N个bar的标签变化)
        label_change = tb["label"].diff().abs()
        result["negation_cycle"] = label_change.rolling(20).sum() / 20.0
        result["negation_cycle"] = result["negation_cycle"].fillna(0)

        # 4. 矛盾主要方面 (主方向)
        result["principal_aspect"] = tb["label"].rolling(10).mean().clip(-1, 1)

        # 5. 矛盾转化概率 (方向反转概率)
        result["transformation_prob"] = (
            label_change.rolling(20).sum() / 20.0
        ).fillna(0)

        return result

    def label_stats(self, labels: pd.DataFrame) -> Dict:
        """标注统计"""
        stats = {}

        # 标签分布
        dist = labels["label"].value_counts()
        stats["label_distribution"] = {
            "up (1)": int(dist.get(1, 0)),
            "down (-1)": int(dist.get(-1, 0)),
            "flat (0)": int(dist.get(0, 0)),
        }

        # 障碍分布
        barrier_dist = labels["barrier_hit"].value_counts()
        stats["barrier_distribution"] = {
            k: int(v) for k, v in barrier_dist.items()
        }

        # 持有时间统计
        hit_bars = labels[labels["hit_bar"] < self.max_bars]["hit_bar"]
        if len(hit_bars) > 0:
            stats["avg_hold_bars"] = float(hit_bars.mean())
            stats["median_hold_bars"] = float(hit_bars.median())
        else:
            stats["avg_hold_bars"] = self.max_bars
            stats["median_hold_bars"] = self.max_bars

        # 矛盾统计
        stats["avg_contradiction_strength"] = float(
            labels["contradiction_strength"].mean()
        )
        stats["avg_quality_change_velocity"] = float(
            labels["quality_change_velocity"].mean()
        )
        stats["negation_cycle_frequency"] = float(
            labels["negation_cycle"].mean()
        )

        return stats
