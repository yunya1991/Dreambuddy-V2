#!/usr/bin/env python3
"""G5 沉淀门禁（SPEC §6 / contracts/gates.yaml）。

判定：record_ids 非空（认知已回写）+ doc_changes 已登记 + arch_issues 已回写（可为空但不能缺字段）。
G5 未过不得关闭 run（phase=CLOSED）。

settle.json 契约：
{
  "run_id": "...",
  "record_ids": ["VM-..."],
  "verified": true,
  "doc_changes": ["1-ARCHITECTURE/specs/xxx.md"],
  "adr": "ADR-xxx 或 null",
  "arch_issues": ["..."]
}

用法：
  python3 .trae/skills/dreamos-dev/scripts/g5_check.py --run .runs/<run_id>/run.json
输出：单条 JSON 证据，exit 0=通过 1=不得关闭 run 2=用法错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check(settle: dict, run: dict | None) -> tuple[bool, list[dict]]:
    record_ids = [x for x in (settle.get("record_ids") or []) if str(x).strip()]
    doc_changes = settle.get("doc_changes")
    arch_issues = settle.get("arch_issues")

    checks = [
        {
            "id": "record_evidence",
            "ok": bool(record_ids),
            "detail": (
                f"record_ids={len(record_ids)}" if record_ids else "缺认知回写（record_ids 为空）"
            ),
        },
        {
            "id": "doc_changes_declared",
            "ok": isinstance(doc_changes, list),
            "detail": (
                f"文档变更 {len(doc_changes)} 项"
                if isinstance(doc_changes, list)
                else "缺 doc_changes 字段（无变更也须填空数组）"
            ),
        },
        {
            "id": "arch_issues_declared",
            "ok": isinstance(arch_issues, list),
            "detail": (
                f"架构问题 {len(arch_issues)} 项"
                if isinstance(arch_issues, list)
                else "缺 arch_issues 字段（无问题也须填空数组）"
            ),
        },
        {
            "id": "verify_flag",
            "ok": settle.get("verified") is True,
            "detail": (
                "verified=true"
                if settle.get("verified") is True
                else "verified 未置 true（未验证经验不得沉淀为结论）"
            ),
        },
    ]
    if run is not None:
        same = str(settle.get("run_id") or "") == str(run.get("run_id") or "")
        checks.append(
            {
                "id": "run_id_consistent",
                "ok": same,
                "detail": (
                    "settle.run_id == run.run_id" if same else "settle.run_id 与 run.json 不一致"
                ),
            }
        )
    return all(c["ok"] for c in checks), checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G5 沉淀门禁")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run.json 路径（读取同目录 settle.json）")
    src.add_argument("--settle", help="settle.json 路径")
    args = ap.parse_args(argv)

    run_path = Path(args.run) if args.run else None
    settle_path = (
        Path(args.settle)
        if args.settle
        else (run_path.parent / "settle.json" if run_path else None)
    )
    if settle_path is None or not settle_path.exists():
        print(
            json.dumps(
                {
                    "gate": "G5",
                    "ok": False,
                    "exit_code": 2,
                    "checks": [
                        {
                            "id": "settle_present",
                            "ok": False,
                            "detail": f"settle.json 不存在：{settle_path}",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 2

    settle = json.loads(settle_path.read_text(encoding="utf-8"))
    run = (
        json.loads(run_path.read_text(encoding="utf-8")) if run_path and run_path.exists() else None
    )
    ok, checks = check(settle, run)
    print(
        json.dumps(
            {
                "gate": "G5",
                "ok": ok,
                "command": f"python3 .trae/skills/dreamos-dev/scripts/g5_check.py --settle {settle_path}",
                "exit_code": 0 if ok else 1,
                "run_id": settle.get("run_id"),
                "checks": checks,
                "reason": "" if ok else "G5 未过：不得关闭 run",
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
