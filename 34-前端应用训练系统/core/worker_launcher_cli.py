# -*- coding: utf-8 -*-
"""D3 拉起器运维 CLI（W4）。

子命令（systemd 与人工运维共用；参数默认值取自 EnvironmentFile）：

    preflight  启动前检查：花名册非空且自检通过、状态目录可写、offset 可读
    once       单轮消费（本地联调 / 手动补跑）
    run        常驻循环（systemd ExecStart）；SIGTERM/SIGINT 优雅退出
    status    打印 metrics.json 与 claims 摘要

环境变量：
    D3_ROOT             仓库根（默认按 core/ 反推）
    D3_ROLES_PATH       花名册 yaml（47 registry）
    D3_WORKERS          本地 roster，逗号分隔；缺省接受任意 worker_id
    D3_EXECUTOR         inproc | dsh-cli | noop（默认 inproc）
    D3_PROFILE          DSH profile（默认 sandbox）
    D3_MAX_CONCURRENCY  批内并发上限（默认 8）
    D3_POLL_INTERVAL    空闲轮询间隔秒（默认 0.5）
    D3_MODEL_PROVIDER / D3_MODEL_NAME   子会话必须显式模型路由
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sys
import threading
from typing import Any, Dict, List, Optional

if __package__ in (None, ""):  # 允许 `python core/worker_launcher_cli.py`
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.inproc_session_executor import InProcessSessionExecutor  # noqa: E402
from core.worker_launcher import DshCliExecutor, WorkerLauncher  # noqa: E402
from core.worker_roles import DEFAULT_ROLES_PATH, RolePolicy, load_worker_roles  # noqa: E402


class _NoopExecutor:
    """本地冒烟用：不调用任何模型，直接回 done。"""

    def __call__(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "done", "evidence": {"summary": "noop executor", "duration_ms": 0}}


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worker_launcher_cli")
    parser.add_argument("command", choices=("preflight", "once", "run", "status"))
    parser.add_argument("--root", default=_env("D3_ROOT"))
    parser.add_argument("--roles", default=_env("D3_ROLES_PATH", DEFAULT_ROLES_PATH))
    parser.add_argument("--workers", default=_env("D3_WORKERS"))
    parser.add_argument("--executor", default=_env("D3_EXECUTOR", "inproc"))
    parser.add_argument("--profile", default=_env("D3_PROFILE", "sandbox"))
    parser.add_argument("--max-concurrency", type=int, default=int(_env("D3_MAX_CONCURRENCY", "8")))
    parser.add_argument(
        "--poll-interval", type=float, default=float(_env("D3_POLL_INTERVAL", "0.5"))
    )
    return parser


def _make_executor(args: argparse.Namespace) -> Any:
    kind = str(args.executor or "inproc").lower()
    if kind == "noop":
        return _NoopExecutor()
    if kind == "dsh-cli":
        return DshCliExecutor(profile=args.profile, dsh_bin=_env("D3_DSH_BIN", "dsh") or "dsh")
    return InProcessSessionExecutor(
        root=args.root,
        profile=args.profile,
        max_concurrency=max(1, int(args.max_concurrency)),
        dsh_bin=_env("D3_DSH_BIN", "dsh") or "dsh",
    )


def _make_launcher(args: argparse.Namespace) -> WorkerLauncher:
    roles = load_worker_roles(args.roles)
    workers = None
    if args.workers:
        workers = {w.strip() for w in str(args.workers).split(",") if w.strip()}
    return WorkerLauncher(
        args.root,
        roles=roles,
        executor=_make_executor(args),
        worker_ids=workers,
    )


def _probe_writable(directory: str) -> Optional[str]:
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, ".preflight_probe")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.unlink(probe)
        return None
    except Exception as exc:
        return "not writable: %s (%s)" % (directory, exc)


def _preflight(args: argparse.Namespace) -> int:
    problems: List[str] = []
    roles = load_worker_roles(args.roles)
    if not roles:
        problems.append("roster: worker_roles empty (%s)" % args.roles)
    else:
        problems.extend("roster: %s" % p for p in RolePolicy(roles).validate())

    launcher = _make_launcher(args)
    for directory, label in (
        (launcher.state_dir, "state_dir"),
        (os.path.dirname(launcher.receipts_path), "receipts_dir"),
    ):
        problem = _probe_writable(directory)
        if problem:
            problems.append("%s %s" % (label, problem))

    if os.path.exists(launcher.offset_path):
        try:
            with open(launcher.offset_path, encoding="utf-8") as handle:
                json.load(handle)
        except Exception as exc:
            problems.append("offset unreadable: %s (%s)" % (launcher.offset_path, exc))

    report = {"ok": not problems, "problems": problems, "root": launcher.root}
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if not problems else 2


def _once(args: argparse.Namespace) -> int:
    stats = _make_launcher(args).run_once()
    print(json.dumps(stats, ensure_ascii=False), flush=True)
    return 0 if not stats.get("errors") else 1


def _acquire_instance_lock(path: str) -> Optional[Any]:
    """单实例锁（§4.9 高可用：首版 flock 防双开）；已被占用返回 None。"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")
    except OSError:
        return None
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
    except OSError:
        pass
    return handle


def _run(args: argparse.Namespace) -> int:
    launcher = _make_launcher(args)
    lock = _acquire_instance_lock(os.path.join(launcher.state_dir, "launcher.lock"))
    if lock is None:
        print(
            json.dumps(
                {"event": "already_running", "state_dir": launcher.state_dir},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 3
    stop = threading.Event()

    def handle(signum: int, _frame: Any) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle)
        except (ValueError, OSError):
            pass

    def on_pass(stats: Dict[str, Any]) -> None:
        print(json.dumps({"event": "pass", **stats}, ensure_ascii=False), flush=True)

    launcher.run_forever(poll_interval=args.poll_interval, stop=stop, on_pass=on_pass)
    print(json.dumps({"event": "stopped"}, ensure_ascii=False), flush=True)
    return 0


def _status(args: argparse.Namespace) -> int:
    launcher = _make_launcher(args)
    claims: Any = {}
    if os.path.exists(launcher.claims_path):
        try:
            with open(launcher.claims_path, encoding="utf-8") as handle:
                claims = json.load(handle)
        except Exception:
            claims = {}
    by_state: Dict[str, int] = {}
    if isinstance(claims, dict):
        for entry in claims.values():
            state = str((entry or {}).get("state") or "unknown")
            by_state[state] = by_state.get(state, 0) + 1
    report = {
        "metrics": launcher.metrics.snapshot(),
        "claims": {"total": sum(by_state.values()), "by_state": by_state},
    }
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {
        "preflight": _preflight,
        "once": _once,
        "run": _run,
        "status": _status,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
