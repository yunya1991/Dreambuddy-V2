#!/usr/bin/env python3
"""
Agent B Runner - DreamBuddy v2 交易决策
完整集成系统能力：
  A0 矛盾论 (7维矛盾识别) → A2 第一性原理 (阻力最小路径 + 趋势延续)
  → A3 大师研讨 (多视角辩论) → A7 置信度门禁 → 执行
  + 图架构上下文压缩(B/A/C三层) + 跨session记忆进化
"""
import os, sys, json, math, requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.aster_spot import HyperliquidClient, scan_opportunities, get_candles
from scoring.scorecard import DecisionLog, _cycle_id
from orchestrator import request_early_run

# ─── 配置 ───────────────────────────────────────────────────────────────────
AUTO_EXECUTE    = os.environ.get("AUTO_EXECUTE", "false").lower() == "true"
BUDGET_USDC     = 60.0        # 软隔离：现货账户预算上限
PER_TRADE_PCT   = float(os.environ.get("PER_TRADE_PCT", "0.05"))
STOP_LOSS_PCT   = 0.05        # 现货止损 5%（无杠杆）
TP_PCT          = 0.10        # 现货止盈 10%
CONFIDENCE_GATE = 0.65
UNIVERSE_B      = ["BTC", "ETH", "SOL", "HYPE", "AVAX"]  # 现货流动性好的5个

MEMORY_PATH = Path(__file__).parent.parent / "data" / "agent_b_memory.json"
GRAPH_LOG   = Path(__file__).parent.parent / "data" / "agent_b_graph.json"

# ─── 记忆层 ─────────────────────────────────────────────────────────────────

def load_memory() -> Dict:
    """加载跨session记忆：历史regime、教训、近期决策"""
    if not MEMORY_PATH.exists():
        return {
            "regime_history": [],
            "lessons": [],
            "recent_decisions": [],
            "win_streaks": 0,
            "loss_streaks": 0,
            "last_regime": None,
            "total_cycles": 0,
        }
    with open(MEMORY_PATH) as f:
        return json.load(f)

def save_memory(memory: Dict, decision: Dict, pnl_pct: Optional[float] = None):
    """将本次决策写回记忆，提炼教训"""
    memory["total_cycles"] = memory.get("total_cycles", 0) + 1
    memory["last_regime"] = decision.get("market_regime")

    # 保留最近20条决策
    recent = memory.get("recent_decisions", [])
    recent.append({
        "cycle_id":   decision.get("cycle_id"),
        "action":     decision.get("action"),
        "regime":     decision.get("market_regime"),
        "confidence": decision.get("confidence"),
        "pnl_pct":    pnl_pct,
        "ts":         datetime.utcnow().isoformat(),
    })
    memory["recent_decisions"] = recent[-20:]

    # 更新连胜/连败
    if pnl_pct is not None:
        if pnl_pct > 0:
            memory["win_streaks"]  = memory.get("win_streaks", 0) + 1
            memory["loss_streaks"] = 0
        else:
            memory["loss_streaks"] = memory.get("loss_streaks", 0) + 1
            memory["win_streaks"]  = 0

    # 提炼教训：连败3次 → 写入保守偏置教训
    if memory.get("loss_streaks", 0) >= 3:
        lesson = f"连败{memory['loss_streaks']}次，regime={memory['last_regime']}，提升置信度门槛至0.75"
        lessons = memory.get("lessons", [])
        if lesson not in lessons:
            lessons.append(lesson)
        memory["lessons"] = lessons[-10:]  # 保留最近10条教训

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def apply_lessons(memory: Dict) -> float:
    """根据教训动态调整置信度门槛"""
    gate = CONFIDENCE_GATE
    for lesson in memory.get("lessons", []):
        if "提升置信度门槛至" in lesson:
            try:
                gate = max(gate, float(lesson.split("至")[-1]))
            except ValueError:
                pass
    return gate

# ─── 市场数据采集 ────────────────────────────────────────────────────────────

def fetch_market_context(client: HyperliquidClient) -> Dict:
    """采集多维市场数据供A0/A2分析（Hyperliquid数据源）"""
    # Agent B 现货市场：只在 UNIVERSE_B 范围内选标的
    opps = client.scan_opportunities()
    mids = client.get_all_mids()

    # 主分析标的：UNIVERSE_B 内资金费率信号最强的
    primary_coin = "BTC"
    for o in sorted(opps, key=lambda x: abs(x["funding"]), reverse=True):
        if o["coin"] in UNIVERSE_B:
            primary_coin = o["coin"]
            break

    price = mids.get(primary_coin, mids.get("BTC", 0))

    candles_1h_raw = get_candles(primary_coin, "1h", 48, client.proxies)
    candles_4h_raw = get_candles(primary_coin, "4h", 14, client.proxies)

    closes_1h = [float(c["c"]) for c in candles_1h_raw if "c" in c]
    closes_4h = [float(c["c"]) for c in candles_4h_raw if "c" in c]
    vols_1h   = [float(c["v"]) for c in candles_1h_raw if "v" in c]

    # 扫描所有标的的机会
    opp_map = {o["coin"]: o for o in opps}

    # 技术指标计算
    def ema(prices, n):
        if len(prices) < n:
            return prices[-1] if prices else 0
        k = 2 / (n + 1)
        e = prices[-n]
        for p in prices[-n+1:]:
            e = p * k + e * (1 - k)
        return e

    def rsi(prices, n=14):
        if len(prices) < n + 1:
            return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains  = [max(d, 0) for d in deltas[-n:]]
        losses = [max(-d, 0) for d in deltas[-n:]]
        avg_g  = sum(gains) / n
        avg_l  = sum(losses) / n
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return 100 - 100 / (1 + rs)

    def atr(raw_candles, n=14):
        if len(raw_candles) < 2:
            return 0
        trs = []
        for i in range(1, min(n+1, len(raw_candles))):
            h = float(raw_candles[i].get("h", 0))
            l = float(raw_candles[i].get("l", 0))
            c_prev = float(raw_candles[i-1].get("c", 0))
            trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
        return sum(trs) / len(trs) if trs else 0

    ema20  = ema(closes_1h, 20)
    ema50  = ema(closes_1h, 50)
    ema200 = ema(closes_4h, 20)
    rsi14  = rsi(closes_1h)
    atr14  = atr(candles_1h_raw)

    change_1h  = ((closes_1h[0] - closes_1h[1])  / closes_1h[1]  * 100) if len(closes_1h) > 1  else 0
    change_24h = ((closes_1h[0] - closes_1h[23]) / closes_1h[23] * 100) if len(closes_1h) > 23 else 0
    change_4h  = ((closes_4h[0] - closes_4h[3])  / closes_4h[3]  * 100) if len(closes_4h) > 3  else 0

    avg_vol = sum(vols_1h) / len(vols_1h) if vols_1h else 0
    cur_vol = vols_1h[0] if vols_1h else 0

    # 从 Hyperliquid 获取资金费率
    funding_rate = opp_map.get(primary_coin, {}).get("funding", 0.0)

    return {
        "price":        price,
        "coin":         primary_coin,
        "opp_map":      opp_map,
        "change_1h":    round(change_1h, 3),
        "change_4h":    round(change_4h, 3),
        "change_24h":   round(change_24h, 3),
        "ema20":        round(ema20, 2), "ema50": round(ema50, 2), "ema200": round(ema200, 2),
        "rsi14":        round(rsi14, 1),
        "atr14":        round(atr14, 2),
        "vol_ratio":    round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0,
        "funding_rate": funding_rate,
        "closes_1h":    closes_1h[:8],
        "ts_utc": datetime.utcnow().isoformat(),
    }

# ─── A0 矛盾论 ──────────────────────────────────────────────────────────────

def a0_contradiction_analysis(mkt: Dict, memory: Dict) -> Dict:
    """
    A0: 7维矛盾识别（C1-C7）
    每个维度识别多方力量 vs 空方力量，评出主导方和强度
    返回主要矛盾和矛盾清单
    """
    price  = mkt["price"]
    ema20  = mkt["ema20"]
    ema50  = mkt["ema50"]
    ema200 = mkt["ema200"]
    rsi14  = mkt["rsi14"]
    fr     = mkt["funding_rate"]
    ch24   = mkt["change_24h"]
    ch1h   = mkt["change_1h"]
    vr     = mkt["vol_ratio"]

    contradictions = []

    # C1 资金面矛盾（用资金费率代理OI方向）
    c1_bull = "资金费率正向" if fr > 0.0001 else ""
    c1_bear = "资金费率负向(空头拥挤)" if fr < -0.0001 else ""
    c1_dom  = "A" if fr > 0.0001 else ("B" if fr < -0.0001 else "EQUAL")
    contradictions.append({
        "dim": "C1", "name": "资金面",
        "bull": c1_bull or "资金费率中性", "bear": c1_bear or "资金费率中性",
        "dominance": c1_dom, "strength": abs(fr) * 10000,
    })

    # C2 情绪面矛盾（RSI代理）
    if rsi14 > 65:
        c2_dom, c2_bull, c2_bear = "A", f"RSI超买{rsi14:.0f}，多头情绪亢奋", "超买反转风险"
    elif rsi14 < 35:
        c2_dom, c2_bull, c2_bear = "B", "超卖反弹预期", f"RSI超卖{rsi14:.0f}，空头情绪主导"
    else:
        c2_dom, c2_bull, c2_bear = "EQUAL", f"RSI中性{rsi14:.0f}", f"RSI中性{rsi14:.0f}"
    contradictions.append({
        "dim": "C2", "name": "情绪面",
        "bull": c2_bull, "bear": c2_bear,
        "dominance": c2_dom, "strength": abs(rsi14 - 50) / 50,
    })

    # C3 技术面矛盾（EMA排列）
    ema_bull = price > ema20 > ema50
    ema_bear = price < ema20 < ema50
    above_200 = price > ema200
    if ema_bull and above_200:
        c3_dom = "A"; c3_str = 0.85
        c3_bull = f"EMA多头排列，价格>{ema200:.0f}(MA200代理)"
        c3_bear = "短期回调可能"
    elif ema_bear and not above_200:
        c3_dom = "B"; c3_str = 0.85
        c3_bull = "低位超卖反弹预期"
        c3_bear = f"EMA空头排列，价格<MA200({ema200:.0f})"
    elif above_200:
        c3_dom = "A"; c3_str = 0.55
        c3_bull = f"价格在MA200上方，中期结构看多"
        c3_bear = "EMA排列混乱，短期方向不清"
    else:
        c3_dom = "B"; c3_str = 0.55
        c3_bull = "短期技术超卖"
        c3_bear = "价格在MA200下方，中期压力大"
    contradictions.append({
        "dim": "C3", "name": "技术面",
        "bull": c3_bull, "bear": c3_bear,
        "dominance": c3_dom, "strength": c3_str,
    })

    # C6 时序矛盾（1H vs 24H方向冲突）
    if ch1h * ch24 < 0:  # 方向相反
        c6_dom = "CONFLICT"
        c6_bull = f"1H {'+' if ch1h>0 else ''}{ch1h:.2f}%"
        c6_bear = f"24H {'+' if ch24>0 else ''}{ch24:.2f}%（方向相反）"
        c6_str  = 0.8
    else:
        c6_dom  = "A" if ch24 > 0 else "B"
        c6_bull = f"短长周期方向一致，1H{ch1h:+.2f}%/24H{ch24:+.2f}%"
        c6_bear = "无时序冲突"
        c6_str  = min(abs(ch24) / 5, 1.0)
    contradictions.append({
        "dim": "C6", "name": "时序",
        "bull": c6_bull if ch24 > 0 else c6_bear,
        "bear": c6_bear if ch24 > 0 else c6_bull,
        "dominance": c6_dom, "strength": c6_str,
    })

    # C7 量价矛盾（成交量验证）
    if vr > 1.5 and ch1h > 0:
        c7_dom = "A"; c7_bull = f"量价配合，成交量{vr:.1f}x放大+价格上涨"
        c7_bear = "量能需持续"; c7_str = 0.75
    elif vr > 1.5 and ch1h < 0:
        c7_dom = "B"; c7_bear = f"放量下跌，成交量{vr:.1f}x+价格下跌"
        c7_bull = "恐慌性下跌可能接近尾声"; c7_str = 0.75
    elif vr < 0.6:
        c7_dom = "EQUAL"; c7_bull = "缩量"; c7_bear = f"成交量萎缩{vr:.1f}x，动能不足"
        c7_str = 0.3
    else:
        c7_dom = "EQUAL"; c7_bull = "量价中性"; c7_bear = "量价中性"; c7_str = 0.4
    contradictions.append({
        "dim": "C7", "name": "量价",
        "bull": c7_bull, "bear": c7_bear,
        "dominance": c7_dom, "strength": c7_str,
    })

    # 识别主要矛盾：取强度最高且非EQUAL/CONFLICT的
    primary = None
    for c in sorted(contradictions, key=lambda x: x["strength"], reverse=True):
        if c["dominance"] not in ("EQUAL", "CONFLICT"):
            primary = c
            break
    if primary is None:
        primary = contradictions[0]

    # 多空力量汇总
    bull_count = sum(1 for c in contradictions if c["dominance"] == "A")
    bear_count = sum(1 for c in contradictions if c["dominance"] == "B")
    conflict   = sum(1 for c in contradictions if c["dominance"] == "CONFLICT")

    return {
        "contradictions": contradictions,
        "primary_contradiction": primary,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "conflict_count": conflict,
        "dominant_force": "BULL" if bull_count > bear_count else ("BEAR" if bear_count > bull_count else "NEUTRAL"),
    }

# ─── A2 第一性原理 ────────────────────────────────────────────────────────────

def a2_first_principles(mkt: Dict, a0: Dict) -> Dict:
    """
    A2: 第一性原理分析
    原理1: 阻力最小路径 — 市场总沿阻力最小方向运行
    原理2: 趋势延续性  — 趋势延续直到遇到足够反向阻力
    """
    price   = mkt["price"]
    atr     = mkt["atr14"]
    ch24    = mkt["change_24h"]
    ch4h    = mkt["change_4h"]
    ema20   = mkt["ema20"]
    ema50   = mkt["ema50"]
    ema200  = mkt["ema200"]
    rsi14   = mkt["rsi14"]
    dom     = a0["dominant_force"]

    reasoning = []

    # 原理1: 阻力分析
    reasoning.append(f"【原理1: 阻力最小路径】")
    resistance_up   = []
    resistance_down = []

    if price < ema20:
        resistance_up.append(f"EMA20={ema20:.0f}(+{(ema20-price)/price*100:.1f}%)压制")
    if price < ema50:
        resistance_up.append(f"EMA50={ema50:.0f}(+{(ema50-price)/price*100:.1f}%)压制")
    if price < ema200:
        resistance_up.append(f"MA200代理={ema200:.0f}(+{(ema200-price)/price*100:.1f}%)强压")
    if rsi14 > 70:
        resistance_up.append(f"RSI={rsi14:.0f}超买，上涨阻力大")

    if price > ema20:
        resistance_down.append(f"EMA20={ema20:.0f}支撑")
    if price > ema50:
        resistance_down.append(f"EMA50={ema50:.0f}支撑")
    if price > ema200:
        resistance_down.append(f"MA200代理={ema200:.0f}强支撑")
    if rsi14 < 30:
        resistance_down.append(f"RSI={rsi14:.0f}超卖，下跌阻力大")

    least_resistance = "UP" if len(resistance_up) < len(resistance_down) else \
                       ("DOWN" if len(resistance_down) < len(resistance_up) else "NEUTRAL")
    reasoning.append(f"上行阻力: {'; '.join(resistance_up) or '小'}")
    reasoning.append(f"下行阻力: {'; '.join(resistance_down) or '小'}")
    reasoning.append(f"阻力最小方向: {least_resistance}")

    # 原理2: 趋势延续
    reasoning.append(f"【原理2: 趋势延续性】")
    if ch24 > 3 and ch4h > 1 and price > ema20:
        trend = "STRONG_UP"; trend_score = 0.85
        reasoning.append(f"24H涨{ch24:.1f}%+4H涨{ch4h:.1f}%+价格>EMA20，上升趋势强劲")
    elif ch24 > 1 and price > ema50:
        trend = "WEAK_UP"; trend_score = 0.6
        reasoning.append(f"24H涨{ch24:.1f}%，趋势偏多但动能一般")
    elif ch24 < -3 and ch4h < -1 and price < ema20:
        trend = "STRONG_DOWN"; trend_score = 0.15
        reasoning.append(f"24H跌{abs(ch24):.1f}%+4H跌{abs(ch4h):.1f}%+价格<EMA20，下降趋势强劲")
    elif ch24 < -1 and price < ema50:
        trend = "WEAK_DOWN"; trend_score = 0.35
        reasoning.append(f"24H跌{abs(ch24):.1f}%，趋势偏空但动能一般")
    else:
        trend = "RANGE"; trend_score = 0.5
        reasoning.append(f"24H变动{ch24:+.1f}%，处于震荡区间")

    # ATR波动度
    atr_pct = atr / price * 100
    reasoning.append(f"ATR波动率: {atr_pct:.2f}%（单次预期波幅）")

    # 综合A0矛盾分析
    reasoning.append(f"【矛盾论验证】主力方向: {dom}，与趋势方向{'一致' if (dom=='BULL')==(trend_score>0.5) else '冲突⚠️'}")

    # 置信度合成
    if least_resistance == "UP" and trend in ("STRONG_UP", "WEAK_UP") and dom == "BULL":
        confidence = 0.72 + min(trend_score * 0.1, 0.12)
        direction  = "BUY"
    elif least_resistance == "DOWN" and trend in ("STRONG_DOWN", "WEAK_DOWN") and dom == "BEAR":
        confidence = 0.72 + min((1 - trend_score) * 0.1, 0.12)
        direction  = "SELL"
    elif least_resistance == "UP" and dom == "BULL":
        confidence = 0.62; direction = "BUY"
    elif least_resistance == "DOWN" and dom == "BEAR":
        confidence = 0.62; direction = "SELL"
    elif dom == "NEUTRAL" or least_resistance == "NEUTRAL":
        confidence = 0.45; direction = "HOLD"
    else:
        # 矛盾信号冲突，降低置信度
        confidence = 0.50; direction = "HOLD"
        reasoning.append("矛盾信号冲突，建议观望")

    return {
        "direction": direction,
        "confidence": round(confidence, 3),
        "least_resistance": least_resistance,
        "trend": trend,
        "trend_score": trend_score,
        "resistance_up": resistance_up,
        "resistance_down": resistance_down,
        "reasoning": reasoning,
        "atr_pct": round(atr_pct, 3),
    }

# ─── A3 大师研讨（简化版三视角辩论）───────────────────────────────────────────

def a3_master_seminar(mkt: Dict, a0: Dict, a2: Dict) -> Dict:
    """
    A3: 多视角辩论（趋势派 vs 均值回归派 vs 风险派）
    三方各给出评分0-10，加权计算最终置信度修正
    """
    price    = mkt["price"]
    rsi      = mkt["rsi14"]
    ch24     = mkt["change_24h"]
    dom      = a0["dominant_force"]
    trend    = a2["trend"]
    a2_dir   = a2["direction"]
    a2_conf  = a2["confidence"]
    bull_cnt = a0["bull_count"]
    bear_cnt = a0["bear_count"]

    opinions = []

    # 大师1: 趋势追踪者（Jesse Livermore风格）
    if trend in ("STRONG_UP",) and dom == "BULL":
        m1_score = 8; m1_vote = "BUY"
        m1_reason = f"趋势强劲，顺势而为。{bull_cnt}维多，做多是顺势"
    elif trend in ("STRONG_DOWN",) and dom == "BEAR":
        m1_score = 8; m1_vote = "SELL"
        m1_reason = f"空头趋势延续，{bear_cnt}维空，做空是顺势"
    elif trend in ("WEAK_UP", "WEAK_DOWN"):
        m1_score = 5; m1_vote = a2_dir
        m1_reason = "趋势偏弱，仓位不宜过重"
    else:
        m1_score = 3; m1_vote = "HOLD"
        m1_reason = "无明确趋势，不轻易入场"
    opinions.append({"master": "趋势派(Livermore)", "vote": m1_vote,
                     "score": m1_score, "reason": m1_reason})

    # 大师2: 均值回归者（Simons量化风格）
    if rsi > 72 and ch24 > 5:
        m2_score = 7; m2_vote = "SELL"
        m2_reason = f"RSI={rsi:.0f}+24H涨{ch24:.1f}%，均值回归压力大"
    elif rsi < 28 and ch24 < -5:
        m2_score = 7; m2_vote = "BUY"
        m2_reason = f"RSI={rsi:.0f}+24H跌{abs(ch24):.1f}%，超卖反弹概率高"
    elif a2_dir == "BUY" and rsi < 60:
        m2_score = 6; m2_vote = "BUY"
        m2_reason = f"RSI={rsi:.0f}未超买，做多空间充足"
    elif a2_dir == "SELL" and rsi > 40:
        m2_score = 6; m2_vote = "SELL"
        m2_reason = f"RSI={rsi:.0f}未超卖，做空空间充足"
    else:
        m2_score = 4; m2_vote = "HOLD"
        m2_reason = "均值回归信号中性"
    opinions.append({"master": "量化派(Simons)", "vote": m2_vote,
                     "score": m2_score, "reason": m2_reason})

    # 大师3: 风险管理者（Dalio风格）
    conflict_cnt = a0["conflict_count"]
    if conflict_cnt >= 2:
        m3_score = 2; m3_vote = "HOLD"
        m3_reason = f"{conflict_cnt}个维度信号冲突，风险不对称，建议观望"
    elif a2_conf > 0.70 and bull_cnt + bear_cnt >= 3:
        m3_score = 7; m3_vote = a2_dir
        m3_reason = f"多维印证({bull_cnt+bear_cnt}个维度同向)，风险可控"
    elif a2_conf < 0.60:
        m3_score = 3; m3_vote = "HOLD"
        m3_reason = f"置信度{a2_conf:.0%}偏低，仓位过重风险大"
    else:
        m3_score = 5; m3_vote = a2_dir
        m3_reason = "风险中性，可以小仓参与"
    opinions.append({"master": "风险派(Dalio)", "vote": m3_vote,
                     "score": m3_score, "reason": m3_reason})

    # 投票结果
    buy_votes  = sum(1 for o in opinions if o["vote"] == "BUY")
    sell_votes = sum(1 for o in opinions if o["vote"] == "SELL")
    hold_votes = sum(1 for o in opinions if o["vote"] == "HOLD")
    avg_score  = sum(o["score"] for o in opinions) / len(opinions)

    if buy_votes >= 2:
        seminar_verdict = "BUY"
    elif sell_votes >= 2:
        seminar_verdict = "SELL"
    else:
        seminar_verdict = "HOLD"

    # 置信度修正：大师共识 → 加成；分歧 → 折扣
    if buy_votes == 3 or sell_votes == 3:
        conf_adj = +0.08   # 三票同向，强烈加成
    elif hold_votes >= 2:
        conf_adj = -0.12   # 多数观望，大幅折扣
    elif buy_votes == 2 or sell_votes == 2:
        conf_adj = +0.03
    else:
        conf_adj = -0.05

    return {
        "opinions": opinions,
        "verdict": seminar_verdict,
        "buy_votes": buy_votes, "sell_votes": sell_votes, "hold_votes": hold_votes,
        "avg_score": round(avg_score, 1),
        "confidence_adj": conf_adj,
    }

# ─── A7 置信度门禁 ───────────────────────────────────────────────────────────

def a7_gate(final_confidence: float, action: str, gate: float,
            memory: Dict) -> tuple[bool, str]:
    """
    A7 实践论门禁
    检查置信度、连败保护、信号一致性
    返回 (pass, reason)
    """
    if action == "HOLD":
        return False, "HOLD信号，不入场"

    if final_confidence < gate:
        return False, f"置信度{final_confidence:.0%} < 门槛{gate:.0%}，未过A7门禁"

    # 连败保护：连败3次后暂停一轮
    if memory.get("loss_streaks", 0) >= 3:
        loss_n = memory["loss_streaks"]
        return False, f"连败保护：已连败{loss_n}次，本轮强制观望"

    return True, "A7门禁通过"

# ─── 图上下文压缩记录 ─────────────────────────────────────────────────────────

def record_graph_context(cycle_id: str, a0: Dict, a2: Dict, a3: Dict,
                         final: Dict, memory: Dict):
    """
    记录B/A/C三层图节点（简化版，用于跨session上下文传递）
    B层=本轮目标, A层=A0/A2/A3执行步骤, C层=最终决策记录
    """
    existing = []
    if GRAPH_LOG.exists():
        with open(GRAPH_LOG) as f:
            existing = json.load(f)

    graph_entry = {
        "cycle_id": cycle_id,
        "ts": datetime.utcnow().isoformat(),
        "B_layer": {
            "objective": f"BTC现货交易 cycle={cycle_id}",
            "regime": final.get("market_regime"),
        },
        "A_layer": [
            {"node": "A0", "dominant_force": a0["dominant_force"],
             "primary_contradiction": a0["primary_contradiction"]["dim"],
             "bull_count": a0["bull_count"], "bear_count": a0["bear_count"]},
            {"node": "A2", "direction": a2["direction"],
             "confidence": a2["confidence"], "trend": a2["trend"],
             "least_resistance": a2["least_resistance"]},
            {"node": "A3", "verdict": a3["verdict"],
             "votes": f"B{a3['buy_votes']}S{a3['sell_votes']}H{a3['hold_votes']}",
             "conf_adj": a3["confidence_adj"]},
        ],
        "C_layer": {
            "action": final.get("action"),
            "confidence": final.get("confidence"),
            "gate_passed": final.get("gate_passed"),
            "position_size_usdt": final.get("position_size_usdt"),
        },
        "memory_context": {
            "lessons_applied": memory.get("lessons", [])[-2:],
            "last_regime": memory.get("last_regime"),
            "loss_streaks": memory.get("loss_streaks", 0),
        },
    }

    existing.append(graph_entry)
    # 保留最近50条
    existing = existing[-50:]

    GRAPH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH_LOG, "w") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return len(a0["contradictions"]) + 3  # 矛盾节点 + A层节点数

# ─── 主流程 ──────────────────────────────────────────────────────────────────

def run():
    cycle = _cycle_id()
    print(f"[Agent B] 启动 cycle={cycle}")

    # 加载记忆
    memory  = load_memory()
    gate    = apply_lessons(memory)
    lessons = memory.get("lessons", [])
    print(f"[Agent B] 记忆加载: {memory['total_cycles']}轮历史, {len(lessons)}条教训, "
          f"连败={memory.get('loss_streaks',0)}, 门槛={gate:.0%}")

    client = HyperliquidClient("b")

    # 软隔离：Agent B 用现货账户，取现货 USDC 余额
    spot_bal = client.get_spot_balance()
    usdc_avail = spot_bal.get("usdc_avail", 0)
    equity = min(usdc_avail, BUDGET_USDC)   # 上限 60 USDC
    print(f"[Agent B] 现货USDC={usdc_avail:.2f}  可用预算={equity:.2f}  "
          f"持仓={list(spot_bal.get('balances', {}).keys())}")

    mkt = fetch_market_context(client)
    print(f"[Agent B] 主标的={mkt['coin']} price={mkt['price']:.2f}, "
          f"24H={mkt['change_24h']:+.1f}%, RSI={mkt['rsi14']}, EMA20={mkt['ema20']:.2f}")

    # ── A0 矛盾论 ───────────────────────────────────────────────────────────
    a0 = a0_contradiction_analysis(mkt, memory)
    print(f"[Agent B/A0] 主要矛盾={a0['primary_contradiction']['dim']}({a0['primary_contradiction']['name']}), "
          f"多:{a0['bull_count']} 空:{a0['bear_count']} 冲突:{a0['conflict_count']}")

    # ── A2 第一性原理 ────────────────────────────────────────────────────────
    a2 = a2_first_principles(mkt, a0)
    print(f"[Agent B/A2] 方向={a2['direction']}, 置信度={a2['confidence']:.0%}, "
          f"阻力最小={a2['least_resistance']}, 趋势={a2['trend']}")

    # ── A3 大师研讨 ──────────────────────────────────────────────────────────
    a3 = a3_master_seminar(mkt, a0, a2)
    print(f"[Agent B/A3] 裁决={a3['verdict']}, 投票=多{a3['buy_votes']}/空{a3['sell_votes']}/观望{a3['hold_votes']}, "
          f"置信度修正{a3['confidence_adj']:+.0%}")

    # ── 综合置信度 ────────────────────────────────────────────────────────────
    raw_action    = a3["verdict"] if a3["verdict"] != "HOLD" else a2["direction"]
    final_conf    = round(min(max(a2["confidence"] + a3["confidence_adj"], 0), 1), 3)

    # ── A7 门禁 ───────────────────────────────────────────────────────────────
    gate_pass, gate_reason = a7_gate(final_conf, raw_action, gate, memory)
    action = raw_action if gate_pass else "HOLD"
    print(f"[Agent B/A7] {'✅ 通过' if gate_pass else '❌ 拦截'}: {gate_reason}")

    # ── 仓位计算（现货，无杠杆）──────────────────────────────────────────────
    position_size_usdt = round(equity * PER_TRADE_PCT, 2) if gate_pass else 0
    price = mkt["price"]
    coin  = mkt.get("coin", "BTC")

    # 现货只做 BUY/HOLD（无做空），若 A2 判断 SELL 则转为 HOLD
    is_buy   = action in ("BUY", "LONG")
    is_sell  = action in ("SELL", "SHORT")

    # A0多标的：UNIVERSE_B 内资金费率信号最强且方向一致时切换标的
    opp_map  = mkt.get("opp_map", {})
    for o in sorted(opp_map.values(), key=lambda x: abs(x["funding"]), reverse=True):
        if o.get("coin") in UNIVERSE_B and o["coin"] != coin and o.get("funding_signal"):
            alt_side = "BUY" if o["funding_dir"] == "SHORT" else "SELL"
            if is_buy and alt_side == "BUY":
                coin = o["coin"]; price = o["price"]
                break

    sl_price = round(price * (1 - STOP_LOSS_PCT), 2) if is_buy else None
    tp_price = round(price * (1 + TP_PCT), 2)        if is_buy else None

    final = {
        "action":             "BUY" if is_buy else ("SELL" if is_sell else "HOLD"),
        "coin":               coin,
        "leverage":           1,      # 现货无杠杆
        "confidence":         final_conf,
        "position_size_usdt": position_size_usdt if is_buy else 0,
        "entry_price":        price,
        "stop_loss_price":    sl_price,
        "take_profit_price":  tp_price,
        "market_regime": (
            "TREND_UP"   if a2["trend"] in ("STRONG_UP", "WEAK_UP") else
            "TREND_DOWN" if a2["trend"] in ("STRONG_DOWN", "WEAK_DOWN") else "RANGE"
        ),
        "gate_passed": gate_pass,
        "cycle_id":    cycle,
    }

    # ── 图上下文压缩记录 ──────────────────────────────────────────────────────
    graph_nodes = record_graph_context(cycle, a0, a2, a3, final, memory)
    print(f"[Agent B] 图节点已记录: {graph_nodes} nodes")

    # ── 写决策日志 ────────────────────────────────────────────────────────────
    log = DecisionLog("b", cycle)
    log.data.update({
        "market_regime":         final["market_regime"],
        "key_contradictions":    [
            f"{c['dim']}({c['name']}): {c['dominance']}" for c in a0["contradictions"]
        ],
        "reasoning_steps": (
            [f"A0: {a0['dominant_force']} 多{a0['bull_count']}空{a0['bear_count']}"]
            + [f"A0_{c['dim']}: {c['bull'] if c['dominance']=='A' else c['bear']}"
               for c in a0["contradictions"]]
            + a2["reasoning"]
            + [f"A3_{o['master']}: {o['vote']} ({o['score']}/10) {o['reason']}"
               for o in a3["opinions"]]
            + [f"A7门禁: {gate_reason}"]
        ),
        "confidence":           final_conf,
        "supporting_evidence":  [
            f"标的: {coin}  杠杆: 1x(现货)",
            f"EMA排列: {mkt['ema20']:.2f}/{mkt['ema50']:.2f}/{mkt['ema200']:.2f}",
            f"RSI14={mkt['rsi14']:.1f}, ATR={mkt['atr14']:.4f}",
            f"资金费率={mkt['funding_rate']:.6f}",
        ],
        "action":               action,
        "coin":                 coin,
        "leverage":             1,
        "entry_price":          price,
        "position_size_usdt":   position_size_usdt,
        "stop_loss_price":      final["stop_loss_price"],
        "take_profit_price":    final["take_profit_price"],
        "decision_rationale":   gate_reason if not gate_pass else
                                f"{coin} {a2['direction']} 1x(现货), {a3['verdict']}裁决, conf={final_conf:.0%}",
        "system_features_used": ["A0_contradiction", "A2_first_principles",
                                 "A3_master_seminar", "A7_gate", "graph_compression", "memory"],
        "graph_context_nodes":  graph_nodes,
        "memory_loaded":        True,
        "prior_lessons_applied": lessons[-2:],
    })

    # ── 执行（现货买入，无杠杆）──────────────────────────────────────────────
    exec_action = final["action"]
    if AUTO_EXECUTE and gate_pass and final["position_size_usdt"] > 0:
        tag = f"b_{cycle[:8]}"
        if exec_action == "BUY":
            exec_result = client.spot_market_buy(coin, final["position_size_usdt"], tag)
        elif exec_action == "SELL":
            # 现货卖出：卖出持仓的 coin
            bal  = client.get_spot_balance()
            held = bal["balances"].get(coin, {}).get("avail", 0)
            sell_sz = round(held * PER_TRADE_PCT, 6)
            exec_result = client.spot_market_sell(coin, sell_sz, tag) if sell_sz > 0 \
                else {"ok": False, "error": "no_spot_holdings"}
        else:
            exec_result = {"ok": False, "error": "HOLD"}
        log.data["execution"] = exec_result
        print(f"[Agent B] 执行: ok={exec_result.get('ok')} {exec_result.get('filled')}")
    else:
        print(f"[Agent B] 跳过执行（AUTO_EXECUTE={AUTO_EXECUTE}, gate={gate_pass}）")

    path = log.save()
    print(f"[Agent B] 日志已保存: {path}")

    # ── 更新记忆（本轮pnl留空，等结算脚本回填）───────────────────────────────
    save_memory(memory, log.data)

    # ── 自主调度：根据系统信号决定下次触发时机 ──────────────────────────
    _b_self_schedule(final, a0, a2, memory)

    return log.data


def _b_self_schedule(final: dict, a0: dict, a2: dict, memory: dict):
    """Agent B 自主申请提前触发——基于矛盾论 + 置信度 + 记忆"""
    import time as _t
    now = _t.time()

    # 场景1：主要矛盾转化信号（C类信号冲突突然减少）→ 2H后复查
    conflict_cnt = a0.get("conflict_count", 0)
    bull_cnt     = a0.get("bull_count", 0)
    bear_cnt     = a0.get("bear_count", 0)
    if conflict_cnt == 0 and abs(bull_cnt - bear_cnt) >= 3:
        dominant = "多" if bull_cnt > bear_cnt else "空"
        request_early_run(
            reason=f"B矛盾清晰：{dominant}头主导{max(bull_cnt,bear_cnt)}维，2H后入场机会",
            run_at_ts=now + 7200,
            priority="normal"
        )

    # 场景2：A2 判断阻力最小方向 UP 但置信度刚好在门槛附近（60-65%）→ 1H后再试
    conf = final.get("confidence", 0)
    if 0.58 <= conf < 0.65 and a2.get("least_resistance") == "UP":
        request_early_run(
            reason=f"B置信度{conf:.0%}接近门槛，1H后市场可能更清晰",
            run_at_ts=now + 3600,
            priority="normal"
        )

    # 场景3：连败保护解除后首次复盘 → 申请6H后重新尝试
    loss_streaks = memory.get("loss_streaks", 0)
    if loss_streaks == 3:
        request_early_run(
            reason="B连败保护触发，6H后强制复盘评估市场",
            run_at_ts=now + 21600,
            priority="urgent"
        )


if __name__ == "__main__":
    run()
