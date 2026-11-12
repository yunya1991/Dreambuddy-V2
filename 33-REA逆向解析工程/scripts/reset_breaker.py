#!/usr/bin/env python3
"""reset_breaker.py — T-G11 人工恢复断路器（必须填原因，写审计）

SPEC-33-G §2.8.2：
  - 断路器 open 后冻结 auto 7 天，阶段回落 S2
  - 恢复只能人工执行本脚本，且 reason 必填、写入 audit/breaker_audit.jsonl
  - reset 不自动升阶段：S2 → S3 仍需 advance_stage 的退出证据

用法：
  python3 scripts/reset_breaker.py --root policy --reason "故障已排查" --actor oncall
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.evolution.controller import ControllerError, EvolutionController  # noqa: E402
from core.evolution.policy_ledger import PolicyLedger  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="人工恢复断路器（必须填原因，写审计）")
    parser.add_argument("--root", default=str(_REPO_ROOT / "policy"), help="policy 根目录")
    parser.add_argument("--reason", required=True, help="恢复原因（必填，写审计）")
    parser.add_argument("--actor", default="operator", help="操作人")
    args = parser.parse_args(argv)

    controller = EvolutionController(PolicyLedger(args.root))
    try:
        document = controller.reset_breaker(reason=args.reason, actor=args.actor)
    except ControllerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "breaker": document,
                "stage": controller.stage(),
                "audit": str(controller.breaker_audit_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
