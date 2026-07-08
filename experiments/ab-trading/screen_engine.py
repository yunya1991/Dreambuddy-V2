#!/usr/bin/env python3
"""
三屏马丁交易引擎 — Screen1(7维评分) + Screen2(V9预设) + Screen3(持仓监控)
数据来源：OKX CLI (@okx_ai/okx-trade-cli)
"""
import json, os, subprocess, math
from datetime import datetime, timezone
from pathlib import Path

HOME_BIN = "/opt/homebrew/bin"
os.environ["PATH"] = HOME_BIN + ":" + os.environ.get("PATH", "")

OKX_PROFILE = "screen_trade"

INST_SPOT = "BTC-USDT"
INST_SWAP = "BTC-USDT-SWAP"

CANDIDATE_COINS = [
    # 主流币（BTC作为波动基准）
    {"symbol": "BTC", "spot": "BTC-USDT", "swap": "BTC-USDT-SWAP", "is_btc": True},
    {"symbol": "ETH", "spot": "ETH-USDT", "swap": "ETH-USDT-SWAP", "is_btc": False},
    {"symbol": "SOL", "spot": "SOL-USDT", "swap": "SOL-USDT-SWAP", "is_btc": False},
    {"symbol": "BNB", "spot": "BNB-USDT", "swap": "BNB-USDT-SWAP", "is_btc": False},
    {"symbol": "DOGE", "spot": "DOGE-USDT", "swap": "DOGE-USDT-SWAP", "is_btc": False},
    {"symbol": "XRP", "spot": "XRP-USDT", "swap": "XRP-USDT-SWAP", "is_btc": False},
]

MAX_ADDONS = 3
ADDON_PCT = 0.08
TP_PCT = 0.04
MIN_VOL_MULT = 0.3
MAX_VOL_MULT = 4.0

DIMENSIONS = [
    {"key": "technical",    "name": "技术指标", "weight": 40, "type": "anchor"},
    {"key": "onchain",      "name": "链上数据", "weight": 15, "type": "anchor"},
    {"key": "cycle",        "name": "减半周期", "weight": 10, "type": "booster"},
    {"key": "miner",        "name": "矿工经济", "weight": 10, "type": "booster"},
    {"key": "macro",        "name": "宏观环境", "weight": 10, "type": "background"},
    {"key": "cross_market", "name": "跨市场联动", "weight": 10, "type": "background"},
    {"key": "sentiment",    "name": "情绪指标", "weight": 5,  "type": "reference"},
]


def _run_okx(args):
    try:
        r = subprocess.run(
            ["okx", "--profile", OKX_PROFILE] + args,
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "NO_UPDATE_CHECK": "1"}
        )
        stdout = "\n".join(l for l in r.stdout.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        stderr = "\n".join(l for l in r.stderr.split("\n") if "Update available" not in l and "Run: npm" not in l).strip()
        if r.returncode != 0 and stderr:
            return {"ok": False, "err": stderr[:200]}
        if stdout.startswith("[") or stdout.startswith("{"):
            return {"ok": True, "data": json.loads(stdout)}
        return {"ok": True, "data": stdout}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _fetch_candles(inst_id, bar, limit):
    r = _run_okx(["market", "candles", inst_id, "--bar", bar, "--limit", str(limit), "--json"])
    if not r["ok"]:
        return []
    raw = r["data"]
    candles = []
    for c in raw:
        candles.append({
            "ts": int(c[0]),
            "o": float(c[1]),
            "h": float(c[2]),
            "l": float(c[3]),
            "c": float(c[4]),
            "vol": float(c[5]),
        })
    return list(reversed(candles))


def _calc_ma200(daily_closes):
    if len(daily_closes) < 200:
        return None
    return sum(daily_closes[-200:]) / 200


def _screen1_technical(daily_closes, weekly_closes):
    price = daily_closes[-1]
    ma200_daily = _calc_ma200(daily_closes)
    ma200_weekly = sum(weekly_closes[-200:]) / 200 if len(weekly_closes) >= 200 else None
    rsi = _rsi(daily_closes, 14)

    ema12 = _ema(daily_closes, 12)
    ema26 = _ema(daily_closes, 26)
    macd = ema12 - ema26 if ema12 and ema26 else None
    signal = _ema([daily_closes[i] * 0 + macd for i in range(len(daily_closes))], 9) if macd else None

    direction = "NEUTRAL"
    score = 0
    reasons = []

    if ma200_daily:
        above_daily = price > ma200_daily
        reasons.append(f"日线MA200: ${ma200_daily:.0f}，价格{'高于' if above_daily else '低于'}")
    else:
        reasons.append("日线MA200数据不足")
        above_daily = None

    if ma200_weekly:
        above_weekly = price > ma200_weekly
        reasons.append(f"周线MA200(200W SMA): ${ma200_weekly:.0f}，价格{'高于' if above_weekly else '低于'} — 大级别牛熊分界")
    else:
        reasons.append("周线MA200数据不足")
        above_weekly = None

    if above_daily is not None:
        direction = "BULL" if above_daily else "BEAR"
        base_tech = 25 if above_daily else 5
        score += base_tech

    if above_weekly is not None:
        if above_weekly:
            score += 8
            direction = "BULL"
        else:
            score = max(0, score - 3)
            direction = "BEAR"

    if rsi is not None:
        if rsi > 70:
            reasons.append(f"RSI {rsi:.0f} 超买，顶部风险预警")
            score = max(0, score - 5)
        elif rsi < 30:
            reasons.append(f"RSI {rsi:.0f} 超卖，底部区域")
            if direction == "BEAR":
                score = min(40, score + 3)
        else:
            reasons.append(f"RSI {rsi:.0f} 中性")

    if macd and signal:
        macd_bull = macd > signal
        reasons.append(f"MACD: {'金叉' if macd_bull else '死叉'}")
        if macd_bull:
            score = min(40, score + 4)
        else:
            score = max(0, score - 2)

    score = max(0, min(40, score))

    return {
        "dimension": "technical_detector",
        "weight": 40,
        "anchor": direction,
        "ma200_daily": round(ma200_daily, 2) if ma200_daily else None,
        "ma200_weekly": round(ma200_weekly, 2) if ma200_weekly else None,
        "price_vs_ma200_daily": "ABOVE" if (ma200_daily and price > ma200_daily) else "BELOW" if ma200_daily else None,
        "price_vs_ma200_weekly": "ABOVE" if (ma200_weekly and price > ma200_weekly) else "BELOW" if ma200_weekly else None,
        "indicators": {
            "rsi_daily": round(rsi, 1) if rsi else None,
            "macd": round(macd, 2) if macd else None,
            "signal": round(signal, 2) if signal else None,
        },
        "score": score,
        "reasoning": "；".join(reasons),
    }


def _screen1_onchain(daily_closes):
    price = daily_closes[-1]
    sma50 = _sma(daily_closes, 50)
    sma200 = _calc_ma200(daily_closes)
    score = 0
    reasons = []

    if sma50 and sma200:
        if sma50 > sma200:
            score += 8
            reasons.append("SMA50 > SMA200，金叉，链上偏多")
        else:
            reasons.append("SMA50 < SMA200，死叉，链上空头")

        if price < sma200 * 1.1:
            score += 5
            reasons.append("价格接近MA200，估值偏低")

    recent_drawdown = (price - max(daily_closes[-90:])) / max(daily_closes[-90:])
    if recent_drawdown < -0.2:
        score += 4
        reasons.append(f"距90日高点回撤{abs(recent_drawdown)*100:.0f}%，深度回调")

    score = min(15, score)
    return {
        "dimension": "onchain_valuation",
        "weight": 15,
        "score": score,
        "reasoning": "；".join(reasons) if reasons else "链上数据待接入",
        "indicators": {
            "sma50": round(sma50, 2) if sma50 else None,
            "sma200": round(sma200, 2) if sma200 else None,
            "drawdown_90d": round(recent_drawdown * 100, 2),
        },
    }


def _screen1_cycle():
    now = datetime.now(timezone.utc)
    halving_date = datetime(2024, 4, 20, tzinfo=timezone.utc)
    days_since = (now - halving_date).days
    score = 0
    reasons = []

    if days_since < 365:
        score = 3
        reasons.append(f"减半后{days_since}天，积累期早期")
    elif days_since < 540:
        score = 7
        reasons.append(f"减半后{days_since}天，积累→上涨过渡期")
    elif days_since < 730:
        score = 10
        reasons.append(f"减半后{days_since}天，牛市主升期")
    else:
        score = 2
        reasons.append(f"减半后{days_since}天，周期尾部风险")

    return {
        "dimension": "halving_cycle",
        "weight": 15,
        "score": score,
        "days_since_halving": days_since,
        "reasoning": "；".join(reasons),
    }


def _screen1_miner(daily_closes):
    price = daily_closes[-1]
    atr14 = _atr(daily_closes, 14)
    vol_pct = atr14 / price * 100 if atr14 else 0
    score = 0
    reasons = []

    if vol_pct > 8:
        score = 3
        reasons.append(f"波动率{vol_pct:.1f}%偏高，矿工抛压大")
    elif vol_pct > 5:
        score = 8
        reasons.append(f"波动率{vol_pct:.1f}%中等")
    else:
        score = 13
        reasons.append(f"波动率{vol_pct:.1f}%低，矿工稳定")

    score = min(15, score)
    return {
        "dimension": "miner_economics",
        "weight": 15,
        "score": score,
        "volatility_pct": round(vol_pct, 2),
        "reasoning": "；".join(reasons),
    }


def _atr(closes, period=14):
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = abs(closes[i] - closes[i - 1])
        trs.append(tr)
    return sum(trs[-period:]) / period


def _screen1_macro(daily_closes):
    price = daily_closes[-1]
    mom_30d = (price / daily_closes[-31] - 1) * 100 if len(daily_closes) > 30 else 0
    score = 0
    reasons = []

    if mom_30d > 15:
        score = 8
        reasons.append(f"30日涨幅{mom_30d:.1f}%，宏观偏多")
    elif mom_30d > 5:
        score = 6
        reasons.append(f"30日涨幅{mom_30d:.1f}%，宏观中性偏多")
    elif mom_30d > -5:
        score = 5
        reasons.append(f"30日涨幅{mom_30d:.1f}%，宏观震荡")
    elif mom_30d > -15:
        score = 3
        reasons.append(f"30日跌幅{abs(mom_30d):.1f}%，宏观偏弱")
    else:
        score = 1
        reasons.append(f"30日跌幅{abs(mom_30d):.1f}%，宏观风险大")

    return {
        "dimension": "macro_finance",
        "weight": 10,
        "score": score,
        "mom_30d_pct": round(mom_30d, 2),
        "reasoning": "；".join(reasons),
    }


def _screen1_cross_market(daily_closes):
    price = daily_closes[-1]
    vol_20 = _atr(daily_closes, 20) / price * 100
    score = 0
    reasons = []

    if vol_20 and vol_20 < 3:
        score = 4
        reasons.append(f"20日波动率{vol_20:.1f}%低，跨市场稳定")
    elif vol_20 and vol_20 < 5:
        score = 3
        reasons.append(f"20日波动率{vol_20:.1f}%中等")
    else:
        score = 1
        reasons.append(f"20日波动率{vol_20:.1f}%高，风险偏好下降")

    return {
        "dimension": "cross_market",
        "weight": 5,
        "score": score,
        "vol_20d_pct": round(vol_20, 2),
        "reasoning": "；".join(reasons),
    }


def _screen1_sentiment():
    r = _run_okx(["market", "funding-rate", INST_SWAP, "--json"])
    funding_rate = None
    score = 3
    reasons = []

    if r["ok"] and isinstance(r["data"], list) and len(r["data"]) > 0:
        fr = float(r["data"][0].get("fundingRate", 0))
        funding_rate = fr * 100
        if fr > 0.001:
            score = 1
            reasons.append(f"资金费率{funding_rate:.3f}%偏高，市场过热")
        elif fr > 0.0001:
            score = 3
            reasons.append(f"资金费率{funding_rate:.3f}%中性偏多")
        elif fr > -0.001:
            score = 4
            reasons.append(f"资金费率{funding_rate:.3f}%偏低，空头拥挤")
        else:
            score = 5
            reasons.append(f"资金费率{funding_rate:.3f}%极度悲观，底部信号")

    r2 = _run_okx(["news", "latest", "--coins", "BTC", "--lang", "zh-CN", "--limit", "5", "--json"])
    news_count = 0
    if r2["ok"] and isinstance(r2["data"], list):
        news_count = len(r2["data"])

    return {
        "dimension": "sentiment",
        "weight": 5,
        "score": score,
        "funding_rate_pct": round(funding_rate, 4) if funding_rate is not None else None,
        "news_count": news_count,
        "reasoning": "；".join(reasons) if reasons else "情绪数据待接入",
    }


def compute_screen1(spot_inst: str = INST_SPOT, is_btc: bool = True):
    """
    计算 Screen1 六维评分
    - BTC: 全六维（技术40/链上15/周期15/矿工15/宏观10/跨市场5 = 100）
    - 其他币: 三维（技术65/宏观20/跨市场15 = 100）— 链上/周期/矿工不适用
    """
    daily = _fetch_candles(spot_inst, "1D", 250)
    weekly = _fetch_candles(spot_inst, "1W", 210)

    if not daily:
        return {"error": f"无法获取{spot_inst} K线数据"}

    daily_closes = [c["c"] for c in daily]
    weekly_closes = [c["c"] for c in weekly] if weekly else []
    price = daily_closes[-1]

    dims = {}
    dims["technical"] = _screen1_technical(daily_closes, weekly_closes)
    dims["macro"] = _screen1_macro(daily_closes)
    dims["cross_market"] = _screen1_cross_market(daily_closes)

    if is_btc:
        dims["onchain"] = _screen1_onchain(daily_closes)
        dims["cycle"] = _screen1_cycle()
        dims["miner"] = _screen1_miner(daily_closes)
        dims["technical"]["weight"] = 40
        dims["macro"]["weight"] = 10
        dims["cross_market"]["weight"] = 5
    else:
        dims["technical"]["weight"] = 65
        dims["macro"]["weight"] = 20
        dims["cross_market"]["weight"] = 15
        dims["onchain"] = {"dimension": "onchain_valuation", "weight": 0, "score": 0, "reasoning": "非BTC币种，链上数据不适用", "not_applicable": True}
        dims["cycle"] = {"dimension": "halving_cycle", "weight": 0, "score": 0, "reasoning": "非BTC币种，减半周期不适用", "not_applicable": True}
        dims["miner"] = {"dimension": "miner_economics", "weight": 0, "score": 0, "reasoning": "非BTC币种，矿工经济不适用", "not_applicable": True}

    total_score = sum(d["score"] for d in dims.values() if not d.get("not_applicable"))
    max_score = sum(d["weight"] for d in dims.values() if not d.get("not_applicable"))

    tech_anchor = dims["technical"]["anchor"]
    score_pct = total_score / max_score * 100 if max_score > 0 else 50

    if score_pct >= 70:
        direction = "BULL"
        confidence = "STRONG"
    elif score_pct >= 55:
        direction = "BULL"
        confidence = "MODERATE"
    elif score_pct >= 45:
        direction = "NEUTRAL"
        confidence = "LOW"
    elif score_pct >= 30:
        direction = "BEAR"
        confidence = "MODERATE"
    else:
        direction = "BEAR"
        confidence = "STRONG"

    return {
        "symbol": spot_inst.split("-")[0],
        "spot_inst": spot_inst,
        "price": round(price, 2),
        "direction": direction,
        "confidence": confidence,
        "total_score": round(total_score, 1),
        "max_score": max_score,
        "score_pct": round(score_pct, 1),
        "dimensions": dims,
        "is_btc": is_btc,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def calc_vol_mult(inst_id: str = INST_SPOT, period: int = 14) -> float:
    """
    计算标的相对于 BTC 的波动率倍数（用于参数自适应缩放）
    BTC 永远返回 1.0（V9 基准参数以 BTC 为标准）
    其他币种 = 标的波动率 / BTC波动率
    范围限制在 [MIN_VOL_MULT, MAX_VOL_MULT]
    """
    if not inst_id or inst_id == INST_SPOT or inst_id == INST_SWAP or inst_id.startswith("BTC-"):
        return 1.0

    btc_candles = _fetch_candles(INST_SPOT, "1D", period + 10)
    target_candles = _fetch_candles(inst_id, "1D", period + 10)
    if not btc_candles or not target_candles:
        return 1.0

    btc_closes = [c["c"] for c in btc_candles]
    target_closes = [c["c"] for c in target_candles]
    btc_atr = _atr(btc_closes, period)
    target_atr = _atr(target_closes, period)
    if not btc_atr or not target_atr or btc_closes[-1] == 0 or target_closes[-1] == 0:
        return 1.0

    btc_vol = btc_atr / btc_closes[-1]
    target_vol = target_atr / target_closes[-1]
    vol_mult = target_vol / btc_vol
    return max(MIN_VOL_MULT, min(MAX_VOL_MULT, vol_mult))


def compute_screen2(s1_direction, current_price, inst_id=None, vol_mult=None):
    if vol_mult is None:
        vol_mult = calc_vol_mult(inst_id) if inst_id else 1.0
    addon_pct = ADDON_PCT * vol_mult
    tp_pct = TP_PCT * vol_mult

    direction = s1_direction if s1_direction in ("BULL", "BEAR") else "BULL"
    is_long = direction == "BULL"

    entry_levels = []
    base_price = current_price

    if is_long:
        for n in range(MAX_ADDONS + 1):
            lvl_price = base_price * (1 - addon_pct) ** n
            spacing = f"-{addon_pct*100:.1f}%" if n > 0 else "—"
            status = "未到达" if n > 0 else ("待触发" if current_price > lvl_price else "已触发")
            entry_levels.append({
                "level": f"入场" if n == 0 else f"加仓{n}",
                "price": round(lvl_price, 2),
                "spacing": spacing,
                "status": status,
            })
        tp_price = base_price * (1 + tp_pct)
    else:
        for n in range(MAX_ADDONS + 1):
            lvl_price = base_price * (1 + addon_pct) ** n
            spacing = f"+{addon_pct*100:.1f}%" if n > 0 else "—"
            status = "未到达" if n > 0 else ("待触发" if current_price < lvl_price else "已触发")
            entry_levels.append({
                "level": f"入场" if n == 0 else f"加仓{n}",
                "price": round(lvl_price, 2),
                "spacing": spacing,
                "status": status,
            })
        tp_price = base_price * (1 - tp_pct)

    coin = (inst_id or INST_SPOT).split("-")[0]
    swap_inst = inst_id if inst_id and "SWAP" in inst_id else INST_SWAP

    return {
        "coin": coin,
        "inst_id": swap_inst,
        "vol_mult": round(vol_mult, 3),
        "direction": direction,
        "addon_pct": round(addon_pct * 100, 2),
        "tp_pct": round(tp_pct * 100, 2),
        "max_addons": MAX_ADDONS,
        "entry_levels": entry_levels,
        "tp_price": round(tp_price, 2),
    }


def compute_screen3(s2):
    r = _run_okx(["account", "balance", "--json"])
    equity = 0
    available = 0
    positions = []

    if r["ok"]:
        try:
            data = r["data"]
            if isinstance(data, list) and len(data) > 0:
                details = data[0].get("details", [])
                for d in details:
                    if d.get("ccy") == "USDT":
                        equity = float(d.get("eq", 0))
                        available = float(d.get("availBal", 0))
        except Exception:
            pass

    for coin in CANDIDATE_COINS:
        swap_inst = coin["swap"]
        r2 = _run_okx(["account", "positions", "--instId", swap_inst, "--json"])
        if r2["ok"] and isinstance(r2["data"], list):
            for p in r2["data"]:
                pos = float(p.get("pos", 0))
                if pos != 0:
                    pos_side = p.get("posSide", "net")
                    side = "LONG" if pos_side == "long" else "SHORT" if pos_side == "short" else ("LONG" if pos > 0 else "SHORT")
                    
                    coin_symbol = p.get("instId", "").replace("-USDT-SWAP", "")
                    
                    s1_pos = compute_screen1(coin["spot"], is_btc=coin["is_btc"])
                    vm_pos = calc_vol_mult(coin["spot"])
                    s2_pos = compute_screen2(s1_pos["direction"], s1_pos["price"], inst_id=swap_inst, vol_mult=vm_pos)
                    
                    entry_levels = s2_pos["entry_levels"]
                    entry_prices = [l["price"] for l in entry_levels]
                    martingale_level = sum(1 for ep in entry_prices if (
                        (s2_pos["direction"] == "BULL" and float(p.get("avgPx", 0)) <= ep) or
                        (s2_pos["direction"] == "BEAR" and float(p.get("avgPx", 0)) >= ep)
                    ))
                    
                    next_entry_pct = None
                    next_entry_price = None
                    if martingale_level < len(entry_levels):
                        next_entry_price = entry_levels[martingale_level]["price"]
                        next_entry_pct = round(abs(next_entry_price - float(p.get("avgPx", 0))) / float(p.get("avgPx", 0)) * 100, 2)
                    
                    current_price = s1_pos["price"]
                    pnl_pct = round((current_price - float(p.get("avgPx", 0))) / float(p.get("avgPx", 0)) * 100 * (1 if side == "LONG" else -1), 2)
                    distance_to_tp = round(abs(current_price - s2_pos["tp_price"]) / float(p.get("avgPx", 0)) * 100, 2)
                    
                    positions.append({
                        "coin": coin_symbol,
                        "size": abs(pos),
                        "side": side,
                        "entry_px": float(p.get("avgPx", 0)),
                        "current_price": current_price,
                        "upnl": float(p.get("upl", 0)),
                        "pnl_pct": pnl_pct,
                        "leverage": float(p.get("lever", 1)),
                        "direction": s2_pos["direction"],
                        "vol_mult": vm_pos,
                        "martingale_level": martingale_level,
                        "max_levels": MAX_ADDONS + 1,
                        "next_entry_price": next_entry_price,
                        "next_entry_pct": next_entry_pct,
                        "tp_price": s2_pos["tp_price"],
                        "tp_pct": s2_pos["tp_pct"],
                        "addon_pct": s2_pos["addon_pct"],
                        "distance_to_tp": distance_to_tp,
                        "entry_levels": [{"level": l["level"], "price": l["price"], "spacing": l["spacing"]} for l in entry_levels],
                    })

    return {
        "equity": round(equity, 2),
        "available": round(available, 2),
        "positions": positions,
        "martingale_level": positions[0]["martingale_level"] if positions else 0,
        "max_levels": MAX_ADDONS + 1,
        "tp_price": positions[0]["tp_price"] if positions else s2.get("tp_price", 0),
    }


def scan_candidates():
    """
    扫描所有候选币种，计算 Screen1 和 vol_mult，按评分排序
    返回排序后的列表（最值得交易的排前面）
    """
    results = []
    for coin in CANDIDATE_COINS:
        try:
            s1 = compute_screen1(coin["spot"], is_btc=coin["is_btc"])
            if "error" in s1:
                continue
            vm = calc_vol_mult(coin["spot"])
            s2 = compute_screen2(s1["direction"], s1["price"], inst_id=coin["swap"], vol_mult=vm)
            results.append({
                "symbol": coin["symbol"],
                "spot": coin["spot"],
                "swap": coin["swap"],
                "is_btc": coin["is_btc"],
                "screen1": s1,
                "screen2": s2,
                "vol_mult": round(vm, 3),
                "score_pct": s1["score_pct"],
                "direction": s1["direction"],
                "confidence": s1["confidence"],
            })
        except Exception as e:
            continue

    def sort_key(r):
        score = r["score_pct"]
        if r["direction"] == "BEAR":
            score = 100 - score
        return score

    results.sort(key=sort_key, reverse=True)
    return results


def select_best_candidate(min_score_pct: float = 70.0):
    """
    选择最优交易标的：
    1. 方向明确（非 NEUTRAL）
    2. 置信度达标（score_pct >= min_score_pct 或 <= 100-min_score_pct）
    3. 按确认度排序，选最高的
    """
    candidates = scan_candidates()
    if not candidates:
        return None, candidates

    qualified = []
    for c in candidates:
        sp = c["score_pct"]
        if c["direction"] == "BULL" and sp >= min_score_pct:
            qualified.append((sp, c))
        elif c["direction"] == "BEAR" and sp <= (100 - min_score_pct):
            qualified.append((100 - sp, c))

    if not qualified:
        return None, candidates

    qualified.sort(key=lambda x: x[0], reverse=True)
    return qualified[0][1], candidates


def get_all(symbol: str = None):
    candidates = scan_candidates()
    best, _ = select_best_candidate(min_score_pct=70.0)

    if symbol:
        target = next((c for c in candidates if c["symbol"] == symbol), None)
    else:
        target = next((c for c in candidates if c["symbol"] == "BTC"), None)

    if target:
        s1 = target["screen1"]
        s2 = target["screen2"]
    else:
        s1 = compute_screen1(INST_SPOT, is_btc=True)
        if "error" in s1:
            return {"error": s1["error"]}
        s2 = compute_screen2(s1["direction"], s1["price"], inst_id=INST_SWAP, vol_mult=1.0)

    s3 = compute_screen3(s2)

    try:
        from report_loader import get_all_reports
        reports = get_all_reports()
    except Exception as e:
        reports = {"error": str(e)}

    return {
        "screen1": s1,
        "screen2": s2,
        "screen3": s3,
        "reports": reports,
        "candidates": candidates,
        "best_candidate": best["symbol"] if best else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    result = get_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
