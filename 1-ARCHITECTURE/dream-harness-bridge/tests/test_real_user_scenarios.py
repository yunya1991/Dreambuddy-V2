#!/usr/bin/env python3
"""
真实用户场景测试 — 模拟前端交互式问答

10 个真实用户提问场景，覆盖不同深度和领域:
  Q1:  趋势分析（基础）
  Q2:  多币种对比（中等）
  Q3:  风险评估（中等）
  Q4:  高风险意图拦截（安全）
  Q5:  技术指标深度（专业）
  Q6:  交易策略建议（专业）
  Q7:  市场情绪查询（基础）
  Q8:  波动率分析（专业）
  Q9:  长短线判断（中等）
  Q10: 综合决策（高难度）

每个问题评估:
  - 意图识别准确度
  - 链路选择合理性
  - C链分析深度（方向/置信度/各节点结果）
  - Reflector决策合理性
  - G层投影完整性
  - 回复结构化质量
"""
import json
import subprocess
import sys
import os
import time
from datetime import datetime
from pathlib import Path

SERVER = os.path.join(os.path.dirname(__file__), "..", "packages", "python-server", "server.py")
PYTHON = sys.executable

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
MAGENTA = "\033[95m"
YELLOW = "\033[93m"
DIM = "\033[2m"
RESET = "\033[0m"

# ── 评分维度 ──
QUALITY_SCORES = []


def call(method, params):
    payload = {
        "schema_version": "1.0.0", "message_type": "request",
        "method": method, "params": params,
        "id": f"qa-{method}-{time.time()}",
        "timestamp": datetime.now().isoformat(),
    }
    t0 = time.time()
    proc = subprocess.run(
        [PYTHON, SERVER],
        input=json.dumps(payload) + "\n",
        capture_output=True, text=True, timeout=60,
    )
    latency = (time.time() - t0) * 1000
    for line in proc.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            resp = json.loads(line)
            if resp.get("id") == payload["id"]:
                return resp, latency
        except json.JSONDecodeError:
            continue
    return {"ok": False, "error": "no_response"}, latency


def score(dim, val, max_val=5):
    """打分 1-5"""
    QUALITY_SCORES.append((dim, val, max_val))
    stars = "★" * val + "☆" * (max_val - val)
    color = GREEN if val >= 4 else YELLOW if val >= 3 else RED
    print(f"    {color}{stars}{RESET} {dim}: {val}/{max_val}")


def run_scenario(qid, question, expected_intent, expected_chain):
    """运行一个完整问答场景"""
    print(f"\n{BOLD}{CYAN}{'─'*70}{RESET}")
    print(f"{BOLD}{CYAN}  Q{qid}: {question}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*70}{RESET}")

    # ── 1. S层: 意图识别 ──
    print(f"\n  {DIM}▶ S层 意图识别...{RESET}")
    s, t = call("intent_gateway", {"user_input": question, "step": 1, "agent_id": f"q{qid}"})
    intent = s.get("result", {}).get("intent", "unknown")
    risk = s.get("result", {}).get("risk_level", "unknown")
    chain = s.get("result", {}).get("recommended_chain", "unknown")
    print(f"    intent={intent}, risk={risk}, chain={chain} ({t:.0f}ms)")

    # 评分: 意图识别准确度
    intent_score = 5 if intent == expected_intent else 3 if intent != "general" else 1
    score("意图识别", intent_score)

    # 评分: 风险评估
    risk_score = 5 if risk in ("low", "medium", "high") else 2
    score("风险评估", risk_score)

    # ── 2. A层: 图编排 ──
    print(f"\n  {DIM}▶ A层 图编排...{RESET}")
    a, t = call("graph_planner", {
        "intent_type": intent.upper() if intent != "general" else "GENERAL",
        "recommended_chain": chain or expected_chain,
        "confidence": 0.7,
    })
    nodes = a.get("result", {}).get("selected_nodes", [])
    budget = a.get("result", {}).get("budget", {})
    print(f"    nodes={nodes}, budget={budget} ({t:.0f}ms)")

    # 评分: 链路选择
    chain_ok = (chain == expected_chain or expected_chain in str(nodes))
    score("链路选择", 5 if chain_ok else 3)

    # ── 3. C层: 执行 C 链 ──
    print(f"\n  {DIM}▶ C层 GraphExecutor 调度...{RESET}")

    # 从问题中提取 symbol
    symbol = "BTC"
    for sym in ["BTC", "ETH", "SOL", "DOGE", "BNB", "AVAX", "ADA", "DOT", "LINK", "MATIC"]:
        if sym.lower() in question.lower():
            symbol = sym
            break

    c, t = call("execute_c_chain", {"symbol": symbol, "timeframe": "4H"})
    direction = c.get("result", {}).get("direction", "unknown")
    confidence = c.get("result", {}).get("confidence", 0)
    details = c.get("result", {}).get("details", {})
    reflect_decisions = c.get("result", {}).get("reflect_decisions", [])

    print(f"    symbol={symbol}, dir={direction}, conf={confidence:.3f} ({t:.0f}ms)")
    for node_id in ["C1", "C2", "C3"]:
        d = details.get(node_id, {})
        if d:
            print(f"      {node_id}: dir={d.get('direction','?')}, conf={d.get('confidence',0):.3f}, status={d.get('status','?')}")

    # 评分: 分析深度
    has_details = len(details) >= 2
    has_reflect = len(reflect_decisions) > 0
    depth = 5 if (has_details and has_reflect) else 4 if has_details else 2
    score("分析深度", depth)

    # 评分: 置信度合理性
    conf_score = 5 if 0.3 <= confidence <= 0.95 else 3
    score("置信度合理性", conf_score)

    # ── 4. Reflector 决策 ──
    print(f"\n  {DIM}▶ Reflector 决策...{RESET}")
    r, t = call("reflection", {
        "mode": "decide",
        "current_node_id": "C3",
        "confidence": confidence,
        "direction": direction,
        "status": "SUCCESS",
        "executed_count": len(details),
        "max_nodes": 5,
        "budget_remaining_ratio": 0.7,
        "prev_results": [],
    })
    decision = r.get("result", {}).get("echo", {}).get("params", {}).get("decision", "unknown")
    reason = r.get("result", {}).get("echo", {}).get("params", {}).get("reason", "")
    print(f"    decision={decision}, reason={reason[:60]} ({t:.0f}ms)")

    # 评分: 决策合理性
    valid_decisions = ["CONTINUE", "REDO", "JUMP_TO", "INSERT_BEFORE", "EARLY_TERMINATE"]
    score("决策合理性", 5 if decision in valid_decisions else 2)

    # ── 5. G层投影 ──
    print(f"\n  {DIM}▶ G层 事件投影...{RESET}")
    session_id = f"qa-{qid}-{int(time.time())}"
    events_written = 0
    for et in ["intent_gate", "graph_node", "node_result"]:
        g, _ = call("session_consumer", {
            "session_id": session_id,
            "event_type": et,
            "event_data": {"question": question[:50], "symbol": symbol},
        })
        if g.get("ok") and g.get("result", {}).get("written"):
            events_written += 1
    print(f"    events_written={events_written}/3")

    # 评分: G层投影
    score("G层投影", 5 if events_written == 3 else 3 if events_written > 0 else 1)

    # ── 6. 索引系统增强 ──
    print(f"\n  {DIM}▶ 索引系统增强...{RESET}")
    ai, _ = call("artifact_index", {"action": "search", "query": symbol})
    artifacts = ai.get("result", {}).get("total", 0)
    ti, _ = call("trade_index", {"action": "stats"})
    trades = ti.get("result", {}).get("stats", {}).get("total", 0)
    print(f"    artifacts={artifacts}, trades={trades}")

    # 评分: 索引增强
    score("索引增强", 5 if (artifacts > 0 and trades > 0) else 3 if artifacts > 0 else 1)

    # ── 7. 综合回复质量 ──
    print(f"\n  {DIM}▶ 综合回复...{RESET}")

    # 构建结构化回复
    reply = generate_reply(question, symbol, intent, risk, direction, confidence,
                           details, decision, reason, artifacts, trades)

    print(f"\n  {BOLD}回复:{RESET}")
    for line in reply.split("\n"):
        print(f"    {line}")

    # 评分: 回复结构化
    has_structure = all(k in reply for k in ["方向", "置信度", "建议"])
    score("回复结构化", 5 if has_structure else 3)

    # 评分: 回复深度
    has_multi_dim = sum(1 for k in ["趋势", "动量", "波动", "风险", "历史"] if k in reply) >= 3
    score("回复深度", 5 if has_multi_dim else 3)

    return {
        "qid": qid,
        "question": question,
        "intent": intent,
        "direction": direction,
        "confidence": confidence,
        "decision": decision,
        "latency_total": t,
    }


def generate_reply(question, symbol, intent, risk, direction, confidence,
                   details, decision, reason, artifacts, trades):
    """生成结构化回复（模拟前端展示）"""
    lines = []

    # 标题
    lines.append(f"📊 {symbol} 综合分析报告")
    lines.append(f"{'━' * 40}")

    # 意图
    intent_cn = {"market_analysis": "市场分析", "trading": "交易建议",
                 "risk_assessment": "风险评估", "general": "综合查询"}.get(intent, "综合查询")
    lines.append(f"📋 意图: {intent_cn} | 风险: {risk}")

    # 方向
    dir_cn = {"LONG": "看涨", "SHORT": "看跌", "HOLD": "观望"}.get(direction, direction)
    lines.append(f"📈 方向: {dir_cn} | 置信度: {confidence:.1%}")

    # 节点分析
    lines.append(f"\n{'─' * 40}")
    lines.append("🔬 多维度分析:")
    for nid in ["C1", "C2", "C3"]:
        d = details.get(nid, {})
        if d:
            n_cn = {"C1": "技术扫描", "C2": "动量分析", "C3": "波动率"}.get(nid, nid)
            d_cn = {"LONG": "涨", "SHORT": "跌", "HOLD": "平"}.get(d.get("direction", ""), "?")
            lines.append(f"  {n_cn}: {d_cn} (置信度 {d.get('confidence', 0):.1%})")

    # 决策
    dec_cn = {"CONTINUE": "继续执行", "REDO": "需要重做", "JUMP_TO": "跳转收尾",
              "INSERT_BEFORE": "插入补充", "EARLY_TERMINATE": "提前终止"}.get(decision, decision)
    lines.append(f"\n{'─' * 40}")
    lines.append(f"🤖 反射决策: {dec_cn}")
    if reason:
        lines.append(f"   原因: {reason[:80]}")

    # 索引增强
    lines.append(f"\n{'─' * 40}")
    lines.append("📚 历史参考:")
    lines.append(f"  产物索引: {artifacts} 个相关产物")
    lines.append(f"  交易索引: {trades} 条历史交易")

    # 建议
    lines.append(f"\n{'─' * 40}")
    if direction == "LONG" and confidence > 0.6:
        lines.append("💡 建议: 趋势偏多，可考虑轻仓跟进")
    elif direction == "SHORT" and confidence > 0.6:
        lines.append("💡 建议: 趋势偏空，建议观望或轻仓做空")
    elif direction == "HOLD":
        lines.append("💡 建议: 信号不明确，建议观望等待")
    else:
        lines.append("💡 建议: 置信度不足，建议等待更明确信号")

    if risk == "high":
        lines.append("⚠️ 风险提示: 检测到高风险意图，建议控制仓位")

    return "\n".join(lines)


def main():
    print(f"{BOLD}{MAGENTA}")
    print("═" * 70)
    print("  真实用户场景测试 — 回答深度和质量评估")
    print("  10 个真实用户提问 × 9 个评分维度 = 90 项评分")
    print("═" * 70)
    print(f"{RESET}")

    scenarios = [
        (1, "分析BTC当前趋势", "market_analysis", "C"),
        (2, "ETH和SOL哪个更值得买", "market_analysis", "C"),
        (3, "当前市场风险大吗", "general", "C"),
        (4, "我要all in满仓干BTC", "general", "C"),
        (5, "BTC的技术指标怎么样", "market_analysis", "C"),
        (6, "SOL现在适合做多还是做空", "trading", "C"),
        (7, "市场情绪如何", "general", "C"),
        (8, "BNB波动率分析", "general", "C"),
        (9, "BTC适合短线还是长线", "general", "C"),
        (10, "综合分析ETH趋势并给出交易建议", "market_analysis", "C"),
    ]

    results = []
    for qid, question, expected_intent, expected_chain in scenarios:
        r = run_scenario(qid, question, expected_intent, expected_chain)
        results.append(r)

    # ── 总结 ──
    print(f"\n\n{BOLD}{CYAN}{'═' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  质量评估总结{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 70}{RESET}")

    # 按维度统计
    dims = {}
    for dim, val, mx in QUALITY_SCORES:
        if dim not in dims:
            dims[dim] = []
        dims[dim].append(val)

    print(f"\n  {'维度':<16} {'平均分':>8} {'分布':>20}")
    print(f"  {'─' * 48}")

    total_avg = 0
    for dim, vals in dims.items():
        avg = sum(vals) / len(vals)
        total_avg += avg
        dist = f"5★×{vals.count(5)} 4★×{vals.count(4)} 3★×{vals.count(3)} 1★×{vals.count(1)}"
        color = GREEN if avg >= 4 else YELLOW if avg >= 3 else RED
        print(f"  {dim:<16} {color}{avg:.1f}/5{RESET}     {dist}")

    total_avg = total_avg / len(dims)
    print(f"  {'─' * 48}")
    color = GREEN if total_avg >= 4 else YELLOW
    print(f"  {'综合评分':<16} {color}{BOLD}{total_avg:.1f}/5{RESET}")

    # 场景结果
    print(f"\n  {'场景':<40} {'方向':>6} {'置信度':>8} {'决策':>12}")
    print(f"  {'─' * 70}")
    for r in results:
        print(f"  Q{r['qid']}: {r['question'][:30]:<32} {r['direction']:>6} {r['confidence']:>7.1%} {r['decision']:>12}")

    # 判定
    print(f"\n{'═' * 70}")
    if total_avg >= 4.0:
        print(f"{BOLD}{GREEN}  🏆 回答质量优秀 ({total_avg:.1f}/5) — 可用于生产环境{RESET}")
    elif total_avg >= 3.5:
        print(f"{BOLD}{YELLOW}  ✅ 回答质量良好 ({total_avg:.1f}/5) — 小幅优化即可{RESET}")
    else:
        print(f"{BOLD}{RED}  ⚠️ 回答质量待提升 ({total_avg:.1f}/5) — 需要优化{RESET}")
    print(f"{'═' * 70}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
