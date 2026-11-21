#!/usr/bin/env python3
"""G2 计划门禁（SPEC §6 / contracts/gates.yaml）。

判定：plan.md 必须包含 gates.yaml 里 G2.required_sections 的全部章节，且每节有实质内容。
「复用盘点」是硬要求：逐级核对 SPEC A-C 条款 → 现有 SKILL → L0 壳，并写明为何不能复用。

用法：
  python3 .trae/skills/dreamos-dev/scripts/g2_check.py --run .runs/<run_id>/run.json
  python3 .../g2_check.py --plan .runs/<run_id>/plan.md
输出：单条 JSON 证据，exit 0=通过 1=退回重规划 2=用法错误。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$")


def _required_sections() -> list[str]:
    import yaml

    gates = yaml.safe_load((CONTRACTS / "gates.yaml").read_text(encoding="utf-8"))
    for gate in gates.get("gates", []):
        if gate.get("id") == "G2":
            return list(gate.get("required_sections") or [])
    return []


def _parse_sections(text: str) -> dict[str, str]:
    """标题 → 该节正文（到下一个同级或更高级标题为止）。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            current = match.group(2).strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def check(text: str, required: list[str]) -> tuple[bool, list[dict]]:
    sections = _parse_sections(text)
    checks: list[dict] = []
    for name in required:
        hit = [body for title, body in sections.items() if name.lower() in title.lower()]
        if not hit:
            checks.append({"id": f"section:{name}", "ok": False, "detail": f"缺章节「{name}」"})
            continue
        filled = any(len(body) >= 10 for body in hit)
        checks.append(
            {
                "id": f"section:{name}",
                "ok": filled,
                "detail": "已填写" if filled else f"章节「{name}」存在但内容为空/过短（<10 字符）",
            }
        )
    return all(c["ok"] for c in checks), checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="G2 计划门禁")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run.json 路径（读取同目录 plan.md）")
    src.add_argument("--plan", help="plan.md 路径")
    args = ap.parse_args(argv)

    plan_path = Path(args.plan) if args.plan else Path(args.run).parent / "plan.md"
    if not plan_path.exists():
        print(
            json.dumps(
                {
                    "gate": "G2",
                    "ok": False,
                    "exit_code": 2,
                    "checks": [
                        {
                            "id": "plan_present",
                            "ok": False,
                            "detail": f"plan.md 不存在：{plan_path}",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 2

    required = _required_sections()
    if not required:
        print(
            json.dumps(
                {
                    "gate": "G2",
                    "ok": False,
                    "exit_code": 2,
                    "checks": [
                        {
                            "id": "contract",
                            "ok": False,
                            "detail": "gates.yaml 未定义 G2.required_sections",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
        return 2

    ok, checks = check(plan_path.read_text(encoding="utf-8"), required)
    print(
        json.dumps(
            {
                "gate": "G2",
                "ok": ok,
                "command": f"python3 .trae/skills/dreamos-dev/scripts/g2_check.py --plan {plan_path}",
                "exit_code": 0 if ok else 1,
                "required_sections": required,
                "checks": checks,
                "reason": "" if ok else "G2 退回：计划缺章节或复用盘点未填",
            },
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
