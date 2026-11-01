# -*- coding: utf-8 -*-
"""
cli.py — evalctl 门禁 CLI（P0-6 / P3-2 / P3-5 / SPEC §13.4）
============================================================
用法：
    evalctl gate --eval-id <id> [--wait [--timeout S] [--poll-interval S]]
    evalctl enforce --kind deploy|l0_settle --eval-id <id> [--approval-id <id>] [--require-approval]
    evalctl audit --eval-id <id>
    evalctl evidence --eval-id <id> [--out bundle.json]
    evalctl evidence --verify bundle.json [--require-signature]

退出码（CI / 部署脚本据此阻断，禁止解析日志判断，§13.4）：
    0 = PASS / 影子观测   2 = BLOCK   3 = INCONCLUSIVE   4 = ERROR（未知 id / 无报告 / 超时）

装配：
- 默认从环境变量 EVAL_PG_DSN 装配 PgRepo；未设置回退 InMemoryRepo（本地空跑）
- `enforce` 的影子/实盘由 config/categories.yaml 的 gate.shadow 决定（唯一开关）
- 27 审批台账路径由 EVAL_APPROVALS_LOG 给定；未配置即视为无审批（fail-closed）
- 证据包签名密钥由 EVAL_EVIDENCE_KEY 注入（EVAL_EVIDENCE_SIGNER 标注签名主体）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
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

    enforce = sub.add_parser("enforce", help="部署 / L0 沉淀门禁卡点（凭证 + 双凭证）")
    enforce.add_argument("--kind", required=True, choices=["deploy", "l0_settle"])
    enforce.add_argument("--eval-id", required=True, help="45 受理返回的 eval_id")
    enforce.add_argument("--approval-id", default=None, help="27 审批凭证 id（P3-4）")
    enforce.add_argument(
        "--require-approval",
        action="store_true",
        help="策略上线双凭证：必须同时持有 27 审批（SPEC §7）",
    )

    audit = sub.add_parser("audit", help="全链路审计查询：申请→执行→判定→门禁裁决")
    audit.add_argument("--eval-id", required=True, help="评测受理返回的 eval_id")

    evidence = sub.add_parser("evidence", help="证据包构建 / 离线验证（P4-1）")
    evidence.add_argument("--eval-id", default=None, help="构建证据包所用 eval_id")
    evidence.add_argument("--out", default=None, help="证据包落盘路径（JSON）")
    evidence.add_argument(
        "--archive", action="store_true", help="将证据包写入 WORM 对象存储（P4-2）"
    )
    evidence.add_argument("--verify", default=None, metavar="BUNDLE", help="离线验证本地证据包")
    evidence.add_argument(
        "--require-signature",
        action="store_true",
        help="离线验证时必须带签名（缺签名即失败）",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    repo: EvalRepo | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    out: Any = sys.stdout,
    shadow: bool | None = None,
    approvals: Callable[[str], bool] | None = None,
    audit_log: Any = None,
) -> int:
    """入口：返回退出码（不调用 sys.exit，便于测试注入）。"""
    args = _build_parser().parse_args(argv)
    if repo is None:
        repo = _default_repo()

    if args.command == "gate":
        return _gate(args, repo, sleeper, out)
    if args.command == "enforce":
        return _enforce(args, repo, shadow, approvals, audit_log, out)
    if args.command == "audit":
        return _audit(args, repo, audit_log, out)
    if args.command == "evidence":
        return _evidence(args, repo, out)
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


def _enforce(
    args: argparse.Namespace,
    repo: EvalRepo,
    shadow: bool | None,
    approvals: Callable[[str], bool] | None,
    audit_log: Any,
    out: Any,
) -> int:
    from core.enforcement import Enforcer
    from core.gate import Gate
    from core.gateway import CategoriesConfig
    from integrations.approvals import ApprovalChecker
    from storage.audit import AuditLog

    effective_shadow = CategoriesConfig.load().gate_shadow if shadow is None else shadow
    checker = approvals if approvals is not None else ApprovalChecker()
    log = audit_log if audit_log is not None else AuditLog()

    decision = Enforcer(
        gate=Gate(repo=repo), audit=log, shadow=effective_shadow, approvals=checker
    ).enforce(
        args.kind,
        args.eval_id,
        approval_id=args.approval_id,
        require_approval=args.require_approval,
    )
    print(json.dumps(decision.to_dict(), ensure_ascii=False), file=out)
    if decision.allowed:
        return EXIT_PASS
    if any("unknown_eval_id" in r or "no_report" in r for r in decision.reasons):
        return EXIT_ERROR
    return EXIT_BLOCK


def _audit(args: argparse.Namespace, repo: EvalRepo, audit_log: Any, out: Any) -> int:
    from core.audit_trace import TraceError, trace
    from storage.audit import AuditLog

    log = audit_log if audit_log is not None else AuditLog()
    try:
        payload = trace(repo, args.eval_id, log)
    except TraceError as exc:
        print(
            json.dumps({"eval_id": args.eval_id, "error": str(exc)}, ensure_ascii=False), file=out
        )
        return EXIT_ERROR
    print(json.dumps(payload, ensure_ascii=False, default=str), file=out)
    return EXIT_PASS


def _evidence(args: argparse.Namespace, repo: EvalRepo, out: Any) -> int:
    """证据包构建 / 离线验证（P4-1：哈希链 + Merkle 根 + HMAC 签名）。"""
    from storage.evidence import (
        DEFAULT_SIGNER,
        EvidenceError,
        build_bundle,
        verify_bundle,
    )

    key = os.environ.get("EVAL_EVIDENCE_KEY")
    signer = os.environ.get("EVAL_EVIDENCE_SIGNER", DEFAULT_SIGNER)

    if args.verify:
        path = Path(args.verify)
        if not path.is_file():
            print(json.dumps({"error": f"证据包不存在: {path}"}, ensure_ascii=False), file=out)
            return EXIT_ERROR
        try:
            bundle = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"证据包解析失败: {exc}"}, ensure_ascii=False), file=out)
            return EXIT_ERROR
        result = verify_bundle(bundle, key=key, require_signature=args.require_signature)
        print(
            json.dumps(
                {"ok": result.ok, "signed": result.signed, "reasons": result.reasons},
                ensure_ascii=False,
            ),
            file=out,
        )
        return EXIT_PASS if result.ok else EXIT_ERROR

    if not args.eval_id:
        print(
            json.dumps(
                {"error": "需指定 --eval-id（构建）或 --verify（离线验证）"}, ensure_ascii=False
            ),
            file=out,
        )
        return EXIT_ERROR

    try:
        bundle = build_bundle(repo, args.eval_id, key=key, signer=signer)
    except EvidenceError as exc:
        print(
            json.dumps({"eval_id": args.eval_id, "error": str(exc)}, ensure_ascii=False), file=out
        )
        return EXIT_ERROR

    if args.out:
        Path(args.out).write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    archived = None
    if args.archive:
        from storage.object_store import ObjectStoreError, archive_bundle, build_store

        try:
            archived = archive_bundle(build_store(), bundle, eval_id=args.eval_id)
        except ObjectStoreError as exc:
            print(
                json.dumps({"eval_id": args.eval_id, "error": str(exc)}, ensure_ascii=False),
                file=out,
            )
            return EXIT_ERROR

    print(
        json.dumps(
            {
                "eval_id": args.eval_id,
                "run_id": bundle["run_id"],
                "chain_entries": len(bundle["chain"]),
                "merkle_root": bundle["merkle_root"],
                "signed_by": (bundle["signature"] or {}).get("signed_by"),
                "out": args.out,
                "archive": archived,
            },
            ensure_ascii=False,
        ),
        file=out,
    )
    return EXIT_PASS


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
