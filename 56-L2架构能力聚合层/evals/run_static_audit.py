# -*- coding: utf-8 -*-
"""run_static_audit.py — 静态总装覆盖矩阵（registry × scenarios）

判定（SPEC §8）:
  AC1  : 18 壳全部出现在覆盖映射；16 个 active 壳每个 ≥1 场景
  AC1b : 每个 active 壳 ≥1 个工具被场景期望覆盖；整体工具触达 ≥70%
  附加 : 注册未覆盖工具清单 / 期望未注册工具清单 / 壳实现缺失清单

输出: evals/out/coverage_matrix.json
用法: python3 evals/run_static_audit.py [--json]
退出码: 0 = AC1 通过；1 = 不通过
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probes import (  # noqa: E402
    DEFAULT_REGISTRY,
    EVALS_DIR,
    OUT_DIR,
    REPO_ROOT,
    load_registry,
)

SCENARIOS_PATH = EVALS_DIR / "scenarios.yaml"
TOOL_COVERAGE_TARGET = 0.70


def _load_scenarios(path: Path = SCENARIOS_PATH) -> Dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _split_pair(pair: str) -> tuple:
    shell, _, tool = pair.partition(":")
    return shell.strip(), tool.strip()


def _load_evidence_hits(path: Path) -> Set[str]:
    """从 evidence.jsonl 读取真实命中的 "shell:tool"（tool_call / tool_sweep）。"""
    hits: Set[str] = set()
    if not path.exists():
        return hits
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") not in ("tool_call", "tool_sweep"):
            continue
        shell, tool = rec.get("shell_id"), rec.get("tool")
        if shell and tool and shell != "?":
            hits.add(f"{shell}:{tool}")
    return hits


def build_matrix(
    registry_path: Path = DEFAULT_REGISTRY,
    evidence_path: Path | None = None,
) -> Dict[str, Any]:
    doc = load_registry(registry_path)
    scen_doc = _load_scenarios()
    scenarios = scen_doc.get("scenarios") or []
    exemptions = {e["shell_id"]: e.get("reason", "") for e in scen_doc.get("exemptions") or []}

    shells: List[Dict[str, Any]] = [s for s in doc.get("shells") or [] if isinstance(s, dict)]
    shell_index = {s["shell_id"]: s for s in shells if s.get("shell_id")}

    # scenario → expected tool pairs
    expected_by_shell: Dict[str, Set[str]] = {}
    expected_pairs: Set[str] = set()
    unregistered_expected: List[Dict[str, str]] = []
    scenario_shells: Dict[str, Set[str]] = {}

    for sc in scenarios:
        sid = sc.get("id", "?")
        scenario_shells[sid] = set()
        for pair in sc.get("expected_tools") or []:
            shell, tool = _split_pair(pair)
            expected_pairs.add(f"{shell}:{tool}")
            expected_by_shell.setdefault(shell, set()).add(tool)
            scenario_shells[sid].add(shell)
            if shell not in shell_index:
                unregistered_expected.append({"scenario_id": sid, "pair": pair})
        for pair in sc.get("expected_write_tools") or []:
            shell, tool = _split_pair(pair)
            expected_pairs.add(f"{shell}:{tool}")
            expected_by_shell.setdefault(shell, set()).add(tool)
            scenario_shells[sid].add(shell)
        for pair in sc.get("expected_unregistered") or []:
            shell, _tool = _split_pair(pair)
            unregistered_expected.append(
                {"scenario_id": sid, "pair": pair, "reason": "已实现未注册（P2 直测）"}
            )
            scenario_shells[sid].add(shell)

    # 壳级覆盖
    shell_rows: List[Dict[str, Any]] = []
    for s in shells:
        sid = s.get("shell_id")
        status = s.get("status", "available")
        tools = [t.get("name") for t in (s.get("tools") or []) if isinstance(t, dict)]
        covered_tools = sorted(set(tools) & expected_by_shell.get(sid, set()))
        row = {
            "shell_id": sid,
            "layer": s.get("layer"),
            "status": status,
            "transport": s.get("transport"),
            "tools_total": len(tools),
            "tools_expected": covered_tools,
            "tools_expected_count": len(covered_tools),
            "tool_coverage": round(len(covered_tools) / len(tools), 3) if tools else 0.0,
            "scenarios": sorted(
                sc.get("id")
                for sc in scenarios
                if sid in (scenario_shells.get(sc.get("id")) or set())
            ),
            "exempt": sid in exemptions,
            "exempt_reason": exemptions.get(sid, ""),
            "shell_path": s.get("shell_path", ""),
            "shell_impl_exists": bool(s.get("shell_path"))
            and (REPO_ROOT / str(s.get("shell_path"))).exists(),
        }
        shell_rows.append(row)

    active_rows = [r for r in shell_rows if r["status"] == "available" and not r["exempt"]]
    deprecated_rows = [r for r in shell_rows if r["status"] == "deprecated"]

    # 工具级整体触达
    all_active_tools = [
        (r["shell_id"], t)
        for r in active_rows
        for t in [tt.get("name") for tt in (shell_index[r["shell_id"]].get("tools") or [])]
        if t
    ]
    evidence_hits = _load_evidence_hits(evidence_path) if evidence_path else set()
    evidence_based = bool(evidence_hits)
    # 有证据 → 以真实命中为准；无证据 → 仅作设计期望参考（不判 AC1b）
    hit_set = (
        evidence_hits
        if evidence_based
        else {f"{sid}:{t}" for sid in expected_by_shell for t in expected_by_shell[sid]}
    )
    hit_tools = [(sid, t) for sid, t in all_active_tools if f"{sid}:{t}" in hit_set]
    tool_ratio = round(len(hit_tools) / len(all_active_tools), 3) if all_active_tools else 0.0

    uncovered_tools = [
        {"shell_id": sid, "tool": t} for sid, t in all_active_tools if f"{sid}:{t}" not in hit_set
    ]

    # 壳实现缺失（非豁免）
    missing_impl = [
        {"shell_id": r["shell_id"], "shell_path": r["shell_path"]}
        for r in active_rows
        if not r["shell_impl_exists"]
    ]

    # AC 判定
    ac1_shells_all_present = all(r["exempt"] or bool(r["scenarios"]) for r in shell_rows)
    ac1_active_covered = all(bool(r["scenarios"]) for r in active_rows)
    # 工具级：以真实证据为准；无证据时 shell 级按设计期望、且 AC1b 记 pending
    active_shell_evidence = {sid for sid, _t in hit_tools}
    ac1b_shell_tool = (
        all(r["shell_id"] in active_shell_evidence for r in active_rows)
        if evidence_based
        else all(r["tools_expected_count"] >= 1 for r in active_rows)
    )
    ac1b_ratio = tool_ratio >= TOOL_COVERAGE_TARGET

    ac1 = ac1_shells_all_present and ac1_active_covered
    if evidence_based:
        ac1b_status = "pass" if (ac1b_shell_tool and ac1b_ratio) else "fail"
    else:
        ac1b_status = "pending"

    return {
        "generated_from": {
            "registry": str(registry_path),
            "scenarios": str(SCENARIOS_PATH),
            "evidence": str(evidence_path) if evidence_path else None,
        },
        "summary": {
            "shells_total": len(shell_rows),
            "shells_active": len(active_rows),
            "shells_deprecated": len(deprecated_rows),
            "shells_exempt": len(exemptions),
            "tools_active": len(all_active_tools),
            "tools_hit": len(hit_tools),
            "tool_coverage_ratio": tool_ratio,
            "tool_coverage_target": TOOL_COVERAGE_TARGET,
            "evidence_based": evidence_based,
            "scenarios_total": len(scenarios),
            "scenarios_sampled": sum(1 for s in scenarios if s.get("sampled")),
            "scenarios_baseline": sum(1 for s in scenarios if s.get("baseline")),
        },
        "shells": shell_rows,
        "uncovered_tools": uncovered_tools,
        "unregistered_expected": unregistered_expected,
        "missing_impl": missing_impl,
        "gates": {
            "AC1": {
                "pass": ac1,
                "shells_all_present": ac1_shells_all_present,
                "active_each_has_scenario": ac1_active_covered,
            },
            "AC1b": {
                "status": ac1b_status,
                "pass": ac1b_status == "pass",
                "each_active_shell_has_tool": ac1b_shell_tool,
                "tool_coverage_ratio_ok": ac1b_ratio,
            },
        },
    }


def _print_report(m: Dict[str, Any]) -> None:
    s = m["summary"]
    print("=" * 78)
    print("静态总装覆盖矩阵")
    print("=" * 78)
    print(
        f"壳: {s['shells_total']}（active {s['shells_active']} / deprecated "
        f"{s['shells_deprecated']} / 豁免 {s['shells_exempt']}）"
    )
    print(
        f"工具: active {s['tools_active']}，期望命中 {s['tools_hit']} → {s['tool_coverage_ratio']:.1%}"
    )
    print(
        f"场景: {s['scenarios_total']}（抽样 {s['scenarios_sampled']} / 基线 {s['scenarios_baseline']}）"
    )
    print("-" * 78)
    print(f"{'shell_id':<26}{'layer':<6}{'tools':<7}{'期望':<5}{'场景':<26}{'状态'}")
    for r in m["shells"]:
        flag = "豁免" if r["exempt"] else ("缺实现" if not r["shell_impl_exists"] else "")
        print(
            f"{r['shell_id']:<26}{r['layer'] or '':<6}"
            f"{r['tools_total']:<7}{r['tools_expected_count']:<5}"
            f"{','.join(r['scenarios']) or '-':<26}{flag}"
        )
    if m["uncovered_tools"]:
        print("-" * 78)
        print(f"未覆盖工具 {len(m['uncovered_tools'])} 个：")
        for u in m["uncovered_tools"]:
            print(f"  - {u['shell_id']}:{u['tool']}")
    if m["unregistered_expected"]:
        print("-" * 78)
        print("期望但未注册：")
        for u in m["unregistered_expected"]:
            print(f"  - {u['scenario_id']} → {u['pair']}")
    if m["missing_impl"]:
        print("-" * 78)
        print("壳实现缺失（非豁免）：")
        for u in m["missing_impl"]:
            print(f"  - {u['shell_id']} → {u['shell_path'] or '(空)'}")
    print("-" * 78)
    for gate, info in m["gates"].items():
        status = str(info.get("status", "pass" if info.get("pass") else "fail")).upper()
        print(f"{gate}: {status}  {info}")
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="仅输出 JSON")
    ap.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="evidence.jsonl 路径；提供则按真实工具命中判定 AC1b",
    )
    args = ap.parse_args()

    matrix = build_matrix(evidence_path=args.evidence)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "coverage_matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(matrix, ensure_ascii=False, indent=2))
    else:
        _print_report(matrix)
        print(f"\n写入: {out_path}")

    if not matrix["gates"]["AC1"]["pass"]:
        return 1
    if matrix["gates"]["AC1b"]["status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
