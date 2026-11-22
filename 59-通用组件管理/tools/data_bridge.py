#!/usr/bin/env python3
"""19-DAL 数据桥（P3）：把 l0_data MCP 的只读数据工具接进 dreambuddy CLI。

只暴露只读工具（data_fetch / data_collect_once / data_store_read）；
data_store_write 永远不在此桥暴露（DAL 写入口唯一在云端，见 CLAUDE.md 硬约束）。

用法:
    python3 tools/data_bridge.py tools
    python3 tools/data_bridge.py scopes
    python3 tools/data_bridge.py read --table mm_metrics \\
        --sub-category macro --metric-name DGS10 --limit 10
    python3 tools/data_bridge.py read --table mm_metrics \\
        --sub-category macro --metric-name DGS10 --start-ts 1735689600 --end-ts 1767225600
    python3 tools/data_bridge.py fetch --scope market --params '{"symbol":"BTC"}'
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
SERVER_PATH = REPO_ROOT / "mcp_shells" / "l0_data" / "server.py"
READ_TOOLS = ("data_fetch", "data_collect_once", "data_store_read", "data_tables")


def load_core():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location("l0_data_server", str(SERVER_PATH))
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("无法加载 l0_data/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tools() -> List[Dict[str, Any]]:
    core = load_core()
    return [
        {
            "name": name,
            "description": core.TOOL_DEFS[name]["description"],
            "inputSchema": core.TOOL_DEFS[name]["inputSchema"],
            "safety": "read",
            "source": core.SHELL_SOURCE,
        }
        for name in READ_TOOLS
    ]


def call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if name not in READ_TOOLS:
        raise ValueError("E_GUARD：{} 不是数据桥暴露的只读工具".format(name))
    core = load_core()
    raw = core.TOOL_HANDLERS[name](dict(arguments or {}))
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("E_DATA：工具返回不是对象")
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="19-DAL 只读数据桥")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("tools", help="列出只读工具")
    sub.add_parser("scopes", help="列出可用数据 scope")
    sub.add_parser("tables", help="列出可读表与必填过滤参数")

    p_read = sub.add_parser("read", help="按 mm_metrics 查询（最新值或时间窗）")
    p_read.add_argument("--table", default="mm_metrics")
    p_read.add_argument("--sub-category", required=True)
    p_read.add_argument("--metric-name", required=True)
    p_read.add_argument("--start-ts", type=int, default=None)
    p_read.add_argument("--end-ts", type=int, default=None)
    p_read.add_argument("--limit", type=int, default=100)

    p_fetch = sub.add_parser("fetch", help="按 scope 取数据上下文")
    p_fetch.add_argument("--scope", required=True)
    p_fetch.add_argument("--params", default="{}")

    args = parser.parse_args(argv)
    if args.cmd == "tools":
        print(json.dumps(tools(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "scopes":
        payload = call("data_collect_once", {})
    elif args.cmd == "tables":
        payload = call("data_tables", {})
    elif args.cmd == "read":
        filters: Dict[str, Any] = {
            "sub_category": args.sub_category,
            "metric_name": args.metric_name,
        }
        if args.start_ts is not None and args.end_ts is not None:
            filters["start_ts"] = args.start_ts
            filters["end_ts"] = args.end_ts
        payload = call(
            "data_store_read", {"table": args.table, "filters": filters, "limit": args.limit}
        )
    elif args.cmd == "fetch":
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print("E_INPUT：--params 必须是 JSON（{}）".format(exc.msg), file=sys.stderr)
            return 2
        payload = call("data_fetch", {"scope": args.scope, "params": params})
    else:
        parser.print_help()
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
