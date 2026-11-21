# -*- coding: utf-8 -*-
"""run_all.py — 一条命令跑全量并给出 AC1-AC7 自验收

顺序: 静态 → 抽样实跑 → 静态(带证据) → DeepSeek 基线 → 验收汇总
产物: evals/out/acceptance.json
用法: python3 evals/run_all.py [--skip-smoke] [--skip-baseline]
退出码: 0 = 全部 AC 通过或仅剩「已知缺口」项；1 = 出现 fail
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probes import EVALS_DIR, OUT_DIR  # noqa: E402

PY = sys.executable
EVIDENCE = OUT_DIR / "evidence.jsonl"
MATRIX = OUT_DIR / "coverage_matrix.json"
COMPARISON = OUT_DIR / "baseline_comparison.json"
REPORT = EVALS_DIR.parent / "docs" / "ASSESSMENT-20261118-架构总装与调度能力评测-v0.1.md"


def _run(cmd: List[str], timeout: int = 1800) -> Dict[str, Any]:
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return {
        "cmd": " ".join(cmd),
        "code": proc.returncode,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "stdout_tail": proc.stdout[-1500:],
        "stderr_tail": proc.stderr[-800:],
    }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _evidence() -> List[Dict[str, Any]]:
    if not EVIDENCE.exists():
        return []
    return [json.loads(x) for x in EVIDENCE.read_text(encoding="utf-8").splitlines() if x.strip()]


def evaluate_acceptance() -> Dict[str, Any]:
    matrix = _load_json(MATRIX)
    ev = _evidence()
    comp = _load_json(COMPARISON)

    scenario_rows = [r for r in ev if r.get("kind") == "scenario"]
    # 仅 phase_p1b 产出的场景记录参与 AC2（faults 的 P1b 记录无期望命中断言）
    p1b = [
        r
        for r in scenario_rows
        if r.get("entry") == "P1b"
        and any(a.get("name") == "expected_tools_hit_rate>=0.8" for a in r.get("assertions") or [])
    ]
    p1 = [r for r in scenario_rows if r.get("entry") == "P1"]
    p3 = [r for r in scenario_rows if r.get("entry") == "P3"]

    # AC2
    ac2_trace = all(bool(r.get("trace_id")) for r in p1b)
    hit_rates = [
        a.get("value")
        for r in p1b
        for a in (r.get("assertions") or [])
        if a.get("name") == "expected_tools_hit_rate>=0.8"
    ]
    ac2_hit = bool(hit_rates) and all((v or 0) >= 0.8 for v in hit_rates)
    ac2_business = all(
        any(
            a.get("name") == "at_least_one_business_tool" and a.get("pass")
            for a in r.get("assertions") or []
        )
        for r in p1b
    )

    # AC3
    sweep = [r for r in ev if r.get("kind") == "shell_sweep"]
    p2_available = len({r["shell_id"] for r in sweep if r.get("ok")})
    p1_answered = len(
        [
            r
            for r in p1
            if any(
                a.get("name") == "p1_answered" and a.get("pass") for a in r.get("assertions") or []
            )
        ]
    )

    # AC4: G 四分流
    sediments: List[str] = []
    for r in p3:
        for s in r.get("sediments") or []:
            if isinstance(s, dict) and s.get("type"):
                sediments.append(str(s["type"]))
            elif isinstance(s, str):
                sediments.append(s)
    sed_types = set(sediments)
    ac4 = {"case", "skill", "doc"}.issubset(sed_types)

    # AC5
    mandate = any(
        any(
            a.get("name") == "deny_without_mandate" and a.get("pass")
            for a in r.get("assertions") or []
        )
        for r in scenario_rows
        if r.get("scenario_id") == "S16"
    )
    degraded_no_fabricate = any(
        r.get("fault") == "timeout" and all(a.get("pass") for a in r.get("assertions") or [])
        for r in scenario_rows
    )
    redo = any(r.get("c_layer_redo") for r in p3)
    ac5 = {
        "mandate_deny": mandate,
        "degraded_no_fabrication": degraded_no_fabricate,
        "c_layer_redo": redo,
    }

    # AC5b
    allow_write = any(
        r.get("scenario_id") == "S16" and r.get("write_landed") for r in scenario_rows
    )

    # AC6
    ac6 = COMPARISON.exists() and comp.get("ok") and len(comp.get("rows") or []) >= 8

    # AC7
    static_gate = _load_json(OUT_DIR / "acceptance.json").get("steps", {})
    ac7 = bool(static_gate.get("static", {}).get("elapsed_s", 999) < 60)

    gates = {
        "AC1": {
            "status": "pass" if matrix.get("gates", {}).get("AC1", {}).get("pass") else "fail",
            "detail": matrix.get("gates", {}).get("AC1"),
        },
        "AC1b": {
            "status": matrix.get("gates", {}).get("AC1b", {}).get("status", "fail"),
            "detail": matrix.get("gates", {}).get("AC1b"),
            "tool_coverage_ratio": matrix.get("summary", {}).get("tool_coverage_ratio"),
        },
        "AC2": {
            "status": (
                "pass" if (len(p1b) >= 8 and ac2_trace and ac2_hit and ac2_business) else "fail"
            ),
            "detail": {
                "sampled": len(p1b),
                "trace_id_all": ac2_trace,
                "expected_hit_rate_ok": ac2_hit,
                "business_tool_all": ac2_business,
            },
        },
        "AC3": {
            "status": "partial",
            "detail": {
                "p2_available_shells": p2_available,
                "p1_answered": p1_answered,
                "p1_shell_touch": "unverified: 产品链工具调用在 Node/DSH 进程内，Python 探针不可见（D-1/D-6）",
            },
        },
        "AC4": {
            "status": "pass" if ac4 else "fail",
            "detail": {"sediment_types": sorted(sed_types)},
        },
        "AC5": {
            "status": (
                "partial"
                if (mandate and degraded_no_fabricate and not redo)
                else ("pass" if (mandate and degraded_no_fabricate) else "fail")
            ),
            "detail": ac5,
        },
        "AC5b": {
            "status": "pass" if allow_write else "fail",
            "detail": {"write_landed": allow_write},
        },
        "AC6": {
            "status": "pass" if ac6 else "fail",
            "detail": {"rows": len(comp.get("rows") or []), "calls": comp.get("deepseek_calls")},
        },
        "AC7": {
            "status": "pass" if ac7 else "fail",
            "detail": {"static_under_60s": ac7},
        },
    }
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "gates": gates,
        "failed": [k for k, v in gates.items() if v["status"] == "fail"],
        "partial": [k for k, v in gates.items() if v["status"] == "partial"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument("--skip-baseline", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    steps: Dict[str, Any] = {}
    acc_path = OUT_DIR / "acceptance.json"
    (acc_path).write_text(json.dumps({"steps": steps}, ensure_ascii=False), encoding="utf-8")

    print("[1/4] 静态覆盖矩阵 ...")
    steps["static"] = _run([PY, str(EVALS_DIR / "run_static_audit.py")])
    print(f"  exit={steps['static']['code']} {steps['static']['elapsed_s']}s")
    acc_path.write_text(
        json.dumps({"steps": steps}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not args.skip_smoke:
        print("[2/4] 抽样实跑（sweep + p1 + p1b + p3 + faults）...")
        steps["smoke"] = _run([PY, str(EVALS_DIR / "run_smoke.py")])
        print(f"  exit={steps['smoke']['code']} {steps['smoke']['elapsed_s']}s")
        acc_path.write_text(
            json.dumps({"steps": steps}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print("[3/4] 静态覆盖矩阵（带证据）...")
        steps["static_with_evidence"] = _run(
            [PY, str(EVALS_DIR / "run_static_audit.py"), "--evidence", str(EVIDENCE)]
        )
        print(
            f"  exit={steps['static_with_evidence']['code']} {steps['static_with_evidence']['elapsed_s']}s"
        )
        acc_path.write_text(
            json.dumps({"steps": steps}, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if not args.skip_baseline:
        print("[4/4] DeepSeek 基线 ...")
        steps["baseline"] = _run([PY, str(EVALS_DIR / "run_baseline.py"), "--max-calls", "40"])
        print(f"  exit={steps['baseline']['code']} {steps['baseline']['elapsed_s']}s")

    acceptance = evaluate_acceptance()
    acceptance["steps"] = steps
    acc_path.write_text(json.dumps(acceptance, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    for k, v in acceptance["gates"].items():
        print(
            f"{k:<6} {v['status'].upper():<8} {json.dumps(v.get('detail'), ensure_ascii=False)[:120]}"
        )
    print("=" * 60)
    print(f"写入: {acc_path}")
    return 1 if acceptance["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
