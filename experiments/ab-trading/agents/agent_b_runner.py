#!/usr/bin/env python3
"""
Agent B Runner - Dreambuddy OS v1.0 系统架构验证实验
========================================================

定位： Dreambuddy OS 的验证实验组
      通过执行 dreambuddy-os SKILL（1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md）
      验证整个系统架构设计的可行性和效果

工作流：
  意图识别 → BAC三层架构规划 → 动态执行 → 自我进化 → D-Z-E开发链

核心能力调用（按 SKILL 定义）：
  - 意图识别：core/intent_gateway.py
  - BAC三层：core/chain_planner.py + core/chain_router.py
  - 执行层：execution/aster_spot.py
  - 自我进化：core/evolution_engine.py（gap_score + A7/A8 + 做梦部）
  - D-Z-E：3-CHAIN-DEVELOPMENT/scripts/chain_guard.py

与 Agent A 的对比：
  Agent A = LLM 驱动实战交易（对照实验）
  Agent B = Dreambuddy OS 架构验证（实验组）
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
from core.exit_module import (
    run_exit_check, init_position, update_position_exit_levels,
    check_classical_indicator_exits, check_l3_classical_exits_api, execute_exit,
)
from core.classic_driver import ClassicDriver, should_use_classic_driver
from core.trading_memory import TradingMemory

# ─── 配置 ───────────────────────────────────────────────────────────────────
AUTO_EXECUTE    = os.environ.get("AUTO_EXECUTE", "false").lower() == "true"
BUDGET_USDC     = 60.0        # 子账户预算（合约）
PER_TRADE_PCT   = float(os.environ.get("PER_TRADE_PCT", "0.05"))
STOP_LOSS_PCT   = 0.04        # 合约止损 4%
TP_PCT          = 0.08        # 合约止盈 8%
CONFIDENCE_GATE = 0.65
MAX_LEVERAGE    = 5
DEFAULT_LEVERAGE = 3
# Agent B 用合约，可交易全部标的池（与 A 相同，但决策框架不同）
UNIVERSE_B = ["BTC", "ETH", "HYPE", "UNI", "LIT", "SOL", "XRP", "ZEC", "NEAR", "WLD", "ADA", "SUI", "ETHFI", "ENA", "JUP", "XLM", "GRASS", "EIGEN", "ZRO", "IMX"]

MEMORY_PATH = Path(__file__).parent.parent / "data" / "agent_b_memory.json"
GRAPH_LOG   = Path(__file__).parent.parent / "data" / "agent_b_graph.json"

# Dreambuddy OS SKILL 路径（系统级 SKILL 内核）
DREAMBUDDY_OS_SKILL = Path(__file__).parent.parent.parent.parent / "1-ARCHITECTURE" / "skills" / "dreambuddy-os" / "SKILL.md"

# D-Z-E 开发链路径
CHAIN_DEV_SCRIPTS = Path(__file__).parent.parent.parent.parent / "3-CHAIN-DEVELOPMENT" / "scripts"

# PR 评论配置
GH_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
PR_NUMBER = "52"

# ─── 记忆层 ─────────────────────────────────────────────────────────────────

def load_memory() -> Dict:
    """加载跨session记忆：历史regime、教训、近期决策、上轮PR建议"""
    if not MEMORY_PATH.exists():
        return {
            "regime_history": [],
            "lessons": [],
            "recent_decisions": [],
            "win_streaks": 0,
            "loss_streaks": 0,
            "last_regime": None,
            "total_cycles": 0,
            "active_positions": {},
            "prior_cycle_suggestions": {},
            "next_cycle_suggestions": {},
        }
    with open(MEMORY_PATH) as f:
        mem = json.load(f)
    if "active_positions" not in mem:
        mem["active_positions"] = {}
    if "prior_cycle_suggestions" not in mem:
        mem["prior_cycle_suggestions"] = {}
    if "next_cycle_suggestions" not in mem:
        mem["next_cycle_suggestions"] = {}
    return mem

def normalize_action(action: Optional[str]) -> str:
    """标准化 action 命名：统一为 LONG/SHORT/HOLD"""
    if not action:
        return "HOLD"
    action_upper = action.upper()
    if action_upper in ("BUY", "LONG", "LONG_BUY"):
        return "LONG"
    if action_upper in ("SELL", "SHORT", "SHORT_SELL"):
        return "SHORT"
    if action_upper in ("HOLD", "HOLD_WAIT", "WAIT", "NONE"):
        return "HOLD"
    return action_upper


def save_memory(memory: Dict, decision: Dict, pnl_pct: Optional[float] = None,
                next_suggestions: Optional[Dict] = None):
    """将本次决策写回记忆，提炼教训，保存下轮建议"""
    memory["total_cycles"] = memory.get("total_cycles", 0) + 1
    memory["last_regime"] = decision.get("market_regime")

    # 保留最近20条决策
    recent = memory.get("recent_decisions", [])
    recent.append({
        "cycle_id":   decision.get("cycle_id"),
        "action":     normalize_action(decision.get("action")),
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

    # 保存下轮建议到 suggestion_loop（交易记忆闭环核心结构）
    if next_suggestions:
        if "suggestion_loop" not in memory:
            memory["suggestion_loop"] = {}
        memory["suggestion_loop"]["next_cycle_suggestions"] = next_suggestions
        # 同时提升为下一轮的 prior_cycle_suggestions
        memory["suggestion_loop"]["prior_cycle_suggestions"] = next_suggestions
        # 兼容旧字段（保持向后兼容）
        memory["prior_cycle_suggestions"] = next_suggestions
        memory["next_cycle_suggestions"] = next_suggestions

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

def _score_coin(price: float, ch24: float, ch1h: float, vol_ratio: float,
                rsi: float, funding_rate: float, ema20: float,
                ema50: float, ema200: float) -> Dict:
    """
    快速扫描评分（0-100分）：评估币种的交易机会强度
    维度：趋势强度(30%) + 动量(20%) + 量能(15%) + 资金费率(15%) + RSI位置(10%) + EMA排列(10%)
    """
    score = 0.0
    signals = []

    # 1. 趋势强度（24h涨跌幅绝对值，越大趋势越强）
    trend_abs = min(abs(ch24) / 8.0, 1.0)
    score += trend_abs * 30
    if ch24 > 3:
        signals.append("强上涨趋势")
    elif ch24 < -3:
        signals.append("强下跌趋势")

    # 2. 动量（1h与24h方向一致性，确认趋势延续）
    if ch24 > 0 and ch1h > 0:
        score += 15
        signals.append("短长共振上涨")
    elif ch24 < 0 and ch1h < 0:
        score += 15
        signals.append("短长共振下跌")
    elif abs(ch1h) > 1.5:
        score += 5

    # 3. 量能（成交量放大 = 趋势确认/反转信号）
    if vol_ratio > 2.0:
        score += 15
        signals.append(f"放量{vol_ratio:.1f}x")
    elif vol_ratio > 1.3:
        score += 8

    # 4. 资金费率偏离（极端负费率 = 空头拥挤/潜在轧空，极端正费率 = 多头拥挤）
    fr_abs = min(abs(funding_rate) * 10000 / 5, 1.0)
    score += fr_abs * 15
    if funding_rate < -0.0003:
        signals.append(f"负费率偏离({funding_rate*100:.4f}%)")
    elif funding_rate > 0.0005:
        signals.append(f"正费率偏高({funding_rate*100:.4f}%)")

    # 5. RSI极端位置（超卖反弹或超买回调机会）
    if rsi < 30:
        score += 10
        signals.append(f"RSI超卖{rsi:.0f}")
    elif rsi > 70:
        score += 10
        signals.append(f"RSI超买{rsi:.0f}")
    elif rsi < 40 or rsi > 60:
        score += 5

    # 6. EMA排列（趋势结构）
    if price > ema20 > ema50:
        score += 8
        if price > ema200:
            score += 2
            signals.append("EMA多头排列+MA200上方")
    elif price < ema20 < ema50:
        score += 8
        if price < ema200:
            score += 2
            signals.append("EMA空头排列+MA200下方")

    direction = "LONG" if ch24 > 0 else "SHORT"
    return {
        "score": round(min(score, 100), 1),
        "direction": direction,
        "signals": signals,
        "price": price,
        "ch24": round(ch24, 2),
        "ch1h": round(ch1h, 2),
        "vol_ratio": round(vol_ratio, 2),
        "rsi": round(rsi, 1),
        "funding_rate": funding_rate,
    }


def scan_all_coins(client: HyperliquidClient) -> Dict:
    """扫描全币种池，快速评分排序，选出Top候选"""
    opps = client.scan_opportunities()
    opp_map = {o["coin"]: o for o in opps}

    all_scores = {}
    for coin in UNIVERSE_B:
        if coin not in opp_map:
            continue
        price = opp_map[coin]["price"]
        if price <= 0:
            continue
        try:
            candles_1h = get_candles(coin, "1h", 48, client.proxies)
            closes = [float(c["c"]) for c in candles_1h if "c" in c]
            vols = [float(c["v"]) for c in candles_1h if "v" in c]
            if len(closes) < 24:
                continue

            ch24 = (closes[0] - closes[23]) / closes[23] * 100 if len(closes) > 23 else 0
            ch1h = (closes[0] - closes[1]) / closes[1] * 100 if len(closes) > 1 else 0

            avg_vol = sum(vols) / len(vols) if vols else 0
            cur_vol = vols[0] if vols else 0
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0

            # 简化指标计算
            def ema(prices, n):
                if len(prices) < n:
                    return prices[-1]
                k = 2 / (n + 1)
                e = prices[-n]
                for p in prices[-n + 1:]:
                    e = p * k + e * (1 - k)
                return e

            closes_rev = closes[::-1]
            ema20 = ema(closes_rev, 20)
            ema50 = ema(closes_rev, 50) if len(closes) >= 50 else ema20
            ema200 = ema(closes_rev, min(200, len(closes)))

            def rsi(prices, n=14):
                if len(prices) < n + 1:
                    return 50.0
                deltas = [prices[i] - prices[i - 1] for i in range(1, min(n + 1, len(prices)))]
                gains = [max(d, 0) for d in deltas]
                losses = [max(-d, 0) for d in deltas]
                avg_g = sum(gains) / n
                avg_l = sum(losses) / n
                if avg_l == 0:
                    return 100.0
                rs = avg_g / avg_l
                return 100 - 100 / (1 + rs)

            rsi14 = rsi(closes_rev)

            funding_rate = opp_map[coin].get("funding", 0.0)

            result = _score_coin(
                price, ch24, ch1h, vol_ratio, rsi14,
                funding_rate, ema20, ema50, ema200
            )
            all_scores[coin] = result
        except Exception:
            continue

    # 按评分排序
    ranked = sorted(all_scores.items(), key=lambda x: x[1]["score"], reverse=True)
    top3 = [name for name, _ in ranked[:3]]

    return {
        "all_scores": all_scores,
        "ranked": ranked,
        "top3": top3,
        "total_scanned": len(all_scores),
    }


def fetch_market_context(client: HyperliquidClient, primary_coin: Optional[str] = None) -> Dict:
    """采集多维市场数据供A0/A2分析（Hyperliquid数据源）"""
    opps = client.scan_opportunities()
    opp_map = {o["coin"]: o for o in opps}
    mids = {k: v["price"] for k, v in opp_map.items()}

    if not primary_coin:
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
        direction  = "LONG"
    elif least_resistance == "DOWN" and trend in ("STRONG_DOWN", "WEAK_DOWN") and dom == "BEAR":
        confidence = 0.72 + min((1 - trend_score) * 0.1, 0.12)
        direction  = "SHORT"
    elif least_resistance == "UP" and dom == "BULL":
        confidence = 0.62; direction = "LONG"
    elif least_resistance == "DOWN" and dom == "BEAR":
        confidence = 0.62; direction = "SHORT"
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
        m1_score = 8; m1_vote = "LONG"
        m1_reason = f"趋势强劲，顺势而为。{bull_cnt}维多，做多是顺势"
    elif trend in ("STRONG_DOWN",) and dom == "BEAR":
        m1_score = 8; m1_vote = "SHORT"
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
        m2_score = 7; m2_vote = "SHORT"
        m2_reason = f"RSI={rsi:.0f}+24H涨{ch24:.1f}%，均值回归压力大"
    elif rsi < 28 and ch24 < -5:
        m2_score = 7; m2_vote = "LONG"
        m2_reason = f"RSI={rsi:.0f}+24H跌{abs(ch24):.1f}%，超卖反弹概率高"
    elif a2_dir in ("LONG", "BUY") and rsi < 60:
        m2_score = 6; m2_vote = "LONG"
        m2_reason = f"RSI={rsi:.0f}未超买，做多空间充足"
    elif a2_dir in ("SHORT", "SELL") and rsi > 40:
        m2_score = 6; m2_vote = "SHORT"
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
    long_votes  = sum(1 for o in opinions if o["vote"] in ("LONG", "BUY"))
    short_votes = sum(1 for o in opinions if o["vote"] in ("SHORT", "SELL"))
    hold_votes = sum(1 for o in opinions if o["vote"] == "HOLD")
    avg_score  = sum(o["score"] for o in opinions) / len(opinions)

    if long_votes >= 2:
        seminar_verdict = "LONG"
    elif short_votes >= 2:
        seminar_verdict = "SHORT"
    else:
        seminar_verdict = "HOLD"

    # 置信度修正：大师共识 → 加成；分歧 → 折扣
    if long_votes == 3 or short_votes == 3:
        conf_adj = +0.08   # 三票同向，强烈加成
    elif hold_votes >= 2:
        conf_adj = -0.12   # 多数观望，大幅折扣
    elif long_votes == 2 or short_votes == 2:
        conf_adj = +0.03
    else:
        conf_adj = -0.05

    return {
        "opinions": opinions,
        "verdict": seminar_verdict,
        "buy_votes": long_votes, "sell_votes": short_votes, "hold_votes": hold_votes,
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

# ─── 经典指标驱动模式 ────────────────────────────────────────────────────────

def _run_classic_mode(
    cycle: str,
    client,
    memory: Dict,
    equity: float,
    l1_closed: List[Dict],
) -> Dict:
    """
    经典指标系统驱动模式（无 LLM 时的完整回退方案）
    
    通过 ClassicDriver 调用 ml_trade_service 完成：
    - 入场信号扫描 + 决策
    - 离场评估（L0~P3 全优先级）
    - 持仓管理
    
    设计原则：只做驱动不做实现，全部逻辑由 ml_trade_service 负责
    """
    print(f"\n[Agent B/Classic] ═══ 经典指标系统驱动模式 ═══")
    print(f"[Agent B/Classic] 目标: 无 LLM 时完整接管交易")
    print(f"[Agent B/Classic] 数据源: ml_trade_service (10-经典指标系统)")
    
    # 初始化 ClassicDriver
    driver = ClassicDriver(
        per_trade_usdc=BUDGET_USDC * PER_TRADE_PCT,
        max_positions=3,
        leverage=DEFAULT_LEVERAGE,
        coins=UNIVERSE_B,
    )
    
    # 检查 API 可用性
    api_ok = driver.is_available()
    print(f"[Agent B/Classic] 服务状态: {'✅ 可用' if api_ok else '❌ 不可用'} "
          f"({driver.get_status().last_error or 'ok'})")
    
    if not api_ok:
        # API 不可用时的兜底：保留 L1 基础离场，不做入场
        print(f"[Agent B/Classic] ⚠️ ml_trade_service 不可用，仅保留 L1 基础风控")
        log = DecisionLog("b", cycle)
        log.data.update({
            "driver_mode": "CLASSIC",
            "api_available": False,
            "api_error": driver.get_status().last_error,
            "action": "HOLD",
            "coin": "BTC",
            "confidence": 0.0,
            "decision_rationale": "ml_trade_service 不可用，经典模式降级为仅L1风控",
            "active_positions": memory.get("active_positions", {}),
            "l1_exits": l1_closed,
            "l3_exits": [],
            "a9_exits": [],
            "market_regime": "UNKNOWN",
        })
        path = log.save()
        save_memory(memory, log.data)
        print(f"[Agent B/Classic] 日志已保存: {path}")
        return log.data
    
    # 获取策略能力
    caps = driver.get_strategy_capabilities()
    print(f"[Agent B/Classic] 支持策略: {len(caps)} 个")
    for c in caps[:4]:
        print(f"  - {c.get('strategy_id')}: {c.get('direction_capability')}")
    
    # 获取价格函数
    def _get_price(coin: str) -> float:
        try:
            mids = client.get_all_mids()
            return float(mids.get(coin, 0) or 0)
        except Exception:
            return 0.0
    
    # 执行开仓函数
    def _execute_entry(coin: str, side: str, size_usdc: float, leverage: int, tag: str) -> Dict:
        if not AUTO_EXECUTE:
            return {"ok": False, "error": "auto_execute_disabled"}
        try:
            if side in ("LONG", "BUY"):
                return client.open_long(coin, size_usdc, leverage, tag)
            elif side in ("SHORT", "SELL"):
                return client.open_short(coin, size_usdc, leverage, tag)
            return {"ok": False, "error": f"invalid_side_{side}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    # 执行平仓函数
    def _execute_exit(coin: str, reason: str, tag: str) -> Dict:
        if not AUTO_EXECUTE:
            return {"ok": False, "error": "auto_execute_disabled"}
        try:
            nonlocal memory
            memory["active_positions"], closed_info, exec_res = execute_exit(
                client, memory.get("active_positions", {}), coin,
                f"CLASSIC_{reason[:20]}", tag=f"b_classic_{tag}"
            )
            return {"ok": bool(closed_info), "closed": closed_info, "execution": exec_res}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    # 执行完整周期
    print(f"\n[Agent B/Classic] 执行完整交易周期...")
    cycle_result = driver.run_full_cycle(
        active_positions=memory.get("active_positions", {}),
        get_price_fn=_get_price,
        execute_entry_fn=_execute_entry,
        execute_exit_fn=_execute_exit,
    )
    
    # 处理开仓结果：初始化 active_positions
    classic_entries = []
    for entry in cycle_result.get("entries", []):
        result = entry.get("result", {})
        if result.get("ok"):
            coin = entry["coin"]
            price = _get_price(coin)
            # 估算入场价
            memory["active_positions"] = init_position(
                memory.get("active_positions", {}),
                coin=coin,
                entry_price=price,
                action=entry["side"].upper(),
                position_size_usdt=driver.per_trade_usdc,
                leverage=driver.leverage,
                stop_loss_price=price * (1 - 0.04 / driver.leverage) if entry["side"].upper() in ("LONG", "BUY") else price * (1 + 0.04 / driver.leverage),
                take_profit_price=price * (1 + 0.08 / driver.leverage) if entry["side"].upper() in ("LONG", "BUY") else price * (1 - 0.08 / driver.leverage),
                cycle_id=cycle,
                proxies=client.proxies,
                client=client,
            )
            classic_entries.append(entry)
            print(f"[Agent B/Classic] ✅ 开仓 {coin} {entry['side']} "
                  f"({entry['strategy']}, conf={entry['confidence']:.0%})")
    
    # 处理平仓结果
    classic_exits = []
    for exit_info in cycle_result.get("exits", []):
        result = exit_info.get("result", {})
        if result.get("ok"):
            classic_exits.append(exit_info)
            closed = result.get("closed", {})
            print(f"[Agent B/Classic] 📤 平仓 {exit_info['coin']}: "
                  f"{exit_info['reason']} "
                  f"PnL={closed.get('pnl_pct', 0)*100:+.2f}%")
    
    # 输出信号概览
    signals = cycle_result.get("signals", [])
    print(f"\n[Agent B/Classic] 信号扫描: 共 {len(signals)} 个信号")
    for s in signals[:5]:
        print(f"  - {s['coin']} {s['side']} ({s['strategy']}): conf={s['conf']:.0%}")
    
    # 写决策日志
    log = DecisionLog("b", cycle)
    top_signal = signals[0] if signals else {"coin": "BTC", "side": "hold", "strategy": "none", "conf": 0.0}
    
    log.data.update({
        "driver_mode": "CLASSIC",
        "api_available": True,
        "strategies_used": driver.strategies,
        "coins_scanned": driver.coins,
        "signals_found": len(signals),
        "top_signal": top_signal,
        "classic_entries": classic_entries,
        "classic_exits": classic_exits,
        "market_regime": "CLASSIC_DRIVEN",
        "action": top_signal["side"].upper() if signals else "HOLD",
        "coin": top_signal["coin"],
        "leverage": driver.leverage,
        "confidence": top_signal.get("conf", 0.0),
        "position_size_usdt": driver.per_trade_usdc,
        "decision_rationale": (
            f"经典指标系统驱动模式 | {len(signals)}个信号 | "
            f"开仓{len(classic_entries)}笔 | 平仓{len(classic_exits)}笔"
        ),
        "system_features_used": [
            "classic_driver", "ml_trade_service", "strategy_feeders",
            "classic_exit_system", "l1_stop_loss",
        ],
        "active_positions": memory.get("active_positions", {}),
        "l1_exits": l1_closed,
        "l3_exits": classic_exits,
        "a9_exits": [],
        "intent_type": "CLASSIC_FALLBACK",
        "plan_budget_mode": "classic",
        "plan_estimated_tokens": 0,
        "plan_shortcut": True,
        "plan_rationale": "无LLM时自动回退到经典指标系统驱动",
    })
    
    path = log.save()
    save_memory(memory, log.data)
    print(f"\n[Agent B/Classic] 日志已保存: {path}")
    print(f"[Agent B/Classic] ═══ 经典模式执行完成 ═══")
    
    return log.data


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def run():
    cycle = _cycle_id()
    print(f"[Agent B] 启动 cycle={cycle}")
    print(f"[Agent B] ═══ Dreambuddy OS v1.0 ═══")

    # Step 0: 加载 Dreambuddy OS SKILL
    if DREAMBUDDY_OS_SKILL.exists():
        with open(DREAMBUDDY_OS_SKILL, "r") as f:
            skill_content = f.read()
        print(f"[Agent B/OS] SKILL 已加载: {DREAMBUDDY_OS_SKILL.name} ({len(skill_content)} chars)")
    else:
        print(f"[Agent B/OS] ⚠️ SKILL 文件不存在: {DREAMBUDDY_OS_SKILL}")

    # 加载记忆
    memory  = load_memory()
    gate    = apply_lessons(memory)
    lessons = memory.get("lessons", [])
    print(f"[Agent B] 记忆加载: {memory['total_cycles']}轮历史, {len(lessons)}条教训, "
          f"连败={memory.get('loss_streaks',0)}, 门槛={gate:.0%}")

    # Step 0.5: 交易记忆闭环初始化 — 加载上轮建议（系统性核心记忆）
    # 这是系统最重要的记忆能力：上轮建议 → 本轮验证 → 提炼教训 → 下轮建议
    trading_mem = TradingMemory(MEMORY_PATH, gh_token=GH_TOKEN, pr_number=PR_NUMBER)
    # 将 trading memory 合并到主 memory 中（保持向后兼容）
    if "suggestion_loop" in trading_mem.memory:
        memory["suggestion_loop"] = trading_mem.memory["suggestion_loop"]
    prior_suggestions = trading_mem.load_prior_suggestions()
    tm_stats = trading_mem.get_stats()
    print(f"[Agent B/Memory] 交易记忆闭环: 建议{tm_stats['prior_suggestions_count']}条 "
          f"(cycle={prior_suggestions.get('cycle_id', 'N/A')}), "
          f"已验证教训{tm_stats['verified_lessons_count']}条, "
          f"累计建议{tm_stats['total_suggestions']}个")

    client = HyperliquidClient("b")

    # Agent B 子账户：合约账户权益
    acct = client.get_account()
    if not acct["ok"]:
        print(f"[Agent B] 账户查询失败"); return
    equity = min(acct["equity"], BUDGET_USDC)
    print(f"[Agent B] 权益={equity:.2f} USDC  持仓={list(acct['positions'].keys())}")

    # ── L1 基础离场检查（止损止盈 + 移动止损）──────────────────────────
    print(f"\n[Agent B/Exit] L1 基础离场检查...")
    memory["active_positions"], l1_closed = run_exit_check(
        client, memory.get("active_positions", {}),
        agent_id="b", enable_trailing=True,
        account_data=acct,
    )
    if l1_closed:
        for ct in l1_closed:
            print(f"[Agent B/Exit] L1平仓 {ct['coin']}: {ct['exit_reason']} "
                  f"PnL={ct['pnl_pct']*100:+.2f}%")
    else:
        print(f"[Agent B/Exit] L1无触发，持仓: {list(memory['active_positions'].keys()) or '无'}")

    # ── 模式判断：BAC 全量架构 vs 经典指标驱动 ─────────────────────────
    use_classic = should_use_classic_driver()
    try:
        from core.llm_client import llm_available
        has_llm = llm_available() != "none"
    except Exception:
        has_llm = False

    if use_classic:
        driver_mode = "CLASSIC"
        mode_desc = "经典指标系统驱动（简化模式）"
    elif has_llm:
        driver_mode = "BAC_LLM"
        mode_desc = "BAC全量架构 + LLM增强（Trae全量模式）"
    else:
        driver_mode = "BAC_RULE"
        mode_desc = "BAC全量架构 + 规则引擎（Trae全量模式，无LLM增强）"

    print(f"\n[Agent B/Mode] 驱动模式: {driver_mode} ({mode_desc})")

    # ── 经典指标驱动模式：完整接管入场+离场 ───────────────────────────
    if use_classic:
        return _run_classic_mode(
            cycle=cycle,
            client=client,
            memory=memory,
            equity=equity,
            l1_closed=l1_closed,
        )

    # ── L3 经典指标离场检查（有 LLM 时跳过，由 A9 智能离场接管）─────
    l3_closed = []
    if memory.get("active_positions"):
        try:
            from core.llm_client import llm_available, llm_quota_ok
            has_llm_a9 = llm_available() != "none" and llm_quota_ok("a9_exit")
        except Exception:
            has_llm_a9 = False

        if has_llm_a9:
            print(f"[Agent B/Exit] L3跳过（有LLM，将在A9节点执行智能离场评估）")
        else:
            print(f"[Agent B/Exit] L3 经典指标离场检查（无LLM增强，BAC链路A9用规则引擎）...")
            mids = client.get_all_mids()
            for coin in list(memory["active_positions"].keys()):
                pos = memory["active_positions"][coin]
                price = mids.get(coin, 0)
                if price <= 0:
                    continue
                try:
                    candles = get_candles(coin, "1h", 48, client.proxies)
                except Exception:
                    candles = []
                should_exit, reason, _ = check_l3_classical_exits_api(
                    coin, price, pos["action"], candles
                )
                if should_exit and AUTO_EXECUTE:
                    memory["active_positions"], closed_info, exec_res = execute_exit(
                        client, memory["active_positions"], coin,
                        f"CLASSIC_{reason[:20]}", tag=f"b_exit_classic"
                    )
                    if closed_info:
                        l3_closed.append(closed_info)
                        print(f"[Agent B/Exit] L3经典平仓 {coin}: {reason} "
                              f"PnL={closed_info['pnl_pct']*100:+.2f}%")
            if not l3_closed:
                print(f"[Agent B/Exit] L3无触发")

    # ── 全币种扫描预筛选：先快速扫描所有币种，选出最优标的做深度分析 ──
    print(f"\n[Agent B/Scan] 全币种扫描预筛选...")
    scan_result = scan_all_coins(client)
    print(f"[Agent B/Scan] 扫描 {scan_result['total_scanned']} 个币种")
    print(f"[Agent B/Scan] Top 5:")
    for coin, data in scan_result["ranked"][:5]:
        print(f"  #{data['score']:5.1f}  {coin:6s}  "
              f"{data['direction']:5s}  24H={data['ch24']:+6.2f}%  "
              f"RSI={data['rsi']:5.1f}  vol={data['vol_ratio']:.2f}x  "
              f"{' | '.join(data['signals'][:2])}")
    top_coin = scan_result["top3"][0] if scan_result["top3"] else "BTC"
    print(f"[Agent B/Scan] 选定主标的: {top_coin} (评分最高)")

    mkt = fetch_market_context(client, primary_coin=top_coin)
    # 注入全币种扫描结果到 mkt（供后续节点使用）
    mkt["scan_result"] = scan_result
    mkt["top3_coins"] = scan_result["top3"]
    mkt["all_coin_scores"] = scan_result["all_scores"]
    # 注入 Regime 到 mkt 供意图识别使用
    mkt["regime"] = (
        "TREND_UP"   if mkt.get("change_24h", 0) > 2 else
        "TREND_DOWN" if mkt.get("change_24h", 0) < -2 else "RANGE"
    )
    print(f"[Agent B] 主标的={mkt['coin']} price={mkt['price']:.2f}, "
          f"24H={mkt['change_24h']:+.1f}%, RSI={mkt['rsi14']}, regime={mkt['regime']}")

    # ── Step 1: 意图识别（零Token）─────────────────────────────────────────
    print(f"[Agent B/OS] Step 1/6 — 意图识别")
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent))
    from core.intent_gateway import detect_intent
    from core.chain_planner import ChainPlanner
    from core.chain_router import ChainRouter

    intent = detect_intent(mkt, memory, memory.get("active_positions"))
    print(f"[Agent B/Intent] {intent.intent_type} conf={intent.confidence:.0%} | {intent.rationale[:60]}")

    # ── Step 2: BAC 三层规划（零Token）────────────────────────────────────
    print(f"[Agent B/OS] Step 2/6 — BAC 三层规划")
    token_budget = int(os.environ.get("TOKEN_BUDGET", "30000"))
    planner = ChainPlanner(token_budget=token_budget)
    plan    = planner.plan(intent, mkt, memory)

    print(f"[Agent B/Plan]   B层蓝图: A1 Feed + Memory + Regime")
    print(f"[Agent B/Plan]   A层架构: {len(plan.planned_chain)} 节点")
    print(f"[Agent B/Plan]   C层时间线: cycle={cycle}")
    print(f"[Agent B/Plan]   模式={plan.budget_mode} 预估={plan.estimated_tokens}t"
          f"{' 快捷路径' if plan.shortcut_taken else ''}"
          f"{' ⬆️自适应升级' if plan.auto_escalated else ''}")
    print(f"[Agent B/Plan]   链路: {plan.planned_chain}")
    if plan.auto_escalated:
        print(f"[Agent B/Plan]   升级原因: {plan.escalation_reason} "
              f"({plan.original_mode}→{plan.budget_mode}, +{plan.escalation_level}档)")
    if plan.pruned_nodes:
        print(f"[Agent B/Plan]   剪枝: {[p.split('（')[0] for p in plan.pruned_nodes]}")
    if plan.added_nodes:
        print(f"[Agent B/Plan]   追加: {plan.added_nodes}")

    # 把规划结果注入 intent（链路规划器的输出替换基础链）
    intent.base_chain    = plan.planned_chain
    intent.extend_nodes  = []  # 规划器已经合并了扩展节点

    # ── Step 3: 动态执行（ChainRouter）────────────────────────────────────
    print(f"[Agent B/OS] Step 3/6 — 动态执行引擎")
    router = ChainRouter(client, mkt, memory, intent, BUDGET_USDC)
    chain_result = router.execute()

    print(f"[Agent B/Chain]  执行了 {len(chain_result.node_trace)} 个节点"
          f"{' (+' + str(len(chain_result.dynamic_nodes_added)) + '动态追加)' if chain_result.dynamic_nodes_added else ''}")
    print(f"[Agent B/Chain]  最终: {chain_result.final_action} {chain_result.coin} "
          f"conf={chain_result.final_confidence:.0%} gate={'✅' if chain_result.gate_passed else '❌'}")
    print(f"[Agent B/A7]  {'✅ 通过' if chain_result.gate_passed else '❌ 拦截'}: {chain_result.gate_reason}")

    # ── Step 3.1: 做梦部强迫性重复检测 → 触发模式升级 + 二次重规划 ──
    if chain_result.compulsive_repetition_detected and not plan.auto_escalated:
        print(f"\n[Agent B/OS] 🔄 做梦部检测到强迫性重复 → 触发模式升级 + 二次重规划")
        print(f"[Agent B/Dream] 原因: {chain_result.dream_department_reason}")

        # 用升级后的预算重新规划
        planner2 = ChainPlanner(token_budget=token_budget)
        plan2 = planner2.plan(intent, mkt, memory, force_escalation=True)

        if plan2.auto_escalated and plan2.budget_mode != plan.budget_mode:
            print(f"[Agent B/OS] 预算模式升级: {plan.budget_mode} → {plan2.budget_mode}")
            print(f"[Agent B/OS] 节点数: {len(plan.planned_chain)} → {len(plan2.planned_chain)}")
            print(f"[Agent B/OS] 重新执行链路...")

            # 重新注入 intent
            intent.base_chain = plan2.planned_chain
            intent.extend_nodes = []

            # 二次执行
            router2 = ChainRouter(client, mkt, memory, intent, BUDGET_USDC)
            chain_result2 = router2.execute()

            print(f"[Agent B/Chain]  二次执行: {len(chain_result2.node_trace)} 个节点")
            print(f"[Agent B/Chain]  二次结果: {chain_result2.final_action} "
                  f"conf={chain_result2.final_confidence:.0%} "
                  f"gate={'✅' if chain_result2.gate_passed else '❌'}")

            # 只有二次执行通过了门禁且结果不是HOLD，才采用二次结果
            if chain_result2.gate_passed and chain_result2.final_action != "HOLD":
                print(f"[Agent B/OS] ✅ 二次执行通过，采用升级后结果")
                chain_result = chain_result2
                plan = plan2
            else:
                print(f"[Agent B/OS] ⚠️ 二次执行仍未突破，保持原结果")
        else:
            print(f"[Agent B/OS] 已是最高模式，无法继续升级")
    elif chain_result.compulsive_repetition_detected and plan.auto_escalated:
        print(f"[Agent B/Dream] ⚠️ 做梦部检测到强迫性重复，但本轮已自动升级过，不再重复升级")

    # ── Step 3.5: 处理 A9 离场评估结果（智能离场）─────────────────────
    a9_exits = []
    if AUTO_EXECUTE and memory.get("active_positions"):
        for node in chain_result.node_trace:
            if "A9" in node.node_id and not node.skipped:
                exit_sugs = node.data.get("exits", [])
                update_sugs = node.data.get("updates", [])
                # 执行离场建议
                for sug in exit_sugs:
                    coin = sug.get("coin")
                    reason = sug.get("reason", "A9_EXIT")
                    if coin and coin in memory["active_positions"]:
                        memory["active_positions"], closed_info, _ = execute_exit(
                            client, memory["active_positions"], coin,
                            f"A9_{reason[:20]}", tag=f"b_exit_a9"
                        )
                        if closed_info:
                            a9_exits.append(closed_info)
                            print(f"[Agent B/Exit] A9智能平仓 {coin}: {reason} "
                                  f"PnL={closed_info['pnl_pct']*100:+.2f}%")
                # 调整止损止盈
                for sug in update_sugs:
                    coin = sug.get("coin")
                    new_sl = sug.get("new_stop_loss")
                    new_tp = sug.get("new_take_profit")
                    if coin and coin in memory["active_positions"]:
                        memory["active_positions"] = update_position_exit_levels(
                            memory["active_positions"], coin, new_sl, new_tp,
                            sl_source="a9_smart", tp_source="a9_smart",
                            client=client if (not sim_mode and AUTO_EXECUTE) else None
                        )
                        print(f"[Agent B/Exit] A9调整 {coin}: SL→{new_sl}, TP→{new_tp}")
                break

    action     = chain_result.final_action
    coin       = chain_result.coin
    leverage   = chain_result.leverage
    final_conf = chain_result.final_confidence
    gate_pass  = chain_result.gate_passed
    gate_reason = chain_result.gate_reason
    position_size_usdt = chain_result.position_size_usdt
    price = mkt["price"]

    # ── 写决策日志 ────────────────────────────────────────────────────────────
    log = DecisionLog("b", cycle)
    log.data.update({
        "market_regime":         mkt["regime"],
        "key_contradictions":    [
            f"{r.node_id}: {r.direction}({r.confidence:.0%})"
            for r in chain_result.node_trace if "A0" in r.node_id or "矛盾" in r.node_id
        ],
        "reasoning_steps": (
            [f"[Intent] {intent.intent_type} conf={intent.confidence:.0%}: {intent.rationale[:80]}"]
            + [f"  [{r.node_id}] {r.direction} conf={r.confidence:.0%}"
               + (f" (SKIP:{r.skip_reason})" if r.skipped else "")
               + (" ← 动态追加" if r.node_id in chain_result.dynamic_nodes_added else "")
               for r in chain_result.node_trace]
            + [f"[A7门禁] {gate_reason}"]
        ),
        "confidence":           final_conf,
        "intent_confidence":    intent.confidence,
        "supporting_evidence":  [
            f"标的: {coin}  杠杆: {leverage}x  意图: {intent.intent_type}",
            f"EMA: {mkt['ema20']:.2f}/{mkt['ema50']:.2f}/{mkt['ema200']:.2f}",
            f"RSI={mkt['rsi14']:.1f} 资金费率={mkt['funding_rate']:.6f}",
            f"规划: {plan.budget_mode}模式 ~{plan.estimated_tokens}t"
            + (f" 快捷路径" if plan.shortcut_taken else ""),
            f"规划理由: {plan.plan_rationale[:100]}",
            f"动态追加节点: {chain_result.dynamic_nodes_added or '无'}",
        ],
        "action":               action,
        "coin":                 coin,
        "leverage":             leverage,
        "entry_price":          price,
        "position_size_usdt":   position_size_usdt,
        "stop_loss_price":      chain_result.stop_loss,
        "take_profit_price":    chain_result.take_profit,
        "decision_rationale":   (gate_reason if not gate_pass else
                                 f"{coin} {action} {leverage}x | {intent.intent_type} | conf={final_conf:.0%}"),
        "system_features_used": (
            ["intent_gateway", "chain_planner", "chain_router", "graph_compression", "memory"]
            + [r.node_id for r in chain_result.node_trace if not r.skipped]
        ),
        "graph_context_nodes":  len(chain_result.node_trace),
        "memory_loaded":        True,
        "prior_lessons_applied": lessons[-2:],
        "prior_pr_suggestions_applied": prior_suggestions.get("cycle_id") if prior_suggestions else None,
        "intent_type":          intent.intent_type,
        "dynamic_nodes_added":  chain_result.dynamic_nodes_added,
        "plan_budget_mode":     plan.budget_mode,
        "plan_estimated_tokens": plan.estimated_tokens,
        "plan_pruned_nodes":    [p.split("（")[0] for p in plan.pruned_nodes],
        "plan_added_nodes":     plan.added_nodes,
        "plan_shortcut":        plan.shortcut_taken,
        "plan_rationale":       plan.plan_rationale,
        "active_positions":     memory.get("active_positions", {}),
        "l1_exits":             l1_closed,
        "l3_exits":             l3_closed,
        "a9_exits":             a9_exits,
        "account_equity":       round(equity, 2),
        "win_streaks":          memory.get("win_streaks", 0),
        "loss_streaks":         memory.get("loss_streaks", 0),
    })

    # ── 执行 ─────────────────────────────────────────────────────────────────
    if AUTO_EXECUTE and gate_pass and position_size_usdt > 0:
        tag = f"b_{cycle[:8]}"
        if action in ("BUY", "LONG"):
            exec_result = client.open_long(coin, position_size_usdt, leverage, tag)
        elif action in ("SELL", "SHORT"):
            exec_result = client.open_short(coin, position_size_usdt, leverage, tag)
        else:
            exec_result = {"ok": False, "error": "HOLD"}
        log.data["execution"] = exec_result
        print(f"[Agent B] 执行: ok={exec_result.get('ok')} {exec_result.get('filled')}")

        # 开仓成功后初始化 active_positions（L1 基础离场）
        if exec_result.get("ok"):
            entry_px = price
            custom_sl = chain_result.stop_loss
            custom_tp = chain_result.take_profit
            memory["active_positions"] = init_position(
                memory.get("active_positions", {}),
                coin=coin,
                entry_price=entry_px,
                action=action,
                position_size_usdt=position_size_usdt,
                leverage=leverage,
                stop_loss_price=custom_sl,
                take_profit_price=custom_tp,
                cycle_id=cycle,
                proxies=client.proxies,
                client=client,
            )
            pos_info = memory["active_positions"][coin]
            print(f"[Agent B/Exit] L1预设: SL={pos_info['stop_loss_price']} "
                  f"({pos_info['sl_source']}), "
                  f"TP={pos_info['take_profit_price']} "
                  f"({pos_info['tp_source']})")
    else:
        print(f"[Agent B] 跳过执行（AUTO_EXECUTE={AUTO_EXECUTE}, gate={gate_pass}）")

    path = log.save()
    print(f"[Agent B] 日志已保存: {path}")

    # ── 交易记忆闭环：验证上轮建议 + 提炼教训 + 生成本轮建议 ──
    # 这是交易记忆系统的核心闭环：建议 → 验证 → 提炼 → 新建议
    verifications, verify_summary = trading_mem.verify_prior_suggestions(
        current_action=action,
        current_coin=coin,
        current_price=price,
        mkt=mkt,
        confidence=final_conf,
        gate_passed=gate_pass,
    )
    if verifications:
        print(f"[Agent B/Memory] 上轮建议验证: "
              f"{verify_summary['verified']}验证/{verify_summary['partial']}部分/"
              f"{verify_summary['pending']}待验证 (共{verify_summary['total']}条)")

    new_lessons = trading_mem.distill_lessons(verifications, cycle)
    if new_lessons:
        print(f"[Agent B/Memory] 提炼新教训: {len(new_lessons)}条")

    next_suggestions = trading_mem.generate_next_suggestions(
        cycle_id=cycle,
        action=action,
        coin=coin,
        price=price,
        confidence=final_conf,
        intent_confidence=intent.confidence,
        regime=mkt["regime"],
        mkt=mkt,
        chain_result=chain_result,
    )
    print(f"[Agent B/Memory] 生成本轮建议: {len(next_suggestions.get('next_verifications', []))}个待验证, "
          f"{len(next_suggestions.get('risk_warnings', []))}个风险, "
          f"{len(next_suggestions.get('bac_adjustments', []))}个BAC调整, "
          f"{len(next_suggestions.get('dze_triggers', []))}个D-Z-E")

    # 将 trading memory 合并回主 memory
    if "suggestion_loop" in trading_mem.memory:
        memory["suggestion_loop"] = trading_mem.memory["suggestion_loop"]

    # ── 更新记忆 ──────────────────────────────────────────────────────────────
    save_memory(memory, log.data, next_suggestions=next_suggestions)

    # ── Step 4: 自我进化（A7+A8+gap_score）────────────────────────────────
    print(f"[Agent B/OS] Step 4/6 — 自我进化引擎")
    _trigger_self_evolution(log.data, memory)

    # ── Step 5: D-Z-E 开发链（按需触发）───────────────────────────────────
    print(f"[Agent B/OS] Step 5/6 — D-Z-E 开发链检查")
    loss_streaks = memory.get("loss_streaks", 0)
    confidence = log.data.get("confidence", 0)
    if loss_streaks >= 3 and confidence > 0.60:
        print(f"[Agent B/DZE] 触发条件满足，启动 D-Z-E")
    else:
        print(f"[Agent B/DZE] 未触发（连败={loss_streaks}, 置信度={confidence:.0%}）")

    # ── Step 6: 预算管理 + 日志归档 + PR 评论 ──────────────────────────────
    print(f"[Agent B/OS] Step 6/6 — 预算管理 & 报告输出")
    print(f"[Agent B/Budget] 模式={plan.budget_mode}, 预估={plan.estimated_tokens}t, 实际≈{len(chain_result.node_trace)*300}t")

    # 日志保存 + Git push
    _save_and_push_logs(cycle, log.data)

    # PR 评论
    pr_report = _build_pr_report(log.data, mkt, plan, chain_result,
                                 prior_suggestions=prior_suggestions,
                                 next_suggestions=next_suggestions,
                                 cycle=cycle)
    _comment_pr(pr_report)

    # 自主调度
    print(f"[Agent B/OS] Step 6+ — 自主调度评估")
    a0_stub = {"conflict_count": 0, "bull_count": 0, "bear_count": 0}
    a2_stub = {"least_resistance": "NEUTRAL", "confidence": final_conf}
    for r in chain_result.node_trace:
        if "A0" in r.node_id: a0_stub.update(r.data.get("a0", {}))
        if "A2" in r.node_id: a2_stub.update(r.data.get("a2", {}))
    _b_self_schedule(log.data, a0_stub, a2_stub, memory)

    print(f"[Agent B/OS] ═══ 执行完成 ═══")
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


# ─── Dreambuddy OS v1.0：PR 评论 + 自我进化 + D-Z-E ──────────────────────────

def _comment_pr(report_md: str) -> bool:
    """在 PR #52 下发交易报告评论"""
    if not GH_TOKEN:
        print("[Agent B/PR] 未配置 GH_TOKEN，跳过评论")
        return False
    url = f"https://api.github.com/repos/yunya1991/Dreambuddy-V2/issues/{PR_NUMBER}/comments"
    headers = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    body = {"body": report_md}
    import requests as _req
    r = _req.post(url, headers=headers, json=body)
    if r.status_code in (200, 201):
        print(f"[Agent B/PR] 评论成功 ✅")
        return True
    else:
        print(f"[Agent B/PR] 评论失败 ❌ {r.status_code}: {r.text[:100]}")
        return False


def _fetch_pr_comments() -> List[Dict]:
    """获取 PR #52 的所有评论（按时间升序）"""
    if not GH_TOKEN:
        print("[Agent B/PR] 未配置 GH_TOKEN，无法读取评论")
        return []
    url = f"https://api.github.com/repos/yunya1991/Dreambuddy-V2/issues/{PR_NUMBER}/comments"
    headers = {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    import requests as _req
    try:
        r = _req.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            comments = r.json()
            return sorted(comments, key=lambda c: c.get("created_at", ""))
        else:
            print(f"[Agent B/PR] 读取评论失败 {r.status_code}: {r.text[:100]}")
            return []
    except Exception as e:
        print(f"[Agent B/PR] 读取评论异常: {e}")
        return []


def _find_last_agent_b_comment(comments: List[Dict]) -> Optional[Dict]:
    """
    从评论列表中找到上一轮 Agent B 的交易报告评论。
    优先找包含「下轮关注建议」的长格式报告（含结构化建议），
    找不到再退而求其次找任意 Agent B 报告。
    """
    for c in reversed(comments):
        body = c.get("body", "")
        if "Agent B 交易报告" in body and "下轮关注" in body:
            return c
    for c in reversed(comments):
        body = c.get("body", "")
        if "Agent B 交易报告" in body or "🧠 Agent B" in body:
            return c
    return None


def _extract_prior_suggestions(comment_body: str) -> Dict:
    """
    从 Agent B 交易报告评论中提取「下轮关注建议」。

    返回结构：
    {
        "cycle_id": "20260630_040730",
        "next_verifications": ["待验证假设1", "待验证假设2"],
        "risk_warnings": ["风险提示1"],
        "bac_adjustments": ["BAC调整建议1"],
        "dze_triggers": ["D-Z-E触发建议1"],
        "raw_text": "原始建议文本...",
    }
    """
    import re

    result = {
        "cycle_id": None,
        "next_verifications": [],
        "risk_warnings": [],
        "bac_adjustments": [],
        "dze_triggers": [],
        "raw_text": "",
    }

    if not comment_body:
        return result

    m = re.search(r"cycle:\s*([0-9_]+)", comment_body)
    if m:
        result["cycle_id"] = m.group(1)

    next_section = ""
    lines = comment_body.split("\n")
    in_next_section = False
    section_level = 0

    for i, line in enumerate(lines):
        if "下轮关注建议" in line or "下轮关注" in line or "🔮" in line and ("关注" in line or "建议" in line):
            in_next_section = True
            section_level = len(line) - len(line.lstrip("#"))
            continue

        if in_next_section:
            if line.strip().startswith("###") and len(line) - len(line.lstrip("#")) <= section_level:
                break
            if line.strip().startswith("##") and len(line) - len(line.lstrip("#")) < section_level:
                break
            next_section += line + "\n"

    result["raw_text"] = next_section.strip()

    current_list = None
    for line in next_section.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        if "待验证假设" in stripped:
            current_list = "next_verifications"
            m = re.search(r"[：:](.+)", stripped)
            if m and m.group(1).strip():
                result["next_verifications"].append(m.group(1).strip())
            continue
        if re.match(r"^\d+\.\s*\*\*风险提示\*\*", stripped) or "风险提示" in stripped and "潜在机会" not in stripped:
            current_list = "risk_warnings"
            m = re.search(r"[：:](.+)", stripped)
            if m and m.group(1).strip():
                result["risk_warnings"].append(m.group(1).strip())
            continue
        if "潜在机会" in stripped:
            current_list = None
            continue
        if re.match(r"^\d+\.\s*\*\*BAC", stripped) or ("BAC" in stripped and ("调整" in stripped or "链路" in stripped)):
            current_list = "bac_adjustments"
            m = re.search(r"[：:](.+)", stripped)
            if m and m.group(1).strip():
                result["bac_adjustments"].append(m.group(1).strip())
            continue
        if re.match(r"^\d+\.\s*\*\*D-Z-E", stripped) or re.match(r"^\d+\.\s*\*\*DZE", stripped) or ("D-Z-E" in stripped and "触发" in stripped):
            current_list = "dze_triggers"
            m = re.search(r"[：:](.+)", stripped)
            if m and m.group(1).strip():
                result["dze_triggers"].append(m.group(1).strip())
            continue

        if stripped.startswith("-") or stripped.startswith("*") or re.match(r"^\d+[\.\)、]", stripped):
            item = re.sub(r"^[-*\d\.\)、]+\s*", "", stripped).strip()
            if item and current_list and current_list in result:
                if item.startswith("**") and item.endswith("**"):
                    continue
                result[current_list].append(item)

    return result


def load_prior_pr_suggestions() -> Dict:
    """
    从 PR #52 读取上一轮 Agent B 交易报告中的下轮关注建议。

    返回：同 _extract_prior_suggestions 的结构；若读取失败返回空结构。
    """
    empty = {"cycle_id": None, "next_verifications": [], "risk_warnings": [],
             "bac_adjustments": [], "dze_triggers": [], "raw_text": ""}

    comments = _fetch_pr_comments()
    if not comments:
        print("[Agent B/PR] 未获取到 PR 评论，跳过 PR 建议读取")
        return empty

    last_comment = _find_last_agent_b_comment(comments)
    if not last_comment:
        print("[Agent B/PR] 未找到上一轮 Agent B 交易报告评论")
        return empty

    suggestions = _extract_prior_suggestions(last_comment.get("body", ""))
    total = (len(suggestions["next_verifications"]) + len(suggestions["risk_warnings"])
             + len(suggestions["bac_adjustments"]) + len(suggestions["dze_triggers"]))
    print(f"[Agent B/PR] 上轮建议已加载 (cycle={suggestions['cycle_id']}, {total}条): "
          f"{len(suggestions['next_verifications'])}个待验证, "
          f"{len(suggestions['risk_warnings'])}个风险, "
          f"{len(suggestions['bac_adjustments'])}个BAC调整, "
          f"{len(suggestions['dze_triggers'])}个D-Z-E")
    return suggestions


def build_next_cycle_suggestions(log_data: dict, mkt: dict, chain_result, memory: dict) -> Dict:
    """
    生成本轮的「下轮关注建议」，用于写入 memory 和 PR 报告。

    返回结构同 _extract_prior_suggestions。
    """
    action = log_data.get("action", "HOLD")
    coin = log_data.get("coin", "BTC")
    confidence = log_data.get("confidence", 0)
    regime = mkt.get("regime", "UNKNOWN")
    gap_score = abs(log_data.get("intent_confidence", 0) - confidence)

    next_verifications = []
    risk_warnings = []
    bac_adjustments = []
    dze_triggers = []

    if action in ("BUY", "LONG"):
        ema50 = mkt.get("ema50", 0)
        ema200 = mkt.get("ema200", 0)
        price = mkt.get("price", 0)
        if ema50 and price < ema50:
            next_verifications.append(f"{coin} 能否突破 EMA50({ema50:.2f}) 并放量确认趋势")
        if ema200 and price < ema200:
            next_verifications.append(f"{coin} 能否站上 EMA200({ema200:.2f}) 打开中期空间")
        if action in ("BUY", "LONG") and chain_result and chain_result.stop_loss:
            next_verifications.append(f"关注 {coin} 止损位 {chain_result.stop_loss} 是否有效")

    if action in ("SELL", "SHORT"):
        ema20 = mkt.get("ema20", 0)
        price = mkt.get("price", 0)
        if ema20 and price > ema20:
            next_verifications.append(f"{coin} 能否跌破 EMA20({ema20:.2f}) 确认下行")

    if mkt.get("vol_ratio", 1) < 0.6:
        risk_warnings.append(f"整体市场量能持续低迷（{mkt['vol_ratio']:.1f}x），警惕假突破/假跌破")

    if regime == "RANGE":
        risk_warnings.append("当前 RANGE 震荡市，突破信号可靠性降低，需严格止损")

    if gap_score >= 0.3:
        bac_adjustments.append(
            f"gap_score={gap_score:.2f}（{'中度' if gap_score < 0.5 else '严重'}背离），"
            f"建议优化意图识别模块对 {regime} 市场的敏感度"
        )

    loss_streaks = memory.get("loss_streaks", 0)
    if loss_streaks >= 3:
        dze_triggers.append(f"连败{loss_streaks}次，触发向外学习，重新评估策略框架")

    recent = memory.get("recent_decisions", [])[-10:]
    hold_count = sum(1 for d in recent if d.get("action") == "HOLD")
    if hold_count >= 5:
        dze_triggers.append(f"连续{hold_count}次HOLD的强迫性重复，建议触发向外学习优化意图识别")

    recent_5 = memory.get("recent_decisions", [])[-5:]
    hold_5 = sum(1 for d in recent_5 if d.get("action") == "HOLD")
    if hold_5 >= 3 and confidence < 0.65:
        dze_triggers.append(f"近5轮{hold_5}次HOLD且置信度<65%，系统可能过度保守")

    if not next_verifications and action == "HOLD":
        next_verifications.append(f"观察 {coin} 在当前 {regime} 区间内的方向选择")

    return {
        "next_verifications": next_verifications,
        "risk_warnings": risk_warnings,
        "bac_adjustments": bac_adjustments,
        "dze_triggers": dze_triggers,
    }


def _build_pr_report(log_data: dict, mkt: dict, plan, chain_result,
                    prior_suggestions: Optional[Dict] = None,
                    next_suggestions: Optional[Dict] = None,
                    cycle: Optional[str] = None) -> str:
    """按 dreambuddy-os SKILL 定义的格式构建 PR 评论"""
    action = log_data.get("action", "HOLD")
    coin = log_data.get("coin", mkt.get("coin", "BTC"))
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M (CST)")
    cycle_display = cycle or log_data.get("cycle_id", "N/A")

    # 获取 top 3 动量标的
    top3 = []
    opp_map = mkt.get("opp_map", {})
    for coin_sym in ["BTC", "ETH", "SOL", "HYPE", "AVAX"]:
        if coin_sym in opp_map:
            o = opp_map[coin_sym]
            top3.append(f"{coin_sym} — 24H {o.get('change_24h', 0):+.1f}%，RSI {o.get('rsi', 'N/A')}")
            if len(top3) >= 3:
                break

    # BAC 链路
    bac_chain = " → ".join([r.node_id for r in chain_result.node_trace]) if chain_result.node_trace else str(plan.planned_chain if plan else [])

    # Lessons
    lessons = log_data.get("prior_lessons_applied", [])
    lessons_str = ", ".join(lessons[-3:]) if lessons else "无"

    # A7 闸门状态
    confidence = log_data.get("confidence", 0)
    gate_passed = confidence >= CONFIDENCE_GATE
    gate_status = "✅ 通过" if gate_passed else "❌ 拦截"

    # 上轮建议落实情况
    prior_section = ""
    if prior_suggestions and (prior_suggestions.get("next_verifications")
                               or prior_suggestions.get("risk_warnings")
                               or prior_suggestions.get("bac_adjustments")
                               or prior_suggestions.get("dze_triggers")):
        prior_lines = []
        prior_cycle = prior_suggestions.get("cycle_id", "未知")
        prior_lines.append(f"\n### 🔁 上轮建议落实 (cycle: {prior_cycle})")

        verified_count = 0
        for v in prior_suggestions.get("next_verifications", []):
            verified_count += 1
            v_short = v[:50] + "..." if len(v) > 50 else v
            if action in ("BUY", "LONG") and "EMA50" in v and coin in v:
                status = "✅ 已验证突破"
            elif action == "HOLD" and "突破" in v:
                status = "⏳ 待验证"
            else:
                status = "📝 纳入本轮分析"
            prior_lines.append(f"- **[{verified_count}]** {v_short} — {status}")

        for rw in prior_suggestions.get("risk_warnings", []):
            rw_short = rw[:50] + "..." if len(rw) > 50 else rw
            prior_lines.append(f"- ⚠️ {rw_short}")

        for ba in prior_suggestions.get("bac_adjustments", []):
            ba_short = ba[:50] + "..." if len(ba) > 50 else ba
            prior_lines.append(f"- 🔧 {ba_short}")

        for dt in prior_suggestions.get("dze_triggers", []):
            dt_short = dt[:50] + "..." if len(dt) > 50 else dt
            prior_lines.append(f"- 🧬 {dt_short}")

        prior_section = "\n".join(prior_lines)

    # 下轮关注建议
    next_section = ""
    if next_suggestions:
        next_lines = ["\n### 🔮 下轮关注建议"]

        for i, v in enumerate(next_suggestions.get("next_verifications", []), 1):
            next_lines.append(f"{i}. **待验证假设**：{v}")

        for i, rw in enumerate(next_suggestions.get("risk_warnings", []), 1):
            next_lines.append(f"{i + len(next_suggestions.get('next_verifications', []))}. **风险提示**：{rw}")

        base_idx = len(next_suggestions.get("next_verifications", [])) + len(next_suggestions.get("risk_warnings", []))
        for i, ba in enumerate(next_suggestions.get("bac_adjustments", []), 1):
            next_lines.append(f"{base_idx + i}. **BAC 调整建议**：{ba}")

        base_idx2 = base_idx + len(next_suggestions.get("bac_adjustments", []))
        for i, dt in enumerate(next_suggestions.get("dze_triggers", []), 1):
            next_lines.append(f"{base_idx2 + i}. **D-Z-E 触发建议**：{dt}")

        next_section = "\n".join(next_lines)

    report = f"""## 🧠 Agent B 交易报告 | Dreambuddy OS | cycle: {cycle_display}

### 📊 本轮决策
| 项目 | 值 |
|------|-----|
| 动作 | {action} |
| 标的 | {coin} |
| 置信度 | {confidence:.0%} |
| A7 闸门 | {gate_status} |
| 当前大师 | Dreambuddy OS |
| BAC 模式 | {log_data.get('plan_budget_mode', 'N/A')} |

### 🧭 BAC 三层链路
- **B层蓝图**：[来源：A1 Feed + Memory + Regime={mkt.get('regime', 'N/A')} + PR建议]
- **A层架构**：{len(chain_result.node_trace) if chain_result.node_trace else len(plan.planned_chain if plan else [])} 节点，执行链路 [{bac_chain}]
- **C层时间线**：cycle={cycle_display}

### 🔍 意图识别
- 类型：{log_data.get('intent_type', 'N/A')}
- 置信度：{log_data.get('confidence', 0):.0%}
- 依据：{log_data.get('decision_rationale', 'N/A')[:80]}

### 🧩 系统特征
- SKILL: dreambuddy-os
- 自我进化：A7闸门 + A8知行合一
- D-Z-E 链：{"⚠️ 已触发" if next_suggestions and next_suggestions.get('dze_triggers') else "未触发"}
- 做梦部：{"已检测" if chain_result and chain_result.compulsive_repetition_detected else "未触发"}
- 驱动模式：BAC_RULE

### 📈 账户状态
- 权益：{log_data.get('account_equity', 'N/A')} USDC
- 持仓：{', '.join(log_data.get('active_positions', {}).keys()) or '无'}

{prior_section}

{next_section}

### 🧩 预算使用
- 模式：{log_data.get('plan_budget_mode', 'N/A')}
- 预估Token：{log_data.get('plan_estimated_tokens', 'N/A')} / 30,000

---

*🤖 自动生成于 {ts} — Dreambuddy OS v1.0*"""
    return report


def _trigger_self_evolution(log_data: dict, memory: dict):
    """
    自我进化引擎驱动（按 dreambuddy-os SKILL 第六步定义）

    检查条件触发：
    1. gap_score ≥ 0.5 → D-Z-E 开发链
    2. 连败 ≥ 3 → 做梦部触发
    3. 置信度 55-64% 反复被拦 → 做梦部触发
    """
    import subprocess

    loss_streaks = memory.get("loss_streaks", 0)
    confidence = log_data.get("confidence", 0)
    action = log_data.get("action", "HOLD")

    # 触发条件1：gap_score ≥ 0.5（D-Z-E）
    # 简化：若置信度与实际结果严重背离（如 HOLD 但市场大涨）
    # 这里用连败3次且置信度>0.6 作为 gap_score 代理
    if loss_streaks >= 3 and confidence > 0.60:
        print(f"[Agent B/Evolution] gap_score 代理 ≥ 0.5，触发 D-Z-E 开发链")
        _trigger_dze_chain(
            f"Agent B 连败{loss_streaks}次，置信度{confidence:.0%}仍亏损，"
            f"regime={memory.get('last_regime')}，需重新评估策略框架"
        )

    # 触发条件2：置信度反复在门槛附近被拦（做梦部）
    if 0.55 <= confidence < 0.65 and action == "HOLD":
        print(f"[Agent B/Evolution] 置信度{confidence:.0%}反复被 A7 门禁拦截，触发做梦部分析")

    # 触发条件3：连败保护刚解除
    if loss_streaks == 0 and memory.get("prev_loss_streaks", 0) >= 3:
        print(f"[Agent B/Evolution] 连败保护解除，强制复盘")


def _trigger_dze_chain(task_description: str):
    """
    触发 D-Z-E 开发链（按 dreambuddy-os SKILL 第七步定义）

    调用 3-CHAIN-DEVELOPMENT/scripts/chain_guard.py
    """
    import subprocess

    guard_path = CHAIN_DEV_SCRIPTS / "chain_guard.py"
    if not guard_path.exists():
        print(f"[Agent B/DZE] chain_guard.py 不存在，跳过: {guard_path}")
        return

    print(f"[Agent B/DZE] 触发 D-Z-E 开发链: {task_description[:80]}")

    # 初始化新任务
    try:
        result = subprocess.run(
            ["python3", str(guard_path), "init", task_description],
            cwd=str(CHAIN_DEV_SCRIPTS),
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            print(f"[Agent B/DZE] D-Z-E 初始化成功 ✅")
            print(f"  输出: {result.stdout[:200] if result.stdout else '(无)'}")
        else:
            print(f"[Agent B/DZE] D-Z-E 初始化失败 ❌: {result.stderr[:200] if result.stderr else result.stdout[:200]}")
    except Exception as e:
        print(f"[Agent B/DZE] 调用失败: {e}")


def _save_and_push_logs(cycle_id: str, log_data: dict):
    """
    保存决策日志并提交到 GitHub（按 dreambuddy-os SKILL 第六步定义）
    注意：DecisionLog.save() 已保存到 logs/agent_b/，这里只负责 git push
    """
    import subprocess

    repo_root = Path(__file__).parent.parent.parent
    log_dir = Path(__file__).parent.parent / "logs" / "agent_b"

    if not GH_TOKEN:
        print(f"[Agent B/Logs] 未配置 GH_TOKEN，跳过 git push")
        return

    log_file = log_dir / f"{cycle_id}.json"
    if not log_file.exists():
        print(f"[Agent B/Logs] 日志文件不存在: {log_file}")
        return

    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=repo_root, check=False)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=repo_root, check=False)

        rel_path = log_file.relative_to(repo_root)
        subprocess.run(["git", "add", str(rel_path)], cwd=repo_root, check=False)
        r = subprocess.run(
            ["git", "commit", "-m", f"chore(agent-b): save decision log {cycle_id[:8]}"],
            cwd=repo_root, capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"[Agent B/Logs] commit 成功 ✅")
            remote_url = f"https://x-access-token:{GH_TOKEN}@github.com/yunya1991/Dreambuddy-V2.git"
            pr = subprocess.run(
                ["git", "push", remote_url, "HEAD"],
                cwd=repo_root, capture_output=True, text=True, timeout=30
            )
            if pr.returncode == 0:
                print(f"[Agent B/Logs] push 成功 ✅")
            else:
                print(f"[Agent B/Logs] push 失败 ❌: {pr.stderr[:200]}")
        else:
            print(f"[Agent B/Logs] commit 跳过（无变更或失败）")
    except Exception as e:
        print(f"[Agent B/Logs] Git 操作异常: {e}")


if __name__ == "__main__":
    run()
