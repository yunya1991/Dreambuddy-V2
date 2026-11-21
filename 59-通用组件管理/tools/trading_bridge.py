#!/usr/bin/env python3
"""6-TRADING 交易域桥（P4）：把 l1_trading MCP 的只读状态工具接进 dreambuddy CLI。

只暴露只读工具（get_*）；forward_signal 是写动作，永远不在此桥暴露。
交易执行仍走 l0.trade-exec MCP / 11 域 okx_client，本桥只读不写。

用法:
    python3 tools/trading_bridge.py tools
    python3 tools/trading_bridge.py signal
    python3 tools/trading_bridge.py bus --symbol BTC --limit 20
    python3 tools/trading_bridge.py positions --symbol BTC
    python3 tools/trading_bridge.py balance
    python3 tools/trading_bridge.py call get_cycle_state --args '{}'
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

MODULE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = MODULE_ROOT.parent
SERVER_PATH = REPO_ROOT / "mcp_shells" / "l1_trading" / "server.py"
DOMAIN = "6-trading"
READ_TOOLS = (
    "get_signal_state",
    "get_bus_state",
    "get_constraint_state",
    "get_cycle_state",
    "get_strategic_extension",
    "get_decision_diagnostics",
    "get_training_status",
    "get_positions",
    "get_balance",
)
ALIASES = {
    "signal": "get_signal_state",
    "bus": "get_bus_state",
    "constraint": "get_constraint_state",
    "cycle": "get_cycle_state",
    "strategic": "get_strategic_extension",
    "diagnostics": "get_decision_diagnostics",
    "training": "get_training_status",
    "positions": "get_positions",
    "balance": "get_balance",
}


def load_core():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("l1_trading_server", str(SERVER_PATH))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("无法加载 l1_trading/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tools() -> List[Dict[str, Any]]:
    core = load_core()
    return [
        {
            "name": item["name"],
            "description": item["description"],
            "inputSchema": item.get("inputSchema") or {"type": "object", "properties": {}},
            "safety": "read",
            "domain": DOMAIN,
            "source": getattr(core, "SHELL_SOURCE", "l1.trading.mcp"),
        }
        for item in core._TOOLS
        if item["name"] in READ_TOOLS
    ]


def call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if name not in READ_TOOLS:
        raise ValueError("E_GUARD：{} 不是交易域桥暴露的只读工具".format(name))
    core = load_core()
    raw = core._TOOL_HANDLERS[name](dict(arguments or {}))
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("E_TRADING：工具返回不是对象")
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="6-TRADING 只读状态桥")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("tools", help="列出只读工具")
    for alias in ALIASES:
        p_alias = sub.add_parser(alias, help="等价 {}".format(ALIASES[alias]))
        if alias == "bus":
            p_alias.add_argument("--symbol", default="")
            p_alias.add_argument("--limit", type=int, default=50)
        elif alias == "positions":
            p_alias.add_argument("--symbol", default="")

    p_call = sub.add_parser("call", help="通用只读调用")
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}")

    args = parser.parse_args(argv)
    if args.cmd == "tools":
        print(json.dumps(tools(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "call":
        try:
            payload = call(args.tool, json.loads(args.args))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 1
    if args.cmd in ALIASES:
        arguments: Dict[str, Any] = {}
        if args.cmd == "bus":
            if args.symbol:
                arguments["symbol"] = args.symbol
            arguments["limit"] = args.limit
        elif args.cmd == "positions" and args.symbol:
            arguments["symbol"] = args.symbol
        payload = call(ALIASES[args.cmd], arguments)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok", True) else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
