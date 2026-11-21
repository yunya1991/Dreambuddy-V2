#!/usr/bin/env python3
"""G4 验收门禁（SPEC §6 / contracts/gates.yaml）。

判定：五维证据齐全，每条必须是 command + exit_code + 关键输出片段；
不适用的维度可显式声明 skip_reason（对齐 G1 的 skips 语义），不允许静默缺失；
已执行证据的 exit_code 必须为 0（非 0 即验收不通过）。

evidence.json 契约：
{
  "run_id": "<与 run.json 一致>",
  "dimensions": [
    {"dimension": "症状复测", "command": "npm run check:contracts", "exit_code": 0, "output": "Tests: 4 passed"},
    {"dimension": "边界", "skip_reason": "本次无业务代码改动"}
  ]
}

维度清单取自 gates.yaml 的 G4.dimensions（规则即数据）。

用法：
  python3 .trae/skills/dreamos-dev/scripts/g4_check.py --run .runs/<run_id>/run.json
  python3 .../g4_check.py --evidence .runs/<run_id>/evidence.json
输出：单条 JSON 证据，exit 0=通过 1=不得宣称完成 2=用法/解析错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
_DEFAULT_DIMENSIONS = ["症状复测", "日志证据", "回归", "影响面", "边界"]


def _dimensions() -> list[str]:
    try:
        import yaml

        gates = yaml.safe_load((CONTRACTS / "gates.yaml").read_text(encoding="utf-8"))
        for gate in gates.get("gates", []):
            if gate.get("id") == "G4":
                dims = [str(d) for d in (gate.get("dimensions") or [])]
                if dims:
                    return dims
    except Exception:
        pass
    return list(_DEFAULT_DIMENSIONS)


def _norm(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in items:
        if isinstance(item, dict) and str(item.get("dimension") or "").strip():
            out[str(item["dimension"]).strip()] = item
    return out


def check(evidence: dict, required: list[str], run: dict | None) -> tuple[bool, list[dict]]:
    by_dim = _norm(evidence.get("dimensions") or [])
    checks: list[dict] = []

    for dim in required:
        item = by_dim.get(dim)
        if item is None:
            checks.append({"id": f"dim:{dim}", "ok": False, "detail": "缺该维度证据且未声明跳过"})
            continue
        skip = str(item.get("skip_reason") or "").strip()
        if skip:
            checks.append({"id": f"dim:{dim}", "ok": True, "detail": f"已声明不适用：{skip}"})
            continue
        cmd = str(item.get("command") or "").strip()
        exit_code = item.get("exit_code")
        output = str(item.get("output") or "").strip()
        problems = []
        if not cmd:
            problems.append("缺 command")
        if not isinstance(exit_code, int):
            problems.append("缺 exit_code（整数）")
        elif exit_code != 0:
            problems.append(f"exit_code={exit_code}（非 0 即不通过）")
        if not output:
            problems.append("缺关键输出片段")
        checks.append(
            {
                "id": f"dim:{dim}",
                "ok": not problems,
                "detail": f"`{cmd}` exit={exit_code}" if not problems else "；".join(problems),
            }
        )

    if run is not None:
        same = str(evidence.get("run_id") or "") == str(run.get("run_id") or "")
        checks.append(
            {
                "id": "run_id_consistent",
                "ok": same,
                "detail": (
                    "evidence.run_id == run.run_id"
                    if same
                    else f"不一致：{evidence.get('run_id')} != {run.get('run_id')}"
                ),
            }
        )

    return all(c["ok"] for c in checks), checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G4 验收门禁")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run.json 路径（读取同目录 evidence.json）")
    src.add_argument("--evidence", help="evidence.json 路径")
    args = ap.parse_args(argv)

    run_path = Path(args.run) if args.run else None
    ev_path = (
        Path(args.evidence)
        if args.evidence
        else (run_path.parent / "evidence.json" if run_path else None)
    )
    if ev_path is None or not ev_path.exists():
        print(
            json.dumps(
                {
                    "gate": "G4",
                    "ok": False,
                    "exit_code": 2,
                    "checks": [
                        {
                            "id": "evidence_present",
                            "ok": False,
                            "detail": f"evidence.json 不存在：{ev_path}",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 2

    evidence = json.loads(ev_path.read_text(encoding="utf-8"))
    run = (
        json.loads(run_path.read_text(encoding="utf-8")) if run_path and run_path.exists() else None
    )
    required = _dimensions()
    ok, checks = check(evidence, required, run)

    print(
        json.dumps(
            {
                "gate": "G4",
                "ok": ok,
                "command": f"python3 .trae/skills/dreamos-dev/scripts/g4_check.py --evidence {ev_path}",
                "exit_code": 0 if ok else 1,
                "run_id": evidence.get("run_id"),
                "dimensions": required,
                "checks": checks,
                "reason": "" if ok else "G4 未过：验收证据不齐全，不得宣称完成",
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
