"""
场景分类器 — 市场场景三维分类

三维分类:
    - 趋势方向: BULL / BEAR / NEUTRAL
    - 波动率等级: LOW / NORMAL / HIGH / EXTREME
    - 动量加速度: ACCELERATING / DECELERATING / EXHAUSTION

总计 3 × 4 × 3 = 36 种场景

复用:
    - A6节点趋势/波动率计算逻辑 (a6_regime_monitor.py)
    - C2节点动量计算 (c2_momentum.py)
    - screen_engine 衰竭检测逻辑
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional


@dataclass
class ScenarioResult:
    """场景分类结果"""
    scenario_id: str        # "BULL_NORMAL_ACCELERATING"
    trend: str              # "BULL" / "BEAR" / "NEUTRAL"
    volatility: str         # "LOW" / "NORMAL" / "HIGH" / "EXTREME"
    momentum: str           # "ACCELERATING" / "DECELERATING" / "EXHAUSTION"
    trend_score: float      # 0-1
    volatility_pct: float   # ATR%
    momentum_speed: float   # 0-100
    momentum_accel: float   # 有符号
    exhaustion: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ScenarioClassifier:
    """市场场景分类器

    用法:
        classifier = ScenarioClassifier()
        result = classifier.classify(market_data)
        print(result.scenario_id)  # "BULL_NORMAL_ACCELERATING"
    """

    # 波动率阈值（复用A6节点 a6_regime_monitor.py 第33-37行）
    VOLATILITY_THRESHOLDS = {
        "EXTREME": 0.04,
        "HIGH": 0.02,
        "NORMAL": 0.01,
    }

    # 趋势阈值
    TREND_THRESHOLD = 0.6

    def classify(self, market_data: Dict[str, Any]) -> ScenarioResult:
        """输入行情数据，输出场景分类结果

        Args:
            market_data: 行情字典，需包含 price/ema20/ema50/ema200/change_24h/
                         change_4h/change_1h/atr_pct 等字段

        Returns:
            ScenarioResult: 场景分类结果
        """
        trend = self._classify_trend(market_data)
        volatility = self._classify_volatility(market_data)
        momentum_state = self._classify_momentum(market_data)

        scenario_id = f"{trend}_{volatility}_{momentum_state}"

        return ScenarioResult(
            scenario_id=scenario_id,
            trend=trend,
            volatility=volatility,
            momentum=momentum_state,
            trend_score=self._last_trend_score,
            volatility_pct=market_data.get("atr_pct", 0.02),
            momentum_speed=self._last_momentum_speed,
            momentum_accel=self._last_momentum_accel,
            exhaustion=self._last_exhaustion,
        )

    def _classify_trend(self, mkt: Dict[str, Any]) -> str:
        """趋势分类 — 复用A6 _calculate_trend_score逻辑

        BULL: price>ema20>ema50>ema200 且 trend_score>=0.6
        BEAR: price<ema20<ema50<ema200 且 trend_score>=0.6
        NEUTRAL: 其他
        """
        price = mkt.get("price", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)
        ema200 = mkt.get("ema200", price)
        change_24h = mkt.get("change_24h", 0)

        score = 0.0
        bull_align = price > ema20 > ema50 > ema200
        bear_align = price < ema20 < ema50 < ema200

        if bull_align:
            score += 0.4
        elif bear_align:
            score += 0.4

        if ema20 > ema50:
            score += 0.2
        elif ema20 < ema50:
            score += 0.2

        score += abs(change_24h) * 0.3
        score = min(max(score, 0), 1)
        self._last_trend_score = score

        if bull_align and score >= self.TREND_THRESHOLD:
            return "BULL"
        elif bear_align and score >= self.TREND_THRESHOLD:
            return "BEAR"
        else:
            return "NEUTRAL"

    def _classify_volatility(self, mkt: Dict[str, Any]) -> str:
        """波动率分类 — 复用A6 _determine_volatility逻辑

        EXTREME: atr_pct>=0.04
        HIGH: atr_pct>=0.02
        NORMAL: atr_pct>=0.01
        LOW: atr_pct<0.01
        """
        atr_pct = mkt.get("atr_pct", 0.02)

        if atr_pct >= self.VOLATILITY_THRESHOLDS["EXTREME"]:
            return "EXTREME"
        elif atr_pct >= self.VOLATILITY_THRESHOLDS["HIGH"]:
            return "HIGH"
        elif atr_pct >= self.VOLATILITY_THRESHOLDS["NORMAL"]:
            return "NORMAL"
        else:
            return "LOW"

    def _classify_momentum(self, mkt: Dict[str, Any]) -> str:
        """动量加速度分类 — 复用C2动量计算 + screen_engine衰竭检测

        ACCELERATING: speed>50 且 accel>0
        DECELERATING: speed>30 且 accel<0 （趋势仍在但减速）
        EXHAUSTION: 衰竭信号（加速度转负 + 短期与中期动量背离）
        """
        ch1h = mkt.get("change_1h", 0)
        ch4h = mkt.get("change_4h", 0)
        ch24h = mkt.get("change_24h", 0)
        rsi = mkt.get("rsi14", 50)

        # 动量速度（复用C2逻辑，归一化到0-100）
        # change_24h*0.5 + change_4h*0.3 + change_1h*0.2 的绝对值作为基础
        raw_speed = abs(ch24h) * 0.5 + abs(ch4h) * 0.3 + abs(ch1h) * 0.2
        # 归一化：5%的变动对应50的速度，10%对应100
        speed = min(raw_speed * 10, 100)
        self._last_momentum_speed = speed

        # 动量加速度：短期动量 vs 中期动量
        # 正值=加速，负值=减速
        short_term = ch1h
        mid_term = ch4h / 4 if ch4h != 0 else 0  # 4h均值
        accel = short_term - mid_term
        self._last_momentum_accel = accel

        # 衰竭检测（复用screen_engine _detect_exhaustion 第310行逻辑）
        # 多头衰竭: 价格上涨但短期动量转负且RSI超买回落
        # 空头衰竭: 价格下跌但短期动量转正且RSI超卖回升
        exhaustion = False
        if ch24h > 2 and short_term < 0 and rsi > 65:
            exhaustion = True
        elif ch24h < -2 and short_term > 0 and rsi < 35:
            exhaustion = True

        self._last_exhaustion = exhaustion

        if exhaustion:
            return "EXHAUSTION"
        elif speed > 50 and accel > 0:
            return "ACCELERATING"
        elif speed > 30 and accel < 0:
            return "DECELERATING"
        elif speed <= 30:
            # 低速时按加速度方向判定
            return "DECELERATING" if accel < 0 else "ACCELERATING"
        else:
            return "ACCELERATING"

    # 内部状态（在classify调用链中暂存）
    _last_trend_score: float = 0.0
    _last_momentum_speed: float = 0.0
    _last_momentum_accel: float = 0.0
    _last_exhaustion: bool = False
