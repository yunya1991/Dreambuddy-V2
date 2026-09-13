"""
ExogenousStrengthEvaluator — 外生力量度量体系
理论文档: 三维度矛盾论理论框架.md §4

核心原则:
  1. 前瞻性: 度量在 t 时刻可得，不依赖 t+1 价格结果
  2. 可验证性: 度量值可被独立第三方重现
  3. 维度无关性: z-score 标准化后所有维度同一标度

力量来源（全部非价格量）:
  - 技术面短期: RippleEngine RI 信号强度
  - 技术面中期: UTXO 换手率/筹码集中度
  - 技术面长期: 月线趋势线斜率
  - 基本面短期: ETF 日净流入量
  - 基本面中期: 链上活跃地址周变化率
  - 基本面长期: NVT Z-Score
  - 宏观面短期: CPI surprise (实际-预期差)
  - 宏观面中期: 利率决议预期概率
  - 宏观面长期: 加息/降息周期方向
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ExogenousStrengthEvaluator:
    """
    外生力量度量器: 将异质信号转换为可比的 [0,1] 力量标度.

    使用 z-score 标准化 + percentile rank 消除维度不可通约问题.
    每个维度×周期的力量值独立计算，不依赖价格结果.
    """

    # 历史窗口大小（用于 z-score 标准化）
    HISTORY_WINDOW = 100

    def __init__(self):
        # 历史数据缓冲（用于 z-score 计算）
        self._histories: dict[str, deque] = {}

    def evaluate(self, data: dict[str, Any]) -> dict[str, dict[str, float]]:
        """
        评估所有维度×周期的外生力量.

        Returns:
            {
                "technical": {"short": float, "medium": float, "long": float},
                "fundamental": {"short": float, "medium": float, "long": float},
                "macro": {"short": float, "medium": float, "long": float},
            }
            每个值为 [0, 1] 标准化力量值，0.5 = 中性
        """
        result = {}
        result["technical"] = self._eval_technical(data)
        result["fundamental"] = self._eval_fundamental(data)
        result["macro"] = self._eval_macro(data)
        return result

    def _eval_technical(self, data: dict) -> dict[str, float]:
        """技术面力量: 短/中/长."""
        # 短期: RI 信号强度（非价格，路径评分）
        ri_signal = data.get("ri_signal_strength")
        if ri_signal is not None:
            try:
                short_raw = float(ri_signal)
            except (TypeError, ValueError):
                short_raw = 0.5
        else:
            short_raw = 0.0  # 无数据 → 中性

        # 中期: UTXO 换手率 / 筹码集中度
        utxo_turnover = data.get("utxo_turnover_rate")
        if utxo_turnover is not None:
            try:
                medium_raw = float(utxo_turnover)
            except (TypeError, ValueError):
                medium_raw = 0.5
        else:
            # fallback: okx_positions 的集中度
            positions = data.get("okx_positions", {})
            if isinstance(positions, dict):
                l = float(positions.get("long", 0.5))
                s = float(positions.get("short", 0.5))
                total = l + s
                medium_raw = abs(l - s) / total if total > 0 else 0.0
            else:
                medium_raw = 0.5

        # 长期: 月线趋势线斜率（几何结构，非价格变动方向）
        monthly_slope = data.get("monthly_trend_slope")
        if monthly_slope is not None:
            try:
                long_raw = float(monthly_slope)
            except (TypeError, ValueError):
                long_raw = 0.5
        else:
            # fallback: ma_200 偏离度（非价格方向，是结构位置）
            ma200 = data.get("ma_200")
            close_arr = data.get("close")
            if ma200 is not None and close_arr is not None:
                try:
                    last_close = float(close_arr[-1]) if hasattr(close_arr, '__getitem__') else float(close_arr)
                    ma200 = float(ma200)
                    if abs(ma200) > 1e-9:
                        pct_off = (last_close - ma200) / ma200
                        long_raw = max(-1.0, min(1.0, pct_off / 0.15))  # ±15% 满档
                    else:
                        long_raw = 0.0
                except (TypeError, ValueError):
                    long_raw = 0.0
            else:
                long_raw = 0.0

        return {
            "short": self._normalize("tech_short", short_raw),
            "medium": self._normalize("tech_medium", medium_raw),
            "long": self._normalize("tech_long", long_raw),
        }

    def _eval_fundamental(self, data: dict) -> dict[str, float]:
        """基本面力量: 短/中/长."""
        # 短期: ETF 日净流入量（份额变动，非价格）
        etf_flow = data.get("etf_net_flow")
        if etf_flow is not None:
            try:
                short_raw = float(etf_flow)
            except (TypeError, ValueError):
                short_raw = 0.0
        else:
            # fallback: funding_rate 作为基本面短期代理
            fr = data.get("funding_rate")
            if fr is not None:
                try:
                    short_raw = float(fr) / 0.0001  # ±0.01% 满档
                    short_raw = max(-1.0, min(1.0, short_raw))
                except (TypeError, ValueError):
                    short_raw = 0.0
            else:
                short_raw = 0.0

        # 中期: 链上活跃地址周变化率
        active_addr = data.get("active_addresses_now")
        active_addr_prev = data.get("active_addresses_7d_ago")
        if active_addr is not None and active_addr_prev is not None:
            try:
                curr = float(active_addr)
                prev = float(active_addr_prev)
                if prev > 0:
                    medium_raw = (curr - prev) / prev
                    medium_raw = max(-1.0, min(1.0, medium_raw / 0.20))  # ±20% 满档
                else:
                    medium_raw = 0.0
            except (TypeError, ValueError):
                medium_raw = 0.0
        else:
            # fallback: exchange_net_flow
            net_flow = data.get("exchange_net_flow")
            if net_flow is not None:
                try:
                    medium_raw = max(-1.0, min(1.0, float(net_flow)))
                except (TypeError, ValueError):
                    medium_raw = 0.0
            else:
                medium_raw = 0.0

        # 长期: NVT Z-Score 或 MVRV Z-Score
        nvt = data.get("nvt_ratio")
        nvt_median = data.get("nvt_historical_median")
        if nvt is not None and nvt_median is not None:
            try:
                nvt = float(nvt)
                nvt_median = float(nvt_median)
                if nvt_median > 0:
                    # NVT 偏离中位数的程度
                    deviation = (nvt - nvt_median) / nvt_median
                    long_raw = max(-1.0, min(1.0, deviation / 0.50))  # ±50% 满档
                else:
                    long_raw = 0.0
            except (TypeError, ValueError):
                long_raw = 0.0
        else:
            long_raw = 0.0

        return {
            "short": self._normalize("fund_short", short_raw),
            "medium": self._normalize("fund_medium", medium_raw),
            "long": self._normalize("fund_long", long_raw),
        }

    def _eval_macro(self, data: dict) -> dict[str, float]:
        """宏观面力量: 短/中/长."""
        # 短期: CPI surprise (实际-预期差)
        cpi_actual = data.get("cpi_actual")
        cpi_expected = data.get("cpi_expected")
        if cpi_actual is not None and cpi_expected is not None:
            try:
                surprise = float(cpi_actual) - float(cpi_expected)
                short_raw = max(-1.0, min(1.0, surprise / 0.50))  # ±0.5% 满档
            except (TypeError, ValueError):
                short_raw = 0.0
        else:
            short_raw = 0.0

        # 中期: 利率决议预期概率
        rate_prob = data.get("rate_hike_prob")
        if rate_prob is not None:
            try:
                # prob > 0.5 → 加息预期 → 资金成本↑ → 阻力↑
                medium_raw = (float(rate_prob) - 0.5) * 2.0  # [-1, +1]
            except (TypeError, ValueError):
                medium_raw = 0.0
        else:
            medium_raw = 0.0

        # 长期: 加息/降息周期方向
        cycle_direction = data.get("monetary_cycle")
        if cycle_direction is not None:
            cycle_map = {"tightening": 1.0, "easing": -1.0, "neutral": 0.0, "hold": 0.0}
            long_raw = cycle_map.get(str(cycle_direction).lower(), 0.0)
        else:
            # fallback: dxy 变化率
            dxy_change = data.get("dxy_change_pct")
            if dxy_change is not None:
                try:
                    long_raw = max(-1.0, min(1.0, float(dxy_change) / 0.02))  # ±2% 满档
                except (TypeError, ValueError):
                    long_raw = 0.0
            else:
                long_raw = 0.0

        return {
            "short": self._normalize("macro_short", short_raw),
            "medium": self._normalize("macro_medium", medium_raw),
            "long": self._normalize("macro_long", long_raw),
        }

    def _normalize(self, key: str, raw_value: float) -> float:
        """
        Z-score 标准化 + percentile rank → [0, 1].

        1. 将原始值加入历史缓冲
        2. 计算 z-score = (raw - mean) / std
        3. 转为 percentile rank（消除异常值影响）
        4. 映射到 [0, 1]（0.5 = 中性）

        新历史（样本 < 10）时直接线性映射 raw ∈ [-1,1] → [0,1].
        """
        if not math.isfinite(raw_value):
            return 0.5

        # 初始化历史缓冲
        if key not in self._histories:
            self._histories[key] = deque(maxlen=self.HISTORY_WINDOW)

        # 样本不足时直接线性映射
        if len(self._histories[key]) < 10:
            self._histories[key].append(raw_value)
            return max(0.0, min(1.0, 0.5 + raw_value * 0.5))

        # 加入历史
        self._histories[key].append(raw_value)

        # Z-score
        hist = np.array(self._histories[key], dtype=float)
        mean = float(np.mean(hist))
        std = float(np.std(hist))
        if std < 1e-9:
            return 0.5
        z = (raw_value - mean) / std

        # Percentile rank（用历史分布的 CDF 近似）
        rank = float(np.sum(hist <= raw_value)) / len(hist)
        return max(0.0, min(1.0, rank))

    def get_primary_contradiction(self, data: dict) -> dict[str, Any] | None:
        """
        识别主要矛盾: 力量最强 + 方向明确的维度×周期.

        Returns:
            {
                "dimension": "technical" | "fundamental" | "macro",
                "timeframe": "short" | "medium" | "long",
                "direction": "BULL" | "BEAR" | "NEUTRAL",
                "strength": float,  # [0, 1]
                "all_contradictions": {...},  # 完整矩阵
            }
            None if无足够数据.
        """
        all_evals = self.evaluate(data)

        # 扁平化为候选列表
        candidates = []
        for dim, timeframes in all_evals.items():
            for tf, strength in timeframes.items():
                # 方向: strength > 0.5 = BULL, < 0.5 = BEAR, ≈0.5 = NEUTRAL
                if strength > 0.55:
                    direction = "BULL"
                elif strength < 0.45:
                    direction = "BEAR"
                else:
                    direction = "NEUTRAL"

                # 力量 = 偏离中性的绝对值
                adj_strength = abs(strength - 0.5) * 2.0  # [0, 1]
                candidates.append({
                    "dimension": dim,
                    "timeframe": tf,
                    "direction": direction,
                    "strength": adj_strength,
                    "normalized_strength": strength,
                })

        if not candidates:
            return None

        # §15 层级加权primary判定：
        # 判据1：主要矛盾 = 因果主导性 + 层级权重（非瞬时力量）
        # TIER_WEIGHT：long > medium > short（长期矛盾约束短期）
        # 力量差大时力量驱动；力量接近时层级驱动
        TIER_WEIGHT = {"short": 0.2, "medium": 0.3, "long": 0.5}
        DOMINANCE_GAP = 0.15  # 力量差超过此值时力量驱动

        def _tier_score(c):
            tier = TIER_WEIGHT.get(c["timeframe"], 0.2)
            # tier_bonus 随 strength 衰减：strength越大tier影响越小
            # strength=0时tier全权，strength=1时tier权重为0
            tier_factor = tier * (1.0 - c["strength"])
            return c["strength"] + tier_factor

        primary = max(candidates, key=_tier_score)
        if primary["strength"] < 0.01:
            return None  # 全部中性

        return {
            "dimension": primary["dimension"],
            "timeframe": primary["timeframe"],
            "direction": primary["direction"].lower(),  # 转小写匹配下游
            "strength": primary["strength"],
            "all_contradictions": all_evals,
        }
