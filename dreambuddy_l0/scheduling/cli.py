"""C9 调度记账 CLI：注册表查询 / run 记账 / missed_run 审计 / 90 天保留。

用法：
  python -m dreambuddy_l0.scheduling.cli list
  python -m dreambuddy_l0.scheduling.cli run --task-key dc.backfill.cloud --now <epoch>
  python -m dreambuddy_l0.scheduling.cli wrap --task-key index.reconcile.cloud -- <cmd...>
  python -m dreambuddy_l0.scheduling.cli audit --now <epoch>
  python -m dreambuddy_l0.scheduling.cli prune --now <epoch>

落库路径：--path 或环境变量 JOB_RUNS_PATH（默认 <repo>/logs/job_runs.jsonl）。
本 CLI 是只读旁路/非实盘链路的记账入口，禁止接入实盘进程（见 SPEC-L0 §10 风险）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import List

from ..adapters.jsonl import JsonlEvent, JsonlStore
from ..scheduling.job_runs import JobRunRecorder
from ..scheduling.registry import load_registry

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_PATH = os.path.join(_REPO_ROOT, "logs", "job_runs.jsonl")


def _recorder(args) -> JobRunRecorder:
    path = args.path or os.environ.get("JOB_RUNS_PATH") or DEFAULT_PATH
    return JobRunRecorder(
        store=JsonlStore(path),
        event=JsonlEvent(path),
        registry=load_registry(args.registry),
    )


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, default=str))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dreambuddy_l0.scheduling")
    parser.add_argument("--path", default="")
    parser.add_argument("--registry", default="")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list")

    p_run = sub.add_parser("run")
    p_run.add_argument("--task-key", required=True)
    p_run.add_argument("--now", type=float, default=None)
    p_run.add_argument("--error", default="")

    p_wrap = sub.add_parser("wrap")
    p_wrap.add_argument("--task-key", required=True)
    p_wrap.add_argument("command", nargs=argparse.REMAINDER)

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("--now", type=float, default=None)

    p_prune = sub.add_parser("prune")
    p_prune.add_argument("--now", type=float, default=None)

    args = parser.parse_args(argv)
    rec = _recorder(args)
    now = time.time() if getattr(args, "now", None) is None else args.now

    if args.cmd == "list":
        _print({"tasks": [s.__dict__ for s in rec.registry.list()]})
        return 0

    if args.cmd == "run":
        try:
            rows = rec.record_run(args.task_key, started_ts=now, finished_ts=now, error=args.error)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        _print({"rows": rows})
        return 0

    if args.cmd == "wrap":
        cmd = [c for c in args.command if c != "--"]
        if not cmd:
            print("ERROR: wrap 需要 -- <cmd...>", file=sys.stderr)
            return 2
        started = time.time()
        row = rec.begin(
            args.task_key,
            window=int(started // rec.registry.get(args.task_key).window_sec),
            now=started,
        )
        try:
            code = subprocess.call(cmd)
        except Exception as exc:  # 记账侧异常不得改变被包装命令的语义
            code = 127
            rec.finish(row["run_id"], now=time.time(), state="failed", error=str(exc))
            print(f"ERROR: wrap 执行失败 {exc}", file=sys.stderr)
            return code
        rec.finish(
            row["run_id"],
            now=time.time(),
            state="succeeded" if code == 0 else "failed",
            error="" if code == 0 else f"exit={code}",
        )
        _print({"row": row["run_id"], "exit_code": code})
        return code

    if args.cmd == "audit":
        _print(rec.audit(now_ts=now))
        return 0

    if args.cmd == "prune":
        _print(rec.prune(now_ts=now))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
