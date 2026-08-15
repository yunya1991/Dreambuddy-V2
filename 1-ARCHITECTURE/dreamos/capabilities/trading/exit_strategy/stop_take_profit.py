#!/usr/bin/env python3
"""
专业止盈止损策略模块

支持多种策略：
1. ATR止损止盈 — 基于波动率的对称/非对称策略
2. 固定百分比止损止盈 — 简单直接的比例控制
3. 移动止盈（追踪止损）— 保护已有利润
4. 斐波那契回调止损止盈 — 基于支撑阻力位
5. 动态止损 — 基于置信度和波动率动态调整

方向处理：
- LONG: 止损在下方，止盈在上方
- SHORT: 止损在上方，止盈在下方
"""

from __future__ import annotations

import math
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, Tuple, List


# ============================================================
# 策略枚举
# ============================================================

class StopLossStrategy(str, Enum):
    """止损策略类型"""
    ATR = "atr"
    FIXED_PCT = "fixed_pct"
    DYNAMIC = "dynamic"
    FIBONACCI = "fibonacci"
    TRAILING = "trailing"


class TakeProfitStrategy(str, Enum):
    """止盈策略类型"""
    ATR = "atr"
    FIXED_PCT = "fixed_pct"
    RATIO = "ratio"
    FIBONACCI = "fibonacci"
    TRAILING = "trailing"


class MarketRegime(str, Enum):
    """市场状态类型"""
    TREND_BULL = "trend_bull"
    TREND_BEAR = "trend_bear"
    RANGING = "ranging"


class SymbolVolatility(str, Enum):
    """币种波动率分类"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ============================================================
# 配置类
# ============================================================

@dataclass
class StopTakeProfitConfig:
    """止盈止损配置"""

    # 止损配置
    stop_strategy: StopLossStrategy = StopLossStrategy.ATR
    stop_atr_multiplier: float = 1.0
    stop_fixed_pct: float = 0.02
    stop_dynamic_base: float = 0.015
    stop_dynamic_max: float = 0.04
    stop_fib_level: str = "f382"
    stop_trailing_pct: float = 0.01

    # 止盈配置
    take_strategy: TakeProfitStrategy = TakeProfitStrategy.RATIO
    take_atr_multiplier: float = 2.0
    take_fixed_pct: float = 0.04
    take_ratio: float = 2.0
    take_fib_level: str = "f618"
    take_trailing_pct: float = 0.015

    # 全局配置
    min_rr_ratio: float = 1.5
    max_risk_pct: float = 0.02
    enable_trailing_tp: bool = True
    trailing_activation_pct: float = 0.015

    # 动态调整配置（市场状态相关）
    ranging_multiplier: float = 1.5       # 震荡市放大倍数
    trend_multiplier: float = 0.8        # 趋势市缩小倍数
    low_vol_multiplier: float = 0.8       # 低波动率缩小倍数
    high_vol_multiplier: float = 1.3      # 高波动率放大倍数

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StopTakeProfitResult:
    """止盈止损计算结果"""
    stop_loss: float
    take_profit: float
    rr_ratio: float
    risk_pct: float
    stop_strategy: str
    take_strategy: str
    rationale: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# 斐波那契工具
# ============================================================

class FibonacciCalculator:
    """斐波那契回调位计算"""

    LEVELS = {
        "f000": 0.0,
        "f236": 0.236,
        "f382": 0.382,
        "f500": 0.500,
        "f618": 0.618,
        "f786": 0.786,
        "f1000": 1.0,
    }

    @staticmethod
    def calculate(swing_high: float, swing_low: float) -> Dict[str, float]:
        """计算斐波那契回调位"""
        range_size = swing_high - swing_low
        return {
            level: swing_low + ratio * range_size
            for level, ratio in FibonacciCalculator.LEVELS.items()
        }

    @staticmethod
    def get_level_value(level: str) -> float:
        """获取斐波那契水平值"""
        return FibonacciCalculator.LEVELS.get(level, 0.5)


# ============================================================
# 止盈止损引擎
# ============================================================

class StopTakeProfitEngine:
    """专业止盈止损计算引擎"""

    def __init__(self, config: Optional[StopTakeProfitConfig] = None):
        self.config = config or StopTakeProfitConfig()

    def calculate(self,
                  direction: str,
                  entry_price: float,
                  atr_pct: float = 0.02,
                  confidence: float = 0.5,
                  swing_high: Optional[float] = None,
                  swing_low: Optional[float] = None,
                  market_regime: Optional[str] = None,
                  symbol_volatility: Optional[str] = None) -> StopTakeProfitResult:
        """计算止盈止损

        Args:
            direction: LONG / SHORT
            entry_price: 入场价格
            atr_pct: ATR百分比
            confidence: 置信度 (0-1)
            swing_high: 波动高点（用于斐波那契）
            swing_low: 波动低点（用于斐波那契）
            market_regime: 市场状态 (trend_bull/trend_bear/ranging)
            symbol_volatility: 币种波动率 (low/medium/high)

        Returns:
            StopTakeProfitResult: 止盈止损结果

        Raises:
            ValueError: 入场价格无效（≤0，通常因行情数据缺失降级）
        """
        if entry_price is None or entry_price <= 0:
            raise ValueError(f"无效入场价格: {entry_price!r}（必须>0，通常因行情数据缺失）")
        if atr_pct is None or atr_pct < 0:
            atr_pct = 0.0
        rationale: List[str] = []

        # 动态计算 ATR 乘数（基于市场状态和币种波动率）
        dynamic_atr_multiplier = self._calculate_dynamic_atr_multiplier(
            market_regime=market_regime,
            symbol_volatility=symbol_volatility,
            confidence=confidence,
        )
        rationale.append(f"动态ATR乘数: {dynamic_atr_multiplier:.2f}x")

        # 1. 计算止损
        stop_loss, stop_rationale = self._calculate_stop_loss(
            direction, entry_price, atr_pct, confidence, swing_high, swing_low,
            dynamic_atr_multiplier=dynamic_atr_multiplier,
        )
        rationale.extend(stop_rationale)

        # 2. 计算止盈
        take_profit, take_rationale = self._calculate_take_profit(
            direction, entry_price, stop_loss, atr_pct, confidence, swing_high, swing_low,
            dynamic_atr_multiplier=dynamic_atr_multiplier,
        )
        rationale.extend(take_rationale)

        # 3. 计算风险回报比
        rr_ratio = self._calculate_rr_ratio(direction, entry_price, stop_loss, take_profit)

        # 4. 计算风险百分比
        risk_pct = self._calculate_risk_pct(direction, entry_price, stop_loss)

        # 5. 验证最小风险回报比
        if rr_ratio < self.config.min_rr_ratio:
            take_profit = self._adjust_take_profit_for_min_rr(
                direction, entry_price, stop_loss, rr_ratio
            )
            rr_ratio = self._calculate_rr_ratio(direction, entry_price, stop_loss, take_profit)
            rationale.append(f"调整止盈以满足最小R:R={self.config.min_rr_ratio}:1")

        return StopTakeProfitResult(
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            rr_ratio=round(rr_ratio, 2),
            risk_pct=round(risk_pct, 4),
            stop_strategy=self.config.stop_strategy.value,
            take_strategy=self.config.take_strategy.value,
            rationale=rationale,
        )

    def _calculate_dynamic_atr_multiplier(self, market_regime: Optional[str],
                                          symbol_volatility: Optional[str],
                                          confidence: float) -> float:
        """根据市场状态和币种波动率动态计算 ATR 乘数

        设计逻辑:
        - 震荡市 (ranging): 放大止损范围，避免频繁止损
        - 趋势市 (trend_bull/trend_bear): 缩小止损范围，快速止损
        - 高波动率币种: 放大止损范围
        - 低波动率币种: 缩小止损范围
        - 高置信度: 可适当缩小止损（信号更可靠）
        """
        base_multiplier = 1.0

        # 市场状态调整
        if market_regime == MarketRegime.RANGING.value:
            base_multiplier *= self.config.ranging_multiplier
        elif market_regime in [MarketRegime.TREND_BULL.value, MarketRegime.TREND_BEAR.value]:
            base_multiplier *= self.config.trend_multiplier

        # 币种波动率调整
        if symbol_volatility == SymbolVolatility.HIGH.value:
            base_multiplier *= self.config.high_vol_multiplier
        elif symbol_volatility == SymbolVolatility.LOW.value:
            base_multiplier *= self.config.low_vol_multiplier

        # 置信度调整（高置信度可适当缩小）
        if confidence > 0.7:
            base_multiplier *= (1 - (confidence - 0.7) * 0.5)

        # 限制范围
        return max(0.5, min(3.0, base_multiplier))

    def _calculate_stop_loss(self, direction: str, entry_price: float,
                             atr_pct: float, confidence: float,
                             swing_high: Optional[float], swing_low: Optional[float],
                             dynamic_atr_multiplier: float = 1.0) -> Tuple[float, List[str]]:
        """计算止损价格"""
        rationale: List[str] = []
        stop_loss = 0.0

        strategy = self.config.stop_strategy

        if strategy == StopLossStrategy.ATR:
            multiplier = self.config.stop_atr_multiplier * dynamic_atr_multiplier
            stop_distance = entry_price * atr_pct * multiplier
            if direction == "LONG":
                stop_loss = entry_price - stop_distance
            else:
                stop_loss = entry_price + stop_distance
            rationale.append(f"ATR止损: {multiplier:.2f}x ATR ({(stop_distance / entry_price if entry_price else 0.0):.2%})")

        elif strategy == StopLossStrategy.FIXED_PCT:
            pct = self.config.stop_fixed_pct * dynamic_atr_multiplier
            stop_distance = entry_price * pct
            if direction == "LONG":
                stop_loss = entry_price - stop_distance
            else:
                stop_loss = entry_price + stop_distance
            rationale.append(f"固定止损: {pct:.2%}")

        elif strategy == StopLossStrategy.DYNAMIC:
            base_pct = self.config.stop_dynamic_base
            max_pct = self.config.stop_dynamic_max
            pct = base_pct + (1 - confidence) * (max_pct - base_pct)
            pct *= dynamic_atr_multiplier
            stop_distance = entry_price * pct
            if direction == "LONG":
                stop_loss = entry_price - stop_distance
            else:
                stop_loss = entry_price + stop_distance
            rationale.append(f"动态止损: {pct:.2%} (置信度={confidence:.1%})")

        elif strategy == StopLossStrategy.FIBONACCI:
            if swing_high is None or swing_low is None:
                return self._calculate_stop_loss(direction, entry_price, atr_pct, confidence, None, None)
            fib_level = self.config.stop_fib_level
            fib_value = FibonacciCalculator.get_level_value(fib_level)
            if direction == "LONG":
                stop_loss = swing_low + (swing_high - swing_low) * fib_value
            else:
                stop_loss = swing_high - (swing_high - swing_low) * fib_value
            rationale.append(f"斐波那契止损: {fib_level} ({fib_value:.3f})")

        elif strategy == StopLossStrategy.TRAILING:
            pct = self.config.stop_trailing_pct * dynamic_atr_multiplier
            if direction == "LONG":
                stop_loss = entry_price * (1 - pct)
            else:
                stop_loss = entry_price * (1 + pct)
            rationale.append(f"追踪止损: {pct:.2%}")

        else:
            return self._calculate_stop_loss(direction, entry_price, atr_pct, confidence, None, None)

        return stop_loss, rationale

    def _calculate_take_profit(self, direction: str, entry_price: float, stop_loss: float,
                               atr_pct: float, confidence: float,
                               swing_high: Optional[float], swing_low: Optional[float],
                               dynamic_atr_multiplier: float = 1.0) -> Tuple[float, List[str]]:
        """计算止盈价格"""
        rationale: List[str] = []
        take_profit = 0.0

        strategy = self.config.take_strategy

        if strategy == TakeProfitStrategy.ATR:
            multiplier = self.config.take_atr_multiplier * dynamic_atr_multiplier
            take_distance = entry_price * atr_pct * multiplier
            if direction == "LONG":
                take_profit = entry_price + take_distance
            else:
                take_profit = entry_price - take_distance
            rationale.append(f"ATR止盈: {multiplier:.2f}x ATR ({(take_distance / entry_price if entry_price else 0.0):.2%})")

        elif strategy == TakeProfitStrategy.FIXED_PCT:
            pct = self.config.take_fixed_pct * dynamic_atr_multiplier
            take_distance = entry_price * pct
            if direction == "LONG":
                take_profit = entry_price + take_distance
            else:
                take_profit = entry_price - take_distance
            rationale.append(f"固定止盈: {pct:.2%}")

        elif strategy == TakeProfitStrategy.RATIO:
            ratio = self.config.take_ratio
            if direction == "LONG":
                stop_distance = entry_price - stop_loss
            else:
                stop_distance = stop_loss - entry_price
            take_distance = stop_distance * ratio
            if direction == "LONG":
                take_profit = entry_price + take_distance
            else:
                take_profit = entry_price - take_distance
            rationale.append(f"R:R={ratio}:1 止盈")

        elif strategy == TakeProfitStrategy.FIBONACCI:
            if swing_high is None or swing_low is None:
                return self._calculate_take_profit(direction, entry_price, stop_loss, atr_pct, confidence, None, None)
            fib_level = self.config.take_fib_level
            fib_value = FibonacciCalculator.get_level_value(fib_level)
            if direction == "LONG":
                take_profit = swing_low + (swing_high - swing_low) * fib_value
            else:
                take_profit = swing_high - (swing_high - swing_low) * fib_value
            rationale.append(f"斐波那契止盈: {fib_level} ({fib_value:.3f})")

        elif strategy == TakeProfitStrategy.TRAILING:
            pct = self.config.take_trailing_pct * dynamic_atr_multiplier
            if direction == "LONG":
                take_profit = entry_price * (1 + pct * 2)
            else:
                take_profit = entry_price * (1 - pct * 2)
            rationale.append(f"追踪止盈: 激活后{self.config.trailing_activation_pct:.2%}追踪")

        else:
            return self._calculate_take_profit(direction, entry_price, stop_loss, atr_pct, confidence, None, None)

        return take_profit, rationale

    def _calculate_rr_ratio(self, direction: str, entry_price: float,
                            stop_loss: float, take_profit: float) -> float:
        """计算风险回报比"""
        if direction == "LONG":
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit

        if risk <= 0:
            return 0.0
        return reward / risk

    def _calculate_risk_pct(self, direction: str, entry_price: float, stop_loss: float) -> float:
        """计算单笔风险百分比"""
        if direction == "LONG":
            return (entry_price - stop_loss) / entry_price
        else:
            return (stop_loss - entry_price) / entry_price

    def _adjust_take_profit_for_min_rr(self, direction: str, entry_price: float,
                                        stop_loss: float, current_rr: float) -> float:
        """调整止盈以满足最小风险回报比"""
        target_rr = self.config.min_rr_ratio
        if direction == "LONG":
            stop_distance = entry_price - stop_loss
            take_distance = stop_distance * target_rr
            return entry_price + take_distance
        else:
            stop_distance = stop_loss - entry_price
            take_distance = stop_distance * target_rr
            return entry_price - take_distance


# ============================================================
# 移动止盈追踪器
# ============================================================

class TrailingStopTracker:
    """移动止盈追踪器

    用法:
        tracker = TrailingStopTracker(entry_price=67500, direction="LONG", trail_pct=0.015)
        tracker.update(current_price=67800)
        stop_price = tracker.get_stop_price()
        should_exit = tracker.should_exit(current_price=67600)
    """

    def __init__(self, entry_price: float, direction: str, trail_pct: float = 0.015,
                 activation_pct: float = 0.015):
        self.entry_price = entry_price
        self.direction = direction
        self.trail_pct = trail_pct
        self.activation_pct = activation_pct
        self.activated = False
        self.highest_price = entry_price if direction == "LONG" else entry_price
        self.lowest_price = entry_price if direction == "SHORT" else entry_price
        self.current_stop_price = 0.0

        if direction == "LONG":
            self.activation_price = entry_price * (1 + activation_pct)
        else:
            self.activation_price = entry_price * (1 - activation_pct)

    def update(self, current_price: float) -> None:
        """更新追踪状态"""
        if self.direction == "LONG":
            if current_price >= self.activation_price:
                self.activated = True

            if self.activated and current_price > self.highest_price:
                self.highest_price = current_price
                self.current_stop_price = current_price * (1 - self.trail_pct)

        else:
            if current_price <= self.activation_price:
                self.activated = True

            if self.activated and current_price < self.lowest_price:
                self.lowest_price = current_price
                self.current_stop_price = current_price * (1 + self.trail_pct)

    def get_stop_price(self) -> float:
        """获取当前追踪止损价"""
        return self.current_stop_price if self.activated else 0.0

    def should_exit(self, current_price: float) -> bool:
        """判断是否应该离场"""
        if not self.activated:
            return False

        if self.direction == "LONG":
            return current_price <= self.current_stop_price
        else:
            return current_price >= self.current_stop_price

    def get_profit_pct(self) -> float:
        """获取当前利润百分比"""
        if self.direction == "LONG":
            return (self.highest_price - self.entry_price) / self.entry_price * 100
        else:
            return (self.entry_price - self.lowest_price) / self.entry_price * 100


# ============================================================
# 入口函数
# ============================================================

def calculate_stop_take_profit(
    direction: str,
    entry_price: float,
    atr_pct: float = 0.02,
    confidence: float = 0.5,
    stop_strategy: str = "atr",
    take_strategy: str = "ratio",
    market_regime: Optional[str] = None,
    symbol_volatility: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """便捷计算止盈止损

    Args:
        direction: LONG / SHORT
        entry_price: 入场价格
        atr_pct: ATR百分比
        confidence: 置信度
        stop_strategy: 止损策略 (atr/fixed_pct/dynamic/fibonacci/trailing)
        take_strategy: 止盈策略 (atr/fixed_pct/ratio/fibonacci/trailing)
        market_regime: 市场状态 (trend_bull/trend_bear/ranging)
        symbol_volatility: 币种波动率 (low/medium/high)
        **kwargs: 额外配置参数

    Returns:
        Dict: 包含 stop_loss, take_profit, rr_ratio 等
    """
    config = StopTakeProfitConfig()

    # 设置策略
    try:
        config.stop_strategy = StopLossStrategy(stop_strategy)
    except ValueError:
        pass

    try:
        config.take_strategy = TakeProfitStrategy(take_strategy)
    except ValueError:
        pass

    # 更新额外参数
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)

    engine = StopTakeProfitEngine(config)
    result = engine.calculate(
        direction=direction,
        entry_price=entry_price,
        atr_pct=atr_pct,
        confidence=confidence,
        swing_high=kwargs.get("swing_high"),
        swing_low=kwargs.get("swing_low"),
        market_regime=market_regime,
        symbol_volatility=symbol_volatility,
    )

    return result.to_dict()


# ============================================================
# 测试入口
# ============================================================

def main():
    """测试止盈止损计算"""
    import argparse

    parser = argparse.ArgumentParser(description="止盈止损计算器")
    parser.add_argument("--direction", "-d", type=str, default="LONG", help="方向 LONG/SHORT")
    parser.add_argument("--price", "-p", type=float, default=67500.0, help="入场价格")
    parser.add_argument("--atr", type=float, default=0.02, help="ATR百分比")
    parser.add_argument("--confidence", "-c", type=float, default=0.7, help="置信度")
    parser.add_argument("--stop-strategy", type=str, default="atr", help="止损策略")
    parser.add_argument("--take-strategy", type=str, default="ratio", help="止盈策略")
    parser.add_argument("--market-regime", "-mr", type=str, default="ranging",
                        help="市场状态: trend_bull/trend_bear/ranging")
    parser.add_argument("--symbol-volatility", "-sv", type=str, default="high",
                        help="币种波动率: low/medium/high")

    args = parser.parse_args()

    result = calculate_stop_take_profit(
        direction=args.direction,
        entry_price=args.price,
        atr_pct=args.atr,
        confidence=args.confidence,
        stop_strategy=args.stop_strategy,
        take_strategy=args.take_strategy,
        market_regime=args.market_regime,
        symbol_volatility=args.symbol_volatility,
        swing_high=args.price * 1.05,
        swing_low=args.price * 0.95,
    )

    print(f"\n{'='*50}")
    print(f"止盈止损计算结果")
    print(f"{'='*50}")
    print(f"方向: {args.direction}")
    print(f"入场价: ${args.price:.4f}")
    print(f"止损价: ${result['stop_loss']:.4f}")
    print(f"止盈价: ${result['take_profit']:.4f}")
    print(f"风险回报比: {result['rr_ratio']:.2f}:1")
    print(f"风险百分比: {result['risk_pct']:.2%}")
    print(f"止损策略: {result['stop_strategy']}")
    print(f"止盈策略: {result['take_strategy']}")
    print(f"市场状态: {args.market_regime}")
    print(f"币种波动率: {args.symbol_volatility}")
    print("\n计算依据:")
    for i, r in enumerate(result.get("rationale", []), 1):
        print(f"  {i}. {r}")

    # 测试移动止盈追踪器
    print(f"\n{'='*50}")
    print(f"移动止盈追踪器测试")
    print(f"{'='*50}")
    tracker = TrailingStopTracker(
        entry_price=args.price,
        direction=args.direction,
        trail_pct=0.015,
        activation_pct=0.015,
    )

    test_prices = [args.price]
    if args.direction == "LONG":
        test_prices.extend([args.price * 1.005, args.price * 1.01, args.price * 1.02,
                           args.price * 1.015, args.price * 1.01, args.price * 1.005])
    else:
        test_prices.extend([args.price * 0.995, args.price * 0.99, args.price * 0.98,
                           args.price * 0.985, args.price * 0.99, args.price * 0.995])

    for idx, price in enumerate(test_prices):
        tracker.update(price)
        stop = tracker.get_stop_price()
        exit_flag = tracker.should_exit(price)
        print(f"Step {idx}: 价格=${price:.2f}, 追踪止损=${stop:.2f}, 激活={tracker.activated}, 离场={exit_flag}")


if __name__ == "__main__":
    main()