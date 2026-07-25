"""三屏趋势系统 — 价值与风险评估模型

基于 Elder-ray 趋势强度 + 波动率 + 背离检测，
判断"价值是否高于风险"，为加仓决策提供依据。

核心功能：
1. Elder-ray 趋势强度检测（来自V15经典马丁策略）
2. 30日波动率计算与波动率放大系数
3. 背离检测（看涨/看跌背离）
4. 价值风险比（Risk/Reward Ratio）计算
5. 加仓可行性评估
"""

from typing import Dict, List, Optional

try:
    from .config import CANDIDATE_COINS
except ImportError:
    pass


def _calc_ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = closes[0]
    for p in closes[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_30d_volatility(closes: List[float]) -> float:
    if len(closes) < 31:
        return 0.02
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    recent_returns = returns[-30:]
    avg = sum(recent_returns) / len(recent_returns)
    variance = sum((r - avg) ** 2 for r in recent_returns) / len(recent_returns)
    return variance**0.5


def calc_elder_ray(klines: List[Dict], period: int = 13) -> Optional[Dict]:
    highs = [float(k["high"]) for k in klines if "high" in k]
    lows = [float(k["low"]) for k in klines if "low" in k]
    closes = [float(k["close"]) for k in klines if "close" in k]

    if len(closes) < period + 5 or len(highs) != len(closes) or len(lows) != len(closes):
        return None

    n = len(closes)
    alpha = 2 / (period + 1)

    emas = []
    bull_powers = []
    bear_powers = []

    ema = closes[0]
    for i in range(n):
        if i > 0:
            ema = closes[i] * alpha + ema * (1 - alpha)
        emas.append(ema)
        bull_powers.append(highs[i] - ema)
        bear_powers.append(lows[i] - ema)

    current_ema = emas[-1]
    current_bull = bull_powers[-1]
    current_bear = bear_powers[-1]

    bull_pct = current_bull / current_ema * 100 if current_ema > 0 else 0
    bear_pct = current_bear / current_ema * 100 if current_ema > 0 else 0

    if len(emas) >= 4 and emas[-4] != 0:
        ema_slope = (emas[-1] - emas[-4]) / emas[-4] * 100
    else:
        ema_slope = 0

    ema_trend_up = ema_slope > 0.01
    ema_trend_down = ema_slope < -0.01
    ema_trend_flat = not ema_trend_up and not ema_trend_down

    lookback = min(20, n - 1)
    bearish_divergence = False
    bullish_divergence = False

    if lookback >= 5:
        recent_high_idx = n - lookback + closes[-lookback:].index(max(closes[-lookback:]))
        if closes[-1] >= closes[recent_high_idx] and bull_powers[-1] < bull_powers[recent_high_idx]:
            bearish_divergence = True

        recent_low_idx = n - lookback + closes[-lookback:].index(min(closes[-lookback:]))
        if closes[-1] <= closes[recent_low_idx] and bear_powers[-1] > bear_powers[recent_low_idx]:
            bullish_divergence = True

    if len(bull_powers) >= 4:
        bull_rising = bull_powers[-1] > bull_powers[-2] > bull_powers[-3]
        bull_falling = bull_powers[-1] < bull_powers[-2] < bull_powers[-3]
    else:
        bull_rising = bull_falling = False

    if len(bear_powers) >= 4:
        bear_rising = bear_powers[-1] > bear_powers[-2] > bear_powers[-3]
        bear_falling = bear_powers[-1] < bear_powers[-2] < bear_powers[-3]
    else:
        bear_rising = bear_falling = False

    bull_out_of_control = current_bull < 0
    bear_out_of_control = current_bear > 0

    both_weakening = (current_bull > 0 and bull_rising) and (current_bear < 0 and bear_rising)

    if ema_trend_up and current_bull > 0 and current_bear > 0:
        direction = "STRONG_BULL"
        strength_base = 80
    elif ema_trend_up and current_bull > 0 and current_bear <= 0:
        direction = "BULL_TREND"
        strength_base = 65
    elif ema_trend_up and current_bull <= 0:
        direction = "BULL_REVERSAL"
        strength_base = 35
    elif ema_trend_down and current_bear < 0 and current_bull < 0:
        direction = "STRONG_BEAR"
        strength_base = 20
    elif ema_trend_down and current_bear < 0 and current_bull >= 0:
        direction = "BEAR_TREND"
        strength_base = 35
    elif ema_trend_down and current_bear >= 0:
        direction = "BEAR_REVERSAL"
        strength_base = 60
    else:
        if current_bull > 0 and current_bear > 0:
            direction = "SIDEWAYS_BULLISH"
            strength_base = 55
        elif current_bull < 0 and current_bear < 0:
            direction = "SIDEWAYS_BEARISH"
            strength_base = 45
        else:
            direction = "SIDEWAYS"
            strength_base = 50

    slope_bonus = min(20, abs(ema_slope) * 50) if ema_trend_up else -min(10, abs(ema_slope) * 30)
    if bullish_divergence and ema_trend_up:
        slope_bonus += 10
    if bearish_divergence and ema_trend_down:
        slope_bonus -= 10
    if both_weakening:
        strength_base = 50

    strength = max(0, min(100, strength_base + slope_bonus))

    long_signal = False
    short_signal = False
    long_reason = ""
    short_reason = ""

    if ema_trend_up:
        if current_bear < 0 and bear_rising and bullish_divergence:
            long_signal = True
            long_reason = "EMA上升+Bear<0+看涨背离+Bear回升"
        elif current_bear < 0 and bear_rising:
            long_reason = "EMA上升+Bear<0+Bear回升（弱信号）"
        elif current_bear > 0:
            long_reason = "EMA上升+Bear>0（空头失控，多头主控）"

    if ema_trend_down:
        if current_bull > 0 and bull_falling and bearish_divergence:
            short_signal = True
            short_reason = "EMA下降+Bull>0+看跌背离+Bull下降"
        elif current_bull > 0 and bull_falling:
            short_reason = "EMA下降+Bull>0+Bull下降（弱信号）"
        elif current_bull < 0:
            short_reason = "EMA下降+Bull<0（多头失控，空头主控）"

    return {
        "bull_power": round(current_bull, 6),
        "bear_power": round(current_bear, 6),
        "ema13": round(current_ema, 6),
        "bull_pct": round(bull_pct, 2),
        "bear_pct": round(bear_pct, 2),
        "ema_slope_pct": round(ema_slope, 4),
        "ema_trend": "up" if ema_trend_up else ("down" if ema_trend_down else "flat"),
        "direction": direction,
        "strength": round(strength, 2),
        "bullish_divergence": bullish_divergence,
        "bearish_divergence": bearish_divergence,
        "bull_rising": bull_rising,
        "bull_falling": bull_falling,
        "bear_rising": bear_rising,
        "bear_falling": bear_falling,
        "bull_out_of_control": bull_out_of_control,
        "bear_out_of_control": bear_out_of_control,
        "both_weakening": both_weakening,
        "long_signal": long_signal,
        "short_signal": short_signal,
        "long_reason": long_reason,
        "short_reason": short_reason,
    }


def get_vol_adjusted_params(
    coin_vol: float, btc_vol: float, base_tp_pct: float = 0.04, base_addon_pct: float = 0.08
) -> Dict:
    if btc_vol <= 0:
        ratio = 1.0
    else:
        ratio = coin_vol / btc_vol

    ratio = max(0.5, min(2.5, ratio))

    tp_pct = base_tp_pct * ratio
    addon_pct = base_addon_pct * ratio

    return {
        "btc_volatility": round(btc_vol * 100, 4),
        "coin_volatility": round(coin_vol * 100, 4),
        "vol_ratio": round(ratio, 4),
        "take_profit_pct": round(tp_pct * 100, 2),
        "addon_pct": round(addon_pct * 100, 2),
        "base_tp_pct": round(base_tp_pct * 100, 2),
        "base_addon_pct": round(base_addon_pct * 100, 2),
    }


def calc_risk_reward_ratio(
    direction: str,
    current_price: float,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
) -> Dict:
    if direction == "LONG":
        risk = (
            entry_price - stop_loss_price if stop_loss_price < entry_price else entry_price * 0.05
        )
        reward = (
            take_profit_price - entry_price
            if take_profit_price > entry_price
            else entry_price * 0.03
        )
    else:
        risk = (
            stop_loss_price - entry_price if stop_loss_price > entry_price else entry_price * 0.05
        )
        reward = (
            entry_price - take_profit_price
            if take_profit_price < entry_price
            else entry_price * 0.03
        )

    if risk <= 0:
        risk = entry_price * 0.01

    rr_ratio = reward / risk if risk > 0 else 0
    risk_pct = risk / entry_price * 100
    reward_pct = reward / entry_price * 100

    return {
        "risk_amount": round(risk, 4),
        "reward_amount": round(reward, 4),
        "risk_pct": round(risk_pct, 2),
        "reward_pct": round(reward_pct, 2),
        "rr_ratio": round(rr_ratio, 2),
        "value_gt_risk": rr_ratio >= 1.5,
    }


def evaluate_addon_opportunity(
    symbol: str,
    direction: str,
    current_price: float,
    entry_price: float,
    is_btc: bool,
    elder_ray: Dict,
    vol_params: Dict,
    unrealized_pnl_pct: float = 0.0,
    current_position_pct: float = 0.0,
    max_position_cap: float = 0.70,
) -> Dict:
    result = {
        "can_add": False,
        "addon_type": None,
        "addon_pct": 0.0,
        "addon_price": 0.0,
        "reason": "",
        "risk_reward": None,
        "value_gt_risk": False,
    }

    if current_position_pct >= max_position_cap:
        result["reason"] = (
            f"当前仓位{current_position_pct*100:.0f}%已达上限{max_position_cap*100:.0f}%"
        )
        return result

    btc_addon_pct = 0.08
    if is_btc:
        base_addon = btc_addon_pct
    else:
        vol_ratio = vol_params.get("vol_ratio", 1.0)
        base_addon = btc_addon_pct * vol_ratio
        base_addon = max(0.04, min(0.20, base_addon))

    if direction == "LONG":
        addon_price = entry_price * (1 - base_addon)
        sl_price = addon_price * (1 - 0.10)
        tp_price = entry_price * (1 + vol_params.get("take_profit_pct", 4) / 100)
    else:
        addon_price = entry_price * (1 + base_addon)
        sl_price = addon_price * (1 + 0.10)
        tp_price = entry_price * (1 - vol_params.get("take_profit_pct", 4) / 100)

    rr = calc_risk_reward_ratio(direction, current_price, addon_price, sl_price, tp_price)
    result["risk_reward"] = rr
    result["value_gt_risk"] = rr["value_gt_risk"]

    if not rr["value_gt_risk"]:
        result["reason"] = f"风险回报比{rr['rr_ratio']:.2f}<1.5，价值低于风险"
        return result

    is_counter_trend = (direction == "LONG" and unrealized_pnl_pct < 0) or (
        direction == "BEAR" and unrealized_pnl_pct < 0
    )
    is_trend_follow = (direction == "LONG" and unrealized_pnl_pct > 0) or (
        direction == "BEAR" and unrealized_pnl_pct > 0
    )

    strength = elder_ray.get("strength", 50)
    bullish_div = elder_ray.get("bullish_divergence", False)
    bearish_div = elder_ray.get("bearish_divergence", False)
    ema_trend = elder_ray.get("ema_trend", "flat")

    if is_counter_trend:
        if is_btc and abs(unrealized_pnl_pct) >= 8.0:
            if (direction == "LONG" and bullish_div) or (direction == "BEAR" and bearish_div):
                result["can_add"] = True
                result["addon_type"] = "divergence_counter_trend"
                result["addon_pct"] = base_addon * 100
                result["addon_price"] = round(addon_price, 4)
                result["reason"] = (
                    f"BTC亏损{abs(unrealized_pnl_pct):.1f}%≥8%+{direction}背离，逆势加仓"
                )
                return result

        if not is_btc and abs(unrealized_pnl_pct) >= base_addon * 100 * 0.8:
            if (direction == "LONG" and bullish_div) or (direction == "BEAR" and bearish_div):
                result["can_add"] = True
                result["addon_type"] = "divergence_counter_trend"
                result["addon_pct"] = base_addon * 100
                result["addon_price"] = round(addon_price, 4)
                result["reason"] = (
                    f"{symbol}亏损{abs(unrealized_pnl_pct):.1f}%+背离，波动率放大逆势加仓"
                )
                return result

        result["reason"] = f"逆势但背离信号不足（亏损{abs(unrealized_pnl_pct):.1f}%）"
        return result

    if is_trend_follow:
        trend_strong = False
        if direction == "LONG" and ema_trend == "up" and strength >= 65:
            trend_strong = True
        elif direction == "BEAR" and ema_trend == "down" and strength <= 35:
            trend_strong = True

        if trend_strong and unrealized_pnl_pct >= vol_params.get("take_profit_pct", 4) * 0.5:
            result["can_add"] = True
            result["addon_type"] = "trend_follow"
            result["addon_pct"] = base_addon * 100 * 0.6
            result["addon_price"] = round(current_price, 4)
            result["reason"] = f"趋势强度{strength:.0f}+浮盈{unrealized_pnl_pct:.1f}%，顺势加仓"
            return result

        result["reason"] = f"顺势但趋势强度不足（strength={strength:.0f}）或浮盈不足"
        return result

    result["reason"] = "无明确加仓信号"
    return result


def calc_position_sizing(
    confidence: float,
    equity: float,
    current_price: float,
    leverage: float = 5.0,
    max_position_pct: float = 0.50,
    is_addon: bool = False,
    addon_type: str = None,
) -> Dict:
    position_tiers = [
        (85, 0.60),
        (75, 0.45),
        (65, 0.30),
        (55, 0.15),
        (45, 0.05),
        (0, 0.02),
    ]

    budget_pct = 0.02
    for threshold, pct in position_tiers:
        if confidence >= threshold:
            budget_pct = pct
            break

    max_notional = equity * max_position_pct
    notional_value = equity * budget_pct
    notional_value = min(notional_value, max_notional)

    margin_required = notional_value / leverage
    quantity = notional_value / current_price if current_price > 0 else 0

    return {
        "budget_pct": round(budget_pct, 4),
        "notional_value": round(notional_value, 2),
        "margin_required": round(margin_required, 2),
        "quantity": round(quantity, 6),
        "leverage": leverage,
        "max_position_pct": max_position_pct,
        "position_of_max": round(notional_value / max_notional * 100, 1) if max_notional > 0 else 0,
    }
