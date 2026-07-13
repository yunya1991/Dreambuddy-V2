#!/usr/bin/env python3
"""
三屏马丁交易引擎 — Screen1(7维评分) + Screen2(V9预设) + Screen3(持仓监控)
数据来源：OKX API (优先) / OKX CLI (回退)
置信度计算：基于回测筛选的经典指标（周线组 + 日线组）
"""
import json, os, subprocess, math, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# 导入经典指标库
sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统")
from talib import abstract as ta

HOME_BIN = "/opt/homebrew/bin"
os.environ["PATH"] = HOME_BIN + ":" + os.environ.get("PATH", "")

OKX_PROFILE = "screen_trade"

INST_SPOT = "BTC-USDT"
INST_SWAP = "BTC-USDT-SWAP"

CANDIDATE_COINS = [
    # 主流币
    {"symbol": "BTC", "spot": "BTC-USDT", "swap": "BTC-USDT-SWAP", "is_btc": True},
    {"symbol": "ETH", "spot": "ETH-USDT", "swap": "ETH-USDT-SWAP", "is_btc": False},
    {"symbol": "SOL", "spot": "SOL-USDT", "swap": "SOL-USDT-SWAP", "is_btc": False},
    {"symbol": "BNB", "spot": "BNB-USDT", "swap": "BNB-USDT-SWAP", "is_btc": False},
    {"symbol": "XRP", "spot": "XRP-USDT", "swap": "XRP-USDT-SWAP", "is_btc": False},
    # 高市值山寨
    {"symbol": "DOGE", "spot": "DOGE-USDT", "swap": "DOGE-USDT-SWAP", "is_btc": False},
    {"symbol": "ADA", "spot": "ADA-USDT", "swap": "ADA-USDT-SWAP", "is_btc": False},
    {"symbol": "AVAX", "spot": "AVAX-USDT", "swap": "AVAX-USDT-SWAP", "is_btc": False},
    {"symbol": "LINK", "spot": "LINK-USDT", "swap": "LINK-USDT-SWAP", "is_btc": False},
    {"symbol": "DOT", "spot": "DOT-USDT", "swap": "DOT-USDT-SWAP", "is_btc": False},
    {"symbol": "TRX", "spot": "TRX-USDT", "swap": "TRX-USDT-SWAP", "is_btc": False},
    {"symbol": "POL", "spot": "POL-USDT", "swap": "POL-USDT-SWAP", "is_btc": False},
    # DeFi 赛道
    {"symbol": "UNI", "spot": "UNI-USDT", "swap": "UNI-USDT-SWAP", "is_btc": False},
    {"symbol": "AAVE", "spot": "AAVE-USDT", "swap": "AAVE-USDT-SWAP", "is_btc": False},
    {"symbol": "LDO", "spot": "LDO-USDT", "swap": "LDO-USDT-SWAP", "is_btc": False},
    # L2 / 新兴公链
    {"symbol": "ARB", "spot": "ARB-USDT", "swap": "ARB-USDT-SWAP", "is_btc": False},
    {"symbol": "OP", "spot": "OP-USDT", "swap": "OP-USDT-SWAP", "is_btc": False},
    {"symbol": "APT", "spot": "APT-USDT", "swap": "APT-USDT-SWAP", "is_btc": False},
    {"symbol": "SUI", "spot": "SUI-USDT", "swap": "SUI-USDT-SWAP", "is_btc": False},
    {"symbol": "SEI", "spot": "SEI-USDT", "swap": "SEI-USDT-SWAP", "is_btc": False},
    # Meme / 热门
    {"symbol": "PEPE", "spot": "PEPE-USDT", "swap": "PEPE-USDT-SWAP", "is_btc": False},
    {"symbol": "WIF", "spot": "WIF-USDT", "swap": "WIF-USDT-SWAP", "is_btc": False},
    # 平台币 / 其他
    {"symbol": "OKB", "spot": "OKB-USDT", "swap": "OKB-USDT-SWAP", "is_btc": False},
    {"symbol": "HYPE", "spot": "HYPE-USDT", "swap": "HYPE-USDT-SWAP", "is_btc": False},
]

MAX_ADDONS = 1
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


def _get_okx_client():
    """获取 OKX API 客户端（优先使用 okx_simulated，支持代理）"""
    root_path = Path(__file__).resolve().parent.parent.parent
    yijing_path = root_path / "11-易经推理系统" / "scripts" / "memory_l4"
    sys.path.insert(0, str(yijing_path))
    try:
        from okx_simulated import OKXSimulatedClient
        client = OKXSimulatedClient()
        return client
    except Exception:
        return None


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
    client = _get_okx_client()
    if client:
        try:
            r = client.get_kline(inst_id, bar=bar, limit=limit)
            if r.get("ok"):
                candles = []
                for c in r.get("candles", []):
                    candles.append({
                        "ts": int(c["ts"]),
                        "o": float(c["o"]),
                        "h": float(c["h"]),
                        "l": float(c["l"]),
                        "c": float(c["c"]),
                        "vol": float(c.get("vol", 0)),
                    })
                return list(reversed(candles))
        except Exception:
            pass
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


def _calc_trend_direction(closes, short=20, medium=50, long=200):
    """基于EMA排列判断趋势方向"""
    ema_s = _ema(closes, short)
    ema_m = _ema(closes, medium)
    ema_l = _ema(closes, long)
    if not all([ema_s, ema_m, ema_l]):
        return "UNKNOWN", {}
    if ema_s > ema_m > ema_l:
        return "BULL", {"ema20": ema_s, "ema50": ema_m, "ema200": ema_l}
    if ema_s < ema_m < ema_l:
        return "BEAR", {"ema20": ema_s, "ema50": ema_m, "ema200": ema_l}
    return "MIXED", {"ema20": ema_s, "ema50": ema_m, "ema200": ema_l}


def _calc_momentum_speed(closes):
    """计算动量速度：7日/14日/30日收益率"""
    speed = {}
    for p in [7, 14, 30]:
        if len(closes) > p:
            speed[f"{p}d"] = round((closes[-1] / closes[-p - 1] - 1) * 100, 2)
        else:
            speed[f"{p}d"] = None
    return speed


def _calc_momentum_acceleration(closes):
    """计算动量加速度：速度的变化率"""
    if len(closes) < 15:
        return None
    cur = (closes[-1] / closes[-8] - 1) * 100 if len(closes) >= 8 else 0
    prev = (closes[-8] / closes[-15] - 1) * 100 if len(closes) >= 15 else 0
    return round(cur - prev, 2)


def _calc_trend_metrics(daily_closes, weekly_closes):
    """综合计算日线和周线趋势指标：方向、速度、加速度"""
    daily_dir, daily_emas = _calc_trend_direction(daily_closes)
    weekly_dir, weekly_emas = _calc_trend_direction(weekly_closes)
    return {
        "daily": {
            "direction": daily_dir,
            "emas": {k: round(v, 2) for k, v in daily_emas.items()} if daily_emas else {},
            "speed": _calc_momentum_speed(daily_closes),
            "acceleration": _calc_momentum_acceleration(daily_closes),
        },
        "weekly": {
            "direction": weekly_dir,
            "emas": {k: round(v, 2) for k, v in weekly_emas.items()} if weekly_emas else {},
            "speed": _calc_momentum_speed(weekly_closes),
            "acceleration": _calc_momentum_acceleration(weekly_closes),
        },
    }


def _assess_trend_consistency(trend_metrics):
    """评估周线和日线的趋势一致性——入场前置条件"""
    w_dir = trend_metrics["weekly"]["direction"]
    d_dir = trend_metrics["daily"]["direction"]
    consistent = (w_dir == d_dir and w_dir in ("BULL", "BEAR"))
    return {
        "consistent": consistent,
        "weekly_direction": w_dir,
        "daily_direction": d_dir,
        "reason": f"周线{w_dir} vs 日线{d_dir}" if w_dir != "UNKNOWN" and d_dir != "UNKNOWN" else "数据不足",
    }


def _detect_exhaustion(trend_metrics, screen1_direction):
    """检测衰竭信号：趋势方向仍偏多/偏空，但速度/加速度衰减
    有衰竭信号时 → 降低置信度，允许轻仓入场
    """
    daily = trend_metrics["daily"]
    signals = []
    adj = 0
    d_dir = daily["direction"]
    speed = daily["speed"]
    accel = daily["acceleration"]

    # 多头衰竭
    if d_dir in ("BULL", "MIXED") and screen1_direction == "BULL":
        if accel is not None and accel < -3:
            signals.append("多头加速度转负，动能衰减")
            adj -= 12
        if speed.get("7d") is not None and speed.get("14d") is not None:
            if speed["7d"] < 0 and speed["14d"] > 0:
                signals.append("短期动量转负，中期仍正，顶部迹象")
                adj -= 15
            elif speed["7d"] < speed["14d"] * 0.3 and speed["14d"] > 0:
                signals.append("短期动量远弱于中期，多头衰竭")
                adj -= 10
    # 空头衰竭
    elif d_dir in ("BEAR", "MIXED") and screen1_direction == "BEAR":
        if accel is not None and accel > 3:
            signals.append("空头加速度转正，下跌动能衰减")
            adj -= 12
        if speed.get("7d") is not None and speed.get("14d") is not None:
            if speed["7d"] > 0 and speed["14d"] < 0:
                signals.append("短期动量转正，中期仍负，底部迹象")
                adj -= 15
            elif speed["7d"] > speed["14d"] * 0.3 and speed["14d"] < 0:
                signals.append("短期下跌放缓，空头衰竭")
                adj -= 10

    return {
        "has_exhaustion": len(signals) > 0,
        "signals": signals,
        "confidence_adjustment": adj,
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


# ============================================================================
# 三屏交易动态算法驱动体系
# 核心架构:
#   1. 趋势一致性计算: 静态指标 + 三维动态指标融合判定方向
#   2. 置信度计算: 动态权重排名 + 贝叶斯参数优化
#   3. 技术面+基本面撮合: 第二重趋势一致性 + 置信度调整
#
# 数据来源: OKX BTC-USDT-SWAP 真实数据回测
# 基线: 日线 SMA200
# 筛选标准: 夏普/回撤/胜率中至少2项优于基线
#
# Screen1 周线组 TOP5（周线夏普排序）:
#   RSI_50(2.965) > SuperTrend(2.569) > StochRSI_Cross(2.472) > OBV_Trend(2.426) > Keltner_Channel(2.318)
# Screen2 日线组 TOP5（日线夏普排序）:
#   GoldenCross_50_200(1.183) > MACD_Cross(0.991) > Vortex(0.845) > TEMA(0.622) > EMA_Align_20_50_200(0.353)
#
# 权重: 周线 60% / 日线 40%
# ============================================================================

SCREEN1_INDICATORS = [
    "RSI_50", "SuperTrend", "StochRSI_Cross", "OBV_Trend", "Keltner_Channel"
]

SCREEN2_INDICATORS = [
    "GoldenCross_50_200", "MACD_Cross", "Vortex", "TEMA", "EMA_Align_20_50_200"
]

# 权重
WEEKLY_WEIGHT = 0.6
DAILY_WEIGHT = 0.4


def _calc_indicator_dynamics(df, indicator_name: str) -> dict:
    """
    计算指标的三个动态维度：
    - direction: 当前方向 (BULL/BEAR)
    - speed: 方向变化的快慢 (动量强度 0-100)
    - acceleration: 速度变化的快慢 (加速/减速 0-100)
    """
    try:
        close = df["close"]
        result = {"direction": "NEUTRAL", "speed": 0.0, "acceleration": 0.0}

        if indicator_name == "MACD_Cross":
            macd_dict = ta.MACD(df, fastperiod=12, slowperiod=26, signalperiod=9)
            macd_line = macd_dict["macd"]
            signal_line = macd_dict["macdsignal"]
            hist = macd_dict["macdhist"]
            # 方向
            result["direction"] = "BULL" if macd_line.iloc[-1] > signal_line.iloc[-1] else "BEAR"
            # 速度：MACD 距零轴的距离（归一化）
            price_mean = close.mean()
            result["speed"] = min(100, abs(macd_line.iloc[-1] - signal_line.iloc[-1]) / price_mean * 1000)
            # 加速度：柱状图斜率（最近2期变化）
            if len(hist) >= 3:
                slope = (hist.iloc[-1] - hist.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope) / price_mean * 1000)

        elif indicator_name == "OBV_Trend":
            obv = ta.OBV(df)
            obv_ma = obv.rolling(10, min_periods=1).mean()
            result["direction"] = "BULL" if obv.iloc[-1] > obv_ma.iloc[-1] else "BEAR"
            # 速度：OBV 距均线的距离
            obv_range = obv.max() - obv.min() + 1
            result["speed"] = min(100, abs(obv.iloc[-1] - obv_ma.iloc[-1]) / obv_range * 100)
            # 加速度：OBV 变化率
            if len(obv) >= 3:
                slope = (obv.iloc[-1] - obv.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope) / obv_range * 100)

        elif indicator_name == "BBands_Mid":
            bb = ta.BBANDS(df, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
            mid = bb["middleband"]
            upper = bb["upperband"]
            lower = bb["lowerband"]
            result["direction"] = "BULL" if close.iloc[-1] > mid.iloc[-1] else "BEAR"
            # 速度：价格在中轨的相对位置（0=中轨，100=上下轨）
            band_width = upper.iloc[-1] - lower.iloc[-1] + 1e-9
            position = (close.iloc[-1] - mid.iloc[-1]) / (band_width / 2)
            result["speed"] = min(100, abs(position) * 50)
            # 加速度：中轨斜率
            if len(mid) >= 3:
                slope = (mid.iloc[-1] - mid.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope) / close.mean() * 10000)

        elif indicator_name == "Ichimoku_Cloud":
            ichi = ta.ICHIMOKU(df, tenkan=9, kijun=26, senkou_b=52)
            cloud_top = ichi["cloud_top"]
            cloud_bottom = ichi["cloud_bottom"]
            if close.iloc[-1] > cloud_top.iloc[-1]:
                result["direction"] = "BULL"
                dist = (close.iloc[-1] - cloud_top.iloc[-1]) / cloud_top.iloc[-1] * 100
            elif close.iloc[-1] < cloud_bottom.iloc[-1]:
                result["direction"] = "BEAR"
                dist = (cloud_bottom.iloc[-1] - close.iloc[-1]) / close.iloc[-1] * 100
            else:
                result["direction"] = "NEUTRAL"
                dist = 0
            # 速度：距云层距离
            result["speed"] = min(100, abs(dist) * 10)
            # 加速度：云层厚度变化
            if len(cloud_top) >= 3:
                thickness_change = (cloud_top.iloc[-1] - cloud_bottom.iloc[-1]) - (cloud_top.iloc[-3] - cloud_bottom.iloc[-3])
                result["acceleration"] = min(100, abs(thickness_change) / close.mean() * 1000)

        elif indicator_name == "Vortex":
            vx = ta.VORTEX(df, period=14)
            vi_plus = vx["plus_vi"]
            vi_minus = vx["minus_vi"]
            result["direction"] = "BULL" if vi_plus.iloc[-1] > vi_minus.iloc[-1] else "BEAR"
            # 速度：+VI -VI 差值
            result["speed"] = min(100, abs(vi_plus.iloc[-1] - vi_minus.iloc[-1]))
            # 加速度：差值的变化
            if len(vi_plus) >= 3:
                diff_now = vi_plus.iloc[-1] - vi_minus.iloc[-1]
                diff_prev = vi_plus.iloc[-3] - vi_minus.iloc[-3]
                result["acceleration"] = min(100, abs(diff_now - diff_prev))

        elif indicator_name == "RSI_50":
            rsi = ta.RSI(df, timeperiod=14)
            result["direction"] = "BULL" if rsi.iloc[-1] > 50 else "BEAR"
            # 速度：RSI 距50的偏差
            result["speed"] = min(100, abs(rsi.iloc[-1] - 50))
            # 加速度：RSI 变化率
            if len(rsi) >= 3:
                result["acceleration"] = min(100, abs(rsi.iloc[-1] - rsi.iloc[-3]))

        elif indicator_name == "Donchian_Channel":
            dc = ta.DONCHIAN(df, period=20)
            upper = dc["upper"]
            lower = dc["lower"]
            if close.iloc[-1] > upper.iloc[-1]:
                result["direction"] = "BULL"
            elif close.iloc[-1] < lower.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            # 速度：突破强度
            mid = (upper.iloc[-1] + lower.iloc[-1]) / 2
            if result["direction"] == "BULL":
                dist = (close.iloc[-1] - upper.iloc[-1]) / upper.iloc[-1] * 100
            elif result["direction"] == "BEAR":
                dist = (lower.iloc[-1] - close.iloc[-1]) / lower.iloc[-1] * 100
            else:
                dist = 0
            result["speed"] = min(100, abs(dist) * 10)
            # 加速度：通道宽度变化
            if len(upper) >= 3:
                width_now = upper.iloc[-1] - lower.iloc[-1]
                width_prev = upper.iloc[-3] - lower.iloc[-3]
                result["acceleration"] = min(100, abs(width_now - width_prev) / close.mean() * 1000)

        elif indicator_name == "SuperTrend":
            st = ta.SUPERTREND(df, period=10, multiplier=3.0)
            direction = st["direction"]
            if direction.iloc[-1] == 1:
                result["direction"] = "BULL"
            elif direction.iloc[-1] == -1:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            # 速度：价格偏离SuperTrend的程度
            st_value = st["lowerband"] if direction.iloc[-1] == 1 else st["upperband"]
            dist_pct = abs(close.iloc[-1] - st_value.iloc[-1]) / st_value.iloc[-1] * 100
            result["speed"] = min(100, dist_pct * 5)
            # 加速度：方向变化率
            if len(direction) >= 3:
                dir_changes = abs(direction.iloc[-1] - direction.iloc[-3])
                result["acceleration"] = min(100, dir_changes * 50)

        elif indicator_name == "StochRSI_Cross":
            sr = ta.STOCHRSI(df, timeperiod=14, fastk_period=3, fastd_period=3)
            fastk = sr["fastk"]
            fastd = sr["fastd"]
            result["direction"] = "BULL" if fastk.iloc[-1] > fastd.iloc[-1] else "BEAR"
            # 速度：RSI内的位置（0-100归一化）
            result["speed"] = min(100, abs(fastk.iloc[-1] - 50) * 2)
            # 加速度：交叉变化率
            if len(fastk) >= 3:
                cross_now = fastk.iloc[-1] - fastd.iloc[-1]
                cross_prev = fastk.iloc[-3] - fastd.iloc[-3]
                result["acceleration"] = min(100, abs(cross_now - cross_prev) * 5)

        elif indicator_name == "Keltner_Channel":
            kc = ta.KELTNER(df, ema_period=20, atr_period=10, mult=2.0)
            upper = kc["upper"]
            middle = kc["middle"]
            lower = kc["lower"]
            if close.iloc[-1] > upper.iloc[-1]:
                result["direction"] = "BULL"
            elif close.iloc[-1] < lower.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            # 速度：价格相对中轨的位置
            band_width = upper.iloc[-1] - lower.iloc[-1] + 1e-9
            position = (close.iloc[-1] - middle.iloc[-1]) / (band_width / 2)
            result["speed"] = min(100, abs(position) * 50)
            # 加速度：ATR带宽变化率
            if len(middle) >= 3:
                width_now = upper.iloc[-1] - lower.iloc[-1]
                width_prev = upper.iloc[-3] - lower.iloc[-3]
                result["acceleration"] = min(100, abs(width_now - width_prev) / close.mean() * 1000)

        elif indicator_name == "GoldenCross_50_200":
            ema50 = ta.EMA(df, timeperiod=50)
            ema200 = ta.EMA(df, timeperiod=200)
            result["direction"] = "BULL" if ema50.iloc[-1] > ema200.iloc[-1] else "BEAR"
            # 速度：金叉/死叉后的距离
            dist_pct = abs(ema50.iloc[-1] - ema200.iloc[-1]) / ema200.iloc[-1] * 100
            result["speed"] = min(100, dist_pct * 10)
            # 加速度：均线斜率变化
            if len(ema50) >= 3:
                slope50 = (ema50.iloc[-1] - ema50.iloc[-3]) / 2
                slope200 = (ema200.iloc[-1] - ema200.iloc[-3]) / 2
                result["acceleration"] = min(100, abs(slope50 - slope200) / close.mean() * 10000)

        elif indicator_name == "TEMA":
            tema = ta.TEMA(df, timeperiod=30)
            tema_trend = tema.pct_change().dropna()
            if len(tema_trend) >= 1:
                result["direction"] = "BULL" if tema_trend.iloc[-1] > 0 else "BEAR"
            # 速度：TEMA变化率
            price_mean = close.mean()
            result["speed"] = min(100, abs(tema.iloc[-1] - close.iloc[-1]) / price_mean * 1000)
            # 加速度：TEMA二阶导数
            if len(tema) >= 4:
                accel = (tema.iloc[-1] - 2 * tema.iloc[-2] + tema.iloc[-3]) / price_mean * 10000
                result["acceleration"] = min(100, abs(accel))

        elif indicator_name == "EMA_Align_20_50_200":
            ema20 = ta.EMA(df, timeperiod=20)
            ema50 = ta.EMA(df, timeperiod=50)
            ema200 = ta.EMA(df, timeperiod=200)
            if ema20.iloc[-1] > ema50.iloc[-1] > ema200.iloc[-1]:
                result["direction"] = "BULL"
            elif ema20.iloc[-1] < ema50.iloc[-1] < ema200.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            # 速度：均线排列的整齐程度（标准差归一化）
            ma_values = [ema20.iloc[-1], ema50.iloc[-1], ema200.iloc[-1]]
            ma_std = np.std(ma_values)
            ma_mean = np.mean(ma_values)
            alignment_score = 1 - (ma_std / ma_mean) if ma_mean > 0 else 0
            result["speed"] = min(100, alignment_score * 100)
            # 加速度：排列变化率
            if len(ema20) >= 3:
                prev_ma_values = [ema20.iloc[-3], ema50.iloc[-3], ema200.iloc[-3]]
                prev_alignment = 1 - (np.std(prev_ma_values) / np.mean(prev_ma_values)) if np.mean(prev_ma_values) > 0 else 0
                result["acceleration"] = min(100, abs(alignment_score - prev_alignment) * 100)

        elif indicator_name == "Elder_ray":
            er = ta.ELDER_RAY(df, period=13)
            bull_power = er["bull_power"]
            bear_power = er["bear_power"]
            # 方向：Bull Power > 0 且 > Bear Power 表示多头
            if bull_power.iloc[-1] > 0 and bull_power.iloc[-1] > abs(bear_power.iloc[-1]):
                result["direction"] = "BULL"
            elif bear_power.iloc[-1] < 0 and abs(bear_power.iloc[-1]) > bull_power.iloc[-1]:
                result["direction"] = "BEAR"
            else:
                result["direction"] = "NEUTRAL"
            # 速度：力量强度（绝对值归一化）
            power_range = max(bull_power.max() - bull_power.min(), bear_power.max() - bear_power.min(), 1e-9)
            power_abs = max(abs(bull_power.iloc[-1]), abs(bear_power.iloc[-1]))
            result["speed"] = min(100, power_abs / power_range * 100)
            # 加速度：力量变化率（衰竭/增强）
            if len(bull_power) >= 3:
                bull_change = bull_power.iloc[-1] - bull_power.iloc[-3]
                bear_change = bear_power.iloc[-1] - bear_power.iloc[-3]
                result["acceleration"] = min(100, abs(bull_change - bear_change) / power_range * 100)

        return result

    except Exception as e:
        return {"direction": "NEUTRAL", "speed": 0.0, "acceleration": 0.0}


def _calc_indicator_signal(df, indicator_name: str) -> str:
    """便捷函数：只返回方向信号"""
    return _calc_indicator_dynamics(df, indicator_name)["direction"]


def _calc_classic_indicator_confidence(weekly_df, daily_df) -> dict:
    """
    计算经典指标综合置信度
    算法：
      - 单一指标命中可信度: 50%
      - 多个指标共振: 50% + N×10% (N=同向指标数)
      - 速度/加速度加成：每个同向指标的速度+加速度/100 × 5 上限加分
      - Screen1(周线)置信度 = 50 + bull_count_weekly × 10 + speed_accel_bonus
      - Screen2(日线)置信度 = 50 + bull_count_daily × 10 + speed_accel_bonus
      - 综合置信度 = Screen1×0.6 + Screen2×0.4
    """
    def _calc_group(indicators, df):
        bull_count = 0
        bear_count = 0
        neutral_count = 0
        signals = {}
        dynamics_list = []
        for ind in indicators:
            dyn = _calc_indicator_dynamics(df, ind)
            signals[ind] = dyn
            if dyn["direction"] == "BULL":
                bull_count += 1
            elif dyn["direction"] == "BEAR":
                bear_count += 1
            else:
                neutral_count += 1
            dynamics_list.append(dyn)

        total = len(indicators)
        # 主导方向
        if bull_count > bear_count:
            direction = "BULL"
            count = bull_count
        elif bear_count > bull_count:
            direction = "BEAR"
            count = bear_count
        else:
            direction = "NEUTRAL"
            count = max(bull_count, bear_count)

        # 基础置信度: 50% + N×10% (单一指标50%，共振递增)
        base_conf = 50 + count * 10

        # 速度/加速度加成: 同向指标的速度和加速度均值 × 5
        same_dir = [d for d in dynamics_list if d["direction"] == direction]
        if same_dir:
            avg_speed = sum(d["speed"] for d in same_dir) / len(same_dir)
            avg_accel = sum(d["acceleration"] for d in same_dir) / len(same_dir)
            dynamics_bonus = min(5, (avg_speed + avg_accel) / 100 * 5)
        else:
            dynamics_bonus = 0

        confidence = min(100, base_conf + dynamics_bonus)

        return {
            "bull_count": bull_count,
            "bear_count": bear_count,
            "neutral_count": neutral_count,
            "direction": direction,
            "confidence": round(confidence, 1),
            "signals": signals,
            "dynamics_bonus": round(dynamics_bonus, 2),
        }

    s1 = _calc_group(SCREEN1_INDICATORS, weekly_df)
    s2 = _calc_group(SCREEN2_INDICATORS, daily_df)

    # 综合判断
    trend_consistent = s1["direction"] == s2["direction"] and s1["direction"] != "NEUTRAL"

    if trend_consistent:
        overall_direction = s1["direction"]
        overall_confidence = round(s1["confidence"] * WEEKLY_WEIGHT + s2["confidence"] * DAILY_WEIGHT, 1)
    else:
        overall_direction = "NEUTRAL"
        overall_confidence = round(min(s1["confidence"], s2["confidence"]) * 0.5, 1)

    return {
        "screen1_weekly": s1,
        "screen2_daily": s2,
        "overall_direction": overall_direction,
        "overall_confidence": overall_confidence,
        "trend_consistent": trend_consistent,
        "weights": {"weekly": WEEKLY_WEIGHT, "daily": DAILY_WEIGHT},
    }


# ============================================================================
# 第一部分: 趋势一致性计算（静态指标 + 三维动态融合）
#   - 每周轮询周线静态信号 + 三维动态信号（方向、速度、加速度）
#   - 每日轮询日线静态信号 + 三维动态信号
#   - 静态信号显示熊市，但三维动态显示趋势逆转 → 最终方向可能不一致
# ============================================================================

def _calc_trend_direction_static(df, indicators: list) -> str:
    """计算静态指标的方向（投票法）"""
    bull_count = sum(1 for ind in indicators if _calc_indicator_signal(df, ind) == "BULL")
    bear_count = sum(1 for ind in indicators if _calc_indicator_signal(df, ind) == "BEAR")
    if bull_count > bear_count:
        return "BULL"
    elif bear_count > bull_count:
        return "BEAR"
    return "NEUTRAL"


def _calc_trend_direction_dynamic(df, indicators: list) -> dict:
    """
    计算三维动态指标的趋势方向
    返回: {
        "direction": "BULL"/"BEAR"/"REVERSAL_BULL"/"REVERSAL_BEAR"/"NEUTRAL",
        "confidence": 0-100,
        "signals": [{indicator, direction, speed, acceleration}],
        "reversal_score": 0-100 (逆转信号强度)
    }
    """
    signals = []
    reversal_signals = []
    bull_count = 0
    bear_count = 0
    
    for ind in indicators:
        dyn = _calc_indicator_dynamics(df, ind)
        signals.append({
            "indicator": ind,
            "direction": dyn["direction"],
            "speed": dyn["speed"],
            "acceleration": dyn["acceleration"],
        })
        if dyn["direction"] == "BULL":
            bull_count += 1
        elif dyn["direction"] == "BEAR":
            bear_count += 1
        
        # 检测逆转信号：速度下降但加速度反向
        if dyn["direction"] == "BULL":
            if dyn["speed"] < 30 and dyn["acceleration"] > 20:
                reversal_signals.append({"indicator": ind, "type": "potential_reversal_bear"})
        else:
            if dyn["speed"] < 30 and dyn["acceleration"] > 20:
                reversal_signals.append({"indicator": ind, "type": "potential_reversal_bull"})
    
    # 计算逆转分数
    reversal_score = min(100, len(reversal_signals) / len(indicators) * 100)
    
    # 综合方向判定
    if bull_count > bear_count:
        base_direction = "BULL"
        count = bull_count
    elif bear_count > bull_count:
        base_direction = "BEAR"
        count = bear_count
    else:
        base_direction = "NEUTRAL"
        count = max(bull_count, bear_count)
    
    # 如果有明显逆转信号，调整方向
    if reversal_score > 50:
        if base_direction == "BULL":
            final_direction = "REVERSAL_BEAR"
        elif base_direction == "BEAR":
            final_direction = "REVERSAL_BULL"
        else:
            final_direction = base_direction
    else:
        final_direction = base_direction
    
    # 计算动态置信度
    avg_speed = sum(s["speed"] for s in signals) / len(signals) if signals else 0
    avg_accel = sum(s["acceleration"] for s in signals) / len(signals) if signals else 0
    confidence = min(100, 50 + count * 10 + (avg_speed + avg_accel) / 200 * 20)
    
    return {
        "direction": final_direction,
        "confidence": round(confidence, 1),
        "signals": signals,
        "reversal_score": round(reversal_score, 1),
        "reversal_signals": reversal_signals,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "avg_speed": round(avg_speed, 1),
        "avg_acceleration": round(avg_accel, 1),
    }


def _calc_trend_consistency_with_dynamics(weekly_df, daily_df) -> dict:
    """
    趋势一致性计算（静态+三维动态融合）
    返回: {
        "weekly": {"static_direction", "dynamic_direction", "final_direction", "confidence", ...},
        "daily": {"static_direction", "dynamic_direction", "final_direction", "confidence", ...},
        "consistent": bool,
        "overall_direction": "BULL"/"BEAR"/"NEUTRAL",
        "consistency_confidence": 0-100,
    }
    """
    # 周线静态方向
    weekly_static = _calc_trend_direction_static(weekly_df, SCREEN1_INDICATORS)
    
    # 周线动态方向（含逆转检测）
    weekly_dynamic = _calc_trend_direction_dynamic(weekly_df, SCREEN1_INDICATORS)
    
    # 周线最终方向：动态优先，静态确认
    if weekly_dynamic["reversal_score"] > 60:
        weekly_final = weekly_dynamic["direction"]
    elif weekly_dynamic["direction"] == "NEUTRAL":
        weekly_final = weekly_static
    else:
        weekly_final = weekly_dynamic["direction"]
    
    # 日线同理
    daily_static = _calc_trend_direction_static(daily_df, SCREEN2_INDICATORS)
    daily_dynamic = _calc_trend_direction_dynamic(daily_df, SCREEN2_INDICATORS)
    
    if daily_dynamic["reversal_score"] > 60:
        daily_final = daily_dynamic["direction"]
    elif daily_dynamic["direction"] == "NEUTRAL":
        daily_final = daily_static
    else:
        daily_final = daily_dynamic["direction"]
    
    # 提取核心方向（去除REVERSAL前缀）
    def _core_dir(d):
        if d.startswith("REVERSAL_"):
            return "BULL" if d == "REVERSAL_BULL" else "BEAR"
        return d
    
    weekly_core = _core_dir(weekly_final)
    daily_core = _core_dir(daily_final)
    
    # 判断一致性
    consistent = weekly_core == daily_core and weekly_core != "NEUTRAL"
    
    # 计算一致性置信度
    if consistent:
        consistency_confidence = round(
            weekly_dynamic["confidence"] * WEEKLY_WEIGHT + 
            daily_dynamic["confidence"] * DAILY_WEIGHT, 1
        )
    else:
        consistency_confidence = round(
            min(weekly_dynamic["confidence"], daily_dynamic["confidence"]) * 0.5, 1
        )
    
    return {
        "weekly": {
            "static_direction": weekly_static,
            "dynamic_direction": weekly_dynamic["direction"],
            "final_direction": weekly_final,
            "core_direction": weekly_core,
            "confidence": weekly_dynamic["confidence"],
            "reversal_score": weekly_dynamic["reversal_score"],
            "bull_count": weekly_dynamic["bull_count"],
            "bear_count": weekly_dynamic["bear_count"],
            "avg_speed": weekly_dynamic["avg_speed"],
            "avg_acceleration": weekly_dynamic["avg_acceleration"],
            "signals": weekly_dynamic["signals"],
        },
        "daily": {
            "static_direction": daily_static,
            "dynamic_direction": daily_dynamic["direction"],
            "final_direction": daily_final,
            "core_direction": daily_core,
            "confidence": daily_dynamic["confidence"],
            "reversal_score": daily_dynamic["reversal_score"],
            "bull_count": daily_dynamic["bull_count"],
            "bear_count": daily_dynamic["bear_count"],
            "avg_speed": daily_dynamic["avg_speed"],
            "avg_acceleration": daily_dynamic["avg_acceleration"],
            "signals": daily_dynamic["signals"],
        },
        "consistent": consistent,
        "overall_direction": weekly_core if consistent else "NEUTRAL",
        "consistency_confidence": consistency_confidence,
    }


# ============================================================================
# 第二部分: 动态权重排名和置信度计算（贝叶斯参数）
#   - 每周交易开启后进行指标回测和权重排名
#   - 三维动态计算作为置信度排名依据
#   - 基于基线回测，通过贝叶斯参数寻找最优组合
# ============================================================================

def _calc_indicator_performance(df, indicator_name: str, baseline_return: float = 0.0) -> dict:
    """
    计算单个指标的历史表现（用于权重排名）
    返回: {"sharpe", "win_rate", "total_return", "weight_score"}
    """
    try:
        signals = []
        close = df["close"].values
        for i in range(1, len(close)):
            df_slice = df.iloc[:i+1]
            dyn = _calc_indicator_dynamics(df_slice, indicator_name)
            if dyn["direction"] == "BULL":
                signals.append(1)
            elif dyn["direction"] == "BEAR":
                signals.append(-1)
            else:
                signals.append(0)
        
        if not signals or sum(abs(s) for s in signals) == 0:
            return {"sharpe": 0.0, "win_rate": 0.5, "total_return": 0.0, "weight_score": 0.0}
        
        returns = []
        for i, sig in enumerate(signals[:-1]):
            if sig != 0:
                ret = (close[i+1] - close[i]) / close[i] * sig
                returns.append(ret)
        
        if not returns:
            return {"sharpe": 0.0, "win_rate": 0.5, "total_return": 0.0, "weight_score": 0.0}
        
        total_return = sum(returns)
        win_rate = sum(1 for r in returns if r > 0) / len(returns)
        sharpe = total_return / (np.std(returns) + 1e-9) if len(returns) > 1 else 0.0
        
        # 权重分数 = 夏普排名分 + 胜率排名分 + 动态因子分
        # 高于基线加分，低于基线扣分
        excess_return = total_return - baseline_return
        weight_score = sharpe + (win_rate - 0.5) * 10 + excess_return * 100
        
        return {
            "sharpe": round(sharpe, 3),
            "win_rate": round(win_rate, 3),
            "total_return": round(total_return, 3),
            "weight_score": round(weight_score, 3),
            "excess_return": round(excess_return, 3),
        }
    except Exception:
        return {"sharpe": 0.0, "win_rate": 0.5, "total_return": 0.0, "weight_score": 0.0}


def _calc_dynamic_weights(df, indicators: list) -> dict:
    """
    计算指标的动态权重（基于历史表现排名）
    返回: {indicator_name: {"weight": 0-1, "performance": {...}}}
    """
    # 先计算基线收益（SMA200策略）
    sma200 = df["close"].rolling(200, min_periods=1).mean()
    baseline_signals = np.where(df["close"] > sma200, 1, -1)
    baseline_returns = []
    for i in range(1, len(df)):
        baseline_returns.append((df["close"].iloc[i] - df["close"].iloc[i-1]) / df["close"].iloc[i-1] * baseline_signals[i-1])
    baseline_return = sum(baseline_returns) / len(baseline_returns) if baseline_returns else 0.0
    
    # 计算每个指标的表现
    performances = {}
    for ind in indicators:
        performances[ind] = _calc_indicator_performance(df, ind, baseline_return)
    
    # 按权重分数排序
    sorted_indicators = sorted(performances.keys(), key=lambda x: performances[x]["weight_score"], reverse=True)
    
    # 计算动态权重（排名越高权重越大）
    total_score = sum(performances[ind]["weight_score"] for ind in sorted_indicators if performances[ind]["weight_score"] > 0)
    if total_score <= 0:
        equal_weight = 1.0 / len(indicators)
        weights = {ind: equal_weight for ind in indicators}
    else:
        weights = {}
        for ind in indicators:
            perf = performances[ind]
            if perf["weight_score"] > 0:
                weights[ind] = perf["weight_score"] / total_score
            else:
                weights[ind] = 0.0
        # 归一化
        weight_sum = sum(weights.values())
        if weight_sum > 0:
            weights = {ind: w / weight_sum for ind, w in weights.items()}
        else:
            equal_weight = 1.0 / len(indicators)
            weights = {ind: equal_weight for ind in indicators}
    
    return {
        "weights": weights,
        "performances": performances,
        "sorted_indicators": sorted_indicators,
        "baseline_return": round(baseline_return, 4),
    }


def _calc_bayesian_confidence(weekly_df, daily_df) -> dict:
    """
    贝叶斯置信度计算（动态权重 + 三维动态融合）
    算法:
      P(趋势正确|指标信号) ∝ P(指标信号|趋势正确) × P(趋势正确)
      - P(趋势正确) = 先验概率（基于历史胜率）
      - P(指标信号|趋势正确) = 似然概率（基于动态权重）
      - 后验概率 = 归一化置信度
    """
    # 计算周线动态权重
    weekly_weights = _calc_dynamic_weights(weekly_df, SCREEN1_INDICATORS)
    # 计算日线动态权重
    daily_weights = _calc_dynamic_weights(daily_df, SCREEN2_INDICATORS)
    
    # 计算周线信号
    weekly_bull_prob = 0.0
    weekly_bear_prob = 0.0
    weekly_total_weight = 0.0
    
    for ind in SCREEN1_INDICATORS:
        weight = weekly_weights["weights"].get(ind, 0.0)
        dyn = _calc_indicator_dynamics(weekly_df, ind)
        weekly_total_weight += weight
        
        # 似然概率：指标方向正确的概率 = 权重 × 动态因子
        if dyn["direction"] == "BULL":
            weekly_bull_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)
        elif dyn["direction"] == "BEAR":
            weekly_bear_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)
    
    # 归一化
    if weekly_total_weight > 0:
        weekly_bull_prob /= weekly_total_weight
        weekly_bear_prob /= weekly_total_weight
    
    # 日线同理
    daily_bull_prob = 0.0
    daily_bear_prob = 0.0
    daily_total_weight = 0.0
    
    for ind in SCREEN2_INDICATORS:
        weight = daily_weights["weights"].get(ind, 0.0)
        dyn = _calc_indicator_dynamics(daily_df, ind)
        daily_total_weight += weight
        
        if dyn["direction"] == "BULL":
            daily_bull_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)
        elif dyn["direction"] == "BEAR":
            daily_bear_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)
    
    if daily_total_weight > 0:
        daily_bull_prob /= daily_total_weight
        daily_bear_prob /= daily_total_weight
    
    # 综合贝叶斯概率
    bull_prob = weekly_bull_prob * WEEKLY_WEIGHT + daily_bull_prob * DAILY_WEIGHT
    bear_prob = weekly_bear_prob * WEEKLY_WEIGHT + daily_bear_prob * DAILY_WEIGHT
    
    # 方向判定和置信度
    if bull_prob > bear_prob:
        direction = "BULL"
        confidence = round(bull_prob * 100, 1)
    elif bear_prob > bull_prob:
        direction = "BEAR"
        confidence = round(bear_prob * 100, 1)
    else:
        direction = "NEUTRAL"
        confidence = round(min(bull_prob, bear_prob) * 50, 1)
    
    return {
        "direction": direction,
        "confidence": confidence,
        "bull_probability": round(bull_prob, 4),
        "bear_probability": round(bear_prob, 4),
        "weekly_weights": weekly_weights,
        "daily_weights": daily_weights,
    }


# ============================================================================
# 第三部分: 技术面 + 基本面撮合
#   - 技术面: 三屏趋势一致性 + 贝叶斯置信度
#   - 基本面: 第一屏研报 + A1研报
#   - 第二重趋势一致性 + 置信度调整
#   - 矛盾存在时: 趋势方向保持一致，置信度在幅度内调整
# ============================================================================

def _fetch_fundamental_data(symbol: str = "BTC") -> dict:
    """
    获取基本面数据（研报 + A1日报）
    返回: {"direction", "confidence", "reports": [...]}
    """
    import requests
    
    reports = []
    direction = "NEUTRAL"
    confidence = 0
    
    try:
        resp = requests.get(f"http://localhost:8092/fundamental/overview/latest", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            sentiment = data.get("sentiment", "NEUTRAL").upper()
            conf = data.get("confidence", 0)
            if sentiment in ("BULL", "BEAR", "NEUTRAL"):
                direction = sentiment
                confidence = conf
                reports.append({"type": "基本面API", "title": "", "direction": direction, "confidence": confidence})
    except Exception:
        pass
    
    if not reports:
        reports.append({"type": "无研报", "title": "", "direction": "NEUTRAL", "confidence": 0})
    
    return {
        "direction": direction,
        "confidence": confidence,
        "reports": reports,
        "bull_count": sum(1 for r in reports if r["direction"] == "BULL"),
        "bear_count": sum(1 for r in reports if r["direction"] == "BEAR"),
        "total_reports": len(reports),
    }


def _resample_candles(candles: list, target_tf: str) -> list:
    """
    跨周期数据对齐：将低时间周期K线聚合成高时间周期K线
    参考 Backtrader 的 resampling 机制
    
    聚合规则:
    - Open: 周期内第一根K线的开盘价
    - High: 周期内最高价
    - Low: 周期内最低价
    - Close: 周期内最后一根K线的收盘价
    - Volume: 周期内成交量之和
    
    支持的聚合:
    - 5m -> 1h: 12根5mK线聚合为1根1hK线
    - 1h -> 4h: 4根1hK线聚合为1根4hK线
    - 1h -> 1D: 24根1hK线聚合为1根日线K线
    - 4h -> 1D: 6根4hK线聚合为1根日线K线
    
    返回: 聚合后的K线列表
    """
    if not candles:
        return []
    
    tf_mapping = {
        ("5m", "1h"): 12,
        ("1h", "4h"): 4,
        ("1h", "1D"): 24,
        ("4h", "1D"): 6,
        ("15m", "1h"): 4,
        ("15m", "4h"): 16,
        ("30m", "1h"): 2,
        ("30m", "4h"): 8,
        ("30m", "1D"): 48,
    }
    
    source_tf = _infer_timeframe(candles)
    key = (source_tf, target_tf)
    
    if key not in tf_mapping:
        return candles
    
    num_bars = tf_mapping[key]
    resampled = []
    
    for i in range(0, len(candles), num_bars):
        chunk = candles[i:i+num_bars]
        if len(chunk) < num_bars:
            continue
        
        resampled.append({
            "o": chunk[0]["o"],
            "h": max(c["h"] for c in chunk),
            "l": min(c["l"] for c in chunk),
            "c": chunk[-1]["c"],
            "vol": sum(c["vol"] for c in chunk),
            "t": chunk[0]["t"],
        })
    
    return resampled


def _infer_timeframe(candles: list) -> str:
    """
    根据K线时间戳推断时间周期
    """
    if len(candles) < 2:
        return "1h"
    
    t0 = candles[0].get("t", 0)
    t1 = candles[1].get("t", 0)
    interval = t1 - t0
    
    if interval <= 300:
        return "5m"
    elif interval <= 900:
        return "15m"
    elif interval <= 1800:
        return "30m"
    elif interval <= 3600:
        return "1h"
    elif interval <= 14400:
        return "4h"
    else:
        return "1D"


def _fetch_freqtrade_signals(symbol: str, timeframes: list = None) -> dict:
    """
    获取 Freqtrade 策略信号（1h/4h）
    基于回测筛选的优质策略，采用多策略投票机制

    4h 波段策略（按回测评分排序）:
    1. MultiGroupStrategy: 评分=100, 信号率=100%
    2. TrendConfirmationStrategy: 评分=94, 信号率=80%

    1h/5m 短线策略:
    1. RegimeHybridStrategy: 评分=41, 信号率=20%
    2. Bot2StrategyTrend: 评分=35, 备用

    返回: {
        "1h": {"signal": "BUY"/"SELL"/"HOLD", "confidence": 0-100, "strategy": "xxx"},
        "4h": {"signal": "BUY"/"SELL"/"HOLD", "confidence": 0-100, "strategy": "xxx"},
    }
    """
    if timeframes is None:
        timeframes = ["1h", "4h"]

    result = {}
    for tf in timeframes:
        result[tf] = {"signal": "HOLD", "confidence": 0, "strategy": "Freqtrade"}

    coin = symbol.split("-")[0] if "-" in symbol else symbol

    # 策略配置
    STRATEGIES_4H = [
        ("user_data.strategies.MultiGroupStrategy", "MultiGroupStrategy", 0.55),
        ("user_data.strategies.TrendConfirmationStrategy", "TrendConfirmationStrategy", 0.45),
    ]
    STRATEGIES_1H = [
        ("user_data.strategies.RegimeHybridStrategy", "RegimeHybridStrategy", 0.6),
        ("user_data.strategies.Bot2StrategyTrend", "Bot2StrategyTrend", 0.4),
    ]

    try:
        import sys
        ml_path = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统"
        if ml_path not in sys.path:
            sys.path.insert(0, ml_path)

        import ml_trade_service

        # 4h 策略投票
        if "4h" in timeframes:
            votes = {"BUY": 0, "SELL": 0, "HOLD": 0}
            for mod, cls, weight in STRATEGIES_4H:
                try:
                    res = ml_trade_service._run_freqtrade_strategy_signal_hyperliquid(mod, cls, coin)
                    if res.get("ok") and res.get("side"):
                        side = res.get("side")
                        sig = "BUY" if side == "long" else ("SELL" if side == "short" else "HOLD")
                        votes[sig] += weight
                except Exception:
                    pass

            if votes["BUY"] > votes["SELL"] and votes["BUY"] > votes["HOLD"]:
                result["4h"] = {"signal": "BUY", "confidence": int(votes["BUY"] * 100), "strategy": "Freqtrade_4h_Vote"}
            elif votes["SELL"] > votes["BUY"] and votes["SELL"] > votes["HOLD"]:
                result["4h"] = {"signal": "SELL", "confidence": int(votes["SELL"] * 100), "strategy": "Freqtrade_4h_Vote"}

        # 1h 策略投票
        if "1h" in timeframes:
            votes = {"BUY": 0, "SELL": 0, "HOLD": 0}
            for mod, cls, weight in STRATEGIES_1H:
                try:
                    res = ml_trade_service._run_freqtrade_strategy_signal_hyperliquid(mod, cls, coin)
                    if res.get("ok") and res.get("side"):
                        side = res.get("side")
                        sig = "BUY" if side == "long" else ("SELL" if side == "short" else "HOLD")
                        votes[sig] += weight
                except Exception:
                    pass

            if votes["BUY"] > votes["SELL"] and votes["BUY"] > votes["HOLD"]:
                result["1h"] = {"signal": "BUY", "confidence": int(votes["BUY"] * 100), "strategy": "Freqtrade_1h_Vote"}
            elif votes["SELL"] > votes["BUY"] and votes["SELL"] > votes["HOLD"]:
                result["1h"] = {"signal": "SELL", "confidence": int(votes["SELL"] * 100), "strategy": "Freqtrade_1h_Vote"}

    except Exception:
        pass

    return result


def _fuse_technical_fundamental(technical_result: dict, fundamental_result: dict) -> dict:
    """
    技术面 + 基本面撮合
    - 第二重趋势一致性检查
    - 矛盾时：趋势方向保持一致（取技术面为主），置信度在幅度内调整
    """
    tech_dir = technical_result.get("direction", "NEUTRAL")
    tech_conf = technical_result.get("confidence", 0)
    fund_dir = fundamental_result.get("direction", "NEUTRAL")
    fund_conf = fundamental_result.get("confidence", 0)
    
    # 技术面权重高于基本面（技术面60% + 基本面40%）
    TECH_WEIGHT = 0.6
    FUND_WEIGHT = 0.4
    
    # 判断第二重一致性
    tech_core = tech_dir.replace("REVERSAL_", "") if tech_dir else "NEUTRAL"
    fund_core = fund_dir
    
    consistent = tech_core == fund_core and tech_core != "NEUTRAL"
    
    # 融合方向：技术面为主
    final_direction = tech_dir if tech_dir != "NEUTRAL" else fund_dir
    
    conflict_level = 0.0
    
    # 融合置信度：
    # - 一致时：加权平均
    # - 不一致时：取较低值，并按矛盾程度扣减
    # - 基本面NEUTRAL时：不扣减，直接使用技术面置信度
    if consistent:
        final_confidence = round(
            tech_conf * TECH_WEIGHT + fund_conf * FUND_WEIGHT, 1
        )
    elif fund_core == "NEUTRAL":
        final_confidence = tech_conf
    else:
        base_conf = min(tech_conf, fund_conf)
        conflict_level = (tech_conf / 100) * (fund_conf / 100)
        deduction = conflict_level * 30
        final_confidence = round(max(0, base_conf - deduction), 1)
    
    return {
        "technical": {
            "direction": tech_dir,
            "confidence": tech_conf,
        },
        "fundamental": {
            "direction": fund_dir,
            "confidence": fund_conf,
        },
        "consistent": consistent,
        "final_direction": final_direction,
        "final_confidence": final_confidence,
        "weights": {"technical": TECH_WEIGHT, "fundamental": FUND_WEIGHT},
        "conflict_level": round(conflict_level * 100, 1) if not consistent else 0,
    }


# ============================================================================
# 主入口: 完整三屏交易算法驱动
# ============================================================================

def compute_full_trading_signal(spot_inst: str = INST_SPOT, is_btc: bool = True) -> dict:
    """
    完整三屏交易信号计算
    输出: {
        "symbol", "price",
        "trend_consistency": {趋势一致性计算结果},
        "bayesian_confidence": {贝叶斯置信度计算结果},
        "technical_fundamental_fusion": {技术面+基本面撮合结果},
        "final_signal": {方向, 置信度},
    }
    """
    daily = _fetch_candles(spot_inst, "1D", 250)
    weekly = _fetch_candles(spot_inst, "1W", 210)
    hourly = _fetch_candles(spot_inst, "1H", 168)
    
    if not daily:
        return {"error": f"无法获取{spot_inst} K线数据"}
    
    daily_closes = [c["c"] for c in daily]
    weekly_closes = [c["c"] for c in weekly] if weekly else []
    hourly_closes = [c["c"] for c in hourly] if hourly else []
    price = daily_closes[-1]
    symbol = spot_inst.split("-")[0]
    
    # 跨周期数据对齐：将1h K线聚合成4h K线
    four_hourly = _resample_candles(hourly, "4h")
    four_hourly_closes = [c["c"] for c in four_hourly] if four_hourly else []
    
    # 创建 DataFrame
    import pandas as pd
    daily_df = pd.DataFrame({
        "open": [c["o"] for c in daily],
        "high": [c["h"] for c in daily],
        "low": [c["l"] for c in daily],
        "close": daily_closes,
        "volume": [c["vol"] for c in daily],
    }) if daily else pd.DataFrame()
    weekly_df = pd.DataFrame({
        "open": [c["o"] for c in weekly],
        "high": [c["h"] for c in weekly],
        "low": [c["l"] for c in weekly],
        "close": weekly_closes,
        "volume": [c["vol"] for c in weekly],
    }) if weekly else pd.DataFrame()
    hourly_df = pd.DataFrame({
        "open": [c["o"] for c in hourly],
        "high": [c["h"] for c in hourly],
        "low": [c["l"] for c in hourly],
        "close": hourly_closes,
        "volume": [c["vol"] for c in hourly],
    }) if hourly else pd.DataFrame()
    four_hourly_df = pd.DataFrame({
        "open": [c["o"] for c in four_hourly],
        "high": [c["h"] for c in four_hourly],
        "low": [c["l"] for c in four_hourly],
        "close": four_hourly_closes,
        "volume": [c["vol"] for c in four_hourly],
    }) if four_hourly else pd.DataFrame()
    
    # 1. 趋势一致性计算（静态+三维动态融合）
    trend_consistency = _calc_trend_consistency_with_dynamics(weekly_df, daily_df)
    
    # 2. 贝叶斯置信度计算（动态权重）
    bayesian_confidence = _calc_bayesian_confidence(weekly_df, daily_df)
    
    # 3. 基本面数据获取
    fundamental_data = _fetch_fundamental_data(symbol)
    
    # 4. Freqtrade 策略信号获取（1h/4h）
    freqtrade_signals = _fetch_freqtrade_signals(symbol)
    
    # 5. 技术面+基本面撮合
    fusion_result = _fuse_technical_fundamental(
        {"direction": bayesian_confidence["direction"], "confidence": bayesian_confidence["confidence"]},
        fundamental_data
    )
    
    # 6. 整合 Freqtrade 信号
    final_direction = fusion_result["final_direction"]
    final_confidence = fusion_result["final_confidence"]
    
    ft_1h_signal = freqtrade_signals.get("1h", {}).get("signal", "HOLD")
    ft_4h_signal = freqtrade_signals.get("4h", {}).get("signal", "HOLD")
    ft_1h_conf = freqtrade_signals.get("1h", {}).get("confidence", 0)
    ft_4h_conf = freqtrade_signals.get("4h", {}).get("confidence", 0)
    
    ft_consistent = False
    if final_direction in ("BULL", "BEAR"):
        ft_dir_map = {"BUY": "BULL", "SELL": "BEAR", "LONG": "BULL", "SHORT": "BEAR", "HOLD": "NEUTRAL"}
        ft_1h_dir = ft_dir_map.get(ft_1h_signal, "NEUTRAL")
        ft_4h_dir = ft_dir_map.get(ft_4h_signal, "NEUTRAL")
        
        if ft_1h_dir == final_direction or ft_4h_dir == final_direction:
            ft_consistent = True
            if ft_1h_dir == final_direction and ft_1h_conf > 0:
                final_confidence = min(100, final_confidence + ft_1h_conf * 0.1)
            if ft_4h_dir == final_direction and ft_4h_conf > 0:
                final_confidence = min(100, final_confidence + ft_4h_conf * 0.15)
        elif ft_1h_dir != "NEUTRAL" or ft_4h_dir != "NEUTRAL":
            final_confidence = max(0, final_confidence - 10)
    
    # 最终信号
    final_signal = {
        "direction": final_direction,
        "confidence": round(final_confidence, 1),
        "trend_consistent": trend_consistency["consistent"],
        "fusion_consistent": fusion_result["consistent"],
        "freqtrade_consistent": ft_consistent,
    }
    
    return {
        "symbol": symbol,
        "spot_inst": spot_inst,
        "price": round(price, 2),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframes": {
            "weekly": len(weekly_df),
            "daily": len(daily_df),
            "4h": len(four_hourly_df),
            "1h": len(hourly_df),
        },
        "resampling": {
            "1h_to_4h": len(four_hourly_df),
            "method": "backtrader_style",
        },
        "trend_consistency": trend_consistency,
        "bayesian_confidence": bayesian_confidence,
        "fundamental_data": fundamental_data,
        "freqtrade_signals": freqtrade_signals,
        "technical_fundamental_fusion": fusion_result,
        "final_signal": final_signal,
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

    # 趋势一致性评估 + 衰竭信号检测（入场前置条件）
    trend_metrics = _calc_trend_metrics(daily_closes, weekly_closes)
    consistency = _assess_trend_consistency(trend_metrics)
    exhaustion = _detect_exhaustion(trend_metrics, direction)

    # 经典指标置信度计算（周线组 + 日线组）
    import pandas as pd
    daily_df = pd.DataFrame({
        "open": [c["o"] for c in daily],
        "high": [c["h"] for c in daily],
        "low": [c["l"] for c in daily],
        "close": daily_closes,
        "volume": [c["vol"] for c in daily],
    }) if daily else pd.DataFrame()
    weekly_df = pd.DataFrame({
        "open": [c["o"] for c in weekly],
        "high": [c["h"] for c in weekly],
        "low": [c["l"] for c in weekly],
        "close": weekly_closes,
        "volume": [c["vol"] for c in weekly],
    }) if weekly else pd.DataFrame()
    classic_confidence = _calc_classic_indicator_confidence(weekly_df, daily_df)

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
        "trend_metrics": trend_metrics,
        "trend_consistency": consistency,
        "exhaustion_signals": exhaustion,
        "classic_indicators": classic_confidence,
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
            lvl_price = base_price * (1 - addon_pct * n)
            spacing = f"-{addon_pct*n*100:.1f}%" if n > 0 else "—"
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
            lvl_price = base_price * (1 + addon_pct * n)
            spacing = f"+{addon_pct*n*100:.1f}%" if n > 0 else "—"
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
                    
                    avg_px = float(p.get("avgPx", 0))
                    pos_direction = "BULL" if side == "LONG" else "BEAR"
                    s2_pos_avg = compute_screen2(pos_direction, avg_px, inst_id=swap_inst, vol_mult=vm_pos)
                    
                    entry_levels = s2_pos_avg["entry_levels"]
                    entry_prices = [l["price"] for l in entry_levels]
                    current_price = s1_pos["price"]
                    
                    martingale_level = sum(1 for ep in entry_prices if (
                        (s2_pos_avg["direction"] == "BULL" and current_price <= ep) or
                        (s2_pos_avg["direction"] == "BEAR" and current_price >= ep)
                    ))
                    
                    for lvl in entry_levels:
                        n = entry_levels.index(lvl)
                        if s2_pos_avg["direction"] == "BULL":
                            if current_price <= lvl["price"]:
                                lvl["status"] = "已触发"
                            elif n == 0:
                                lvl["status"] = "已入场"
                            else:
                                lvl["status"] = "未到达"
                        else:
                            if current_price >= lvl["price"]:
                                lvl["status"] = "已触发"
                            elif n == 0:
                                lvl["status"] = "已入场"
                            else:
                                lvl["status"] = "未到达"
                    
                    next_entry_pct = None
                    next_entry_price = None
                    if martingale_level < len(entry_levels):
                        next_entry_price = entry_levels[martingale_level]["price"]
                        next_entry_pct = round(abs(next_entry_price - current_price) / current_price * 100, 2)
                    
                    pnl_pct = round((current_price - avg_px) / avg_px * 100 * (1 if side == "LONG" else -1), 2)
                    tp_price = avg_px * (1 + s2_pos_avg["tp_pct"] / 100) if s2_pos_avg["direction"] == "BULL" else avg_px * (1 - s2_pos_avg["tp_pct"] / 100)
                    distance_to_tp = round(abs(current_price - tp_price) / avg_px * 100, 2)
                    
                    positions.append({
                        "coin": coin_symbol,
                        "size": abs(pos),
                        "side": side,
                        "entry_px": avg_px,
                        "current_price": current_price,
                        "upnl": float(p.get("upl", 0)),
                        "pnl_pct": pnl_pct,
                        "leverage": float(p.get("lever", 1)),
                        "direction": s2_pos_avg["direction"],
                        "vol_mult": vm_pos,
                        "martingale_level": martingale_level,
                        "max_levels": MAX_ADDONS + 1,
                        "next_entry_price": next_entry_price,
                        "next_entry_pct": next_entry_pct,
                        "tp_price": tp_price,
                        "tp_pct": s2_pos_avg["tp_pct"],
                        "addon_pct": s2_pos_avg["addon_pct"],
                        "distance_to_tp": distance_to_tp,
                        "entry_levels": [{"level": l["level"], "price": l["price"], "spacing": l["spacing"], "status": l["status"]} for l in entry_levels],
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
