#!/usr/bin/env python3
"""
Agent A Runner — 完整升级版
集成：
  - Agent A 交易 SKILL（六维分析框架）
  - 三级 LLM 回退：Trae → DeepSeek V4 → 基本规则
  - 记忆系统：Lessons、交易记录、大师切换、连胜连败
  - 风险控制：止损止盈、连败保护、最大回撤保护
  - PR 评论同步：执行后写评论到固定交易 PR

每轮执行流程：
  1. 加载记忆 + 账户状态
  2. 扫描市场数据
  3. 调用 LLM（按 SKILL 框架）做决策
  4. 执行交易（AUTO_EXECUTE=true 时）
  5. 更新记忆 + Lessons
  6. 评估是否切换大师风格
  7. 自主调度（申请提前触发）
  8. 同步评论到 GitHub PR（可选）
"""
import os, sys, json, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / "config" / ".env"))

sys.path.insert(0, str(Path(__file__).parent.parent))
from execution.aster_spot import HyperliquidClient, scan_opportunities, get_candles
from scoring.scorecard import DecisionLog, _cycle_id
from orchestrator import request_early_run
from core.agent_a_memory import (
    load_memory, save_memory, add_lesson, record_trade,
    update_equity_stats, maybe_switch_master, get_top_lessons,
    record_closed_trade, update_hold_streak, get_evolution_params,
)
from core.exit_module import run_exit_check, init_position, update_position_exit_levels
from core.agent_a_llm import agent_a_llm_decide, get_quota_status, get_available_provider

# ── 配置 ───────────────────────────────────────────────────────────────────
AUTO_EXECUTE  = os.environ.get("AUTO_EXECUTE", "false").lower() == "true"
BUDGET_USDC   = 60.0
PER_TRADE_PCT = float(os.environ.get("PER_TRADE_PCT", "0.05"))
DEFAULT_LEV   = 3
STOP_LOSS_PCT = 0.04
TP_PCT        = 0.08

UNIVERSE_A = [
    "BTC", "ETH", "HYPE", "UNI",
    "LIT", "SOL", "XRP", "ZEC", "NEAR", "WLD", "ADA", "SUI", "ETHFI", "ENA", "JUP", "XLM", "GRASS", "EIGEN", "ZRO", "IMX",
]


# ── 市场数据采集 ──────────────────────────────────────────────────────────

def fetch_market_context(client: HyperliquidClient) -> dict:
    """采集所有标的的市场数据（1H K线 + 资金费率）"""
    opps = client.scan_opportunities()
    mids = {o["coin"]: o["price"] for o in opps}

    coin_data = {}
    for coin in UNIVERSE_A:
        price = mids.get(coin, 0)
        if price <= 0:
            continue
        try:
            candles = get_candles(coin, "1h", 48, client.proxies)
            closes  = [float(c["c"]) for c in candles if "c" in c]
            vols    = [float(c["v"]) for c in candles if "v" in c]
        except Exception:
            closes, vols = [], []

        ch24 = ((closes[0] - closes[23]) / closes[23] * 100) if len(closes) > 23 else 0
        ch4h = ((closes[0] - closes[3])  / closes[3]  * 100) if len(closes) > 3  else 0
        ch1h = ((closes[0] - closes[1])  / closes[1]  * 100) if len(closes) > 1  else 0

        avg_vol = sum(vols) / len(vols) if vols else 0
        cur_vol = vols[0] if vols else 0

        # 简化 EMA 计算
        def ema(prices, n):
            if not prices or n <= 0:
                return prices[-1] if prices else 0
            if len(prices) < n:
                return prices[-1]
            k = 2 / (n + 1)
            e = prices[-n]
            for p in prices[-n+1:]:
                e = p * k + e * (1 - k)
            return e

        ema20  = ema(closes[::-1], 20)
        ema50  = ema(closes[::-1], 50) if len(closes) >= 50 else ema20
        ema200 = ema(closes[::-1], min(200, len(closes)))

        # RSI(14) — 使用最新数据
        def rsi(prices, n=14):
            if len(prices) < n + 1:
                return 50.0
            # 取最新 n+1 根 K 线计算差分
            recent = prices[-(n+1):]
            deltas = [recent[i] - recent[i-1] for i in range(1, len(recent))]
            gains  = [max(d, 0) for d in deltas]
            losses = [max(-d, 0) for d in deltas]
            avg_g  = sum(gains) / n
            avg_l  = sum(losses) / n
            if avg_l == 0:
                return 100.0
            rs = avg_g / avg_l
            return 100 - 100 / (1 + rs)

        rsi14 = rsi(closes[::-1])

        coin_data[coin] = {
            "price":     price,
            "ch24":      round(ch24, 2),
            "ch4h":      round(ch4h, 2),
            "ch1h":      round(ch1h, 2),
            "vol_ratio": round(cur_vol / avg_vol, 2) if avg_vol > 0 else 1.0,
            "ema20":     round(ema20, 2),
            "ema50":     round(ema50, 2),
            "ema200":    round(ema200, 2),
            "rsi14":     round(rsi14, 1),
        }

    opp_map = {o["coin"]: o for o in opps}

    return {
        "coins":   coin_data,
        "opp_map": opp_map,
        "ts_utc":  datetime.utcnow().isoformat(),
    }


# ── 主流程 ────────────────────────────────────────────────────────────────

def run():
    cycle = _cycle_id()
    print(f"{'='*60}")
    print(f"[Agent A] 启动 cycle={cycle}")
    print(f"{'='*60}")

    # ── 1. 加载记忆 ───────────────────────────────────────────────
    memory = load_memory()
    top_lessons = get_top_lessons(memory, 10)
    evolution_params = get_evolution_params(memory)
    print(f"[记忆] 当前大师: {memory['current_master']}")
    print(f"[记忆] 总交易: {memory['total_trades']} | "
          f"连胜: {memory['win_streak']} | 连败: {memory['loss_streak']}")
    print(f"[记忆] Lessons: {len(memory['lessons'])} 条 | "
          f"最大回撤: {memory.get('max_drawdown_pct', 0):.1f}%")
    if evolution_params:
        print(f"[进化] 已采纳参数: {evolution_params}")
    print(f"[LLM]  可用: {get_available_provider()} | 配额: {get_quota_status()}")

    # ── 2. 获取账户状态 ───────────────────────────────────────────
    client = HyperliquidClient("a")
    sim_mode = False
    try:
        acct = client.get_account()
        if not acct.get("ok"):
            raise ValueError("账户查询失败")
        equity = acct["equity"]
        positions = acct.get("positions", {})
    except Exception as e:
        # 模拟模式：无有效账户时使用虚拟资金
        sim_mode = True
        equity = max(memory.get("peak_equity", BUDGET_USDC), BUDGET_USDC)
        positions = {}
        print(f"[账户] 模拟模式（无有效账户）: {e}")
    print(f"[账户] 权益: {equity:.2f} USDC | 持仓: {list(positions.keys()) or '无'} | 模式: {'模拟' if sim_mode else '实盘'}")

    # 更新权益统计
    memory = update_equity_stats(memory, equity)

    # 确保 active_positions 存在（旧版本兼容）
    if "active_positions" not in memory:
        memory["active_positions"] = {}

    # ── 2.5 L1 离场检查（基础止损止盈 + 移动止损）──────────────────────
    print(f"\n[离场] L1 基础离场检查...")
    acct_for_exit = acct if not sim_mode else None
    memory["active_positions"], closed_trades = run_exit_check(
        client, memory.get("active_positions", {}),
        agent_id="a", enable_trailing=True,
        account_data=acct_for_exit,
    )
    if closed_trades:
        for ct in closed_trades:
            print(f"[离场] 平仓 {ct['coin']}: {ct['exit_reason']} "
                  f"PnL={ct['pnl_pct']*100:+.2f}% "
                  f"@ {ct['exit_price']}")
            memory = record_closed_trade(memory, ct, 0.0, memory["current_master"])
    else:
        print(f"[离场] 无触发，当前持仓: {list(memory['active_positions'].keys()) or '无'}")

    # 最大回撤保护：回撤≥15% 暂停交易
    max_dd = memory.get("max_drawdown_pct", 0)
    if max_dd >= 15:
        print(f"[风控] 最大回撤{max_dd:.1f}%≥15%，暂停交易，全面复盘")
        log = DecisionLog("a", cycle)
        log.data.update({
            "action": "HOLD",
            "confidence": 0,
            "reasoning_steps": [f"最大回撤保护：{max_dd:.1f}%≥15%，强制暂停"],
            "decision_rationale": "最大回撤保护触发",
            "memory_loaded": True,
            "system_features_used": ["max_drawdown_protection"],
        })
        path = log.save()
        save_memory(memory)
        print(f"[Agent A] 日志: {path}")
        return log.data

    # ── 3. 扫描市场 ──────────────────────────────────────────────
    mkt = fetch_market_context(client)
    print(f"[市场] 扫描到 {len(mkt['coins'])} 个标的")

    # ── 4. LLM 决策（三级回退）───────────────────────────────────
    account_data = {
        "equity": equity,
        "positions": positions,
        "active_positions": memory.get("active_positions", {}),
    }

    print(f"\n[决策] 调用 LLM 进行决策（SKILL 框架）...")
    decision, provider = agent_a_llm_decide(mkt, memory, account_data, max_tokens=8000)
    print(f"[决策] Provider: {provider}")
    print(f"[决策] 结果: {decision.get('action')} {decision.get('coin','')} "
          f"conf={decision.get('confidence',0):.0%}")
    print(f"[决策] 理由: {decision.get('decision_rationale','')[:80]}")

    # 连续HOLD检测：超过10轮HOLD时降低入场门槛，打破保守死循环
    hold_streak = memory.get("hold_streak", 0)
    if hold_streak >= 10 and decision.get("action") == "HOLD":
        print(f"[风控] 连续{hold_streak}轮HOLD，降低入场门槛以打破保守循环")
        _break_conservative_loop(decision, mkt, memory, account_data)

    # 连败保护：连败≥3 时强制 HOLD（即使 LLM 说要做）
    if memory.get("loss_streak", 0) >= 3 and decision.get("action") != "HOLD":
        print(f"[风控] 连败{memory['loss_streak']}次，强制观望一轮")
        decision["action"] = "HOLD"
        decision["confidence"] = 0
        decision["reasoning_steps"] = decision.get("reasoning_steps", []) + [
            f"连败保护：已连败{memory['loss_streak']}次，本轮强制观望"
        ]
        decision["decision_rationale"] = "连败保护触发，强制HOLD"

    # ── 4.5 L2 智能离场（LLM 给出持仓调整建议）───────────────────────
    smart_exits = []
    active_pos = memory.get("active_positions", {})
    if active_pos and AUTO_EXECUTE and not sim_mode:
        # 检查 LLM 是否给出了离场建议
        exit_suggestions = decision.get("exit_suggestions", [])
        update_suggestions = decision.get("update_exit_levels", [])

        # 处理主动离场建议
        for sug in exit_suggestions:
            coin = sug.get("coin")
            reason = sug.get("reason", "LLM_SIGNAL_EXIT")
            if coin and coin in active_pos:
                from core.exit_module import execute_exit
                memory["active_positions"], closed_info, exec_res = execute_exit(
                    client, memory["active_positions"], coin,
                    f"SMART_{reason[:20]}", tag=f"a_exit_smart"
                )
                if closed_info:
                    smart_exits.append(closed_info)
                    memory = record_closed_trade(
                        memory, closed_info, decision.get("confidence", 0),
                        memory["current_master"]
                    )
                    print(f"[离场] L2智能平仓 {coin}: {reason} "
                          f"PnL={closed_info['pnl_pct']*100:+.2f}%")

        # 处理止损止盈调整建议
        for sug in update_suggestions:
            coin = sug.get("coin")
            new_sl = sug.get("new_stop_loss")
            new_tp = sug.get("new_take_profit")
            if coin and coin in memory["active_positions"]:
                memory["active_positions"] = update_position_exit_levels(
                    memory["active_positions"], coin, new_sl, new_tp,
                    sl_source="llm_smart", tp_source="llm_smart",
                    client=client if (not sim_mode and AUTO_EXECUTE) else None
                )
                print(f"[离场] L2调整 {coin}: SL→{new_sl}, TP→{new_tp}")

    # ── 5. 执行交易 ──────────────────────────────────────────────
    action = decision.get("action", "HOLD")
    coin = decision.get("coin")
    conf = decision.get("confidence", 0)
    leverage = int(decision.get("leverage", DEFAULT_LEV))
    leverage = min(5, max(1, leverage))
    pos_usdt = float(decision.get("position_size_usdt", 0))

    exec_result = None
    if not sim_mode and AUTO_EXECUTE and action in ("LONG", "SHORT") and coin and pos_usdt > 0:
        effective_equity = min(equity, BUDGET_USDC)
        pos_usdt = max(min(pos_usdt, effective_equity * PER_TRADE_PCT), 5.0)
        tag = f"a_{cycle[:8]}"

        if action == "LONG":
            exec_result = client.open_long(coin, pos_usdt, leverage, tag)
        else:
            exec_result = client.open_short(coin, pos_usdt, leverage, tag)

        print(f"[执行] {action} {coin} {pos_usdt} USDC × {leverage}x")
        print(f"[执行] 结果: ok={exec_result.get('ok')} filled={exec_result.get('filled')}")

        # 开仓成功后初始化 active_positions（L1 基础离场）
        if exec_result.get("ok"):
            entry_px = decision.get("entry_price", 0) or client.get_mid_price(coin)
            custom_sl = decision.get("stop_loss_price")
            custom_tp = decision.get("take_profit_price")
            memory["active_positions"] = init_position(
                memory.get("active_positions", {}),
                coin=coin,
                entry_price=entry_px,
                action=action,
                position_size_usdt=pos_usdt,
                leverage=leverage,
                stop_loss_price=custom_sl,
                take_profit_price=custom_tp,
                cycle_id=cycle,
                proxies=client.proxies,
                client=client,
            )
            pos_info = memory["active_positions"][coin]
            print(f"[离场] L1 预设: SL={pos_info['stop_loss_price']} "
                  f"({pos_info['sl_source']}), "
                  f"TP={pos_info['take_profit_price']} "
                  f"({pos_info['tp_source']})")
    elif sim_mode and action in ("LONG", "SHORT") and coin and pos_usdt > 0:
        effective_equity = min(equity, BUDGET_USDC)
        pos_usdt = max(min(pos_usdt, effective_equity * PER_TRADE_PCT), 5.0)
        print(f"[执行] [模拟] {action} {coin} {pos_usdt} USDC × {leverage}x（模拟模式，不下单）")
    else:
        print(f"[执行] 跳过（模式:{'模拟' if sim_mode else '实盘'}, AUTO_EXECUTE={AUTO_EXECUTE}, action={action}）")

    # ── 6. 记录决策日志 ──────────────────────────────────────────
    log = DecisionLog("a", cycle)
    log.data.update({
        "market_regime":       decision.get("market_regime", "UNKNOWN"),
        "reasoning_steps":     decision.get("reasoning_steps", []),
        "confidence":          conf,
        "action":              action,
        "coin":                coin,
        "leverage":            leverage,
        "entry_price":         decision.get("entry_price"),
        "position_size_usdt":  pos_usdt,
        "stop_loss_price":     decision.get("stop_loss_price"),
        "take_profit_price":   decision.get("take_profit_price"),
        "decision_rationale":  decision.get("decision_rationale", ""),
        "system_features_used": [
            f"llm_provider:{provider}",
            "skill:agent-a-trading",
            "memory_system",
            "exit_module:l1+l2",
            "master_style:" + str(decision.get("current_master", memory["current_master"])),
            "sim_mode" if sim_mode else "live_mode",
        ],
        "memory_loaded":       True,
        "sim_mode":            sim_mode,
        "current_master":      decision.get("current_master", memory["current_master"]),
        "llm_provider":        provider,
        "top_lessons":         [l["content"] for l in top_lessons[:5]],
        "active_positions":    memory.get("active_positions", {}),
        "smart_exits":         smart_exits,
    })
    if exec_result:
        log.data["execution"] = exec_result

    path = log.save()
    print(f"\n[日志] 已保存: {path}")

    # ── 7. 更新记忆 ──────────────────────────────────────────────
    # 处理新 lesson
    new_lesson = decision.get("new_lesson", "")
    if new_lesson:
        u = int(decision.get("lesson_score_universal", 3))
        i = int(decision.get("lesson_score_importance", 3))
        memory = add_lesson(memory, new_lesson, universality=u, importance=i)
        print(f"[记忆] 新 Lesson: {new_lesson[:50]} (score={u*i})")

    # 处理大师切换
    switch_reason = decision.get("master_switch_reason", "")
    new_master = decision.get("current_master", memory["current_master"])
    if switch_reason and new_master != memory.get("current_master"):
        memory["current_master"] = new_master
        print(f"[记忆] 大师切换: {memory.get('current_master')} → {new_master}")
        print(f"[记忆] 切换原因: {switch_reason}")

    # 如果开仓了，记录交易（exit_price 先填 entry，pnl 先为0，后续平仓更新）
    if action in ("LONG", "SHORT") and coin:
        entry_px = decision.get("entry_price", 0)
        memory = record_trade(
            memory,
            coin=coin,
            action=action,
            entry_price=entry_px,
            exit_price=None,
            pnl_pct=0,
            confidence=conf,
            master=decision.get("current_master", memory["current_master"]),
            lesson=decision.get("decision_rationale", "")[:80],
        )

    # 根据市场环境评估是否切换大师
    regime = decision.get("market_regime", "RANGE")
    memory = maybe_switch_master(memory, regime)

    # 更新连续HOLD计数
    memory = update_hold_streak(memory, action)
    print(f"[记忆] 连续HOLD: {memory.get('hold_streak', 0)} 轮")

    save_memory(memory)
    print(f"[记忆] 已更新并保存")

    # ── 8. 自主调度 ──────────────────────────────────────────────
    _self_schedule(decision, mkt, memory)

    # ── 9. 同步到 GitHub PR 评论（可选） ─────────────────────────
    _post_to_github_pr(log.data, sim_mode)

    print(f"\n{'='*60}")
    print(f"[Agent A] 本轮完成 | action={action} | provider={provider}")
    print(f"{'='*60}")
    return log.data


# ── 打破保守循环机制 ──────────────────────────────────────────────────────

def _break_conservative_loop(decision: dict, mkt: dict, memory: dict, account_data: dict):
    """
    当连续多轮HOLD时，降低入场门槛，强制寻找交易机会
    机制：使用简化规则引擎，选择评分最高的标的（即使低于常规门槛）
    使用进化参数动态调整阈值
    """
    from core.agent_a_memory import get_evolution_params
    evo_params = get_evolution_params(memory)

    coins = mkt.get("coins", {})
    opp_map = mkt.get("opp_map", {})
    
    best_coin = None
    best_score = 0
    best_side = "LONG"
    best_info = {}
    
    # 使用进化参数，回退到默认值
    mom_threshold = evo_params.get("momentum_threshold", 0.02)
    vol_threshold = evo_params.get("volume_threshold", 1.2)
    rsi_oversold = evo_params.get("rsi_oversold", 40)
    rsi_overbought = evo_params.get("rsi_overbought", 60)
    use_ema_cross = evo_params.get("use_ema_cross", True)
    
    for coin, d in coins.items():
        score = 0
        side = "LONG"
        
        ch24 = d.get("ch24", 0)
        ch4h = d.get("ch4h", 0)
        vr = d.get("vol_ratio", 1.0)
        rsi_val = d.get("rsi14", 50)
        ema20 = d.get("ema20", 0)
        ema50 = d.get("ema50", 0)
        
        # 动量信号（使用进化阈值）
        if ch24 > mom_threshold * 100 or ch4h > mom_threshold * 100 * 0.4:
            score += 2
            side = "LONG"
        elif ch24 < -mom_threshold * 100 or ch4h < -mom_threshold * 100 * 0.4:
            score += 2
            side = "SHORT"
        
        # 量比信号（使用进化阈值）
        if vr > vol_threshold:
            score += 1
        
        # 资金费率信号
        opp = opp_map.get(coin, {})
        fr = opp.get("funding", 0)
        if abs(fr) > 0.0002:
            score += 1
            side = "SHORT" if fr > 0 else "LONG"
        
        # RSI 信号（使用进化阈值）
        if rsi_val < rsi_oversold:
            score += 1
            side = "LONG"
        elif rsi_val > rsi_overbought:
            score += 1
            side = "SHORT"
        
        # EMA 交叉信号（使用进化开关）
        if use_ema_cross and ema20 > 0 and ema50 > 0:
            if ema20 > ema50:
                score += 1
                if side != "SHORT":
                    side = "LONG"
            elif ema20 < ema50:
                score += 1
                if side != "LONG":
                    side = "SHORT"
        
        if score > best_score:
            best_score = score
            best_coin = coin
            best_side = side
            best_info = d
    
    # 保守循环打破时入场门槛应低于正常（正常=1，此处用1）
    if best_score >= 1 and best_coin:
        confidence = min(0.4 + best_score * 0.05, 0.6)
        equity = min(account_data.get("equity", 60.0), 60.0)
        pos_usdt = max(round(equity * 0.03, 2), 3.0)
        leverage = min(3, max(1, int(confidence * 4)))
        
        px = best_info.get("price", 0)
        sl_pct = 0.03
        tp_pct = 0.06
        sl = round(px * (1 - sl_pct) if best_side == "LONG" else px * (1 + sl_pct), 2)
        tp = round(px * (1 + tp_pct) if best_side == "LONG" else px * (1 - tp_pct), 2)
        
        decision.update({
            "action": best_side,
            "coin": best_coin,
            "confidence": confidence,
            "leverage": leverage,
            "position_size_usdt": pos_usdt,
            "entry_price": px,
            "stop_loss_price": sl,
            "take_profit_price": tp,
            "market_regime": "TREND_UP" if best_side == "LONG" else "TREND_DOWN",
            "decision_rationale": f"[保守循环打破] {best_coin} {best_side} score={best_score} "
                                 f"conf={confidence:.0%}（连续HOLD触发强制入场）",
            "reasoning_steps": decision.get("reasoning_steps", []) + [
                f"连续HOLD触发保守循环打破机制",
                f"选择 {best_coin} {best_side} score={best_score}",
                f"仓位: {pos_usdt} USDC × {leverage}x"
            ],
        })
        print(f"[风控] 保守循环打破: {best_coin} {best_side} score={best_score} conf={confidence:.0%}")
    else:
        print(f"[风控] 保守循环打破: 无足够信号（最高score={best_score}），继续HOLD")


# ── 自主调度 ──────────────────────────────────────────────────────────────

def _self_schedule(decision: dict, mkt: dict, memory: dict):
    """根据本轮信号决定下次触发时机"""
    import time as _t
    now = _t.time()
    action = decision.get("action", "HOLD")
    conf   = decision.get("confidence", 0.5)
    loss_streak = memory.get("loss_streak", 0)

    # 场景1：高置信度信号 → 1H后复查
    if action != "HOLD" and conf >= 0.75:
        request_early_run(
            reason=f"A高置信度{conf:.0%}信号，1H后复查仓位",
            run_at_ts=now + 3600,
            priority="normal",
        )

    # 场景2：成交量异常放大 → 2H后复查
    for coin, d in mkt.get("coins", {}).items():
        if d.get("vol_ratio", 0) > 2.5:
            request_early_run(
                reason=f"{coin}成交量异常放大{d['vol_ratio']:.1f}x，2H后复查",
                run_at_ts=now + 7200,
                priority="normal",
            )
            break

    # 场景3：连败保护解除 → 6H后复盘
    if loss_streak >= 3:
        request_early_run(
            reason=f"A连败{loss_streak}次，6H后强制复盘评估市场",
            run_at_ts=now + 21600,
            priority="urgent",
        )

    # 场景4：置信度接近门槛（60-65%）→ 1H后再试
    if 0.58 <= conf < 0.65 and action == "HOLD":
        request_early_run(
            reason=f"A置信度{conf:.0%}接近门槛，1H后市场可能更清晰",
            run_at_ts=now + 3600,
            priority="normal",
        )


# ── GitHub PR 评论同步 ────────────────────────────────────────────────────

def _post_to_github_pr(log_data: dict, sim_mode: bool):
    """执行完成后，写评论到固定交易 PR（用于 Actions 检查新鲜度）"""
    import requests

    gh_token = os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")

    if not gh_token or not gh_repo or not pr_number:
        return

    try:
        pr_number = int(pr_number)
    except (ValueError, TypeError):
        return

    beijing_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

    action = log_data.get("action", "HOLD")
    coin = log_data.get("coin", "N/A")
    conf = log_data.get("confidence", 0)
    provider = log_data.get("llm_provider", "rule")
    master = log_data.get("current_master", "N/A")
    rationale = log_data.get("decision_rationale", "N/A")
    pos_usdt = log_data.get("position_size_usdt", 0)
    leverage = log_data.get("leverage", 1)

    mode_label = "模拟" if sim_mode else "实盘"
    source_label = os.environ.get("PR_COMMENT_SOURCE", "Trae")

    comment = f"""## {source_label} 执行记录 - {now_bj} (GMT+8)

### 交易决策
- **操作**: {action}
- **币种**: {coin}
- **置信度**: {conf:.0%}
- **理由**: {rationale[:120]}

### 账户状态
- **持仓**: {coin + ' ' + str(pos_usdt) + ' USDT' if action in ('LONG', 'SHORT') else '无新持仓'}
- **杠杆**: {leverage}x

### 执行详情
- **模式**: {mode_label} ({source_label})
- **Provider**: {provider}
- **大师风格**: {master}

---
*🤖 自动执行于 {source_label}*
"""

    url = f"https://api.github.com/repos/{gh_repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {gh_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"body": comment}

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code == 201:
            print(f"[PR] 已写评论到 PR #{pr_number}")
        else:
            print(f"[PR] 写评论失败: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"[PR] 写评论异常: {e}")


if __name__ == "__main__":
    run()
