#!/usr/bin/env python3
"""19-DAL 数据组件（内部）：仅本地只读查询。

设计边界（硬约束）：
- 只读：tools / scopes / tables / read / fetch / status；
- 仅本地：只读本地镜像库与本地工具，不联网、不触发同步、不写任何数据；
- 不注册 DAL 写能力（data_store_write）：DAL 写入口唯一在云端，见 CLAUDE.md。

实现方式：子进程编排 59 既有工具，不 import 组件外代码。
- tools/scopes/tables/read/fetch → tools/data_bridge.py（l0_data 只读工具）
- status                         → tools/cloud_sync.py --check（纯本地文件/sqlite 只读）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "tools"
DATA_BRIDGE = TOOLS / "data_bridge.py"
CLOUD_SYNC = TOOLS / "cloud_sync.py"


def _envelope(command: str, payload: Any, ok: bool = True) -> Dict[str, Any]:
    return {
        "schema_version": "1.0",
        "command": "dal-data.{}".format(command),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ok": ok,
        "data": payload,
    }


def _run(script: Path, argv: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _emit(command: str, proc: subprocess.CompletedProcess) -> int:
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        print(json.dumps(_envelope(command, detail, ok=False), ensure_ascii=False, indent=2))
        return 1
    try:
        payload = json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        payload = {"raw": (proc.stdout or "").strip()}
    print(json.dumps(_envelope(command, payload), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="19-DAL 数据组件（内部只读）")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("tools", help="列出 19-DAL 只读工具")
    sub.add_parser("scopes", help="列出可用数据 scope")
    sub.add_parser("tables", help="列出可读表与必填过滤参数")

    p_read = sub.add_parser("read", help="按 mm_metrics 查询")
    p_read.add_argument("--table", default="mm_metrics")
    p_read.add_argument("--sub-category", required=True)
    p_read.add_argument("--metric-name", required=True)
    p_read.add_argument("--start-ts", type=int, default=None)
    p_read.add_argument("--end-ts", type=int, default=None)
    p_read.add_argument("--limit", type=int, default=100)

    p_fetch = sub.add_parser("fetch", help="按 scope 取数据上下文")
    p_fetch.add_argument("--scope", required=True)
    p_fetch.add_argument("--params", default="{}")

    sub.add_parser("status", help="查看本地只读镜像新鲜度")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # 统一 CLI 会统一追加 --json；本组件始终输出 JSON，容忍该开关
    argv = [item for item in (sys.argv[1:] if argv is None else argv) if item != "--json"]
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "tools":
        return _emit("tools", _run(DATA_BRIDGE, ["tools"]))
    if args.cmd == "scopes":
        return _emit("scopes", _run(DATA_BRIDGE, ["scopes"]))
    if args.cmd == "tables":
        return _emit("tables", _run(DATA_BRIDGE, ["tables"]))
    if args.cmd == "read":
        argv_read = [
            "read",
            "--table",
            args.table,
            "--sub-category",
            args.sub_category,
            "--metric-name",
            args.metric_name,
            "--limit",
            str(args.limit),
        ]
        if args.start_ts is not None and args.end_ts is not None:
            argv_read += ["--start-ts", str(args.start_ts), "--end-ts", str(args.end_ts)]
        return _emit("read", _run(DATA_BRIDGE, argv_read))
    if args.cmd == "fetch":
        try:
            json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(
                json.dumps(
                    _envelope(
                        "fetch", "E_INPUT：--params 必须是 JSON（{}）".format(exc.msg), ok=False
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2
        return _emit(
            "fetch", _run(DATA_BRIDGE, ["fetch", "--scope", args.scope, "--params", args.params])
        )
    if args.cmd == "status":
        # 镜像过期时 cloud_sync --check 以非零退出码报告 stale，属正常状态而非命令失败
        proc = _run(CLOUD_SYNC, ["--check", "--json"])
        try:
            payload = json.loads(proc.stdout or "null")
        except json.JSONDecodeError:
            return _emit("status", proc)
        print(json.dumps(_envelope("status", payload), ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
