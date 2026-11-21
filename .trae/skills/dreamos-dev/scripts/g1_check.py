#!/usr/bin/env python3
"""G1 上下文门禁（SPEC §6 / contracts/gates.yaml）。

判定：recall 有记录（recall_ids 非空）且 REA 有快照（snapshot_id 非空）；
任一项可显式声明跳过（skips 字段写明理由），但不允许「静默缺失」。

context.json 契约：
{
  "run_id": "<与 run.json 一致>",
  "recall_ids": ["VM-..."],
  "snapshot_id": "rea_xxx",
  "skips": {"recall": "", "rea": ""},
  "impact": ["path/to/file"]
}

用法：
  python3 .trae/skills/dreamos-dev/scripts/g1_check.py --run .runs/<run_id>/run.json
  python3 .../g1_check.py --context .runs/<run_id>/context.json
输出：单条 JSON 证据，exit 0=通过 1=退回 2=用法/解析错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(ctx: dict, run: dict | None) -> tuple[bool, list[dict]]:
    skips = ctx.get("skips") or {}
    recall_ids = [x for x in (ctx.get("recall_ids") or []) if str(x).strip()]
    snapshot = str(ctx.get("snapshot_id") or "").strip()
    impact = [x for x in (ctx.get("impact") or []) if str(x).strip()]

    checks = [
        {
            "id": "recall_evidence",
            "ok": bool(recall_ids) or bool(str(skips.get("recall") or "").strip()),
            "detail": (
                f"recall_ids={len(recall_ids)}"
                if recall_ids
                else (
                    "已声明跳过：" + str(skips.get("recall"))
                    if skips.get("recall")
                    else "缺 recall 记录且未声明跳过"
                )
            ),
        },
        {
            "id": "rea_evidence",
            "ok": bool(snapshot) or bool(str(skips.get("rea") or "").strip()),
            "detail": (
                f"snapshot_id={snapshot}"
                if snapshot
                else (
                    "已声明跳过：" + str(skips.get("rea"))
                    if skips.get("rea")
                    else "缺 REA snapshot_id 且未声明跳过"
                )
            ),
        },
        {
            "id": "impact_declared",
            "ok": bool(impact),
            "detail": f"影响面 {len(impact)} 项" if impact else "缺影响面（G2/G3 无法判定）",
        },
    ]

    if run is not None:
        same = str(ctx.get("run_id") or "") == str(run.get("run_id") or "")
        checks.append(
            {
                "id": "run_id_consistent",
                "ok": same,
                "detail": (
                    "context.run_id == run.run_id"
                    if same
                    else f"不一致：{ctx.get('run_id')} != {run.get('run_id')}"
                ),
            }
        )

    return all(c["ok"] for c in checks), checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G1 上下文门禁")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run.json 路径（同时校验 context.json 同名）")
    src.add_argument("--context", help="context.json 路径")
    args = ap.parse_args(argv)

    run_path = Path(args.run) if args.run else Path(".runs") / "<unknown>" / "run.json"
    ctx_path = Path(args.context) if args.context else run_path.parent / "context.json"

    if not ctx_path.exists():
        print(
            json.dumps(
                {
                    "gate": "G1",
                    "ok": False,
                    "exit_code": 2,
                    "checks": [
                        {
                            "id": "context_present",
                            "ok": False,
                            "detail": f"context.json 不存在：{ctx_path}",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 2
    ctx = _load(ctx_path)
    run = _load(run_path) if args.run and run_path.exists() else None

    ok, checks = check(ctx, run)
    print(
        json.dumps(
            {
                "gate": "G1",
                "ok": ok,
                "command": f"python3 .trae/skills/dreamos-dev/scripts/g1_check.py --context {ctx_path}",
                "exit_code": 0 if ok else 1,
                "run_id": ctx.get("run_id"),
                "checks": checks,
                "reason": "" if ok else "G1 退回：上下文证据不完整",
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
