"""
A3 策略设计节点 — 设计具体交易策略，计算仓位、止损止盈、R:R
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult

MIN_LEVERAGE = 1
MAX_LEVERAGE = 5
CONFIDENCE_THRESHOLD = float(os.environ.get("DREAMOS_CONFIDENCE_THRESHOLD", "0.4"))


def calc_dynamic_leverage(
    confidence: float,
    min_lev: int = MIN_LEVERAGE,
    max_lev: int = MAX_LEVERAGE,
    threshold: float = CONFIDENCE_THRESHOLD,
    atr_pct: Optional[float] = None,
    vol_benchmark: float = 0.025,
) -> int:
    """基于置信度+波动率动态计算杠杆倍数（Kelly 风格）

    映射逻辑:
      - 置信度 = threshold (默认 0.4) → min_lev (1x)
      - 置信度 >= 0.75 → 基础系数打满
      - atr_pct > vol_benchmark 时按比例降杠杆(高波动币降风险)
      - atr_pct < 1.0% 时最高可 +1x
    """
    if confidence <= threshold:
        return min_lev
    conf_ratio = min(1.0, (confidence - threshold) / max(1e-6, (0.75 - threshold)))
    vol_factor = 1.0
    if atr_pct is not None and atr_pct > 0:
        vol_ratio = vol_benchmark / max(1e-6, atr_pct)
        vol_factor = max(0.5, min(1.5, vol_ratio))
    target = min_lev + conf_ratio * (max_lev - min_lev)
    target *= vol_factor
    return max(min_lev, min(max_lev, int(round(target))))


def calc_dynamic_position_and_leverage(
    confidence: float,
    atr_pct: float,
    account_equity: Optional[float] = None,
    direction: str = "LONG",
    min_lev: int = MIN_LEVERAGE,
    max_lev: int = MAX_LEVERAGE,
    threshold: float = CONFIDENCE_THRESHOLD,
    symbol: str = "BTC",
    default_equity: float = 60.0,
) -> Dict[str, float]:
    """统一的 Kelly 动态仓位 & 杠杆模型（与 A5 一致）"""
    if confidence >= threshold:
        conf_score = min(1.0, (confidence - threshold) / max(1e-6, 0.75 - threshold))
    else:
        conf_score = 0.0
    conf_score = max(0.0, min(1.0, conf_score))
    atr = max(0.001, float(atr_pct) if atr_pct else 0.025)
    vol_score = 0.025 / atr
    vol_score = max(0.5, min(1.5, vol_score))
    edge = max(0.0, conf_score - 0.35)
    kelly_full = (edge * 3.0 - (1.0 - conf_score)) / 2.0
    kelly_full = max(0.02, min(0.30, kelly_full))
    kelly_half = kelly_full * 0.5
    if account_equity is None or account_equity <= 0:
        account_equity = default_equity
    eq = max(0.0, float(account_equity))
    tier1 = {"BTC", "ETH"}
    tier2 = {"SOL", "BNB", "XRP"}
    tier_small_min = {"OP", "ARB", "DOGE", "SHIB", "PEPE", "DOT"}
    max_single_pct = 0.25 if symbol.upper() in tier1 else (0.18 if symbol.upper() in tier2 else 0.15)
    min_position_usdt = 5.0 if symbol.upper() in tier_small_min else 3.0
    position = eq * kelly_half * conf_score * vol_score
    position = max(min_position_usdt, min(position, eq * max_single_pct))
    position = round(position, 2)
    leverage = calc_dynamic_leverage(
        confidence=confidence, min_lev=min_lev, max_lev=max_lev,
        threshold=threshold, atr_pct=atr_pct,
    )
    return {
        "position_size": position, "leverage": float(leverage),
        "confidence_score": round(conf_score, 3),
        "vol_score": round(vol_score, 3),
        "kelly_pct": round(kelly_half, 4),
        "max_single_pct": max_single_pct,
        "min_position_usdt": min_position_usdt,
        "account_equity": round(eq, 2),
    }


class A3StrategyNode(BaseNode):
    """A3 策略设计节点

    基于前序节点的方向和置信度，设计具体交易策略，
    包括仓位计算、止损止盈、R:R 比例等。
    """

    node_id = "A3"
    name = "策略设计"
    description = "设计交易策略，计算仓位、止损止盈、R:R 比例"
    chain = "A"
    tags = ["strategy", "risk-management", "position-sizing"]
    estimated_tokens = 0
    estimated_latency_ms = 80

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        price = mkt.get("price", 0)
        coin = mkt.get("coin", "BTC")
        atr_pct = mkt.get("atr_pct", 0.02)
        atr = price * atr_pct

        rationale: List[str] = []
        strategy: Dict[str, Any] = {}

        # 从 state 中收集方向和置信度
        direction, confidence = self._collect_direction(state)

        # A0 矛盾一致性校验
        a0_data = self._get_a0_data(state)
        if a0_data:
            main_direction = a0_data.get("main_direction", "")
            rationale.append(f"[A3-A0验证] 策略方向={direction} vs 矛盾主导={main_direction}")
            consistent = (main_direction == direction) or direction == "HOLD"
            if consistent:
                rationale.append("✅ 策略与矛盾一致 ✓")
            else:
                confidence = round(confidence * 0.85, 3)
                rationale.append(f"⚠️ 策略与矛盾不一致，置信度折扣至 {confidence:.0%}")

        # 策略设计
        if direction == "HOLD" or confidence < 0.3:
            rationale.append("[策略] 无有效方向，跳过策略设计")
            return NodeResult(
                node_id="A3",
                confidence=0.50,
                direction="HOLD",
                outputs={
                    "rationale": rationale,
                    "strategy": {},
                },
            )

        # P0-6: Kelly 动态仓位 & 杠杆（置信度 × 波动率 × 账户权益）
        acc_eq = None
        if isinstance(mkt, dict):
            acc_eq = mkt.get("account_equity") or mkt.get("totalWalletBalance") or mkt.get("eq")
            if acc_eq is not None:
                try:
                    acc_eq = float(acc_eq)
                except (TypeError, ValueError):
                    acc_eq = None
        dyn = calc_dynamic_position_and_leverage(
            confidence=confidence,
            atr_pct=atr_pct,
            account_equity=acc_eq,
            direction=direction,
            min_lev=MIN_LEVERAGE,
            max_lev=MAX_LEVERAGE,
            threshold=CONFIDENCE_THRESHOLD,
            symbol=coin,
        )
        position_size = dyn["position_size"]
        leverage = int(dyn["leverage"])
        equity = dyn["account_equity"]

        # 止损止盈计算（与A5保持一致：1.0倍ATR止损，2.0倍ATR止盈）
        if direction == "LONG":
            stop_loss = round(price * (1 - atr_pct * 1.0), 4)
            take_profit = round(price * (1 + atr_pct * 2.0), 4)
            rr_ratio = (take_profit - price) / (price - stop_loss) if price != stop_loss else 0
        else:  # SHORT
            stop_loss = round(price * (1 + atr_pct * 1.0), 4)
            take_profit = round(price * (1 - atr_pct * 2.0), 4)
            rr_ratio = (price - take_profit) / (stop_loss - price) if stop_loss != price else 0

        # R:R 评估
        if rr_ratio >= 2.0:
            rr_rating = "✅ 优秀"
        elif rr_ratio >= 1.5:
            rr_rating = "⚠️ 一般"
        else:
            rr_rating = "❌ 较差"

        rationale.append(f"[策略] {direction} {coin} @ ${price:.4f}")
        rationale.append(
            f"  Kelly 模型: eq={equity}USDT kelly={dyn['kelly_pct']:.2%} "
            f"conf={dyn['confidence_score']:.2f} vol={dyn['vol_score']:.2f} "
            f"max_single={dyn['max_single_pct']:.0%}"
        )
        rationale.append(f"  仓位: {position_size:.2f} USDT ({position_size/equity*100:.1f}% of equity)")
        rationale.append(f"  杠杆: {leverage}x (置信度={confidence:.2f} ATR%={atr_pct*100:.1f}%)")
        rationale.append(f"  止损: ${stop_loss:.4f} ({abs(price-stop_loss)/price*100:.1f}%)")
        rationale.append(f"  止盈: ${take_profit:.4f} ({abs(take_profit-price)/price*100:.1f}%)")
        rationale.append(f"  R:R: {rr_ratio:.2f}:1 {rr_rating}")

        strategy = {
            "coin": coin,
            "direction": direction,
            "entry_price": price,
            "position_size": round(position_size, 2),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rr_ratio": round(rr_ratio, 2),
            "leverage": leverage,
            "_kelly": dyn,
        }

        return NodeResult(
            node_id="A3",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "strategy": strategy,
            },
        )

    def _collect_direction(self, state: State) -> tuple:
        """从 state 的结果中收集方向和置信度"""
        direction = "HOLD"
        confidence = 0.0

        results = state.results if state.results else {}
        for node_id, result in results.items():
            if hasattr(result, "direction") and result.direction and result.direction != "HOLD":
                if hasattr(result, "confidence") and result.confidence > confidence:
                    direction = result.direction
                    confidence = result.confidence

        # 如果没有找到，使用默认值
        if direction == "HOLD":
            confidence = 0.45

        return direction, confidence

    def _get_a0_data(self, state: State) -> Dict:
        """从 state 中获取 A0 矛盾论数据"""
        results = state.results if state.results else {}
        for node_id, result in results.items():
            if node_id == "A0" or (hasattr(result, "outputs") and result.outputs and "main_contradiction" in result.outputs):
                if hasattr(result, "outputs"):
                    return result.outputs
        return {}

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}
