"""
TraditionalFinanceBridge — 传统金融方法论桥接器

将传统金融核心概念引入自进化系统：
1. RegimeDetector   — 市场状态分类（趋势/震荡/危机），Markov切换思想
2. KellySizer        — Kelly公式最优仓位，f = (bp - q) / b
3. VolatilityScaler  — 波动率缩放，仓位 ∝ 1/σ（风险平价）
4. PerformanceTracker — Sharpe/Sortino/Calmar 跟踪，盈利验证标准

哲学根:
  - 趋势市用动量，震荡市用均值回归，危机市降杠杆（regime-aware）
  - Kelly 公式是对数最优增长的理论最优解
  - 波动率缩放是桥水/风险平价的核心
  - Sharpe > 1 是策略有效性的机构标准
"""
from __future__ import annotations

import math
import logging
from typing import Any

logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    市场状态检测器（Markov切换思想的简化版）

    三态分类:
    - "trend_up"   : 上涨趋势 (价格 > MA20 且 ADX > 20)
    - "trend_down" : 下跌趋势 (价格 < MA20 且 ADX > 20)
    - "ranging"    : 震荡市    (|价格-MA20|/MA20 < 1% 或 ADX < 20)
    - "crisis"     : 危机市    (20日波动率 > 历史90分位)
    """

    @staticmethod
    def detect(prices: list[float], highs: list[float], lows: list[float]) -> dict[str, Any]:
        """
        检测当前市场状态。
        Returns: {regime, trend_strength, volatility_ratio, adx}
        """
        try:
            # 兼容 numpy 数组 / list
            closes = [float(p) for p in list(prices)]
            if len(closes) < 20:
                return {"regime": "ranging", "trend_strength": 0.0,
                        "volatility_ratio": 1.0, "adx": 0.0}

            highs_list = [float(h) for h in list(highs)] if highs is not None else closes
            lows_list = [float(l) for l in list(lows)] if lows is not None else closes

            ma20 = sum(closes[-20:]) / 20
            price = closes[-1]

            # 1. 趋势强度 = (price - ma20) / ma20 归一化到 [-1, 1]
            trend_strength = max(-1.0, min(1.0, (price - ma20) / max(ma20, 1e-9) * 20))

            # 2. ADX 简化版（方向性指标）
            adx = RegimeDetector._calc_adx(highs_list, lows_list, closes)

            # 3. 波动率比率 = 当前20日波动率 / 历史60日波动率
            vol_20 = RegimeDetector._std(closes[-20:])
            vol_60 = RegimeDetector._std(closes[-60:]) if len(closes) >= 60 else vol_20
            vol_ratio = vol_20 / max(vol_60, 1e-9)

            # 4. 状态判定
            if vol_ratio > 1.8:
                regime = "crisis"
            elif adx > 20:
                regime = "trend_up" if price > ma20 else "trend_down"
            else:
                regime = "ranging"

            return {
                "regime": regime,
                "trend_strength": round(trend_strength, 4),
                "volatility_ratio": round(vol_ratio, 4),
                "adx": round(adx, 2),
            }
        except Exception as e:
            logger.debug("[FO] regime detect: %s", e)
            return {"regime": "ranging", "trend_strength": 0.0,
                    "volatility_ratio": 1.0, "adx": 0.0}

    @staticmethod
    def _calc_adx(highs, lows, closes, period: int = 14) -> float:
        """简化版 ADX（平均趋向指数）"""
        try:
            if len(closes) < period + 1:
                return 0.0
            plus_dm = []
            minus_dm = []
            tr = []
            for i in range(1, len(closes)):
                up = highs[i] - highs[i - 1]
                down = lows[i - 1] - lows[i]
                plus_dm.append(max(up, 0) if up > down else 0)
                minus_dm.append(max(down, 0) if down > up else 0)
                tr.append(max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                ))
            if not tr or sum(tr) == 0:
                return 0.0
            plus_di = 100 * sum(plus_dm[-period:]) / max(sum(tr[-period:]), 1e-9)
            minus_di = 100 * sum(minus_dm[-period:]) / max(sum(tr[-period:]), 1e-9)
            dx = 100 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9)
            return dx
        except Exception:
            return 0.0

    @staticmethod
    def _std(data: list[float]) -> float:
        if len(data) < 2:
            return 0.0
        mean = sum(data) / len(data)
        var = sum((x - mean) ** 2 for x in data) / len(data)
        return math.sqrt(var)


class KellySizer:
    """
    Kelly 公式仓位计算器

    f* = (b·p - q) / b
    其中:
      b = 赔率 (平均盈利 / 平均亏损)
      p = 胜率
      q = 1 - p

    实战中用 Half-Kelly (f*/2) 降低估计误差风险。
    """

    @staticmethod
    def kelly_fraction(win_rate: float, payoff_ratio: float,
                       fraction: float = 0.5) -> float:
        """
        计算 Kelly 仓位比例。
        Args:
            win_rate: 胜率 [0, 1]
            payoff_ratio: 赔率 = 平均盈利 / 平均亏损
            fraction: Kelly 分数（0.5 = Half-Kelly，机构常用）
        Returns:
            仓位比例 [0, 1]（负值表示不应下注）
        """
        try:
            p = max(0.0, min(1.0, float(win_rate)))
            b = max(0.0, float(payoff_ratio))
            q = 1.0 - p
            if b <= 0:
                return 0.0
            f_star = (b * p - q) / b
            # Half-Kelly 降低风险
            f = f_star * float(fraction)
            return max(0.0, min(1.0, f))
        except Exception:
            return 0.0


class VolatilityScaler:
    """
    波动率缩放器（风险平价思想）

    目标波动率 = 固定值（如 2%），实际仓位 = 目标波动率 / 实际波动率
    波动率越高 → 仓位越小
    """

    @staticmethod
    def vol_scalar(current_vol: float, target_vol: float = 0.02,
                   min_scalar: float = 0.2, max_scalar: float = 2.0) -> float:
        """
        计算波动率缩放系数。
        Args:
            current_vol: 当前波动率（日收益率标准差）
            target_vol: 目标波动率（默认 2%）
            min_scalar: 最小缩放（防止仓位过小）
            max_scalar: 最大缩放（防止仓位过大）
        Returns:
            缩放系数 [min_scalar, max_scalar]
        """
        try:
            if current_vol <= 0:
                return 1.0
            scalar = target_vol / current_vol
            return max(min_scalar, min(max_scalar, scalar))
        except Exception:
            return 1.0


class PerformanceTracker:
    """
    策略绩效跟踪器

    传统金融验证标准:
    - Sharpe  > 1.0: 策略有效
    - Sortino > 1.0: 下行风险可控
    - Calmar  > 1.0: 收益/回撤比良好
    - 胜率    > 50%: 方向判断有效
    """

    def __init__(self):
        self._returns: list[float] = []  # 每笔交易收益率
        self._equity_curve: list[float] = [1.0]  # 净值曲线

    def record_trade(self, pnl_pct: float) -> None:
        """记录一笔交易的收益率"""
        self._returns.append(float(pnl_pct))
        self._equity_curve.append(self._equity_curve[-1] * (1.0 + pnl_pct))

    @property
    def win_rate(self) -> float:
        if not self._returns:
            return 0.0
        wins = sum(1 for r in self._returns if r > 0)
        return wins / len(self._returns)

    @property
    def payoff_ratio(self) -> float:
        wins = [r for r in self._returns if r > 0]
        losses = [abs(r) for r in self._returns if r <= 0]
        if not losses:
            return float("inf") if wins else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 1e-9
        return avg_win / max(avg_loss, 1e-9)

    @property
    def sharpe(self) -> float:
        """年化 Sharpe 比率（假设交易频率为日频，√252 年化）"""
        if len(self._returns) < 2:
            return 0.0
        import statistics
        mean_r = statistics.mean(self._returns)
        std_r = statistics.stdev(self._returns)
        if std_r == 0:
            return 0.0
        return (mean_r / std_r) * math.sqrt(252)

    @property
    def sortino(self) -> float:
        """Sortino 比率（仅下行波动率）"""
        if len(self._returns) < 2:
            return 0.0
        import statistics
        mean_r = statistics.mean(self._returns)
        downside = [r for r in self._returns if r < 0]
        if not downside:
            return float("inf") if mean_r > 0 else 0.0
        downside_std = statistics.stdev(downside)
        if downside_std == 0:
            return 0.0
        return (mean_r / downside_std) * math.sqrt(252)

    @property
    def max_drawdown(self) -> float:
        """最大回撤"""
        if len(self._equity_curve) < 2:
            return 0.0
        peak = self._equity_curve[0]
        max_dd = 0.0
        for eq in self._equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def calmar(self) -> float:
        """Calmar 比率 = 年化收益 / 最大回撤"""
        if self.max_drawdown == 0:
            return 0.0
        total_return = self._equity_curve[-1] - 1.0
        # 假设有交易笔数对应的天数
        n_days = max(len(self._returns), 1)
        annualized = (1.0 + total_return) ** (252 / n_days) - 1.0
        return annualized / self.max_drawdown

    def summary(self) -> dict[str, Any]:
        """绩效摘要"""
        return {
            "n_trades": len(self._returns),
            "win_rate": round(self.win_rate, 4),
            "payoff_ratio": round(self.payoff_ratio, 4),
            "sharpe": round(self.sharpe, 4),
            "sortino": round(self.sortino, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "calmar": round(self.calmar, 4),
            "total_return": round(self._equity_curve[-1] - 1.0, 4),
        }


class TraditionalFinanceBridge:
    """
    传统金融桥接器 — 统一入口

    为数据管线提供:
    - regime: 市场状态
    - kelly_fraction: Kelly 仓位比例
    - vol_scalar: 波动率缩放系数
    - performance: 绩效摘要
    """

    def __init__(self):
        self._perf = PerformanceTracker()

    def analyze(self, kline_data: dict[str, Any]) -> dict[str, Any]:
        """
        分析市场状态并输出传统金融信号。
        """
        try:
            prices = kline_data.get("close")
            highs = kline_data.get("high")
            lows = kline_data.get("low")
            if prices is None:
                prices = []
            if highs is None:
                highs = []
            if lows is None:
                lows = []

            # 1. Regime 检测
            regime_info = RegimeDetector.detect(prices, highs, lows)

            # 2. 波动率缩放
            closes_list = [float(p) for p in list(prices)]
            current_vol = RegimeDetector._std(
                closes_list[-20:]
            ) if len(closes_list) >= 20 else 0.0
            vol_scalar = VolatilityScaler.vol_scalar(current_vol)

            # 3. Kelly 仓位（基于历史绩效，若没有交易记录则用中性 0.1）
            perf = self._perf.summary()
            if perf["n_trades"] >= 5:
                kelly_f = KellySizer.kelly_fraction(
                    win_rate=perf["win_rate"],
                    payoff_ratio=perf["payoff_ratio"],
                )
            else:
                kelly_f = 0.10  # 训练期默认 10% 风险预算

            return {
                "regime": regime_info["regime"],
                "trend_strength": regime_info["trend_strength"],
                "volatility_ratio": regime_info["volatility_ratio"],
                "adx": regime_info["adx"],
                "vol_scalar": round(vol_scalar, 4),
                "kelly_fraction": round(kelly_f, 4),
                "performance": perf,
            }
        except Exception as e:
            logger.warning("[FO] TraditionalFinanceBridge crash: %s", e)
            return {
                "regime": "ranging",
                "trend_strength": 0.0,
                "volatility_ratio": 1.0,
                "adx": 0.0,
                "vol_scalar": 1.0,
                "kelly_fraction": 0.10,
                "performance": PerformanceTracker().summary(),
            }

    def record_trade(self, pnl_pct: float) -> None:
        """记录交易结果用于绩效跟踪"""
        self._perf.record_trade(pnl_pct)
