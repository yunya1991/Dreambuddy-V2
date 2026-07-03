"""
Dreambuddy OS — CLI 命令行工具

交互式交易分析终端，演示 S-A-C-G 全链路能力。

子命令:
    analyze    单次市场数据分析
    chat       对话式分析
    nodes      列出已注册节点
    status     Agent 状态
    history    历史记录
    serve      启动 HTTP API 服务
    repl       交互式 REPL

用法:
    python -m dreamos.apps.cli analyze --price 65000 --rsi 55
    python -m dreamos.apps.cli chat "BTC 现在能做多吗？"
    python -m dreamos.apps.cli serve --port 8000
    python -m dreamos.apps.cli repl
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional


def _build_agent(budget_mode: str = "standard"):
    """构建 TradingAgent（延迟导入，避免子命令慢启动）"""
    from dreamos.apps.trading_agent import TradingAgent
    return TradingAgent(budget_mode=budget_mode)


def _print_result(result: Dict[str, Any], verbose: bool = False) -> None:
    """格式化输出分析结果"""
    action = result.get("action", "HOLD")
    confidence = result.get("confidence", 0)

    # 颜色符号
    if action == "LONG":
        action_str = "\033[92m🟢 LONG 做多\033[0m"
    elif action == "SHORT":
        action_str = "\033[91m🔴 SHORT 做空\033[0m"
    else:
        action_str = "\033[93m🟡 HOLD 观望\033[0m"

    print()
    print("=" * 60)
    print(f"  交易决策: {action_str}  (置信度 {confidence:.1%})")
    print("=" * 60)
    print(f"  周期ID:   {result.get('cycle_id', '-')}")
    print(f"  意图:     {result.get('intent', {}).get('type', '-')} "
          f"({result.get('intent', {}).get('confidence', 0):.0%})")
    print(f"  链路:     {result.get('plan', {}).get('chain', '-')} "
          f"({', '.join(result.get('plan', {}).get('nodes', []))})")
    print(f"  耗时:     {result.get('latency_ms', 0):.0f}ms")
    print(f"  Token:    {result.get('tokens_used', 0)}")
    print("-" * 60)

    rationale = result.get("rationale", [])
    if rationale:
        print("  分析依据:")
        for r in rationale[:8]:  # 最多显示 8 条
            print(f"    {r}")
        if len(rationale) > 8:
            print(f"    ... 还有 {len(rationale) - 8} 条")
        print("-" * 60)

    if verbose:
        print("  完整结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    print()


def cmd_analyze(args: argparse.Namespace) -> int:
    """analyze 子命令 — 单次市场数据分析"""
    agent = _build_agent(budget_mode=args.budget)

    market_data = {
        "price": args.price,
        "rsi14": args.rsi,
        "ema20": args.ema20,
        "ema50": args.ema50,
        "ema200": args.ema200,
        "change_24h": args.change_24h,
        "change_4h": args.change_4h,
        "change_1h": args.change_1h,
        "vol_ratio": args.vol_ratio,
        "regime": args.regime,
        "funding_rate": args.funding,
        "fgi": args.fgi,
        "atr_pct": args.atr / 100,
    }

    # 清理 None 值
    market_data = {k: v for k, v in market_data.items() if v is not None}

    user_input = args.input or ""

    result = agent.run(
        user_input=user_input,
        market_data=market_data,
    )

    _print_result(result, verbose=args.verbose)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    """chat 子命令 — 对话式分析"""
    agent = _build_agent(budget_mode=args.budget)

    market_data = {}
    if args.price is not None:
        market_data["price"] = args.price
    if args.rsi is not None:
        market_data["rsi14"] = args.rsi

    result = agent.chat(
        message=args.message,
        market_data=market_data,
    )

    _print_result(result, verbose=args.verbose)
    return 0


def cmd_nodes(args: argparse.Namespace) -> int:
    """nodes 子命令 — 列出节点"""
    agent = _build_agent()

    nodes = agent.registry.list_nodes()
    print(f"\n已注册节点: {len(nodes)} 个\n")

    # 按链分组
    chains: Dict[str, List] = {}
    for n in nodes:
        chain = getattr(n, "chain", "?")
        chains.setdefault(chain, []).append(n)

    for chain, chain_nodes in sorted(chains.items()):
        print(f"  [{chain} 链]  {len(chain_nodes)} 个节点:")
        for n in chain_nodes:
            tags = ", ".join(n.tags or [])
            print(f"    {n.node_id:4s} {n.name:10s} "
                  f"({n.estimated_latency_ms}ms, {n.estimated_tokens}tok) "
                  f"[{tags}]")
            if n.description and args.verbose:
                print(f"         {n.description}")
        print()

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """status 子命令 — Agent 状态"""
    agent = _build_agent()

    status = agent.status()
    print(f"\n🤖 Dreambuddy OS — Trading Agent 状态\n")
    print(f"  执行周期:   {status['cycles_executed']}")
    print(f"  节点数量:   {status['registered_nodes']}")
    print(f"  历史记录:   {status['history_count']}")
    print(f"  检查点数:   {status['checkpoint_count']}")

    budget = status.get("budget", {})
    print(f"\n  预算模式:   {budget.get('mode', '-')}")
    print(f"  健康状态:   {budget.get('level', '-')}")
    per_cycle = budget.get("per_cycle", {})
    print(f"  周期预算:   {per_cycle.get('used', 0)}/{per_cycle.get('budget', 0)} "
          f"({per_cycle.get('usage_ratio', 0):.1%})")

    print()
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """history 子命令 — 历史记录"""
    agent = _build_agent()

    entries = agent.history(limit=args.limit)
    print(f"\n历史记录: {len(entries)} 条\n")

    for i, e in enumerate(entries, 1):
        action = e.get("final_action", "?")
        conf = e.get("final_confidence", 0)
        intent = e.get("intent_type", "?")
        cid = e.get("cycle_id", "?")
        print(f"  {i:2d}. [{cid}] {intent:20s} → {action:5s} ({conf:.0%})")

    print()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """serve 子命令 — 启动 HTTP API"""
    from dreamos.apps.api_server import create_app

    app = create_app(budget_mode=args.budget)
    print(f"🚀 Dreambuddy OS API Server")
    print(f"   http://{args.host}:{args.port}")
    print(f"   预算模式: {args.budget}")
    print()
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


def cmd_repl(args: argparse.Namespace) -> int:
    """repl 子命令 — 交互式 REPL"""
    agent = _build_agent(budget_mode=args.budget)

    print("\n🤖 Dreambuddy OS — 交互式分析终端")
    print("   输入自然语言或市场数据查询，输入 quit/exit 退出")
    print("   提示: 输入 'status' 看状态，'nodes' 看节点，'history' 看历史\n")

    while True:
        try:
            user_input = input("\033[94m[你]\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            return 0

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("👋 再见！")
            return 0
        if user_input.lower() == "status":
            cmd_status(args)
            continue
        if user_input.lower() == "nodes":
            cmd_nodes(args)
            continue
        if user_input.lower() == "history":
            cmd_history(args)
            continue

        try:
            result = agent.chat(message=user_input)
            _print_result(result, verbose=args.verbose)
        except Exception as e:
            print(f"\n  ❌ 错误: {e}\n")

    return 0


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dreamos",
        description="Dreambuddy OS — 意图驱动的 AI 交易操作系统",
    )
    parser.add_argument("--budget", default="standard",
                        choices=["lean", "standard", "full"],
                        help="预算模式 (默认: standard)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="详细输出")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ── analyze ────────────────────────────
    p_analyze = subparsers.add_parser("analyze", help="单次市场数据分析")
    p_analyze.add_argument("--price", type=float, help="当前价格")
    p_analyze.add_argument("--rsi", type=float, help="RSI 14 值")
    p_analyze.add_argument("--ema20", type=float, help="EMA 20")
    p_analyze.add_argument("--ema50", type=float, help="EMA 50")
    p_analyze.add_argument("--ema200", type=float, help="EMA 200")
    p_analyze.add_argument("--change-24h", type=float, help="24h 涨跌幅 %")
    p_analyze.add_argument("--change-4h", type=float, help="4h 涨跌幅 %")
    p_analyze.add_argument("--change-1h", type=float, help="1h 涨跌幅 %")
    p_analyze.add_argument("--vol-ratio", type=float, help="量比")
    p_analyze.add_argument("--regime", default="TREND",
                           choices=["TREND", "RANGE"], help="市场状态")
    p_analyze.add_argument("--funding", type=float, help="资金费率 (如 0.0001)")
    p_analyze.add_argument("--fgi", type=float, help="恐惧贪婪指数 (0-100)")
    p_analyze.add_argument("--atr", type=float, help="ATR 百分比")
    p_analyze.add_argument("-i", "--input", type=str, help="用户输入文本")
    p_analyze.set_defaults(func=cmd_analyze)

    # ── chat ──────────────────────────────
    p_chat = subparsers.add_parser("chat", help="对话式分析")
    p_chat.add_argument("message", help="分析请求")
    p_chat.add_argument("--price", type=float, help="当前价格")
    p_chat.add_argument("--rsi", type=float, help="RSI 值")
    p_chat.set_defaults(func=cmd_chat)

    # ── nodes ─────────────────────────────
    p_nodes = subparsers.add_parser("nodes", help="列出已注册节点")
    p_nodes.set_defaults(func=cmd_nodes)

    # ── status ────────────────────────────
    p_status = subparsers.add_parser("status", help="Agent 状态")
    p_status.set_defaults(func=cmd_status)

    # ── history ───────────────────────────
    p_history = subparsers.add_parser("history", help="历史记录")
    p_history.add_argument("-n", "--limit", type=int, default=10,
                           help="显示数量 (默认 10)")
    p_history.set_defaults(func=cmd_history)

    # ── serve ─────────────────────────────
    p_serve = subparsers.add_parser("serve", help="启动 HTTP API 服务")
    p_serve.add_argument("--host", default="0.0.0.0", help="监听地址")
    p_serve.add_argument("--port", type=int, default=8000, help="监听端口")
    p_serve.add_argument("--debug", action="store_true", help="调试模式")
    p_serve.set_defaults(func=cmd_serve)

    # ── repl ──────────────────────────────
    p_repl = subparsers.add_parser("repl", help="交互式 REPL")
    p_repl.set_defaults(func=cmd_repl)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
