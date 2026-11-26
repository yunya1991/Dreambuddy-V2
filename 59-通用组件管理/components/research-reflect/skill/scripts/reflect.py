#!/usr/bin/env python3
"""research-reflect：OKA 反思资产的薄封装（只读交易库，写入仅限反向目录）。

动作：status / propose / gaps / review。所有动作透传 `oka ... --json`，
输出统一为 `data.v1`（skill/version/data_date/limits + payload）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

VERSION = "0.1.0"


def oka_root() -> str:
    return os.path.expanduser(os.environ.get("OKA_HOME") or "~/Documents/顺风车业务/okx-assistant")


def run_oka(args: list[str]) -> dict:
    cli = os.path.join(oka_root(), "skill", "scripts", "oka.py")
    if not os.path.isfile(cli):
        return {
            "ok": False,
            "exit_code": -1,
            "error": "找不到 OKA CLI：{}".format(cli),
            "payload": None,
        }
    argv = [sys.executable, cli] + args + ["--json"]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=os.path.join(oka_root(), "skill", "scripts"),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "exit_code": -1,
            "error": "{}: {}".format(type(exc).__name__, exc),
            "payload": None,
        }
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"raw": (proc.stdout or "")[:1000]}
    return {
        "ok": proc.returncode in (0, 5),
        "exit_code": proc.returncode,
        "payload": payload,
        "stderr": (proc.stderr or "")[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="research-reflect")
    parser.add_argument("action", choices=["status", "propose", "gaps", "review"])
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--window", default="90d")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--opt-id", dest="opt_id", default="")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.action == "status":
        command = ["reverse", "proposals", "--limit", str(args.limit)]
    elif args.action == "propose":
        command = ["reverse", "propose", "--window", args.window]
        if args.symbols:
            command += ["--symbols", args.symbols]
    elif args.action == "gaps":
        command = ["backtest", "samples", "gaps"]
    else:
        if not args.opt_id:
            print(
                json.dumps(
                    {
                        "skill": "research-reflect",
                        "version": VERSION,
                        "data_date": "",
                        "limits": "",
                        "error": "缺少 --opt-id",
                    },
                    ensure_ascii=False,
                )
            )
            return 2
        command = ["reverse", "review", "--opt-id", args.opt_id]
        if args.no_llm:
            command.append("--no-llm")

    result = run_oka(command)
    output = {
        "skill": "research-reflect",
        "version": VERSION,
        "data_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "limits": "透传 OKA；propose/review 仅写本地 reverse 目录，不触订单",
        "payload": result.get("payload"),
        "ok": result.get("ok"),
        "exit_code": result.get("exit_code"),
    }
    if result.get("error"):
        output["error"] = result["error"]
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
