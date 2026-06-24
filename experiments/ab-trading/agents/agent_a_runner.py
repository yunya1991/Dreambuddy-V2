#!/usr/bin/env python3
"""
Agent A Runner - Raw Claude 合约交易
无系统加持，仅依赖模型原生推理。
支持多币种 + 最大 5x 杠杆合约
"""
import os, sys, json, requests, warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.aster_spot import HyperliquidClient, scan_opportunities, get_candles
from scoring.scorecard import DecisionLog, _cycle_id
from orchestrator import request_early_run

AUTO_EXECUTE  = os.environ.get("AUTO_EXECUTE", "false").lower() == "true"
BUDGET_USDC   = 60.0       # 软隔离：合约账户预算上限
PER_TRADE_PCT = float(os.environ.get("PER_TRADE_PCT", "0.05"))
LEVERAGE      = 3
STOP_LOSS_PCT = 0.04
TP_PCT        = 0.08
UNIVERSE_A    = ["BTC", "ETH", "SOL", "HYPE", "AVAX", "ARB", "SUI", "INJ", "LINK", "TIA"]


def fetch_market_context(client: HyperliquidClient) -> dict:
    """采集所有标的的市场数据"""
    mids = client.get_all_mids()
    opps = client.scan_opportunities()

    # 对每个标的取 1H K线做简单指标（仅合约标的池 UNIVERSE_A）
    coin_data = {}
    for coin in UNIVERSE_A:
        price = mids.get(coin, 0)
        if price <= 0:
            continue
        try:
            candles = get_candles(coin, "1h", 24, client.proxies)
            closes  = [float(c["c"]) for c in candles if "c" in c]
            vols    = [float(c["v"]) for c in candles if "v" in c]
        except Exception:
            closes, vols = [], []

        ch24 = ((closes[0] - closes[-1]) / closes[-1] * 100) if len(closes) > 1 else 0
        ch4h = ((closes[0] - closes[3])  / closes[3]  * 100) if len(closes) > 3 else 0
        avg_vol = sum(vols) / len(vols) if vols else 0
        cur_vol = vols[0] if vols else 0

        coin_data[coin] = {
            "price":    price,
            "ch24":     round(ch24, 2),
            "ch4h":     round(ch4h, 2),
            "vol_ratio": round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0,
        }

    # 找资金费率信号
    opp_map = {o["coin"]: o for o in opps}

    return {
        "coins":     coin_data,
        "opp_map":   opp_map,
        "ts_utc":    datetime.utcnow().isoformat(),
    }


def agent_a_decide(mkt: dict, equity: float) -> dict:
    """
    Raw Claude 决策：简单动量 + 量价 + 资金费率反向
    无矛盾论、无记忆、无门禁
    """
    coins     = mkt["coins"]
    opp_map   = mkt["opp_map"]
    reasoning = []

    best_coin   = None
    best_score  = 0
    best_side   = "LONG"
    best_info   = {}

    for coin, d in coins.items():
        score = 0
        side  = "LONG"

        # 动量信号
        if d["ch24"] > 3 and d["ch4h"] > 1:
            score += 3; side = "LONG"
        elif d["ch24"] < -3 and d["ch4h"] < -1:
            score += 3; side = "SHORT"
        elif abs(d["ch24"]) > 1.5:
            score += 1; side = "LONG" if d["ch24"] > 0 else "SHORT"

        # 量价配合
        if d["vol_ratio"] > 1.5:
            score += 1

        # 资金费率极值（拥挤做反向）
        opp = opp_map.get(coin, {})
        if opp.get("funding_signal"):
            score += 2
            side = "SHORT" if opp.get("funding_dir") == "LONG" else "LONG"

        if score > best_score:
            best_score = score
            best_coin  = coin
            best_side  = side
            best_info  = d

    if best_score < 2 or best_coin is None:
        reasoning.append("全市场无明确信号，观望")
        return {"action": "HOLD", "coin": None, "confidence": 0.4,
                "reasoning_steps": reasoning, "position_size_usdt": 0}

    confidence = min(0.5 + best_score * 0.07, 0.85)
    # 软隔离：合约账户预算上限 BUDGET_USDC
    effective_equity = min(equity, BUDGET_USDC)
    pos_usdt = max(round(effective_equity * PER_TRADE_PCT, 2), 5.0)  # 最小 $5，名义 $15

    reasoning.append(f"扫描 {len(coins)} 个标的")
    reasoning.append(f"最优标的: {best_coin} score={best_score}")
    reasoning.append(f"方向: {best_side} | 24H={best_info['ch24']:+.1f}% 4H={best_info['ch4h']:+.1f}%")
    reasoning.append(f"量比: {best_info['vol_ratio']:.2f}x")
    reasoning.append(f"仓位: {pos_usdt} USDC × {LEVERAGE}x = {pos_usdt*LEVERAGE:.0f} 名义")

    px = best_info["price"]
    sl = round(px * (1 - STOP_LOSS_PCT) if best_side == "LONG" else px * (1 + STOP_LOSS_PCT), 2)
    tp = round(px * (1 + TP_PCT)        if best_side == "LONG" else px * (1 - TP_PCT),        2)

    return {
        "action":             best_side,
        "coin":               best_coin,
        "confidence":         round(confidence, 3),
        "reasoning_steps":    reasoning,
        "position_size_usdt": pos_usdt,
        "leverage":           LEVERAGE,
        "entry_price":        px,
        "stop_loss_price":    sl,
        "take_profit_price":  tp,
        "market_regime":      "TREND_UP" if best_side == "LONG" else "TREND_DOWN",
        "decision_rationale": f"{best_coin} {best_side} score={best_score} conf={confidence:.0%}",
    }


def run():
    cycle = _cycle_id()
    print(f"[Agent A] 启动 cycle={cycle}")

    client = HyperliquidClient("a")

    acct = client.get_account()
    if not acct["ok"]:
        print(f"[Agent A] 账户查询失败"); return
    equity = acct["equity"]
    print(f"[Agent A] 权益={equity:.2f} USDC  持仓={list(acct['positions'].keys())}")

    mkt      = fetch_market_context(client)
    decision = agent_a_decide(mkt, equity)

    print(f"[Agent A] 决策={decision['action']} coin={decision.get('coin')} "
          f"conf={decision['confidence']:.0%}")

    log = DecisionLog("a", cycle)
    log.data.update({
        "market_regime":       decision.get("market_regime", "UNKNOWN"),
        "reasoning_steps":     decision["reasoning_steps"],
        "confidence":          decision["confidence"],
        "action":              decision["action"],
        "entry_price":         decision.get("entry_price"),
        "position_size_usdt":  decision["position_size_usdt"],
        "stop_loss_price":     decision.get("stop_loss_price"),
        "take_profit_price":   decision.get("take_profit_price"),
        "decision_rationale":  decision.get("decision_rationale", ""),
        "system_features_used": [],
        "memory_loaded":       False,
        "coin":                decision.get("coin"),
        "leverage":            decision.get("leverage", LEVERAGE),
    })

    if AUTO_EXECUTE and decision["action"] != "HOLD" and decision["position_size_usdt"] > 0:
        coin = decision["coin"]
        lev  = decision.get("leverage", LEVERAGE)
        tag  = f"a_{cycle[:8]}"
        if decision["action"] == "LONG":
            result = client.open_long(coin, decision["position_size_usdt"], lev, tag)
        else:
            result = client.open_short(coin, decision["position_size_usdt"], lev, tag)
        log.data["execution"] = result
        print(f"[Agent A] 执行: {result.get('ok')} {result.get('filled')}")
    else:
        print(f"[Agent A] 跳过执行（AUTO_EXECUTE={AUTO_EXECUTE}）")

    path = log.save()
    print(f"[Agent A] 日志: {path}")

    # ── 自主调度：根据本轮信号决定下次触发时机 ──────────────────────────
    _self_schedule(decision, mkt)

    return log.data


def _self_schedule(decision: dict, mkt: dict):
    """Agent A 自主申请提前触发的逻辑"""
    import time as _t
    now = _t.time()
    action = decision.get("action", "HOLD")
    conf   = decision.get("confidence", 0.5)

    # 场景1：高置信度信号但资金不足/未入场 → 1H后复查
    if action != "HOLD" and conf >= 0.75:
        request_early_run(
            reason=f"A高置信度{conf:.0%}信号，1H后复查仓位",
            run_at_ts=now + 3600,
            priority="normal"
        )

    # 场景2：市场正在加速（量比 > 2x）→ 2H后复查
    for coin, d in mkt.get("coins", {}).items():
        if d.get("vol_ratio", 0) > 2.5:
            request_early_run(
                reason=f"{coin}成交量异常放大{d['vol_ratio']:.1f}x，2H后复查",
                run_at_ts=now + 7200,
                priority="normal"
            )
            break

    # 场景3：持有仓位且价格靠近止损 → 申请1H后监控
    # （持仓止损监控由 agent 主动申请，不依赖固定cron）


if __name__ == "__main__":
    run()
