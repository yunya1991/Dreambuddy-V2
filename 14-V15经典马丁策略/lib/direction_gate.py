#!/usr/bin/env python3
"""
多空方向控制器 (DirectionGate)
==============================

基于风险-价值二元评估理论：
- 暴涨暴跌占市场20%，震荡占80%，整体做多占多数
- BTC有效跌破日线MA128（连续3日收盘价低于MA128）→ 全系统做空闸门打开
- 价格跌至周线MA200 → 继续做空风险较高，转为做多

三种市场状态：
  LONG_PREFERRED   — 价格在日线MA128上方，只做多（震荡+多头行情）
  SHORT_ALLOWED    — BTC有效跌破MA128后，允许做空（暴跌阶段）
  LONG_ONLY_FORCE  — 跌至周线MA200，强制做多，禁止做空（下跌末端）

状态转移：
  LONG_PREFERRED ──BTC有效跌破MA128──→ SHORT_ALLOWED
  SHORT_ALLOWED  ──BTC涨回MA128上──→ LONG_PREFERRED
  SHORT_ALLOWED  ──跌至周MA200──→ LONG_ONLY_FORCE
  LONG_ONLY_FORCE ──涨回日MA128上──→ LONG_PREFERRED

BTC风向标机制：
  - 当BTC有效跌破日线MA128（连续3日收盘价低于MA128），全系统做空闸门打开
  - 其他币种根据自身位置判断：跌破周MA200则强制做多
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List


class MarketRegime(str, Enum):
    """市场状态"""
    LONG_PREFERRED = "long_preferred"      # 做多优先（价格在日MA128上方）
    SHORT_ALLOWED = "short_allowed"        # 允许做空（BTC有效跌破MA128，在周MA200上方）
    LONG_ONLY_FORCE = "long_only_force"    # 强制做多（跌至周MA200）


class TradeDirection(str, Enum):
    """交易方向许可"""
    LONG_ONLY = "long_only"     # 只允许做多
    SHORT_ONLY = "short_only"   # 只允许做空
    BOTH = "both"               # 多空都允许
    NONE = "none"               # 都不允许（异常状态）


@dataclass
class GateResult:
    """方向控制判断结果"""
    regime: MarketRegime
    allowed_direction: TradeDirection
    price_vs_daily_ma128: str    # "above" / "below" / "unknown"
    price_vs_weekly_ma200: str   # "above" / "below" / "unknown"
    daily_ma128: Optional[float]
    weekly_ma200: Optional[float]
    current_price: float
    reason: str

    @property
    def short_enabled(self) -> bool:
        """是否允许做空"""
        return self.allowed_direction in (TradeDirection.SHORT_ONLY, TradeDirection.BOTH)

    @property
    def long_enabled(self) -> bool:
        """是否允许做多"""
        return self.allowed_direction in (TradeDirection.LONG_ONLY, TradeDirection.BOTH)

    def to_dict(self) -> Dict:
        return {
            "regime": self.regime.value,
            "allowed_direction": self.allowed_direction.value,
            "short_enabled": self.short_enabled,
            "long_enabled": self.long_enabled,
            "price_vs_daily_ma128": self.price_vs_daily_ma128,
            "price_vs_weekly_ma200": self.price_vs_weekly_ma200,
            "daily_ma128": self.daily_ma128,
            "weekly_ma200": self.weekly_ma200,
            "current_price": self.current_price,
            "reason": self.reason,
        }


class DirectionGate:
    """
    多空方向控制器
    ==============

    核心逻辑：
    1. BTC有效跌破日线MA128（连续3日收盘价低于MA128）→ 全系统做空闸门打开
    2. 价格跌至周线MA200 → 强制做多，禁止做空

    用法:
        gate = DirectionGate(allow_short=True)
        result = gate.evaluate(
            current_price=65000,
            daily_ma128=60000,
            weekly_ma200=55000,
            recent_daily_closes=[59000, 58500, 58000],  # 最近3日收盘价
            btc_short_enabled=True,                      # BTC风向标
        )
        if result.short_enabled:
            # 可以做空
    """

    def __init__(self, allow_short: bool = True, buffer_pct: float = 0.01):
        """
        Args:
            allow_short: 全局做空开关。False 时永远只做多
            buffer_pct: MA附近的缓冲带（1%），避免临界点频繁切换
        """
        self.allow_short = allow_short
        self.buffer_pct = buffer_pct

    def evaluate(
        self,
        current_price: float,
        daily_ma128: Optional[float] = None,
        weekly_ma200: Optional[float] = None,
        recent_daily_closes: Optional[List[float]] = None,
        btc_short_enabled: bool = False,
    ) -> GateResult:
        """
        评估当前市场状态和允许的交易方向

        核心判断使用收盘价确认，避免实时价格波动导致频繁切换。
        有效跌破定义：连续3日收盘价低于日线MA128

        Args:
            current_price: 当前实时价格
            daily_ma128: 日线MA128（替代原MA200，更灵敏）
            weekly_ma200: 周线MA200
            recent_daily_closes: 最近N日收盘价列表（用于判断有效跌破）
            btc_short_enabled: BTC风向标，True表示BTC已有效跌破MA128，全系统做空闸门打开
        """
        if not self.allow_short:
            return GateResult(
                regime=MarketRegime.LONG_PREFERRED,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128=self._pos(current_price, daily_ma128),
                price_vs_weekly_ma200=self._pos(current_price, weekly_ma200),
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason="全局做空开关关闭(V15_ALLOW_SHORT=false), 只做多",
            )

        if daily_ma128 is None or weekly_ma200 is None:
            return GateResult(
                regime=MarketRegime.LONG_PREFERRED,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128="unknown",
                price_vs_weekly_ma200="unknown",
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason="MA数据不足, 保守只做多",
            )

        if recent_daily_closes is None:
            recent_daily_closes = []

        daily_buffer = daily_ma128 * self.buffer_pct
        weekly_buffer = weekly_ma200 * self.buffer_pct

        price_vs_daily = self._pos(current_price, daily_ma128)
        price_vs_weekly = self._pos(current_price, weekly_ma200)

        # ── 有效跌破判断：连续3日收盘价低于MA128 ──
        has_valid_breakdown = self._check_valid_breakdown(recent_daily_closes, daily_ma128)

        # ── 核心状态判断 ──

        # 情况1: 跌至周线MA200附近 → 强制做多，禁止做空
        # 理论：跌到周线MA200说明下跌较多，继续做空风险高，转为做多
        weekly_ref = recent_daily_closes[-1] if recent_daily_closes else current_price
        if weekly_ref <= weekly_ma200 + weekly_buffer:
            return GateResult(
                regime=MarketRegime.LONG_ONLY_FORCE,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128=price_vs_daily,
                price_vs_weekly_ma200=price_vs_weekly,
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason=f"价格({weekly_ref:.2f})跌至周线MA200({weekly_ma200:.2f})附近, 做空风险高, 强制做多",
            )

        # 情况2: 全系统做空闸门未打开 → 只做多
        # BTC风向标关闭（未有效跌破MA128），整个系统不允许做空
        if not btc_short_enabled:
            return GateResult(
                regime=MarketRegime.LONG_PREFERRED,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128=price_vs_daily,
                price_vs_weekly_ma200=price_vs_weekly,
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason=f"BTC做空闸门未打开(btc_short_enabled=false), 只做多",
            )

        # 情况3: BTC做空闸门打开 + 在周MA200上方 → 允许做空
        # 理论：BTC有效跌破MA128，全系统做空闸门打开；当前币种在周MA200上方，做空价值较高
        return GateResult(
            regime=MarketRegime.SHORT_ALLOWED,
            allowed_direction=TradeDirection.BOTH,
            price_vs_daily_ma128=price_vs_daily,
            price_vs_weekly_ma200=price_vs_weekly,
            daily_ma128=daily_ma128,
            weekly_ma200=weekly_ma200,
            current_price=current_price,
            reason=f"BTC做空闸门打开(btc_short_enabled=true), 价格在周线MA200({weekly_ma200:.2f})上方, 允许做空",
        )

    def _check_valid_breakdown(self, recent_daily_closes: List[float], daily_ma128: float) -> bool:
        """
        检查是否有效跌破MA128

        有效跌破定义：连续3日收盘价低于MA128

        Args:
            recent_daily_closes: 最近N日收盘价列表
            daily_ma128: 日线MA128

        Returns:
            True: 有效跌破；False: 未有效跌破
        """
        if len(recent_daily_closes) < 3:
            return False
        last_3_closes = recent_daily_closes[-3:]
        return all(close <= daily_ma128 for close in last_3_closes)

    @staticmethod
    def _pos(price: float, ma: Optional[float]) -> str:
        if ma is None:
            return "unknown"
        return "above" if price > ma else "below"


# ── 模块级便捷函数 ──────────────────────────────────────────────

_gate_instance: Optional[DirectionGate] = None


def get_gate(allow_short: bool = True) -> DirectionGate:
    """获取全局 DirectionGate 单例"""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = DirectionGate(allow_short=allow_short)
    return _gate_instance


def reset_gate():
    """重置单例（测试用）"""
    global _gate_instance
    _gate_instance = None


def evaluate_direction(
    current_price: float,
    daily_ma128: Optional[float] = None,
    weekly_ma200: Optional[float] = None,
    recent_daily_closes: Optional[List[float]] = None,
    btc_short_enabled: bool = False,
    allow_short: bool = True,
) -> GateResult:
    """便捷函数：评估多空方向"""
    gate = DirectionGate(allow_short=allow_short)
    return gate.evaluate(
        current_price=current_price,
        daily_ma128=daily_ma128,
        weekly_ma200=weekly_ma200,
        recent_daily_closes=recent_daily_closes,
        btc_short_enabled=btc_short_enabled,
    )


# ── 向后兼容函数 ──────────────────────────────────────────────

def evaluate_direction_v1(
    current_price: float,
    daily_ma200: Optional[float] = None,
    weekly_ma200: Optional[float] = None,
    last_daily_close: Optional[float] = None,
    last_weekly_close: Optional[float] = None,
    allow_short: bool = True,
) -> GateResult:
    """
    向后兼容版本：使用原MA200参数
    注意：此函数会被新逻辑替代，保留仅用于兼容旧代码
    """
    gate = DirectionGate(allow_short=allow_short)
    recent_closes = []
    if last_daily_close is not None:
        recent_closes.append(last_daily_close)
    return gate.evaluate(
        current_price=current_price,
        daily_ma128=daily_ma200,
        weekly_ma200=weekly_ma200,
        recent_daily_closes=recent_closes,
        btc_short_enabled=True if allow_short else False,
    )


if __name__ == "__main__":
    print("=== DirectionGate 自检 (MA128 + BTC风向标) ===")

    gate = DirectionGate(allow_short=True)

    # 场景1: BTC未有效跌破MA128 → 做空闸门关闭，只做多
    r = gate.evaluate(
        current_price=65000,
        daily_ma128=60000,
        weekly_ma200=55000,
        recent_daily_closes=[62000, 61500, 61000],
        btc_short_enabled=False,
    )
    print(f"\n场景1 (BTC做空闸门关闭): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景2: BTC有效跌破MA128（连续3日收盘价低于MA128）→ 做空闸门打开
    r = gate.evaluate(
        current_price=58000,
        daily_ma128=60000,
        weekly_ma200=55000,
        recent_daily_closes=[59000, 58500, 58000],
        btc_short_enabled=True,
    )
    print(f"\n场景2 (BTC有效跌破MA128, 做空闸门打开): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景3: BTC做空闸门打开但跌至周MA200 → 强制做多
    r = gate.evaluate(
        current_price=54000,
        daily_ma128=60000,
        weekly_ma200=55000,
        recent_daily_closes=[54500, 54000, 53500],
        btc_short_enabled=True,
    )
    print(f"\n场景3 (跌至周MA200, 强制做多): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景4: 全局开关关闭
    gate_off = DirectionGate(allow_short=False)
    r = gate_off.evaluate(
        current_price=58000,
        daily_ma128=60000,
        weekly_ma200=55000,
        btc_short_enabled=True,
    )
    print(f"\n场景4 (全局做空关闭): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景5: 非BTC币种，BTC做空闸门打开
    r = gate.evaluate(
        current_price=4200,
        daily_ma128=4500,
        weekly_ma200=3800,
        btc_short_enabled=True,
    )
    print(f"\n场景5 (ETH,BTC做空闸门打开): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景6: 非BTC币种，BTC做空闸门打开但跌至周MA200
    r = gate.evaluate(
        current_price=3700,
        daily_ma128=4500,
        weekly_ma200=3800,
        btc_short_enabled=True,
    )
    print(f"\n场景6 (ETH跌至周MA200, 强制做多): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")
