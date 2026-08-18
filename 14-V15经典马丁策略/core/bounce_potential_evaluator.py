#!/usr/bin/env python3
"""
反弹潜力评估器
从"反弹空间"角度评估币种，适合马丁做多策略

评估维度：
1. 斐波那契回撤 - 当前价离关键支撑位的距离
2. 布林带下轨距离 - 当前价离布林带下轨的距离（超卖程度）
3. 线性回归偏离 - 当前价偏离回归线的程度
4. ATR距离 - 当前价离近期低点的ATR倍数
5. 乖离率 - 当前价与MA的偏离程度
6. RSI超卖 - RSI低于超卖线的程度
7. 成交量恐慌 - 下跌时成交量是否异常放大
"""
import json
import time
from pathlib import Path
from typing import Dict, List

from v15_backtest import fetch_klines

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "data" / "bounce_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SEC = 3600


def _calc_returns(klines: List[Dict]) -> List[float]:
    closes = [float(k["c"]) for k in klines]
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    return returns


def _calc_ma(klines: List[Dict], period: int) -> float:
    closes = [float(k["c"]) for k in klines]
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


def _calc_atr(klines: List[Dict], period: int = 14) -> float:
    trs = []
    for i in range(1, len(klines)):
        high = float(klines[i]["h"])
        low = float(klines[i]["l"])
        prev_close = float(klines[i - 1]["c"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    atr = sum(trs[-period:]) / period
    return atr


def _calc_std(klines: List[Dict], period: int = 20) -> float:
    closes = [float(k["c"]) for k in klines]
    if len(closes) < period:
        return 0
    window = closes[-period:]
    avg = sum(window) / len(window)
    variance = sum((c - avg) ** 2 for c in window) / len(window)
    return variance**0.5


def _calc_rsi(klines: List[Dict], period: int = 14) -> float:
    closes = [float(k["c"]) for k in klines]
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period):]
    gains = [max(d, 0) for d in recent]
    losses = [max(-d, 0) for d in recent]
    avg_g = sum(gains) / period
    avg_l = sum(losses) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - 100 / (1 + rs)


def _calc_fib_levels(high: float, low: float) -> Dict[str, float]:
    levels = {
        "0.0": high,
        "0.236": high - (high - low) * 0.236,
        "0.382": high - (high - low) * 0.382,
        "0.5": high - (high - low) * 0.5,
        "0.618": high - (high - low) * 0.618,
        "0.786": high - (high - low) * 0.786,
        "1.0": low,
    }
    return levels


def _calc_linear_regression(klines: List[Dict], period: int = 30) -> float:
    closes = [float(k["c"]) for k in klines]
    if len(closes) < period:
        return 0.0
    window = closes[-period:]
    n = len(window)
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(window)
    sum_xy = sum(x[i] * window[i] for i in range(n))
    sum_x2 = sum(xi**2 for xi in x)

    denom = n * sum_x2 - sum_x**2
    if denom == 0:
        return 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    predicted = slope * (n - 1) + intercept
    current = window[-1]

    return (current - predicted) / predicted


def _calc_volume_anomaly(klines: List[Dict], period: int = 20, lookback: int = 5) -> float:
    vols = [float(k["v"]) for k in klines]
    if len(vols) < period + lookback:
        return 1.0

    recent = vols[-lookback:]
    avg_recent = sum(recent) / len(recent)

    past = vols[-(period + lookback) : -lookback]
    avg_past = sum(past) / len(past)

    if avg_past == 0:
        return 1.0

    return avg_recent / avg_past


def evaluate_bounce_potential(
    coin: str,
    klines_4h: List[Dict],
    method: str = "fib",
    lookback: int = 60,
) -> Dict:
    """
    评估反弹潜力（单指标模式，用于回测对比）

    method:
        - 'fib': 斐波那契回撤 - 当前价离0.618支撑位的距离
        - 'bb': 布林带下轨距离 - 当前价与下轨的偏离程度
        - 'reg': 线性回归偏离 - 当前价低于回归线的程度
        - 'atr': ATR距离 - 当前价离近期低点的ATR倍数
        - 'bias': 乖离率 - 当前价与MA的偏离程度
        - 'rsi': RSI超卖 - RSI低于超卖线的程度
        - 'volume': 成交量恐慌 - 下跌放量程度
        - 'combo': 综合评分（加权，保留用于对比）
    """
    closes = [float(k["c"]) for k in klines_4h]
    highs = [float(k["h"]) for k in klines_4h]
    lows = [float(k["l"]) for k in klines_4h]

    if len(closes) < max(lookback, 30):
        return {"coin": coin, "method": method, "score": 0.0, "valid": False}

    window = lookback
    recent_closes = closes[-window:]
    recent_highs = highs[-window:]
    recent_lows = lows[-window:]

    current = closes[-1]
    recent_high = max(recent_highs)
    recent_low = min(recent_lows)

    score = 0.0
    details = {}

    if method == "fib":
        fib = _calc_fib_levels(recent_high, recent_low)
        dist_to_618 = abs(current - fib["0.618"]) / (recent_high - recent_low)
        score = dist_to_618 if current < fib["0.618"] else 0
        details = {"fib_0.618": round(fib["0.618"], 2), "dist_ratio": round(dist_to_618, 4)}

    elif method == "bb":
        ma = _calc_ma(klines_4h, 20)
        std = _calc_std(klines_4h, 20)
        bb_lower = ma - 2 * std
        if bb_lower == 0:
            score = 0
        else:
            score = (bb_lower - current) / bb_lower if current < bb_lower else 0
        details = {
            "ma_20": round(ma, 2),
            "bb_lower": round(bb_lower, 2),
            "deviation": round(score, 4),
        }

    elif method == "reg":
        reg_dev = _calc_linear_regression(klines_4h, 30)
        score = -reg_dev if reg_dev < 0 else 0
        details = {"regression_deviation": round(reg_dev, 4)}

    elif method == "atr":
        atr = _calc_atr(klines_4h, 14)
        dist_from_low = recent_low - current if current < recent_low else 0
        score = dist_from_low / atr if atr > 0 else 0
        details = {
            "atr": round(atr, 2),
            "dist_from_low": round(dist_from_low, 2),
            "atr_multiplier": round(score, 2),
        }

    elif method == "bias":
        ma50 = _calc_ma(klines_4h, 50)
        if ma50 == 0:
            score = 0
        else:
            bias = (current - ma50) / ma50
            score = -bias if bias < 0 else 0
        details = {"ma50": round(ma50, 2), "bias_pct": round(bias * 100, 2)}

    elif method == "rsi":
        rsi = _calc_rsi(klines_4h, 14)
        score = (30 - rsi) / 30 if rsi < 30 else 0
        details = {"rsi": round(rsi, 2)}

    elif method == "volume":
        vol_ratio = _calc_volume_anomaly(klines_4h, 20, 5)
        score = vol_ratio if vol_ratio > 1.5 else 0
        details = {"volume_ratio": round(vol_ratio, 2)}

    elif method == "combo":
        # 4指标加权组合：乖离率(0.3) + 斐波那契(0.25) + RSI超卖(0.25) + 成交量恐慌(0.2)
        sub_scores = {}

        # 1. 乖离率：当前价低于MA50越多，反弹空间越大
        ma50 = _calc_ma(klines_4h, 50)
        if ma50 > 0:
            bias = (current - ma50) / ma50
            sub_scores["bias"] = max(-bias, 0)  # 负乖离越大，分数越高
        else:
            sub_scores["bias"] = 0

        # 2. 斐波那契回撤：当前价低于0.618支撑位越远，反弹空间越大
        fib = _calc_fib_levels(recent_high, recent_low)
        price_range = recent_high - recent_low
        if price_range > 0 and current < fib["0.618"]:
            sub_scores["fib"] = (fib["0.618"] - current) / price_range
        else:
            sub_scores["fib"] = 0

        # 3. RSI超卖：RSI越低，超卖程度越大
        rsi = _calc_rsi(klines_4h, 14)
        sub_scores["rsi"] = max((30 - rsi) / 30, 0) if rsi < 30 else 0

        # 4. 成交量恐慌：下跌放量程度
        vol_ratio = _calc_volume_anomaly(klines_4h, 20, 5)
        sub_scores["volume"] = vol_ratio / 3.0 if vol_ratio > 1.5 else 0  # 归一化：3倍量为满分

        # 加权求和（经滚动窗口验证的最优权重）
        weights = {"bias": 0.20, "fib": 0.20, "rsi": 0.20, "volume": 0.40}
        score = sum(sub_scores[k] * weights[k] for k in weights)

        # 多少个子指标触发（辅助判断信号强度）
        n_triggered = sum(1 for v in sub_scores.values() if v > 0)

        details = {
            "bias_score": round(sub_scores["bias"], 4),
            "fib_score": round(sub_scores["fib"], 4),
            "rsi_score": round(sub_scores["rsi"], 4),
            "vol_score": round(sub_scores["volume"], 4),
            "n_triggered": n_triggered,
            "rsi_raw": round(rsi, 1),
        }

    return {
        "coin": coin,
        "method": method,
        "score": round(score, 4),
        "current_price": round(current, 2),
        "recent_high": round(recent_high, 2),
        "recent_low": round(recent_low, 2),
        "price_from_low_pct": round((current - recent_low) / recent_low * 100, 2),
        **details,
        "valid": True,
    }


def rank_by_bounce_potential(
    coins: List[str],
    method: str = "fib",
    top_n: int = 3,
    lookback: int = 60,
    min_score: float = 0.0,
    use_cache: bool = True,
) -> Dict:
    cache_key = f"{method}_{lookback}_{min_score}"
    cache_file = CACHE_DIR / f"bounce_{cache_key}.json"
    now = time.time()

    if use_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            if now - cached.get("cached_at", 0) < CACHE_TTL_SEC:
                ranking = cached.get("ranking", [])
                selected = [r["coin"] for r in ranking if r["score"] >= min_score][:top_n]
                return {"ranking": ranking, "selected": selected, "from_cache": True}
        except Exception:
            pass

    ranking = []
    for coin in coins:
        klines = fetch_klines(coin, "4h", lookback + 100)
        if len(klines) < lookback:
            continue
        result = evaluate_bounce_potential(coin, klines, method, lookback)
        if result["valid"]:
            ranking.append(result)

    ranking.sort(key=lambda x: x["score"], reverse=True)
    selected = [r["coin"] for r in ranking if r["score"] >= min_score][:top_n]

    result_data = {
        "cached_at": now,
        "method": method,
        "lookback": lookback,
        "min_score": min_score,
        "ranking": ranking,
        "selected": selected,
        "from_cache": False,
    }
    cache_file.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))

    return result_data


def print_bounce_report(result: Dict):
    method_names = {
        "fib": "斐波那契回撤",
        "bb": "布林带下轨距离",
        "reg": "线性回归偏离",
        "atr": "ATR距离",
        "bias": "乖离率",
        "rsi": "RSI超卖",
        "volume": "成交量恐慌",
        "combo": "综合评分",
    }
    print("\n" + "=" * 80)
    print(f"  反弹潜力排名 ({method_names.get(result.get('method'), result.get('method'))})")
    print("=" * 80)
    print(f"  {'#':>3}  {'币种':>6}  {'评分':>7}  {'当前价':>8}  {'从低点%':>10}  {'状态':>6}")
    print("-" * 80)
    for i, r in enumerate(result["ranking"]):
        status = "✓选" if r["coin"] in result["selected"] else ""
        print(
            f"  {i+1:>3}  {r['coin']:>6}  {r['score']:>+7.4f}  {r['current_price']:>8.2f}  {r['price_from_low_pct']:>+9.2f}%  {status:>6}"
        )
    print("=" * 80)
    print(f"  入选: {', '.join(result.get('selected', []))}")
    print("=" * 80)


# ═══════════════════════════════════════════════════════
# 异常信号监控模式
# ═══════════════════════════════════════════════════════

# 各指标的异常阈值（基线配置）
# 剔除乖离率信号（bias），保留作为参考但不参与触发判断
SIGNAL_THRESHOLDS = {
    "bias": -999.0,  # 乖离率已剔除，不参与触发
    "fib": 0.0,  # 当前价低于0.618支撑位触发
    "rsi": 25,  # RSI < 25 触发
    "volume": 1.8,  # 成交量比率 > 1.8 触发
}

# 参与触发判断的有效信号
ACTIVE_SIGNALS = ["fib", "rsi", "volume"]


def evaluate_signals(coin: str, klines_4h: List[Dict], lookback: int = 60) -> Dict:
    """
    异常信号监控：4个指标独立判断，任一触发即标记为潜在高价值

    返回每个指标的原始值和是否触发，不做加权
    """
    closes = [float(k["c"]) for k in klines_4h]
    highs = [float(k["h"]) for k in klines_4h]
    lows = [float(k["l"]) for k in klines_4h]

    if len(closes) < max(lookback, 50):
        return {"coin": coin, "valid": False, "signals": {}, "n_triggered": 0}

    recent_closes = closes[-lookback:]
    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]
    current = closes[-1]
    recent_high = max(recent_highs)
    recent_low = min(recent_lows)

    # 1. 乖离率
    ma50 = _calc_ma(klines_4h, 50)
    bias = (current - ma50) / ma50 if ma50 > 0 else 0

    # 2. 斐波那契0.618
    fib = _calc_fib_levels(recent_high, recent_low)
    price_range = recent_high - recent_low
    fib_below_618 = (
        (fib["0.618"] - current) / price_range if price_range > 0 and current < fib["0.618"] else 0
    )

    # 3. RSI
    rsi = _calc_rsi(klines_4h, 14)

    # 4. 成交量比率
    vol_ratio = _calc_volume_anomaly(klines_4h, 20, 5)

    # 判断是否触发
    signals = {
        "bias": {
            "value": round(bias * 100, 2),
            "threshold": SIGNAL_THRESHOLDS["bias"] * 100,
            "triggered": bias < SIGNAL_THRESHOLDS["bias"],
            "desc": f"乖离率 {bias*100:.1f}% (阈值 {SIGNAL_THRESHOLDS['bias']*100:.0f}%)",
        },
        "fib": {
            "value": round(fib_below_618, 4),
            "threshold": SIGNAL_THRESHOLDS["fib"],
            "triggered": fib_below_618 > SIGNAL_THRESHOLDS["fib"],
            "desc": f"低于0.618 {fib_below_618*100:.1f}% (阈值 >0%)",
        },
        "rsi": {
            "value": round(rsi, 1),
            "threshold": SIGNAL_THRESHOLDS["rsi"],
            "triggered": rsi < SIGNAL_THRESHOLDS["rsi"],
            "desc": f"RSI {rsi:.1f} (阈值 <{SIGNAL_THRESHOLDS['rsi']})",
        },
        "volume": {
            "value": round(vol_ratio, 2),
            "threshold": SIGNAL_THRESHOLDS["volume"],
            "triggered": vol_ratio > SIGNAL_THRESHOLDS["volume"],
            "desc": f"量比 {vol_ratio:.2f} (阈值 >{SIGNAL_THRESHOLDS['volume']})",
        },
    }

    n_triggered = sum(1 for k in ACTIVE_SIGNALS if signals[k]["triggered"])
    triggered_list = [k for k in ACTIVE_SIGNALS if signals[k]["triggered"]]

    return {
        "coin": coin,
        "valid": True,
        "current_price": round(current, 2),
        "recent_high": round(recent_high, 2),
        "recent_low": round(recent_low, 2),
        "price_from_low_pct": round((current - recent_low) / recent_low * 100, 2),
        "signals": signals,
        "n_triggered": n_triggered,
        "triggered_list": triggered_list,
        "has_signal": n_triggered > 0,
    }


def monitor_bounce_signals(coins: List[str], lookback: int = 60, min_signals: int = 1) -> Dict:
    """
    批量监控币种异常信号
    min_signals: 至少触发几个信号才算潜在高价值（1=任一触发）
    """
    results = []
    for coin in coins:
        klines = fetch_klines(coin, "4h", lookback + 100)
        if len(klines) < lookback:
            continue
        r = evaluate_signals(coin, klines, lookback)
        if r["valid"]:
            results.append(r)

    # 按触发信号数排序
    results.sort(key=lambda x: x["n_triggered"], reverse=True)

    highlighted = [r for r in results if r["n_triggered"] >= min_signals]

    return {
        "total_coins": len(results),
        "highlighted_count": len(highlighted),
        "min_signals": min_signals,
        "all_results": results,
        "highlighted": highlighted,
    }


def print_signal_monitor(result: Dict):
    print("\n" + "=" * 100)
    print("  反弹潜力异常信号监控")
    print(
        f"  阈值: 乖离率<{SIGNAL_THRESHOLDS['bias']*100:.0f}% | 斐波那契低于0.618 | RSI<{SIGNAL_THRESHOLDS['rsi']} | 量比>{SIGNAL_THRESHOLDS['volume']}"
    )
    print("=" * 100)
    print(
        f"  {'币种':>6}  {'乖离率':>8}  {'fib偏离':>8}  {'RSI':>6}  {'量比':>6}  {'触发数':>6}  {'触发信号':>20}"
    )
    print("-" * 100)

    for r in result["all_results"]:
        s = r["signals"]
        bias_str = f"{s['bias']['value']:+.1f}%" + ("⚠️" if s["bias"]["triggered"] else "")
        fib_str = f"{s['fib']['value']*100:+.1f}%" + ("⚠️" if s["fib"]["triggered"] else "")
        rsi_str = f"{s['rsi']['value']:.1f}" + ("⚠️" if s["rsi"]["triggered"] else "")
        vol_str = f"{s['volume']['value']:.2f}" + ("⚠️" if s["volume"]["triggered"] else "")
        n = r["n_triggered"]
        triggers = ", ".join(r["triggered_list"]) if r["triggered_list"] else ""

        marker = " >>>" if r["has_signal"] else ""
        print(
            f"  {r['coin']:>6}  {bias_str:>10}  {fib_str:>10}  {rsi_str:>8}  {vol_str:>8}  {n:>6}  {triggers:>20}{marker}"
        )

    print("-" * 100)
    highlighted_coins = [r["coin"] for r in result["highlighted"]]
    print(
        f"  潜在高价值 ({result['min_signals']}+信号): {', '.join(highlighted_coins) if highlighted_coins else '无'}"
    )
    print("=" * 100)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="反弹潜力评估器")
    parser.add_argument(
        "--coins",
        default="BTC,ETH,SOL,BNB,XRP,ADA,DOGE,LTC,LINK,AVAX,DOT,UNI,NEAR,APT,ARB,OP,INJ,SUI,SEI,TIA,AAVE,COMP,CRV,DYDX,LDO,PEPE,SAND,SHIB,STX,SUSHI,WLD,ZEC,OKB,HYPE",
    )
    parser.add_argument(
        "--method",
        default="fib",
        choices=["fib", "bb", "reg", "atr", "bias", "rsi", "volume", "combo"],
    )
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--lookback", type=int, default=60)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--monitor", action="store_true", help="异常信号监控模式")
    parser.add_argument("--min-signals", type=int, default=1, help="至少触发几个信号")
    args = parser.parse_args()

    coins = [c.strip() for c in args.coins.split(",") if c.strip()]

    if args.monitor:
        result = monitor_bounce_signals(coins, args.lookback, args.min_signals)
        print_signal_monitor(result)
    else:
        result = rank_by_bounce_potential(
            coins,
            method=args.method,
            top_n=args.top,
            lookback=args.lookback,
            min_score=args.min_score,
            use_cache=not args.no_cache,
        )
        print_bounce_report(result)
