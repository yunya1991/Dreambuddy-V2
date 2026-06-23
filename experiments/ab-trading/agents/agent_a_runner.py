#!/usr/bin/env python3
"""
Agent A Runner - Raw Claude 交易决策
无任何系统加持，仅依赖模型原生推理能力
每次触发：获取市场数据 → 推理 → 决策 → 记录日志（不自动下单，需人工确认或设 AUTO_EXECUTE=true）
"""
import os, sys, json, requests
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.okx_spot import OKXSpotClient, _PROXIES
from scoring.scorecard import DecisionLog, _cycle_id

AUTO_EXECUTE = os.environ.get("AUTO_EXECUTE", "false").lower() == "true"
INST_ID = "BTC-USDT"
PER_TRADE_PCT = float(os.environ.get("PER_TRADE_PCT", "0.05"))
STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.06


def fetch_market_context(client: OKXSpotClient) -> dict:
    """采集基础市场数据供 Agent A 推理"""
    ticker = client.get_ticker(INST_ID)

    # 获取K线数据(1H x 24根)
    url = "https://www.okx.com/api/v5/market/candles"
    r = requests.get(url, params={"instId": INST_ID, "bar": "1H", "limit": "24"},
                     proxies=_PROXIES, timeout=10)
    candles = r.json().get("data", [])

    # 计算简单技术指标
    closes = [float(c[4]) for c in candles if c]
    price_change_24h = ((closes[0] - closes[-1]) / closes[-1] * 100) if len(closes) > 1 else 0
    vol_list = [float(c[5]) for c in candles if c]
    avg_vol = sum(vol_list) / len(vol_list) if vol_list else 0

    return {
        "inst_id": INST_ID,
        "current_price": ticker.get("last"),
        "bid": ticker.get("bid"),
        "ask": ticker.get("ask"),
        "vol24h": ticker.get("vol24h"),
        "price_change_24h_pct": round(price_change_24h, 2),
        "avg_vol_1h": round(avg_vol, 2),
        "recent_closes_24h": closes[:8],  # 最近8根K线收盘价
        "ts_utc": datetime.utcnow().isoformat(),
    }


def agent_a_decide(market_ctx: dict, balance: dict) -> dict:
    """
    Agent A 决策逻辑：直接基于原始市场数据推理。
    没有矛盾论、没有记忆、没有系统框架。

    这是 Raw LLM 的基准实现：
    - 仅使用价格变动、成交量、简单趋势
    - 无历史记忆，每次从零判断
    - 没有置信度门禁
    """
    price = market_ctx["current_price"]
    change_24h = market_ctx["price_change_24h_pct"]
    vol24h = market_ctx["vol24h"]
    avg_vol = market_ctx["avg_vol_1h"]
    closes = market_ctx["recent_closes_24h"]

    reasoning_steps = []
    reasoning_steps.append(f"当前BTC价格: {price} USDT")
    reasoning_steps.append(f"24H涨跌幅: {change_24h}%")
    reasoning_steps.append(f"24H成交量: {vol24h}")

    # 简单动量判断（无框架）
    if len(closes) >= 3:
        short_trend = closes[0] - closes[2]
        reasoning_steps.append(f"近3H价格变动: {round(short_trend, 2)} USDT")
    else:
        short_trend = 0

    # 量价判断
    vol_signal = vol24h > avg_vol * 1.5 if avg_vol > 0 else False
    reasoning_steps.append(f"成交量放大信号: {vol_signal}")

    # 原始决策逻辑
    action = "HOLD"
    confidence = 0.5
    rationale = "无明确信号，观望"

    if change_24h > 2 and short_trend > 0:
        action = "BUY"
        confidence = 0.6 + min(change_24h / 20, 0.2)
        rationale = f"24H上涨{change_24h}%，近3H延续上涨趋势"
        if vol_signal:
            confidence = min(confidence + 0.1, 0.85)
            rationale += "，量价配合"
    elif change_24h < -2 and short_trend < 0:
        action = "SELL"
        confidence = 0.6 + min(abs(change_24h) / 20, 0.2)
        rationale = f"24H下跌{abs(change_24h)}%，近3H延续下跌趋势"
    elif change_24h > 1:
        action = "BUY"
        confidence = 0.52
        rationale = f"小幅上涨{change_24h}%，弱多信号"

    reasoning_steps.append(f"决策: {action}，置信度: {confidence:.2f}")
    reasoning_steps.append(f"依据: {rationale}")

    # 计算仓位
    usdt_avail = balance.get("assets", {}).get("USDT", {}).get("avail", 0)
    position_size_usdt = round(usdt_avail * PER_TRADE_PCT, 2) if action != "HOLD" else 0

    return {
        "action": action,
        "confidence": round(confidence, 3),
        "reasoning_steps": reasoning_steps,
        "rationale": rationale,
        "position_size_usdt": position_size_usdt,
        "stop_loss_price": round(price * (1 - STOP_LOSS_PCT), 2) if action == "BUY" else None,
        "take_profit_price": round(price * (1 + TAKE_PROFIT_PCT), 2) if action == "BUY" else None,
        "market_regime": (
            "TREND_UP" if change_24h > 2 else
            "TREND_DOWN" if change_24h < -2 else "RANGE"
        ),
    }


def run():
    cycle = _cycle_id()
    print(f"[Agent A] 启动 cycle={cycle}")

    client = OKXSpotClient("a")

    # 获取账户余额
    balance = client.get_balance()
    if not balance["ok"]:
        print(f"[Agent A] 余额获取失败: {balance}")
        return

    # 获取市场数据
    market_ctx = fetch_market_context(client)
    print(f"[Agent A] BTC={market_ctx['current_price']}, 24H={market_ctx['price_change_24h_pct']}%")

    # 决策
    decision = agent_a_decide(market_ctx, balance)
    print(f"[Agent A] 决策: {decision['action']} | 置信度: {decision['confidence']}")

    # 记录决策日志
    log = DecisionLog("a", cycle)
    log.data.update({
        "market_regime": decision["market_regime"],
        "reasoning_steps": decision["reasoning_steps"],
        "confidence": decision["confidence"],
        "action": decision["action"],
        "entry_price": market_ctx["current_price"],
        "position_size_usdt": decision["position_size_usdt"],
        "stop_loss_price": decision["stop_loss_price"],
        "take_profit_price": decision["take_profit_price"],
        "decision_rationale": decision["rationale"],
        "system_features_used": [],
        "memory_loaded": False,
    })

    # 执行（仅在 AUTO_EXECUTE=true 时）
    if AUTO_EXECUTE and decision["action"] != "HOLD" and decision["position_size_usdt"] > 0:
        if decision["action"] == "BUY":
            exec_result = client.market_buy(INST_ID, decision["position_size_usdt"],
                                            tag=f"agent_a_{cycle}")
        elif decision["action"] == "SELL":
            btc_avail = balance.get("assets", {}).get("BTC", {}).get("avail", 0)
            sell_btc = round(btc_avail * PER_TRADE_PCT, 8)
            exec_result = client.market_sell(INST_ID, sell_btc, tag=f"agent_a_{cycle}")
        else:
            exec_result = {"ok": False, "error": "HOLD, no execution"}
        log.data["execution"] = exec_result
        print(f"[Agent A] 执行结果: {exec_result}")
    else:
        print(f"[Agent A] AUTO_EXECUTE=false, 跳过执行（人工确认模式）")

    path = log.save()
    print(f"[Agent A] 日志已保存: {path}")
    return log.data


if __name__ == "__main__":
    run()
