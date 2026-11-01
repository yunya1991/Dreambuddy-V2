# -*- coding: utf-8 -*-
"""
cli.py — evalctl 门禁 CLI（P0-6 / SPEC §13.4）
==============================================
用法：
    evalctl gate --eval-id <id> [--wait [--timeout S] [--poll-interval S]]

退出码（CI 据此阻断，禁止解析日志判断，§13.4）：
    0 = PASS  2 = BLOCK  3 = INCONCLUSIVE  4 = ERROR（未知 id / 超时 / 未出分且未 --wait）

存储装配：
- 默认从环境变量 EVAL_PG_DSN 装配 PgRepo；未设置回退 InMemoryRepo（本地空跑）
- 测试可注入 repo / sleeper，避免真实等待
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Callable, Sequence

from storage.repo import EvalRepo, InMemoryRepo

logger = logging.getLogger("evalctl")

EXIT_PASS = 0
EXIT_BLOCK = 2
EXIT_INCONCLUSIVE = 3
EXIT_ERROR = 4

VERDICT_EXIT = {
    "PASS": EXIT_PASS,
    "BLOCK": EXIT_BLOCK,
    "INCONCLUSIVE": EXIT_INCONCLUSIVE,
}


def _default_repo() -> EvalRepo:
    dsn = os.environ.get("EVAL_PG_DSN")
    if dsn:
        from storage.repo import PgRepo

        return PgRepo(dsn)
    return InMemoryRepo()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evalctl",
        description="45-评测系统门禁 CLI（§13.4：退出码即判定，禁止解析日志）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gate = sub.add_parser("gate", help="查询评测门禁判定并以退出码返回")
    gate.add_argument("--eval-id", required=True, help="评测受理返回的 eval_id")
    gate.add_argument(
        "--wait",
        action="store_true",
        help="未出分时轮询等待，直至出分或 --timeout 超时",
    )
    gate.add_argument("--timeout", type=float, default=60.0, help="--wait 最长等待秒数")
    gate.add_argument("--poll-interval", type=float, default=1.0, help="轮询间隔秒数")
    return parser


def main(
    argv: Sequence[str] | None = None,
    repo: EvalRepo | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    out: Any = sys.stdout,
) -> int:
    """入口：返回退出码（不调用 sys.exit，便于测试注入）。"""
    args = _build_parser().parse_args(argv)
    if repo is None:
        repo = _default_repo()

    if args.command == "gate":
        return _gate(args, repo, sleeper, out)
    print(f"未知命令: {args.command}", file=out)
    return EXIT_ERROR


def _gate(
    args: argparse.Namespace, repo: EvalRepo, sleeper: Callable[[float], None], out: Any
) -> int:
    eval_id: str = args.eval_id
    report = repo.get_report(eval_id)

    if report is None and args.wait:
        deadline = time.monotonic() + args.timeout
        while report is None and time.monotonic() < deadline:
            sleeper(args.poll_interval)
            report = repo.get_report(eval_id)
        if report is None:
            print(
                json.dumps(
                    {"eval_id": eval_id, "error": f"等待超时（{args.timeout}s 未出分）"},
                    ensure_ascii=False,
                ),
                file=out,
            )
            return EXIT_ERROR

    if report is None:
        # 未出分：区分“未知 id”与“已受理未出分”，均按 ERROR（§13.4 无中间态）
        request = repo.get_request(eval_id)
        error = (
            f"已受理（状态 {request.status}）但尚未出分；请使用 --wait 等待"
            if request is not None
            else "未知 eval_id"
        )
        print(json.dumps({"eval_id": eval_id, "error": error}, ensure_ascii=False), file=out)
        return EXIT_ERROR

    verdict: str = report["verdict"]
    print(
        json.dumps(
            {
                "eval_id": eval_id,
                "verdict": verdict,
                "score": report.get("score"),
                "n": report.get("n"),
                "block_reasons": report.get("block_reasons", []),
                "spec_hash": report.get("spec_hash"),
                "expires_at": report.get("expires_at"),
            },
            ensure_ascii=False,
        ),
        file=out,
    )
    return VERDICT_EXIT[verdict]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
