#!/usr/bin/env python3
"""
Harness 前端交互模拟验证器

模拟用户在前端提问，通过 DreamOS + Harness 的 S→A→C→G 完整流程处理，
验证回复质量、调度情况和运行数据。

用法:
    python harness_interactive_test.py            # 交互模式
    python harness_interactive_test.py --auto     # 自动测试多个场景
"""
import json
import subprocess
import sys
import os
import time
from datetime import datetime

SERVER = os.path.join(os.path.dirname(__file__), "..", "packages", "python-server", "server.py")
PYTHON = sys.executable

# ANSI 颜色
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"


class HarnessSimulator:
    """模拟 Harness 前端交互"""

    def __init__(self):
        self.session_id = f"harness-test-{int(time.time())}"
        self.logs = []  # 调度日志
        self.stats = {
            "total_requests": 0,
            "s_layer_calls": 0,
            "a_layer_calls": 0,
            "c_layer_calls": 0,
            "g_layer_calls": 0,
            "reflector_calls": 0,
            "total_latency_ms": 0,
        }

    def call(self, method, params):
        """调用 Python server 的 IPC 方法"""
        payload = {
            "schema_version": "1.0.0",
            "message_type": "request",
            "method": method,
            "params": params,
            "id": f"sim-{method}-{os.getpid()}-{time.time()}",
            "timestamp": datetime.utcnow().isoformat(),
        }
        t0 = time.time()
        proc = subprocess.run(
            [PYTHON, SERVER],
            input=json.dumps(payload) + "\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        latency_ms = (time.time() - t0) * 1000
        self.stats["total_latency_ms"] += latency_ms

        for line in proc.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                if resp.get("id") == payload["id"]:
                    self.logs.append({
                        "method": method,
                        "latency_ms": round(latency_ms, 1),
                        "ok": resp.get("ok", False),
                    })
                    return resp
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"No response for {method}")

    def handle_user_input(self, user_input: str) -> dict:
        """处理用户输入，走通 S→A→C→G 流程"""
        self.stats["total_requests"] += 1
        result = {"user_input": user_input, "steps": []}

        print(f"\n{BOLD}{MAGENTA}👤 用户提问:{RESET} {user_input}")
        print(f"{CYAN}{'─'*70}{RESET}")

        # ═══ S 层: 意图识别 ═══
        print(f"{BOLD}{CYAN}📍 S 层 — 意图识别 (IntentGateway){RESET}")
        s_resp = self.call("intent_gateway", {
            "user_input": user_input,
            "step": self.stats["total_requests"],
            "agent_id": "harness-frontend-sim",
        })
        s_result = s_resp["result"]
        self.stats["s_layer_calls"] += 1
        intent = s_result["intent"]
        risk = s_result["risk_level"]
        print(f"  意图: {GREEN}{intent}{RESET} | 风险: {YELLOW}{risk}{RESET}")
        print(f"  置信度: {s_result.get('confidence', 'N/A')}")
        result["steps"].append({"layer": "S", "intent": intent, "risk": risk})

        # G 层投影: intent_gate
        self.call("session_consumer", {
            "session_id": self.session_id,
            "event_type": "intent_gate",
            "event_data": {"intent": intent, "risk_level": risk, "user_input": user_input},
        })
        self.stats["g_layer_calls"] += 1

        # ═══ A 层: 图编排 ═══
        print(f"\n{BOLD}{CYAN}📍 A 层 — 图编排 (GraphPlanner){RESET}")
        # 根据意图选择链路
        chain_map = {
            "market_analysis": "C",
            "trade_execution": "A",
            "risk_assessment": "G",
            "fundamental": "F",
        }
        chain = chain_map.get(intent, "C")
        a_resp = self.call("graph_planner", {
            "intent_type": intent.upper().replace("-", "_"),
            "recommended_chain": chain,
            "confidence": 0.7,
        })
        a_result = a_resp["result"]
        self.stats["a_layer_calls"] += 1
        nodes = a_result.get("selected_nodes", [])
        budget = a_result.get("budget", {})
        print(f"  链路: {GREEN}{a_result.get('planned_chain', chain)}{RESET}")
        print(f"  节点: {', '.join(nodes[:6])}{'...' if len(nodes) > 6 else ''}")
        print(f"  预算: {budget}")
        result["steps"].append({"layer": "A", "chain": a_result.get("planned_chain"), "nodes": nodes})

        # G 层投影: graph_node
        self.call("session_consumer", {
            "session_id": self.session_id,
            "event_type": "graph_node",
            "event_data": {"phase": "A_planner", "chain": a_result.get("planned_chain"), "nodes": nodes},
        })
        self.stats["g_layer_calls"] += 1

        # ═══ C 层: 执行分析 ═══
        print(f"\n{BOLD}{CYAN}📍 C 层 — 执行分析 (GraphExecutor){RESET}")
        # 从用户输入提取 symbol
        symbol = "BTC"
        for s in ["BTC", "ETH", "SOL", "BNB", "DOGE"]:
            if s.lower() in user_input.lower():
                symbol = s
                break

        c_resp = self.call("execute_c_chain", {"symbol": symbol, "timeframe": "4H"})
        c_result = c_resp["result"]
        self.stats["c_layer_calls"] += 1
        direction = c_result["direction"]
        confidence = c_result["confidence"]
        details = c_result.get("details", {})
        exec_stats = c_result.get("execution_stats", {})

        dir_color = GREEN if direction == "LONG" else (RED if direction == "SHORT" else YELLOW)
        print(f"  综合方向: {dir_color}{direction}{RESET}")
        print(f"  置信度: {confidence}")
        print(f"  执行统计: {exec_stats}")
        for nid, ndata in details.items():
            nd = ndata.get("direction", "?")
            nc = ndata.get("confidence", 0)
            ns = ndata.get("status", "?")
            print(f"    {nid}: {nd} (conf={nc:.2f}, status={ns})")

        result["steps"].append({
            "layer": "C", "direction": direction, "confidence": confidence,
            "details": details, "exec_stats": exec_stats,
        })

        # G 层投影: node_result
        self.call("session_consumer", {
            "session_id": self.session_id,
            "event_type": "node_result",
            "event_data": {"symbol": symbol, "direction": direction, "confidence": confidence},
        })
        self.stats["g_layer_calls"] += 1

        # ═══ C 层 Reflector: 反射决策 ═══
        print(f"\n{BOLD}{CYAN}📍 C 层 — 反射决策 (Reflector){RESET}")
        r_resp = self.call("reflection", {
            "mode": "decide",
            "current_node_id": nodes[-1] if nodes else "C3",
            "confidence": confidence,
            "direction": direction,
            "status": "SUCCESS",
            "executed_count": len(nodes) if nodes else 3,
            "max_nodes": len(nodes) if nodes else 5,
            "budget_remaining_ratio": 0.7,
            "prev_results": [
                {"node_id": nid, "direction": nd.get("direction"), "confidence": nd.get("confidence")}
                for nid, nd in details.items()
            ],
        })
        r_result = r_resp["result"]["echo"]["params"]
        decision = r_result["decision"]
        self.stats["reflector_calls"] += 1
        dec_color = GREEN if decision == "CONTINUE" else (YELLOW if decision in ["REDO", "INSERT_BEFORE"] else RED)
        print(f"  反射决策: {dec_color}{decision}{RESET}")
        print(f"  原因: {r_result.get('reason', '')[:80]}")
        result["steps"].append({"layer": "C-Reflector", "decision": decision})

        # G 层投影: graph_node (reflector)
        self.call("session_consumer", {
            "session_id": self.session_id,
            "event_type": "graph_node",
            "event_data": {"phase": "C_reflector", "decision": decision},
        })
        self.stats["g_layer_calls"] += 1

        # ═══ 生成回复 ═══
        print(f"\n{BOLD}{GREEN}🤖 DreamOS 回复:{RESET}")
        reply = self._generate_reply(user_input, intent, risk, symbol, direction, confidence, details, decision)
        for line in reply.split("\n"):
            print(f"  {line}")
        result["reply"] = reply

        print(f"\n{CYAN}{'─'*70}{RESET}")
        return result

    def _generate_reply(self, user_input, intent, risk, symbol, direction, confidence, details, decision):
        """根据各层结果生成自然语言回复"""
        dir_text = {"LONG": "看多（建议做多）", "SHORT": "看空（建议做空/观望）", "HOLD": "中性（建议观望）"}
        risk_text = {"low": "低风险", "medium": "中等风险", "high": "高风险"}

        lines = []
        lines.append(f"针对您的问题「{user_input[:30]}...」，分析结果如下：")
        lines.append("")
        lines.append(f"【意图识别】{intent}（{risk_text.get(risk, risk)}）")
        lines.append(f"【市场分析】{symbol} 当前方向: {dir_text.get(direction, direction)}")
        lines.append(f"【置信度】{confidence:.0%}")
        lines.append("")

        # 各节点分析摘要
        node_names = {"C1": "技术扫描", "C2": "动量分析", "C3": "波动率分析"}
        lines.append("【多维度分析】")
        for nid, ndata in details.items():
            name = node_names.get(nid, nid)
            nd = ndata.get("direction", "?")
            nc = ndata.get("confidence", 0)
            lines.append(f"  - {name}: {nd} (置信度 {nc:.0%})")

        lines.append("")
        # 决策建议
        if decision == "CONTINUE":
            lines.append("【调度决策】继续执行后续节点，信号一致性良好。")
        elif decision == "REDO":
            lines.append("【调度决策】信号置信度不足，建议重新执行分析。")
        elif decision == "JUMP_TO":
            lines.append("【调度决策】预算紧张，跳转到离场评估节点。")
        elif decision == "EARLY_TERMINATE":
            lines.append("【调度决策】信号矛盾过大，终止本轮分析。")
        else:
            lines.append(f"【调度决策】{decision}")

        lines.append("")
        lines.append("⚠️ 以上分析仅供参考，不构成投资建议。")
        return "\n".join(lines)

    def print_stats(self):
        """打印运行统计"""
        print(f"\n{BOLD}{MAGENTA}{'═'*70}{RESET}")
        print(f"{BOLD}📊 运行数据统计{RESET}")
        print(f"{MAGENTA}{'═'*70}{RESET}")
        print(f"  会话 ID: {self.session_id}")
        print(f"  总请求数: {self.stats['total_requests']}")
        print(f"  S 层调用: {self.stats['s_layer_calls']} 次")
        print(f"  A 层调用: {self.stats['a_layer_calls']} 次")
        print(f"  C 层调用: {self.stats['c_layer_calls']} 次")
        print(f"  Reflector 调用: {self.stats['reflector_calls']} 次")
        print(f"  G 层投影: {self.stats['g_layer_calls']} 次")
        print(f"  总延迟: {self.stats['total_latency_ms']:.0f} ms")
        if self.stats["total_requests"] > 0:
            avg = self.stats["total_latency_ms"] / self.stats["total_requests"]
            print(f"  平均延迟/请求: {avg:.0f} ms")

        print(f"\n{BOLD}调度日志:{RESET}")
        for i, log in enumerate(self.logs, 1):
            status = "✅" if log["ok"] else "❌"
            print(f"  [{i:2d}] {status} {log['method']:25s} {log['latency_ms']:8.1f} ms")


def run_auto_tests():
    """自动测试多个场景"""
    sim = HarnessSimulator()

    scenarios = [
        "分析 BTC 当前趋势，判断是否适合入场",
        "ETH 最近波动很大，帮我看看风险如何",
        "现在市场情绪怎么样，适合做短线吗",
        "SOL 有没有突破迹象，技术面如何",
    ]

    print(f"\n{BOLD}🚀 Harness 前端交互模拟验证{RESET}")
    print(f"验证 DreamOS + Harness 集成后的 S→A→C→G 全链路交互能力")
    print(f"{'═'*70}")

    for scenario in scenarios:
        try:
            sim.handle_user_input(scenario)
        except Exception as e:
            print(f"{RED}ERROR: {e}{RESET}")

    sim.print_stats()

    # 验证 G 层投影
    g_path = os.path.join(
        os.path.dirname(__file__), "..", "packages", ".session-projections", "g_layer_events.jsonl"
    )
    if os.path.exists(g_path):
        session_events = []
        with open(g_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line.strip())
                    if e.get("session_id") == sim.session_id:
                        session_events.append(e)
                except json.JSONDecodeError:
                    pass
        print(f"\n{BOLD}G 层投影验证:{RESET}")
        print(f"  g_layer_events.jsonl 中本会话事件数: {len(session_events)}")
        event_types = set(e["event_type"] for e in session_events)
        print(f"  事件类型: {', '.join(sorted(event_types))}")


def run_interactive():
    """交互模式"""
    sim = HarnessSimulator()
    print(f"\n{BOLD}🚀 Harness 前端交互模式{RESET}")
    print("输入您的问题（输入 'quit' 退出）:")
    print(f"{'═'*70}")

    while True:
        try:
            user_input = input(f"\n{BOLD}您: {RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            break
        try:
            sim.handle_user_input(user_input)
        except Exception as e:
            print(f"{RED}处理出错: {e}{RESET}")

    sim.print_stats()


if __name__ == "__main__":
    if "--auto" in sys.argv:
        run_auto_tests()
    else:
        run_interactive()
