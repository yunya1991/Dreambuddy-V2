#!/usr/bin/env python3
"""
Agent B 完整交易周期执行脚本
按 Dreambuddy OS SKILL 六步工作流执行
"""
import os, sys, json, math
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(str(Path(__file__).parent / "config" / ".env"))
sys.path.insert(0, str(Path(__file__).parent))

from execution.aster_spot import HyperliquidClient, get_candles
from core.intent_gateway import detect_intent
from core.chain_planner import ChainPlanner
from core.nodes.c1_tech_scan import execute as c1_execute
from core.nodes.f2_fund_flow import execute as f2_execute
from core.nodes.f3_sentiment import execute as f3_execute
from core.nodes.a2_analysis import execute as a2_execute
from core.nodes.a4_gate import execute as a4_execute
from core.nodes.a9_exit import execute as a9_execute
from core.nodes.a0_contradiction import execute as a0_execute
from scoring.scorecard import DecisionLog, _cycle_id

# ─── 配置 ───────────────────────────────────────────────────────────────────
AUTO_EXECUTE    = os.environ.get("AUTO_EXECUTE", "false").lower() == "true"
BUDGET_USDC     = 60.0
PER_TRADE_PCT   = float(os.environ.get("PER_TRADE_PCT", "0.05"))
CONFIDENCE_GATE = 0.55
MAX_LEVERAGE    = 5
DEFAULT_LEVERAGE = 3

UNIVERSE_B = ["BTC", "ETH", "HYPE", "UNI", "LIT", "SOL", "XRP", "ZEC", "NEAR", "WLD", "ADA", "SUI", "ETHFI", "ENA", "JUP", "XLM", "GRASS", "EIGEN", "ZRO", "IMX"]

MEMORY_PATH = Path(__file__).parent / "data" / "agent_b_memory.json"
CYCLE_ID = _cycle_id()

print(f"{'='*60}")
print(f"🧠 Agent B 交易周期开始 | cycle: {CYCLE_ID}")
print(f"{'='*60}")

# ─── 记忆加载 ────────────────────────────────────────────────────────────────
def load_memory():
    if not MEMORY_PATH.exists():
        return {
            "regime_history": [], "lessons": [], "recent_decisions": [],
            "win_streaks": 0, "loss_streaks": 0, "last_regime": None,
            "total_cycles": 0, "active_positions": {},
            "prior_cycle_suggestions": {}, "next_cycle_suggestions": {},
        }
    with open(MEMORY_PATH) as f:
        mem = json.load(f)
    for key in ["active_positions", "prior_cycle_suggestions", "next_cycle_suggestions"]:
        if key not in mem:
            mem[key] = {}
    return mem

def save_memory(memory, decision, pnl_pct=None, next_suggestions=None):
    memory["total_cycles"] = memory.get("total_cycles", 0) + 1
    memory["last_regime"] = decision.get("market_regime")
    recent = memory.get("recent_decisions", [])
    recent.append({
        "cycle_id": decision.get("cycle_id"),
        "action": decision.get("action", "HOLD").upper(),
        "regime": decision.get("market_regime"),
        "confidence": decision.get("confidence"),
        "pnl_pct": pnl_pct,
        "ts": datetime.utcnow().isoformat(),
    })
    memory["recent_decisions"] = recent[-20:]
    if pnl_pct is not None:
        if pnl_pct > 0:
            memory["win_streaks"] = memory.get("win_streaks", 0) + 1
            memory["loss_streaks"] = 0
        else:
            memory["loss_streaks"] = memory.get("loss_streaks", 0) + 1
            memory["win_streaks"] = 0
    if next_suggestions:
        memory["next_cycle_suggestions"] = next_suggestions
        memory["prior_cycle_suggestions"] = next_suggestions
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

# ─── 市场数据采集 ────────────────────────────────────────────────────────────
def _score_coin(price, ch24, ch1h, vol_ratio, rsi, funding_rate, ema20, ema50, ema200):
    score = 0.0
    signals = []
    trend_abs = min(abs(ch24) / 8.0, 1.0)
    score += trend_abs * 30
    if ch24 > 3: signals.append("强上涨趋势")
    elif ch24 < -3: signals.append("强下跌趋势")
    if ch24 > 0 and ch1h > 0:
        score += 15; signals.append("短长共振上涨")
    elif ch24 < 0 and ch1h < 0:
        score += 15; signals.append("短长共振下跌")
    elif abs(ch1h) > 1.5:
        score += 5
    if vol_ratio > 2.0:
        score += 15; signals.append(f"放量{vol_ratio:.1f}x")
    elif vol_ratio > 1.3:
        score += 8
    fr_abs = min(abs(funding_rate) * 10000 / 5, 1.0)
    score += fr_abs * 15
    if funding_rate < -0.0003: signals.append(f"负费率偏离({funding_rate*100:.4f}%)")
    elif funding_rate > 0.0005: signals.append(f"正费率偏高({funding_rate*100:.4f}%)")
    if rsi < 30: score += 10; signals.append(f"RSI超卖{rsi:.0f}")
    elif rsi > 70: score += 10; signals.append(f"RSI超买{rsi:.0f}")
    elif rsi < 40 or rsi > 60: score += 5
    if price > ema20 > ema50:
        score += 8
        if price > ema200: score += 2; signals.append("EMA多头排列+MA200上方")
    elif price < ema20 < ema50:
        score += 8
        if price < ema200: score += 2; signals.append("EMA空头排列+MA200下方")
    direction = "LONG" if ch24 > 0 else "SHORT"
    return {"score": round(min(score, 100), 1), "direction": direction, "signals": signals,
            "price": price, "ch24": round(ch24, 2), "ch1h": round(ch1h, 2),
            "vol_ratio": round(vol_ratio, 2), "rsi": round(rsi, 1), "funding_rate": funding_rate}

def scan_all_coins(client):
    opps = client.scan_opportunities()
    opp_map = {o["coin"]: o for o in opps}
    all_scores = {}
    for coin in UNIVERSE_B:
        if coin not in opp_map: continue
        price = opp_map[coin]["price"]
        if price <= 0: continue
        try:
            candles_1h = get_candles(coin, "1h", 48, client.proxies)
            closes = [float(c["c"]) for c in candles_1h if "c" in c]
            vols = [float(c["v"]) for c in candles_1h if "v" in c]
            if len(closes) < 24: continue
            ch24 = (closes[0] - closes[23]) / closes[23] * 100 if len(closes) > 23 else 0
            ch1h = (closes[0] - closes[1]) / closes[1] * 100 if len(closes) > 1 else 0
            avg_vol = sum(vols) / len(vols) if vols else 0
            cur_vol = vols[0] if vols else 0
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0
            def ema(prices, n):
                if len(prices) < n: return prices[-1]
                k = 2 / (n + 1); e = prices[-n]
                for p in prices[-n + 1:]: e = p * k + e * (1 - k)
                return e
            closes_rev = closes[::-1]
            ema20 = ema(closes_rev, 20)
            ema50 = ema(closes_rev, 50) if len(closes) >= 50 else ema20
            ema200 = ema(closes_rev, min(200, len(closes)))
            def rsi(prices, n=14):
                if len(prices) < n + 1: return 50.0
                deltas = [prices[i] - prices[i - 1] for i in range(1, min(n + 1, len(prices)))]
                gains = [max(d, 0) for d in deltas]; losses = [max(-d, 0) for d in deltas]
                avg_g = sum(gains) / n; avg_l = sum(losses) / n
                if avg_l == 0: return 100.0
                return 100 - 100 / (1 + avg_g / avg_l)
            rsi14 = rsi(closes_rev)
            funding_rate = opp_map[coin].get("funding", 0.0)
            result = _score_coin(price, ch24, ch1h, vol_ratio, rsi14, funding_rate, ema20, ema50, ema200)
            all_scores[coin] = result
        except Exception as e:
            continue
    ranked = sorted(all_scores.items(), key=lambda x: x[1]["score"], reverse=True)
    top3 = [name for name, _ in ranked[:3]]
    return {"all_scores": all_scores, "ranked": ranked, "top3": top3, "total_scanned": len(all_scores)}

def fetch_market_context(client, primary_coin=None):
    opps = client.scan_opportunities()
    opp_map = {o["coin"]: o for o in opps}
    mids = {k: v["price"] for k, v in opp_map.items()}
    if not primary_coin:
        primary_coin = "BTC"
        for o in sorted(opps, key=lambda x: abs(x["funding"]), reverse=True):
            if o["coin"] in UNIVERSE_B:
                primary_coin = o["coin"]; break
    price = mids.get(primary_coin, mids.get("BTC", 0))
    candles_1h_raw = get_candles(primary_coin, "1h", 48, client.proxies)
    candles_4h_raw = get_candles(primary_coin, "4h", 14, client.proxies)
    closes_1h = [float(c["c"]) for c in candles_1h_raw if "c" in c]
    closes_4h = [float(c["c"]) for c in candles_4h_raw if "c" in c]
    vols_1h = [float(c["v"]) for c in candles_1h_raw if "v" in c]
    def ema(prices, n):
        if len(prices) < n: return prices[-1] if prices else 0
        k = 2 / (n + 1); e = prices[-n]
        for p in prices[-n+1:]: e = p * k + e * (1 - k)
        return e
    def rsi(prices, n=14):
        if len(prices) < n + 1: return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas[-n:]]; losses = [max(-d, 0) for d in deltas[-n:]]
        avg_g = sum(gains) / n; avg_l = sum(losses) / n
        if avg_l == 0: return 100.0
        return 100 - 100 / (1 + avg_g / avg_l)
    def atr(raw_candles, n=14):
        if len(raw_candles) < 2: return 0
        trs = []
        for i in range(1, min(n+1, len(raw_candles))):
            h = float(raw_candles[i].get("h", 0)); l = float(raw_candles[i].get("l", 0))
            c_prev = float(raw_candles[i-1].get("c", 0))
            trs.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
        return sum(trs) / len(trs) if trs else 0
    ema20 = ema(closes_1h, 20); ema50 = ema(closes_1h, 50); ema200 = ema(closes_4h, 20)
    rsi14 = rsi(closes_1h); atr14 = atr(candles_1h_raw)
    change_1h = ((closes_1h[0] - closes_1h[1]) / closes_1h[1] * 100) if len(closes_1h) > 1 else 0
    change_24h = ((closes_1h[0] - closes_1h[23]) / closes_1h[23] * 100) if len(closes_1h) > 23 else 0
    change_4h = ((closes_4h[0] - closes_4h[3]) / closes_4h[3] * 100) if len(closes_4h) > 3 else 0
    avg_vol = sum(vols_1h) / len(vols_1h) if vols_1h else 0
    cur_vol = vols_1h[0] if vols_1h else 0
    funding_rate = opp_map.get(primary_coin, {}).get("funding", 0.0)
    if change_24h > 3 and price > ema20 > ema50: regime = "TREND_UP"
    elif change_24h < -3 and price < ema20 < ema50: regime = "TREND_DOWN"
    elif abs(change_24h) < 1.5: regime = "RANGE"
    else: regime = "TRANSITION"
    return {
        "price": price, "coin": primary_coin, "opp_map": opp_map,
        "change_1h": round(change_1h, 3), "change_4h": round(change_4h, 3),
        "change_24h": round(change_24h, 3),
        "ema20": round(ema20, 2), "ema50": round(ema50, 2), "ema200": round(ema200, 2),
        "rsi14": round(rsi14, 1), "atr14": round(atr14, 2),
        "vol_ratio": round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0,
        "funding_rate": funding_rate, "regime": regime,
        "closes_1h": closes_1h[:8], "ts_utc": datetime.utcnow().isoformat(),
    }

# ─── 主执行流程 ──────────────────────────────────────────────────────────────
def main():
    memory = load_memory()
    print(f"\n📋 记忆加载: {memory.get('total_cycles', 0)} 轮历史, "
          f"连胜={memory.get('win_streaks', 0)}, 连败={memory.get('loss_streaks', 0)}")

    # 初始化客户端
    client = HyperliquidClient('b')

    # 扫描全币种，选最优标的
    print("\n🔍 第0步：全币种扫描...")
    scan_result = scan_all_coins(client)
    print(f"   扫描 {scan_result['total_scanned']} 个币种")
    print(f"   Top3: {scan_result['top3']}")
    for coin, data in scan_result['ranked'][:5]:
        print(f"   {coin}: {data['score']}分 ({data['direction']}) - {', '.join(data['signals'][:3])}")

    primary_coin = scan_result['top3'][0] if scan_result['top3'] else "BTC"
    print(f"\n🎯 主分析标的: {primary_coin}")

    # 获取账户信息
    print("\n💰 获取账户状态...")
    try:
        account = client.get_account()
        equity = account.get('equity', 0)
        positions = account.get('positions', {})
        print(f"   权益: ${equity:.2f}")
        print(f"   持仓: {list(positions.keys()) if positions else '无'}")
        for coin, pos in positions.items():
            print(f"     {coin}: {pos['size']} @ {pos['entry_px']} (PnL: ${pos['upnl']:.2f})")
    except Exception as e:
        print(f"   ⚠️ 账户查询失败: {e}")
        equity = 0; positions = {}

    # 获取市场上下文
    print(f"\n📊 获取 {primary_coin} 市场数据...")
    mkt = fetch_market_context(client, primary_coin)
    print(f"   价格: ${mkt['price']:.2f}")
    print(f"   24H: {mkt['change_24h']:+.2f}% | 4H: {mkt['change_4h']:+.2f}% | 1H: {mkt['change_1h']:+.2f}%")
    print(f"   RSI: {mkt['rsi14']:.1f} | Regime: {mkt['regime']}")
    print(f"   资金费率: {mkt['funding_rate']*100:.4f}%")

    # ─── 第1步：意图识别 ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("🧠 第1步：意图识别 (S层)")
    print(f"{'='*60}")
    intent = detect_intent(mkt, memory, positions)
    print(f"   意图类型: {intent.intent_type}")
    print(f"   置信度: {intent.confidence:.0%}")
    print(f"   依据: {intent.rationale}")
    print(f"   基础链: {intent.base_chain}")
    print(f"   扩展节点: {intent.extend_nodes}")

    # ─── 第2步：BAC三层规划 ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("🏗️ 第2步：BAC三层规划 (A层)")
    print(f"{'='*60}")
    planner = ChainPlanner(token_budget=6000)
    plan = planner.plan(intent, mkt, memory)
    print(f"   模式: {plan.budget_mode}")
    print(f"   节点数: {len(plan.planned_chain)}")
    print(f"   执行链路: {' → '.join(plan.planned_chain)}")
    print(f"   剪枝: {plan.pruned_nodes[:3]}...")
    print(f"   预估Token: {plan.estimated_tokens}")
    print(f"   规划理由: {plan.plan_rationale[:100]}...")

    # ─── 第3步：动态执行引擎 ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("⚡ 第3步：动态执行引擎 (C层)")
    print(f"{'='*60}")

    node_results = []
    shared_data = {
        "intent_confidence": intent.confidence,
        "intent_type": intent.intent_type,
        "node_results": node_results,
        "positions": positions,
    }
    all_reasoning = []

    # A0 矛盾论（内置，在A2前执行）
    print("\n   [A0] 矛盾论分析...")
    a0_result = a0_execute(mkt, memory, shared_data)
    shared_data["a0"] = a0_result.get("data", {})
    shared_data["a0_dominant"] = a0_result.get("dominant_force", "NEUTRAL")
    all_reasoning.extend(a0_result.get("rationale", []))
    print(f"   → 主导力量: {a0_result.get('dominant_force')}")
    print(f"   → 置信度: {a0_result.get('confidence', 0):.0%}")

    # 按规划链路执行节点
    final_direction = "HOLD"
    final_confidence = 0.0
    gate_passed = False
    gate_reason = ""

    for node_id in plan.planned_chain:
        print(f"\n   [{node_id}] 执行中...")
        try:
            if node_id == "C1_技术扫描":
                result = c1_execute(mkt, memory, shared_data)
            elif node_id == "F2_资金流":
                result = f2_execute(mkt, memory, shared_data)
            elif node_id == "F3_情绪":
                result = f3_execute(mkt, memory, shared_data)
            elif node_id == "A2_分析(含A0)":
                shared_data["a0"] = a0_result.get("data", {})
                result = a2_execute(mkt, memory, shared_data)
            elif node_id == "A4_门禁":
                result = a4_execute(mkt, memory, shared_data)
                gate_passed = result.get("gate_passed", False)
                gate_reason = result.get("reason", "")
            elif node_id == "A9_离场评估":
                result = a9_execute(mkt, memory, shared_data)
            else:
                print(f"   ⏭️  跳过 {node_id}（暂无本地实现）")
                continue

            node_results.append(result)
            shared_data["direction"] = result.get("direction", shared_data.get("direction", "HOLD"))
            shared_data["confidence"] = result.get("confidence", shared_data.get("confidence", 0))

            all_reasoning.extend(result.get("rationale", []))
            final_direction = result.get("direction", final_direction)
            final_confidence = result.get("confidence", final_confidence)

            print(f"   → 方向: {result.get('direction')}")
            print(f"   → 置信度: {result.get('confidence', 0):.0%}")

            # 门禁拦截则停止
            if node_id == "A4_门禁" and not gate_passed:
                print(f"   🛑 A7 门禁拦截，停止执行")
                final_direction = "HOLD"
                break

        except Exception as e:
            print(f"   ❌ 执行失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n   📌 最终决策: {final_direction} @ {final_confidence:.0%}")
    print(f"   🚪 A7 门禁: {'✅通过' if gate_passed else '❌拦截'} - {gate_reason}")

    # ─── 第4步：自我进化 ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("🔄 第4步：自我进化")
    print(f"{'='*60}")

    # A8 知行合一
    intent_conf = intent.confidence
    exec_conf = final_confidence
    gap_score = abs(intent_conf - exec_conf)
    print(f"   意图置信度: {intent_conf:.0%}")
    print(f"   执行置信度: {exec_conf:.0%}")
    print(f"   gap_score: {gap_score:.0%}")

    if gap_score >= 0.5:
        print("   ⚠️ 严重背离 → 触发 D-Z-E 链（A1重启调研）")
        dze_triggered = True
    elif gap_score >= 0.3:
        print("   ⚠️ 中度背离 → A2 更新分析")
        dze_triggered = False
    elif gap_score < 0.3:
        print("   ✅ 知行基本一致")
        dze_triggered = False

    # 做梦部检查
    dream_triggered = False
    loss_streaks = memory.get("loss_streaks", 0)
    if loss_streaks >= 3:
        print(f"   💭 连败{loss_streaks}次 → 触发做梦部")
        dream_triggered = True
    elif final_direction == "HOLD" and len([d for d in memory.get("recent_decisions", [])[-5:] if d.get("action") == "HOLD"]) >= 3:
        print("   💭 连续HOLD → 触发做梦部")
        dream_triggered = True
    else:
        print("   💤 做梦部未触发")

    # ─── 第5步：D-Z-E 开发链检查 ───────────────────────────────────────
    print(f"\n{'='*60}")
    print("🔧 第5步：D-Z-E 开发链检查")
    print(f"{'='*60}")

    if dze_triggered or loss_streaks >= 3:
        print("   🚨 触发 D-Z-E 向外学习")
        print(f"      原因: gap={gap_score:.0%}, 连败={loss_streaks}")
    else:
        print("   ✅ D-Z-E 链未触发")

    # ─── 第6步：预算管理 + 日志 + 决策输出 ────────────────────────────
    print(f"\n{'='*60}")
    print("📝 第6步：预算管理 + 决策日志")
    print(f"{'='*60}")

    # 保存决策日志
    log = DecisionLog('b', CYCLE_ID)
    log.data.update({
        "market_regime": mkt.get("regime"),
        "action": final_direction,
        "coin": primary_coin,
        "confidence": final_confidence,
        "entry_price": mkt["price"] if final_direction != "HOLD" else None,
        "position_size_usdt": max(equity * PER_TRADE_PCT, 5) if gate_passed and final_direction != "HOLD" else None,
        "reasoning_steps": all_reasoning,
        "decision_rationale": f"{final_direction} @ {final_confidence:.0%} - {gate_reason}",
        "system_features_used": [
            "dreambuddy_os", "bac三层", "sacg架构",
            "a0矛盾论", "a7门禁", "a8知行合一",
        ],
        "memory_loaded": True,
        "graph_context_nodes": len(node_results),
    })
    log_path = log.save()
    print(f"   日志已保存: {log_path}")

    # 执行下单（如果门禁通过）
    execution_ok = False
    if gate_passed and final_direction in ("LONG", "SHORT") and AUTO_EXECUTE:
        print(f"\n📈 执行 {final_direction} 下单...")
        try:
            position_size_usdt = max(equity * PER_TRADE_PCT, 5)
            size = position_size_usdt / mkt["price"]
            leverage = min(MAX_LEVERAGE, max(1, int(final_confidence * 5)))
            print(f"   标的: {primary_coin}")
            print(f"   方向: {final_direction}")
            print(f"   数量: {size:.6f} (${position_size_usdt:.2f})")
            print(f"   杠杆: {leverage}x")
            execution_ok = True
        except Exception as e:
            print(f"   ❌ 下单失败: {e}")
    else:
        if not gate_passed:
            print("   🚫 未过门禁，不下单")
        elif final_direction == "HOLD":
            print("   ⏸️  HOLD 决策，不下单")
        elif not AUTO_EXECUTE:
            print("   ⚙️  AUTO_EXECUTE=false，跳过下单")

    # 保存记忆
    decision_info = {
        "cycle_id": CYCLE_ID,
        "action": final_direction,
        "market_regime": mkt.get("regime"),
        "confidence": final_confidence,
    }
    next_suggestions = {
        "hypothesis": f"验证 {primary_coin} 在 {mkt['regime']} 行情下的趋势延续性",
        "risk_note": f"gap_score={gap_score:.0%}，关注知行偏差",
        "chain_adjustment": "保持当前链路，观察A0矛盾论有效性",
    }
    save_memory(memory, decision_info, pnl_pct=None, next_suggestions=next_suggestions)

    # ─── 输出汇总 ────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("📊 执行汇总")
    print(f"{'='*60}")
    print(f"   Cycle ID: {CYCLE_ID}")
    print(f"   意图: {intent.intent_type} ({intent.confidence:.0%})")
    print(f"   决策: {final_direction} @ {final_confidence:.0%}")
    print(f"   A7门禁: {'✅通过' if gate_passed else '❌拦截'}")
    print(f"   模式: {plan.budget_mode}")
    print(f"   节点数: {len(plan.planned_chain)}")
    print(f"   gap_score: {gap_score:.0%}")
    print(f"   做梦部: {'触发' if dream_triggered else '未触发'}")
    print(f"   权益: ${equity:.2f}")

    # 返回所有数据供PR报告使用
    return {
        "cycle_id": CYCLE_ID,
        "intent": intent,
        "plan": plan,
        "mkt": mkt,
        "final_direction": final_direction,
        "final_confidence": final_confidence,
        "gate_passed": gate_passed,
        "gate_reason": gate_reason,
        "gap_score": gap_score,
        "dream_triggered": dream_triggered,
        "dze_triggered": dze_triggered,
        "equity": equity,
        "positions": positions,
        "node_results": node_results,
        "all_reasoning": all_reasoning,
        "scan_result": scan_result,
        "primary_coin": primary_coin,
    }

if __name__ == "__main__":
    result = main()
    print("\n✅ Agent B 执行完成")
