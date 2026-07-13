#!/usr/bin/env python3
"""
持仓战略评估 & 离场建议脚本 v1.0 — Phase 0/1

目标：
  1. 聚合 6 个交易系统的持仓（Agent A/B/C、V15、易经、三屏）
  2. 简化版 A1-A2-A3 宏观分析
  3. 逐持仓输出离场建议（平仓/减仓/HOLD/提高止盈）
  4. 产物输出到 artifacts/exit-evaluations/

阶段定位：
  - Phase 1：查询层完成（6 系统覆盖），分析层用简化版
  - Phase 2：接入真实 A1/A2/A3 SKILL

说明：
  - 不执行任何交易操作（只输出建议）
  - 单系统失败不影响整体（降级容错）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent  # dreambuddy-v2/
MODULE_DIR = Path(__file__).parent.parent       # 16-调控系统/
ARTIFACTS_DIR = MODULE_DIR / "artifacts" / "exit-evaluations"
CORE_DIR = MODULE_DIR / "core"

sys.path.insert(0, str(CORE_DIR))
from unified_position_query import fetch_all_positions


def fetch_market_snapshot() -> dict:
    """获取市场快照（简化版）— 阶段0用公开 API，不需要密钥"""
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "instruments": {},
        "data_source": "",
    }

    sources = [
        _fetch_from_hyperliquid,
        _fetch_from_coingecko,
        _fetch_from_binance,
        _fetch_from_okx,
    ]

    for source_fn in sources:
        try:
            result = source_fn()
            if result and result.get("instruments") and result["instruments"].get("BTC", {}).get("price", 0) > 0:
                snapshot.update(result)
                return snapshot
        except Exception:
            continue

    snapshot["error"] = "All market data sources failed"
    return snapshot


def _fetch_from_hyperliquid() -> dict:
    """从 Hyperliquid 获取行情"""
    import requests
    r = requests.post(
        "https://api.hyperliquid.xyz/info",
        json={"type": "allMids"},
        timeout=8,
    )
    data = r.json()
    coins = ["BTC", "ETH", "SOL"]
    instruments = {}
    for coin in coins:
        if coin in data:
            price = float(data[coin])
            instruments[coin] = {
                "price": price,
                "change_24h_pct": 0.0,
            }
    return {"instruments": instruments, "data_source": "hyperliquid"}


def _fetch_from_coingecko() -> dict:
    """从 CoinGecko 获取行情"""
    import requests
    coins = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}
    ids = ",".join(coins.keys())
    r = requests.get(
        f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true",
        timeout=8,
    )
    data = r.json()
    instruments = {}
    for cg_id, symbol in coins.items():
        if cg_id in data:
            instruments[symbol] = {
                "price": float(data[cg_id]["usd"]),
                "change_24h_pct": float(data[cg_id].get("usd_24h_change", 0)),
            }
    return {"instruments": instruments, "data_source": "coingecko"}


def _fetch_from_binance() -> dict:
    """从 Binance 获取行情"""
    import requests
    coins = ["BTC", "ETH", "SOL"]
    instruments = {}
    for coin in coins:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/24hr?symbol={coin}USDT",
            timeout=5,
        )
        data = r.json()
        if "lastPrice" in data:
            instruments[coin] = {
                "price": float(data["lastPrice"]),
                "change_24h_pct": float(data["priceChangePercent"]),
                "high_24h": float(data["highPrice"]),
                "low_24h": float(data["lowPrice"]),
                "volume": float(data["volume"]),
            }
    return {"instruments": instruments, "data_source": "binance"}


def _fetch_from_okx() -> dict:
    """从 OKX 获取行情"""
    import requests
    coins = ["BTC", "ETH", "SOL"]
    instruments = {}
    for coin in coins:
        r = requests.get(
            f"https://www.okx.com/api/v5/market/ticker?instId={coin}-USDT-SWAP",
            timeout=5,
        )
        data = r.json()
        if data.get("code") == "0" and data.get("data"):
            ticker = data["data"][0]
            instruments[coin] = {
                "price": float(ticker["last"]),
                "change_24h_pct": float(ticker.get("sodUtc0", 0)) * 100,
                "high_24h": float(ticker.get("high24h", 0)),
                "low_24h": float(ticker.get("low24h", 0)),
                "volume": float(ticker.get("vol24h", 0)),
            }
    return {"instruments": instruments, "data_source": "okx"}


def simplified_a1_analysis(market: dict, positions: list) -> dict:
    """
    简化版 A1 深度调研
    阶段0：只做基础市场状态判断，不做完整三角准则
    """
    btc = market.get("instruments", {}).get("BTC", {})
    price = btc.get("price", 0)
    change_24h = btc.get("change_24h_pct", 0)

    signal_sufficiency = "MODERATE"
    if abs(change_24h) > 5:
        signal_sufficiency = "HIGH"
    elif abs(change_24h) < 1:
        signal_sufficiency = "LOW"

    regime = "TREND_UP" if change_24h > 2 else ("TREND_DOWN" if change_24h < -2 else "RANGE")

    contradiction_list = []
    if positions:
        directions = [p.get("direction", "UNKNOWN") for p in positions]
        long_count = sum(1 for d in directions if d == "LONG")
        short_count = sum(1 for d in directions if d == "SHORT")

        if long_count > short_count and change_24h < 0:
            contradiction_list.append({
                "id": "C_POS_001",
                "name": "持仓方向与市场走势背离",
                "dimension": "C3_技术面",
                "description": f"多头持仓 {long_count} 个，但 BTC 24h 跌幅 {abs(change_24h):.2f}%",
                "severity": "HIGH" if abs(change_24h) > 3 else "MEDIUM",
            })
        if short_count > long_count and change_24h > 0:
            contradiction_list.append({
                "id": "C_POS_002",
                "name": "空头持仓与市场上涨背离",
                "dimension": "C3_技术面",
                "description": f"空头持仓 {short_count} 个，但 BTC 24h 涨幅 {change_24h:.2f}%",
                "severity": "HIGH" if abs(change_24h) > 3 else "MEDIUM",
            })

    if not contradiction_list:
        contradiction_list.append({
            "id": "C_DEF_001",
            "name": "暂无显著矛盾",
            "dimension": "C6_时序",
            "description": "当前市场状态与持仓方向基本一致",
            "severity": "LOW",
        })

    return {
        "phase": "A1_simplified",
        "signal_sufficiency": signal_sufficiency,
        "market_regime": regime,
        "btc_price": price,
        "btc_change_24h_pct": change_24h,
        "action_pressure": "LOW" if signal_sufficiency == "MODERATE" else signal_sufficiency,
        "contradiction_list": contradiction_list,
        "summary": f"BTC ${price:,.0f}，24h {change_24h:+.2f}%，信号充分性 {signal_sufficiency}，市场状态 {regime}",
    }


def simplified_a2_analysis(a1_result: dict, market: dict) -> dict:
    """
    简化版 A2 第一性原理分析
    阶段0：只做阻力最小方向判断
    """
    change_24h = a1_result.get("btc_change_24h_pct", 0)

    if change_24h > 3:
        least_resistance_path = "UP"
        trend_phase = "ACCELERATING"
        confidence = "HIGH"
    elif change_24h > 0.5:
        least_resistance_path = "UP"
        trend_phase = "CONSOLIDATING_UP"
        confidence = "MEDIUM"
    elif change_24h > -0.5:
        least_resistance_path = "NEUTRAL"
        trend_phase = "RANGING"
        confidence = "LOW"
    elif change_24h > -3:
        least_resistance_path = "DOWN"
        trend_phase = "CONSOLIDATING_DOWN"
        confidence = "MEDIUM"
    else:
        least_resistance_path = "DOWN"
        trend_phase = "ACCELERATING_DOWN"
        confidence = "HIGH"

    return {
        "phase": "A2_simplified",
        "least_resistance_path": least_resistance_path,
        "trend_phase": trend_phase,
        "confidence": confidence,
        "resistance_score": abs(change_24h) * 10,
        "summary": f"阻力最小方向: {least_resistance_path}，趋势阶段: {trend_phase}，置信度: {confidence}",
    }


def simplified_a3_strategy(a1_result: dict, a2_result: dict, positions: list) -> dict:
    """
    简化版 A3 战略合成
    阶段0：基于 A1+A2 输出战略建议
    """
    regime = a1_result.get("market_regime", "RANGE")
    path = a2_result.get("least_resistance_path", "NEUTRAL")
    confidence = a2_result.get("confidence", "LOW")

    strategy_direction = "NEUTRAL"
    if path == "UP" and confidence in ("HIGH", "MEDIUM"):
        strategy_direction = "BULLISH"
    elif path == "DOWN" and confidence in ("HIGH", "MEDIUM"):
        strategy_direction = "BEARISH"

    stance = "HOLD"
    rationale = "维持现有策略"

    if strategy_direction == "BULLISH":
        if positions:
            long_positions = [p for p in positions if p.get("direction") == "LONG"]
            if long_positions:
                stance = "RAISE_TP"
                rationale = "趋势向上，持仓方向一致，建议提高止盈"
            else:
                stance = "REDUCE"
                rationale = "趋势向上但持有空头，建议减仓"
        else:
            stance = "HOLD"
            rationale = "无持仓，趋势向上但暂不开新仓"
    elif strategy_direction == "BEARISH":
        if positions:
            short_positions = [p for p in positions if p.get("direction") == "SHORT"]
            if short_positions:
                stance = "RAISE_TP"
                rationale = "趋势向下，持仓方向一致，建议提高止盈"
            else:
                stance = "REDUCE"
                rationale = "趋势向下但持有多头，建议减仓"
        else:
            stance = "HOLD"
            rationale = "无持仓，趋势向下但暂不开新仓"
    else:
        stance = "HOLD"
        rationale = "市场震荡，维持现状"

    return {
        "phase": "A3_simplified",
        "strategy_direction": strategy_direction,
        "overall_stance": stance,
        "rationale": rationale,
        "risk_level": confidence,
        "summary": f"战略方向: {strategy_direction}，整体立场: {stance}",
    }


def evaluate_position_exit(position: dict, a1: dict, a2: dict, a3: dict) -> dict:
    """
    简化版 A9 离场评估
    对单个持仓输出四种行为建议：CLOSE / REDUCE / HOLD / RAISE_TP
    """
    direction = position.get("direction", "UNKNOWN")
    strategy_dir = a3.get("strategy_direction", "NEUTRAL")
    regime = a1.get("market_regime", "RANGE")
    confidence = a2.get("confidence", "LOW")

    action = "HOLD"
    reason = "默认持有"
    urgency = "LOW"

    if direction == "LONG":
        if strategy_dir == "BEARISH" and confidence == "HIGH":
            action = "CLOSE"
            reason = "战略方向转空，与多头持仓矛盾，建议平仓"
            urgency = "HIGH"
        elif strategy_dir == "BEARISH" and confidence == "MEDIUM":
            action = "REDUCE"
            reason = "战略方向偏空，与多头持仓矛盾，建议减仓"
            urgency = "MEDIUM"
        elif strategy_dir == "BULLISH":
            action = "RAISE_TP"
            reason = "战略方向多头，持仓方向一致，建议提高止盈"
            urgency = "LOW"
        else:
            action = "HOLD"
            reason = "市场中性，维持现有持仓"
            urgency = "LOW"
    elif direction == "SHORT":
        if strategy_dir == "BULLISH" and confidence == "HIGH":
            action = "CLOSE"
            reason = "战略方向转多，与空头持仓矛盾，建议平仓"
            urgency = "HIGH"
        elif strategy_dir == "BULLISH" and confidence == "MEDIUM":
            action = "REDUCE"
            reason = "战略方向偏多，与空头持仓矛盾，建议减仓"
            urgency = "MEDIUM"
        elif strategy_dir == "BEARISH":
            action = "RAISE_TP"
            reason = "战略方向空头，持仓方向一致，建议提高止盈"
            urgency = "LOW"
        else:
            action = "HOLD"
            reason = "市场中性，维持现有持仓"
            urgency = "LOW"

    return {
        "position": {
            "symbol": position.get("symbol"),
            "system": position.get("system"),
            "direction": direction,
            "size": position.get("size"),
            "entry_price": position.get("entry_price"),
            "unrealized_pnl": position.get("unrealized_pnl"),
        },
        "recommended_action": action,
        "reason": reason,
        "urgency": urgency,
        "confidence": confidence,
    }


def generate_exit_evaluation() -> dict:
    """生成完整的离场评估报告"""
    print("=" * 60)
    print("📊 阶段0：持仓战略评估 & 离场建议（MVP）")
    print("=" * 60)

    print("\n[1/5] 查询统一持仓...")
    positions_data = fetch_all_positions()
    all_positions = positions_data.get("all_positions", [])
    print(f"  → 共 {positions_data['total_positions']} 个持仓，来自 {positions_data['total_systems']} 个系统")
    for sys_name, status in positions_data.get("system_status", {}).items():
        print(f"    · {sys_name}: {status}")

    print("\n[2/5] 获取市场快照...")
    market = fetch_market_snapshot()
    btc_info = market.get("instruments", {}).get("BTC", {})
    if btc_info:
        print(f"  → BTC ${btc_info.get('price', 0):,.0f}，24h {btc_info.get('change_24h_pct', 0):+.2f}%")
    else:
        print(f"  → 市场数据获取失败: {market.get('error', 'unknown')}")

    print("\n[3/5] 简化 A1-A2-A3 宏观分析...")
    a1 = simplified_a1_analysis(market, all_positions)
    print(f"  A1: {a1['summary']}")
    a2 = simplified_a2_analysis(a1, market)
    print(f"  A2: {a2['summary']}")
    a3 = simplified_a3_strategy(a1, a2, all_positions)
    print(f"  A3: {a3['summary']}")

    print("\n[4/5] 逐持仓离场评估...")
    evaluations = []
    for pos in all_positions:
        ev = evaluate_position_exit(pos, a1, a2, a3)
        evaluations.append(ev)
        print(f"  [{ev['recommended_action']}] {pos.get('system')}/{pos.get('symbol')} {pos.get('direction')} — {ev['reason']}")

    if not evaluations:
        print("  → 当前无持仓，跳过逐持仓评估")

    report = {
        "version": "0.1.0-phase0",
        "timestamp": datetime.now().isoformat(),
        "status": "completed",
        "positions_overview": {
            "total_systems": positions_data["total_systems"],
            "total_positions": positions_data["total_positions"],
            "system_status": positions_data["system_status"],
        },
        "market_snapshot": market,
        "macro_analysis": {
            "a1_research": a1,
            "a2_first_principles": a2,
            "a3_strategy": a3,
        },
        "exit_evaluations": evaluations,
        "overall_summary": {
            "total_evaluated": len(evaluations),
            "close_count": sum(1 for e in evaluations if e["recommended_action"] == "CLOSE"),
            "reduce_count": sum(1 for e in evaluations if e["recommended_action"] == "REDUCE"),
            "hold_count": sum(1 for e in evaluations if e["recommended_action"] == "HOLD"),
            "raise_tp_count": sum(1 for e in evaluations if e["recommended_action"] == "RAISE_TP"),
            "overall_stance": a3["overall_stance"],
            "rationale": a3["rationale"],
        },
        "disclaimer": "阶段0验证版，不构成交易建议。仅用于验证技术通路验证。",
    }

    print("\n[5/5] 保存产物...")
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = ARTIFACTS_DIR / f"exit_evaluation_{ts}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  → JSON: {json_path}")

    md_path = ARTIFACTS_DIR / f"exit_evaluation_{ts}.md"
    md_content = generate_markdown_report(report)
    with open(md_path, "w") as f:
        f.write(md_content)
    print(f"  → Markdown: {md_path}")

    print("\n✅ 阶段0验证完成！")
    return report


def generate_markdown_report(report: dict) -> str:
    """生成 Markdown 格式报告"""
    ts = report["timestamp"]
    overview = report["overall_summary"]
    a1 = report["macro_analysis"]["a1_research"]
    a2 = report["macro_analysis"]["a2_first_principles"]
    a3 = report["macro_analysis"]["a3_strategy"]
    evals = report["exit_evaluations"]

    lines = []
    lines.append("---")
    lines.append(f'title: "离场评估报告 - {ts}"')
    lines.append('department: trading')
    lines.append('chain_phase: "A9-Phase0"')
    lines.append(f'date: "{ts}"')
    lines.append('type: exit_evaluation')
    lines.append('status: completed')
    lines.append('tags: "phase0 mvp exit-evaluation"')
    lines.append('by_a_phase: "A1+A2+A3+A9"')
    lines.append("---")
    lines.append("")
    lines.append("# 离场评估报告（阶段0 MVP）")
    lines.append("")
    lines.append(f"**生成时间**: {ts}")
    lines.append(f"**版本**: {report['version']}")
    lines.append(f"**整体立场**: {overview['overall_stance']}")
    lines.append(f"**理由**: {overview['rationale']}")
    lines.append("")

    lines.append("## 一、持仓概览")
    lines.append("")
    lines.append(f"- 系统数: {report['positions_overview']['total_systems']}")
    lines.append(f"- 总持仓数: {report['positions_overview']['total_positions']}")
    lines.append("")
    lines.append("### 各系统状态")
    lines.append("")
    lines.append("| 系统 | 状态 |")
    lines.append("|---|---|")
    for sys_name, status in report["positions_overview"]["system_status"].items():
        lines.append(f"| {sys_name} | {status} |")
    lines.append("")

    lines.append("## 二、宏观分析（A1-A2-A3 简化版）")
    lines.append("")
    lines.append(f"**A1 调研**: {a1['summary']}")
    lines.append("")
    lines.append(f"- 信号充分性: {a1['signal_sufficiency']}")
    lines.append(f"- 市场状态: {a1['market_regime']}")
    lines.append(f"- 主要矛盾数: {len(a1['contradiction_list'])}")
    lines.append("")
    lines.append(f"**A2 第一性原理**: {a2['summary']}")
    lines.append("")
    lines.append(f"- 阻力最小方向: {a2['least_resistance_path']}")
    lines.append(f"- 趋势阶段: {a2['trend_phase']}")
    lines.append(f"- 置信度: {a2['confidence']}")
    lines.append("")
    lines.append(f"**A3 战略**: {a3['summary']}")
    lines.append("")
    lines.append(f"- 战略方向: {a3['strategy_direction']}")
    lines.append(f"- 风险等级: {a3['risk_level']}")
    lines.append("")

    lines.append("## 三、逐持仓评估")
    lines.append("")
    if evals:
        lines.append("| 系统 | 币种 | 方向 | 建议 | 紧急度 | 理由 |")
        lines.append("|---|---|---|---|---|---|")
        for e in evals:
            p = e["position"]
            lines.append(
                f"| {p['system']} | {p['symbol']} | {p['direction']} | "
                f"**{e['recommended_action']}** | {e['urgency']} | {e['reason']} |"
            )
    else:
        lines.append("当前无持仓。")
    lines.append("")

    lines.append("## 四、评估统计")
    lines.append("")
    lines.append(f"- 评估持仓数: {overview['total_evaluated']}")
    lines.append(f"- 平仓建议: {overview['close_count']}")
    lines.append(f"- 减仓建议: {overview['reduce_count']}")
    lines.append(f"- 持有建议: {overview['hold_count']}")
    lines.append(f"- 提高止盈建议: {overview['raise_tp_count']}")
    lines.append("")

    lines.append("## 五、免责声明")
    lines.append("")
    lines.append("> ⚠️ 阶段0验证版，仅用于技术通路验证，不构成任何交易建议。")
    lines.append("> 所有分析基于简化逻辑，不代表真实 A1/A2/A3/A9 SKILL 的完整判断。")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    generate_exit_evaluation()
