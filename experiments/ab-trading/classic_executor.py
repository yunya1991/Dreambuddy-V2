#!/usr/bin/env python3
"""
经典指标执行器
- 第三屏执行：基于技术指标的精准入场/离场
- ATR 动态止损 + 分级止盈
- AI 指令集成：接收方向约束和币种池
- 双模式运行：AI主导模式（接收指令）/ 经典接管模式（自主决策）
"""
import json, os, subprocess, math, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "data" / "classic_executor_state.json"
LOG_DIR = BASE_DIR / "logs" / "classic_executor"
LOG_DIR.mkdir(parents=True, exist_ok=True)

HOME_BIN = "/opt/homebrew/bin"
os.environ["PATH"] = HOME_BIN + ":" + os.environ.get("PATH", "")

OKX_PROFILE = os.environ.get("SCREEN_OKX_PROFILE", "screen_trade")

MAX_POSITION_PCT = 0.20
ATR_STOP_MULT = 1.5
TAKE_PROFIT_PCT = 0.04
TRAILING_STOP_PCT = 0.02

_cache: dict = {}
_CACHE_TTL = 60


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
            return {"ok": False, "err": stderr[:300]}
        if stdout.startswith("[") or stdout.startswith("{"):
            return {"ok": True, "data": json.loads(stdout)}
        return {"ok": True, "data": stdout}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _log(level: str, msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    log_file = LOG_DIR / f"classic_executor_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
    with open(log_file, "a") as f:
        f.write(line + "\n")


def _load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "mode": "ai_directed",
        "last_signal_ts": 0,
        "active_signals": [],
        "position_history": [],
        "exec_count": 0,
        "error_count": 0,
    }


def _save_state(state: Dict):
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(STATE_FILE)


# ── AI 指令读取 ──────────────────────────────────────────────────────────

def get_ai_directive() -> Dict:
    """从 mode_manager 读取 AI 指令"""
    try:
        from mode_manager import get_ai_directive
        return get_ai_directive()
    except Exception:
        pass
    try:
        directive_file = BASE_DIR / "data" / "mode_state" / "ai_directive.json"
        if directive_file.exists():
            with open(directive_file, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "direction": None,
        "symbol_pool": ["BTC", "ETH"],
        "confidence": 0.5,
        "risk_level": "medium",
    }


def get_current_mode() -> str:
    """获取当前模式"""
    try:
        from mode_manager import get_current_state
        return get_current_state().get("mode", "ai_directed")
    except Exception:
        return "ai_directed"


# ── 技术指标计算 ─────────────────────────────────────────────────────────

def _fetch_candles(symbol: str, bar: str = "1H", limit: int = 60) -> List:
    inst = f"{symbol}-USDT-SWAP"
    r = _run_okx(["market", "candles", inst, "--bar", bar, "--limit", str(limit), "--json"])
    if not r["ok"]:
        return []
    raw = r["data"]
    candles = []
    for c in raw:
        candles.append({
            "ts": int(c[0]),
            "o": float(c[1]), "h": float(c[2]), "l": float(c[3]),
            "c": float(c[4]), "vol": float(c[5]),
        })
    return list(reversed(candles))


def _calc_atr(candles: List, period: int = 14) -> float:
    """计算 ATR"""
    if len(candles) < period + 1:
        return 0.0
    tr_list = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]
        l = candles[i]["l"]
        prev_c = candles[i-1]["c"]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        tr_list.append(tr)
    if len(tr_list) < period:
        return sum(tr_list) / len(tr_list) if tr_list else 0.0
    atr = sum(tr_list[-period:]) / period
    return atr


def _calc_rsi(candles: List, period: int = 14) -> float:
    """计算 RSI"""
    if len(candles) < period + 1:
        return 50.0
    changes = []
    for i in range(1, len(candles)):
        changes.append(candles[i]["c"] - candles[i-1]["c"])
    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calc_macd(candles: List, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    """计算 MACD"""
    if len(candles) < slow + signal:
        return {"macd": 0, "signal": 0, "hist": 0}

    closes = [c["c"] for c in candles]
    ema_fast = []
    ema_slow = []
    alpha_fast = 2 / (fast + 1)
    alpha_slow = 2 / (slow + 1)

    for i, c in enumerate(closes):
        if i == 0:
            ema_fast.append(c)
            ema_slow.append(c)
        else:
            ema_fast.append(c * alpha_fast + ema_fast[-1] * (1 - alpha_fast))
            ema_slow.append(c * alpha_slow + ema_slow[-1] * (1 - alpha_slow))

    macd_line = [ema_fast[i] - ema_slow[i] for i in range(len(ema_fast))]
    alpha_signal = 2 / (signal + 1)
    signal_line = []
    for i, m in enumerate(macd_line):
        if i == 0:
            signal_line.append(m)
        else:
            signal_line.append(m * alpha_signal + signal_line[-1] * (1 - alpha_signal))

    hist = [macd_line[i] - signal_line[i] for i in range(len(macd_line))]

    return {
        "macd": macd_line[-1],
        "signal": signal_line[-1],
        "hist": hist[-1],
        "hist_prev": hist[-2] if len(hist) >= 2 else 0,
    }


def _calc_bollinger(candles: List, period: int = 20, std: int = 2) -> Dict:
    """计算布林带"""
    if len(candles) < period:
        return {"middle": 0, "upper": 0, "lower": 0, "pct": 50}
    closes = [c["c"] for c in candles[-period:]]
    middle = sum(closes) / period
    variance = sum((c - middle) ** 2 for c in closes) / period
    sigma = math.sqrt(variance)
    upper = middle + std * sigma
    lower = middle - std * sigma
    current = candles[-1]["c"]
    pct = (current - lower) / (upper - lower) * 100 if upper > lower else 50
    return {"middle": middle, "upper": upper, "lower": lower, "pct": round(pct, 2)}


# ── 信号生成 ────────────────────────────────────────────────────────────

def generate_signals(symbol: str) -> Dict:
    """
    生成第三屏技术信号
    返回: {
        symbol, price, signals: [{type, strength, confidence, reason, indicator}],
        indicators: {atr, rsi, macd, bollinger},
        recommended_action: enter_long/enter_short/hold/exit_long/exit_short,
        entry_price: 建议入场价,
        stop_loss: 止损价,
        take_profit: 止盈价,
    }
    """
    candles_1h = _fetch_candles(symbol, "1H", 60)
    candles_4h = _fetch_candles(symbol, "4H", 20)

    if not candles_1h:
        return {"error": "无法获取K线数据", "symbol": symbol}

    atr_1h = _calc_atr(candles_1h, 14)
    rsi_1h = _calc_rsi(candles_1h, 14)
    macd_1h = _calc_macd(candles_1h)
    boll_1h = _calc_bollinger(candles_1h)

    atr_4h = _calc_atr(candles_4h, 14)
    rsi_4h = _calc_rsi(candles_4h, 14)
    macd_4h = _calc_macd(candles_4h)

    price = candles_1h[-1]["c"]
    prev_candle = candles_1h[-2] if len(candles_1h) >= 2 else None
    prev_4h = candles_4h[-2] if len(candles_4h) >= 2 else None

    signals = []

    # 1. RSI 超买超卖信号
    if rsi_1h < 30 and rsi_4h < 40:
        signals.append({
            "type": "enter_long",
            "strength": min(1.0, (30 - rsi_1h) / 15),
            "confidence": 0.65,
            "reason": f"RSI双周期超卖 (1H:{rsi_1h:.1f}, 4H:{rsi_4h:.1f})",
            "indicator": "RSI",
        })
    elif rsi_1h > 70 and rsi_4h > 60:
        signals.append({
            "type": "enter_short",
            "strength": min(1.0, (rsi_1h - 70) / 15),
            "confidence": 0.65,
            "reason": f"RSI双周期超买 (1H:{rsi_1h:.1f}, 4H:{rsi_4h:.1f})",
            "indicator": "RSI",
        })

    # 2. MACD 交叉信号
    if macd_1h["macd"] > macd_1h["signal"] and macd_1h["hist_prev"] <= 0 and macd_1h["hist"] > 0:
        signals.append({
            "type": "enter_long",
            "strength": min(1.0, macd_1h["hist"] / (atr_1h * 0.5) if atr_1h else 0.5),
            "confidence": 0.7,
            "reason": "MACD金叉，柱线翻红",
            "indicator": "MACD",
        })
    elif macd_1h["macd"] < macd_1h["signal"] and macd_1h["hist_prev"] >= 0 and macd_1h["hist"] < 0:
        signals.append({
            "type": "enter_short",
            "strength": min(1.0, abs(macd_1h["hist"]) / (atr_1h * 0.5) if atr_1h else 0.5),
            "confidence": 0.7,
            "reason": "MACD死叉，柱线翻绿",
            "indicator": "MACD",
        })

    # 3. MACD 4H 趋势确认
    if macd_4h["hist"] > 0 and macd_4h["hist"] > macd_4h["hist_prev"]:
        signals.append({
            "type": "trend_long",
            "strength": min(1.0, macd_4h["hist"] / (atr_4h * 0.5) if atr_4h else 0.5),
            "confidence": 0.75,
            "reason": "4H MACD多头趋势增强",
            "indicator": "MACD_4H",
        })
    elif macd_4h["hist"] < 0 and macd_4h["hist"] < macd_4h["hist_prev"]:
        signals.append({
            "type": "trend_short",
            "strength": min(1.0, abs(macd_4h["hist"]) / (atr_4h * 0.5) if atr_4h else 0.5),
            "confidence": 0.75,
            "reason": "4H MACD空头趋势增强",
            "indicator": "MACD_4H",
        })

    # 4. 布林带突破信号
    if boll_1h["pct"] > 90:
        signals.append({
            "type": "enter_short",
            "strength": min(1.0, (boll_1h["pct"] - 90) / 10),
            "confidence": 0.6,
            "reason": f"布林带上轨突破 ({boll_1h['pct']:.1f}%)",
            "indicator": "Bollinger",
        })
    elif boll_1h["pct"] < 10:
        signals.append({
            "type": "enter_long",
            "strength": min(1.0, (10 - boll_1h["pct"]) / 10),
            "confidence": 0.6,
            "reason": f"布林带下轨突破 ({boll_1h['pct']:.1f}%)",
            "indicator": "Bollinger",
        })

    # 5. 价格突破信号（1H）
    if prev_candle:
        if price > prev_candle["h"]:
            signals.append({
                "type": "breakout_long",
                "strength": min(1.0, (price - prev_candle["h"]) / atr_1h if atr_1h else 0.3),
                "confidence": 0.55,
                "reason": f"突破前高 ({prev_candle['h']:.2f})",
                "indicator": "Breakout",
            })
        elif price < prev_candle["l"]:
            signals.append({
                "type": "breakout_short",
                "strength": min(1.0, (prev_candle["l"] - price) / atr_1h if atr_1h else 0.3),
                "confidence": 0.55,
                "reason": f"跌破前低 ({prev_candle['l']:.2f})",
                "indicator": "Breakout",
            })

    # 6. ATR 波动信号（波动放大可能是趋势启动）
    if atr_1h > atr_4h * 1.5:
        signals.append({
            "type": "volatility_surge",
            "strength": min(1.0, (atr_1h - atr_4h) / atr_4h),
            "confidence": 0.5,
            "reason": f"波动率放大 (1H ATR:{atr_1h:.2f} > 4H ATR:{atr_4h:.2f})",
            "indicator": "ATR",
        })

    # 综合推荐
    long_signals = [s for s in signals if s["type"].startswith("enter_long") or s["type"] == "trend_long"]
    short_signals = [s for s in signals if s["type"].startswith("enter_short") or s["type"] == "trend_short"]

    recommended_action = "hold"
    entry_price = price
    stop_loss = None
    take_profit = None

    long_score = sum(s["strength"] * s["confidence"] for s in long_signals)
    short_score = sum(s["strength"] * s["confidence"] for s in short_signals)

    if long_score > short_score and long_score > 0.5:
        recommended_action = "enter_long"
        stop_loss = price - atr_1h * ATR_STOP_MULT
        take_profit = price + price * TAKE_PROFIT_PCT
    elif short_score > long_score and short_score > 0.5:
        recommended_action = "enter_short"
        stop_loss = price + atr_1h * ATR_STOP_MULT
        take_profit = price - price * TAKE_PROFIT_PCT

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "signals": sorted(signals, key=lambda x: x["strength"] * x["confidence"], reverse=True),
        "indicators": {
            "atr_1h": round(atr_1h, 2),
            "atr_4h": round(atr_4h, 2),
            "rsi_1h": round(rsi_1h, 1),
            "rsi_4h": round(rsi_4h, 1),
            "macd_1h": {k: round(v, 4) for k, v in macd_1h.items()},
            "macd_4h": {k: round(v, 4) for k, v in macd_4h.items()},
            "bollinger_1h": {k: round(v, 2) if isinstance(v, float) else v for k, v in boll_1h.items()},
        },
        "recommended_action": recommended_action,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2) if stop_loss else None,
        "take_profit": round(take_profit, 2) if take_profit else None,
        "long_score": round(long_score, 3),
        "short_score": round(short_score, 3),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── 持仓监控 & 止损检查 ──────────────────────────────────────────────────

def get_open_positions(symbol: str = None) -> List:
    """获取当前持仓"""
    r = _run_okx(["account", "positions", "--json"])
    if not r["ok"]:
        return []
    positions = []
    for p in r["data"]:
        inst_type = p.get("instType")
        if inst_type != "SWAP":
            continue
        if symbol and p.get("instId") != f"{symbol}-USDT-SWAP":
            continue
        pos_side = p.get("posSide")
        pos = float(p.get("pos", "0"))
        if pos <= 0:
            continue
        avg_price = float(p.get("avgPx", "0"))
        mark_price = float(p.get("markPx", "0"))
        unrealized_pnl = float(p.get("upl", "0"))
        pnl_pct = float(p.get("uplRatio", "0")) * 100

        positions.append({
            "inst_id": p.get("instId"),
            "symbol": p.get("instId").replace("-USDT-SWAP", "") if p.get("instId") else "",
            "pos_side": pos_side,
            "pos": round(pos, 4),
            "avg_price": round(avg_price, 2),
            "mark_price": round(mark_price, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "leverage": int(p.get("lever", "10")),
        })
    return positions


def check_stop_loss(position: Dict, signals: Dict) -> Dict:
    """
    检查持仓是否需要止损/止盈
    返回: {action: hold/reduce/close, reason, pnl_pct, stop_loss, take_profit}
    """
    pos_side = position["pos_side"]
    mark_price = position["mark_price"]
    avg_price = position["avg_price"]
    pnl_pct = position["pnl_pct"]
    atr_1h = signals.get("indicators", {}).get("atr_1h", 0)

    stop_loss_price = None
    take_profit_price = None

    if pos_side == "long":
        stop_loss_price = avg_price - atr_1h * ATR_STOP_MULT
        take_profit_price = avg_price + avg_price * TAKE_PROFIT_PCT
        trailing_stop = mark_price - mark_price * TRAILING_STOP_PCT
    else:
        stop_loss_price = avg_price + atr_1h * ATR_STOP_MULT
        take_profit_price = avg_price - avg_price * TAKE_PROFIT_PCT
        trailing_stop = mark_price + mark_price * TRAILING_STOP_PCT

    # ATR 止损
    if pos_side == "long" and mark_price <= stop_loss_price:
        return {
            "action": "close",
            "reason": f"ATR止损触发 (市价:{mark_price:.2f} ≤ 止损:{stop_loss_price:.2f})",
            "pnl_pct": pnl_pct,
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(take_profit_price, 2),
            "trigger_type": "atr_stop",
        }
    elif pos_side == "short" and mark_price >= stop_loss_price:
        return {
            "action": "close",
            "reason": f"ATR止损触发 (市价:{mark_price:.2f} ≥ 止损:{stop_loss_price:.2f})",
            "pnl_pct": pnl_pct,
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(take_profit_price, 2),
            "trigger_type": "atr_stop",
        }

    # 止盈
    if pos_side == "long" and mark_price >= take_profit_price:
        return {
            "action": "close",
            "reason": f"止盈触发 (市价:{mark_price:.2f} ≥ 止盈:{take_profit_price:.2f})",
            "pnl_pct": pnl_pct,
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(take_profit_price, 2),
            "trigger_type": "take_profit",
        }
    elif pos_side == "short" and mark_price <= take_profit_price:
        return {
            "action": "close",
            "reason": f"止盈触发 (市价:{mark_price:.2f} ≤ 止盈:{take_profit_price:.2f})",
            "pnl_pct": pnl_pct,
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(take_profit_price, 2),
            "trigger_type": "take_profit",
        }

    # 反向信号
    if pos_side == "long" and signals.get("recommended_action") == "enter_short":
        return {
            "action": "close",
            "reason": "出现反向入场信号",
            "pnl_pct": pnl_pct,
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(take_profit_price, 2),
            "trigger_type": "reverse_signal",
        }
    elif pos_side == "short" and signals.get("recommended_action") == "enter_long":
        return {
            "action": "close",
            "reason": "出现反向入场信号",
            "pnl_pct": pnl_pct,
            "stop_loss": round(stop_loss_price, 2),
            "take_profit": round(take_profit_price, 2),
            "trigger_type": "reverse_signal",
        }

    return {
        "action": "hold",
        "reason": "继续持有",
        "pnl_pct": pnl_pct,
        "stop_loss": round(stop_loss_price, 2),
        "take_profit": round(take_profit_price, 2),
        "trigger_type": None,
    }


# ── OKX 交易所深度适配 ──────────────────────────────────────────────────

def execute_market_order(symbol: str, direction: str, size: float = None) -> Dict:
    """市价单开仓"""
    inst = f"{symbol}-USDT-SWAP"
    side = "buy" if direction == "long" else "sell"
    pos_side = direction

    if size is None:
        r_balance = _run_okx(["account", "balance", "--json"])
        if not r_balance["ok"]:
            return {"ok": False, "error": "无法获取余额"}
        balance = 0
        for b in r_balance["data"]:
            if b.get("ccy") == "USDT":
                balance = float(b.get("eq", "0"))
                break
        candles = _fetch_candles(symbol, "1H", 5)
        price = candles[-1]["c"] if candles else 1
        size = balance * BASE_POSITION_PCT / price
        size = round(size, 4)

    r = _run_okx(["trade", "order", inst, side, "market", str(size), "--posSide", pos_side, "--json"])
    if r["ok"]:
        return {"ok": True, "order_type": "market", "symbol": symbol, "direction": direction, "size": size, "message": "市价单开仓成功"}
    return {"ok": False, "error": r.get("err", "市价单开仓失败")}


def execute_limit_order(symbol: str, direction: str, price: float, size: float = None) -> Dict:
    """限价单开仓"""
    inst = f"{symbol}-USDT-SWAP"
    side = "buy" if direction == "long" else "sell"
    pos_side = direction

    if size is None:
        r_balance = _run_okx(["account", "balance", "--json"])
        if not r_balance["ok"]:
            return {"ok": False, "error": "无法获取余额"}
        balance = 0
        for b in r_balance["data"]:
            if b.get("ccy") == "USDT":
                balance = float(b.get("eq", "0"))
                break
        size = balance * BASE_POSITION_PCT / price
        size = round(size, 4)

    r = _run_okx(["trade", "order", inst, side, "limit", str(price), str(size), "--posSide", pos_side, "--json"])
    if r["ok"]:
        return {"ok": True, "order_type": "limit", "symbol": symbol, "direction": direction, "price": price, "size": size, "message": "限价单已提交"}
    return {"ok": False, "error": r.get("err", "限价单提交失败")}


def execute_conditional_order(symbol: str, direction: str, trigger_price: float, order_price: float = None, size: float = None) -> Dict:
    """条件单（止盈/止损）"""
    inst = f"{symbol}-USDT-SWAP"
    side = "buy" if direction == "long" else "sell"
    pos_side = direction
    order_price = order_price or trigger_price

    if size is None:
        positions = get_open_positions(symbol)
        if positions:
            for p in positions:
                if p["pos_side"] == pos_side:
                    size = p["pos"]
                    break

    if size is None:
        return {"ok": False, "error": "无法确定下单数量"}

    r = _run_okx(["trade", "order", inst, side, "conditional", str(trigger_price), str(order_price), str(size), "--posSide", pos_side, "--json"])
    if r["ok"]:
        return {"ok": True, "order_type": "conditional", "symbol": symbol, "direction": direction, "trigger_price": trigger_price, "order_price": order_price, "size": size, "message": "条件单已提交"}
    return {"ok": False, "error": r.get("err", "条件单提交失败")}


def execute_take_profit(symbol: str, pos_side: str, take_profit_price: float) -> Dict:
    """设置止盈条件单"""
    positions = get_open_positions(symbol)
    for p in positions:
        if p["pos_side"] == pos_side:
            direction = "short" if pos_side == "long" else "long"
            return execute_conditional_order(symbol, direction, take_profit_price, take_profit_price, p["pos"])
    return {"ok": False, "error": "未找到对应持仓"}


def execute_stop_loss(symbol: str, pos_side: str, stop_loss_price: float) -> Dict:
    """设置止损条件单"""
    positions = get_open_positions(symbol)
    for p in positions:
        if p["pos_side"] == pos_side:
            direction = "short" if pos_side == "long" else "long"
            return execute_conditional_order(symbol, direction, stop_loss_price, stop_loss_price, p["pos"])
    return {"ok": False, "error": "未找到对应持仓"}


def close_position(symbol: str, pos_side: str = None) -> Dict:
    """平仓"""
    inst = f"{symbol}-USDT-SWAP"
    positions = get_open_positions(symbol)
    for p in positions:
        if pos_side and p["pos_side"] != pos_side:
            continue
        r = _run_okx(["trade", "close-position", inst, "--posSide", p["pos_side"], "--json"])
        if r["ok"]:
            return {"ok": True, "action": "close", "symbol": symbol, "pos_side": p["pos_side"], "pos": p["pos"], "message": "平仓成功"}
        return {"ok": False, "error": r.get("err", "平仓失败")}
    return {"ok": False, "error": "未找到对应持仓"}


# ── 执行决策 ────────────────────────────────────────────────────────────

def execute_trade(symbol: str, action: str, pos_side: str = None, size: float = None, price: float = None, stop_loss: float = None, take_profit: float = None) -> Dict:
    """
    执行交易（支持多种下单类型）
    参数:
        action: enter_long/enter_short/close/enter_long_limit/enter_short_limit
        price: 限价单价格
        stop_loss: 止损价（开仓后自动设置）
        take_profit: 止盈价（开仓后自动设置）
    """
    state = _load_state()
    auto_execute = os.environ.get("SCREEN_AUTO_EXECUTE", "false").lower() == "true"

    if not auto_execute:
        return {
            "ok": True,
            "action": action,
            "symbol": symbol,
            "pos_side": pos_side,
            "size": size,
            "price": price,
            "status": "simulation",
            "message": "模拟执行（SCREEN_AUTO_EXECUTE=false）",
        }

    try:
        if action == "close":
            result = close_position(symbol, pos_side)
            if result["ok"]:
                state["exec_count"] = state.get("exec_count", 0) + 1
                state["position_history"].append({
                    "action": "close",
                    "symbol": symbol,
                    "pos_side": result.get("pos_side"),
                    "pos": result.get("pos"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                _save_state(state)
            return result

        elif action == "enter_long" or action == "enter_short":
            direction = action.split("_")[1]
            result = execute_market_order(symbol, direction, size)
            if result["ok"]:
                state["exec_count"] = state.get("exec_count", 0) + 1
                state["position_history"].append({
                    "action": action,
                    "symbol": symbol,
                    "pos_side": direction,
                    "order_type": "market",
                    "size": result.get("size"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                _save_state(state)

                if stop_loss:
                    sl_result = execute_stop_loss(symbol, direction, stop_loss)
                    if sl_result["ok"]:
                        _log("INFO", f"止损条件单已设置: {symbol} {direction} @ {stop_loss}")
                if take_profit:
                    tp_result = execute_take_profit(symbol, direction, take_profit)
                    if tp_result["ok"]:
                        _log("INFO", f"止盈条件单已设置: {symbol} {direction} @ {take_profit}")

            return result

        elif action == "enter_long_limit" or action == "enter_short_limit":
            direction = action.split("_")[1]
            if price is None:
                return {"ok": False, "error": "限价单需要指定价格"}
            result = execute_limit_order(symbol, direction, price, size)
            if result["ok"]:
                state["exec_count"] = state.get("exec_count", 0) + 1
                state["position_history"].append({
                    "action": action,
                    "symbol": symbol,
                    "pos_side": direction,
                    "order_type": "limit",
                    "price": price,
                    "size": result.get("size"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                _save_state(state)
            return result

        return {"ok": False, "error": f"未知操作: {action}"}

    except Exception as e:
        state["error_count"] = state.get("error_count", 0) + 1
        _save_state(state)
        return {"ok": False, "error": str(e)}


# ── 主执行循环 ──────────────────────────────────────────────────────────

def run(symbol: str = "BTC") -> Dict:
    """
    执行一轮经典指标检测和交易决策
    """
    mode = get_current_mode()
    directive = get_ai_directive()
    state = _load_state()

    signals = generate_signals(symbol)
    if signals.get("error"):
        return {"error": signals["error"], "mode": mode}

    positions = get_open_positions(symbol)

    # AI 主导模式：受方向约束
    if mode == "ai_directed":
        ai_direction = directive.get("direction")
        if ai_direction:
            if ai_direction == "long":
                signals["recommended_action"] = signals["recommended_action"] if signals["recommended_action"] in ("enter_long", "hold") else "hold"
            elif ai_direction == "short":
                signals["recommended_action"] = signals["recommended_action"] if signals["recommended_action"] in ("enter_short", "hold") else "hold"

    result = {
        "mode": mode,
        "symbol": symbol,
        "signals": signals,
        "positions": positions,
        "ai_directive": directive,
        "executions": [],
    }

    # 检查现有持仓的止损/止盈
    for pos in positions:
        sl_result = check_stop_loss(pos, signals)
        if sl_result["action"] != "hold":
            exec_result = execute_trade(symbol, "close", pos["pos_side"])
            result["executions"].append({
                "type": "stop_loss",
                "pos_side": pos["pos_side"],
                "reason": sl_result["reason"],
                "pnl_pct": sl_result["pnl_pct"],
                "execution": exec_result,
            })

    # 检查入场信号
    if not positions and signals["recommended_action"] != "hold":
        action = signals["recommended_action"]
        exec_result = execute_trade(symbol, action)
        result["executions"].append({
            "type": "entry",
            "action": action,
            "reason": f"技术指标触发入场 ({', '.join(s['indicator'] for s in signals['signals'][:3])})",
            "execution": exec_result,
        })

    state["last_signal_ts"] = time.time()
    state["active_signals"] = [s["type"] for s in signals["signals"][:5]]
    _save_state(state)

    return result


def get_executor_state() -> Dict:
    """获取执行器状态"""
    state = _load_state()
    mode = get_current_mode()
    directive = get_ai_directive()

    try:
        signals = generate_signals("BTC")
    except Exception:
        signals = {"error": "信号生成失败"}

    # AI 主导模式：应用方向约束
    if signals.get("recommended_action") and mode == "ai_directed":
        ai_direction = directive.get("direction")
        if ai_direction == "long":
            if signals["recommended_action"] not in ("enter_long", "hold"):
                signals["recommended_action"] = "hold"
        elif ai_direction == "short":
            if signals["recommended_action"] not in ("enter_short", "hold"):
                signals["recommended_action"] = "hold"

    try:
        positions = get_open_positions()
    except Exception:
        positions = []

    now_ts = time.time()
    elapsed_m = (now_ts - state.get("last_signal_ts", 0)) / 60

    return {
        "mode": mode,
        "ai_directive": directive,
        "signals": signals,
        "positions": positions,
        "exec_count": state.get("exec_count", 0),
        "error_count": state.get("error_count", 0),
        "last_signal_ts": state.get("last_signal_ts", 0),
        "elapsed_minutes": round(elapsed_m, 1),
        "state_updated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    result = run(symbol)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
