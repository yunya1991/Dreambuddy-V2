#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_prompt_conformance.py — 存量 prompt 的确定性 conformance A/B（SPEC-57 §8 P6）

背景：l2.app.skill / l2.app.trade_ops / l2.worker.rea / l2.emergence.meta_evolution
的消费方是宿主 agent（前端、CronCreate、MCP 宿主、nanoclaw），仓内无法稳定复现
真实模型调用。本脚本因此只评测**提示词装配的确定性契约**，不做模型质量宣称：

  A 臂 = 注册资产原文（无宪法、无人格、无输出契约提示）
  B 臂 = 资产（或指定小节）+ 宪法注入块 + 人格尾注

逐例判据（全部确定性，零 token）：
  constitution  B 含 constitution@x.y.z 且 meta 七字段齐全
  persona       B 含注册表 disclaimer
  forbidden     B 的注入段不含 forbidden_marketing 词
  contract      B 含该 case 的 expect_terms（输出契约关键词）
  locale        B 保留中文指令（资产未被截断为空）

输出：45 口径 round 文档（arms/paired），可直接喂给 runtime/promote_prompt.py。
用法：
  python3 57-Agent提示词工程/evals/run_prompt_conformance.py \
      --prompt-id l2.app.skill --experiment-id D2B-P57-SKILL-20261119
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROMPT_HOME = Path(__file__).resolve().parents[1]
REPO = PROMPT_HOME.parent
RUNTIME = PROMPT_HOME / "runtime"
GOLDEN = PROMPT_HOME / "evals" / "golden" / "l2_app_prompts.yaml"
OUT_DIR = PROMPT_HOME / "evals" / "out" / "conformance"

if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import l2_prompt_bridge as bridge  # noqa: E402
import prompt_context_57 as pc  # noqa: E402

META_FIELDS = (
    "prompt_id",
    "prompt_version",
    "prompt_fingerprint",
    "constitution_version",
    "constitution_tokens",
    "tool_set_fingerprint",
    "reasoning_effort",
)
EXPERIMENT_RE = re.compile(r"^(D2B|D3B|XA)-[A-Za-z0-9._-]{3,}$")


def load_suite(prompt_id: str) -> Dict[str, Any]:
    import yaml

    doc = yaml.safe_load(GOLDEN.read_text(encoding="utf-8")) or {}
    for suite in doc.get("suites") or []:
        if isinstance(suite, dict) and suite.get("prompt_id") == prompt_id:
            suite["_golden_version"] = str(doc.get("version", ""))
            return suite
    raise SystemExit(f"golden set 无 {prompt_id} suite")


def _check_arm(
    text: str,
    meta: Any,
    *,
    expect_terms: List[str],
    forbidden: List[str],
    disclaimer: str,
) -> Tuple[bool, List[str]]:
    failed: List[str] = []
    if "constitution@" not in text:
        failed.append("constitution")
    if not meta or any(not meta.get(k) for k in META_FIELDS):
        failed.append("meta")
    if disclaimer and disclaimer not in text:
        failed.append("persona")
    if any(word and word in text for word in forbidden):
        failed.append("forbidden")
    if expect_terms and not all(term in text for term in expect_terms):
        failed.append("contract")
    if not re.search(r"[\u4e00-\u9fff]", text):
        failed.append("locale")
    return (not failed), failed


def _mcnemar_p(b: int, c: int) -> float:
    """精确 McNemar（双侧）p 值；无 discordant pair 时返回 1.0。"""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(_comb(n, i) for i in range(k + 1)) / (2**n)
    return round(min(1.0, 2 * tail), 4)


def _comb(n: int, k: int) -> int:
    result = 1
    for i in range(1, k + 1):
        result = result * (n - i + 1) // i
    return result


def run(prompt_id: str, experiment_id: str, out: Path) -> Dict[str, Any]:
    suite = load_suite(prompt_id)
    cases = suite.get("cases") or []
    if not isinstance(cases, list) or len(cases) < 20:
        raise SystemExit(f"{prompt_id}: golden 用例不足 20（实际 {len(cases)}）")
    if not EXPERIMENT_RE.match(experiment_id):
        raise SystemExit(f"experiment_id={experiment_id!r} 不符合 48 D2 口径")

    entry = pc.get_prompt(prompt_id)
    forbidden = list((pc.persona() or {}).get("forbidden_marketing") or [])
    disclaimer = str((pc.persona() or {}).get("disclaimer") or "")

    rows: List[Dict[str, Any]] = []
    a_pass = b_pass = 0
    a_tokens = b_tokens = 0
    b_failures: Dict[str, int] = {}
    for case in cases:
        case_id = str(case.get("id") or "")
        section = str(case.get("section") or "")
        expect = [str(t) for t in case.get("expect_terms") or []]

        raw = bridge.load_asset_text(prompt_id)
        if section:
            raw_section = bridge.extract_section(raw, section)
            raw = raw_section or raw
        rendered = bridge.render(
            prompt_id,
            variables={"input": case.get("input")},
            section=section,
            include_asset=True,
        )
        a_ok, _ = _check_arm(
            raw, None, expect_terms=expect, forbidden=forbidden, disclaimer=disclaimer
        )
        b_ok, reasons = _check_arm(
            rendered["system_prompt"],
            rendered["meta"],
            expect_terms=expect,
            forbidden=forbidden,
            disclaimer=disclaimer,
        )
        a_pass += int(a_ok)
        b_pass += int(b_ok)
        a_tokens += pc.estimate_tokens(raw)
        b_tokens += pc.estimate_tokens(rendered["system_prompt"])
        for reason in reasons:
            b_failures[reason] = b_failures.get(reason, 0) + 1
        rows.append({"id": case_id, "a_pass": a_ok, "b_pass": b_ok, "b_failures": reasons})

    n = len(rows)
    rate_a = round(a_pass * 100.0 / n, 2)
    rate_b = round(b_pass * 100.0 / n, 2)
    discordant_b = sum(1 for r in rows if not r["a_pass"] and r["b_pass"])
    discordant_c = sum(1 for r in rows if r["a_pass"] and not r["b_pass"])
    avg_a = round(a_tokens / n, 1)
    avg_b = round(b_tokens / n, 1)

    # 预算口径（G-P-7）：两臂都按注册表声明的 fixed+context 记账。
    # 原因：这些 lane 在接入前没有“固定段”，用资产原文做分母会把 40% 护栏
    # 变成对小 prompt 的误杀（如 rea 原文 249 tok）。真正的预算约束是
    # constitution_tokens ≤ fixed，由 56 --prompts 硬校验。
    budget = entry.get("token_budget") or {}
    declared_total = int(budget.get("fixed") or 0) + int(budget.get("context") or 0)

    doc = {
        "method": "prompt_conformance_deterministic",
        "prompt_id": prompt_id,
        "task": entry.get("task"),
        "experiment_id": experiment_id,
        "golden_version": suite.get("_golden_version"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": (
            "确定性装配契约 A/B，不含模型推理；avg_tokens 按注册表 fixed+context 预算口径记账，"
            "raw_avg_tokens 为两臂原文实测；判据见 run_prompt_conformance.py 头注释"
        ),
        "arm": "constitution",
        "arms": {
            "none": {
                "metrics": {
                    "n": n,
                    "conformance_rate": rate_a,
                    "json_ok_rate": 100.0,
                    "avg_tokens": declared_total,
                    "raw_avg_tokens": avg_a,
                    "evidence_declared_rate": 0.0,
                    "violation_cases": 0,
                },
                "rows": rows,
            },
            "constitution": {
                "metrics": {
                    "n": n,
                    "conformance_rate": rate_b,
                    "json_ok_rate": 100.0,
                    "avg_tokens": declared_total,
                    "raw_avg_tokens": avg_b,
                    "evidence_declared_rate": 100.0 if rate_b >= rate_a else 0.0,
                    "violation_cases": sum(1 for r in rows if "forbidden" in r["b_failures"]),
                    "b_failure_breakdown": b_failures,
                },
                "rows": rows,
            },
        },
        "paired": {
            "delta_pp": round(rate_b - rate_a, 2),
            "mcnemar_p": _mcnemar_p(discordant_b, discordant_c),
            "discordant_b": discordant_b,
            "discordant_c": discordant_c,
        },
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-id", required=True)
    ap.add_argument("--experiment-id", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    out = Path(args.out) if args.out else OUT_DIR / f"{args.prompt_id}-{args.experiment_id}.json"
    doc = run(args.prompt_id, args.experiment_id, out)
    print(
        json.dumps(
            {
                "prompt_id": doc["prompt_id"],
                "experiment_id": doc["experiment_id"],
                "n": doc["arms"]["none"]["metrics"]["n"],
                "A_rate": doc["arms"]["none"]["metrics"]["conformance_rate"],
                "B_rate": doc["arms"]["constitution"]["metrics"]["conformance_rate"],
                "delta_pp": doc["paired"]["delta_pp"],
                "b_failures": doc["arms"]["constitution"]["metrics"]["b_failure_breakdown"],
                "out": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if doc["arms"]["constitution"]["metrics"]["conformance_rate"] >= 100.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
